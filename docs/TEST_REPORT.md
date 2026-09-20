# MailSend expanded test audit

## Result

**156 automated tests passed** in 38.421 seconds on September 19, 2026, after reproducing and fixing the defects below. The original baseline was 124 passing tests. This audit added 32 tests covering previously untested failure cases, concurrent requests, account setup, and Google failures. No real email was sent.

Coverage.py ran with branch measurement enabled over `mail` and `config`, excluding tests, migrations, and empty package files. The combined statement/branch score was **90%** (1,335 statements; 384 branches). This is measured coverage, not proof that every possible input or environment is bug-free. The report is available locally at `htmlcov/index.html`.

## How it was checked

1. Reran the original full suite before making changes: 124 passed.
2. Used three independent agents to audit workflows, delivery/authentication, and account setup against the documented requirements.
3. Added failing regression tests for reproduced bugs, then fixed the implementation and reran the affected suites.
4. Used real independent database connections/threads to test simultaneous send claims and duplicate CSV commits; used a real transaction commit to test attachment cleanup failures.
5. Ran the entire expanded suite with coverage after merging all fixes: 156 passed. Google API responses were mocked; MIME/demo deliveries used isolated temporary storage.
6. Verified Django checks, model/migration consistency, Python compilation, dependency consistency, and production settings checks.
7. Configured the supplied OAuth client in the Git-ignored local `.env`, generated an encryption key without displaying it, checked OAuth request construction, and restarted the development server. After the owner corrected the callback registration and completed Google sign-in and consent, verified successful authentication, identity mapping, sending permission, encrypted token storage, and a connection audit event.

## Confirmed bugs fixed

| Area | Reproduction and consequence | Fix / regression evidence |
| --- | --- | --- |
| Review tabs | A second tab replaced the review sequence, allowing the first tab to save its content over a different draft with the same version. | Signed form token binds user, workspace, period, position and exact message; mismatches return 409 without a write. |
| Expired or removed review | Posting an old form could report completion while discarding its edits. | Explicit unsaved-edits conflict when the sequence expires or the draft is no longer editable. |
| Confirmation inputs | Non-ASCII send/merge tokens raised TypeError and produced HTTP 500. | Unicode-safe constant-time comparison rejects the request without sending or creating drafts. |
| Stale send tab | An invalid token from an old tab consumed the newer valid approval. | Consume the stored approval only after successful validation. |
| Form binding | Empty POSTs left forms unbound, hiding validation errors and ignoring signature clearing. | Bind forms based on HTTP method, including empty request data. |
| Recipient parser | Malformed RFC address syntax or deeply nested comments escaped validation and crashed compose/CSV processing. | Parser failures become actionable validation errors. |
| Simultaneous sends | SQLite lock contention escaped the atomic claim as HTTP 500. | Return a safe conflict before delivery; threaded regression verifies only one provider call. |
| Attachment storage | Storage failure produced HTTP 500; cleanup failure after commit could delete the newly saved replacement. | Roll back failed uploads with a form error; isolate/log post-commit cleanup failures and retain the replacement. |
| Demo account collisions | Seeding could adopt unrelated existing accounts or create inconsistent workspace ownership. | Refuse username/email/membership collisions and incomplete or inactive pairs atomically. |
| Demo password validation | Empty or weak custom seed passwords bypassed normal validators. | Validate passwords before creating accounts; repeat seed leaves existing passwords unchanged. |
| Demo launcher | An interrupted dependency installation left a virtual environment that later launches treated as complete. | Reconcile pinned dependencies on each launch; PowerShell syntax and dependency consistency verified. |

New tests are in `mail/tests/test_delivery_audit.py`, `mail/tests/test_workflow_audit.py`, and `mail/tests/test_setup_audit.py`. Existing review tests now submit the real hidden review token as the browser does; assertions were not weakened.

## Google configuration status

Local settings now support `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`, with the previous names retained for compatibility. The actual credentials and token encryption key are in `.env`, which Git ignores. Secret values are not in source, tests, or this report. Delivery remains `demo`.

The authorization request correctly contains state, nonce, PKCE S256, the client ID, and the configured callback, and does not expose the client secret in the URL. The first browser attempt received **Error 400: redirect_uri_mismatch**. After the owner registered the exact Authorized redirect URI below, a fresh attempt successfully reached Google's account sign-in screen:

```
http://127.0.0.1:8000/accounts/google/callback/
```

The redirect mismatch is resolved. Google's sign-in screen identifies the OAuth app as **Team Form**. The account owner completed sign-in and consent, and the browser returned to the MailSend outbox with **Google is connected**. The successful authorization-code exchange and verified Google identity created an active executive account in its own workspace.

Read-only checks of the saved connection confirmed an unexpired access token, a stored refresh token, Gmail sending permission, matching account email and Google subject hash, encrypted token storage, and a `google.connected` audit event. No secret values were printed. Live refresh and real Gmail delivery remain unverified, and no external messages were sent. Delivery remains in demo mode. The OAuth client secret shared in chat should be rotated before production use.

## Remaining practical limits

- Live Google sign-in, consent and token exchange are verified. A real token refresh and Gmail delivery have not been exercised; the app remains in demo delivery mode.
- Exact Ruby parity/data migration cannot be assessed without the original repository.
- If removal of an old private attachment fails because storage is unavailable, an inaccessible orphan may remain. The failure is logged and the saved replacement is preserved; cleanup requires operational follow-up.
- Stress/load testing, production infrastructure and a full browser/device matrix are outside these results. The interrupted second browser audit did not replace the automated multi-tab regression tests.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m coverage run manage.py test mail.tests -v 2
.\.venv\Scripts\python.exe -m coverage report
.\.venv\Scripts\python.exe -m coverage html
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```
