# AI ARVI ALGO

Standalone Streamlit application for NIFTY and BANKNIFTY index signals, Kite option contract discovery, and simulated options trading.

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
- NFO instrument-master lookup, nearest-expiry option filtering, ATM / ITM / OTM contract selection, live premium, bid/ask spread, volume, OI and lot size.
- Lot-size-aware paper quantity calculator using capital-at-risk.
- Paper trade entry, live-LTP refresh while the Streamlit session is open, target/stop/trailing-stop simulation, manual paper exit, trade history and daily risk blocks.
- GitHub Actions syntax compilation and pytest checks.

## Important execution boundary
This version is PAPER ONLY. It does not call Kite `place_order`, does not send real orders, and does not provide unattended live trade execution. Paper positions currently live in Streamlit session state and are cleared when the session/app restarts. The paper monitor requires an active Kite session and the app tab to remain connected. It is not a broker-side stop-loss and cannot protect a real position.

Before any real-money use, the app still needs persistent state and recovery, WebSocket/reliable quote monitoring, exchange/market-hours and stale-data checks, order lifecycle reconciliation (accepted/rejected/partial fills/cancelled), broker-side protective orders, kill switch, audit logging, and extended paper-forward testing. No trading strategy or signal is guaranteed profitable.

The DTC concept is invite-only; the indicator implementation here is an independent approximation based on publicly described concepts, not proprietary source code.
