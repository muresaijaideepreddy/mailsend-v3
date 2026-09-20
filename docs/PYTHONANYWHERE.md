# MailSend V3 on PythonAnywhere

This guide deploys the existing Django app using PythonAnywhere's native WSGI hosting. Use the free Beginner plan for a small, controlled demonstration. The public demo is deployed at https://jaideepreddy05.pythonanywhere.com/; deployment evidence and remaining checks are recorded in [PYTHONANYWHERE_LIVE_STATUS.md](PYTHONANYWHERE_LIVE_STATUS.md). Local tests alone do not establish live Google delivery.

V3 stays unchanged: assistants prepare drafts, executives explicitly send them, and dates never trigger unattended delivery. Production configuration requires Gmail delivery and refuses demo transport.

Local validation on September 20, 2026: all **284 automated tests passed**, including eight new PythonAnywhere regressions; Django checks and migration consistency also passed. These checks use synthetic data and blocked external networking. Separate host checks verified Linux private-file permissions, successful migrations and deployment checks, and the public HTTPS login page. Hosted Google delivery still needs its own verification. See [test results](V3_TEST_RESULTS.json) and [live status](PYTHONANYWHERE_LIVE_STATUS.md).

## Free-plan limits

As checked on September 20, 2026, the free plan has one web app with one web worker, 512 MiB total disk space, two consoles and a one-month web-app expiry that must be extended through the account. New free accounts have no MySQL database or scheduled task. V3 does not need a scheduled sender. [Free account features](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/)

This deployment uses SQLite and private attachments under the account's persistent home directory. PythonAnywhere explicitly discourages SQLite as a production database because of filesystem performance. Keep demo batches and attachments small and avoid simultaneous maintenance writes. This free setup is not the single-host production topology described in [DEPLOYMENT.md](DEPLOYMENT.md); sustained buyer use needs a supported server database, capacity planning and recovery testing. [Database guidance](https://help.pythonanywhere.com/pages/KindsOfDatabases)

The free outbound allowlist includes Google and Google APIs. The app uses HTTPS requests to the Gmail API; it does not use SMTP. Preserve PythonAnywhere's proxy environment. Successful Google consent and one authorized delivery must still be checked on the actual host. [Allowlist](https://www.pythonanywhere.com/whitelist/)

## 1. Sign in and upload source

Sign in to a PythonAnywhere account, or create a free Beginner account. The account's assigned web hostname will normally be `PA_USERNAME.pythonanywhere.com` (or `PA_USERNAME.eu.pythonanywhere.com` on the EU service). Substitute the actual username and hostname below.

Upload the reviewed source-only `MailSend-V3-PythonAnywhere.zip` through the Files page into the account home directory. It contains the `mailsend-v3/` source folder. In a Bash console:

```sh
umask 077
cd "$HOME"
unzip MailSend-V3-PythonAnywhere.zip
cd "$HOME/mailsend-v3"
```

For the first deployment, use a new source folder. Do not unzip over an existing live checkout during a send. An authenticated HTTPS Git clone is another option if private-repository access is already configured. Do not place a GitHub access token in a clone URL or command history.

The upload must exclude `.env`, local databases, Google tokens, `.local-secret`, `private_media`, `demo_outbox`, `.venv`, logs and backups. Never upload the local Gmail demo directory as a whole. Do not run `seed_demo` on the public host.

## 2. Create a virtual environment

Use a supported Python version of 3.11 or newer, and select that same version when creating the Web app. The example uses Python 3.13; confirm it is available on the account before running it.

```sh
python3.13 -m venv "$HOME/.virtualenvs/mailsend"
source "$HOME/.virtualenvs/mailsend/bin/activate"
python -m pip install --no-cache-dir -r requirements.txt
python -m pip check
```

Avoid installing development tools and test dependencies on the free account. The virtual environment, source, database and uploaded files share the disk allowance.

## 3. Initialize private configuration

Use separate directories for source, configuration and data. Run from `mailsend-v3` with the virtual environment active:

```sh
umask 077
mkdir -p "$HOME/.config/mailsend" "$HOME/.local/share/mailsend"
chmod 700 "$HOME/.config/mailsend" "$HOME/.local/share/mailsend"
export MAILSEND_ENV_FILE="$HOME/.config/mailsend/production.env"
python -m deploy.pythonanywhere --env "$MAILSEND_ENV_FILE" init \
  --host PA_USERNAME.pythonanywhere.com \
  --data "$HOME/.local/share/mailsend"
```

The helper creates new Django and encryption keys without printing them and refuses to overwrite an existing file. Keep those keys stable across restarts and upgrades. Configuration is loaded explicitly from this private file; an old checkout `.env` or unrelated application environment cannot supply missing settings.

Edit that private file on PythonAnywhere and fill only the real `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` initially. Keep the generated keys. Do not paste secrets into chat, source files or logs. The Google client secret is an application credential, not the executive's Gmail password.

In the matching Google Cloud OAuth **Web application** client, add this exact authorized redirect URI:

```text
https://PA_USERNAME.pythonanywhere.com/accounts/google/callback/
```

Use the actual EU hostname if applicable. Enable the Gmail API and configure the consent screen/test users for the executive and assistants who will demonstrate the app. The executive authorizes Gmail sending through the application; the assistant links Google for identity only. Follow [Google's web-server OAuth guidance](https://developers.google.com/identity/protocols/oauth2/web-server).

Keep `DJANGO_DEBUG=false`, `MAILSEND_DELIVERY_MODE=gmail`, `DJANGO_TRUST_PROXY=false`, and HTTPS enabled. The provider's native WSGI request scheme is used. Do not enable forwarded-header trust to hide an HTTPS redirect loop; inspect the actual host configuration first.

## 4. Prepare the fresh database and static files

After completing the private configuration:

```sh
python -m deploy.pythonanywhere --env "$MAILSEND_ENV_FILE" prepare
```

This validates production settings, applies migrations, collects static files, runs Django's deployment checks and checks readiness. It does not start a server or send any email. Missing or unsafe configuration must be corrected before publishing.

For later management commands, use the same loader and private environment:

```sh
python -m deploy.pythonanywhere --env "$MAILSEND_ENV_FILE" manage check_readiness
```

## 5. Configure the Web app

On PythonAnywhere's **Web** tab, add a web app using **Manual configuration**, then choose the same Python version used for the virtual environment. [Official Django deployment guide](https://help.pythonanywhere.com/pages/DeployExistingDjangoProject/)

Set:

| Field | Value |
| --- | --- |
| Source code | `/home/PA_USERNAME/mailsend-v3` |
| Working directory | `/home/PA_USERNAME/mailsend-v3` |
| Virtualenv | `/home/PA_USERNAME/.virtualenvs/mailsend` |

Open the WSGI configuration file linked on that Web page. Replace its sample application with [pythonanywhere_wsgi.py.example](../deploy/pythonanywhere_wsgi.py.example), substituting the actual absolute paths. This is PythonAnywhere's WSGI file, not the repository's `config/wsgi.py`.

The WSGI adapter loads the private configuration and returns the Django application. It does not run migrations or start Waitress. Do not run `manage.py runserver`, `deploy.start`, Docker or `start-live.ps1` to serve this hosted application.

WhiteNoise serves the collected `/static/` assets, so no static mapping is needed initially. **Never create a public mapping for the private data directory, `private_media`, the configuration directory or the entire source checkout.** Attachments must pass through the authenticated Django download route.

Enable **Force HTTPS**, then click **Reload**. [HTTPS instructions](https://help.pythonanywhere.com/pages/ForcingHTTPS/)

## 6. Verify before the live demo

Use the actual public HTTPS URL and fresh accounts. This is the complete verification checklist; consult [live status](PYTHONANYWHERE_LIVE_STATUS.md) for which checks have been completed on this account:

- `/healthz/` returns HTTP 200 with `{"status":"ready"}`; the login page and CSS load correctly.
- HTTP redirects to HTTPS; HTTPS has no redirect loop; session and CSRF cookies are secure.
- Database, environment and direct private-upload URLs are inaccessible.
- Executive Google sign-in completes at the public callback and creates the correct workspace.
- The executive sets up a worker; local login works. The worker links their matching Google account once, then subsequent Google sign-in enters the same assistant account.
- The assistant saves a draft with an attachment; the executive can review it. The assistant cannot send or access another workspace.
- Past/today drafts appear in Current; future drafts stay out of Send Current. Reviewing and saving never send.
- After explicit authorization for a controlled recipient and message, the executive sends one email. Confirm the app's receipt, the sending Gmail account and recipient arrival. Automated provider mocks and a local Gmail test do not substitute for this hosted test.
- Reload the Web app and confirm drafts, attachments and Google connection survive. Run readiness again.

Do not publish the local demo password or import its accounts. Workers get their own credentials from the executive. Keep the free app's expiry extended and check disk usage before each demo.

## Maintenance and recovery

Do maintenance with the Web app disabled and no send in progress. Preserve a recovery set containing the SQLite database, private attachments and matching secret configuration. Download an encrypted backup to a restricted location outside the hosting account; the free disk allowance makes accumulating backups on the same host unsuitable. Rehearse restoration in an isolated environment with outbound mail blocked before calling the setup production-ready.

For updates, take that recovery set, update only reviewed source, activate the same virtual environment, install changed requirements, run `prepare` with the existing private environment, and reload the Web app. Recheck health and an authenticated draft/attachment. Never rerun initialization over existing keys or replace the encryption key without a planned credential migration.

If delivery is marked `sending` or `uncertain` after an interruption, inspect the executive's Gmail Sent folder. The app blocks automatic retries but has no reconciliation screen or command. Preserve the record and involve the operator; do not reset the status, recreate the message, or retry a possibly accepted delivery without resolving its outcome.
