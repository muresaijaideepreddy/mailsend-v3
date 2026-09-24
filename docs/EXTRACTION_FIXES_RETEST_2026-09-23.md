# Extraction fixes and retest — September 23, 2026

All 11 previously reported failure checks pass after local changes. No emails were sent, no private documents or real contact lists were sent to AI, and PythonAnywhere was not changed.

## Causes and fixes

| Failure | Cause | Fix |
|---|---|---|
| Body address selected as To | Address only had to occur somewhere in the source | Compare each recipient list with its corresponding source header |
| CC moved to To | No recipient-role validation | Validate To, CC and BCC separately; normalize display names to mailbox addresses |
| CC omitted | Empty AI fields were trusted | Reject mismatches with explicit source recipient lists |
| Unsupported date | ISO syntax was checked, source evidence was not | Parse supported source date forms and compare; unknown/ambiguous dates stay empty |
| Body shortened | Substring validation did not establish completeness | Compare the full body region with source text and check uncovered lines |
| Empty body despite source text | Zero body ranges were accepted | Require body/source agreement; genuinely missing bodies still allowed |
| All messages omitted | Empty model results were always accepted | Reject empty results when source message headers are present |
| Wrong subject | Any source substring was accepted | Compare with the source Subject header |
| Word headers omitted | Only main document body was read | Include header parts, including first/even-page variants |
| Word footers omitted | Only main document body was read | Include footer parts without duplicating linked parts |
| Nested tables omitted | Only immediate cell text was read | Recursively read cell contents and avoid merged-cell duplication |

## Final verification

- 381 automated tests passed, zero failures/errors/skips; Django checks and migration consistency passed.
- Original 19 live AI cases: 19 passed.
- Additional 22 live AI cases: 22 passed.
- Local reader and adversarial validation checks: 21 passed, including all 11 original failures.
- Synthetic contact matching matrix: 15 passed.
- Seven-file synthetic PDF pack: 7 passed, including a 10-page mixed document with eight emails; scanned/corrupt cases passed by being rejected as expected.
- Synthetic 90-page Word document: 30/30 drafts extracted; no subject, recipient or body-content mismatches across 52,774 extracted characters.

Live AI used the configured TAMU endpoint and synthetic documents. Contacts were mocked locally. Full app regression tests used an isolated database and mocked external services. These counts cover different layers and include overlapping scenarios; they are not a statistical accuracy percentage.

## Compatibility and limits

Explicit EMAIL DRAFT / END EMAIL DRAFT markers allow background notes between drafts. Ordinary paragraph drafts and simple/nested Word tables are supported by the reader. Display-name email addresses are compared by mailbox identity. Invalid original recipient text is still retained for worker review, with sending blocked by the existing missing-recipient guard.

The new validation rejects inconsistent or incomplete extraction instead of silently saving it. It does not repair every malformed AI response or automatically retry. Unmarked background notes interleaved between drafts may require clearer boundaries or separate uploads. Dates currently recognized by the source verifier are ISO YYYY-MM-DD and English month-name forms (for example October 1, 2026 or 1 October 2026); ambiguous/unsupported formats need clarification. Layout formatting is not reproduced, and headers/footers are collected as text, not rendered page-by-page. OCR and text embedded in images remain unsupported. Tests compare content with whitespace normalized.

Eleven permanent regression test methods were added in mail/tests/test_import_source.py. Existing missing-field fixtures now actually have missing fields in their source. Two upload-repeat fixtures now supply AI responses matching changed source content rather than silently discarding added text.

Previously reported unrelated shared-review/group-apply defects are outside this fix and are not claimed resolved.

## Evidence

- tmp/pipeline-edge-audit/results.json
- tmp/pipeline-edge-audit/expanded-results.json
- tmp/pipeline-edge-audit/deterministic-results.json
- tmp/pipeline-edge-audit/contact-matrix-results.json
- tmp/import-edge-cases/results.json
- tmp/import-edge-cases/synthetic-90-page-results.json
- tmp/document-import-release/automated-checks-shared-memory-20260923T211331070148Z.json
