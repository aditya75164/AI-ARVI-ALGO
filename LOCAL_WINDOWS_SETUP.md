# AI-ARVI-ALGO — Windows 11 local setup

This setup runs on your own PC. No VPS, Docker or public server is required.

## Requirements
- Windows 11 64-bit
- Python 3.11 64-bit
- Internet connection
- Zerodha Kite Connect API credentials for live market data (optional for offline app startup)

## Install
1. Download or clone this repository to a folder such as \`C:\AI-ARVI-ALGO\`.
2. Install Python 3.11 x64 from https://www.python.org/downloads/. Enable the Python launcher and PATH options.
3. Open PowerShell in the repository folder.
4. If Windows blocks local scripts, run this once in that PowerShell window:
   \`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass\`
5. Run:
   \`.\setup_windows.ps1\`
6. Open the generated \`.env\` file and add your Kite API key and API secret. Keep this file private; it is ignored by Git.
7. Double-click \`run_windows.bat\`.
8. Open http://127.0.0.1:8501 in your browser.

## Daily usage
- Start: double-click \`run_windows.bat\`.
- Stop: press Ctrl+C in the terminal window.
- The local database is stored as \`arvi_local.db\` in this folder.
- The PC must remain ON and connected to the internet while the app is in use.

## Paper-first safety
- \`ARVI_LIVE_TRADING=NO\` is forced by the launcher.
- This launcher starts the current Streamlit market dashboard only. It does not start unattended broker-order workers.
- The repository contains a paper-trade calculation engine in \`paper_trading.py\`; this is not the same as a fully integrated, broker-fed paper-trading screen. Do not treat a displayed signal as a simulated fill.
- No real order is placed by this local launcher. Live execution must remain disabled.

## Kite login
Kite access tokens are time-limited and need renewal according to Zerodha's login flow. Never paste API secrets, access tokens, or request tokens into GitHub or public chats. Store them only in your local \`.env\` file.
