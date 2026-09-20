# Live Gmail verification

At the user's request, the local app was switched from demo delivery to Gmail delivery and one real controlled test email was sent through the executive dashboard.

- Sent at: September 19, 2026, 9:36 PM America/Chicago (2026-09-20 02:36:24 UTC).
- App message: 15, `MailSend V3 live demo - controlled test`.
- Sender and recipient: the connected executive account (self-addressed test).
- Attachments: `overview.txt`, `checklist.csv`, `notes.md`, all synthetic demo files.
- Gmail API receipt: returned and verified; the account-specific identifier is retained privately.
- Database state: `sent`; audit records `send_started` with `Delivery mode: gmail.` and `delivery_sent`.
- Browser result: `Message sent.`; Sent history labels the new message `Sent` and the earlier local-only message `Demo delivery`.

The original local-only demo message (14) was retained unchanged. A fresh draft was created for the real send; the app did not reopen or relabel the demo history. The executive clicked the individual Send action through the browser automation, under the user's instruction to send the real email. No batch send or automatic retry was used.

The first credential preflight from the restricted execution environment could not reach Google. The local server was restarted with network access, still bound only to `127.0.0.1:8000`. It then refreshed the existing connection and Gmail accepted the send. Tokens and client secrets were not included in this report.

## Current state and remaining checks

`MAILSEND_DELIVERY_MODE=gmail` is persisted in the local `.env`; sends now use Gmail. This is a local live-email demo, not a published production deployment.

Google's acceptance and the application's saved receipt are verified. Recipient inbox arrival and successful opening of the three received attachments await the user's confirmation. The send used an existing linked executive account; it does not establish a fresh production OAuth consent flow or assistant Google login.

Public hosting still requires the chosen server/domain, HTTPS and deployment/backup verification described in [DEPLOYMENT.md](DEPLOYMENT.md). Automated tests and previous local reviews remain recorded in [V3_ACCEPTANCE_REPORT.md](V3_ACCEPTANCE_REPORT.md).
