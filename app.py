import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from engine import add_dtc_style_indicators, build_signal
from kite_adapter import (
    kite_client, login_url, generate_session, fetch_index_candles,
    select_option_contract, get_option_ltp, get_secret
)
from paper_trading import (
    quantity_for_risk, open_paper_trade, mark_paper_trade,
    close_paper_trade, can_open_trade, daily_realized_pnl
)

st.set_page_config(page_title="AI ARVI ALGO", page_icon="🧭", layout="wide")
IST = ZoneInfo("Asia/Kolkata")
if "paper_trades" not in st.session_state:
    st.session_state.paper_trades = []
if "last_scan" not in st.session_state:
    st.session_state.last_scan = None
if "selected_contract" not in st.session_state:
    st.session_state.selected_contract = None

st.markdown("""<style>
.stApp{background:#f4f7fb;color:#14243a}.block-container{max-width:1440px;padding-top:1.2rem}
[data-testid="stMetric"]{background:white;border:1px solid #dbe4ef;padding:12px;border-radius:12px}
div.stButton>button{border-radius:9px;font-weight:600}
</style>""", unsafe_allow_html=True)
st.title("🧭 AI ARVI ALGO")
st.caption("Zerodha Kite · NIFTY / BANKNIFTY · Options scanner · Paper execution & risk monitor")

# User-selectable execution preference. Selection alone never submits an order.
if "trading_mode" not in st.session_state:
    st.session_state.trading_mode = "Semi-Automatic"
if "live_trading_armed" not in st.session_state:
    st.session_state.live_trading_armed = False

st.subheader("Execution preference")
semi_col, auto_col = st.columns(2)
with semi_col:
    st.markdown("### 🧑‍💻 Semi-Automatic")
    st.caption("AI generates the signal; you review and confirm each entry.")
    if st.button("Select Semi-Automatic", use_container_width=True,
                 type="primary" if st.session_state.trading_mode == "Semi-Automatic" else "secondary"):
        st.session_state.trading_mode = "Semi-Automatic"
        st.rerun()
with auto_col:
    st.markdown("### ⚡ Fully Automatic")
    st.caption("Designed for rule-based execution after all live safeguards are available.")
    if st.button("Select Fully Automatic", use_container_width=True,
                 type="primary" if st.session_state.trading_mode == "Fully Automatic" else "secondary"):
        st.session_state.trading_mode = "Fully Automatic"
        st.rerun()

selected_col, safety_col = st.columns(2)
selected_col.info(f"Selected preference: **{st.session_state.trading_mode}**")
safety_col.warning("Live execution is not connected in this build. Both preferences currently run PAPER trades only.")
st.toggle("Live trading master switch", key="live_trading_armed", disabled=True,
          help="Unavailable until live order execution, broker-side protection and reconciliation are implemented and verified.")

with st.sidebar:
    st.header("Risk & execution")
    capital = st.number_input("Trading capital (₹)", min_value=1000, value=50000, step=5000)
    risk_pct = st.number_input("Risk per trade (%)", min_value=0.25, max_value=3.0, value=1.0, step=0.25)
    target = st.number_input("Target (%)", min_value=0.5, max_value=20.0, value=3.0, step=0.5)
    stop = st.number_input("Stop-loss (%)", min_value=0.5, max_value=20.0, value=2.0, step=0.5)
    trail_on = st.toggle("Trailing stop-loss", value=True)
    trail_pct = st.number_input("Trailing SL (%)", min_value=0.25, max_value=10.0, value=1.0, step=0.25, disabled=not trail_on)
    max_trades = st.number_input("Maximum trades/day", min_value=1, max_value=10, value=3)
    daily_loss = st.number_input("Daily loss limit (₹)", min_value=500, value=2000, step=500)
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
                token = generate_session(request_token)
                st.session_state["kite_access_token"] = token
                st.success("Kite session token received. Press Verify connection.")
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
mode_col, conn_col, risk_col, pnl_col = st.columns(4)
mode_col.metric("Execution mode", "PAPER ONLY")
conn_col.metric("Kite API", "Verified" if connected else "Not verified")
risk_col.metric("Risk / trade", f"₹{capital*risk_pct/100:,.0f}")
pnl_col.metric("Today's realized P&L", f"₹{daily_realized_pnl(st.session_state.paper_trades):,.2f}")
st.warning("Live order placement is deliberately disabled. All entries and exits below are simulated paper trades; no broker order is sent.")

scanner_tab, options_tab, positions_tab, guide_tab = st.tabs(
    ["Market scanner", "Option chain & paper entry", "Positions & risk", "Strategy guide"]
)

with scanner_tab:
    left, right = st.columns([1, 1])
    with left:
        underlying = st.selectbox("Underlying index", ["NIFTY", "BANKNIFTY"], key="scan_underlying")
    with right:
        timeframe = st.selectbox("Signal timeframe", ["3minute", "5minute", "15minute"], key="scan_timeframe")
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
            st.success(f"Direction signal: {result['signal']}. Go to Option chain tab to fetch and inspect the matching contract.")
            st.session_state["suggested_side"] = "CE" if result["signal"] == "BUY CE" else "PE"

with options_tab:
    st.subheader("Live NFO option contract selector")
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
                contract = select_option_contract(kite, opt_underlying, opt_side, moneyness)
                st.session_state.selected_contract = contract
        except Exception as exc:
            st.session_state.selected_contract = None
            st.error(f"Option selection failed: {exc}")
    contract = st.session_state.selected_contract
    if contract:
        a,b,c,d = st.columns(4)
        a.metric("Spot", f'{contract["spot_ltp"]:,.2f}')
        b.metric("Option premium", f'₹{contract["option_ltp"]:,.2f}')
        c.metric("Strike / expiry", f'{contract["strike"]:g} · {contract["expiry"]}')
        d.metric("Lot size", contract["lot_size"])
        st.write(f'**Contract:** {contract["tradingsymbol"]} · {contract["side"]}')
        e,f,g = st.columns(3)
        e.metric("Bid", f'₹{contract["best_bid"]:,.2f}' if contract["best_bid"] else "Unavailable")
        f.metric("Ask", f'₹{contract["best_ask"]:,.2f}' if contract["best_ask"] else "Unavailable")
        g.metric("Spread", f'{contract["spread_pct"]:.2f}%' if contract["spread_pct"] is not None else "Unavailable")
        if contract["spread_pct"] is not None and contract["spread_pct"] > 1.0:
            st.warning("Bid/ask spread exceeds 1%. Contract is illiquid or costly; avoid paper entry unless reviewed.")
        if contract["volume"] == 0 or contract["oi"] == 0:
            st.warning("Volume or open interest is zero. Liquidity is not confirmed.")
        qty = quantity_for_risk(capital, risk_pct, contract["option_ltp"], stop, contract["lot_size"])
        st.write(f"**Risk-based quantity:** {qty} units ({qty // contract['lot_size']} lots) · budget ₹{capital*risk_pct/100:,.0f}")
        if qty == 0:
            st.warning("Capital/risk budget is insufficient for one lot at this premium and stop distance.")
        else:
            if st.button("Open PAPER trade", type="primary"):
                allowed, reason = can_open_trade(st.session_state.paper_trades, max_trades, daily_loss)
                if not allowed:
                    st.error(reason)
                else:
                    trade = open_paper_trade(contract, qty, target, stop, trail_on, trail_pct)
                    st.session_state.paper_trades.append(trade)
                    st.success(f'Paper position opened: {contract["tradingsymbol"]} · {qty} units')
                    st.rerun()
        st.caption("Option contracts, expiry, lot size and quotes are read from Kite NFO instruments and quote endpoints. The chosen contract is the nearest expiry and selected moneyness.")

with positions_tab:
    st.subheader("Paper position monitor")
    @st.fragment(run_every="5s")
    def paper_position_monitor():
        positions = [t for t in st.session_state.paper_trades if t["status"] == "OPEN"]
        if positions and kite is not None:
            for trade in positions:
                try:
                    idx = next(i for i,x in enumerate(st.session_state.paper_trades) if x["id"] == trade["id"])
                    latest = get_option_ltp(kite, trade["tradingsymbol"])
                    st.session_state.paper_trades[idx] = mark_paper_trade(trade, latest)
                except Exception as exc:
                    st.warning(f'{trade["tradingsymbol"]}: automatic paper quote check failed: {exc}')
        positions = [t for t in st.session_state.paper_trades if t["status"] == "OPEN"]
        if positions:
            for trade in positions:
                st.markdown(f'**{trade["tradingsymbol"]}** · {trade["quantity"]} units · {trade["status"]}')
                p1,p2,p3,p4 = st.columns(4)
                p1.metric("Entry", f'₹{trade["entry_price"]:.2f}')
                p2.metric("Last marked", f'₹{trade["ltp"]:.2f}')
                p3.metric("Current P&L", f'₹{trade["pnl"]:,.2f}')
                p4.metric("Stop / target", f'₹{trade["stop_price"]:.2f} / ₹{trade["target_price"]:.2f}')
                if st.button(f'Manual paper exit {trade["tradingsymbol"]}', key=f'exit_{trade["id"]}', disabled=(kite is None)):
                    try:
                        idx = next(i for i,x in enumerate(st.session_state.paper_trades) if x["id"] == trade["id"])
                        latest = get_option_ltp(kite, trade["tradingsymbol"])
                        st.session_state.paper_trades[idx] = close_paper_trade(trade, latest)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Paper exit failed: {exc}")
                st.divider()
        else:
            st.info("No open paper positions.")
        if kite is None and positions:
            st.warning("Kite disconnected: automatic paper stop/target checks cannot run.")
    paper_position_monitor()
    if st.session_state.paper_trades:
        st.subheader("Trade history")
        history = pd.DataFrame(st.session_state.paper_trades)
        cols = ["tradingsymbol","status","quantity","entry_price","ltp","stop_price","target_price","pnl","exit_reason","opened_at","closed_at"]
        st.dataframe(history[[c for c in cols if c in history.columns]], use_container_width=True)
    realized = daily_realized_pnl(st.session_state.paper_trades)
    st.metric("Daily realized P&L", f"₹{realized:,.2f}")
    if realized <= -abs(daily_loss):
        st.error("Daily loss limit reached. New paper trades blocked.")

with guide_tab:
    st.markdown("""**Signal framework (research approximation, not proprietary DTC code):**
- Six EMA alignment: 30, 35, 40, 45, 50 and 60.
- ATR activity filter, VWAP and RSI confirmation.
- CE: bullish EMA stack, close above VWAP and RSI strength.
- PE: bearish EMA stack, close below VWAP and RSI weakness.
- Incomplete confirmation returns WAIT.

**Execution protections in this build:**
- Real option contract and quote discovery from Kite.
- Lot-size-aware quantity from capital-at-risk.
- Paper target, initial stop and trailing stop.
- Daily trade-count and realized-loss blocks.
- No real order placement; paper positions persist only for the current Streamlit session. Restarting the app clears them.

This does not guarantee profits. Use a persistent trade journal, market-hours tests and extended paper forward testing before considering any live workflow.""")
st.caption(f"Local time: {datetime.now(IST).strftime('%d-%b-%Y %H:%M:%S')} IST · Live orders disabled")
