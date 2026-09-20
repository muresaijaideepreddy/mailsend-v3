# Send date and time update

> Historical report, superseded by the user's V3-priority decision. Planning time is now optional; Current and Future use calendar dates only. Follow [PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md) and [V3_ACCEPTANCE_REPORT.md](V3_ACCEPTANCE_REPORT.md) for current behavior and verification. The results below describe earlier revisions.

September 19, 2026. The user explicitly requested a time field beside the send date. This supersedes the earlier date-only implementation decision.

- Compose, edit, executive review and mail merge require an explicit minute-resolution send time. No time is silently assumed.
- The UI displays the app timezone, currently America/Chicago, alongside planned and actual times.
- Current includes drafts with a chosen time on past dates or a time that has arrived today. Future includes explicitly timed drafts later today or on future dates. Older drafts without a time display Time not set in All and Needs time, and are excluded from Current, Future and Send Current until a time is set.
- Send Current only sends the due drafts in the executive's confirmation. A draft becoming due after that confirmation does not join the approved batch.
- Individual Send now can explicitly send before the planned date or time, consistent with the V3 executive override.
- Saving a date and time does not schedule unattended delivery. Executive approval remains required. The original document also describes a legacy Schedule checkbox; that separate automatic delivery workflow is not implemented by this field addition.
- Time edits increment the draft version, invalidating earlier send approvals. CSV preview/commit preserves the approved time for every generated draft.
- Existing drafts and sent history are preserved. Migration 0004 adds a nullable send_time column; it does not invent times for older messages. Older CSV previews without a time must be previewed again with a chosen time before creating drafts. Existing previews with a valid minute-resolution time remain usable.

## Latest verification: required time

The user pointed out that Any time did not communicate when sending should occur. The forms now require a specific time, legacy records display Time not set, and individual executive actions are labeled Send now. Planned send time determines due status; it does not promise a mailbox arrival time or enable unattended delivery.

All **197 tests passed in 48.783 seconds**, with **91% combined statement/branch coverage** (1,388 statements, 408 branches). The 22 send-time regressions cover required fields without invented defaults, midnight, missing-time filters, batch approval rechecks, strict minute precision, stale CSV previews and immediate executive overrides. System checks and migration consistency also passed. Both live role views and the side-by-side preview were refreshed and verified. No external emails were sent.

## Earlier verification: initial optional-time implementation

- 15 independent new regressions passed, including invalid inputs, save/edit/clear, local midnight and UTC date rollover, exact due-time boundaries, batch rechecks, stale approvals, review and CSV imports.
- Full suite: **190 tests passed in 53.389 seconds**; **92% combined statement/branch coverage**. Evidence: ignored `tmp/functional-qa/send-time-full-tests.log` and `send-time-coverage.txt`.
- Django system checks passed and `makemigrations --check --dry-run` found no outstanding model changes.
- Browser verification saved a synthetic draft at 23:45 in the isolated demo database, confirmed 11:45 PM in the outbox, and reopened the edit form with 23:45 preserved. The running app visibly presents native date/time controls and timezone guidance.
- No external emails were sent for this update. Ordinary app delivery remains demo.

## Outbox screenshot follow-up

The user supplied an assistant-outbox screenshot while the running account was an executive with no remaining drafts. The outbox now follows the reference more closely: maroon New Message button first, All Messages heading, roomy white card, compact table and blue/red edit/delete icons. Executive-only send and review controls remain in a small labeled section. Filters and search expand from Filter messages and stay open when a filter or query is active.

Browser checks verified the populated assistant table in the isolated test app and the executive view in the running app. Native date/time controls and a saved 23:45 value were verified. A narrow-layout check found the visually hidden table heading could cause page-wide horizontal overflow; positioning its scroll container fixed it. At a 390px viewport, document width now remains 390px while the wide table scrolls inside its container. After the outbox template update, all 47 workflow/time tests passed in 10.200 seconds.
