$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment.' }
}
# Also repairs an interrupted first install or changed requirements on later runs.
& '.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& '.venv\Scripts\python.exe' manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw 'Database setup failed.' }
& '.venv\Scripts\python.exe' manage.py seed_demo
if ($LASTEXITCODE -ne 0) { throw 'Demo setup failed. Check .env delivery mode.' }
Write-Host 'Open http://127.0.0.1:8000. Sign in as executive or assistant.'
& '.venv\Scripts\python.exe' manage.py runserver 127.0.0.1:8000
