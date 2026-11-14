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


## Independent NSE data source
The app includes a separate authorized NSE data-feed adapter in `nse_data_provider.py`. It does not scrape the NSE website. Configure the endpoint and bearer token supplied under your NSE Data subscription or authorized data vendor:

```toml
NSE_DATA_API_URL = "https://YOUR_AUTHORIZED_VENDOR_ENDPOINT/quotes"
NSE_DATA_API_TOKEN = "YOUR_TOKEN"
```

The configured endpoint must accept a GET query parameter `symbols` (comma-separated) and return JSON as either a list or `{"data": [...]}`. Each row must contain `symbol` and `last_price`; optional fields are `open`, `high`, `low`, `previous_close`, `volume`, `oi`, `bid`, `ask`, `timestamp`, and `exchange`. This is a connector contract, not an NSE public API URL. Obtain the real endpoint and data-use rights from NSE Data or your authorized vendor. The UI keeps this source separate from Kite until a licensed feed is configured.

NSE prohibits systematic/automated scraping of its public website. Official real-time, snapshot and historical products are subscription products. See [NSE Data & Analytics](https://www.nse.in/static/nse-data-and-analytics/data-information-vending) and [NSE Terms of Use](https://www.nseindia.com/static/nse-terms-of-use).
