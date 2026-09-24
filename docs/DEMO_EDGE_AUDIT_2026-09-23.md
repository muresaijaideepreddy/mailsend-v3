# Demo edge-case audit — September 23, 2026

Scope: local MailSend import, contacts, shared review, authorization and sending safeguards. All new probes used synthetic inputs and an isolated database. No real email was sent, no private document was transmitted, and no production deployment was changed.

## Results

- Existing regression suite: 368 passed, zero failures/errors.
- Adversarial probe suite: 20 checks, 13 passed, 7 failed, zero errors. Five inherited review tests overlap existing coverage; totals are not unique test counts.
- The seven failed checks represent six defect categories below. These findings have not been fixed by this audit.

## Confirmed defects

1. **Unsaved edits disappear on invalid or stale save.** The database correctly rejects an invalid recipient or stale version, but rendering reloads saved records instead of preserving submitted subject/body text. Two failed probes cover this category. Users may lose work and inadvertently retry against newly displayed state.
2. **A changed source recipient can still propagate through an old same-name group selection.** Search/review a John Smith group, change the source draft greeting to another person and To to that person's address, then apply the existing group checkbox. The peer receives the new address even though its recipient name remains John Smith. The submitted source identity is not rechecked against the signed group name.
3. **Group application bypasses an unresolved CC review guard.** A peer's To is intentionally blank because its imported CC was invalid. Group-apply fills To and makes the peer appear ready without resolving the CC warning.
4. **An explicit invalid To header can be overridden by a different greeting.** With a retained To value containing an invalid email and a body greeting addressed to another known contact, name inference skips the header because it contains @, then exact matching fills To from the greeting. Conflicting evidence must require review.
5. **AI recipient provenance is too broad.** A synthetic response selected an address mentioned only in the body while the source To was blank. Validation accepts it because the address exists anywhere inside the message span. Prompt instructions alone do not enforce recipient-header provenance.
6. **An invented but valid ISO date passes validation.** A synthetic response returned 2028-01-15 while the source explicitly said October 1, 2026. Only ISO parsing is checked, so the wrong planning date is accepted.

## Passed targeted safeguards

Tampered and expired group tokens roll back changes; same filenames in distinct upload batches are not grouped; invalid recipient/header injection is rejected; sent drafts cannot be edited; invalid IDs are rejected; CSRF is enforced; contact notes are HTML-escaped; other-workspace access is denied; worker edits remain drafts; stale peer changes roll back a group transaction. Existing V3 tests also passed executive sending, worker restrictions, send approval invalidation, and replay protections.

## Demo recommendation

Fix recipient provenance, conflicting-name handling and group-recipient safeguards before an unrestricted customer demo, then preserve failed form submissions. Validate dates against source data. Promote the failing probes into regression tests as fixes are implemented.

Passing the existing suite does not mean every edge case is covered. These deterministic probes simulate malformed or inconsistent AI output; they do not assert that every real AI request produces these failures. OCR/image-only PDFs, arbitrary document layouts, provider outages and real-mail delivery remain separate limitations or checks. This audit did not send mail to prove delivery.

Evidence: `tmp/document-import-release/demo-edge-probe-results.json`, `demo-edge-probe.log`, `demo_edge_probes.py`; full suite report `automated-checks-shared-memory-20260923T195810156393Z.json` in the same directory.
