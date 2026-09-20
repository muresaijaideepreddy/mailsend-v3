"""Create a private deployment template without printing generated secrets."""
import argparse
import base64
import os
from pathlib import Path
import secrets


def initialize(filename):
    path = Path(filename).expanduser()
    template = Path(__file__).with_name('production.env.example').read_text(encoding='utf-8')
    template = template.replace('DJANGO_SECRET_KEY=\n', 'DJANGO_SECRET_KEY=' + secrets.token_urlsafe(64) + '\n')
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii')
    template = template.replace('MAILSEND_TOKEN_ENCRYPTION_KEY=\n', 'MAILSEND_TOKEN_ENCRYPTION_KEY=' + key + '\n')
    # Exclusive creation prevents accidental rotation of keys protecting existing data.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(template)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', help='New private environment file outside the checkout')
    args = parser.parse_args()
    try:
        initialize(args.path)
    except OSError:
        parser.exit(1, 'Could not create the private file. Check directory access and use a new filename.\n')
    print('Private environment template created. Fill the real domain, TLS contact and Google OAuth credentials before starting.')
