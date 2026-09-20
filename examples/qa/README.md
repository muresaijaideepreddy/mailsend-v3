# CSV checks

These synthetic addresses use the reserved `.test` domain. Use them in demo mode; they are not real delivery targets.

- `mail_merge_multiline.csv`: use subject `Hello {{first_name}}` and body `{{organization}}: {{note}}`. The preview should contain two drafts, preserving the quoted comma, multiline note, and accented name. Creating drafts must not send email.
- `bcc_duplicates.csv`: import into a draft's BCC CSV field. It should add two unique recipients, keeping the first spelling of the duplicated address.
- `invalid_empty_email.csv`: mail merge or BCC import must report **CSV row 4** and save nothing because the final row has no email address.

CSV error row numbers identify each record's starting physical line in the source file, including blank lines and quoted multiline values.
