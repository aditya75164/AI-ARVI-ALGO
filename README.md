# AI ARVI ALGO

Standalone Streamlit dashboard for NIFTY and BANKNIFTY signals and read-only Kite option contract discovery.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Kite Connect setup
Configure these values in Streamlit Cloud -> App -> Settings -> Secrets, or as environment variables:
- `KITE_API_KEY`
- `KITE_API_SECRET`
- Optional daily `KITE_ACCESS_TOKEN`

Never commit credentials. Without an API key and secret, login cannot be completed. Kite access tokens have a daily lifecycle: use the login flow in the sidebar and verify the profile after login.

## Features in this build
- Kite profile verification and NIFTY/BANKNIFTY 3m, 5m and 15m historical candle retrieval.
- Six-EMA, ATR, VWAP and RSI signal framework.
- NFO instrument lookup, nearest-expiry option filtering, ATM / ITM / OTM contract selection, live premium, bid/ask spread, volume, OI and lot size.
- Side-by-side Semi-Automatic and Fully Automatic preference selector.
- Live trading ON/OFF authorization preference in the UI.
- Paper-entry controls and paper-position monitor have been removed from the dashboard.

## Critical execution status
**This repository version does not execute live or paper orders.** The live trading switch is a UI preference only and is not connected to Kite order APIs. Turning it ON does not place an order; turning it OFF does not cancel or close any broker position. Do not use the switch as evidence that real-money execution is active.

Kite order placement, broker-side protective stop/target orders, persistent state and recovery, order lifecycle reconciliation (accepted/rejected/partial fills/cancelled), market-hours and stale-quote checks, kill switch, audit logging, and extended testing remain to be implemented and verified before live use. No real orders have been sent by this app build.

The DTC concept is invite-only; the indicator implementation here is an independent approximation based on publicly described concepts, not proprietary source code. No strategy or signal is guaranteed profitable.
