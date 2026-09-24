import base64
import hashlib
import secrets
import time
from functools import partial
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import redirect
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.auth.exceptions import GoogleAuthError
from google.oauth2 import id_token

from .google_api import (
    AUTHORIZATION_URL, HTTP_TIMEOUT, IDENTITY_SCOPES, SCOPES, SEND_SCOPE, CONTACTS_SCOPE, TOKEN_URL, decrypt_credentials,
    encrypt_credentials, oauth_configured, subject_hash, token_values,
)
from .models import AuditEvent, GoogleCredential, Membership, Workspace, SenderAccount
from .services import require_executive

SESSION_KEY = "google_oauth"
FLOW_TTL_SECONDS = 600


@login_required
@never_cache
@require_POST
def google_sender(request):
    require_executive(request.user)
    return _begin_google(request, mode='sender')


def _connect_sender(request, claims, email, token_response):
    member = require_executive(request.user)
    if email.casefold() == request.user.email.casefold():
        raise ValueError('Use the primary account connection for this address.')
    with transaction.atomic():
        record = SenderAccount.objects.filter(workspace=member.workspace, subject_hash=subject_hash(claims['sub'])).first()
        previous = {}
        if record:
            if record.email.casefold() != email.casefold():
                raise ValueError('The sender identity changed.')
            try:
                previous = decrypt_credentials(record)
            except ValueError:
                pass
        data = token_values(token_response, previous=previous, required_scopes=(SEND_SCOPE,))
        if not data.get('refresh_token'):
            raise ValueError('Offline sending permission is required.')
        data.update(sub=claims['sub'], email=email)
        SenderAccount.objects.update_or_create(workspace=member.workspace, subject_hash=subject_hash(claims['sub']),
            defaults={'email': email, 'encrypted_data': encrypt_credentials(data), 'connected': True})
        AuditEvent.objects.create(workspace=member.workspace, actor=request.user, action='sender.connected', detail=email)
    return request.user


@login_required
@never_cache
@require_GET
def google_contacts(request):
    require_executive(request.user)
    return _begin_google(request, mode="contacts")


@never_cache
@require_GET
def google_signin(request):
    """Executive sign-in: identify the account before requesting mailbox access."""
    if request.user.is_authenticated:
        require_executive(request.user)
        return _begin_google(request, mode="send")
    return _begin_google(request, mode="auto")


@never_cache
@require_GET
def google_login(request):
    if request.user.is_authenticated:
        require_executive(request.user)
        return _begin_google(request, mode="send")
    # Bookmarked legacy login URLs use the same identity-first public flow.
    return _begin_google(request, mode="auto")


@never_cache
@require_GET
def google_identity_login(request):
    """Keep the legacy identity URL available to executives only."""
    if request.user.is_authenticated:
        require_executive(request.user)
    return _begin_google(request, mode="identity")


def _begin_google(request, *, mode, expected_identity=None):
    if request.user.is_authenticated:
        require_executive(request.user)
    if not oauth_configured():
        messages.error(request, "Google sign-in is not configured. Use your MailSend login or ask the administrator to configure Google OAuth.")
        return redirect("mail:dashboard" if request.user.is_authenticated else "mail:login")
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    request.session[SESSION_KEY] = {
        "state": state, "nonce": nonce, "verifier": verifier,
        "started_at": time.time(), "user_id": request.user.pk if request.user.is_authenticated else None,
        "mode": mode,
    }
    if expected_identity is not None:
        request.session[SESSION_KEY]["expected_identity"] = expected_identity
        request.session.modified = True
    identity_only = mode in ("identity", "auto")
    requested_scopes = (*IDENTITY_SCOPES, SEND_SCOPE) if mode == 'sender' else SCOPES
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code", "scope": " ".join(IDENTITY_SCOPES if identity_only else requested_scopes),
        "state": state, "nonce": nonce,
        "prompt": "select_account" if identity_only else "consent",
        "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("="),
        "code_challenge_method": "S256",
    }
    if not identity_only:
        # SCOPES includes identity, sending and read-only contacts. Do not merge unrelated
        # permissions previously granted to this Google project.
        params.update(access_type="offline", include_granted_scopes="false")
    if expected_identity is not None:
        params["login_hint"] = expected_identity["sub"]
    elif request.user.is_authenticated and mode != 'sender':
        params["login_hint"] = request.user.email
    if mode == 'sender':
        params['prompt'] = 'consent select_account'
    return redirect(AUTHORIZATION_URL + "?" + urlencode(params))


def _validate_claims(claims, nonce):
    if not isinstance(claims, dict) or claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise ValueError("Invalid Google issuer")
    if claims.get("email_verified") is not True:
        raise ValueError("Google has not verified this email address")
    if not isinstance(claims.get("nonce"), str) or not constant_time_compare(claims["nonce"], nonce):
        raise ValueError("Invalid Google nonce")
    if not isinstance(claims.get("sub"), str) or not claims["sub"] or len(claims["sub"]) > 255:
        raise ValueError("Invalid Google identity")
    email = claims.get("email")
    if not isinstance(email, str) or len(email) > 254:
        raise ValueError("Invalid Google email")
    validate_email(email)
    return email.lower()


def _previous_identity(credential, claims, email):
    """Recover tokens only after the stable, independently verified identity matches."""
    if credential.subject_hash != subject_hash(claims["sub"]) or credential.user.email.casefold() != email.casefold():
        raise ValueError("The Google identity does not match its linked MailSend account.")
    try:
        previous = decrypt_credentials(credential)
    except ValueError:
        # Key rotation or damaged token ciphertext should not lock out an owner
        # whose signed Google subject still matches the persisted identity hash.
        return {}
    if previous.get("sub") != claims["sub"] or previous.get("email", "").casefold() != email.casefold():
        raise ValueError("The Google identity no longer matches its MailSend account.")
    return previous


def _local_account_uses_identity(email):
    # A worker username may look like an email even though workers do not need
    # an Email field. Never reinterpret that username as a new executive.
    return get_user_model().objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists()


def _connect_identity(request, claims, email, token_response, *, mode="send", expected_identity=None):
    User = get_user_model()
    hashed_subject = subject_hash(claims["sub"])
    with transaction.atomic():
        credential = GoogleCredential.objects.select_related("user").filter(subject_hash=hashed_subject).first()
        if expected_identity is not None:
            # login_hint is only a Google UI hint. Bind the second grant to
            # both the first verified identity and its original local account.
            if (not constant_time_compare(claims["sub"], expected_identity["sub"])
                    or email.casefold() != expected_identity["email"].casefold()
                    or (credential.user_id if credential else None) != expected_identity["user_id"]):
                raise ValueError("The Google account changed during sign-in. Start again.")
        previous = {}
        if request.user.is_authenticated:
            user = request.user
            member = require_executive(user)
            if user.email.casefold() != email.casefold():
                raise ValueError("Connect the Google account matching your MailSend email address.")
            if credential and credential.user_id != user.pk:
                raise ValueError("This Google account is already linked to a different MailSend account.")
            existing = GoogleCredential.objects.filter(user=user).first()
            if existing:
                previous = _previous_identity(existing, claims, email)
                credential = existing
        elif credential:
            user = credential.user
            member = require_executive(user)
            previous = _previous_identity(credential, claims, email)
        else:
            # Email alone is not proof of ownership of an existing local account.
            if _local_account_uses_identity(email):
                raise ValueError("An existing MailSend account uses this email or username. Sign in with its assigned username and password.")
            if mode == "identity":
                raise ValueError("Start executive Google sign-in from the login page.")
            name = str(claims.get("given_name") or "")[:150]
            user = User.objects.create_user(username="google_" + secrets.token_hex(16), email=email, first_name=name)
            workspace = Workspace.objects.create(name=(f"{name}'s workspace" if name else "My workspace")[:160], executive=user)
            member = Membership.objects.create(user=user, workspace=workspace, role=Membership.Role.EXECUTIVE)
        if mode == "identity":
            # The signed ID token proves login identity. Discard any API tokens
            # returned by Google and leave existing executive grants untouched.
            if not credential:
                GoogleCredential.objects.create(user=user, encrypted_data=encrypt_credentials({"sub": claims["sub"], "email": email}), subject_hash=hashed_subject, connected=False)
            AuditEvent.objects.create(workspace=member.workspace, actor=user, action="google.identity_linked")
        else:
            required = {SEND_SCOPE, CONTACTS_SCOPE}
            data = token_values(token_response, previous=previous, required_scopes=required)
            if expected_identity is not None and not data.get("refresh_token"):
                raise ValueError("Google did not grant offline sending access. Start again.")
            data.update(sub=claims["sub"], email=email)
            GoogleCredential.objects.update_or_create(user=user, defaults={"encrypted_data": encrypt_credentials(data), "subject_hash": hashed_subject, "connected": True})
            AuditEvent.objects.create(workspace=member.workspace, actor=user, action="google.connected")
    return user


def _identify_for_signin(request, claims, email):
    """Return a linked user, or an identity-pinned executive consent redirect."""
    credential = GoogleCredential.objects.select_related("user").filter(subject_hash=subject_hash(claims["sub"])).first()
    if credential:
        require_executive(credential.user)
        previous = _previous_identity(credential, claims, email)
        if (credential.connected and previous.get("refresh_token")
                and {SEND_SCOPE, CONTACTS_SCOPE}.issubset(str(previous.get("scope", "")).split())):
            return _connect_identity(request, claims, email, {}, mode="identity"), None
    elif _local_account_uses_identity(email):
        raise ValueError("Sign in with your assigned username and password. Google sign-in is for executives only.")
    # No account, role, credentials or workspace is created until this second
    # grant completes. Reusing the first ID token cannot complete this step.
    expected_identity = {"sub": claims["sub"], "email": email,
                         "user_id": credential.user_id if credential else None}
    return None, _begin_google(request, mode="send", expected_identity=expected_identity)


@never_cache
@require_GET
def google_callback(request):
    flow = request.session.pop(SESSION_KEY, None)
    destination = "mail:dashboard" if request.user.is_authenticated else "mail:login"
    try:
        if not isinstance(flow, dict) or not isinstance(flow.get("state"), str) or not constant_time_compare(request.GET.get("state", ""), flow["state"]):
            raise ValueError("Google sign-in expired or its security check failed. Start again.")
        elapsed = time.time() - float(flow.get("started_at", 0))
        if elapsed < 0 or elapsed > FLOW_TTL_SECONDS:
            raise ValueError("Google sign-in expired. Start again.")
        current_user_id = request.user.pk if request.user.is_authenticated else None
        if flow.get("user_id") != current_user_id:
            raise ValueError("The signed-in account changed during Google sign-in. Start again.")
        if request.user.is_authenticated:
            require_executive(request.user)
        mode = flow.get("mode", "send")
        if mode not in ("send", "identity", "auto", "contacts", "sender"):
            raise ValueError("Invalid Google sign-in flow. Start again.")
        if mode in ('contacts', 'sender') and not request.user.is_authenticated:
            raise ValueError('Sign in as executive before connecting contacts.')
        if request.GET.get("error"):
            raise ValueError("Google sign-in was cancelled or permission was not granted.")
        code = request.GET.get("code", "")
        if not code or not oauth_configured():
            raise ValueError("Google sign-in could not be completed. Start again.")
        response = requests.post(TOKEN_URL, data={
            "client_id": settings.GOOGLE_CLIENT_ID, "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI, "grant_type": "authorization_code",
            "code": code, "code_verifier": flow["verifier"],
        }, timeout=HTTP_TIMEOUT, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError("Google could not complete sign-in. Start again.")
        token_response = response.json()
        if not isinstance(token_response, dict) or not token_response.get("id_token"):
            raise ValueError("Google did not return a verified identity. Start again.")
        claims = id_token.verify_oauth2_token(token_response["id_token"], partial(GoogleAuthRequest(), timeout=15), audience=settings.GOOGLE_CLIENT_ID)
        email = _validate_claims(claims, flow["nonce"])
        if mode == 'sender':
            user = _connect_sender(request, claims, email, token_response)
        elif mode == "auto":
            user, continuation = _identify_for_signin(request, claims, email)
            if continuation is not None:
                return continuation
        else:
            user = _connect_identity(request, claims, email, token_response, mode=mode,
                                     expected_identity=flow.get("expected_identity"))
    except (ValueError, TypeError, KeyError, ValidationError, ImproperlyConfigured, IntegrityError, PermissionDenied, requests.RequestException, GoogleAuthError):
        # Neither tokens nor Google's raw error response are shown to a user.
        if isinstance(flow, dict) and flow.get('mode') == 'sender' and request.user.is_authenticated:
            messages.error(request, 'Sender connection failed. Choose an additional Google account and grant sending access. Your primary account is managed through its existing connection. Start again if consent expired or was cancelled.')
            return redirect('mail:senders')
        messages.error(request, "Google sign-in could not be completed. Google sign-in is for executives only; assistants must use their assigned username and password. Executives should choose the matching Google account and grant the requested permissions. If you already have a local executive account, sign in with its password before connecting Google.")
        return redirect(destination)
    if mode == 'sender':
        messages.success(request, 'Sender connected. Workers can now choose this From address.')
        return redirect('mail:senders')
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    messages.success(request, "Signed in with Google." if mode in ("identity", "auto") else "Google is connected. Sending still requires executive approval.")
    return redirect("mail:dashboard")


@login_required
@require_POST
def google_disconnect(request):
    member = require_executive(request.user)
    with transaction.atomic():
        credential = GoogleCredential.objects.select_for_update().filter(user=request.user).first()
        if credential:
            try:
                data = decrypt_credentials(credential)
                identity = {key: data[key] for key in ("sub", "email") if key in data}
                credential.encrypted_data = encrypt_credentials(identity)
            except (ValueError, ImproperlyConfigured):
                # Keep the account identity hash; unusable ciphertext cannot send.
                credential.encrypted_data = ""
            credential.connected = False
            credential.save(update_fields=["encrypted_data", "connected", "updated_at"])
            AuditEvent.objects.create(workspace=member.workspace, actor=request.user, action="google.disconnected")
    messages.success(request, "Google sending is disconnected from MailSend. You can reconnect when ready.")
    return redirect("mail:dashboard")
