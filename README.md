# AI ARVI ALGO — F&O and Equity Stock Scanner

Read-only Streamlit market scanner. The primary workflows are separate stock-selection screens for (1) F&O-eligible stock underlyings and (2) NSE cash-equity stocks.

## Main screens
- **F&O Stock Selection:** derives its stock universe from unexpired NFO stock futures, maps each underlying to its NSE cash instrument, ranks liquid candidates, and analyses daily historical candles.
- **Equity Stock Selection:** scans the NSE cash-equity universe independently using the same daily-candle trend and volume methodology.
- Both tables show stock, price, BUY/SELL/WAIT, trend, score, RSI, relative volume, momentum, volume, entry reference, target, stop loss, candle date and data source.
- Target and stop-loss percentages are editable. Defaults are 10% and 5%; they are calculation references, not predicted or guaranteed returns.
- Additional screens retain live quote monitoring, NIFTY/BANKNIFTY indicators and F&O option contract monitoring.

## Data and method
- Kite instrument masters define the F&O and NSE equity universes.
- Kite quote data ranks candidate stocks by turnover when available.
- Kite historical daily candles drive the stock signal calculation. If quote volume is unavailable (for example, outside market hours), the scanner falls back to a bounded deterministic slice of the instrument universe and labels results by their historical candle date.
- Daily signals use six EMAs (30/35/40/45/50/60), VWAP, RSI(14), relative volume and six-session momentum.
- BUY requires bullish EMA alignment, close above VWAP, RSI >= 52 and positive momentum. SELL requires bearish EMA alignment, close below VWAP, RSI <= 48 and negative momentum. Otherwise WAIT.
- This is a technical screening rule, not a promise of 10% returns or investment advice. Validate liquidity and current prices before any decision.

## Setup
Configure `KITE_API_KEY`, `KITE_API_SECRET`, and optionally `KITE_ACCESS_TOKEN` in Streamlit Cloud Secrets or environment variables. Never commit credentials.

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Limitations and safety
The app is read-only. It does not place, modify or cancel broker orders. Kite quote polling is not an exchange tick-by-tick WebSocket feed. Historical-data availability depends on Kite entitlements, instrument coverage, API limits and requested date range. No result is guaranteed to be profitable.
