import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo
from engine import add_dtc_style_indicators, build_signal
from kite_adapter import (
    kite_client, login_url, generate_session, fetch_index_candles,
    select_option_contract, get_secret
)

st.set_page_config(page_title="AI ARVI ALGO", page_icon="🧭", layout="wide")
IST = ZoneInfo("Asia/Kolkata")
for key, default in {
    "last_scan": None,
    "selected_contract": None,
    "trading_mode": "Semi-Automatic",
    "live_trading_armed": False,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

st.markdown("""<style>
.stApp{background:#f4f7fb;color:#14243a}.block-container{max-width:1440px;padding-top:1.2rem}
[data-testid="stMetric"]{background:white;border:1px solid #dbe4ef;padding:12px;border-radius:12px}
div.stButton>button{border-radius:9px;font-weight:600}
</style>""", unsafe_allow_html=True)
st.title("🧭 AI ARVI ALGO")
st.caption("Zerodha Kite · NIFTY / BANKNIFTY · Options scanner")

with st.sidebar:
    st.header("Risk controls")
    capital = st.number_input("Trading capital (₹)", min_value=1000, value=50000, step=5000)
    risk_pct = st.number_input("Risk budget per trade (%)", min_value=0.25, max_value=3.0, value=1.0, step=0.25)
    target_pct = st.number_input("Target (%)", min_value=0.5, max_value=20.0, value=3.0, step=0.5)
    stop_pct = st.number_input("Stop-loss (%)", min_value=0.5, max_value=20.0, value=2.0, step=0.5)
    max_trades = st.number_input("Maximum trades/day", min_value=1, max_value=10, value=3)
    daily_loss = st.number_input("Daily loss limit (₹)", min_value=500, value=2000, step=500)
    st.caption("These are displayed risk settings. Live order enforcement is not connected yet.")
    st.divider()
    st.subheader("Kite connection")
    api_key_set = bool(get_secret("KITE_API_KEY"))
    api_secret_set = bool(get_secret("KITE_API_SECRET"))
    st.write("API key:", "Configured" if api_key_set else "Missing")
    st.write("API secret:", "Configured" if api_secret_set else "Missing")
    if api_key_set and api_secret_set:
        try:
            st.link_button("1 · Login to Zerodha Kite", login_url())
        except Exception as exc:
            st.error(f"Login URL error: {exc}")
        request_token = st.text_input("2 · Paste request_token from callback URL", type="password")
        if st.button("Complete Kite login", use_container_width=True):
            try:
                st.session_state["kite_access_token"] = generate_session(request_token)
                st.success("Kite session token received. Verify connection.")
                st.rerun()
            except Exception as exc:
                st.error(f"Kite login failed: {exc}")
    else:
        st.warning("Add KITE_API_KEY and KITE_API_SECRET to Streamlit deployment Secrets.")
    if st.button("Verify Kite connection", use_container_width=True):
        try:
            client = kite_client()
            if client is None:
                st.error("No session. Complete Kite login or configure KITE_ACCESS_TOKEN.")
            else:
                profile = client.profile()
                st.session_state["kite_profile"] = profile
                st.success(f"Connected: {profile.get('user_name') or profile.get('user_id')}")
        except Exception as exc:
            st.session_state.pop("kite_profile", None)
            st.error(f"Connection verification failed: {exc}")

kite = kite_client()
connected = bool(st.session_state.get("kite_profile")) and kite is not None

st.subheader("Trading mode")
semi_col, auto_col = st.columns(2)
with semi_col:
    st.markdown("### 🧑‍💻 Semi-Automatic")
    st.caption("Signal and contract are shown to you. You decide whether to place each trade in your broker.")
    if st.button("Choose Semi-Automatic", use_container_width=True,
                 type="primary" if st.session_state.trading_mode == "Semi-Automatic" else "secondary"):
        st.session_state.trading_mode = "Semi-Automatic"
        st.rerun()
with auto_col:
    st.markdown("### ⚡ Fully Automatic")
    st.caption("Intended for rule-based order execution after live safeguards and broker protection are implemented.")
    if st.button("Choose Fully Automatic", use_container_width=True,
                 type="primary" if st.session_state.trading_mode == "Fully Automatic" else "secondary"):
        st.session_state.trading_mode = "Fully Automatic"
        st.rerun()

mode_col, conn_col, risk_col = st.columns(3)
mode_col.metric("Selected mode", st.session_state.trading_mode)
conn_col.metric("Kite API", "Verified" if connected else "Not verified")
risk_col.metric("Risk budget / trade", f"₹{capital*risk_pct/100:,.0f}")

st.subheader("Real-money trading master switch")
st.toggle(
    "I authorize live trading mode",
    key="live_trading_armed",
    help="This is an authorization preference only. It does not place orders in this build."
)
if st.session_state.live_trading_armed:
    st.error("LIVE MODE SELECTED — but live order placement is not implemented or connected. No real order can be sent from this version. Do not treat this switch as active broker execution.")
else:
    st.info("Live trading is OFF. Scanner and contract lookup are read-only.")
st.caption("Switching modes or turning this control ON/OFF never submits, modifies, or cancels a broker order.")

scanner_tab, options_tab, guide_tab = st.tabs(
    ["Market scanner", "Option contract lookup", "Strategy & execution status"]
)

with scanner_tab:
    left, right = st.columns(2)
    underlying = left.selectbox("Underlying index", ["NIFTY", "BANKNIFTY"], key="scan_underlying")
    timeframe = right.selectbox("Signal timeframe", ["3minute", "5minute", "15minute"], key="scan_timeframe")
    if st.button("Scan index", type="primary"):
        try:
            if kite is None:
                st.error("Connect and verify Kite first.")
            else:
                candles = fetch_index_candles(kite, underlying, timeframe)
                if candles.empty:
                    st.error("Kite returned no candles. Check market hours and API access.")
                else:
                    analysed = add_dtc_style_indicators(candles)
                    result = build_signal(analysed)
                    st.session_state.last_scan = {
                        "market": underlying, "timeframe": timeframe,
                        "result": result, "data": analysed
                    }
        except Exception as exc:
            st.error(f"Scan failed: {exc}")
    scan = st.session_state.last_scan
    if scan:
        result = scan["result"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Market bias", result["bias"])
        c2.metric("Signal", result["signal"])
        c3.metric("Score", f'{result["score"]}/100')
        c4.metric("Last candle", str(scan["data"].index[-1]))
        st.write("**Reason:**", result["reason"])
        st.dataframe(scan["data"].tail(30), use_container_width=True)
        if result["signal"] in ("BUY CE", "BUY PE"):
            st.success(f"Direction signal: {result['signal']}. Inspect the matching option contract in the next tab.")
            st.session_state["suggested_side"] = "CE" if result["signal"] == "BUY CE" else "PE"

with options_tab:
    st.subheader("Live NFO option contract lookup — read only")
    c1, c2, c3 = st.columns(3)
    opt_underlying = c1.selectbox("Underlying", ["NIFTY", "BANKNIFTY"], key="opt_underlying")
    suggested = st.session_state.get("suggested_side", "CE")
    opt_side = c2.selectbox("Option type", ["CE", "PE"], index=0 if suggested == "CE" else 1)
    moneyness = c3.selectbox("Strike selection", ["ATM", "1 ITM", "2 ITM", "1 OTM", "2 OTM"])
    if st.button("Fetch live option contract", type="primary"):
        try:
            if kite is None:
                st.error("Connect and verify Kite first.")
            else:
                st.session_state.selected_contract = select_option_contract(
                    kite, opt_underlying, opt_side, moneyness
                )
        except Exception as exc:
            st.session_state.selected_contract = None
            st.error(f"Option selection failed: {exc}")
    contract = st.session_state.selected_contract
    if contract:
        a, b, c, d = st.columns(4)
        a.metric("Spot", f'{contract["spot_ltp"]:,.2f}')
        b.metric("Option premium", f'₹{contract["option_ltp"]:,.2f}')
        c.metric("Strike / expiry", f'{contract["strike"]:g} · {contract["expiry"]}')
        d.metric("Lot size", contract["lot_size"])
        st.write(f'**Contract:** {contract["tradingsymbol"]} · {contract["side"]}')
        e, f, g = st.columns(3)
        e.metric("Bid", f'₹{contract["best_bid"]:,.2f}' if contract["best_bid"] else "Unavailable")
        f.metric("Ask", f'₹{contract["best_ask"]:,.2f}' if contract["best_ask"] else "Unavailable")
        g.metric("Spread", f'{contract["spread_pct"]:.2f}%' if contract["spread_pct"] is not None else "Unavailable")
        if contract["spread_pct"] is not None and contract["spread_pct"] > 1.0:
            st.warning("Bid/ask spread exceeds 1%. Liquidity/cost risk is elevated.")
        if contract["volume"] == 0 or contract["oi"] == 0:
            st.warning("Volume or open interest is zero. Liquidity is not confirmed.")
        st.metric("Risk budget", f"₹{capital*risk_pct/100:,.0f}")
        st.write(f"Indicative stop distance: {stop_pct:.2f}% · Indicative target: {target_pct:.2f}%")
        st.info("Contract lookup only. No entry button, paper trade, or broker order placement is available.")
        st.caption("Contract, expiry, lot size and quote are read from Kite. Nearest expiry and selected moneyness are used.")

with guide_tab:
    st.markdown("""**Signal framework (research approximation, not proprietary DTC code):**
- Six EMA alignment: 30, 35, 40, 45, 50 and 60.
- ATR activity filter, VWAP and RSI confirmation.
- CE: bullish EMA stack, close above VWAP and RSI strength.
- PE: bearish EMA stack, close below VWAP and RSI weakness.
- Incomplete confirmation returns WAIT.

**Execution status**
- Paper entry and paper position monitor have been removed from the dashboard.
- Semi-Automatic and Fully Automatic are selectable preferences.
- Live trading master switch is a UI authorization preference only; it is not connected to Kite order placement.
- Broker-side SL/Target, order lifecycle reconciliation, persistent state, kill switch and audit logging are not implemented. Do not enable real trading based on this UI switch.

This tool does not guarantee profits. Validate all signals independently and understand options can lose the full premium.""")
st.caption(f"Local time: {datetime.now(IST).strftime('%d-%b-%Y %H:%M:%S')} IST · Order execution not connected")
