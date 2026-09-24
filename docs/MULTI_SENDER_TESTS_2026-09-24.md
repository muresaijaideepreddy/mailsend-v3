# Multiple sending accounts — local verification

September 24, 2026. Available locally; not deployed to PythonAnywhere or pushed to GitHub in this change.

The existing custom Signature editor is retained. MIME tests verify that its text is appended to an additional sender's outgoing message. Primary login and contacts remain tied to the original executive; secondary sending grants are stored separately and encrypted.

## Results

- Full regression suite: 395 tests passed, zero failures/errors/skips. This included the first 13 sender tests and existing signature and mail merge coverage.
- Final targeted suite: all 17 sender tests passed after adding imported-review, mixed-token, forged-identity and callback checks.
- Django configuration and migration consistency checks passed. Migration 0011 applied locally. Local login returned HTTP 200 after restart.
- No real email was sent; Google provider calls were mocked. Tests used isolated database storage.

The sender tests cover MIME From and signature, selected-token delivery without a primary token, foreign-workspace rejection, disconnected sender rejection, token refresh isolation, worker sender edits and approval invalidation, foreign sender form rejection, executive-only account management, POST-only OAuth initiation and scope selection, secondary linking without primary identity changes, disconnect behavior, sent-address snapshots, personalized merge drafts retaining the sender, disconnect between merge preview and creation, imported-draft sender selection, primary/secondary token routing, forged From/identity rejection, and callback session preservation.

## Remaining live check

An executive must authorize each additional real Google account under Sending accounts, then explicitly approve test delivery to a chosen recipient. Automated tests do not prove that a particular institution permits OAuth grants or that its live mailbox accepts delivery. Revoked/expired permissions require reconnection. The app retains the one workspace signature for all senders; per-account signatures and secondary contact imports are not included.

Detailed test logs remain locally under `tmp/document-import-release/` with timestamps `20260924T150108761531Z` (full suite) and `20260924T150630157616Z` (final sender suite).
