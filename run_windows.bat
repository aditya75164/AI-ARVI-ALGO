@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Environment not found. Run setup_windows.ps1 first.
  pause
  exit /b 1
)
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
  )
)
set ARVI_DB_PATH=%CD%\arvi_local.db
set ARVI_LIVE_TRADING=NO
echo Starting AI-ARVI-ALGO locally. Live trading is disabled.
echo Keep this window open while using the dashboard.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
pause
