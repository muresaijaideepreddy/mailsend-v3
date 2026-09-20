FROM python:3.13.15-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    DJANGO_DEBUG=false \
    MAILSEND_DELIVERY_MODE=gmail \
    MAILSEND_DATA_DIR=/data

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt \
    && groupadd --gid 10001 mailsend \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin mailsend \
    && mkdir -p /data \
    && chown 10001:10001 /data

# Explicit source allowlist: local environment, databases and uploads are never copied.
COPY config /app/config
COPY mail /app/mail
COPY templates /app/templates
COPY static /app/static
COPY deploy /app/deploy
COPY manage.py /app/manage.py

USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM
ENTRYPOINT ["python", "-m", "deploy.start"]

