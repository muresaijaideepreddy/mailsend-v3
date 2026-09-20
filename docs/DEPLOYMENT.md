# MailSend V3 production deployment

This package prepares a single Linux host deployment with Docker Compose, Caddy HTTPS and one nonroot Waitress application process. It has not been published to a server. Supply a real host, domain and Google OAuth application before deploying. The current development `.env`, database, accounts and private files are not deployment inputs.

V3 messages are sent only after an executive approves them in the app. There is no scheduled sender, inbox synchronization job or background mail worker. The Inbox remains inactive under the V3 design.

## Prerequisites

- A Linux server with Docker Engine and Docker Compose v2, sufficient disk space for private attachments, and the source checkout.
- A real public DNS hostname whose A/AAAA records point to that server. Open inbound TCP 80/443 and optionally UDP 443 for Caddy. Allow outbound HTTPS for Google and certificate issuance. Do not publish app port 8000.
- A Google OAuth web client with the exact authorized redirect URI `https://YOUR_REAL_DOMAIN/accounts/google/callback/`. Configure the consent screen and Gmail send permission as appropriate for your Google project. Readiness checks configuration format; only a live authorized sign-in and controlled delivery can establish provider readiness.
- Python 3 for the optional secret-file initialization helper (standard library only).

## Configure private values

Run these commands from the checkout on the target server. The real environment file stays outside the checkout; the helper refuses to overwrite an existing file and does not print secrets.

```sh
umask 077
mkdir -p "$HOME/.config/mailsend"
chmod 700 "$HOME/.config/mailsend"
export MAILSEND_ENV_FILE="$HOME/.config/mailsend/production.env"
python3 -m deploy.initialize_env "$MAILSEND_ENV_FILE"
```

Edit that private file and set `MAILSEND_DOMAIN`, `MAILSEND_TLS_EMAIL`, `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`. The helper generates a strong Django secret and a Fernet encryption key. Preserve both across restarts and upgrades. Do not reuse demonstration credentials or regenerate the encryption key for an existing database; encrypted Google credentials depend on it.

Compose sets production mode, Gmail delivery, exact allowed host/CSRF origin, the callback URL, the trusted proxy and `/data`. Missing or unsafe production settings abort startup. The app rejects DEBUG mode, demo delivery, weak Django secrets, missing Google credentials/encryption keys, wildcard/placeholder hosts, mismatched or insecure callback/CSRF URLs, insecure cookies, and database/private media paths outside the explicit persistent directory.

For a secret manager, use `DJANGO_SECRET_KEY_FILE`, `GOOGLE_OAUTH_CLIENT_SECRET_FILE` and `MAILSEND_TOKEN_ENCRYPTION_KEY_FILE` instead of their direct values. Mount those secret files read-only and provide their container paths. Setting both forms is rejected. Do not pass secrets as command-line arguments or build arguments. Avoid `docker compose config` without `--quiet`, because its expanded output includes environment values.

## Build and start

```sh
docker compose --env-file "$MAILSEND_ENV_FILE" config --quiet
docker compose --env-file "$MAILSEND_ENV_FILE" build --pull
docker compose --env-file "$MAILSEND_ENV_FILE" up -d
docker compose --env-file "$MAILSEND_ENV_FILE" ps
docker compose --env-file "$MAILSEND_ENV_FILE" exec app python manage.py check_readiness
```

Startup validates configuration, creates persistent directories, applies migrations, collects compressed and hashed static assets, runs Django's deployment checks and checks database/migration readiness and known demo accounts. An unsuccessful check prevents the WSGI server from starting. The image copies an explicit source allowlist; `.env`, the local database, demo messages and private uploads are excluded from the build context and image.

The app runs as UID/GID 10001 with a read-only root filesystem. Its named volume holds `/data/db.sqlite3`, `/data/private_media` and generated `/data/staticfiles`; uploads are served only by authenticated application endpoints. WhiteNoise serves only the collected static directory. A bind mount, if substituted for the named volume, must be writable by UID/GID 10001 before starting.

Caddy obtains and renews certificates and redirects HTTP to HTTPS. It overwrites incoming forwarded protocol headers. Waitress accepts that protocol header only behind the unpublished Compose app port; this Compose-only network boundary is why `WAITRESS_TRUSTED_PROXY=*` is set. Do not reuse this wildcard configuration on an app port accessible to untrusted clients. If you add another reverse proxy or CDN, configure and review the new trust boundary first.

Waitress uses four request threads. SIGTERM stops accepting new connections, allows active work up to 30 seconds to finish, then closes remaining connections; Compose allows 45 seconds before forcing termination. During an upgrade, an interrupted provider request may have an uncertain outcome: use the app's reconciliation flow and verify Gmail before any retry.

## Operational verification

```sh
docker compose --env-file "$MAILSEND_ENV_FILE" exec app python manage.py check --deploy --fail-level WARNING
docker compose --env-file "$MAILSEND_ENV_FILE" exec app python manage.py check_readiness
```

Open `https://YOUR_REAL_DOMAIN/healthz/`: the response is only `{"status":"ready"}` or `{"status":"unavailable"}`, with HTTP 200 or 503 and no account/configuration data. The endpoint checks database connectivity and migration state. Compose probes the app every 30 seconds; its health status is visible through `ps`. An unhealthy container is marked unhealthy; Docker does not automatically restart a process solely because a health probe fails. Investigate before restarting.

Create the real executive workspace by the supported Google sign-in flow or run `docker compose --env-file "$MAILSEND_ENV_FILE" exec app python manage.py create_workspace --username REAL_USERNAME --email REAL_EMAIL --name REAL_WORKSPACE_NAME`, which prompts for the password. Add assistants through Worker accounts. Use separate production identities and data. The readiness command intentionally refuses the known synthetic demo identities/default demo password; it does not delete or modify accounts.

Verify the login page and CSS over HTTPS, secure cookies, sign-in/consent, assistant draft access, executive confirmation, and one explicitly authorized message to a controlled recipient. Check the corresponding Gmail account and Sent history. This real provider check is not performed by startup, tests or this deployment package.

## Backups and recovery

Back up the database, private media and encryption key as one recovery set. Store encrypted copies outside the host with restricted access and a documented retention policy. Keep secrets separate from ordinary application logs/source artifacts. Caddy's `caddy_data` and `caddy_config` volumes hold certificate/account state and should also be included in host backup planning.

For a simple consistent cold backup, choose a private backup directory outside the checkout, stop the app, copy its entire `/data` directory from the stopped container, and restart the app. For example:

```sh
umask 077
backup_dir="$HOME/mailsend-backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"
docker compose --env-file "$MAILSEND_ENV_FILE" stop app
docker compose --env-file "$MAILSEND_ENV_FILE" cp app:/data "$backup_dir/data"
docker compose --env-file "$MAILSEND_ENV_FILE" start app
```

Confirm that copying succeeded before restarting, and confirm the app becomes healthy afterward. This backup briefly interrupts access; do it during a maintenance window with no pending send operation. Back up the matching private environment/secrets through your secret manager; do not include them in shared reports. Copying a live SQLite file while it is being written is not a substitute for this procedure. Use SQLite's backup API or filesystem snapshots if you later need online backups, and account for consistency with private attachments.

To recover, first preserve the failed deployment's current data. Restore the recovery set into an empty replacement volume owned by UID/GID 10001, restore its matching secret/encryption key, and start the same application image version that produced the backup. Run readiness and inspect representative messages and authorized attachment downloads before allowing use. Rehearse recovery on an isolated host with outbound mail blocked. Never test recovery by overwriting the only production volume. `docker compose down -v` deletes named volumes and must not be used for routine upgrades.

## Upgrades and limits

Take a verified recovery set, stop the app during the maintenance window, rebuild the reviewed source with `build --pull`, then recreate it with `up -d`. Startup applies forward migrations. An older application image may not work with a migrated database: rollback requires a compatible recovery set, not just changing the image tag. Rotate secrets only through a planned migration; replacing the encryption key alone makes existing credentials unreadable.

This topology is one application instance on one host with local SQLite storage. Do not scale app replicas or share SQLite over network filesystems. A multi-instance deployment needs a supported server database, shared private storage, coordinated migrations and additional operational testing.

## Verification completed in this checkout

The isolated deployment tests cover invalid production settings, weak keys and dual secret sources; secret-file configuration and initialization that refuses to overwrite keys; missing migrations and known demo accounts; generic health responses; and a fresh production subprocess that applies migrations, collects/serves hashed CSS, runs `check --deploy`, enforces HTTPS/host/CSRF rules and blocks direct private-media access. A separate real Waitress process binds only to `127.0.0.1` and is checked through HTTP for health, static serving, forwarded protocol, HTTPS redirect, host rejection and its signal-driven shutdown. Both processes use synthetic settings/data, and the socket guard permits only loopback traffic. No external mail is sent by these tests.

Docker is unavailable in the current Windows environment. Therefore container build/start, Caddy certificate issuance, public DNS/firewall behavior, a real Google consent/delivery run, and a restore rehearsal remain to be verified on the chosen host. No live host or domain has been supplied or deployed.

Configuration references: [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/), [WhiteNoise Django integration](https://whitenoise.readthedocs.io/en/stable/django.html), [WhiteNoise 6.12.0 on PyPI](https://pypi.org/project/whitenoise/6.12.0/), [Waitress proxy settings](https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html), [Caddy reverse proxy and HTTPS](https://caddyserver.com/docs/quick-starts/reverse-proxy), [official Python image tags](https://github.com/docker-library/official-images/blob/master/library/python), [official Caddy image tags](https://github.com/docker-library/official-images/blob/master/library/caddy).
