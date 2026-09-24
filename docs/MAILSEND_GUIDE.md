# MailSend application guide

Last updated: September 23, 2026. Covers the current application. The September 23 source release, import migrations, review page and worker Help are installed on PythonAnywhere. Hosted AI extraction is blocked by PythonAnywhere outbound access to TAMU; the AI key has not been transferred; check PYTHONANYWHERE_LIVE_STATUS.md for current operational limits.

## What MailSend does

MailSend helps a team prepare outgoing email drafts. Workers (also called assistants) complete messages; the executive controls sending. V3 is the primary specification. Document import, contact matching, shared executive drafts, and worker Help include subsequently requested extensions.

The workflow is: create or import → complete and save → executive reviews if needed → executive sends. There is no separate worker Submit for approval stage. Opening, editing, saving, importing, or previewing does not send an email.

## Accounts and permissions

Each workspace has one executive and can have multiple workers. A different executive can have a separate workspace. Workspace data is isolated.

| Action | Worker | Executive |
|---|---|---|
| Create messages and CSV merge drafts | Yes | Yes |
| View/edit own unsent drafts | Yes | Yes |
| View/edit executive-created drafts and attachments | Yes | Yes |
| View/edit another worker's unsent drafts | No | Yes |
| Delete executive-created drafts | No | Yes |
| Delete own unsent drafts | Yes | Yes |
| Read workspace Sent history | Yes | Yes |
| Update shared signature | Yes | Yes |
| Upload documents for AI extraction | No | Yes |
| Connect Google sending/contacts | No | Yes |
| Add workers and manage their credentials | No | Yes |
| Send messages | No | Yes |

Workers use the username/password assigned by the executive. Worker email is not required, and Google sign-in is not a worker login method. The account menu provides Account security for password changes. Ask the executive to reset a forgotten worker password.

Executives can use configured Google sign-in. Signing into MailSend and authorizing Gmail sending are related but distinct actions. Actual sending uses the executive's connected Google mailbox, not an arbitrary username entered in a local login form. Do not assume a Gmail connection exists merely because password login succeeded.

## Navigation

| Tab or page | Purpose |
|---|---|
| Outbox | Find, create and edit unsent messages; executive sending actions appear here |
| Inbox | Inactive legacy feature; incoming emails/replies remain in the connected mailbox |
| Sent | Search and inspect workspace messages marked sent |
| Signature | Edit the shared closing added to future deliveries |
| Worker | Executive-only account management |
| Mail merge | Upload CSV data, preview personalized content and create drafts |
| Help | Worker navigation link to expandable FAQs at `/help/workers/` |
| Review imported drafts | Complete document-generated drafts at `/documents/review/`; linked from Outbox |
| Document upload | Executive upload at `/documents/import/` |

## Worker: complete a message

1. Open Outbox or Review imported drafts.
2. Open an available draft, or use New Message to write one.
3. Confirm the intended recipient and To/CC/BCC addresses.
4. Check the subject, full body, date, and attachments. Compare an imported draft with its original document.
5. Save the changes. They become available to the executive without a separate submission step.

Workers may help complete executive drafts, but cannot delete those drafts or send them. The original author remains recorded; edits are audited and invalidate prior sending approvals. Sent messages cannot be edited; prepare a new draft for corrections.

If information is unknown, seek clarification. Imported drafts may retain blank fields while being completed. Do not invent an email address. Normal manual composition requires its form fields; incomplete imported drafts can be edited while unfinished.

## Executive: review and send

Outbox includes the workspace's drafts. Review actions can step through current, future or all editable messages. The executive can edit first or send directly.

- **Current:** dated today or earlier in the configured app timezone (default America/Chicago).
- **Future:** dated after today.
- **Send now:** explicitly sends that individual message immediately, even if its date is later.
- **Send Current Messages:** includes the whole workspace's current messages, even outside the active search/filter.

Dates organize work; they do not trigger automatic delivery. Required fields must be complete and valid before sending. A Ready label indicates field completeness, not that content or recipient identity has been verified.

Changed drafts or signatures require fresh approval. Duplicate/replayed sends are guarded. If delivery is uncertain, reconcile the result before retrying; the app avoids automatic retries that could duplicate email.

## Shared signature and attachments

The signature is shared across the workspace and appended at delivery. Agree on changes with the executive, because they affect future sends and invalidate pending approvals. Avoid duplicating it inside each body.

Messages support up to three attachments totaling 20 MiB. An imported document's reference to an attachment does not supply that file; add it separately in the message editor. Attachments and sent records may contain private information.

## CSV mail merge

1. Open Mail merge and upload a UTF-8 CSV containing an `email` column.
2. Add columns such as `first_name` for personalization.
3. Write a subject/body using matching placeholders, for example `Hello {{first_name}}`.
4. Choose the date and review every personalized preview.
5. Create the drafts. The executive sends them later.

CSV merge accepts files up to 1 MB and 200 rows. Each row becomes a separate message. A placeholder in a normal message is literal text; personalization happens through Mail merge. This is different from adding several addresses to one To/BCC field. The separate BCC CSV recipient import supports up to 450 recipients across the recipient fields.

## Document upload and AI extraction

The executive uploads a Word `.docx` or text-based PDF. MailSend reads text locally, removes recognized credential lines, then sends the extracted text to the configured AI provider. The current local integration supports TAMU's gateway and a configurable Claude model. Do not upload material you are not authorized to process with that provider; credential filtering is not a guarantee that all sensitive information is removed.

The AI identifies existing messages and their source line ranges. The app copies body text from the source rather than asking the AI to rewrite it. Source validation checks recipient roles, subject, supported date values, body completeness, and omitted text. A rejected extraction creates no partial drafts.

Word reading includes main paragraphs, tables, nested tables, headers and footers. It extracts text, not a faithful reproduction of page layout. Linked header/footer parts and merged cells are not duplicated.

| Import limit | Current behavior |
|---|---|
| File size | Up to 5 MiB |
| Extracted text | Up to 200,000 characters |
| PDF length | Up to 100 pages |
| Extracted messages | Up to 100 per import |
| Word expanded archive | Up to 25 MiB |
| Scanned/image-only PDF | Requires OCR before upload |
| Encrypted PDF, old `.doc`, corrupt file | Rejected |

For mixed notes and messages, explicit `EMAIL DRAFT` and `END EMAIL DRAFT` boundaries help separate correspondence. Unmarked notes between messages may require clearer boundaries or separate uploads. Uncertain, missing or unsupported dates remain empty; the source verifier recognizes ISO dates and English month-name dates. Images, handwritten text, and arbitrary complex layouts are not guaranteed to extract.

## Contacts and recipient matching

Availability: the combined signup consent change is currently local only. PythonAnywhere retains the earlier separate contacts connection.

The administrator enables the Google People API. Executive Google signup automatically continues to consent for Gmail sending and read-only contacts together. Both permissions must be granted before signup completes. Existing Google executives with sending-only access are prompted for contacts on their next Google sign-in; existing sessions can reconnect through the contacts action. Google consent is still required and cannot be granted silently. Contact lookup happens locally after extraction when recipient addresses are missing. The address book is not sent to Claude.

- One unique exact normalized name match can fill a missing To address.
- Case, titles, accents and reordered names are normalized.
- Typos, partial names, duplicate names and uncertain matches stay blank with suggestions.
- Conflicting header/greeting names or unresolved explicit addresses require review.
- Existing valid To addresses are preserved.
- Contact lookup failure leaves recipients blank; it does not by itself discard otherwise valid drafts.

A contact match does not prove the stored address is current or belongs to the intended person. Workers must review it. Corrections apply when saved; previously imported drafts are not silently updated when the Google address book changes.

## Review imported drafts

Use Needs attention, Ready and All drafts to filter accessible imports. Each card lets workers complete recipient fields, subject, body and date; contact suggestions help fill To. Use the linked full editor for attachments. This page does not send messages.

Some new import batches offer applying an address to same-name drafts in that batch. **Known unresolved review issue:** earlier audits found gaps when the source name changes after group selection or a target has unresolved CC. Use individual saves for these cases until the group-apply fixes are verified. Legacy imports without batch identity have no group option.

Saving errors can currently discard the submitted form display even though the stored draft stays unchanged. Keep a copy of unsaved work and compare against the latest saved version before retrying. These review issues are separate from the completed extraction fixes.

## Troubleshooting

| Symptom | What to do |
|---|---|
| Required information missing | Open the draft and enter confirmed details |
| Invalid email address | Correct the address; use commas for multiple recipient addresses |
| No contact match | Confirm manually or ask the executive to check their contacts connection |
| AI unavailable | Ask the administrator to check provider access/configuration and retry later |
| Extraction failed validation | Inspect message headers, boundaries and omitted-content warning; clarify or split the document |
| No readable text | Convert to a text document or perform OCR first |
| Duplicate upload warning | Check Outbox/review for the earlier result before retrying |
| Stale edit or approval | Reopen the latest version and compare before saving/sending |
| Google consent or connection error | Ask the executive/administrator to check account consent, enabled APIs and exact callback configuration |
| Demo delivery notice | The app is using local demo transport; no real email was sent |

## Local setup, configuration and deployment

For an existing configured workspace, preserve `.env`, database, media and encryption keys. Start using the repository's documented local startup workflow. Do not seed demo users into a live-data installation or replace its private configuration.

- [README: installation and workflow](../README.md)
- [Fresh clone and GitHub setup](GITHUB_SETUP.md)
- [Local live-demo startup](LIVE_DEMO_START.md)
- [Deployment instructions](DEPLOYMENT.md)

The development URL is `http://127.0.0.1:8000/`. A fresh setup requires Python, dependency installation, migrations and separately configured accounts. See the linked setup guides for exact commands.

`MAILSEND_DELIVERY_MODE=demo` saves local email files without delivery. Gmail mode requires the executive's connected sending account. Configure AI and Google credentials privately; never commit or paste them into this guide. Disconnecting Google removes local tokens. Deploying new code is a separate action from changing local files.

## Verification and maintenance

The latest extraction-fix baseline passed 381 automated tests, 41 live synthetic AI cases, 21 reader/validator checks, 15 contact cases, a seven-file PDF pack, and a synthetic 90-page/30-message document. These checks overlap and are not an accuracy percentage. The later worker Help change passed rendering/access checks and Django system checks; the entire suite was not rerun for that static FAQ addition.

- [Extraction fixes and retest details](EXTRACTION_FIXES_RETEST_2026-09-23.md)
- [Original expanded extraction audit](EXTRACTION_CONTACT_AUDIT_2026-09-23.md)
- [Earlier broader demo audit and outstanding review issues](DEMO_EDGE_AUDIT_2026-09-23.md)

Keep this guide synchronized with behavior changes. Update worker FAQs when workers are affected and setup documents when configuration changes. `AGENTS.md` records this requirement for future work in this project. This is a development workflow requirement, not a background service that independently detects edits.

## Change history

| Date | Change |
|---|---|
| 2026-09-23 | Local only: executive Google signup now requests Gmail sending and read-only contacts together; incomplete grants cannot complete signup. PythonAnywhere still uses the earlier separate-contacts flow. |
| 2026-09-23 | Installed the source release on PythonAnywhere; host readiness and protected-page checks passed. Hosted TAMU AI access blocked by the outbound proxy; no key transferred. |
| 2026-09-23 | Added full application guide, worker Help with 15 expandable FAQs, and documentation-maintenance instructions. Documented current extraction safeguards and remaining review limitations. |

Google signup consent update verification: 90 focused OAuth/contact tests and the full 382-test suite passed. Report: `tmp/document-import-release/automated-checks-shared-memory-20260923T220426568733Z.json`. Local server restarted; login returns HTTP 200. PythonAnywhere signup remains unchanged.
