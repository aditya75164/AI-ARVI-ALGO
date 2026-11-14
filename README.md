# AI ARVI ALGO — F&O and Equity Stock Scanner

Streamlit trading intelligence application with separate F&O-underlying and NSE cash-equity stock selection, plus a broker-synchronised Bot Control Center.

## Bot Control Center and broker records
- The first dashboard tab synchronises actual Kite orders and tradebook and displays broker-reported day P&L, net-position P&L, open positions, orders and fills.
- A SQLite ledger stores broker order snapshots, tradebook rows, bot events and equity snapshots. Set `ARVI_DB_PATH` to a persistent disk path in production; Streamlit Cloud's ephemeral filesystem is not suitable for durable performance history.
- This release does **not** yet run unattended automated entry/exit strategies and does not place orders. The bot control centre is currently a broker reporting and ledger foundation, not an active trading bot.

## Daily market briefing
- A dedicated first tab fetches NIFTY 50 and BANK NIFTY daily index candles from Kite.
- It shows conditional bullish/bearish trigger levels, two targets and invalidation levels, plus prior 20-session support/resistance and ATR(14).
- Scenarios use the last completed daily candle (the current in-progress daily candle is excluded during market hours).
- Market headlines are retrieved from Google News RSS with publisher, publication time and article links. The news cache refreshes every 15 minutes; use Refresh news for an immediate refresh.
- This is a technical scenario report, not a guaranteed prediction. News headlines are contextual and are not automatically converted into directional signals.

## Stock selection
- F&O Stock Selection derives underlyings from unexpired NFO stock futures and maps them to NSE cash instruments.
- Equity Stock Selection scans NSE cash equities separately.
- Both use Kite quotes for live turnover ranking where available; when quotes are unavailable, the scanner ranks a bounded candidate set by the latest completed daily candle's close × volume. The table identifies whether its ranking is based on live quote or last-session history.
- Signals use six EMAs (30/35/40/45/50/60), VWAP, RSI(14), relative volume and six-session momentum.
- BUY requires bullish EMA alignment, close above VWAP, RSI >= 52 and positive momentum. SELL requires bearish EMA alignment, close below VWAP, RSI <= 48 and negative momentum. Otherwise WAIT.

## F&O stock option premium line
- Below the F&O underlying stock table, the app adds one trend-aligned option contract per selected stock: BUY signal maps to CE and SELL signal maps to PE.
- It checks the nearest expiry and near-ATM strikes, then requires a recent quote, positive premium/volume/OI, two-sided bid/ask depth and a spread no wider than 5%.
- It estimates implied volatility from the premium using Black-Scholes and displays estimated theta per calendar day. Selection prefers the least-negative theta among buyer-dominant contracts.
- Buyer pressure is the displayed five-level bid quantity divided by ask quantity; it is a depth imbalance proxy, not proof of actual buyer-initiated trades. Theta is a model estimate, not an exchange-provided Greek. WAIT stocks do not receive a directional option pick.

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
The app does not place, modify or cancel broker orders. Live automated execution, broker-side protective stop placement, target monitoring/reconciliation, unattended worker hosting and persistent production database deployment remain to be implemented and tested before it can be called a complete trading bot. Historical-data availability depends on Kite entitlements, instrument coverage, API limits and requested date range. Intraday price may differ from the last completed daily candle. No result is guaranteed to be profitable.
