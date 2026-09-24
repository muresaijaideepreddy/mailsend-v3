import os
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
DEBUG = os.getenv('DJANGO_DEBUG', 'true').lower() == 'true'
MAILSEND_DATA_DIR_CONFIGURED = bool(os.getenv('MAILSEND_DATA_DIR', '').strip())
MAILSEND_DATA_DIR = Path(os.getenv('MAILSEND_DATA_DIR') or BASE_DIR).expanduser()


def env_secret(name):
    """Read deployment secrets from an environment variable or an explicit file."""
    value, filename = os.getenv(name, ''), os.getenv(name + '_FILE', '')
    if value and filename:
        raise ImproperlyConfigured(f'Set only one of {name} and {name}_FILE.')
    if filename:
        try:
            return Path(filename).read_text(encoding='utf-8').strip()
        except (OSError, UnicodeError) as exc:
            raise ImproperlyConfigured(f'{name}_FILE could not be read.') from None
    return value


SECRET_KEY = env_secret('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY is required in production.')
    MAILSEND_DATA_DIR.mkdir(parents=True, exist_ok=True)
    secret_file = MAILSEND_DATA_DIR / '.local-secret'
    if not secret_file.exists():
        try:
            with secret_file.open('x', encoding='utf-8') as handle:
                handle.write(secrets.token_urlsafe(64))
        except FileExistsError:
            pass
    SECRET_KEY = secret_file.read_text(encoding='utf-8').strip()
ALLOWED_HOSTS = [x.strip() for x in os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1]').split(',') if x.strip()]
CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if x.strip()]
INSTALLED_APPS = ['django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles', 'mail.apps.MailConfig']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware', 'mail.middleware.PrivatePageMiddleware']
if not DEBUG:
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request', 'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages', 'mail.context_processors.workspace_context']}}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': os.getenv('DJANGO_DB_PATH', str(MAILSEND_DATA_DIR / 'db.sqlite3')), 'OPTIONS': {'timeout': 20}}}
AUTH_PASSWORD_VALIDATORS = [{'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'}, {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'}, {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'}, {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.getenv('MAILSEND_TIME_ZONE', 'America/Chicago')
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = MAILSEND_DATA_DIR / 'staticfiles'
MEDIA_ROOT = MAILSEND_DATA_DIR / 'private_media'
if not DEBUG:
    STORAGES = {
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
    }
    WHITENOISE_USE_FINDERS = False
    WHITENOISE_AUTOREFRESH = False
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'mail:login'
LOGIN_REDIRECT_URL = 'mail:dashboard'
LOGOUT_REDIRECT_URL = 'mail:login'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 8 * 60 * 60
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.getenv('DJANGO_SECURE_SSL_REDIRECT', 'true').lower() == 'true'
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
MAILSEND_DELIVERY_MODE = os.getenv('MAILSEND_DELIVERY_MODE', 'demo')
if MAILSEND_DELIVERY_MODE not in ('demo', 'gmail'):
    raise ImproperlyConfigured('MAILSEND_DELIVERY_MODE must be demo or gmail.')
MAILSEND_DEMO_OUTBOX = MAILSEND_DATA_DIR / 'demo_outbox'
MAILSEND_DEMO_ENABLED = DEBUG and MAILSEND_DELIVERY_MODE == 'demo'
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_OAUTH_CLIENT_ID') or os.getenv('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = env_secret('GOOGLE_OAUTH_CLIENT_SECRET') or env_secret('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', 'http://127.0.0.1:8000/accounts/google/callback/')
MAILSEND_TOKEN_ENCRYPTION_KEY = env_secret('MAILSEND_TOKEN_ENCRYPTION_KEY')
MAILSEND_CLAUDE_API_KEY = env_secret('MAILSEND_CLAUDE_API_KEY')
MAILSEND_CLAUDE_MODEL = os.getenv('MAILSEND_CLAUDE_MODEL', 'claude-sonnet-4-6')

# Enable only when a trusted reverse proxy strips incoming forwarded headers.
if os.getenv('DJANGO_TRUST_PROXY', 'false').lower() == 'true':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

if not DEBUG:
    from .production import production_errors
    configuration_errors = production_errors(globals())
    if configuration_errors:
        raise ImproperlyConfigured('Production configuration rejected: ' + ' '.join(configuration_errors))


MAILSEND_CLAUDE_PROVIDER = os.getenv('MAILSEND_CLAUDE_PROVIDER', 'anthropic')
if MAILSEND_CLAUDE_PROVIDER not in ('anthropic', 'tamu'):
    raise ImproperlyConfigured('MAILSEND_CLAUDE_PROVIDER must be anthropic or tamu.')
