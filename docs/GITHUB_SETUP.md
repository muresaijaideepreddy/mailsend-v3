# Upload, run and test MailSend V3

This is a Python/Django application. Use Python 3.11 or newer; this revision was tested with Python 3.13.7. The project pins its dependencies in `requirements.txt`. Git is needed for cloning or pushing source code.

## Upload the source to GitHub

Use Git or GitHub Desktop with the repository's `.gitignore`. Do not upload the entire working directory manually: it also contains this computer's private configuration, accounts and mail.

The source repository includes `mail/`, `config/`, `templates/`, `static/`, `examples/`, `docs/`, migrations, tests, `manage.py`, dependency files, startup scripts and deployment files. Commit `.env.example` and `deploy/production.env.example` with their empty/example values.

Keep `.env`, real `*.env` files, `.local-secret`, Google client/token JSON, databases, `.venv/`, `private_media/`, `demo_outbox/`, `tmp/`, `data/`, `backups/` and `secrets/` out of Git. The included `.gitignore` excludes these files. It cannot remove a secret that was already committed; check the staged file list before pushing and never use `git add --force` for private files.

Create an empty repository under your GitHub account, without adding a README or other starter files. Replace `YOUR_GITHUB_REPOSITORY_URL` below with the HTTPS or SSH URL GitHub supplies. Run from the project folder:

```powershell
# Skip this line if the directory already contains a .git folder.
git init
git add .
git diff --cached --name-only
git commit -m "Add MailSend V3 application and setup guide"
git remote add origin YOUR_GITHUB_REPOSITORY_URL
git push -u origin HEAD
```

`git push -u origin HEAD` uses your current branch. If `origin` already exists, inspect `git remote -v` and use the correct existing remote rather than adding it again. Authenticate to your own GitHub account when Git requests it. These instructions do not create or publish a repository automatically.

Official references: [upload existing source](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github) and [Git ignore rules](https://docs.github.com/en/get-started/git-basics/ignoring-files).

## Run a fresh clone on Windows

Open PowerShell and replace the repository URL in the first command:

```powershell
git clone YOUR_GITHUB_REPOSITORY_URL mailsend-v3
cd mailsend-v3
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

These commands are for a **fresh clone**. Do not overwrite the `.env` or database in an existing live installation. The example configuration uses `MAILSEND_DELIVERY_MODE=demo`, so sending creates local `.eml` files and never delivers real email.

Open [MailSend](http://127.0.0.1:8000/) on the same computer. Keep the terminal open; press Ctrl+C to stop the server. If port 8000 is occupied, use `127.0.0.1:8001` in the final command for this demo-only run and open that port. Do not change ports for Google sign-in unless its registered callback is updated too.

Alternatively, from a fresh checkout run `powershell -ExecutionPolicy Bypass -File .\start-demo.ps1`. It creates the Python environment if needed, installs dependencies, migrates and seeds demo data. It refuses to seed in Gmail/production mode.

## Run a fresh clone on macOS or Linux

```bash
git clone YOUR_GITHUB_REPOSITORY_URL mailsend-v3
cd mailsend-v3
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

Linux distributions may require their Python venv package before `python3 -m venv` works.

## Fresh demo credentials

| Role | Username | Password |
|---|---|---|
| Executive | `executive` | `MailSend-Demo-2026!` |
| Assistant | `assistant` | `MailSend-Demo-2026!` |

These are synthetic accounts made by `seed_demo`. This computer's personal executive/worker logins and Gmail connection are **not** part of the repository. Repeating `seed_demo` preserves existing passwords. Use a regular browser window for one role and a private window for the other.

## Manual workflow check

1. Log in as the assistant and create a draft addressed to a synthetic address such as `recipient@example.test`. Set today's date, subject and body; optionally use the files in `examples/live-demo/` as attachments. Save it.
2. Confirm the assistant has no sending controls. Saving must leave the message in Outbox.
3. In the executive browser session, open the same draft and edit or review it.
4. Click that message's **Send now**. In demo mode it moves to Sent and writes a local email under `demo_outbox/`; no recipient receives it.
5. Create a future-dated draft and try **Send Current Messages**. The batch includes dates up to today, while future drafts remain unsent. An executive can explicitly send a future draft individually.
6. Try the synthetic CSV files in `examples/qa/` and update the shared signature. CSV import prepares drafts and never sends.

The seeded workspace already contains sample drafts. Review the whole current batch before using **Send Current Messages**. Optional planning time never schedules delivery.

## Automated tests

From the fresh demo checkout, in a second PowerShell terminal:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test mail.tests -v 2
```

On macOS/Linux replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`. The suite uses isolated test databases and mocks Google responses. It covers permissions, separate workspaces, sending rules, dates, attachments, CSV, signatures, Google login and local production-serving checks. It never sends real emails. Latest recorded application results: [V3_TEST_RESULTS.json](V3_TEST_RESULTS.json); requirement coverage and remaining external checks: [V3_ACCEPTANCE_REPORT.md](V3_ACCEPTANCE_REPORT.md).

On September 20, 2026, a clean export containing only Git-included source files passed fresh migrations, demo seeding, dependency checks, system checks, migration consistency checks and all **276 tests** (93.699 seconds for the test suite). Both documented demo logins and their role restrictions were verified against the fresh database. This used the existing Python environment with the pinned packages; downloading/installing dependencies on another computer and macOS/Linux execution were not independently tested in this check. No existing personal accounts or Gmail connections were copied, and no real email was sent.

Optional coverage:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m coverage run manage.py test mail.tests
.\.venv\Scripts\python.exe -m coverage report
```

## Real Gmail and public hosting

Google sign-in is hidden until Google OAuth and token encryption are configured. A new clone cannot reuse this computer's Gmail connection. Follow [Connect Gmail in the README](../README.md#connect-gmail) to configure your own OAuth client, register the exact callback, set a private encryption key and sign in with an executive's Google account. Configure the intended users in the Google project and verify their real consent flow before a buyer demo.

Use a separate installation and fresh database for real Gmail or production instead of promoting the synthetic demo accounts. Keep delivery in demo mode until the real sender and recipients are ready, then set `MAILSEND_DELIVERY_MODE=gmail` and restart. Only an executive Send action sends real mail. Assistant Google login currently requires one initial local login and explicit Google linking.

The configured local Windows Gmail demo can use [start-live.ps1](../start-live.ps1); its prerequisites are in [LIVE_DEMO_START.md](LIVE_DEMO_START.md). Public HTTPS hosting requires the separate [DEPLOYMENT.md](DEPLOYMENT.md) procedure. Uploading source to GitHub does not itself deploy or run this Django app.
