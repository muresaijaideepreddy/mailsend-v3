# Supplied MailSend implementation audit

Date: 2026-09-19. Source: the separately supplied `MailSend_v3_Django/mailsend_v3` reference project (not included in this repository).

Source, source database and source environment files were not changed. Application source and tests were copied into `tmp/supplied-audit/`, excluding environment files, SQLite databases, media and the virtual environment. Tests used an in-memory database and Django's local-memory email backend; no mail was delivered. The supplied virtual environment supplied its existing installed dependencies.

## Results

- Existing suite: **281 tests passed in 12.078 seconds**.
- Independent regression expectations: **8 checks failed in 0.350 seconds**, each reproducing a gap not covered by the supplied suite.
- Original run output: `tmp/supplied-audit/supplied-tests.log`.
- Additional checks: `tmp/supplied-audit/mail/tests/test_audit_regressions.py` and `tmp/supplied-audit/independent-regressions.log`.

## Reproduced defects

All paths and line numbers in this table refer to the supplied source, not the application being developed in the current workspace.

| Severity | Source | Reproduction and effect |
| --- | --- | --- |
| High | `accounts/views.py:110` | A callback with no saved session state reaches the token exchange. The comparison rejects unequal states only when both are present. The test mocks the provider; it establishes missing callback validation, not a live Google exploit. |
| High | `accounts/views.py:127` | A provider response with `verified_email=False` signs into an existing manager matched by email. There is no verified-email or durable provider-subject binding. |
| High | `config/urls.py:13` | Under the default DEBUG=True configuration, an anonymous request to a known attachment media URL receives HTTP 200. The authenticated attachment view is bypassed by static media serving. |
| High | `mail/views.py:574` | Open review of the first draft, delete it elsewhere, then submit the old form: the second draft is overwritten with the first draft's edits. POST chooses the current index rather than binding the submitted draft identity and version. |
| High | `mail/models.py:215` | An hour-old SENDING record can be claimed for sending again. If its first provider request was accepted before the process lost confirmation, retry can duplicate delivery. No uncertain state distinguishes this case. |
| Medium | `mail/views.py:320` | An assistant can POST BCC upload against a sent message and rewrite its stored recipient history. This route does not require an editable draft. |
| Medium | `mail/views.py:247` | An assistant can POST the delete endpoint for a sent message and remove shared sent history. UI hiding does not protect the route. |
| Medium | `mail/views.py:255` | A delete request with `next=//external.example/path` is accepted and redirects to an external origin. |

## Additional source findings

- `accounts/models.py:171`: access token, refresh token and OAuth client secret are stored in plaintext database columns. The current workspace implementation encrypts token data.
- `mail/models.py:192` and `templates/mail/message_detail.html:41`: sent detail renders the current workspace signature instead of preserving the signature actually sent.
- `mail/forms.py:224`: attachment replacements delete the old file before the database transaction commits; a later storage/database failure can leave a restored database row pointing to a missing file.
- `mail/transport.py:194`: the service has no executive/tenant guard itself; HTTP routes supply manager gating. The current workspace checks permissions at both layers.

## Functionality comparison

Both applications provide role-specific outbox/dashboard screens, composing/editing/deleting drafts, date review, executive single/bulk sending, three attachment slots, CSV mail merge/BCC import, signature, sent history and worker password administration. The supplied application's UI closely uses traditional table/form navigation and year/month/day selects.

The supplied implementation is a separate backend with a custom User model and one automatically provisioned worker per manager. It is not a drop-in theme for the current project. It also adds Gmail Inbox/read scope, replies, and optional unattended scheduled sending. The current V3 contract intentionally leaves legacy Inbox inactive and requires explicit executive send approval; current source also has preview/confirmation/version checks and supports multiple assistants. Preserve these controls while applying the reference UI layout.

The eight independent checks intentionally remain failing in this read-only audit copy. They were not added to the current application's test package. No supplied backend was substituted into the running application.
