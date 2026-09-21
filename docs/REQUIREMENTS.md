# Requirements and acceptance map

The detailed current checklist and fresh results are in [V3_ACCEPTANCE_REPORT.md](V3_ACCEPTANCE_REPORT.md). [PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md) records the user's final precedence decision: V3 governs, and V1 fills only unspecified details.

The user asked for a working Python/Django implementation using multiple coding and testing agents. The reference PDFs supply product behavior, not instructions to access accounts, share credentials, or bypass browser warnings. The user subsequently approved using ChatGPT agents instead of Claude.

| Reference requirement | Implementation | Acceptance evidence |
| --- | --- | --- |
| Executive and assistant roles | Workspace owner plus membership role, server authorization on every operation | HTTP IDOR/role tests and service authorization tests |
| Assistant dashboard: own drafts, date, To, subject, edit/delete | Outbox with search, filters, compose and confirmation pages | Browser draft creation; view workflow tests |
| To, CC, BCC, subject, body, date | Validated Django form and MIME message construction | Header injection and recipient parsing tests |
| Up to three attachments | Private storage, authenticated download, 20 MiB combined limit | Upload count/size/privacy/rollback tests |
| Executive dashboard: all workspace messages | Executive outbox and detail view | Two-workspace and peer-assistant tests |
| Current/future/all sequential editing | Review snapshot and version-checked saves | Boundary-date and sequential review tests; browser future review |
| Single send even for a future draft | Executive confirmation plus domain send service | Future send and no-GET-side-effect tests |
| Send Current Messages | Executive-approved IDs/versions; send date today or earlier in the app timezone, with no time input | PDF December example, local calendar boundaries, date-only drafts, stale/replayed approvals and partial-result tests |
| Assistants cannot send | No send UI; both HTTP and service layer deny | Browser direct URL returns 403; service/POST bypass tests |
| Google identity and executive Gmail send | OAuth state/PKCE/nonce, verified identity, encrypted executive tokens, executive-only Google sign-in and Gmail API; assistant Google paths are denied | Mocked OAuth/provider tests pass; live Google consent and delivery of this revision remain pending |
| Mail merge and BCC CSV | Full validation then preview and atomic draft creation | Malformed CSV, placeholders, import replay and concurrency tests |
| Sent tab | Immutable shared workspace history with actual sent signature and delivery label | Sent-history and signature tests |
| Signature tab | Shared plain-text signature, appended once; changes invalidate approvals | Signature/MIME/stale-confirmation tests |
| Worker account management | Executive explicitly adds each worker with username/password; no automatic default worker or assistant email; users change own passwords | Empty-workspace, manual creation, placeholder retirement, role/tenant/password-strength and Google-denial tests |
| Legacy Inbox/Reply | Informational inactive page | Reference explicitly states Inbox is inactive; no read scope requested |
| Legacy automatic scheduling | Replaced by explicit V3 executive send approval | Date never triggers unattended delivery |

Dates use `MAILSEND_TIME_ZONE` (America/Chicago by default). There is no planning time input and dates never schedule delivery. By the explicit September 20 user update, assistants use only username/password and do not supply email. HTML/rich-text email editing is not specified and plain-text composition is used. CSV creates one personalized draft per row; it never sends messages during import.

The production package and remaining deployment verification are described in [DEPLOYMENT.md](DEPLOYMENT.md). Direct parity against the Ruby source and production data migration require that repository/data; live Gmail verification requires the deployment-specific Google setup and an authorized controlled test.
