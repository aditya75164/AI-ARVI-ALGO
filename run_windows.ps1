$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Run setup_windows.ps1 first." }

$env:ARVI_DB_PATH = Join-Path $PSScriptRoot "arvi_local.db"
$env:ARVI_LIVE_TRADING = "NO"
$env:ARVI_LIVE_TRADING_APPROVED = "NO"
$env:PYTHONUNBUFFERED = "1"
$port = if ($env:ARVI_LOCAL_PORT) { [int]$env:ARVI_LOCAL_PORT } else { 8502 }

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

$configPath = Join-Path $PSScriptRoot "bot_config.json"
if (-not (Test-Path $configPath)) { Copy-Item (Join-Path $PSScriptRoot "bot_config.example.json") $configPath }
$env:ARVI_BOT_CONFIG = $configPath
$worker = $null
try {
    Write-Host "Starting local ARVI signal worker (SIGNAL_ONLY; live orders forced OFF)..." -ForegroundColor Cyan
    $worker = Start-Process -FilePath $python -ArgumentList "bot_worker.py" -WorkingDirectory $PSScriptRoot -RedirectStandardOutput (Join-Path $PSScriptRoot "worker.log") -RedirectStandardError (Join-Path $PSScriptRoot "worker-error.log") -PassThru
    Write-Host "Signal worker PID: $($worker.Id)" -ForegroundColor Green
    Write-Host "Starting local dashboard. Open http://127.0.0.1:$port." -ForegroundColor Green
    Write-Host "Keep this window open. Press Ctrl+C to stop dashboard and worker."
    & $python -m streamlit run app.py --server.address 127.0.0.1 --server.port $port
}
finally {
    if ($worker -and -not $worker.HasExited) { Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue; Write-Host "ARVI signal worker stopped." -ForegroundColor Yellow }
}
