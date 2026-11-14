$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Run setup_windows.ps1 first." }

$env:ARVI_DB_PATH = Join-Path $PSScriptRoot "arvi_local.db"
$env:ARVI_LIVE_TRADING = "NO"
$env:PYTHONUNBUFFERED = "1"

$envFile = Join-Path $PSScriptRoot ".env"
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) { continue }
        $parts = $trimmed -split "=", 2
        $name = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($name -match '^[A-Z_][A-Z0-9_]*$') { [Environment]::SetEnvironmentVariable($name, $value, "Process") }
    }
}
$env:ARVI_LIVE_TRADING = "NO"
$env:ARVI_LIVE_TRADING_APPROVED = "NO"
Write-Host "AI-ARVI-ALGO local dashboard starting. Live trading is forced OFF." -ForegroundColor Green
Write-Host "Open http://127.0.0.1:8501. Keep this window open. Press Ctrl+C to stop."
& $python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
