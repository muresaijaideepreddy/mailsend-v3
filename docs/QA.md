# MailSend quality assurance

The test strategy checks product behavior and challenges the authorization boundary between assistants, executives, and independent workspaces. Test recipients use reserved example domains. No QA step sends real email.

## Acceptance scope

- Assistants prepare and modify only their own drafts, with no ability to send or manage team members.
- Executives review all workspace drafts, send one explicitly approved message, or send the explicitly confirmed current batch.
- Current means a send date at or before the application/workspace-local date; future messages need an explicit individual send.
- Review and CSV merge create or update drafts without sending.
- Tenant isolation covers lists, detail pages, writes, downloads, signatures, and history.
- Confirmation snapshots and optimistic versions prevent stale approval or editing from silently applying to changed drafts.
- Mail merge validates the entire input before creating any drafts. Uploaded attachments remain private.
- Gmail delivery requires explicit configuration; automated tests use local delivery or mocks.

## Automated regression suites

- `mail.tests.test_security`: role bypass, cross-workspace access, peer draft privacy, private attachments, mass-assignment attempts, CSRF, GET safety, XSS escaping, immutable sent history, and stale updates.
- `mail.tests.test_workflows`: composition, date filters, sequential review, send approval snapshots, CSV preview/commit, and attachment workflows.
- `mail.tests.test_concurrency`: two independent requests commit the same merge preview concurrently, followed by a safe retry if SQLite reports contention; only one complete batch may exist.
- Domain and delivery suites independently exercise parsers, limits, sending transitions, and failure handling.

Verified on September 19, 2026 with Python 3.13 on Windows:

```powershell
.venv\Scripts\python.exe manage.py test --verbosity 1
```

Result: **124 tests passed** in 27.592 seconds. Django reported no system-check issues. This includes 56 independent HTTP/concurrency regressions and the domain, delivery, Google, and account-management suites. Tests use temporary storage and an isolated test database; Google calls are mocked. No real email was sent. A passing suite is evidence for the tested behavior, not a guarantee of zero defects.

## Defects found and corrected during independent review

- Shared sent history originally excluded messages authored by other assistants. Lists, detail pages, and downloads now expose sent messages within the same workspace while preserving draft privacy.
- Signature changes could alter email content after a draft was reviewed. Signature updates now increment editable draft versions in the same transaction, invalidating stale editing and send confirmations.
- Merge CC/BCC templates were parsed before placeholder substitution. Each expanded recipient field is now validated before any draft is created.
- A partial batch could omit its already-delivered count from the error report. The response now distinguishes the messages already delivered from those still unsent.
- A draft deleted during an earlier message's delivery could interrupt the batch with an unhelpful 404. It now stops with an accurate partial-delivery report.
- Concurrent CSV commits could encounter a SQLite transaction-upgrade lock. Receipt insertion now begins the atomic write, and temporary SQLite write contention returns a retryable 409 with the preview preserved. The unique receipt prevents duplication on retry.
- An attachment database-insert failure could leave an orphaned private file. Storage writes are tracked before insertion and removed on transaction failure.
- Google disconnection retained its identity record, which could incorrectly leave the UI showing a connected account. Connection state now uses the explicit connected flag; the sign-in control also requires a usable encryption configuration.

Every issue above has a regression test. Send confirmations also have a regression requiring the body, signature, and attachment names to be available for review.

## External integration boundary

An end-to-end Google OAuth and Gmail delivery check requires the deployer's own authorized Google OAuth client and account. Automated mocks can validate request construction and error handling but cannot prove live Google consent configuration or delivery. Production deployment must use HTTPS, persistent private file storage, a secure token-encryption key, and explicit host/origin settings.

The supplied references were used as a behavioral specification. No access to the original Ruby repository or live V1 application was available for a line-by-line or production-data comparison. Assistants use local username/password authentication in this version; Google identity and sending are implemented for executives. Inbox remains an explicitly inactive legacy feature, and date-based automatic sending is intentionally replaced by the V3 executive approval flow.

## Final local verification (2026-09-19)

The integrating agent independently ran the full suite: **124 tests passed in 24.508 seconds**, with no Django system-check issues. `makemigrations --check --dry-run` reports no pending model changes. Production configuration passed `check --deploy` with DEBUG disabled and a supplied test secret. `pip check` found no broken requirements, and `collectstatic` completed.

Browser verification covered assistant login, draft creation with To/CC/BCC/body, direct assistant send denial (403), logout, executive login, future filtering, sequential review without sending, full-content send confirmation, local demo delivery, and sent history. The resulting MIME file exists and includes the stored signature snapshot; future drafts remained unsent. Desktop and 390px mobile layouts and mobile navigation were visually checked. Mobile CSV instructions were corrected to remain available at narrow widths.

The browser automation file chooser timed out, so multipart uploads were additionally tested through the running HTTP server: CSV upload and personalized preview, committing exactly two drafts, uploading a synthetic attachment, and downloading its exact original bytes with authenticated access all passed. Upload validation and permissions are also covered by the automated suite. No live Gmail authorization or external delivery was performed.

## Expanded follow-up audit

The later audit found defects beyond the original 124 tests and fixed them with 32 additional regressions. The combined **156-test suite passed**, with a **90% combined statement/branch coverage score**. See [TEST_REPORT.md](TEST_REPORT.md) for exact findings, reproduction steps, and the current Google authentication verification status. After the owner corrected the callback registration and completed Google sign-in and consent, the browser returned to MailSend with a successful connection. Read-only checks verified account identity, an unexpired access token, a stored refresh token, Gmail sending permission, encrypted token storage, and the connection audit event. Live token refresh and Gmail delivery remain unverified; delivery mode remains demo.

## Reference UI update (2026-09-19)

The running UI was aligned with the supplied MailSend screenshots: maroon top navigation, compact outbox tables, a two-column compose header, three attachments, simple login/signature pages, and direct executive edit controls. The unchanged protected backend passed all **156 tests in 33.097 seconds**, with **90% coverage**. Isolated desktop/mobile browser checks covered draft creation, future filtering, sequential review, explicit demo sending and Sent history. See [UI_ALIGNMENT.md](UI_ALIGNMENT.md) and [SUPPLIED_PROJECT_AUDIT.md](SUPPLIED_PROJECT_AUDIT.md) for the visual comparison and the separate supplied-project audit.

## Full email and CSV verification (2026-09-19)

After further CSV/MIME regressions and safe Gmail configuration error handling, **175 tests passed**, with **91% coverage**. All **35 isolated HTTP checks** passed, including actual CSV/attachment uploads, private downloads, MIME byte verification, explicit sends and replay protection. The user also confirmed receiving the one authorized Gmail self-email with its attachment. The Gmail API was enabled by its owner after an initial definitive rejection. General app delivery remains demo. See [FUNCTIONAL_TEST_REPORT.md](FUNCTIONAL_TEST_REPORT.md) for fixes, evidence and test CSV files.

Date/time clarification: the V3 design specifies date-based current/future review and manual executive sending. Its later legacy instructions describe the former Schedule checkbox. Following the user's direction to use the V3 specification, compose retains the date-only field; actual sending date and time remain visible in Sent history. Additional user-requested CC and BCC Gmail tests each had three attachments and two recipient addresses; both were accepted by Gmail and recorded in Sent. The user confirmed both reached the VIT mailbox with all three attachments, completing receipt verification for all three authorized live test emails.
