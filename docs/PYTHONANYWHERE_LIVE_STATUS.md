# PythonAnywhere live deployment status

Verified September 21, 2026 UTC (September 20 in America/Chicago). Public app: https://jaideepreddy05.pythonanywhere.com/.

**Current status: release `877236a` is deployed and public checks pass; end-to-end acceptance remains incomplete.** The worker setup update was applied around 01:54 UTC on September 21. After preparation and reload, health, login, About and Privacy all returned HTTP 200 with expected content at 01:56:48 UTC. PythonAnywhere access recovered after the initial retry timeout; the intermittent connection problem's cause remains unconfirmed, and this successful check does not establish a permanent fix.

## Worker setup update deployed

The latest user request removes automatic default workers and confirms that workers see only their own unsent drafts; Sent remains shared within the workspace. All 302 local tests passed at 2026-09-21 01:37:09 UTC (100.437 seconds), along with system and migration consistency checks. New workspaces start executive-only; Worker page reads do not create accounts; executives add workers explicitly. Migration `0006_retire_unused_default_workers` disables and hides only untouched generated placeholders, retaining all records and preserving configured or used accounts. The existing local `worker-3` is configured and has two messages, so it is not an unused placeholder.

The 13-file source-only archive from release `877236a`, `tmp/worker-setup-release/MailSend-V3-Worker-Setup.zip`, has SHA-256 `9f394deed1b087130e039d01851caaf5d84d34680c76330e1209bb5b50076eec`. The guarded updater validated before/after hashes and applied it around 01:54 UTC, with prior source backed up at `/home/jaideepreddy05/.local/share/mailsend-source-backups/worker-setup-d2gaj7pd`. Host preparation applied `0006_retire_unused_default_workers`; system and readiness checks passed, and the Web app reload completed. A read-only audit confirmed two untouched default placeholders were retired. No accounts were deleted; configured or used accounts and all records are preserved.

The private local artifact `tmp/worker-setup-release/worker-setup-live.json` records HTTP 200 and expected content for `/healthz/`, `/accounts/login/`, `/about/` and `/privacy/` at `2026-09-21T01:56:48.593096+00:00`. Browser inspection confirmed that `/merge/` redirects to login when signed out. This release check did not verify authenticated hosted workflows, a hosted Gmail receipt or recovery. The package contains no credentials, database or media.

During the earlier September 20 deployment, switching Wi-Fi restored the public health response and PythonAnywhere control-panel access around 21:13 UTC. Both timed out again around 21:36 UTC. After the user switched to mobile data around 21:41 UTC, the authenticated file manager opened successfully. Following the source update and reload, `/about/`, `/privacy/`, `/terms/` and `/healthz/` all returned HTTP 200 with expected content at 21:44:23 UTC. The intermittent connectivity cause is unconfirmed, with no established global hosting outage or application defect.

## Deployment completed

- The initial deployment used application commit `243b736` from the private GitHub repository. The source-only archive SHA-256 matched on the host: `524a43d2fece0313cfdc82a4646f4a3e5aa248998e19b26e5a0bbf0549b0bece`.
- Applied the 13-file public-page/OAuth source update around 21:43 UTC after validating it against baseline `243b736`. ZIP SHA-256: `7fa06f4f834b26679ebaf3fec04783a85791e0c214cf9ff845cb3c0dee2e1747`. The prior source is backed up at `/home/jaideepreddy05/.local/share/mailsend-source-backups/public-update-29nq5et0`. Host preparation reported no issues, readiness passed, no migrations remained pending, and the app was reloaded. The private local artifact `tmp/pythonanywhere-audit/public-pages-live.json` records all four public page/health checks passing at 21:44:23 UTC.
- PythonAnywhere Beginner account `jaideepreddy05`, native WSGI, Python 3.13 and a dedicated virtual environment. All dependencies installed; `pip check` reported no broken requirements.
- Created fresh production secrets and a new persistent database, separate from the local demo. Existing Google OAuth application credentials were transferred only after explicit user approval.
- Applied all migrations; Django deployment checks reported no issues; `check_readiness` passed on the host.
- Verified owner-only configuration/data directories (`0700`) and environment/database files (`0600`). Private data has no public static mapping; WhiteNoise serves collected static assets.
- Enabled Force HTTPS and reloaded the web app. The public HTTPS login page rendered with its stylesheet and one Google sign-in button.
- Added and saved the exact public Google callback after explicit user approval: `https://jaideepreddy05.pythonanywhere.com/accounts/google/callback/`. Existing localhost callbacks were preserved.
- Saved Google Branding with the MailSend name and all three live public page URLs. After explicit approval, published the Google app at approximately 21:49 UTC. Audience showed **External / In production**, a **Back to testing** button and **0 users / 100 user cap**. Public admission no longer requires a test-user list. No full verification was submitted; the owner accepts the unverified-app warning and 100 lifetime user cap.
- Google accepted the public sign-in request and displayed the selected executive account and a permission screen. Final consent and the public callback are not yet verified.
- Read-only public HTTP checks verified `/healthz/` returned HTTP 200 with `{"status":"ready"}`, the login page and hashed CSS returned 200, HTTP redirected to HTTPS, and the CSRF cookie had Secure/HttpOnly/SameSite=Lax flags. HSTS, content-type, frame and referrer protections were present; `/.env` returned 404. The [sanitized HTTP report](PYTHONANYWHERE_HTTP_CHECKS.json) records seven passed checks and nine inconclusive checks after network timeouts. Authenticated session-cookie behavior remains untested on the host.

## Remaining acceptance checks

- Complete fresh Google consent after publication and verify the hosted callback creates the executive workspace and Gmail connection. The public Google configuration is complete, but end-to-end admission has not yet been confirmed. Managed-domain administrators may still restrict access; publication does not remove Google's unverified-app warning or lifetime user cap.
- Verify assistant creation without email and password-only sign-in; check that assistant Google linking/login is denied after the simplification update.
- Verify authenticated hosted drafting, attachments, role/workspace separation, date grouping, and persistence across reload. These workflows already pass the local automated suite; that is separate evidence.
- Send one specifically authorized message to a controlled recipient and confirm the sender, app receipt, recipient arrival and received content. No email has been sent by this hosted deployment yet.
- Rehearse backup restoration with the matching encryption key and outbound mail disabled before claiming production recovery readiness.

## Assistant-account and date-only update deployed

The user requested password-only assistant accounts without email collection and removal of optional planning time. All 290 automated tests pass (2026-09-20 22:35:52 UTC; 111.572 seconds), including system and migration consistency checks. Isolated browser checks confirm the changed worker, login/menu and compose screens.

The 25 reviewed source files from commit `bc94d4c` were applied at 2026-09-21 00:47 UTC. Archive SHA-256: `0648923760bcca4464c0c7d3d121d99e08641cf824d599f7ea220163f3ea1970`. Prior source is backed up at `/home/jaideepreddy05/.local/share/mailsend-source-backups/accounts-dates-ljdebuwf`. Host preparation applied the options-only migration `mail.0005_message_date_ordering`; system checks and readiness passed, and the Web app reload completed. Existing account data and the nullable legacy time column are retained.

The private local artifact `tmp/pythonanywhere-audit/accounts-dates-live.json` records HTTP 200 and expected content for `/healthz/`, `/accounts/login/`, `/about/` and `/privacy/` at `2026-09-21T00:50:22.362546+00:00`. The browser confirmed that login styling loaded correctly and the page explains that Google sign-in is for executives only. Authenticated hosted workflows, a hosted real Gmail receipt and recovery rehearsal remain unverified by this release check.

## Latest application and Google Cloud changes

Google Cloud saved the application name **MailSend** and scope declarations for `openid`, `email`, `profile` and `https://www.googleapis.com/auth/gmail.send` only; `gmail.readonly` is no longer declared. Existing Google grants have not been revoked, so these saved declarations do not remove permissions previously granted by an account.

Public `/about/`, `/privacy/` and `/terms/` pages and the OAuth change to `include_granted_scopes=false` passed the earlier **288-test local suite**, started on September 20 at 21:32:13 UTC, and were deployed that day. The later 290-test suite and deployed `bc94d4c` update described above supersede that local verification count. The OAuth change avoids automatically combining unrelated prior grants in future requests; it does not revoke existing grants. All three live page links are saved in Google Branding, and **In production** publication is confirmed as recorded above. Full Google verification is outside the current release goal.

The authorized PythonAnywhere support email about intermittent access was sent through the existing local MailSend service to `support@pythonanywhere.com`; the app recorded Sent status and a provider receipt. Recipient arrival is not confirmed. This was separate from the hosted deployment, which has not sent an email.

Google Branding currently warns that homepage ownership is not registered to the operator; the TAMU Google account cannot access Search Console, so ownership verification remains pending. Audience remains **In production**. This is not a claim of full Google verification.

## Operational limits

This free deployment is suitable for a small controlled demo. It has one web worker and SQLite on PythonAnywhere storage; synchronous send batches can delay other requests. Keep batches and attachments small. Sustained buyer use requires capacity/database planning and verified operational recovery; see [hosting guidance](PYTHONANYWHERE.md).

The Web page showed an expiry of **October 20, 2026**. Extend the free app through PythonAnywhere before that date. No paid plan was purchased.

An earlier Google permission screen included viewing email messages/settings as well as sending. Scope declarations and the deployed OAuth request behavior have since been narrowed as recorded above, but the selected account's existing grant has not been revoked. A fresh hosted consent screen remains unverified.

The app uses `America/Chicago` for Current/Future date boundaries. Delivery remains V3 manual executive sending; dates alone never send a message.

Uncertain deliveries are protected against automatic retry. There is currently no dedicated reconciliation screen or command; operator-assisted investigation remains necessary.
