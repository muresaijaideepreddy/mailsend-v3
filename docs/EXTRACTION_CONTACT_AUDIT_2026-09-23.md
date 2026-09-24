# MailSend extraction and contact audit — September 23, 2026

Update: the 11 failures below were subsequently fixed and retested. See [fix and retest report](EXTRACTION_FIXES_RETEST_2026-09-23.md). The original findings below describe the pre-fix audit.

## Result and scope

58 new checks: 47 passed and 11 failed. These are targeted examples, not a statistical accuracy score. The 11 failures comprise 8 validation gaps and 3 unsupported Word text locations. No application code was changed in this audit. No emails were sent, no database drafts were created, and no private document or real address book was sent to the AI.

22 additional DOCX cases used the real configured TAMU Claude endpoint; contacts were synthetic and matched locally. The previous 19 live cases passed separately. Each live case was run once; model output can vary. The last regression suite passed 370 tests before this audit.

## Reproducible failures

| Check | What happened | Impact / required safeguard |
|---|---|---|
| Body-only email used as To | Validator accepted admin@example.test from a body sentence | Check addresses against their corresponding recipient fields, not the whole message |
| CC address moved to To | Validator accepted a source CC address in To | Preserve recipient roles; particularly important for BCC privacy |
| Invented date | Source October 1, 2026; validator accepted January 15, 2028 | Validate date against source evidence |
| Body shortened | Validator accepted only greeting and first paragraph, omitting later paragraphs | Source substring validation prevents rewriting but does not establish completeness |
| Body entirely omitted | Body range 0/0 accepted despite source body | Detect an unjustified empty body |
| All drafts omitted | Empty messages list accepted for a document containing a clear email | Detect source message coverage or explicitly require review |
| Wrong subject selected | Body sentence accepted as subject | Require subject-specific source evidence |
| CC omitted | Empty CC accepted despite an explicit source CC | Compare source recipient fields to extracted fields |
| Word header text omitted | Important text in section header missing from extracted text | Read supported header content or warn about ignored content |
| Word footer text omitted | Important text in section footer missing from extracted text | Read supported footer content or warn about ignored content |
| Nested Word table text omitted | Text in a table within a table missing | Recursively extract table contents |

The eight validator failures used deliberately incorrect synthetic AI responses. They demonstrate what the application would accept if the model made that mistake; the live AI did not produce these errors in the tested cases. The three Word reader failures happen before the AI receives the document.

## Supported rejection behavior

Corrupt files, old .doc files, image-only PDFs without readable text, encrypted PDFs, PDFs with 101 pages, and uploads above 5 MB were rejected as expected. Image-only PDFs need OCR first. The implementation also caps extracted text at 200,000 characters and an import at 100 messages; those two boundaries were inspected in code, not newly exercised here.

## Contact matching interpretation

All 15 additional contact checks passed: accent normalization, hyphen/space differences, titles/case, reversed names, partial names, typos, duplicate names, duplicate same address, normalized-name collisions, empty address books, unresolved BCC, conflicting To headers, invalid explicit addresses, existing valid To preservation, and provider outage. Ambiguous/fuzzy/missing contacts remain blank for review. A name match is not proof of identity or mailbox ownership; a contact stored under the wrong name cannot be recognized as wrong from name/email alone.

## Remaining coverage limits

These checks do not certify arbitrary layouts, multi-column PDF reading order, scanned handwriting/OCR, embedded text boxes/images, tracked changes, multilingual message boundaries, sustained provider failures, or model variability across repeated runs. Existing earlier large-document tests are separate evidence; this run used small synthetic files to isolate failures. Full content preservation is therefore not a defensible universal claim yet.

## Demo explanation

“The importer creates editable drafts from supported text documents. Exact unique contact names can fill missing recipients; ambiguous names remain for manual review. The executive controls sending. We tested normal and adversarial cases, and identified remaining gaps in source completeness validation and complex Word layouts. We use ordinary paragraphs or simple tables for the demo and verify recipient fields, dates, and content against the source.”

Before unrestricted use, prioritize recipient-role checks, complete source coverage, source-supported dates/subjects, and detection of omitted document content. Earlier review/group-apply audit findings are separate from this extraction audit and are not certified fixed by these results.

## Case evidence

### Live AI extraction: additional synthetic DOCX cases

22/22 passed.

| Case | Result |
|---|---|
| placeholder-tbd | PASS |
| placeholder-na | PASS |
| two-names-comma | PASS |
| two-names-slash | PASS |
| mixed-valid-invalid | PASS |
| plus-address | PASS |
| uppercase-address | PASS |
| display-name | PASS |
| title-name | PASS |
| nickname | PASS |
| unknown-name | PASS |
| generic-team | PASS |
| different-title-header | PASS |
| bullets-blank-lines | PASS |
| urls-html-literals | PASS |
| headers-inside-body | PASS |
| missing-subject | PASS |
| missing-body | PASS |
| notes-without-mails | PASS |
| identical-drafts-twice | PASS |
| invalid-date | PASS |
| relative-date | PASS |

Evidence: `tmp\pipeline-edge-audit\expanded-results.json`.

### Local reader and adversarial validator checks

10/21 passed.

| Case | Result |
|---|---|
| validator-body-only-address | FAIL |
| validator-cc-moved-to-to | FAIL |
| validator-invented-date | FAIL |
| validator-truncated-body | FAIL |
| validator-empty-body-despite-source | FAIL |
| validator-zero-drafts-despite-source | FAIL |
| validator-subject-from-body | FAIL |
| validator-omitted-cc | FAIL |
| validator-invented-address | PASS |
| validator-overlap | PASS |
| validator-out-of-range | PASS |
| reader-header | FAIL |
| reader-footer | FAIL |
| reader-nested-table | FAIL |
| reader-ordinary-table | PASS |
| reject-corrupt | PASS |
| reject-old-doc | PASS |
| reject-scan | PASS |
| reject-encrypted | PASS |
| reject-101-pages | PASS |
| reject-over-5mb | PASS |

Evidence: `tmp\pipeline-edge-audit\deterministic-results.json`.

### Local synthetic contact-matching cases

15/15 passed.

| Case | Result |
|---|---|
| accents | PASS |
| hyphen-space | PASS |
| case-title | PASS |
| reversed | PASS |
| partial | PASS |
| typo | PASS |
| duplicate-person | PASS |
| repeated-same-address | PASS |
| normalized-name-collision | PASS |
| empty-address-book | PASS |
| bcc-unresolved | PASS |
| multiple-explicit-header-lines | PASS |
| invalid-header-and-matching-greeting | PASS |
| valid-to-preserved | PASS |
| contacts-outage | PASS |

Evidence: `tmp\pipeline-edge-audit\contact-matrix-results.json`.

## Reproduce

Run from the project directory using the local virtual environment:

```powershell
.venv\Scripts\python.exe tmp/pipeline-edge-audit/expanded.py
.venv\Scripts\python.exe tmp/pipeline-edge-audit/deterministic.py
.venv\Scripts\python.exe tmp/pipeline-edge-audit/contact_matrix.py
```

Only expanded.py calls the configured AI endpoint and may incur provider usage. Other scripts operate locally. All use synthetic data and do not save drafts.