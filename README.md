# MailSend 3.0

**Using the app:** see the [complete application guide](docs/MAILSEND_GUIDE.md), including worker/executive workflows, every tab, imports, contacts, troubleshooting and current limitations. Workers also have an in-app **Help** tab with expandable FAQs. Keep these documents current when behavior changes, as required by [AGENTS.md](AGENTS.md).

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

- Username/password login, logout, password change, and one Google sign-in button for executives. Assistants use only their assigned username and password; no assistant email is required.
- One executive account per workspace with separate assistant accounts. Another executive can create a separate workspace through Google signup or `create_workspace`. Tenant and role checks are enforced by the server, including on file downloads and send services.
- Outbox search and all/current/future filters. Assistants see their own drafts and can view/edit executive-created drafts in the same workspace; executives see all workspace drafts. Other assistants' unsent drafts remain private.
- Compose, edit, delete, To/CC/BCC, subject, plain-text body, required send date, and up to three attachments totaling 20 MiB. BCC CSV import supports up to 450 recipients across all recipient fields.
- Sequential executive review of current, future, or all editable messages. Review saves edits and never sends.
- Individual **Send now** (including future drafts) and **Send Current Messages** directly from the executive outbox. Current includes every editable draft dated today or earlier in the app timezone (`MAILSEND_TIME_ZONE`, default `America/Chicago`); Future includes later dates. Send Current covers the workspace regardless of the active search/filter.
- Clicking Send explicitly approves immediate delivery. Signed approvals capture message versions and the shared signature and expire after 30 minutes; changed drafts require a fresh approval. An optional batch preview is available. Saving, importing, opening a page, and reviewing never send automatically. Mailbox arrival time depends on the provider.
- Duplicate-send protection, delivery receipts, shared sent history, and audit records. Ambiguous delivery is held for manual reconciliation instead of automatically retried.
- Shared signature, appended once when the message is sent. Changing it invalidates pending approvals.
- New executive workspaces start without workers. The executive adds each worker with a username and password in Worker settings, which also supports name and password management. No invitation email is automatically sent.
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

4. Restart the server. The **Sign in with Google** button is for executives and first verifies identity. Executives with an existing sending connection sign in directly. A new executive or an executive needing to reconnect continues to Gmail sending and read-only contacts consent for the same Google account; a new executive workspace is created only after that grant succeeds. Workers are added separately by the executive. Existing local accounts are never silently linked by email alone.
5. For an assistant, the executive provides a username and sets a password. No email address is collected. Assistants sign in only through the username/password form; Google linking and login are blocked, including previously linked identities.

6. Change `MAILSEND_DELIVERY_MODE=gmail` and restart only when ready to send real mail. An executive must still approve every send. There is no automatic fallback to demo mode if Gmail fails.

Worker settings starts empty until the executive uses **Add an assistant**. No account is created by opening that page. The upgrade retires untouched automatic placeholders by disabling their login and hiding them from the worker list; configured or used accounts and all stored records are preserved. Workers can edit/delete their own unsent drafts, including after executive edits, and can view/edit executive-created drafts and their attachments. Workers cannot delete executive-created drafts or send any message. Edits retain the original author, record the editing worker in the audit history, and invalidate earlier approvals. Sent history is shared within the workspace. V3 requires the assistant's own drafts to appear but does not specify the executive-created draft case; collaborative access follows the user's latest clarification. See the acceptance report for this change's verification and deployment status.

The legacy names `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are also accepted; the `GOOGLE_OAUTH_` names take precedence when nonempty. A `redirect_uri_mismatch` error means the exact `GOOGLE_REDIRECT_URI` (including scheme, host, port, path and trailing slash) must be added to the OAuth client in Google Cloud.

Executive tokens are encrypted at rest; the key must be kept stable and backed up securely. Executive scopes are identity scopes plus `gmail.send`; reading the inbox is not requested. Existing assistant identity records are retained for compatibility but cannot authenticate. An executive who disconnects Google retains the identity mapping and can authenticate again.

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


## Import Word/PDF drafts with Claude (local configuration)

Executives can use **Outbox → Import document** to extract existing email drafts from `.docx` files or text PDFs. Drafts are created directly in Outbox and workers can edit them. Missing recipients, subjects, bodies or dates stay blank; sending is blocked until they are completed. Ordinary compose still requires these fields. Imports do not send email or attach the source document.

The Claude integration is disabled while the key is blank. In the existing private `.env`, set:

```dotenv
MAILSEND_CLAUDE_API_KEY=
MAILSEND_CLAUDE_MODEL=claude-sonnet-4-6
```

Add your Anthropic API key after the first `=` and restart the local server. Preserve the other settings and never commit `.env`. The key is read on the server, never entered into an upload page or included in frontend code.

For a fresh checkout, install `requirements.txt` and run `python manage.py migrate` before starting. Local startup:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Open http://127.0.0.1:8000/documents/import/ and sign in as executive. The September 23 update was installed locally only; PythonAnywhere was not updated.

Limits: 5 MB per file, 100 PDF pages, 200,000 extracted characters and 100 drafts per request. Scanned/image-only PDFs require OCR elsewhere first. The importer preserves supported paragraph/table text; images and referenced attachments are not imported. Large responses or incomplete/invalid extraction create no drafts, rather than saving partial results. A repeated submission of the same upload form cannot create another batch; intentionally uploading again from a new form can create duplicates.

Review all extracted drafts before sending. Only addresses present in each source span are accepted; Claude is instructed to use explicit recipient headers and leave uncertain addresses blank. Automatic credential-label removal is a precaution, not a complete secret detector: remove sensitive credentials before uploading. Once configured, extracted text goes to the configured TAMU or Anthropic endpoint. The original document is not permanently retained; drafts, filename and import receipt remain in MailSend.

The Anthropic adapter uses the Messages API with structured JSON output. The TAMU adapter is described below. The model can be changed through configuration; both adapters validate returned content locally.


### TAMU Claude connection (local only)

The local installation now supports TAMU's OpenAI-compatible gateway:

```dotenv
MAILSEND_CLAUDE_PROVIDER=tamu
MAILSEND_CLAUDE_MODEL=protected.Claude Sonnet 4.6
MAILSEND_CLAUDE_API_KEY=
```

Store the TAMU key in the existing private `.env`, then restart Django. The API URL is fixed to `https://chat-api.tamu.ai/openai/chat/completions`; redirects are not followed. TAMU uses Bearer authentication and a different response format from Anthropic. Thinking is disabled for extraction. JSON is validated locally; HTTP 200 responses containing gateway errors or truncated output are rejected.

September 23 validation: all 339 automated tests passed, including 33 importer tests. Seven synthetic edge cases passed, with five readable PDFs tested against TAMU and two invalid/image-only PDFs rejected locally. The ten-page PDF produced eight drafts with every expected field preserved, including the complete cross-page body. A transactional local workflow also verified worker editing, missing-recipient send blocking, and worker delete/send restrictions. Only synthetic documents are approved for AI testing; the supplied mixed Word document was not transmitted. PythonAnywhere remains unchanged.


Sequential upload fix: different files (including changed content under the same filename) are accepted from a cached form. Repeating the exact same file on the same form remains replay-protected. Error responses issue a fresh form token for retries.

Content preservation: extraction sends document text, not the binary file. PDF page numbers and continuation headings are removed only when their position and layout identify them as page furniture. Ordinary message text about passwords is preserved; explicit credential labels remain filtered. Email wording is not summarized to reduce usage. The synthetic test pack and results are in `examples/import-edge-cases/`.

The latest extraction contract asks Claude for body start/end line numbers rather than rewritten body text. Django copies every line in the selected range directly from the parsed source, checks that it belongs to the message, and rejects credential markers. This avoids wording drift and reduces output size. Source-boundary selection still needs human review. All seven synthetic edge cases and 37 importer tests passed; a synthetic Word document with 90 explicitly separated pages and 52,774 extracted characters returned all 30 expected drafts with complete matching bodies, recipients and subjects. This does not establish successful extraction of the user's private 90-page document, which was not sent during agent testing.

### Google contact name matching (local only)

Executives can open a saved draft and select **Find recipient in Google contacts**. A recipient name is suggested from the import review note or greeting. Search supports exact names, case/accent normalization, reordered names, first names and spelling variations. Every match requires explicit selection, including exact matches. The displayed score measures spelling similarity, not identity confidence. Duplicate names and multiple email addresses remain separate choices. Workers cannot browse this contact lookup; they can edit the selected draft recipients under existing workspace rules.

Enable Google's People API for the OAuth project, then use **Connect Google contacts (read-only)** and grant `https://www.googleapis.com/auth/contacts.readonly` using the executive's matching Google account. This reconnect action requests both Gmail sending and read-only contacts access. Executive signup requests Gmail sending and read-only contacts in the same consent step; both grants are required. Returning Google executives missing contacts permission are prompted on their next Google sign-in. Contact names/addresses are read on demand, are not stored as an address book, and are never sent to Claude. Selected addresses are stored in the draft; selections increment the draft version and create an audit event. Google disconnect removes the local access tokens. Searches are limited to 25 pages of 1,000 connections and reject partial listings.

Contact matching and OAuth checks passed 53 tests using synthetic contacts and mocked Google responses. Real-account contact retrieval still requires the executive to grant the new permission and enable People API. PythonAnywhere was not updated.

### Automatic contact matching during import

The local importer now fetches the executive's contacts once after AI extraction when To addresses are missing. A unique exact normalized name match fills To; partial names, typos, duplicate names, and no matches remain blank with review notes. Existing valid addresses are preserved. Invalid CC/BCC recipient text remains available for correction and prevents automatic filling from bypassing its review guard. If Google contacts are unavailable, import still creates drafts with blank recipients. The full address book never goes to Claude; only relevant draft matching notes are stored. Matching applies to new imports, not previously saved drafts.

Verified with the connected account's 20 synthetic contacts and `output/pdf/contact-matching-20-emails.pdf`: 20 drafts created, 13 exact addresses filled, 1 existing address preserved, 6 unresolved drafts blocked from sending. Subjects, complete bodies, dates and recipient fields matched the independent expected-results file in both service and browser tests. Audit records exist for all 13 automatic matches. No emails were sent. Test results are in `examples/contact-test-pack/`.

### Combined imported-draft review (local only)

After upload, open `/documents/review/` to complete imported drafts on one screen. Outbox also links to it. Needs attention, All drafts and Ready filters share a readiness count. Each card provides To/CC/BCC, subject, date and body editing, saved-body preview, contact choices and a link to the attachment editor. Workers use the same author/workspace permissions as the ordinary editor; this page has no send action. Selecting a suggested contact populates To; Save draft records the edit and increments its version.

New uploads retain an explicit batch ID. An optional checkbox applies a confirmed To address only to the displayed same-name, missing-recipient drafts in that batch. The signed target list and each draft version are checked; a changed target rolls back the entire update. Legacy imports remain individually editable, but have no group-apply option because their batch identity was not recorded. Group edits are audited. Existing drafts are not changed simply by opening the review screen.

### Combined Google signup consent (local only, September 23)
Executive signup now requests Gmail sending and read-only contacts together after identity verification. Both permissions are required before account creation. Existing Google users missing contacts permission are prompted on their next Google sign-in. Google still requires explicit user consent. The 90 focused OAuth/contact tests passed. PythonAnywhere has not received this signup-flow change.
