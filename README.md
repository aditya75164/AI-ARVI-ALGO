# AI ARVI ALGO

A standalone Streamlit application. It does not change or merge into the AI Stock Screener terminal.

## Run
```bash
cd ai_arvi_algo
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Kite setup
Set `KITE_API_KEY`, `KITE_API_SECRET`, and daily `KITE_ACCESS_TOKEN` as environment variables or deployment secrets. Never commit credentials. The access token lifecycle follows Kite Connect's daily login requirements.

## Current scope and safety
- NIFTY and BANKNIFTY index candle scanner.
- DTC-inspired six-EMA trend stack (30/35/40/45/50/60), ATR, VWAP and RSI.
- Editable option-premium target, stop-loss, trailing-stop preference, risk sizing and daily limits.
- Paper-trade premium calculator.
- No live order placement, no automatic option contract selection, no WebSocket streaming, and no broker order management in this initial foundation. Do not use for live trading.
- DTC is invite-only; this is an independent approximation from publicly described concepts, not an exact clone or endorsement.
