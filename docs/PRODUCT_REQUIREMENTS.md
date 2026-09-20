# MailSend product requirements and precedence

The buyer's deliverable is **MailSend V3**. The user explicitly confirmed this priority on September 19, 2026.

0. The user's explicit September 20, 2026 update overrides earlier optional worker Google/email behavior: assistants use only username/password, collect no assistant email, and expose no planning time input. Executives retain Google/Gmail.
1. The main requirements in **Mailsend Design v3.0.pdf** define product behavior.
2. **MailSend V1.0 Screenshots.pdf** fills details that V3 leaves unspecified, such as the worker interface, CSV uploads and three attachment inputs. It does not override V3.
3. The legacy How to Use section must be interpreted consistently with V3's main workflow. The user explicitly selected manual executive sending.

## Required behavior

- Assistants create, assemble, edit and delete their own drafts. They cannot send, approve a send, or trigger automatic delivery.
- Executives see workspace drafts, edit every content field and attachment, review sequentially, and explicitly send individually or in a current-message batch.
- Current means send date on or before the workspace-local calendar date. Future means send date after that date.
- Send date is required; there is no time input. The nullable legacy time database column remains only for non-destructive compatibility and does not control display, ordering, grouping or sending.
- Saving, reviewing, importing a CSV or opening any page never sends email.
- Executive Google identity supplies sign-in and Gmail sending. Assistants use assigned usernames and passwords only; email and Google linking/login are removed, including previously linked assistant identities.
- The **Sign in with Google** button is executive-only. Request Gmail consent for an executive who needs a sending connection; create a new executive workspace only after successful sending consent. A verified Google email matching an existing assistant email or email-shaped username cannot provision another account.
- Separate accounts and workspaces remain isolated. Display the assistant's actual login username in Worker settings.
- Worker settings supplies an initial assistant username even for an older empty workspace. Preserve existing assistants and require the executive to set the new worker's password before local login is possible; no shared default password or public assistant registration is needed.
- Worker navigation, signature, sent history, CSV merge/BCC import, and up to three attachments follow V3 and the supplementary V1 reference.

## Explicitly outside the active V3 scope

- The legacy worker Schedule checkbox and unattended sending: these contradict the confirmed executive-control workflow.
- Live Inbox synchronization, daily received-mail polling, and Reply/Reply All: V3 explicitly labels this legacy feature inactive. Retain its labeled placeholder without requesting Gmail read access.
- Pixel-identical V1 widgets or old deployment hostnames: V1 is supplementary. A native date picker and separate CSV preview are acceptable when they preserve V3 functionality.

## Deployment acceptance

Production must use HTTPS, persistent private storage, production settings and a WSGI server, real Gmail mode, correct Google callback/consent configuration and independent secrets. Demo accounts/data must not be shipped. Automated provider mocks establish code behavior; real Google consent, live delivery and the hosting environment require separate verification and must never be reported as tested merely because mocks passed.
