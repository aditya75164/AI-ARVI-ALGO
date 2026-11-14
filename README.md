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

## Always-on NIFTY / BANK NIFTY worker
A separate background process is provided in `bot_worker.py`; do not run the trading loop inside Streamlit.

### Configure and start in a dedicated worker host
1. Copy `bot_config.example.json` to `bot_config.json` and adjust risk limits after reviewing them.
2. Set worker environment variables: `KITE_API_KEY`, `KITE_ACCESS_TOKEN`, `ARVI_BOT_CONFIG=bot_config.json`, and `ARVI_DB_PATH=/data/arvi_bot.db` on a persistent volume.
3. Build/run with `docker build -f Dockerfile.worker -t arvi-worker .` and `docker run --restart unless-stopped --env-file worker.env -v arvi-data:/data arvi-worker`.
4. Keep `ARVI_LIVE_TRADING` unset initially. The worker then logs trade candidates only and does not send orders.
5. Only after independent paper/sandbox validation, broker order lifecycle tests, persistent storage, monitoring and explicit operator approval should a deployment administrator set `ARVI_LIVE_TRADING=YES`.

### Worker strategy and safeguards
- Scans NIFTY and BANK NIFTY using the existing 5-minute six-EMA/VWAP/RSI/ATR signal engine.
- BUY CE / BUY PE candidate uses nearest-expiry ATM option, recent two-sided quote, volume/OI, spread gate and 5-minute option ATR for stop/target references.
- Risk-based whole-lot sizing, max lots, maximum open positions, daily broker P&L loss gate, trading time window and duplicate-position/order checks.
- When live mode is explicitly enabled, it submits LIMIT entry orders, verifies broker fills, protects filled quantity with a broker-side SL, and monitors target exits in the always-on worker. Partial fills are handled by cancelling remainder and protecting filled quantity.
- Worker must stay running and retain API access for target monitoring. Broker-side SL remains with the exchange/broker, but target exits are worker-managed; outages can delay target exits.
- Initial worker is for NIFTY/BANKNIFTY index options only. Stock F&O and cash-equity auto-bots are not yet wired into the worker.

### Critical deployment notes
- This repository commit does not deploy or start a background service. A separate always-on host, environment secrets, persistent disk/database, logs and alerting must be configured.
- Never put API secrets in GitHub files or chat. Kite access tokens expire and require renewal.
- Live execution is OFF by default. Do not enable live mode until the broker account, lot sizes, margins, order types, SL behavior, partial fills, rejected orders, network recovery and daily risk limits are tested in a controlled environment.


## Stock F&O background scanner
- `stock_fno_worker.py` runs a separate 15-minute stock F&O scan by default.
- It ranks F&O underlyings, maps trend BUY/SELL to CE/PE, checks near-ATM contracts, quote freshness, bid/ask spread, volume, OI, buyer-side depth and estimated theta.
- It writes scan candidates and worker heartbeat to the same SQLite ledger. It is signal-only and does not place, modify or cancel orders.
- Start a second worker container from the same image with command override: `python stock_fno_worker.py`.
- Both the Streamlit dashboard and both workers must mount the same persistent `ARVI_DB_PATH` database file. Separate containers need a shared filesystem volume; a local SQLite file in two separate containers is not shared automatically.
