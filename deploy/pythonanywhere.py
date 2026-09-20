"""Native PythonAnywhere WSGI setup with explicit private configuration."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import secrets
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import dotenv_values

from config.production import production_errors


SOURCE_ROOT = Path(__file__).resolve().parent.parent
_HOSTNAME = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.(?:eu\.)?pythonanywhere\.com')
_REQUIRED = frozenset({
    'DJANGO_DEBUG', 'DJANGO_ALLOWED_HOSTS', 'DJANGO_CSRF_TRUSTED_ORIGINS',
    'DJANGO_SECRET_KEY', 'GOOGLE_OAUTH_CLIENT_ID', 'GOOGLE_OAUTH_CLIENT_SECRET',
    'GOOGLE_REDIRECT_URI', 'MAILSEND_TOKEN_ENCRYPTION_KEY', 'MAILSEND_DATA_DIR',
    'MAILSEND_DELIVERY_MODE', 'DJANGO_TRUST_PROXY',
})
_APP_PREFIXES = ('DJANGO_', 'GOOGLE_', 'MAILSEND_', 'WAITRESS_')


def _private_path(value, *, directory=False):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError('Private configuration and data paths must be absolute.')
    resolved = path.resolve()
    if resolved.is_relative_to(SOURCE_ROOT) or (directory and SOURCE_ROOT.is_relative_to(resolved)):
        raise ValueError('Private configuration and data must be outside the source checkout.')
    return path


def _hostname(value):
    if not isinstance(value, str) or not _HOSTNAME.fullmatch(value):
        raise ValueError('Use one exact PythonAnywhere account hostname.')
    return value


def _paths(filename, data_dir):
    filename = _private_path(filename)
    data_dir = _private_path(data_dir, directory=True)
    if filename.resolve().is_relative_to(data_dir.resolve()):
        raise ValueError('Keep the private configuration file outside the data directory.')
    return filename, data_dir


def initialize(filename, *, hostname, data_dir):
    """Create a fresh private template; existing files/keys are never replaced."""
    hostname = _hostname(hostname)
    filename, data_dir = _paths(filename, data_dir)
    values = {
        'DJANGO_DEBUG': 'false',
        'DJANGO_ALLOWED_HOSTS': hostname,
        'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://' + hostname,
        'DJANGO_SECRET_KEY': secrets.token_urlsafe(64),
        'MAILSEND_DELIVERY_MODE': 'gmail',
        'MAILSEND_DATA_DIR': str(data_dir.resolve()),
        'MAILSEND_TIME_ZONE': 'America/Chicago',
        'DJANGO_TRUST_PROXY': 'false',
        'GOOGLE_OAUTH_CLIENT_ID': '',
        'GOOGLE_OAUTH_CLIENT_SECRET': '',
        'GOOGLE_REDIRECT_URI': 'https://' + hostname + '/accounts/google/callback/',
        'MAILSEND_TOKEN_ENCRYPTION_KEY': base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii'),
    }
    filename.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write('# Private PythonAnywhere configuration. Preserve the generated keys.\n')
        handle.write('# Fill both Google OAuth values before prepare or reload. Never commit this file.\n')
        for key, value in values.items():
            encoded = json.dumps(value, ensure_ascii=False) if any(c in value for c in ' \\#\'"\n\r\t') else value
            handle.write(f'{key}={encoded}\n')
    return filename


def load_environment(filename):
    """Validate the private file, then replace only application-specific env vars."""
    from django.conf import settings
    if settings.configured:
        raise ValueError('Load PythonAnywhere settings in a fresh process before initializing Django.')
    filename = _private_path(filename)
    if not filename.is_file():
        raise ValueError('The explicit private environment file is missing.')
    if os.name != 'nt' and filename.stat().st_mode & 0o077:
        raise ValueError('The private environment file must be readable only by its owner (mode 0600).')
    # Never resolve ${...} from ambient credentials or other environment values.
    values = dict(dotenv_values(filename, interpolate=False, encoding='utf-8'))
    if set(values) - (_REQUIRED | {'MAILSEND_TIME_ZONE'}):
        raise ValueError('The private environment file contains unsupported settings.')
    if any(not isinstance(values.get(key), str) or not values[key] for key in _REQUIRED):
        raise ValueError('Complete every required private setting, including both Google OAuth values.')
    if (values['DJANGO_DEBUG'] != 'false' or values['MAILSEND_DELIVERY_MODE'] != 'gmail'
            or values['DJANGO_TRUST_PROXY'] != 'false'):
        raise ValueError('PythonAnywhere requires DEBUG=false, Gmail delivery and proxy-header trust disabled.')
    host = _hostname(values['DJANGO_ALLOWED_HOSTS'])
    if (values['DJANGO_CSRF_TRUSTED_ORIGINS'] != 'https://' + host
            or values['GOOGLE_REDIRECT_URI'] != 'https://' + host + '/accounts/google/callback/'):
        raise ValueError('The HTTPS origin and Google callback must exactly match the account hostname.')
    _, data_dir = _paths(filename, values['MAILSEND_DATA_DIR'])
    values['MAILSEND_DATA_DIR'] = str(data_dir.resolve())
    values.setdefault('MAILSEND_TIME_ZONE', 'America/Chicago')
    try:
        ZoneInfo(values['MAILSEND_TIME_ZONE'])
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError('MAILSEND_TIME_ZONE must be a valid timezone.') from None
    errors = production_errors({
        'DEBUG': False, 'SECRET_KEY': values['DJANGO_SECRET_KEY'],
        'ALLOWED_HOSTS': [host], 'CSRF_TRUSTED_ORIGINS': [values['DJANGO_CSRF_TRUSTED_ORIGINS']],
        'MAILSEND_DELIVERY_MODE': values['MAILSEND_DELIVERY_MODE'],
        'GOOGLE_CLIENT_ID': values['GOOGLE_OAUTH_CLIENT_ID'],
        'GOOGLE_CLIENT_SECRET': values['GOOGLE_OAUTH_CLIENT_SECRET'],
        'GOOGLE_REDIRECT_URI': values['GOOGLE_REDIRECT_URI'],
        'MAILSEND_TOKEN_ENCRYPTION_KEY': values['MAILSEND_TOKEN_ENCRYPTION_KEY'],
        'SESSION_COOKIE_SECURE': True, 'CSRF_COOKIE_SECURE': True, 'SECURE_SSL_REDIRECT': True,
        'MAILSEND_DATA_DIR': data_dir.resolve(), 'MAILSEND_DATA_DIR_CONFIGURED': True,
        'DATABASES': {'default': {'NAME': data_dir.resolve() / 'db.sqlite3'}},
        'MEDIA_ROOT': data_dir.resolve() / 'private_media',
    })
    if errors:
        raise ValueError('Production configuration rejected: ' + ' '.join(errors))
    # Preserve PythonAnywhere's HTTP(S) proxy and other system variables. Clear
    # stale application settings, including alternate credential *_FILE values.
    for key in list(os.environ):
        if key.startswith(_APP_PREFIXES):
            del os.environ[key]
    os.environ.update(values)
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    return values


def setup_application(filename):
    """Return the native WSGI app; no migration, server, or provider calls."""
    from django.conf import settings
    if settings.configured:
        raise ValueError('Load PythonAnywhere settings in a fresh process before initializing Django.')
    load_environment(filename)
    from django.core.wsgi import get_wsgi_application
    return get_wsgi_application()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', required=True, help='Absolute private environment file outside the checkout')
    commands = parser.add_subparsers(dest='command', required=True)
    init_parser = commands.add_parser('init', help='Create a new private environment template')
    init_parser.add_argument('--host', required=True)
    init_parser.add_argument('--data', required=True)
    commands.add_parser('prepare', help='Apply migrations, collect static files and check readiness')
    manage_parser = commands.add_parser('manage', help='Run a Django management command with the same private environment')
    manage_parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            initialize(args.env, hostname=args.host, data_dir=args.data)
            print('Private template created. Fill the Google OAuth values; preserve the generated keys.')
            return 0
        load_environment(args.env)
        if args.command == 'manage':
            if not args.arguments:
                parser.error('manage requires a Django command')
            from django.core.management import execute_from_command_line
            execute_from_command_line([str(SOURCE_ROOT / 'manage.py'), *args.arguments])
            return 0
        import django
        from django.conf import settings
        from django.core.management import call_command
        django.setup()
        previous_umask = os.umask(0o077)
        try:
            for directory in (settings.MAILSEND_DATA_DIR, settings.MEDIA_ROOT, settings.STATIC_ROOT):
                Path(directory).mkdir(parents=True, exist_ok=True, mode=0o700)
            call_command('migrate', interactive=False)
            call_command('collectstatic', interactive=False, verbosity=0)
            call_command('check', deploy=True, fail_level='WARNING')
            call_command('check_readiness')
        finally:
            os.umask(previous_umask)
        print('Prepared for PythonAnywhere. Reload the configured WSGI web app; no server was started.')
        return 0
    except Exception:
        # A traceback or provider/command error could contain private values.
        print('PythonAnywhere setup failed. Check the private file, production settings and directory access. Existing keys were not replaced.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
