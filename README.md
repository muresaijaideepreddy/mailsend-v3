# MailSend 3.0

A Python/Django implementation of the executive-and-assistant MailSend workflow. **V3 is the buyer's deliverable; V1 fills only details that V3 leaves unspecified.** See [requirements precedence](docs/PRODUCT_REQUIREMENTS.md) and the [current acceptance report](docs/V3_ACCEPTANCE_REPORT.md). Assistants prepare messages. Executives review and explicitly send them. The default demo transport writes local `.eml` files and never contacts recipients.

**New clone or GitHub handoff:** follow [GITHUB_SETUP.md](docs/GITHUB_SETUP.md) for upload, installation, demo credentials and test commands. Local accounts, Google tokens, mail and secret configuration are excluded from Git; a new clone starts with a fresh database.

## Run on Windows

For the already-configured local Gmail demo, run `powershell -ExecutionPolicy Bypass -File .\start-live.ps1`. This preserves accounts/settings, serves the local app and static files through Waitress, and sends real email only when the executive approves it. Use `-CheckOnly` to verify local setup without starting another server. See [LIVE_DEMO_START.md](docs/LIVE_DEMO_START.md). Public hosting uses [DEPLOYMENT.md](docs/DEPLOYMENT.md).

Python 3.11 or newer is required (implemented and tested on Python 3.13).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Fresh clone only: keep an existing .env unchanged.
if (!(Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Or run `powershell -ExecutionPolicy Bypass -File .\start-demo.ps1` from this directory. Open http://127.0.0.1:8000.

| Role | Username | Demo password |
| --- | --- | --- |
| Executive | `executive` | `MailSend-Demo-2026!` |
| Assistant | `assistant` | `MailSend-Demo-2026!` |

These are synthetic local accounts, unrelated to credentials in the reference documents. The seed command is idempotent and refuses production or Gmail mode. Existing account passwords are never overwritten. Conflicts with unrelated existing usernames, emails, or memberships are refused; weak custom demo passwords are also refused. Use `seed_demo --password <your-local-password>` when first creating demo accounts if preferred.

On macOS/Linux, use `python3`, `.venv/bin/python`, and the same management commands.

## What works

- Username/password login, logout, password change, and one shared Google sign-in button that identifies the account role. Assistants link their identity once; only executives grant Gmail sending access.
- One executive account per workspace with separate assistant accounts. Another executive can create a separate workspace through Google signup or `create_workspace`. Tenant and role checks are enforced by the server, including on file downloads and send services.
- Outbox search and all/current/future filters. Assistants see their own drafts; executives see all workspace drafts.
- Compose, edit, delete, To/CC/BCC, subject, plain-text body, required send date, optional planning time, and up to three attachments totaling 20 MiB. BCC CSV import supports up to 450 recipients across all recipient fields.
- Sequential executive review of current, future, or all editable messages. Review saves edits and never sends.
- Individual **Send now** (including future drafts) and **Send Current Messages** directly from the executive outbox. Current includes every editable draft dated today or earlier in the app timezone (`MAILSEND_TIME_ZONE`, default `America/Chicago`); Future includes later dates. Missing or later-today planning times do not affect these categories. Send Current covers the workspace regardless of the active search/filter.
- Clicking Send explicitly approves immediate delivery. Signed approvals capture message versions and the shared signature and expire after 30 minutes; changed drafts require a fresh approval. An optional batch preview is available. Saving, importing, opening a page, and reviewing never send automatically. Mailbox arrival time depends on the provider.
- Duplicate-send protection, delivery receipts, shared sent history, and audit records. Ambiguous delivery is held for manual reconciliation instead of automatically retried.
- Shared signature, appended once when the message is sent. Changing it invalidates pending approvals.
- New executive signup provisions an initial worker with login disabled until the executive sets its password. Worker settings always show the login username and allow profile/email and password management. No invitation email is automatically sent.
- CSV mail merge: upload, validate, preview every personalized message, then atomically create drafts. Commit is replay protected. No emails are sent by import.

The legacy Inbox tab is clearly identified as inactive, as described in the reference. It does not display fabricated Gmail content. V3 explicit executive approval takes precedence over the legacy auto-scheduling paragraph: dates organize drafts and **do not automatically send mail**.

## Try the workflow

1. Sign in as `assistant`. Create a draft, add an attachment, and save.
2. Sign out; sign in as `executive`. Review current messages and save edits.
3. Click a message's **Send now** button. It moves to Sent; a MIME email appears under `demo_outbox/`.
4. Try **Send Current Messages**. Drafts dated today or earlier are sent; future drafts remain in the outbox.
5. Try **Mail merge** with `examples/mail_merge.csv`, subject `Hello {{first_name}}`, and a body such as `Hello {{first_name}}, thank you for your work at {{organization}}.` Preview, then create the drafts.
6. Use two browser sessions to edit a draft after the executive loads the outbox. Sending from the stale outbox is refused until reloaded.

Demo email files can contain BCC and attachments. Keep them private, just like the database and attachment directory. They are ignored by Git and have no public download route.

## Connect Gmail

1. Create a Google Cloud project, enable the Gmail API, and configure its OAuth consent screen. Add test users while the app is in testing.
2. Create an OAuth **Web application** client. Register the exact callback `http://127.0.0.1:8000/accounts/google/callback/` for local development and your HTTPS callback for production.
3. Create `.env` from `.env.example` only if `.env` does not exist. Otherwise edit the existing file, preserving its secrets and encryption key. Set `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, and a Fernet token encryption key. For a new installation, generate the key with:

   ```powershell
   .\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

4. Restart the server. The shared **Sign in with Google** button first verifies identity. Linked assistants and executives with an existing sending connection sign in directly. A new executive or an executive needing to reconnect continues to Gmail consent for the same Google account; a new workspace and initial worker are created only after that grant succeeds. Existing local accounts are never silently linked by email alone.
5. For an assistant, the executive first sets the worker's email and password. The assistant signs in locally and chooses **Link Google sign-in** in the account menu, using that same email. Subsequent logins use the shared Google button. Assistant linking and login request identity scopes only and cannot change the assistant role or authorize sending.

6. Change `MAILSEND_DELIVERY_MODE=gmail` and restart only when ready to send real mail. An executive must still approve every send. There is no automatic fallback to demo mode if Gmail fails.

Worker settings automatically supplies an initial username for an older workspace that has no assistants, too. The executive sets its password before the assistant can log in; email is needed for Google linking. Existing assistant accounts are preserved. Additional accounts can be created in the executive's **Add an assistant** form.

The legacy names `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are also accepted; the `GOOGLE_OAUTH_` names take precedence when nonempty. A `redirect_uri_mismatch` error means the exact `GOOGLE_REDIRECT_URI` (including scheme, host, port, path and trailing slash) must be added to the OAuth client in Google Cloud.

Executive tokens are encrypted at rest; the key must be kept stable and backed up securely. Executive scopes are identity scopes plus `gmail.send`; reading the inbox is not requested. The assistant identity flow retains its verified identity mapping without retaining Google access/refresh tokens. A disconnected Google-only account retains its identity mapping and can authenticate again.

OAuth consent configuration/verification depends on the Google project. Automated integration tests mock Google responses and never send external mail. An authorized live test has now been accepted by Gmail; see [LIVE_GMAIL_VERIFICATION.md](docs/LIVE_GMAIL_VERIFICATION.md) for its evidence and remaining checks.

Official references: [Google server-side Gmail authorization](https://developers.google.com/workspace/gmail/api/auth/web-server), [Gmail send API](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send), [Django supported releases](https://www.djangoproject.com/download/).

## Validation

```powershell
.\.venv\Scripts\python.exe manage.py test mail.tests -v 2
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

See [the current acceptance report](docs/V3_ACCEPTANCE_REPORT.md) for every document requirement and the latest full test results. It includes the PDF's December 1/2/3 example, date boundaries, role/workspace isolation, Google identity flows, CSV/MIME, attachment edits, stale/replayed approval rejection, and production startup checks. Browser checks use a separate synthetic demo database. Provider tests mock Google; no external emails are sent by this suite.

To measure coverage separately, install `requirements-dev.txt`, then run `python -m coverage run manage.py test mail.tests` and `python -m coverage html`. Earlier test/coverage reports are historical, not fresh coverage measurements of this revision.

## Deployment and operations

For the selected free demo host, follow [PythonAnywhere setup](docs/PYTHONANYWHERE.md). It uses native WSGI hosting with private configuration and fresh data. Account access, public Google callback configuration and hosted acceptance checks are still required before the demo is live.

The repository now includes a production Docker Compose package: nonroot Waitress, Caddy HTTPS, WhiteNoise static assets, persistent SQLite/private uploads, health/readiness checks, startup validation and a backup/recovery runbook. Follow [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

Production startup refuses demo mode, unsafe/missing configuration, pending readiness failures and known demo accounts. Deploy using a fresh database and independent secrets. Private attachments have authenticated download routes and must never have a public media alias. The included topology supports one application instance on one Linux host.

A process crash after a send claim leaves a `sending` message; a timeout leaves `uncertain`. Check Gmail Sent before manual reconciliation. Neither state is automatically resent because the provider may have accepted the email.

The package has not been published to a server. Docker/Caddy, public TLS/DNS, backup restoration and live Google consent/delivery require verification on the selected host. Local production subprocess and real loopback Waitress checks do not replace those deployment checks.

The Ruby repository was not available in this workspace. This implementation reproduces documented behavior; direct Ruby data migration and live parity testing require that repository and access to a separate test account.


The reference UI comparison and latest visual verification are documented in `docs/UI_ALIGNMENT.md`. The running interface now follows the supplied MailSend screenshots while retaining the tested Django backend and Google connection.

Synthetic CSV upload examples are in `examples/qa/`, and synthetic live-demo attachments are in `examples/live-demo/`. The local app was explicitly switched to Gmail delivery for the authorized live test. Historical reports of earlier Gmail tests are separate from the current [live verification](docs/LIVE_GMAIL_VERIFICATION.md).
