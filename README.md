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
