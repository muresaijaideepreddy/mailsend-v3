"""Production invariants. Error messages name settings, never their values."""
import base64
import re
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet


def production_errors(configuration):
    get = configuration.get if isinstance(configuration, dict) else lambda key, default=None: getattr(configuration, key, default)
    errors = []
    if get('DEBUG', True):
        errors.append('DJANGO_DEBUG must be false in production.')
    secret = get('SECRET_KEY', '')
    if len(secret) < 50 or len(set(secret)) < 5 or secret.startswith('django-insecure-') or any(
        marker in secret.lower() for marker in ('change-me', 'changeme', 'replace-me', 'example-secret')
    ):
        errors.append('DJANGO_SECRET_KEY must be a unique strong secret of at least 50 characters.')
    hosts = get('ALLOWED_HOSTS', [])
    def public_hostname(host):
        return (isinstance(host, str) and len(host) <= 253
                and bool(re.fullmatch(r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}', host))
                and not host.lower().endswith(('.localhost', '.local', '.test', '.example', '.invalid', '.internal'))
                and host.lower() not in ('example.com', 'example.net', 'example.org')
                and not any(host.lower().endswith('.' + domain) for domain in ('example.com', 'example.net', 'example.org')))
    if not hosts or not all(public_hostname(host) for host in hosts):
        errors.append('DJANGO_ALLOWED_HOSTS must contain exact public DNS hostnames, without wildcards or placeholders.')
    origins = get('CSRF_TRUSTED_ORIGINS', [])
    expected_origins = {'https://' + host for host in hosts}
    if not origins or any(origin not in expected_origins for origin in origins):
        errors.append('DJANGO_CSRF_TRUSTED_ORIGINS must contain HTTPS origins matching DJANGO_ALLOWED_HOSTS.')
    if get('MAILSEND_DELIVERY_MODE') != 'gmail':
        errors.append('MAILSEND_DELIVERY_MODE must be gmail in production; demo delivery is forbidden.')
    client_secret = get('GOOGLE_CLIENT_SECRET', '')
    if (not get('GOOGLE_CLIENT_ID', '').endswith('.apps.googleusercontent.com')
            or len(client_secret) < 16
            or any(marker in client_secret.lower() for marker in ('change-me', 'changeme', 'replace-me'))):
        errors.append('Google OAuth client ID and client secret are required in production.')
    try:
        uri = urlsplit(get('GOOGLE_REDIRECT_URI', ''))
        valid_redirect = (uri.scheme == 'https' and uri.hostname in hosts and uri.port in (None, 443)
                          and not uri.username and not uri.password and not uri.query and not uri.fragment
                          and uri.path == '/accounts/google/callback/'
                          and 'https://' + uri.hostname in origins)
    except (TypeError, ValueError):
        valid_redirect = False
    if not valid_redirect:
        errors.append('GOOGLE_REDIRECT_URI must be the HTTPS /accounts/google/callback/ URL on an allowed host.')
    try:
        key = get('MAILSEND_TOKEN_ENCRYPTION_KEY', '').encode('ascii')
        Fernet(key)
        if len(set(base64.urlsafe_b64decode(key))) < 5:
            raise ValueError('Weak encryption key')
    except (TypeError, ValueError, UnicodeError, AttributeError):
        errors.append('MAILSEND_TOKEN_ENCRYPTION_KEY must be a valid persistent Fernet key.')
    if not get('SESSION_COOKIE_SECURE', False) or not get('CSRF_COOKIE_SECURE', False) or not get('SECURE_SSL_REDIRECT', False):
        errors.append('HTTPS redirect and secure session/CSRF cookies are required in production.')
    data_dir = get('MAILSEND_DATA_DIR')
    if not get('MAILSEND_DATA_DIR_CONFIGURED', False) or not data_dir or not Path(data_dir).is_absolute():
        errors.append('MAILSEND_DATA_DIR must explicitly name an absolute persistent data directory.')
    else:
        directory = Path(data_dir).resolve()
        for label, value in (
            ('database', get('DATABASES', {}).get('default', {}).get('NAME', '')),
            ('private media', get('MEDIA_ROOT', '')),
        ):
            if not value or not Path(value).resolve().is_relative_to(directory) or Path(value).resolve() == directory:
                errors.append(f'The {label} path must be inside MAILSEND_DATA_DIR.')
    return errors
