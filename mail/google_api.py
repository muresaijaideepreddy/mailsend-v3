"""Small Google OAuth/Gmail adapter with encrypted credentials and no send retries."""

import base64
import hashlib
import json
import math
import time
from email.utils import getaddresses
from urllib.parse import urlparse

import requests
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from .models import GoogleCredential
from .services import DeliveryRejected, require_executive

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
IDENTITY_SCOPES = ("openid", "email", "profile")
SCOPES = (*IDENTITY_SCOPES, SEND_SCOPE, CONTACTS_SCOPE)
HTTP_TIMEOUT = (5, 20)


def _cipher():
    key = getattr(settings, "MAILSEND_TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise ImproperlyConfigured("Configure MAILSEND_TOKEN_ENCRYPTION_KEY before connecting Google.")
    try:
        return Fernet(key.encode("ascii") if isinstance(key, str) else key)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ImproperlyConfigured("MAILSEND_TOKEN_ENCRYPTION_KEY must be a valid Fernet key.") from exc


def oauth_configured():
    try:
        _cipher()
        uri = urlparse(getattr(settings, "GOOGLE_REDIRECT_URI", ""))
        safe_uri = uri.scheme == "https" or (settings.DEBUG and uri.scheme == "http" and uri.hostname in ("localhost", "127.0.0.1", "::1"))
        return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and uri.netloc and safe_uri)
    except (ImproperlyConfigured, ValueError):
        return False


def encrypt_credentials(data):
    return _cipher().encrypt(json.dumps(data, separators=(",", ":")).encode("utf-8")).decode("ascii")


def decrypt_credentials(record_or_ciphertext):
    ciphertext = getattr(record_or_ciphertext, "encrypted_data", record_or_ciphertext)
    try:
        data = json.loads(_cipher().decrypt(ciphertext.encode("ascii")))
        if not isinstance(data, dict):
            raise ValueError("Invalid token data")
        return data
    except (InvalidToken, TypeError, ValueError, UnicodeError, AttributeError) as exc:
        raise ValueError("The stored Google connection could not be read. Reconnect Google.") from exc


def subject_hash(subject):
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()


def token_values(response_data, previous=None, *, required_scopes=(SEND_SCOPE,)):
    """Validate a successful token response and retain an omitted refresh token."""
    previous = previous or {}
    if not isinstance(response_data, dict):
        raise ValueError("Invalid Google token response")
    access_token = response_data.get("access_token")
    if not isinstance(access_token, str) or not access_token or len(access_token) > 16_384 or any(ord(c) < 33 for c in access_token):
        raise ValueError("Missing Google access token")
    if str(response_data.get("token_type", "Bearer")).lower() != "bearer":
        raise ValueError("Unexpected Google token type")
    expiry = float(response_data.get("expires_in", 3600))
    if not math.isfinite(expiry) or expiry <= 0:
        raise ValueError("Invalid Google token lifetime")
    scope = response_data.get("scope", previous.get("scope", ""))
    if not isinstance(scope, str) or not set(required_scopes).issubset(scope.split()):
        raise ValueError("Google did not grant the required permissions")
    result = dict(previous)
    result.update(access_token=access_token, expires_at=time.time() + expiry, scope=scope)
    refresh_token = response_data.get("refresh_token") or previous.get("refresh_token")
    if refresh_token:
        if not isinstance(refresh_token, str) or len(refresh_token) > 16_384:
            raise ValueError("Invalid Google refresh token")
        result["refresh_token"] = refresh_token
    return result


def _access_token(user, *, required_scopes=(SEND_SCOPE,)):
    require_executive(user)
    required_scopes = set(required_scopes)
    try:
        if not oauth_configured():
            raise ValueError("Google OAuth is not configured")
        record = GoogleCredential.objects.get(user=user, connected=True)
        data = decrypt_credentials(record)
        if not data.get("sub") or data.get("email", "").casefold() != user.email.casefold():
            raise ValueError("The connected Google account does not match the executive")
        granted_scopes = set(data.get("scope", "").split())
        if not required_scopes.issubset(granted_scopes):
            raise ValueError("Required Google permissions are missing")
        expiry = float(data.get("expires_at", 0))
        if not math.isfinite(expiry):
            raise ValueError("Invalid Google expiry")
        if expiry > time.time() + 60 and data.get("access_token"):
            return data["access_token"]
        if not data.get("refresh_token"):
            raise ValueError("Reconnect Google to renew sending permission")
        response = requests.post(TOKEN_URL, data={
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "refresh_token": data["refresh_token"],
            "grant_type": "refresh_token",
        }, timeout=HTTP_TIMEOUT, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError("Google could not refresh this connection")
        # Never replace an existing sending grant with a narrower token.
        retained_scopes = granted_scopes.intersection({SEND_SCOPE, CONTACTS_SCOPE})
        refreshed = token_values(response.json(), previous=data, required_scopes=required_scopes | retained_scopes)
        # A concurrent disconnect or reconnect must not be overwritten by refresh.
        updated = GoogleCredential.objects.filter(pk=record.pk, connected=True, encrypted_data=record.encrypted_data).update(
            encrypted_data=encrypt_credentials(refreshed), updated_at=timezone.now()
        )
        if not updated:
            raise ValueError("The Google connection changed during refresh")
        return refreshed["access_token"]
    except (GoogleCredential.DoesNotExist, ValueError, TypeError, AttributeError, ImproperlyConfigured, requests.RequestException) as exc:
        # No Gmail send has occurred, so retrying after reconnecting is safe.
        message = "Connect the executive's Google account before sending." if required_scopes == {SEND_SCOPE} else "Connect the executive's Google account with the required permissions before continuing."
        raise DeliveryRejected(message) from exc


def _gmail_api_disabled(response):
    """Recognize Google's structured API-disabled error without exposing its text."""
    if response.status_code != 403:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict) or error.get("code") != 403:
        return False
    legacy_errors = error.get("errors")
    if isinstance(legacy_errors, list) and any(
        isinstance(item, dict) and item.get("reason") == "accessNotConfigured"
        and item.get("domain") == "usageLimits" for item in legacy_errors
    ):
        return True
    details = error.get("details")
    if isinstance(details, list):
        for item in details:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata")
            if (item.get("@type") == "type.googleapis.com/google.rpc.ErrorInfo"
                    and item.get("reason") == "SERVICE_DISABLED"
                    and item.get("domain") == "googleapis.com"
                    and isinstance(metadata, dict)
                    and metadata.get("service") == "gmail.googleapis.com"):
                return True
    return False


def send_gmail(user, email_message):
    require_executive(user)
    senders = getaddresses(email_message.get_all("From", []))
    if len(senders) != 1 or senders[0][1].casefold() != user.email.casefold():
        raise DeliveryRejected("The message sender must match the executive's Google account.")
    token = _access_token(user)
    raw = base64.urlsafe_b64encode(email_message.as_bytes()).decode("ascii")
    # Intentionally one HTTP send only. A timeout or 5xx can follow acceptance.
    response = requests.post(SEND_URL, json={"raw": raw}, headers={"Authorization": f"Bearer {token}"}, timeout=HTTP_TIMEOUT, allow_redirects=False)
    if 400 <= response.status_code < 500 and response.status_code != 408:
        if _gmail_api_disabled(response):
            raise DeliveryRejected("Google rejected the message because the Gmail API is disabled.", code="gmail_api_disabled")
        raise DeliveryRejected("Google rejected the message before accepting delivery.")
    if not 200 <= response.status_code < 300:
        raise RuntimeError("Google delivery could not be confirmed")
    data = response.json()
    provider_id = data.get("id") if isinstance(data, dict) else None
    if not isinstance(provider_id, str) or not provider_id or len(provider_id) > 255:
        raise RuntimeError("Google did not return a delivery receipt")
    return provider_id
