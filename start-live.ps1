param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$livePython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $livePython -PathType Leaf)) {
    throw 'The project Python environment is missing. Follow the initial setup in README.md before starting the live demo.'
}

# Local live-mail launcher: no account seeding, migrations, credential changes,
# dependency installation, provider calls, or automatic sends occur at startup.
$liveLauncher = @'
import os
import socket
import sys
from pathlib import Path


def main():
    from dotenv import load_dotenv

    root = Path.cwd()
    load_dotenv(root / '.env')
    data_dir = Path(os.getenv('MAILSEND_DATA_DIR') or root).expanduser()
    if not (os.getenv('DJANGO_SECRET_KEY') or os.getenv('DJANGO_SECRET_KEY_FILE')
            or (data_dir / '.local-secret').is_file()):
        raise RuntimeError('The existing Django secret is missing. Restore the original secret before starting; do not generate a replacement for this demo.')
    database_path = Path(os.getenv('DJANGO_DB_PATH') or data_dir / 'db.sqlite3')
    if not database_path.is_file():
        raise RuntimeError('The existing database is missing. Check DJANGO_DB_PATH/MAILSEND_DATA_DIR or restore the demo database before starting.')

    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    import django
    django.setup()

    from django.conf import settings
    from django.core import checks
    from config.readiness import database_ready
    from mail.google_api import oauth_configured
    from mail.models import GoogleCredential

    if not settings.DEBUG:
        raise RuntimeError('This launcher is for the local HTTP live demo. Use docs/DEPLOYMENT.md for DEBUG=false and public HTTPS hosting.')
    if settings.MAILSEND_DELIVERY_MODE != 'gmail':
        raise RuntimeError('Real sending is disabled. Set MAILSEND_DELIVERY_MODE=gmail in the existing .env, then restart this launcher.')
    if not oauth_configured():
        raise RuntimeError('Google OAuth or the token encryption key is missing/invalid. Check the existing .env using the Connect Gmail section in README.md.')
    if settings.GOOGLE_REDIRECT_URI != 'http://127.0.0.1:8000/accounts/google/callback/':
        raise RuntimeError('The local demo requires GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/accounts/google/callback/ and that exact authorized Google callback.')
    if '127.0.0.1' not in settings.ALLOWED_HOSTS:
        raise RuntimeError('Add 127.0.0.1 to DJANGO_ALLOWED_HOSTS for this local demo.')
    if any(issue.level >= checks.ERROR for issue in checks.run_checks()):
        raise RuntimeError('Django system checks failed. Run .\\.venv\\Scripts\\python.exe manage.py check to inspect the errors.')
    if not database_ready():
        raise RuntimeError('Database migrations are pending. Back up the existing database, then run .\\.venv\\Scripts\\python.exe manage.py migrate before starting.')

    from waitress import serve
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from config.wsgi import application

    print('Local checks passed: Gmail mode, OAuth configuration, Django checks and database migrations.', flush=True)
    connected = GoogleCredential.objects.filter(
        connected=True, user__is_active=True, user__membership__role='executive'
    ).exists()
    if not connected:
        print('No connected executive account was found. Sign in and connect Google before sending.', flush=True)
    print('No Google request or email was sent by these checks; provider permission is checked when the executive sends.', flush=True)

    if '--check-only' in sys.argv:
        print('Check-only complete. No server was started and no accounts or configuration were changed.', flush=True)
        return

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(('127.0.0.1', 8000))
        except OSError:
            raise RuntimeError('Port 8000 is already in use. Keep the existing MailSend server if it is in Gmail mode, or stop its own terminal with Ctrl+C and rerun this command. No process was stopped.') from None

    print('Open http://127.0.0.1:8000 in this computer. Keep this terminal open; press Ctrl+C to stop.', flush=True)
    print('LIVE GMAIL MODE: an executive Send action delivers real email. Review recipients and the whole current batch before clicking Send.', flush=True)
    print('This loopback HTTP demo is not the public production deployment.', flush=True)
    # StaticFilesHandler serves configured static assets only. Private uploads
    # retain their authenticated Django routes; no media directory is exposed.
    try:
        serve(StaticFilesHandler(application), host='127.0.0.1', port=8000,
              threads=4, clear_untrusted_proxy_headers=True)
    except OSError:
        raise RuntimeError('Waitress could not bind local port 8000. Check whether another server started, then retry without stopping unrelated processes.') from None


try:
    main()
except KeyboardInterrupt:
    print('\nLocal MailSend server stopped.', flush=True)
except RuntimeError as exc:
    print(f'Startup stopped: {exc}', file=sys.stderr)
    sys.exit(1)
except Exception as exc:
    print(f'Startup stopped ({type(exc).__name__}). Run .\\.venv\\Scripts\\python.exe manage.py check and review the local setup in docs/LIVE_DEMO_START.md. Secret values are not displayed.', file=sys.stderr)
    sys.exit(1)
'@

$liveArguments = @('-')
if ($CheckOnly) { $liveArguments += '--check-only' }
$liveLauncher | & $livePython @liveArguments
if ($LASTEXITCODE -ne 0) { throw 'MailSend live startup did not complete. Follow the message above.' }
