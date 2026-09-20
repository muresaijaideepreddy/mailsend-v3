# Full email, CSV and attachment verification

Date: September 19, 2026. The running MailSend app was tested using independent CSV and MIME audits, browser uploads, isolated HTTP workflows, automated regressions, and three user-authorized real Gmail emails.

## Final result

- **175 automated tests passed in 50.704 seconds**, with **91% combined statement/branch coverage** (1,368 statements, 402 branches). Logs: `tmp/functional-qa/full-tests.log` and `coverage.txt`; interactive report: `htmlcov/index.html`.
- **35 live local HTTP checks passed** against the isolated demo server, using separate database/media/outbox/session cookies. Evidence: `tmp/functional-qa/http-roundtrip-results.json` and `http-roundtrip.log`.
- The browser successfully selected and uploaded actual CSV and attachment files through the file chooser. A UTF-8 BOM CSV with a quoted comma produced two personalized previews and exactly two saved drafts. Bulk BCC preserved existing recipients and removed duplicates. Three uploaded attachments appeared on the saved draft.
- **Three real Gmail test messages were accepted and received**, as confirmed by the user: the initial self-email with one attachment, followed by the separately requested CC and BCC tests with three attachments each. Only the connected TAMU account and the explicitly supplied VIT address were used.
- Django system checks, migration consistency, and dependency checks passed.

## Bugs fixed during this pass

| Finding | Fix and evidence |
| --- | --- |
| CSV row errors pointed to the wrong source line after blank lines or quoted multiline cells. | Preserve each record's physical start line. Ten new CSV roundtrip/boundary tests cover line numbers, BOM/UTF-8, literal HTML/formula content, exact row/recipient limits, expired/stale previews and atomic invalid imports. |
| Uploaded email files or multipart content types generated malformed MIME structure. | Treat structured MIME uploads as opaque binary attachments; preserve their exact bytes. Five new MIME tests cover Unicode headers/body/signatures, three byte-exact attachments, CSV/BCC serialization, and actual aggregate size checks. |
| Disabled Gmail API produced an unhelpful generic failure. | Recognize structured API-disabled errors and display safe instructions to enable Gmail API and approve a retry. Four new tests cover saved/UI guidance, explicit reapproval, malformed error payloads and prevention of raw provider data leakage. |
| Demo-mode wording could imply an earlier genuine Gmail delivery was simulated. | The Sent notice and footer now describe new sends; historical delivery labels remain unchanged. |

## Functional coverage

| Workflow | Verified outcome |
| --- | --- |
| CSV mail merge | Preview personalization; quoted comma/BOM handling; draft creation without sending; invalid row rejection without partial drafts; stale/expired/replayed approvals; 200-row limit. |
| Bulk BCC | CSV import plus existing BCC; deduplication; 450-recipient bounds and cross-field checks; invalid imports leave drafts unchanged. |
| Attachments | Browser upload of three files; exact authenticated downloads; anonymous download blocked; private/no-store caching; fourth file rejected; over-20-MiB request rejected; invalid edits preserve saved draft. |
| Email content | To/CC/BCC, Unicode, signatures and attachment bytes survive MIME serialization; signatures appended once and preserved in sent history. |
| Permissions | Assistant cannot send even with a direct POST; missing CSRF rejected; existing tenant-isolation regression suite passes. |
| Executive send | Full-content confirmation, individual and current-batch demo delivery; replay cannot duplicate delivery; future drafts remain unsent by current-batch operation. |
| Google | Real sign-in/consent and encrypted credentials were previously verified. This pass verified actual Gmail API acceptance, MailSend Sent history, and user-confirmed mailbox receipt with attachment. |

## Gmail configuration resolution

The first live test was definitively rejected with `SERVICE_DISABLED` because Gmail API was disabled in the OAuth project. It did not send an email. The owner enabled the API and confirmed completion. A diagnostic request without email content confirmed the endpoint was active. The same failed message was then retried once, obtained a provider receipt, and was received by the owner. An ambiguous delivery was never retried.

The initial authorization covered one real self-email; the user later explicitly requested the two CC/BCC recipient tests documented below. Each authorized test used Gmail mode only for its own execution. The app's general delivery mode remains **demo**; new ordinary sends stay local until the owner chooses to enable Gmail delivery generally. Live token renewal after expiry and production load testing remain outside this pass; refresh failure/success paths are covered with provider mocks.

## Sample files and reproduction

Ready-to-upload synthetic CSVs are in [examples/qa](../examples/qa/README.md): valid multiline mail merge, duplicate BCC recipients, and an intentionally invalid empty-email CSV. These use `.test` addresses and are for demo mode only.

```powershell
.\.venv\Scripts\python.exe -m coverage run manage.py test mail.tests
.\.venv\Scripts\python.exe -m coverage report
.\.venv\Scripts\python.exe -m coverage html
.\.venv\Scripts\python.exe manage.py check
```

The one-time live-email scripts and receipt are in ignored `tmp/functional-qa/`. Their persisted attempt markers prevent accidental repeated sending; they are audit artifacts, not ordinary test-suite steps. Tests in `mail.tests` never send external mail.
## Additional requested live recipient tests

The user subsequently requested tests to their VIT address, two recipients at once, CC/BCC, and three attachments. Two separately labeled emails were submitted through the normal delivery service with Gmail mode scoped to those executions:

| Scenario | To | Additional recipient | Attachments | Result |
| --- | --- | --- | --- | --- |
| CC | User-specified VIT address | Connected TAMU account in CC | Text, CSV, JSON (three synthetic files) | Gmail accepted; provider receipt saved; listed in Sent at 2:58 PM local time. |
| BCC | Connected TAMU account | User-specified VIT address in BCC | Same three synthetic files | Gmail accepted; provider receipt saved; listed in Sent at 2:58 PM local time. |

These are additional explicit user-authorized messages, not automatic retries of earlier tests. Receipt evidence is in ignored `tmp/functional-qa/cc-bcc-three-attachments-receipt.json`. The user confirmed that both additional emails arrived at the VIT mailbox with all three attachments. Across this session, three real emails were accepted: the original self-test (receipt confirmed by the user) and these two additional tests.

## Decision on the missing time field

**Superseded by the user's subsequent explicit request for a time field.** See [SEND_TIME_UPDATE.md](SEND_TIME_UPDATE.md): compose and CSV merge now require date and time, due filters respect that time, and executive approval remains required. Older missing times are labeled Time not set and excluded from Send Current. The latest full suite is 197 tests with 91% coverage. The paragraph below records the earlier interpretation.

The user asked why compose has no time field and then asked us to decide based on the document. The V3 specification on page 2 repeatedly describes a send **date**, date-based current/future filters, executive send buttons, and editing without sending. The later "How to Use Mailsend" section describes an older worker Schedule checkbox with delivery within ten minutes of a specified time. The V3 executive workflow takes precedence for this rewrite. Compose therefore retains a calendar date and explicit executive approval; no time picker or unattended scheduler was added. Actual `sent_at` timestamps, including time of day, are shown in Sent history and message details. This follows the user's direction to implement the V3 document rather than add a separate scheduling workflow.
