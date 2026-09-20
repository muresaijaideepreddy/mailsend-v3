# MailSend V3 live demo

Use an inbox you control as the recipient. These files contain synthetic
content only; `checklist.csv` is an attachment, not a recipient import.

1. As the executive, set the workspace signature to `MailSend V3 demo`.
2. As the assistant, create a draft dated today with subject
   `MailSend V3 live demo - current` and body
   `Synthetic demonstration message prepared by the assistant.` Leave the
   optional planning time blank. Attach `overview.txt`, `checklist.csv`, and
   `notes.md`, then save.
3. Create a second draft dated tomorrow with subject
   `MailSend V3 live demo - future` and body
   `Synthetic future draft; leave this pending.` Save it without sending.
4. Check Current and Future. The first draft belongs to Current, the second
   to Future. The assistant has no sending controls.
5. As the executive, open the current draft, inspect its recipient, signature,
   and all three attachments, then edit its body to add
   `Reviewed by the executive.` Save and inspect the result.
6. For real Gmail delivery, connect the executive's Google account and verify
   the app shows Gmail delivery mode. The executive can then choose **Send
   now** on this specific current draft after reviewing it. Demo delivery
   mode saves a local message and does not send email.
7. Verify Sent history and, for Gmail delivery, receipt in the controlled
   inbox with the edited body, signature, and three attachments. Confirm the
   future draft remains pending.

V3 requires an explicit executive send action. Waiting for a date or planning
time does not send either draft. Use Send Current only after reviewing every
current draft in the workspace, because it approves the entire current batch.
