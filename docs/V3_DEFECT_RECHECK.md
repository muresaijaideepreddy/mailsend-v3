# V3 defect review before the live demo

> Historical note: later live inspection found that older workspaces did not receive an initial worker automatically, and that behavior was implemented and tested. The user subsequently explicitly removed automatic default workers. D52 is now a USER OVERRIDE; see [V3_ACCEPTANCE_REPORT.md](V3_ACCEPTANCE_REPORT.md). The results below remain the record of the earlier review.

Reviewed September 19, 2026 locally (September 20 UTC).

**No reproducible V3 application defect was found in this review.** The implemented workflows are ready for a controlled live demo. This does not establish that real Google consent, Gmail delivery or a public deployment works; those need live verification.

V3 governs. V1 supplements only unspecified details. Automatic worker sending and the explicitly inactive Inbox/Reply features are excluded under the user's confirmed requirements, not missing active V3 features. The complete 71-row traceability checklist remains in [V3_ACCEPTANCE_REPORT.md](V3_ACCEPTANCE_REPORT.md).

## Fresh results

| Check | Result |
|---|---|
| Entire automated suite | 237 passed; zero failures, errors or skips |
| Django system and migration checks | Passed |
| Installed dependency consistency | Passed |
| Additional independent integration probes | All five passed; separate from the 237-test suite |
| Application changes during this review | None |
| Real account changes or external emails | None |

The full run started at 2026-09-20 02:10:24 UTC and completed in 69.173 seconds including checks. See [V3_TEST_RESULTS.json](V3_TEST_RESULTS.json). Provider responses were mocked, test data/storage were isolated, and external connections were blocked. The production HTTP smoke permits loopback traffic only.

## Independent defect checks

Two reviewers independently inspected account/Google behavior and message workflows alongside the complete test run. Production settings, startup, private storage/static separation, reverse-proxy configuration and health checks were also reviewed. No confirmed defect was identified.

The five additional probes established:

1. Fresh executive signup provisions a worker; the executive can set its email/password; the worker can log in locally, link Google identity and return through Google. Assistant access to sending, executive team management and Gmail connection remains blocked.
2. Separate Google executives receive separate workspaces and workers. Cross-workspace draft access/edit/delete and worker profile/password access are rejected.
3. A signature change during the first batch delivery stops later drafts and preserves the first sent message's original signature.
4. A signature change while constructing the outgoing email prevents the provider call.
5. Replacing an attachment invalidates an old dashboard send approval.

Local probe scripts for account integration and workflow interactions are retained as private local audit artifacts and are not included in the source repository. Earlier browser and MIME checks remain recorded in the complete acceptance report; they were not rerun or relabeled as fresh browser tests during this code review.

## Still pending for live verification

- Real executive Google signup/login, assistant Google linking/login, and the buyer's intended OAuth user audience.
- An explicitly authorized test email to a controlled recipient: executive sender, recipients, body/signature, three attachments, receipt and Sent status.
- For a public production demo: Docker/Compose startup, DNS/HTTPS, persistent data and a backup/restore rehearsal on the chosen host. Docker is unavailable in this Windows environment and no public destination has been supplied.

These are open verification items, not reproduced software defects. Proceed to the controlled live demo to test Google behavior; do not describe full production acceptance as complete until the relevant live checks pass.
