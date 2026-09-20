"""Production safety and real WSGI/static checks with isolated data only."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import base64
import _socket
import http.client
from io import StringIO
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings

from config.production import production_errors

ROOT = Path(__file__).resolve().parents[2]


def production_configuration(directory):
    return {
        'DEBUG': False,
        'SECRET_KEY': secrets.token_urlsafe(64),
        'ALLOWED_HOSTS': ['mail.company.org'],
        'CSRF_TRUSTED_ORIGINS': ['https://mail.company.org'],
        'MAILSEND_DELIVERY_MODE': 'gmail',
        'GOOGLE_CLIENT_ID': '123456-audit.apps.googleusercontent.com',
        'GOOGLE_CLIENT_SECRET': 'isolated-oauth-client-secret',
        'GOOGLE_REDIRECT_URI': 'https://mail.company.org/accounts/google/callback/',
        'MAILSEND_TOKEN_ENCRYPTION_KEY': Fernet.generate_key().decode('ascii'),
        'SESSION_COOKIE_SECURE': True, 'CSRF_COOKIE_SECURE': True,
        'SECURE_SSL_REDIRECT': True,
        'MAILSEND_DATA_DIR': Path(directory), 'MAILSEND_DATA_DIR_CONFIGURED': True,
        'DATABASES': {'default': {'NAME': str(Path(directory) / 'db.sqlite3')}},
        'MEDIA_ROOT': Path(directory) / 'private_media',
    }


class ProductionConfigurationTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='mailsend-deployment-')
        self.addCleanup(self.directory.cleanup)
        self.valid = production_configuration(self.directory.name)

    def test_valid_configuration_and_rejected_insecure_variants(self):
        self.assertEqual(production_errors(self.valid), [])
        changes = (
            {'DEBUG': True}, {'SECRET_KEY': 'short'}, {'SECRET_KEY': 'x' * 64},
            {'SECRET_KEY': 'django-insecure-' + secrets.token_urlsafe(64)},
            {'ALLOWED_HOSTS': ['*']}, {'ALLOWED_HOSTS': ['localhost']},
            {'ALLOWED_HOSTS': ['mail.example.com']}, {'ALLOWED_HOSTS': ['.company.org']},
            {'CSRF_TRUSTED_ORIGINS': ['http://mail.company.org']},
            {'CSRF_TRUSTED_ORIGINS': ['https://unrelated.org']},
            {'MAILSEND_DELIVERY_MODE': 'demo'}, {'GOOGLE_CLIENT_ID': ''},
            {'GOOGLE_CLIENT_SECRET': ''}, {'GOOGLE_CLIENT_SECRET': 'weak'},
            {'MAILSEND_TOKEN_ENCRYPTION_KEY': 'bad-key'},
            {'MAILSEND_TOKEN_ENCRYPTION_KEY': base64.urlsafe_b64encode(b'x' * 32).decode('ascii')},
            {'GOOGLE_REDIRECT_URI': 'http://mail.company.org/accounts/google/callback/'},
            {'GOOGLE_REDIRECT_URI': 'https://unrelated.org/accounts/google/callback/'},
            {'GOOGLE_REDIRECT_URI': 'https://mail.company.org/accounts/google/callback/?extra=1'},
            {'GOOGLE_REDIRECT_URI': 'https://mail.company.org:bad/accounts/google/callback/'},
            {'SESSION_COOKIE_SECURE': False}, {'CSRF_COOKIE_SECURE': False},
            {'SECURE_SSL_REDIRECT': False}, {'MAILSEND_DATA_DIR_CONFIGURED': False},
            {'MAILSEND_DATA_DIR': Path('relative')},
            {'DATABASES': {'default': {'NAME': ':memory:'}}},
            {'MEDIA_ROOT': ROOT / 'private_media'},
        )
        for changed in changes:
            with self.subTest(setting=list(changed)[0]):
                config = deepcopy(self.valid)
                config.update(changed)
                errors = production_errors(config)
                self.assertTrue(errors)
                self.assertNotIn(self.valid['SECRET_KEY'], ' '.join(errors))
                self.assertNotIn(self.valid['MAILSEND_TOKEN_ENCRYPTION_KEY'], ' '.join(errors))

    def environment(self, **changes):
        environment = os.environ.copy()
        environment.update({
            'PYTHON_DOTENV_DISABLED': '1', 'PYTHONDONTWRITEBYTECODE': '1',
            'DJANGO_SETTINGS_MODULE': 'config.settings',
            'DJANGO_DEBUG': 'false', 'DJANGO_SECRET_KEY': self.valid['SECRET_KEY'],
            'DJANGO_ALLOWED_HOSTS': 'mail.company.org',
            'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://mail.company.org',
            'DJANGO_SECURE_SSL_REDIRECT': 'true', 'DJANGO_TRUST_PROXY': 'true',
            'MAILSEND_DELIVERY_MODE': 'gmail', 'MAILSEND_DATA_DIR': self.directory.name,
            'DJANGO_DB_PATH': str(Path(self.directory.name) / 'db.sqlite3'),
            'GOOGLE_OAUTH_CLIENT_ID': self.valid['GOOGLE_CLIENT_ID'],
            'GOOGLE_OAUTH_CLIENT_SECRET': self.valid['GOOGLE_CLIENT_SECRET'],
            'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '',
            'GOOGLE_REDIRECT_URI': self.valid['GOOGLE_REDIRECT_URI'],
            'MAILSEND_TOKEN_ENCRYPTION_KEY': self.valid['MAILSEND_TOKEN_ENCRYPTION_KEY'],
        })
        for name in ('DJANGO_SECRET_KEY', 'GOOGLE_OAUTH_CLIENT_SECRET', 'GOOGLE_CLIENT_SECRET', 'MAILSEND_TOKEN_ENCRYPTION_KEY'):
            environment[name + '_FILE'] = ''
        environment.update(changes)
        return environment

    def run_python(self, code, **changes):
        return subprocess.run([sys.executable, '-B', '-c', textwrap.dedent(code)],
                              cwd=ROOT, env=self.environment(**changes), capture_output=True,
                              text=True, timeout=60)

    def test_settings_import_fails_early_without_modifying_data(self):
        result = self.run_python('import config.settings', DJANGO_SECRET_KEY='weak-secret')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('DJANGO_SECRET_KEY', result.stderr)
        self.assertNotIn('weak-secret', result.stderr)
        self.assertFalse((Path(self.directory.name) / 'db.sqlite3').exists())

    def test_secret_file_is_supported_and_dual_sources_are_rejected(self):
        filename = Path(self.directory.name) / 'django-key'
        filename.write_text(self.valid['SECRET_KEY'], encoding='utf-8')
        result = self.run_python('import config.settings; print("loaded")',
                                 DJANGO_SECRET_KEY='', DJANGO_SECRET_KEY_FILE=str(filename))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'loaded')
        result = self.run_python('import config.settings', DJANGO_SECRET_KEY_FILE=str(filename))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Set only one', result.stderr)
        self.assertNotIn(self.valid['SECRET_KEY'], result.stderr)

    def test_private_environment_initialization_never_overwrites_keys(self):
        from deploy.initialize_env import initialize
        from dotenv import dotenv_values
        filename = Path(self.directory.name) / 'private.env'
        initialize(filename)
        original = filename.read_bytes()
        values = dotenv_values(filename)
        self.assertGreaterEqual(len(values['DJANGO_SECRET_KEY']), 50)
        Fernet(values['MAILSEND_TOKEN_ENCRYPTION_KEY'].encode('ascii'))
        self.assertEqual(values['GOOGLE_OAUTH_CLIENT_SECRET'], '')
        with self.assertRaises(FileExistsError):
            initialize(filename)
        self.assertEqual(filename.read_bytes(), original)

    def test_production_migrations_readiness_static_tls_and_private_media(self):
        result = self.run_python('''
            import json
            from pathlib import Path
            from unittest.mock import patch
            import django
            with patch('socket.socket.connect', side_effect=RuntimeError('External network disabled')):
                django.setup()
                from django.conf import settings
                from django.core.management import call_command
                from django.contrib.staticfiles.storage import staticfiles_storage
                from django.test import Client
                call_command('migrate', interactive=False, verbosity=0)
                call_command('collectstatic', interactive=False, verbosity=0)
                call_command('check', deploy=True, fail_level='WARNING', verbosity=0)
                call_command('check_readiness', verbosity=0)
                settings.MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
                (settings.MEDIA_ROOT / 'private-probe.txt').write_text('PRIVATE_AUDIT_CONTENT')
                client = Client(enforce_csrf_checks=True)
                asset_url = staticfiles_storage.url('mail/app.css')
                asset = client.get(asset_url, secure=True, HTTP_HOST='mail.company.org')
                content = b''.join(asset.streaming_content)
                asset.close()
                health = client.get('/healthz/', secure=True, HTTP_HOST='mail.company.org')
                http = client.get('/accounts/login/', HTTP_HOST='mail.company.org')
                spoofed = client.get('/healthz/', secure=True, HTTP_HOST='rogue.org')
                private = client.get('/private_media/private-probe.txt', secure=True, HTTP_HOST='mail.company.org')
                csrf = client.post('/accounts/login/', {'username': 'nobody', 'password': 'irrelevant'}, secure=True, HTTP_HOST='mail.company.org')
                print(json.dumps({'static': asset.status_code, 'css_nonempty': bool(content),
                    'hashed_asset': asset_url != '/static/mail/app.css',
                    'health': health.status_code, 'health_json': health.json(),
                    'http_redirect': http.status_code, 'https_location': http['Location'].startswith('https://'),
                    'wrong_host': spoofed.status_code, 'private_status': private.status_code,
                    'private_exposed': b'PRIVATE_AUDIT_CONTENT' in private.content, 'csrf': csrf.status_code}))
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(observed, {
            'static': 200, 'css_nonempty': True, 'hashed_asset': True,
            'health': 200, 'health_json': {'status': 'ready'},
            'http_redirect': 301, 'https_location': True, 'wrong_host': 400,
            'private_status': 404, 'private_exposed': False, 'csrf': 403,
        })

    def test_waitress_loopback_http_proxy_static_and_signal_shutdown(self):
        # Parent audit runners may forbid all network access. This test permits
        # only numeric loopback addresses; neither process can contact Google.
        def loopback_connect(sock, address):
            if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1'):
                raise RuntimeError('Only loopback connections are permitted by this test')
            return _socket.socket.connect(sock, address)

        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        code = textwrap.dedent('''
            import _socket
            import logging
            import signal
            import socket
            import sys
            import threading
            import time
            from pathlib import Path
            def loopback_connect(sock, address):
                if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1'):
                    raise RuntimeError('Only loopback connections are permitted by this test')
                return _socket.socket.connect(sock, address)
            socket.socket.connect = loopback_connect
            import django
            django.setup()
            from django.core.management import call_command
            from django.core.wsgi import get_wsgi_application
            from deploy.start import serve
            call_command('migrate', interactive=False, verbosity=0)
            call_command('collectstatic', interactive=False, verbosity=0)
            call_command('check_readiness', verbosity=0)
            from django.conf import settings
            application = get_wsgi_application()
            def smoke_application(environ, start_response):
                if environ.get('PATH_INFO') == '/__deployment_slow_probe__/':
                    (settings.MAILSEND_DATA_DIR / 'inflight-probe').write_text('started')
                    time.sleep(0.75)
                    start_response('200 OK', [('Content-Type', 'text/plain'), ('Content-Length', '8')])
                    return [b'finished']
                return application(environ, start_response)
            def control():
                if sys.stdin.readline().strip() == 'stop':
                    signal.raise_signal(signal.SIGTERM)
            threading.Thread(target=control, daemon=True).start()
            logging.basicConfig(level=logging.INFO)
            # The deliberate bad-host request is asserted below; keep its
            # expected Django diagnostic out of the server-shutdown error log.
            logging.getLogger('django.security.DisallowedHost').setLevel(logging.CRITICAL)
            serve(smoke_application, host='127.0.0.1', port=int(sys.argv[1]))
            print('STOPPED_CLEANLY', flush=True)
        ''')
        process = subprocess.Popen([sys.executable, '-B', '-c', code, str(port)],
            cwd=ROOT, env=self.environment(WAITRESS_TRUSTED_PROXY='127.0.0.1'),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            def request(path, *, secure=True, host='mail.company.org'):
                headers = {'Host': host, 'Connection': 'close', 'X-Forwarded-Host': 'untrusted.org'}
                if secure:
                    headers['X-Forwarded-Proto'] = 'https'
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
                try:
                    connection.request('GET', path, headers=headers)
                    response = connection.getresponse()
                    return response.status, dict(response.getheaders()), response.read()
                finally:
                    connection.close()

            with patch('socket.socket.connect', loopback_connect):
                deadline = time.monotonic() + 30
                while True:
                    try:
                        health = request('/healthz/')
                        break
                    except OSError:
                        if process.poll() is not None or time.monotonic() > deadline:
                            self.fail('The isolated Waitress server did not become ready.')
                        time.sleep(0.1)
                self.assertEqual(health[0], 200)
                self.assertEqual(json.loads(health[2]), {'status': 'ready'})
                status, headers, content = request('/static/mail/app.css')
                self.assertEqual(status, 200)
                self.assertIn('text/css', headers['Content-Type'])
                self.assertTrue(content)
                status, headers, _ = request('/healthz/', secure=False)
                self.assertEqual(status, 301)
                self.assertTrue(headers['Location'].startswith('https://mail.company.org/'))
                self.assertEqual(request('/healthz/', host='untrusted.org')[0], 400)
                self.assertEqual(request('/private_media/not-public.txt')[0], 404)
                with ThreadPoolExecutor(max_workers=1) as executor:
                    inflight = executor.submit(request, '/__deployment_slow_probe__/')
                    started = Path(self.directory.name) / 'inflight-probe'
                    deadline = time.monotonic() + 3
                    while not started.exists():
                        if time.monotonic() > deadline:
                            self.fail('The in-flight shutdown probe did not start.')
                        time.sleep(0.02)
                    stdout, stderr = process.communicate('stop\n', timeout=10)
                    status, _, body = inflight.result(timeout=3)
                    self.assertEqual((status, body), (200, b'finished'))
            self.assertEqual(process.returncode, 0, stderr)
            self.assertIn('STOPPED_CLEANLY', stdout)
            self.assertNotIn('Traceback', stderr)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)


class ReadinessTests(TestCase):
    def test_health_is_generic_and_fails_closed_when_database_unavailable(self):
        response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ready'})
        self.assertIn('no-store', response['Cache-Control'])
        for outcome in (False, OperationalError('sensitive database path')):
            with self.subTest(outcome=type(outcome).__name__):
                options = {'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome}
                with patch('config.health.database_ready', **options):
                    response = self.client.get('/healthz/')
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {'status': 'unavailable'})
        self.assertEqual(self.client.post('/healthz/').status_code, 405)

    @patch('mail.management.commands.check_readiness.production_errors', return_value=[])
    def test_readiness_blocks_pending_migrations_and_known_demo_accounts(self, configuration):
        with patch('mail.management.commands.check_readiness.database_ready', return_value=False):
            with self.assertRaisesMessage(CommandError, 'unapplied database migrations'):
                call_command('check_readiness', stdout=StringIO())
        get_user_model().objects.create_user('executive', 'daniel@example.com', 'changed-demo-password')
        with self.assertRaisesMessage(CommandError, 'known demo accounts'):
            call_command('check_readiness', stdout=StringIO())

    @patch('mail.management.commands.check_readiness.production_errors', return_value=[])
    def test_readiness_allows_real_generic_username_and_rejects_default_demo_password(self, configuration):
        account = get_user_model().objects.create_user('assistant', 'worker@company.org', 'A-unique-long-password-2026!')
        call_command('check_readiness', stdout=StringIO())
        account.set_password('MailSend-Demo-2026!')
        account.save(update_fields=['password'])
        with self.assertRaisesMessage(CommandError, 'known demo accounts'):
            call_command('check_readiness', stdout=StringIO())

    def test_readiness_rejects_default_development_mode(self):
        with self.assertRaisesMessage(CommandError, 'Readiness failed:'):
            call_command('check_readiness', stdout=StringIO())
