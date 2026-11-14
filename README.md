# AI ARVI ALGO — F&O and Equity Stock Scanner

Read-only Streamlit market scanner with separate F&O-underlying and NSE cash-equity stock selection.

## Stock selection
- F&O Stock Selection derives underlyings from unexpired NFO stock futures and maps them to NSE cash instruments.
- Equity Stock Selection scans NSE cash equities separately.
- Both use Kite quotes for live turnover ranking where available; when quotes are unavailable, the scanner ranks a bounded candidate set by the latest completed daily candle's close × volume. The table identifies whether its ranking is based on live quote or last-session history.
- Signals use six EMAs (30/35/40/45/50/60), VWAP, RSI(14), relative volume and six-session momentum.
- BUY requires bullish EMA alignment, close above VWAP, RSI >= 52 and positive momentum. SELL requires bearish EMA alignment, close below VWAP, RSI <= 48 and negative momentum. Otherwise WAIT.

## Indicator-derived price levels (no fixed 10%/5%)
- ATR(14) is calculated from daily true range.
- Support and resistance use the prior 20 completed daily candles, excluding the current candle.
- For BUY, target levels use the nearest valid 20-session resistance and 2×/3× ATR extensions; stop uses the more conservative of recent support and a 1.5× ATR buffer.
- For SELL, target levels use the nearest valid 20-session support and 2×/3× ATR extensions; stop uses recent resistance and a 1.5× ATR buffer.
- The table displays Entry, Target 1, Target 2, Stop Loss, expected P/L per share, expected P/L %, risk/reward, ATR, support/resistance, and candle date.
- These are technical estimates from the last available daily candle, not guaranteed outcomes. WAIT rows are not entry recommendations. Use a current quote to refresh entry before acting.

## Setup
Configure `KITE_API_KEY`, `KITE_API_SECRET`, and optionally `KITE_ACCESS_TOKEN` in Streamlit Cloud Secrets or environment variables. Never commit credentials.

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Limitations and safety
The app is read-only and does not place, modify or cancel broker orders. Historical-data availability depends on Kite entitlements, instrument coverage, API limits and requested date range. Intraday price may differ from the last completed daily candle. No result is guaranteed to be profitable.
