import os
import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from engine import add_dtc_style_indicators, build_signal
from kite_adapter import kite_client, login_url, generate_session, fetch_index_candles

st.set_page_config(page_title="AI ARVI ALGO", page_icon="🧭", layout="wide")
IST = ZoneInfo("Asia/Kolkata")
st.markdown("""<style>
.stApp{background:#f4f7fb;color:#14243a}.block-container{max-width:1440px;padding-top:1.4rem}
[data-testid="stMetric"]{background:white;border:1px solid #dbe4ef;padding:14px;border-radius:12px}
</style>""", unsafe_allow_html=True)
st.title("🧭 AI ARVI ALGO")
st.caption("Standalone Zerodha options trading terminal · DTC-inspired trend framework · Paper trading first")

with st.sidebar:
    st.header("Risk & execution")
    target = st.number_input("Target (%)", min_value=0.5, max_value=20.0, value=3.0, step=0.5)
    stop = st.number_input("Stop-loss (%)", min_value=0.5, max_value=20.0, value=2.0, step=0.5)
    trail_on = st.toggle("Trailing stop-loss", value=True)
    trail_pct = st.number_input("Trailing SL (%)", min_value=0.25, max_value=10.0, value=1.0, step=0.25, disabled=not trail_on)
    capital = st.number_input("Trading capital (₹)", min_value=1000, value=50000, step=5000)
    risk_pct = st.number_input("Risk per trade (%)", min_value=0.25, max_value=3.0, value=1.0, step=0.25)
    max_trades = st.number_input("Maximum trades/day", min_value=1, max_value=10, value=3)
    daily_loss = st.number_input("Daily loss limit (₹)", min_value=500, value=2000, step=500)
    st.divider()
    st.subheader("Broker connection")
    api_key_set = bool(os.getenv("KITE_API_KEY"))
    api_secret_set = bool(os.getenv("KITE_API_SECRET"))
    st.write("API key:", "Configured" if api_key_set else "Missing")
    st.write("API secret:", "Configured" if api_secret_set else "Missing")
    if api_key_set and api_secret_set:
        url = login_url()
        st.link_button("Connect Zerodha Kite", url)
        req_token = st.text_input("Request token after Kite login", type="password")
        if st.button("Complete Kite login") and req_token:
            try:
                token = generate_session(req_token)
                st.session_state["kite_access_token"] = token
                st.session_state["kite_connected"] = True
                st.success("Kite login successful. Session is active in this browser session; the access token is hidden.")
            except Exception as exc:
                st.error(f"Login failed: {exc}")
    else:
        st.info("Set KITE_API_KEY and KITE_API_SECRET in your deployment secrets. Never paste them into chat.")

st.warning("PAPER MODE ONLY. This standalone build does not place live orders. Live execution is intentionally not implemented/enabled until broker setup, testing and explicit risk approval.")
col1,col2,col3,col4=st.columns(4)
col1.metric("Mode","PAPER")
col2.metric("Target",f"{target:.2f}%")
col3.metric("Stop-loss",f"{stop:.2f}%")
col4.metric("Risk / trade",f"₹{capital*risk_pct/100:,.0f}")

tab1,tab2,tab3=st.tabs(["Market scanner","Paper trade plan","Strategy guide"])
with tab1:
    market=st.selectbox("Underlying",["NIFTY","BANKNIFTY"])
    timeframe=st.selectbox("Signal timeframe",["3minute","5minute","15minute"])
    if st.button("Scan market",type="primary"):
        try:
            kite=kite_client()
            if kite is None:
                st.error("Kite session unavailable. Configure KITE_API_KEY and KITE_ACCESS_TOKEN.")
            else:
                candles=fetch_index_candles(kite,market,timeframe)
                if candles.empty:
                    st.error("No candle data returned. Check session, instrument token and market hours.")
                else:
                    analysed=add_dtc_style_indicators(candles)
                    result=build_signal(analysed)
                    st.session_state["last_scan"]={"market":market,"timeframe":timeframe,"result":result,"data":analysed}
        except Exception as exc:
            st.error(f"Scan failed: {exc}")
    scan=st.session_state.get("last_scan")
    if scan:
        res=scan["result"]
        a,b,c=st.columns(3)
        a.metric("Market bias",res["bias"])
        b.metric("Signal",res["signal"])
        c.metric("Confirmation score",f'{res["score"]}/100')
        st.write("**Reason:**",res["reason"])
        st.dataframe(scan["data"].tail(20),use_container_width=True)
        if res["signal"] in ("BUY CE","BUY PE"):
            st.info("Underlying direction confirmed. Next step: choose a liquid ATM/1-ITM option using live option-chain quotes, spread and OI filters. Contract selection is not yet connected in this foundation build.")
with tab2:
    st.subheader("Paper trade calculator")
    side=st.radio("Option side",["CE","PE"],horizontal=True)
    premium=st.number_input("Option premium entry (₹)",min_value=0.05,value=100.0,step=1.0)
    qty=st.number_input("Quantity",min_value=1,value=25,step=25)
    entry_value=premium*qty
    target_price=premium*(1+target/100)
    stop_price=premium*(1-stop/100)
    st.write(f"**Estimated target premium:** ₹{target_price:.2f}")
    st.write(f"**Stop-loss premium:** ₹{stop_price:.2f}")
    st.write(f"**Gross target P&L:** ₹{(target_price-premium)*qty:,.2f}")
    st.write(f"**Gross stop P&L:** ₹{(stop_price-premium)*qty:,.2f}")
    st.caption("Illustrative calculation only; excludes brokerage, taxes, slippage and partial fills.")
with tab3:
    st.markdown("""**DTC-inspired public-behavior approximation (not the invite-only DTC source code):**
- Six EMA alignment: 30, 35, 40, 45, 50 and 60.
- Higher-timeframe trend confirmation is planned; this initial scanner checks the selected candle timeframe only.
- ATR volatility filter avoids very quiet conditions.
- VWAP and RSI provide additional intraday confirmation.
- Signal is emitted only on a completed candle; no forced trades when filters disagree.

**CE:** bullish EMA stack + close above VWAP + RSI strength + ATR activity.
**PE:** bearish EMA stack + close below VWAP + RSI weakness + ATR activity.

This is a research framework, not a profit guarantee. Backtest and paper trade before considering live capital.""")
st.caption(f"Local time: {datetime.now(IST).strftime('%d-%b-%Y %H:%M:%S')} IST")
