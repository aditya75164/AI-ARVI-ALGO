import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from engine import add_dtc_style_indicators, build_signal
from stock_selector import scan_fno_stock_candidates
from kite_adapter import (
    kite_client, login_url, generate_session, fetch_index_candles,
    fetch_derivative_contracts, get_quote_snapshot, get_secret, validate_option_liquidity, filter_live_option_contracts, build_stock_option_watchlist
)

st.set_page_config(page_title="AI ARVI ALGO", page_icon="🧭", layout="wide")
IST=ZoneInfo("Asia/Kolkata")
for key, default in {
    "last_scan":None, "watch_history":{}, "selected_symbol":None,
    "selected_derivative":None, "kite_profile":None
}.items():
    if key not in st.session_state: st.session_state[key]=default

st.markdown("""<style>
.stApp{background:#f4f7fb;color:#14243a}.block-container{max-width:1500px;padding-top:1rem}
[data-testid="stMetric"]{background:white;border:1px solid #dbe4ef;padding:12px;border-radius:12px}
div.stButton>button{border-radius:9px;font-weight:600}
</style>""",unsafe_allow_html=True)
st.title("🧭 AI ARVI ALGO")
st.caption("Market intelligence · Live price & volume monitor · BUY/SELL indicators · NSE/BSE F&O watch")

with st.sidebar:
    st.subheader("Kite market-data connection")
    key_ok=bool(get_secret("KITE_API_KEY")); secret_ok=bool(get_secret("KITE_API_SECRET"))
    st.write("API key:", "Configured" if key_ok else "Missing")
    st.write("API secret:", "Configured" if secret_ok else "Missing")
    if key_ok and secret_ok:
        st.link_button("1 · Login to Zerodha Kite",login_url())
        callback_token = st.query_params.get("request_token", "")
        if callback_token:
            st.success("Kite callback detected. Complete login promptly; request tokens are single-use and short-lived.")
            if st.button("2 · Complete login from callback URL", use_container_width=True):
                try:
                    st.session_state.kite_access_token = generate_session(callback_token)
                    st.query_params.clear()
                    st.success("Kite access token received. Now verify connection.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Login failed: {exc}. Start a fresh Kite login and use the newest callback URL.")
        else:
            st.info("After Kite login, you will return here. The app will read the request token from the callback URL.")
            token_input = st.text_input("Fallback: paste request_token", type="password")
            if st.button("Complete login with pasted token", use_container_width=True):
                try:
                    if not token_input.strip():
                        st.error("Request token is empty.")
                    else:
                        st.session_state.kite_access_token = generate_session(token_input.strip())
                        st.success("Kite access token received. Verify connection.")
                        st.rerun()
                except Exception as exc:
                    st.error(f"Login failed: {exc}. Start a fresh Kite login; request tokens cannot be reused.")
    if st.button("Verify Kite connection",use_container_width=True):
        try:
            client=kite_client()
            if client is None: st.error("Login first or configure KITE_ACCESS_TOKEN.")
            else:
                st.session_state.kite_profile=client.profile()
                st.success(f"Connected: {st.session_state.kite_profile.get('user_name') or st.session_state.kite_profile.get('user_id')}")
        except Exception as exc:
            st.session_state.kite_profile=None
            st.error(f"Connection failed: {exc}")
    st.divider()
    refresh=st.selectbox("Refresh interval",["1 second","2 seconds","5 seconds"],index=1)
    refresh_seconds={"1 second":1,"2 seconds":2,"5 seconds":5}[refresh]
    st.caption("Live polling uses Kite quote API. API rate limits and your market-data entitlement apply.")

kite=kite_client()
connected=bool(st.session_state.kite_profile) and kite is not None
c1,c2,c3=st.columns(3)
c1.metric("Kite market data","Connected" if connected else "Not verified")
c2.metric("Dashboard mode","Market monitor only")
c3.metric("Order execution","Removed")
st.info("This dashboard is read-only. It does not place, modify or cancel orders.")

tabs=st.tabs(["Selected stock pick","Live market monitor","Index signals","Stock F&O options watch","Indicator guide"])
with tabs[0]:
    st.subheader("Top selected stock — trend + volume + global news")
    st.caption("Shows only the highest-ranked eligible F&O stock. A 10% objective is a target reference, not a promised return.")
    if st.button("Find strongest stock now",type="primary"):
        try:
            if not connected:
                st.error("Connect and verify Kite first.")
            else:
                with st.spinner("Scanning liquid F&O stocks, volume, momentum and global headlines..."):
                    st.session_state.stock_picks=scan_fno_stock_candidates(kite,max_stocks=25)
        except Exception as exc:
            st.error(f"Stock selection failed: {exc}")
    picks=st.session_state.get("stock_picks",[])
    if picks:
        best=picks[0]
        st.success(f"Selected stock: {best['name']} ({best['symbol']})")
        a,b,c,d=st.columns(4)
        a.metric("Selection score",f"{best['score']}/100")
        b.metric("Last price",f"₹{best['last_price']:,.2f}")
        c.metric("Relative volume",f"{best['relative_volume']}x")
        d.metric("5-candle momentum",f"{best['momentum_pct']:+.2f}%")
        st.write(f"**Trend:** Bullish · **RSI:** {best['rsi']} · **Day volume:** {best['day_volume']:,}")
        st.write(f"**News context:** {best['headline']}")
        st.caption("Filters: bullish six-EMA/VWAP alignment, relative volume ≥1.5x, positive short-term momentum and RSI 55–80. Global headlines are keyword-scored when they mention the stock; missing stock-specific news is neutral. No 10% return is guaranteed.")
    elif "stock_picks" in st.session_state:
        st.warning("No stock currently passes all filters. No pick is better than a weak pick.")
    else:
        st.info("Click Find strongest stock now after verifying Kite connection.")
with tabs[1]:
    st.subheader("Second-by-second price & volume movement")
    x,y=st.columns([1,2])
    exchange=x.selectbox("Cash market",["NSE","BSE"])
    symbol=y.text_input("Equity trading symbol",value="RELIANCE",help="Enter exact NSE/BSE trading symbol, e.g. RELIANCE")
    if connected:
        @st.fragment(run_every=refresh_seconds)
        def live_ticker():
            try:
                q=get_quote_snapshot(kite,exchange,symbol.strip().upper())
                if q["last_price"]<=0: st.warning("No valid traded price yet."); return
                history=st.session_state.watch_history.setdefault(q["key"],[])
                now=datetime.now(IST)
                if not history or history[-1]["time"]!=now.strftime("%H:%M:%S"):
                    history.append({"time":now.strftime("%H:%M:%S"),"price":q["last_price"],"volume":q["volume"]})
                    st.session_state.watch_history[q["key"]]=history[-180:]
                delta=(q["last_price"]/history[-2]["price"]-1)*100 if len(history)>1 and history[-2]["price"] else 0
                vol_delta=q["volume"]-history[-2]["volume"] if len(history)>1 else 0
                a,b,c,d=st.columns(4)
                a.metric("Last price",f"₹{q['last_price']:,.2f}",f"{delta:+.2f}% since previous sample")
                b.metric("Traded volume",f"{q['volume']:,}",f"{vol_delta:+,} since previous sample")
                c.metric("Best bid",f"₹{q['bid']:,.2f}" if q["bid"] else "—")
                d.metric("Best ask",f"₹{q['ask']:,.2f}" if q["ask"] else "—")
                hist=pd.DataFrame(history)
                if len(hist)>1:
                    st.line_chart(hist.set_index("time")[["price"]],height=280)
                    st.bar_chart(hist.set_index("time")[["volume"]],height=180)
                st.caption(f"Quote timestamp: {q['timestamp'] or 'not supplied'} · Local sample: {now.strftime('%H:%M:%S IST')}. Polling is not an exchange tick feed.")
            except Exception as exc: st.error(f"Quote fetch failed: {exc}")
        live_ticker()
    else:
        st.warning("Connect and verify Kite to view live market quotes.")

with tabs[2]:
    st.subheader("NIFTY / BANKNIFTY trend & BUY/SELL indicator")
    u,v=st.columns(2)
    index=u.selectbox("Index",["NIFTY","BANKNIFTY"])
    interval=v.selectbox("Candle interval",["3minute","5minute","15minute"])
    if st.button("Calculate index indicators",type="primary"):
        try:
            if not connected: st.error("Connect Kite first.")
            else:
                candles=fetch_index_candles(kite,index,interval)
                analysed=add_dtc_style_indicators(candles)
                st.session_state.last_scan={"data":analysed,"result":build_signal(analysed),"index":index}
        except Exception as exc: st.error(f"Indicator calculation failed: {exc}")
    scan=st.session_state.last_scan
    if scan:
        row=scan["data"].iloc[-1]; sig=scan["result"]
        a,b,c,d=st.columns(4)
        a.metric("Trend",row.get("TREND_LABEL","—"))
        b.metric("Signal",sig["signal"])
        c.metric("RSI 14",f"{row['RSI_14']:.1f}" if pd.notna(row["RSI_14"]) else "—")
        d.metric("Relative volume",f"{row['RELATIVE_VOLUME']:.2f}x" if pd.notna(row["RELATIVE_VOLUME"]) else "—")
        st.write("**Signal reason:**",sig["reason"])
        st.line_chart(scan["data"].tail(120)[["Close","EMA_30","EMA_60","VWAP"]],height=360)
        st.bar_chart(scan["data"].tail(120)[["Volume"]],height=180)
        st.dataframe(scan["data"].tail(30),use_container_width=True)

with tabs[3]:
    st.subheader("NSE/BSE stock F&O — one premium per stock")
    st.caption("One near-ATM contract per underlying, chosen by highest OI among nearby strikes in the nearest expiry.")
    ex=st.selectbox("Derivatives exchange",["NFO","BFO"])
    side=st.selectbox("Option side",["CE","PE"])
    underlying=st.text_input("Underlying filter (optional)",placeholder="RELIANCE, SBIN, INFY")
    x,y=st.columns(2)
    target_pct=x.number_input("Target %",min_value=1.0,max_value=50.0,value=10.0,step=1.0)
    stop_pct=y.number_input("Stop loss %",min_value=1.0,max_value=30.0,value=5.0,step=0.5)
    if st.button("Scan one option per stock",type="primary"):
        try:
            if not connected:
                st.error("Connect and verify Kite first.")
            else:
                with st.spinner("Checking nearest expiry, ATM strikes, premium, volume and OI..."):
                    watch, stats=build_stock_option_watchlist(
                        kite,exchange=ex,option_side=side,
                        underlying_filter=underlying.strip() or None,
                        target_pct=target_pct,stop_pct=stop_pct
                    )
                st.session_state.option_watchlist=watch
                st.session_state.option_watch_stats=stats
        except Exception as exc:
            st.error(f"F&O scan failed: {exc}")
    watch=st.session_state.get("option_watchlist")
    stats=st.session_state.get("option_watch_stats")
    if stats:
        st.caption(f"Unique F&O stocks: {stats['underlyings']} · Near-ATM contracts checked: {stats['candidates']} · Stocks with valid premium/OI: {stats['selected']}")
        if stats["reason"]=="Last-session quote reference":
            st.info("LAST SESSION REFERENCE · Premium, volume and OI are from the latest dated Kite quote. Signals are indicative only; no live bid/ask or executable price is implied.")
    if watch is not None and not watch.empty:
        st.dataframe(watch,use_container_width=True,hide_index=True)
        buys=int((watch["Signal"]=="BUY").sum())
        sells=int((watch["Signal"]=="SELL").sum())
        waits=int((watch["Signal"]=="WAIT").sum())
        p,q,r=st.columns(3)
        p.metric("BUY",buys)
        q.metric("SELL",sells)
        r.metric("WAIT",waits)
        st.download_button("Download selected stock signals (CSV)",watch.to_csv(index=False),"arvi_option_watchlist.csv","text/csv")
    elif stats:
        st.warning("No contracts have usable premium, volume, OI and dated quote data. No false picks are displayed.")
    else:
        st.info("Choose CE/PE and scan. The table will show one selected premium per underlying, with strike, entry, target, stop loss and signal.")
    
with tabs[4]:
    st.markdown("""### Indicator definitions
- **BUY CE:** bullish six-EMA alignment, price above VWAP, RSI strength and ATR activity.
- **BUY PE:** bearish six-EMA alignment, price below VWAP, RSI weakness and ATR activity.
- **WAIT:** confirmations incomplete.
- **Bullish/Bearish trend:** EMA stack aligned and price on the corresponding side of VWAP.
- **Relative volume:** current candle volume divided by its 20-candle average.
- **Volume change:** difference between cumulative exchange-reported volume samples.
- **Price movement:** change between successive quote samples.

Signals are technical indicators, not guaranteed predictions or investment advice. The 1-second/2-second setting controls quote polling, not guaranteed exchange tick frequency. Streamlit Cloud sleep, Kite API limits, market-data entitlements and network latency can delay updates. For true tick-by-tick streaming, use KiteTicker/WebSocket on an always-on server.
""")
st.caption(f"{datetime.now(IST).strftime('%d-%b-%Y %H:%M:%S')} IST · Read-only market monitor · No order execution")
