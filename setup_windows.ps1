$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "AI-ARVI-ALGO Windows setup" -ForegroundColor Cyan
$python = Get-Command py -ErrorAction SilentlyContinue
if (-not $python) { throw "Python launcher not found. Install Python 3.11 x64 from https://www.python.org/downloads/ and enable 'Add Python to PATH'." }

$version = & py -3.11 --version 2>&1
if ($LASTEXITCODE -ne 0) { throw "Python 3.11 is required. Install Python 3.11 x64, then rerun this script." }
Write-Host $version

if (-not (Test-Path ".venv")) { & py -3.11 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }

if (-not (Test-Path ".env")) {
    @"
# Add your own Kite API credentials locally. Never commit this file.
KITE_API_KEY=
KITE_API_SECRET=
# Optional; daily Kite access token expires and must be renewed.
KITE_ACCESS_TOKEN=
"@ | Set-Content -Encoding UTF8 ".env"
}
Write-Host ""
Write-Host "Setup completed. Edit .env with your Kite credentials, then run .\run_windows.bat" -ForegroundColor Green
