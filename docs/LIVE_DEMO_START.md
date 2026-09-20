# Start the local V3 live demo

This starts the existing Windows app with **real Gmail delivery** at `http://127.0.0.1:8000`. It uses the existing accounts, database, attachments, Google connection and `.env`. Keep those files private and preserve the original token encryption key.

From PowerShell in the project directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-live.ps1
```

Keep the terminal open throughout the demo. Open **http://127.0.0.1:8000** on the same computer. Stop this server with **Ctrl+C** when finished. If port 8000 is occupied, the launcher stops without killing any process. Use the existing server if it is already in Gmail mode; otherwise stop that server in its own terminal before rerunning.

To check local configuration and database readiness without starting another server:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-live.ps1 -CheckOnly
```

The check-only option is safe to run while the existing server is open. It checks Gmail mode, OAuth/encryption configuration, the exact local callback, Django system checks and applied migrations. It does not contact Google, refresh tokens, send mail, change credentials, seed accounts or apply migrations. Google may still require reconnection when a send is attempted. A connected account indicator alone does not prove fresh provider authorization.

## Demo sequence

1. Sign in as the assistant. Create a new draft addressed only to an agreed test mailbox. Add up to three sample attachments, choose today's date and save. Saving does not send.
2. Sign in as the executive, open the draft and verify To/CC/BCC, subject, body, attachments and signature.
3. Click that draft's **Send now** once. In Gmail mode this sends a real email. Do not use **Send Current Messages** until you have reviewed every current workspace draft; that action includes all drafts dated today or earlier, regardless of the active filter.
4. Confirm the app reports Gmail delivery, then check the recipient mailbox for the actual message and attachments. A “Demo delivery saved” result means that server is still running in demo mode and needs to be restarted after its existing `.env` is corrected.
5. If the app reports **Delivery needs checking**, check Gmail Sent before any manual reconciliation. Do not create another copy or retry blindly; Gmail may already have accepted it.

The V3 rule remains unchanged: only an executive's explicit Send action sends email. Dates organize Current/Future drafts; there is no scheduled sender.

## If startup or Google fails

- **Demo mode:** the existing `.env` must contain `MAILSEND_DELIVERY_MODE=gmail`. Restart the process after a change. Do not use `start-demo.ps1` for this live run.
- **Missing dependencies:** install `requirements.txt` into the existing `.venv` once. The launcher does not reinstall packages on every start.
- **Missing database/secret:** restore the original files or correct their paths; do not run `seed_demo` or replace the encryption key to repair a live connection.
- **Pending migrations:** back up the existing database before running `manage.py migrate` with the project Python.
- **Google reconnect required:** sign in as the executive and reconnect the matching Google account. The authorized local callback must be exactly `http://127.0.0.1:8000/accounts/google/callback/`.

## Public launch is separate

This launcher uses Waitress on loopback with local static-file handling and the existing development settings. It does **not** provide a public URL, HTTPS, production secrets, verified Google consent for all buyers, or a verified backup/restore process. Do not expose this local DEBUG-enabled server to the internet. Follow [DEPLOYMENT.md](DEPLOYMENT.md) for the separate Linux Docker/Caddy production deployment and its host-specific checks.
