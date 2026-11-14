# AI ARVI ALGO — Market Monitor

Read-only Streamlit dashboard for market movement, volume, trend indicators and NSE/BSE F&O contract monitoring. **All real-money trading controls and order execution UI have been removed.**

## Features
- Kite login and profile verification.
- NIFTY/BANKNIFTY historical candles with six EMA, ATR, RSI, VWAP, bullish/bearish trend, BUY CE / BUY PE / WAIT signal and relative volume.
- NSE/BSE cash-equity quote monitor with sampled price movement, cumulative volume change, best bid/ask and rolling charts.
- NFO/BFO current unexpired CE/PE instrument discovery for eligible index and stock derivatives, with live quote, volume and OI monitor.
- Configurable 1s/2s/5s polling via Streamlit fragments.
- Single highest-ranked F&O stock shortlist using bullish EMA/VWAP trend, 5-candle momentum, relative volume, RSI and Google News global headline context. Scanner checks up to 25 liquid F&O underlyings after quote-based liquidity ranking.

## Setup
Configure `KITE_API_KEY`, `KITE_API_SECRET`, and optionally `KITE_ACCESS_TOKEN` in Streamlit Cloud Secrets or environment variables. Never commit credentials. Login tokens have a daily lifecycle.

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Data limitations
The dashboard uses Kite quote polling. A one-second polling interval is a requested refresh cadence, not a guarantee of one exchange tick per second. Streamlit Cloud sleeping, API rate limits, market-data entitlements, network latency and quote availability can delay updates. True tick-by-tick streaming requires a persistent KiteTicker/WebSocket connection on an always-on server; this build does not claim that WebSocket streaming is active.

Index historical candles may have zero volume from the provider; relative volume is meaningful only when candle volume is populated. Stock F&O availability depends on the current exchange instrument master and your Kite market-data entitlements.

## Safety
This app is market-data and indicator only. It does not submit, modify, or cancel orders. BUY/SELL labels are rule-based technical signals and are not guaranteed predictions or investment advice.


## Historical data sources
- **NSE official bhavcopy:** In the NSE Historical Data tab, upload the official CM-UDiFF bhavcopy CSV/ZIP downloaded from [NSE All Reports](https://www.nseindia.com/all-reports). The parser normalizes equity OHLC, volume, series and available UDiFF fields including expiry, strike, option type and OI. This is exchange-published end-of-day data, not live depth or intraday candles.
- **Kite historical candles:** With a verified Kite account and historical-data entitlement, enter NSE symbols and a date range in the same tab to fetch daily OHLCV candles using Kite's historical API. The app labels this source as Kite, not direct NSE.
- NSE's official EOD/historical data products are also available by subscription through NSE Data & Analytics. This app does not scrape NSE pages or invent a public API endpoint. See [NSE EOD/Historical Data](https://www.nse.in/static/market-data/eod-historical-data-subscription) and [NSE All Reports](https://www.nseindia.com/all-reports).

## Historical data limitations
Bhavcopy uploads contain only the dates and segments included in the file. The CM equity bhavcopy does not provide full intraday candles. Use an NSE F&O bhavcopy for option contract EOD fields. Kite historical candles require a verified account and the relevant historical-data entitlement.
