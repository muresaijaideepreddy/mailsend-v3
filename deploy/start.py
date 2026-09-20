"""Prepare one production instance and serve WSGI with bounded shutdown."""
import logging
import os
from pathlib import Path
import signal
import sys
import threading
import time


def serve(application, *, host='0.0.0.0', port=8000):
    from waitress import create_server, wasyncore

    options = dict(host=host, port=port, threads=4, channel_timeout=120,
                   asyncore_loop_timeout=0.25, max_request_body_size=30 * 1024 * 1024,
                   clear_untrusted_proxy_headers=True, ident='MailSend')
    proxy = os.getenv('WAITRESS_TRUSTED_PROXY', '')
    if proxy:
        options.update(trusted_proxy=proxy, trusted_proxy_count=1,
                       trusted_proxy_headers={'x-forwarded-proto'})
    server = create_server(application, **options)
    stopping = threading.Event()
    def stop(signum, frame):
        stopping.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    worker = threading.Thread(target=server.run, name='waitress-network', daemon=True)
    worker.start()
    logging.getLogger(__name__).info('MailSend WSGI server started.')
    try:
        while not stopping.wait(0.5):
            if not worker.is_alive():
                raise RuntimeError('WSGI network loop stopped unexpectedly.')
    finally:
        # Stop accepting new sockets while the network loop drains active work.
        # Keep the trigger and existing channels alive while handlers finish.
        wasyncore.dispatcher.close(server)
        server.task_dispatcher.shutdown(cancel_pending=True, timeout=30)
        # Let the still-running network loop flush responses that handlers just
        # completed, without allowing a slow client to hold shutdown open.
        flush_deadline = time.monotonic() + 2
        while (any(channel.total_outbufs_len for channel in list(server.active_channels.values()))
               and time.monotonic() < flush_deadline):
            time.sleep(0.05)
        server.close()
        wasyncore.close_all(map=server._map, ignore_all=True)
        worker.join(timeout=2)


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    from django.conf import settings
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application
    from config.production import production_errors

    # Settings reject unsafe production values before opening the database.
    errors = production_errors(settings)
    if errors:
        raise RuntimeError('Production configuration rejected: ' + ' '.join(errors))
    for directory in (settings.MAILSEND_DATA_DIR, settings.MEDIA_ROOT, settings.STATIC_ROOT):
        Path(directory).mkdir(parents=True, exist_ok=True)
    django.setup()
    call_command('migrate', interactive=False)
    call_command('collectstatic', interactive=False, verbosity=0)
    call_command('check', deploy=True, fail_level='WARNING')
    call_command('check_readiness')
    serve(get_wsgi_application())


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Expected configuration errors contain setting names only. Avoid raw
        # tracebacks/provider data in container logs; detailed checks are separate.
        logging.getLogger(__name__).error('Startup failed. Run manage.py check_readiness with the production environment.')
        sys.exit(1)
