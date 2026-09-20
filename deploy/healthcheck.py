"""Container-only HTTP probe; no credentials or mail-provider requests."""
import os
import sys
from urllib.request import Request, urlopen


def main():
    host = os.environ['DJANGO_ALLOWED_HOSTS'].split(',')[0].strip()
    request = Request('http://127.0.0.1:8000/healthz/', headers={
        'Host': host, 'X-Forwarded-Proto': 'https',
    })
    try:
        with urlopen(request, timeout=5) as response:
            return 0 if response.status == 200 else 1
    except Exception:
        return 1


if __name__ == '__main__':
    sys.exit(main())
