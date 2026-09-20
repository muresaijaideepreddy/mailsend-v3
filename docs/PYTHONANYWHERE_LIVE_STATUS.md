# PythonAnywhere live deployment status

Verified September 20, 2026. Public app: https://jaideepreddy05.pythonanywhere.com/.

**Current status: deployed; end-to-end acceptance incomplete.** Initial public checks passed, but later requests to both the app and PythonAnywhere's own control-panel/log pages timed out, and the Bash console attempted to reconnect. Continued availability and the remaining checks must be reverified after connectivity recovers. The cause is not established; these timeouts are not evidence of a specific Django defect.

## Deployment completed

- Deployed application commit `243b736` from the private GitHub repository. The source-only archive SHA-256 matched on the host: `524a43d2fece0313cfdc82a4646f4a3e5aa248998e19b26e5a0bbf0549b0bece`.
- PythonAnywhere Beginner account `jaideepreddy05`, native WSGI, Python 3.13 and a dedicated virtual environment. All dependencies installed; `pip check` reported no broken requirements.
- Created fresh production secrets and a new persistent database, separate from the local demo. Existing Google OAuth application credentials were transferred only after explicit user approval.
- Applied all migrations; Django deployment checks reported no issues; `check_readiness` passed on the host.
- Verified owner-only configuration/data directories (`0700`) and environment/database files (`0600`). Private data has no public static mapping; WhiteNoise serves collected static assets.
- Enabled Force HTTPS and reloaded the web app. The public HTTPS login page rendered with its stylesheet and one Google sign-in button.
- Added and saved the exact public Google callback after explicit user approval: `https://jaideepreddy05.pythonanywhere.com/accounts/google/callback/`. Existing localhost callbacks were preserved.
- Google accepted the public sign-in request and displayed the selected executive account and a permission screen. Final consent and the public callback are not yet verified.
- Read-only public HTTP checks verified `/healthz/` returned HTTP 200 with `{"status":"ready"}`, the login page and hashed CSS returned 200, HTTP redirected to HTTPS, and the CSRF cookie had Secure/HttpOnly/SameSite=Lax flags. HSTS, content-type, frame and referrer protections were present; `/.env` returned 404. The [sanitized HTTP report](PYTHONANYWHERE_HTTP_CHECKS.json) records seven passed checks and nine inconclusive checks after network timeouts. Authenticated session-cookie behavior remains untested on the host.

## Remaining acceptance checks

- Complete Google consent and verify the public callback creates the executive workspace and Gmail connection.
- Configure the buyer's Google admission. The project's Audience page showed **External / Testing**, **zero test users**, and a disabled Publish app button requiring Branding completion. Arbitrary buyer Google accounts are not yet enabled. Add specifically authorized demo test users or complete the appropriate publishing/verification process before broader use.
- Activate an assistant, verify local sign-in and subsequent Google linking/sign-in with that worker's actual account.
- Verify authenticated hosted drafting, attachments, role/workspace separation, date grouping, and persistence across reload. These workflows already pass the local automated suite; that is separate evidence.
- Send one specifically authorized message to a controlled recipient and confirm the sender, app receipt, recipient arrival and received content. No email has been sent by this hosted deployment yet.
- Rehearse backup restoration with the matching encryption key and outbound mail disabled before claiming production recovery readiness.

## Operational limits

This free deployment is suitable for a small controlled demo. It has one web worker and SQLite on PythonAnywhere storage; synchronous send batches can delay other requests. Keep batches and attachments small. Sustained buyer use requires capacity/database planning and verified operational recovery; see [hosting guidance](PYTHONANYWHERE.md).

The Web page showed an expiry of **October 20, 2026**. Extend the free app through PythonAnywhere before that date. No paid plan was purchased.

The Google permission screen currently requests viewing email messages/settings and sending email for the selected executive. The existing OAuth grant may include permissions beyond the current V3 app's identity/send needs; the exact displayed grant was presented to the user for approval. This deployment has not changed the project's scopes or publishing state.

The app uses `America/Chicago` for Current/Future date boundaries. Delivery remains V3 manual executive sending; dates alone never send a message.

Uncertain deliveries are protected against automatic retry. There is currently no dedicated reconciliation screen or command; operator-assisted investigation remains necessary.
