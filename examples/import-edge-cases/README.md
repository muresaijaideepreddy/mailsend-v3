# MailSend document import edge cases

Synthetic fixtures only, using example.test addresses. No real credentials or private documents are included.

## September 23, 2026 results

All seven cases passed. Five readable PDFs were tested against the configured TAMU Claude service; the scanned and corrupt PDFs were rejected locally. The full automated suite passed 339 tests, including 33 importer tests.

| File | Verified outcome |
| --- | --- |
| 01-mixed-10-pages.pdf | Eight drafts, all expected fields preserved, including the complete body across pages 6 and 7 |
| 02-notes-only.pdf | No drafts |
| 03-incomplete-drafts.pdf | Two drafts; missing recipient, date and body stay blank |
| 04-misleading-instructions.pdf | One legitimate draft; embedded instructions and unrelated contacts ignored |
| 05-password-word-in-email.pdf | Ordinary password reminder wording preserved |
| 06-scanned-image-only.pdf | Rejected locally because OCR is not supported |
| 07-corrupt-upload.pdf | Rejected locally as an invalid PDF |

The browser upload also created all eight ten-page sample drafts in the local Outbox. Every persisted field matched expected-results.json after whitespace normalization. No emails were sent. Earlier service-only tests did not save drafts.

## Fixes verified

Cross-page drafts previously failed because a footer and continuation heading interrupted the source body. Cleanup now uses PDF layout and position to identify those lines while preserving ordinary text at page boundaries. The credential filter also previously removed normal prose about passwords; it now targets explicit credential labels instead.

Different files can be uploaded sequentially, including from a cached form. An exact repeat on the same form remains protected against duplicate submission; a fresh form allows deliberate reimport.

## Coverage and use

Upload one numbered PDF through Outbox > Import document. Compare drafts with expected-results.json. The ten-page fixture includes missing fields, multiple recipients, CC/BCC, repeated subjects, merge placeholders, an attachment reference, background notes, misleading instructions and fake credentials.

Workers in the same workspace can edit executive-created drafts. Missing required fields block sending. Referenced attachments must be supplied separately.

These results verify the supplied synthetic fixtures, not every possible document layout. Images and original formatting are not imported; scanned PDFs need OCR first. Full email wording takes priority over reducing AI usage.
