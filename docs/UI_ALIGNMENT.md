# UI reference alignment and verification

Updated September 19, 2026. Target: the application in this repository, as selected by the user. The separately supplied project was reviewed as a reference; its source, database and credentials were not modified.

## Visual comparison and changes

The former running UI used a sidebar, large editorial headings and summary cards. It did not match the traditional MailSend screenshots. The revised UI follows the supplied V1 screenshots and the reference Django project's visual structure:

| Screen | Updated layout |
| --- | --- |
| Navigation | Dark maroon horizontal header; MailSend, Outbox, Inbox, Sent, Signature; executive Worker link and Mail merge access. Account security/Google connection are in the account menu. |
| Assistant outbox | White card on gray background; maroon New Message action; separate Send On, To and Subject columns; blue Edit and red Delete actions. |
| Executive dashboard | New Message followed by All Messages, compact executive Send Current and Edit Current/Future/All controls, and per-message Send/Edit/Delete actions. Counts and search are available under Filter messages. |
| Compose/review | Send date and stacked recipients on the left, BCC CSV and mail-merge access on the right; subject and body across the form; three attachment slots; green Save and red Cancel. |
| Sign in | Centered simple form, blue local sign-in button, red Google sign-in button when configured. |
| Sent/signature | Plain headings and compact table/form styling consistent with the other pages. |
| Mobile | Collapsible navigation; stacked compose/import/attachment fields; horizontally scrollable tables with keyboard access and an explanatory hint. |

The date uses a native date picker instead of three separate dropdowns. Mail merge opens the existing upload/preview workflow; BCC import stays on compose. Extra confirmation, review version checks, meaningful error messages, accessible labels and mobile controls are retained. The result is a close layout/style match, not a claim of pixel-identical reproduction.

The V3 design's executive approval workflow is preserved. Inbox remains inactive and drafts never send automatically. Features added only by the supplied code (live Inbox/replies and optional unattended scheduling) were not imported. No reference account credentials or real recipient examples were copied into application data.

## Verification

- Full current application suite: **156 tests passed in 33.097 seconds**, measured with coverage; **90% combined statement/branch coverage**. Log: `tmp/reference-full-tests.log`; summary: `tmp/reference-coverage.txt`.
- Django system checks passed; no pending migrations; static assets collected successfully.
- Desktop visual inspection compared the 1280-pixel browser layout against the source screenshots: login, assistant outbox, compose and worker management. Mobile inspection used a 390-pixel viewport and checked navigation, dashboard, compose inputs, attachments, and save/cancel controls. No page-level horizontal overflow on compose; tables intentionally scroll within their container.
- Browser workflow test used a separate SQLite database and separate session cookies on port 8001. Assistant login, creating a draft with To/CC/BCC/body/future date, future filtering, logout/executive login, future sequential review with saved changes, explicit single-message approval, local demo delivery, Sent history, and opening mail merge all succeeded.
- The Google-connected user's real workspace and drafts were not used for these write tests. No external email was sent. Google consent/token exchange was verified in the earlier authentication check; live Gmail delivery remains untested.

## Supplied project findings

Its existing **281 tests passed**, but **eight additional independent regression checks failed**, reproducing problems in OAuth validation, attachment privacy, stale review, duplicate-send protection, sent-history integrity and redirects. These are findings in the supplied backend, which was not adopted. See [SUPPLIED_PROJECT_AUDIT.md](SUPPLIED_PROJECT_AUDIT.md) for exact source locations and reproductions. Audit reproduction artifacts remain in `tmp/supplied-audit/` and are separate from the running application's test suite.

The running server on port 8000 was restarted to clear cached templates. The updated dashboard and account menu were verified live, with the existing signed-in Google account still connected. Development auto-reload is enabled for future template changes. The isolated browser-test server was stopped after verification.
