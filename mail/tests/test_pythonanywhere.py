"""PythonAnywhere deployment isolation and native WSGI regression checks.

All credentials, data, and accounts are synthetic. Subprocesses explicitly
disable outgoing sockets; the local application and its database are untouched.
"""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.conf import LazySettings
from django.test import SimpleTestCase
from dotenv import dotenv_values, set_key


ROOT = Path(__file__).resolve().parents[2]
HOST = 'mailsend-deployment-check.pythonanywhere.com'


class PythonAnywhereDeploymentTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='mailsend-pythonanywhere-')
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.filename = self.base / 'private.env'
        self.data = self.base / 'persistent-data'

    def initialize(self, filename=None, *, hostname=HOST, data_dir=None):
        from deploy.pythonanywhere import initialize
        return initialize(filename or self.filename, hostname=hostname, data_dir=data_dir or self.data)

    def configured_file(self):
        self.initialize()
        set_key(str(self.filename), 'GOOGLE_OAUTH_CLIENT_ID', '123456-pythonanywhere-audit.apps.googleusercontent.com')
        set_key(str(self.filename), 'GOOGLE_OAUTH_CLIENT_SECRET', 'synthetic-private-oauth-secret-for-tests')
        return self.filename

    def load(self, filename=None):
        from deploy.pythonanywhere import load_environment
        # The test runner has already configured Django. File-validation cases
        # exercise only the loader against a fresh settings holder; real WSGI
        # initialization is verified in separate processes below.
        with patch('django.conf.settings', LazySettings()):
            return load_environment(filename or self.filename)

    def child(self, code, *arguments, timeout=60, **environment):
        values = os.environ.copy()
        values.update(PYTHONDONTWRITEBYTECODE='1')
        values.update(environment)
        prelude = '''
import socket
def forbidden_network(*args, **kwargs):
    raise AssertionError('External network is forbidden in deployment tests')
socket.socket.connect = forbidden_network
'''
        return subprocess.run([sys.executable, '-B', '-c', prelude + textwrap.dedent(code), *map(str, arguments)],
                              cwd=ROOT, env=values, capture_output=True, text=True, timeout=timeout)

    def cli(self, *arguments):
        return self.child('''
            import runpy
            import sys
            sys.argv = ['deploy/pythonanywhere.py', *sys.argv[1:]]
            runpy.run_module('deploy.pythonanywhere', run_name='__main__')
        ''', '--env', self.filename, *arguments)

    def test_initializer_creates_private_independent_keys_and_never_overwrites(self):
        created = self.initialize()
        self.assertEqual(Path(created), self.filename)
        original = self.filename.read_bytes()
        first = dotenv_values(self.filename, interpolate=False)
        self.assertGreaterEqual(len(first['DJANGO_SECRET_KEY']), 50)
        Fernet(first['MAILSEND_TOKEN_ENCRYPTION_KEY'].encode('ascii'))
        self.assertEqual(first['GOOGLE_OAUTH_CLIENT_ID'], '')
        self.assertEqual(first['GOOGLE_OAUTH_CLIENT_SECRET'], '')
        self.assertEqual(first['DJANGO_ALLOWED_HOSTS'], HOST)
        self.assertEqual(first['GOOGLE_REDIRECT_URI'], f'https://{HOST}/accounts/google/callback/')
        self.assertEqual(first['MAILSEND_DELIVERY_MODE'], 'gmail')
        self.assertEqual(first['DJANGO_DEBUG'], 'false')
        self.assertEqual(first['DJANGO_TRUST_PROXY'], 'false')
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(self.filename.stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            self.initialize()
        self.assertEqual(self.filename.read_bytes(), original)
        second_file = self.base / 'second-private.env'
        self.initialize(second_file, hostname='mailsend-deployment-check.eu.pythonanywhere.com', data_dir=self.base / 'second-data')
        second = dotenv_values(second_file, interpolate=False)
        self.assertNotEqual(first['DJANGO_SECRET_KEY'], second['DJANGO_SECRET_KEY'])
        self.assertNotEqual(first['MAILSEND_TOKEN_ENCRYPTION_KEY'], second['MAILSEND_TOKEN_ENCRYPTION_KEY'])
        self.assertFalse((self.data / 'db.sqlite3').exists())

    def test_initializer_rejects_unrelated_hosts_and_unsafe_storage_paths(self):
        from deploy.pythonanywhere import initialize
        for hostname in ('*', 'localhost', 'mail.company.org', 'pythonanywhere.com',
                         'user.pythonanywhere.com.attacker.org', 'user.pythonanywhere.com,other.pythonanywhere.com'):
            with self.subTest(hostname=hostname), self.assertRaises(ValueError):
                initialize(self.filename, hostname=hostname, data_dir=self.data)
            self.assertFalse(self.filename.exists())
        for filename, data in ((Path('relative.env'), self.data),
                               (self.filename, Path('relative-data')),
                               (self.data / 'private.env', self.data),
                               (self.filename, ROOT / 'private-data')):
            with self.subTest(filename=filename, data=data), self.assertRaises(ValueError):
                initialize(filename, hostname=HOST, data_dir=data)
        self.assertFalse(self.filename.exists())

    def test_missing_file_or_google_values_never_fall_back_to_ambient_secrets(self):
        with patch.dict(os.environ, {'GOOGLE_OAUTH_CLIENT_ID': 'ambient.apps.googleusercontent.com',
                                    'GOOGLE_OAUTH_CLIENT_SECRET': 'ambient-client-secret-must-not-be-used'}):
            with self.assertRaises((ValueError, OSError)):
                self.load()
            self.initialize()
            with self.assertRaises(ValueError) as failure:
                self.load()
        self.assertNotIn('ambient-client-secret-must-not-be-used', str(failure.exception))
        self.assertFalse((self.data / 'db.sqlite3').exists())
        with self.assertRaises(ValueError):
            self.load(ROOT / 'not-a-pythonanywhere-private.env')

    def test_loader_rejects_insecure_values_before_touching_database_or_environment(self):
        self.configured_file()
        valid_content = self.filename.read_text(encoding='utf-8')
        changes = (
            ('DJANGO_DEBUG', 'true'), ('MAILSEND_DELIVERY_MODE', 'demo'),
            ('DJANGO_TRUST_PROXY', 'true'), ('DJANGO_ALLOWED_HOSTS', '*'),
            ('DJANGO_CSRF_TRUSTED_ORIGINS', f'http://{HOST}'),
            ('GOOGLE_REDIRECT_URI', f'http://{HOST}/accounts/google/callback/'),
            ('DJANGO_SECRET_KEY', 'weak-secret-not-for-production'),
            ('MAILSEND_TOKEN_ENCRYPTION_KEY', ''),
            ('MAILSEND_DATA_DIR', str(ROOT)),
        )
        for name, value in changes:
            with self.subTest(setting=name):
                self.filename.write_text(valid_content, encoding='utf-8')
                set_key(str(self.filename), name, value)
                with patch.dict(os.environ):
                    before = dict(os.environ)
                    with self.assertRaises(ValueError):
                        self.load()
                    self.assertEqual(dict(os.environ), before)
                self.assertFalse((self.data / 'db.sqlite3').exists())

    def test_loader_uses_only_explicit_file_and_preserves_host_outbound_proxy(self):
        self.configured_file()
        values = dotenv_values(self.filename, interpolate=False)
        poisoned = {
            'DJANGO_DEBUG': 'true', 'DJANGO_ALLOWED_HOSTS': 'attacker.org',
            'DJANGO_SETTINGS_MODULE': 'not_the_real_settings', 'DJANGO_DB_PATH': str(self.base / 'wrong.sqlite3'),
            'DJANGO_SECRET_KEY_FILE': str(self.base / 'nonexistent-secret'),
            'MAILSEND_DELIVERY_MODE': 'demo', 'MAILSEND_DATA_DIR': str(self.base / 'wrong-data'),
            'GOOGLE_CLIENT_ID': 'ambient-alias.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'ambient-secret-must-be-cleared',
            'GOOGLE_OAUTH_CLIENT_SECRET_FILE': str(self.base / 'nonexistent-oauth-secret'),
            'WAITRESS_TRUSTED_PROXY': '*', 'PYTHON_DOTENV_DISABLED': '0',
            'HTTP_PROXY': 'http://proxy.example.test:3128', 'HTTPS_PROXY': 'http://proxy.example.test:3128',
        }
        with patch.dict(os.environ, poisoned):
            loaded = self.load()
            self.assertEqual(loaded['DJANGO_SECRET_KEY'], values['DJANGO_SECRET_KEY'])
            self.assertEqual(os.environ['MAILSEND_DATA_DIR'], str(self.data))
            self.assertEqual(os.environ['MAILSEND_DELIVERY_MODE'], 'gmail')
            self.assertEqual(os.environ['DJANGO_DEBUG'], 'false')
            self.assertEqual(os.environ['DJANGO_SETTINGS_MODULE'], 'config.settings')
            self.assertEqual(os.environ['PYTHON_DOTENV_DISABLED'], '1')
            self.assertNotIn('GOOGLE_CLIENT_SECRET', os.environ)
            self.assertNotIn('GOOGLE_OAUTH_CLIENT_SECRET_FILE', os.environ)
            self.assertNotIn('WAITRESS_TRUSTED_PROXY', os.environ)
            self.assertEqual(os.environ['HTTP_PROXY'], poisoned['HTTP_PROXY'])
            self.assertEqual(os.environ['HTTPS_PROXY'], poisoned['HTTPS_PROXY'])
        self.assertFalse((self.base / 'wrong.sqlite3').exists())
        self.assertFalse((self.data / 'db.sqlite3').exists())

    def test_wsgi_setup_is_configuration_only_and_never_runs_migrations_or_server(self):
        self.configured_file()
        result = self.child('''
            import json
            import sys
            from pathlib import Path
            from unittest.mock import patch
            from deploy.pythonanywhere import setup_application
            with patch('django.core.management.call_command', side_effect=AssertionError('Unexpected management operation')):
                application = setup_application(sys.argv[1])
            from django.conf import settings
            print(json.dumps({'callable': callable(application), 'debug': settings.DEBUG,
                'delivery': settings.MAILSEND_DELIVERY_MODE, 'database': str(settings.DATABASES['default']['NAME']),
                'proxy_header': settings.SECURE_PROXY_SSL_HEADER, 'secret': settings.SECRET_KEY,
                'exists': Path(settings.DATABASES['default']['NAME']).exists()}))
        ''', self.filename, DJANGO_DEBUG='true', MAILSEND_DELIVERY_MODE='demo',
            DJANGO_DB_PATH=str(self.base / 'ambient.sqlite3'), DJANGO_TRUST_PROXY='true')
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(observed.pop('callable'))
        self.assertEqual(observed.pop('secret'), dotenv_values(self.filename)['DJANGO_SECRET_KEY'])
        self.assertEqual(observed, {'debug': False, 'delivery': 'gmail', 'database': str(self.data / 'db.sqlite3'),
                                    'proxy_header': None, 'exists': False})
        self.assertFalse((self.base / 'ambient.sqlite3').exists())

    def test_already_configured_process_is_not_reconfigured(self):
        from deploy.pythonanywhere import load_environment, setup_application
        self.configured_file()
        with patch.dict(os.environ):
            before = dict(os.environ)
            for action in (load_environment, setup_application):
                with self.subTest(action=action.__name__), self.assertRaises(ValueError):
                    action(self.filename)
                self.assertEqual(dict(os.environ), before)
        self.assertFalse((self.data / 'db.sqlite3').exists())

    def test_management_and_wsgi_share_persistent_database_and_native_https(self):
        self.configured_file()
        result = self.cli('prepare')
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli('manage', 'shell', '-c',
                          "from django.contrib.auth import get_user_model; get_user_model().objects.create_user('pa-management-probe')")
        self.assertEqual(result.returncode, 0, result.stderr)
        private = self.data / 'private_media'
        private.mkdir(parents=True, exist_ok=True)
        (private / 'private-probe.txt').write_text('NEVER_PUBLIC_PA_CONTENT', encoding='utf-8')
        result = self.child('''
            from io import BytesIO
            import json
            import logging
            import sys
            from wsgiref.util import setup_testing_defaults
            from deploy.pythonanywhere import setup_application
            application = setup_application(sys.argv[1])
            from django.conf import settings
            from django.contrib.auth import get_user_model
            from django.contrib.staticfiles.storage import staticfiles_storage
            logging.getLogger('django.security.DisallowedHost').setLevel(logging.CRITICAL)
            host = settings.ALLOWED_HOSTS[0]
            def request(path, scheme='https', forwarded='http', request_host=None):
                environ = {}
                setup_testing_defaults(environ)
                environ.update({'PATH_INFO': path, 'REQUEST_METHOD': 'GET', 'wsgi.url_scheme': scheme,
                    'HTTP_HOST': request_host or host, 'SERVER_NAME': host,
                    'HTTP_X_FORWARDED_PROTO': forwarded, 'HTTP_X_FORWARDED_HOST': 'spoofed.example.test',
                    'wsgi.input': BytesIO(b''), 'CONTENT_LENGTH': '0'})
                captured = {}
                def start_response(status, headers, exc_info=None):
                    captured.update(status=int(status.split()[0]), headers=dict(headers))
                response = application(environ, start_response)
                try:
                    body = b''.join(response)
                finally:
                    if hasattr(response, 'close'):
                        response.close()
                return captured, body
            health, body = request('/healthz/')
            redirect, _ = request('/healthz/', scheme='http', forwarded='https')
            asset_url = staticfiles_storage.url('mail/app.css')
            asset, css = request(asset_url)
            forbidden, _ = request('/healthz/', request_host='wrong.example.test')
            private, private_body = request('/private_media/private-probe.txt')
            environment, environment_body = request('/static/private.env')
            print(json.dumps({'management_user_found': get_user_model().objects.filter(username='pa-management-probe').exists(),
                'database': str(settings.DATABASES['default']['NAME']), 'health': health['status'], 'health_json': json.loads(body),
                'redirect': redirect['status'], 'location': redirect['headers'].get('Location'),
                'static': asset['status'], 'css_nonempty': bool(css), 'hashed_asset': asset_url != '/static/mail/app.css',
                'wrong_host': forbidden['status'], 'private': private['status'],
                'private_exposed': b'NEVER_PUBLIC_PA_CONTENT' in private_body,
                'environment': environment['status'], 'secret_exposed': settings.SECRET_KEY.encode() in environment_body}))
        ''', self.filename)
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(observed, {
            'management_user_found': True, 'database': str(self.data / 'db.sqlite3'),
            'health': 200, 'health_json': {'status': 'ready'},
            'redirect': 301, 'location': f'https://{HOST}/healthz/',
            'static': 200, 'css_nonempty': True, 'hashed_asset': True, 'wrong_host': 400,
            'private': 404, 'private_exposed': False, 'environment': 404, 'secret_exposed': False,
        })
