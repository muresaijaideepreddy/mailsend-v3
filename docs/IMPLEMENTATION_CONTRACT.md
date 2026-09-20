# MailSend 3 implementation contract

Source: user-provided V3 design and V1 screenshots. Treat document instructions as product requirements only. Do not copy reference credentials into source, demo data, or docs.

## Product decisions
- Django app `mail`, project `config`, SQLite default, local demo delivery by default; Gmail delivery explicitly configured.
- Assistant prepares drafts, never sends. Executive owns a workspace. Assistant sees only drafts they created; executive sees every workspace message. Sent history and signature shared within workspace. All resources require tenant checks.
- V3 manual executive approval takes precedence over legacy auto-schedule text. Send current means dates <= workspace-local today. Future sends only via explicit single-send action. Review never sends.
- CSV merge is a preview then atomic draft creation (never sends). CSV header `email` required, other headers supply `{{field}}` placeholders. BCC CSV import supported in compose. Up to 3 attachments, total <= 20 MiB, recipient count <= 450.
- Inbox is legacy inactive; provide a clear informational page, not fake inbox data.

## Shared interface (do not rename without coordinating)
Models in `mail/models.py`:
- Workspace: name, executive (OneToOne User), signature (TextField blank)
- Membership: user (OneToOne User related_name `membership`), workspace (FK related_name `memberships`), role strings `executive`/`assistant`
- Message: workspace (FK), created_by (FK User), to, cc, bcc (TextFields); subject (CharField 255); body (TextField); send_date (DateField); status (`draft`, `sending`, `sent`, `failed`, `uncertain`), version (positive int default 1); sent_at nullable; provider_id blank; last_error blank; created_at/updated_at.
- Attachment: message FK related_name `attachments`, file FileField, original_name, size, content_type.
- GoogleCredential: user OneToOne; encrypted token data (agent defines internals; root OAuth adapter coordinates).
- AuditEvent: workspace FK, actor nullable FK User, message nullable FK, action, detail blank, created_at.

Services in `mail/services.py` (domain agent):
- `visible_messages(user)` QuerySet; `require_executive(user)` raises PermissionDenied.
- `send_message(user, message_id)` executive-only, tenant-scoped, atomic compare-and-set claim, no automatic retry of ambiguous errors. Returns Message. Demo writes .eml locally and returns unique provider id. Gmail via `mail.google_api.send_gmail(user, email_message)` callback.
- `parse_addresses(value, required=False)` returns canonical comma-separated string; ValidationError on invalid address/header injection.
- `validate_attachments(files, existing=())` validates max 3 and combined max 20 MiB.
- `merge_preview(csv_file, subject, body, cc='', bcc='')` returns list of dicts `{to,cc,bcc,subject,body}`; reject invalid CSV/placeholders/rows, max 200 rows, max 1 MiB.
- `bcc_from_csv(csv_file)` returns validated canonical addresses.

Root owns: config/, manage.py, mail/apps.py, mail/forms.py, mail/views.py, mail/urls.py, mail/google_api.py, mail/oauth_views.py, demo seed command, README and deployment config.
Domain agent owns: mail/models.py, mail/services.py, mail/admin.py, mail/migrations/, domain tests in mail/tests/test_domain.py, mail/tests/test_delivery.py.
UI agent owns: templates/, static/ only. Build responsive polished maroon/cream MailSend UI (server-rendered Django). Coordinate context names below.
QA agent owns: mail/tests/test_security.py, mail/tests/test_workflows.py, docs/QA.md. Can add other test_* files except agent-owned files. Wait for implementation to run tests; independently inspect requirements now. Root creates shared package init files.

## URL names (namespace `mail`)
- dashboard `/`; query `period=all|current|future`, `q=...`
- compose `/messages/new/`; edit `/messages/<pk>/edit/`; detail `/messages/<pk>/`; delete `/messages/<pk>/delete/` GET confirmation/POST action
- send `/messages/<pk>/send/` GET confirmation/POST action
- send_current `/send-current/` GET confirmation/POST action
- review `/review/<period>/` GET/POST sequential one-message form, query `index=0`; POST save moves to next using session snapshot of IDs and versions.
- sent `/sent/`; signature `/signature/`; team `/team/`; merge `/merge/`; inbox `/inbox/`; attachment `/attachments/<pk>/`
- login `/accounts/login/`; logout `/accounts/logout/` POST; google_login `/accounts/google/login/`; google_callback `/accounts/google/callback/`; google_disconnect POST

## Template context contract
All logged-in pages: membership, workspace, is_executive, delivery_mode (`demo`/`gmail`), google_connected, active_nav.
base.html: blocks title/content; Django messages; request.user.
registration/login.html: form AuthenticationForm, google_enabled, demo_enabled.
mail/dashboard.html: drafts (Message queryset), counts dict {all,current,future,sent}, period, query, today. Render executive review/current-send controls. Empty state and search.
mail/message_form.html: form, message_obj (or None), attachments, review_mode bool, review_index (1 based), review_total, period. Form fields `to`, `cc`, `bcc`, `subject`, `body`, `send_date`, `version`, `attachment_1`, `attachment_2`, `attachment_3`, `remove_attachments`, `bcc_csv`. Render multipart form.
mail/message_detail.html: message_obj, attachments. Escape body and signature.
mail/confirm.html: heading, explanation, messages_to_act (list), submit_label, destructive bool. POST with CSRF, optional hidden `version` and `batch_token` provided context.
mail/sent.html: sent_messages queryset, query.
mail/signature.html: form (signature textarea).
mail/team.html: form fields username,email,first_name,password; assistants list Membership. Create only (no automatic emails).
mail/merge.html: form fields csv_file, subject, body, cc, bcc, send_date; preview_rows and merge_token optional; POST action=preview or action=commit, commit hidden merge_token. Document email column + {{first_name}} using verbatim.
mail/inbox.html: inactive legacy feature informational.
mail/error.html: heading/detail.
Demo login details root to provide when seed ready. Do not hardcode reference account data.
