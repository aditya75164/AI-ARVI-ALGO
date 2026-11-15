import streamlit as st
import pandas as pd
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from engine import add_dtc_style_indicators, build_signal
from stock_selector import scan_stock_universe
from option_enrichment import enrich_fno_option_premiums
from bot_ledger import init_db, sync_broker_history, dashboard_data
from paper_trading import quantity_for_risk, open_paper_trade, mark_paper_trade, close_paper_trade, can_open_trade, backtest_ema_strategy, compare_backtest_horizons, calculate_backtest_metrics
from paper_ledger import init_paper_db, load_paper_trades, save_paper_trade, paper_summary
from market_briefing import fetch_index_daily_candles, build_index_scenarios, fetch_market_news
from kite_adapter import (
    kite_client, login_url, generate_session, persist_access_token, fetch_index_candles,
    fetch_derivative_contracts, get_quote_snapshot, get_secret, validate_option_liquidity, filter_live_option_contracts, build_stock_option_watchlist, select_option_contract, get_option_ltp, quote_timestamp_age_seconds
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
                    persist_access_token(st.session_state.kite_access_token)
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
                        persist_access_token(st.session_state.kite_access_token)
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
    st.divider()
    st.caption("Kite market data: daily historical candles for F&O and NSE equity stock selection.")

kite=kite_client()
connected=bool(st.session_state.kite_profile) and kite is not None
c1,c2,c3=st.columns(3)
c1.metric("Kite market data","Connected" if connected else "Not verified")
c2.metric("Dashboard mode","Market + Paper")
c3.metric("Broker orders","OFF · Paper only")
st.info("Broker order execution is disabled. Paper BUY/SELL trades are simulated locally and never reach Zerodha.")

tabs=st.tabs(["Bot Control Center","Daily Market Brief","F&O Stock Selection","Equity Stock Selection","Live Market Monitor","Index Signals","F&O Options Watch","Indicator Guide","Paper Trading"])
with tabs[0]:
    st.subheader("Automated Trading Bot · Control Center")
    st.caption("Broker-synchronised orders, tradebook, positions and performance. This panel reports real Kite records; it does not invent fills or P&L.")
    init_db()
    if not connected:
        st.warning("Connect and verify Kite to synchronise broker records.")
    else:
        if st.button("Sync actual Kite orders & trades",type="primary",key="sync_broker_records"):
            try:
                result=sync_broker_history(kite)
                st.session_state.broker_sync_result=result
                st.success(f"Synced {result['orders']} orders and {result['trades']} trades from Kite.")
            except Exception as exc:
                st.error(f"Broker sync failed: {exc}")
        try:
            positions_data=kite.positions() or {}
            day_positions=positions_data.get("day") or []
            net_positions=positions_data.get("net") or []
            day_pnl=sum(float(p.get("pnl") or 0) for p in day_positions)
            net_pnl=sum(float(p.get("pnl") or 0) for p in net_positions)
            orders=kite.orders() or []
            trades=kite.trades() or []
            open_positions=[p for p in net_positions if int(p.get("quantity") or 0)!=0]
            a,b,c,d=st.columns(4)
            a.metric("Today's broker P&L",f"₹{day_pnl:,.2f}")
            b.metric("Net positions P&L",f"₹{net_pnl:,.2f}")
            c.metric("Open positions",len(open_positions))
            d.metric("Orders today",len(orders))
            st.markdown("#### Open broker positions")
            if open_positions:
                st.dataframe(pd.DataFrame(open_positions),use_container_width=True,hide_index=True)
            else:
                st.info("No open broker positions reported by Kite.")
            st.markdown("#### Actual broker orders")
            if orders: st.dataframe(pd.DataFrame(orders).sort_values("order_timestamp",ascending=False),use_container_width=True,hide_index=True)
            else: st.info("No broker orders returned.")
            st.markdown("#### Actual broker tradebook")
            if trades: st.dataframe(pd.DataFrame(trades).sort_values("fill_timestamp",ascending=False),use_container_width=True,hide_index=True)
            else: st.info("No broker trades returned.")
        except Exception as exc:
            st.error(f"Unable to read Kite portfolio: {exc}")
    ledger=dashboard_data()
    st.markdown("#### Background worker health")
    heartbeats=ledger.get("heartbeats",[])
    if heartbeats:
        hb=pd.DataFrame(heartbeats)
        hb["heartbeat_time"]=pd.to_datetime(hb["heartbeat_time"],errors="coerce",utc=True)
        now=pd.Timestamp.now(tz="UTC")
        hb["age_seconds"]=(now-hb["heartbeat_time"]).dt.total_seconds()
        hb["health"]=hb.apply(lambda r:"STALE" if pd.isna(r["age_seconds"]) or r["age_seconds"]>120 else r["status"],axis=1)
        st.dataframe(hb[["worker_name","heartbeat_time","health","age_seconds","message"]],use_container_width=True,hide_index=True)
        if (hb["health"]=="STALE").any():
            st.warning("Worker heartbeat is stale. The background service may be stopped or unable to reach the shared database.")
    else:
        db_path=os.getenv("ARVI_DB_PATH","arvi_bot.db")
        st.warning(
            "No worker heartbeat found in this dashboard's database. "
            "Kite login is separate from worker connectivity. The dashboard is currently reading "
            f"'{db_path}'. If this app is hosted on Streamlit Community Cloud while workers run "
            "on a separate VPS/Docker host, their local SQLite files are different and cannot "
            "share heartbeats automatically."
        )
        st.markdown("**Required deployment:** run the dashboard, index worker and stock F&O worker "
                    "together on the same always-on VPS using this repository's docker-compose.yml. "
                    "All three services must use ARVI_DB_PATH=/data/arvi_bot.db and the shared "
                    "arvi-data volume. Then open the dashboard on the VPS (port 8501), not the "
                    "separate *.streamlit.app deployment.")
        st.caption(f"Dashboard database path: {os.path.abspath(db_path)}")
    if ledger["positions"]:
        st.markdown("#### Bot-managed open positions")
        st.dataframe(pd.DataFrame(ledger["positions"]),use_container_width=True,hide_index=True)
    if ledger["orders"]:
        st.markdown("#### Bot order ledger")
        st.dataframe(pd.DataFrame(ledger["orders"]),use_container_width=True,hide_index=True)
    if ledger["events"]:
        st.markdown("#### Bot activity log")
        st.dataframe(pd.DataFrame(ledger["events"]),use_container_width=True,hide_index=True)
    st.warning("This dashboard reports broker records and worker activity. Worker and dashboard must share the same persistent database path. Live entries remain disabled by default; do not enable until end-to-end broker testing is complete.")
with tabs[1]:
    st.subheader("Daily market briefing")
    st.caption("NIFTY 50 and BANK NIFTY conditional scenarios, indicator-derived levels and market-moving headlines.")
    if not connected:
        st.warning("Connect and verify Kite to fetch the latest index daily candles. Headlines can still be refreshed independently.")
    top_left,top_right=st.columns([1,1])
    refresh_news=top_right.button("Refresh news",key="refresh_market_news")
    if refresh_news:
        st.session_state.market_news_refresh=datetime.now(IST).isoformat()
    @st.cache_data(ttl=900,show_spinner=False)
    def _cached_index_brief(_kite,index):
        candles=fetch_index_daily_candles(_kite,index,days=220)
        return build_index_scenarios(candles,index)
    @st.cache_data(ttl=900,show_spinner=False)
    def _cached_news(_refresh_key):
        return fetch_market_news()
    if connected:
        try:
            with st.spinner("Fetching latest completed daily index candles..."):
                nifty=_cached_index_brief(kite,"NIFTY")
                bank=_cached_index_brief(kite,"BANKNIFTY")
            st.caption(f"Index data: last completed daily candle · NIFTY {nifty['candle_date']} · BANK NIFTY {bank['candle_date']} · ATR(14) and prior 20-session swing levels")
            for brief in (nifty,bank):
                st.markdown(f"### {brief['index']}  ·  {brief['close']:,.2f}")
                st.caption(f"Support {brief['support']:,.2f} · Resistance {brief['resistance']:,.2f} · ATR(14) {brief['atr']:,.2f}")
                bull,bear=st.columns(2)
                with bull:
                    st.markdown("**:green[Bullish scenario ↑]**")
                    st.metric("Trigger above",f"{brief['bullish']['trigger']:,.2f}")
                    st.write(f"Targets: **{brief['bullish']['target1']:,.2f} → {brief['bullish']['target2']:,.2f}**")
                    st.caption(f"Scenario invalidation below {brief['bullish']['invalidation']:,.2f}")
                with bear:
                    st.markdown("**:red[Bearish scenario ↓]**")
                    st.metric("Trigger below",f"{brief['bearish']['trigger']:,.2f}")
                    st.write(f"Targets: **{brief['bearish']['target1']:,.2f} → {brief['bearish']['target2']:,.2f}**")
                    st.caption(f"Scenario invalidation above {brief['bearish']['invalidation']:,.2f}")
                st.caption(f"Calculation: {brief['method']}")
                st.divider()
        except Exception as exc:
            st.error(f"Index data unavailable: {exc}")
    try:
        news=_cached_news(st.session_state.get("market_news_refresh","daily"))
        st.markdown("### Market news")
        if news:
            for item in news:
                st.markdown(f"**[{item['title']}]({item['link']})**")
                st.caption(f"{item['publisher']} · {item['published']}")
        else:
            st.info("No headlines returned by the news feed.")
    except Exception as exc:
        st.warning(f"News feed unavailable right now: {exc}")
    st.caption(f"Brief generated: {datetime.now(IST).strftime('%d-%b-%Y %H:%M:%S IST')} · Refresh cache: 15 minutes. Scenarios are conditional levels, not predictions or guaranteed targets.")

with tabs[2]:
    st.subheader("Automatic NSE F&O Stock + Options Scanner")
    st.caption("No manual stock or CE/PE selection. ARVI scans the NSE F&O universe, derives direction from underlying indicators, selects the matching CE/PE premium, backtests candidates and ranks the strongest historical results.")
    st.info("Full-universe mode: ARVI checks every active NSE F&O underlying available in the Kite instrument master, ranks all valid daily-history signals, then tests up to 30 strongest unique stocks (one CE or PE contract per stock) to stay within Kite quote/history API limits.")
    if st.button("RUN AUTOMATIC NSE F&O SCAN + BACKTEST",type="primary",key="auto_fno_scan"):
        if not connected:
            st.error("Verify Kite connection first.")
        else:
            try:
                with st.spinner("Step 1/4 · Scanning NSE F&O stocks and calculating EMA, RSI, VWAP, ATR, relative volume and momentum..."):
                    stock_frame,scan_stats=scan_stock_universe(kite,"FNO",None)
                st.session_state.auto_fno_scan_stats=scan_stats
                st.session_state.auto_fno_stocks=stock_frame
                directional=stock_frame[stock_frame["Signal"].isin(["BUY","SELL"])].copy() if not stock_frame.empty else pd.DataFrame()
                if not directional.empty:
                    directional=directional.sort_values(["Score","Relative Volume","Turnover ₹"],ascending=[False,False,False]).drop_duplicates("Stock").reset_index(drop=True)
                # A single best liquid contract per stock; never repeat the same stock in the shortlist.
                shortlist=directional.head(30).copy()
                st.session_state.auto_fno_shortlist=shortlist
                with st.spinner("Step 2/4 · Selecting one trend-aligned CE/PE contract per shortlisted stock..."):
                    option_frame=enrich_fno_option_premiums(kite,shortlist,max_stocks=30) if not shortlist.empty else pd.DataFrame()
                st.session_state.auto_fno_options=option_frame
                tested=[]
                if not option_frame.empty:
                    with st.spinner("Step 3/4 · Backtesting one option contract per unique stock on 30 days of 5-minute candles..."):
                        master=pd.DataFrame(kite.instruments("NFO"))
                        token_map=dict(zip(master["tradingsymbol"].astype(str),master["instrument_token"].astype(int))) if not master.empty else {}
                        now=datetime.now(IST); start_date=now-timedelta(days=30)
                        for _,option in option_frame.iterrows():
                            symbol=str(option["Option Symbol"])
                            token=token_map.get(symbol)
                            if not token: continue
                            try:
                                candles=kite.historical_data(token,start_date,now,"5minute")
                                candle_frame=pd.DataFrame(candles)
                                if candle_frame.empty or "date" not in candle_frame.columns: continue
                                result=backtest_ema_strategy(candle_frame,fast=9,slow=21,stop_pct=5.0,target_pct=10.0,trailing_pct=1.5)
                                if int(result.get("trade_count",0))<1: continue
                                tested.append({
                                    "Stock":str(option["Stock"]),
                                    "Option":str(option["Option Side"]),
                                    "Contract":symbol,
                                    "Premium (₹)":float(option["Option Premium"]),
                                    "Underlying Signal":str(directional.loc[directional["Stock"].eq(option["Stock"]),"Signal"].iloc[0]),
                                    "Stock Score":float(directional.loc[directional["Stock"].eq(option["Stock"]),"Score"].iloc[0]),
                                    "RSI":float(directional.loc[directional["Stock"].eq(option["Stock"]),"RSI"].iloc[0]),
                                    "Relative Volume":float(directional.loc[directional["Stock"].eq(option["Stock"]),"Relative Volume"].iloc[0]),
                                    "Buyer Pressure":float(option["Buyer Pressure"]) if pd.notna(option["Buyer Pressure"]) else None,
                                    "Theta / Day":float(option["Option Theta / Day"]) if pd.notna(option["Option Theta / Day"]) else None,
                                    "Option OI":int(option["Option OI"]),
                                    "Option Volume":int(option["Option Volume"]),
                                    "Backtest Trades":int(result["trade_count"]),
                                    "Win Rate %":float(result["win_rate_pct"]),
                                    "Wins":int(result["wins"]),
                                    "Losses":int(result["losses"]),
                                    "Net Points / Unit":float(result["net_points_per_unit"]),
                                    "Net Trade Return %":round(sum(float(t.get("return_pct",0.0)) for t in result.get("trades",[])),2),
                                    "Strategy":"EMA 9/21 · 5-minute · 30-day"
                                })
                            except Exception:
                                continue
                tested_frame=pd.DataFrame(tested)
                if not tested_frame.empty:
                    tested_frame=tested_frame.sort_values(["Net Trade Return %","Net Points / Unit","Win Rate %","Stock Score"],ascending=False).drop_duplicates("Stock").reset_index(drop=True)
                    tested_frame.insert(0,"Rank",range(1,len(tested_frame)+1))
                st.session_state.auto_fno_backtest=tested_frame
                st.session_state.auto_fno_scan_time=datetime.now(IST).strftime("%d-%b-%Y %H:%M:%S IST")
            except Exception as exc:
                st.error(f"Automatic F&O scan failed: {exc}")
    scan_stats=st.session_state.get("auto_fno_scan_stats")
    if scan_stats:
        st.caption(f"Last scan: {st.session_state.get('auto_fno_scan_time','')} · Active NSE F&O underlyings: {scan_stats.get('universe',0)} · Quote-ranked: {scan_stats.get('quote_ranked',0)} · Daily histories checked: {scan_stats.get('history_checked',0)} · Valid indicator signals: {scan_stats.get('selected',0)} · Detailed option shortlist: max 30 unique stocks")
        stocks=st.session_state.get("auto_fno_stocks")
        if stocks is not None and not stocks.empty:
            st.markdown("#### Underlying stock signals")
            st.dataframe(stocks,use_container_width=True,hide_index=True)
        options=st.session_state.get("auto_fno_options")
        if options is not None and not options.empty:
            st.markdown("#### Automatically selected CE / PE premiums")
            st.caption("BUY underlying → CE; SELL underlying → PE. Option filters: live quote freshness, OI, volume, bid/ask spread, estimated theta and displayed bid/ask buyer pressure.")
            st.dataframe(options,use_container_width=True,hide_index=True)
        results=st.session_state.get("auto_fno_backtest")
        st.markdown("#### Best historical option strategies")
        if results is not None and not results.empty:
            st.success(f"{len(results)} unique stocks completed at least one historical option trade. One best CE/PE contract per stock. Ranked by summed historical trade return, then net points, win rate and underlying score. Trade count is shown as the evidence size; brokerage, taxes and slippage are not included.")
            st.dataframe(results,use_container_width=True,hide_index=True)
            st.download_button("Download automatic F&O backtest ranking",results.to_csv(index=False),"arvi_automatic_fno_backtest.csv","text/csv")
        else:
            st.warning("No shortlisted option produced even one valid historical trade. Check option contract history availability and the scan diagnostics above.")
    else:
        st.info("Press RUN AUTOMATIC NSE F&O SCAN + BACKTEST. ARVI scans all active NSE F&O underlyings, chooses one CE/PE contract per strongest unique stock and ranks the historical results. No manual stock selection is required.")

with tabs[3]:
    st.subheader("NSE equity stock selection")
    st.caption("Scans NSE cash-equity stocks separately from the F&O universe using daily historical candles.")
    max_eq=st.number_input("Maximum equity stocks to analyse",10,100,35,5,key="max_eq")
    if st.button("Scan NSE equity stocks",type="primary",key="scan_equity_universe"):
        try:
            if not connected: st.error("Verify Kite connection first.")
            else:
                with st.spinner("Scanning NSE equity universe and daily history..."):
                    frame,stats=scan_stock_universe(kite,"EQUITY",int(max_eq))
                st.session_state.equity_selection=frame
                st.session_state.equity_selection_stats=stats
        except Exception as exc: st.error(f"Equity scan failed: {exc}")
    frame=st.session_state.get("equity_selection")
    stats=st.session_state.get("equity_selection_stats")
    if stats:
        st.caption(f"NSE equity universe: {stats['universe']} · Quote ranked: {stats['quote_ranked']} · History checked: {stats['history_checked']} · Results: {stats['selected']}")
        if stats.get('reason'): st.info(stats['reason'])
    if frame is not None and not frame.empty:
        st.dataframe(frame,use_container_width=True,hide_index=True)
        st.download_button("Download equity stock picks",frame.to_csv(index=False),"arvi_equity_stock_picks.csv","text/csv")
    elif stats: st.warning("No stocks passed the available historical-data checks.")
    else: st.info("Click Scan NSE equity stocks to rank cash-market stocks.")

with tabs[4]:
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

with tabs[5]:
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

with tabs[6]:
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
    
with tabs[7]:
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


with tabs[8]:
    st.subheader("Paper Trading Control Center")
    st.caption("Virtual option BUY/SELL only. This panel never submits orders to Zerodha. Live Kite quotes are used for paper marks when authenticated.")
    init_paper_db()
    paper_trades=load_paper_trades()
    summary=paper_summary(paper_trades)
    m1,m2,m3,m4=st.columns(4)
    m1.metric("Open paper positions",summary["open"])
    m2.metric("Unrealized P&L",f"₹{summary['unrealized_pnl']:,.2f}")
    m3.metric("Realized P&L",f"₹{summary['realized_pnl']:,.2f}")
    m4.metric("Closed trades",summary["closed"])
    st.info("Execution mode: PAPER ONLY · No real BUY/SELL orders · One open paper position at a time.")
    if kite is None:
        st.warning("Kite access token is not available in this dashboard process. Complete Kite login and Verify Kite connection first.")
    else:
        if "paper_fno_underlyings" not in st.session_state:
            _master = pd.DataFrame(kite.instruments("NFO"))
            if _master.empty or not {"name","instrument_type","expiry"}.issubset(_master.columns):
                st.session_state.paper_fno_underlyings = ["NIFTY", "BANKNIFTY"]
            else:
                _master = _master[_master["instrument_type"].astype(str).str.upper().isin(["CE","PE"])].copy()
                _master["expiry"] = pd.to_datetime(_master["expiry"], errors="coerce").dt.date
                _master = _master[_master["expiry"] >= datetime.now(IST).date()]
                st.session_state.paper_fno_underlyings = sorted(_master["name"].dropna().astype(str).unique().tolist())
        paper_universe = st.session_state.paper_fno_underlyings or ["NIFTY", "BANKNIFTY"]
        st.markdown("#### Live market-data verification")
        if st.button("Verify live Kite market data",key="paper_verify_market"):
            try:
                profile=kite.profile()
                spot=float((kite.ltp(["NSE:NIFTY 50"]).get("NSE:NIFTY 50") or {}).get("last_price") or 0)
                if spot<=0: raise RuntimeError("Kite returned no valid NIFTY LTP")
                st.success(f"Authenticated as {profile.get('user_name') or profile.get('user_id')} · NIFTY LTP ₹{spot:,.2f}")
            except Exception as exc: st.error(f"Live market-data verification failed: {exc}")
        st.markdown("#### Open a virtual option BUY")
        st.caption("Universe: all currently unexpired NSE NFO option underlyings available in your Kite instrument master. Choose any stock/index and CE or PE.")
        x,y,z=st.columns(3)
        paper_underlying=x.selectbox("NSE F&O stock / index",paper_universe,key="paper_underlying")
        paper_side=y.selectbox("Option side",["CE","PE"],key="paper_side")
        paper_moneyness=z.selectbox("Strike selection",["ATM","1 ITM","1 OTM"],key="paper_moneyness")
        p1,p2,p3=st.columns(3)
        paper_capital=p1.number_input("Virtual capital (₹)",min_value=1000.0,max_value=10000000.0,value=100000.0,step=5000.0,key="paper_capital")
        paper_risk=p2.number_input("Risk per trade (%)",min_value=0.1,max_value=5.0,value=1.0,step=0.1,key="paper_risk")
        paper_stop=p3.number_input("Stop loss (%)",min_value=0.5,max_value=20.0,value=5.0,step=0.5,key="paper_stop")
        q1,q2,q3=st.columns(3)
        paper_target=q1.number_input("Target (%)",min_value=0.5,max_value=50.0,value=10.0,step=0.5,key="paper_target")
        paper_trailing=q2.checkbox("Enable trailing stop",value=True,key="paper_trailing")
        paper_trail_pct=q3.number_input("Trailing distance (%)",min_value=0.2,max_value=10.0,value=1.5,step=0.1,key="paper_trail_pct")
        market_now=datetime.now(IST)
        paper_market_open=(market_now.weekday()<5 and "09:15"<=market_now.strftime("%H:%M")<="15:30")
        if not paper_market_open:
            st.warning(f"NSE derivatives market is closed ({market_now.strftime('%A %d-%b-%Y %H:%M IST')}). Live-quote Paper BUY is disabled outside market hours. You can still review trade history and run historical backtests.")
        if st.button("Fetch selected option & calculate paper quantity",key="paper_fetch_contract",disabled=not paper_market_open):
            try:
                contract=select_option_contract(kite,paper_underlying,paper_side,paper_moneyness)
                age=quote_timestamp_age_seconds(contract.get("quote_time")) if contract.get("quote_time") else None
                if age is None or age>180: raise RuntimeError(f"Option quote is stale ({age:.0f}s old)." if age is not None else "Kite did not provide a quote timestamp. Paper entry blocked; retry during market hours.")
                quantity=quantity_for_risk(paper_capital,paper_risk,contract["option_ltp"],paper_stop,contract["lot_size"])
                st.session_state.paper_candidate={"contract":contract,"quantity":quantity,"age":age}
            except Exception as exc:
                st.session_state.paper_candidate=None
                st.error(f"Contract/quote check failed: {exc}")
        candidate=st.session_state.get("paper_candidate")
        if candidate:
            contract=candidate["contract"]
            st.dataframe(pd.DataFrame([{"Stock / Index":contract["underlying"],"Option":contract["side"],"Contract":contract["tradingsymbol"],"Expiry":contract["expiry"],"Strike":contract["strike"],"Premium (₹)":contract["option_ltp"],"Lot size":contract["lot_size"],"Buyer depth":contract.get("buyer_depth_qty"),"Seller depth":contract.get("seller_depth_qty"),"Quote age (sec)":round(candidate["age"],1),"Risk-sized quantity":candidate["quantity"]}]),use_container_width=True,hide_index=True)
            allowed,reason=can_open_trade(load_paper_trades(),3,1500)
            if not allowed: st.warning(reason)
            if candidate["quantity"]<=0: st.warning("Risk budget is too small for one complete lot.")
            if st.button("CONFIRM PAPER BUY",type="primary",disabled=(not allowed or candidate["quantity"]<=0),key="paper_confirm_buy"):
                try:
                    trade=open_paper_trade(contract,candidate["quantity"],paper_target,paper_stop,paper_trailing,paper_trail_pct)
                    save_paper_trade(trade); st.session_state.paper_candidate=None
                    st.success(f"Virtual BUY opened: {trade['tradingsymbol']} · Qty {trade['quantity']} · Entry ₹{trade['entry_price']:.2f}")
                    st.rerun()
                except Exception as exc: st.error(f"Paper entry failed: {exc}")
    st.markdown("#### Manage paper positions")
    paper_trades=load_paper_trades()
    open_trades=[t for t in paper_trades if t.get("status")=="OPEN"]
    if open_trades:
        if kite is None:
            st.warning("Connect Kite to update live marks. Paper positions remain stored in the local database.")
        else:
            st.caption("Live paper monitor refreshes every 5 seconds while this tab is open. SL/target/trailing checks use latest Kite LTP; simulated exits are not guaranteed exchange fills.")
        @st.fragment(run_every=5 if (kite is not None and open_trades) else None)
        def paper_position_monitor():
            current=load_paper_trades()
            active=[t for t in current if t.get("status")=="OPEN"]
            for trade in active:
                if kite is not None:
                    try:
                        live_price=get_option_ltp(kite,trade["tradingsymbol"])
                        marked=mark_paper_trade(trade,live_price)
                        if marked != trade:
                            save_paper_trade(marked)
                            trade=marked
                    except Exception as exc:
                        st.warning(f"{trade['tradingsymbol']}: live mark unavailable ({exc})")
                st.markdown(f"**{trade['tradingsymbol']}** · Qty {trade['quantity']} · Entry ₹{trade['entry_price']:.2f} · LTP ₹{trade['ltp']:.2f}")
                st.caption(f"Stop ₹{trade['stop_price']:.2f} · Target ₹{trade['target_price']:.2f} · P&L ₹{trade['pnl']:.2f} · {trade['status']}")
                if kite is not None and trade.get("status")=="OPEN" and st.button(f"SELL / Close paper position · {trade['tradingsymbol']}",key="paper_close_"+trade["id"]):
                    try:
                        exit_ltp=get_option_ltp(kite,trade["tradingsymbol"])
                        closed=close_paper_trade(trade,exit_ltp,"MANUAL_SELL")
                        save_paper_trade(closed)
                        st.success(f"Paper SELL closed at ₹{exit_ltp:.2f}; P&L ₹{closed['realized_pnl']:.2f}")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Paper close failed: {exc}")
        paper_position_monitor()
    else:
        st.info("No open paper positions.")
    paper_trades=load_paper_trades()
    if paper_trades:
        st.markdown("#### Paper trade history")
        st.dataframe(pd.DataFrame(paper_trades),use_container_width=True,hide_index=True)
        st.download_button("Download paper trade history CSV",pd.DataFrame(paper_trades).to_csv(index=False),"arvi_paper_trade_history.csv","text/csv")
    st.markdown("#### Strategy & stock-selection logic")
    with st.expander("Which indicators and strategy does AI ARVI use?"):
        st.markdown("""
        **Paper BUY contract selection:** this is a user-selected contract lookup, not an AI BUY signal. The app selects the nearest unexpired expiry and ATM / ITM / OTM strike from the NSE NFO instrument master, then checks the live quote timestamp. It does not rank or recommend a stock at this step.

        **F&O Stock Selection watchlist:** scans near-ATM CE/PE contracts for F&O stocks. It uses premium percentage change versus the previous close: BUY at +0.5% or more, SELL at -0.5% or less, otherwise WAIT. It selects the nearest expiry and ranks the selected contracts by open interest (OI) and traded volume. This is a simple momentum/reference filter, not EMA/RSI/ADX confirmation.

        **Historical Paper Backtest:** uses EMA 9 / EMA 21 bullish crossover on the selected option's 5-minute premium candles. Entry is simulated at the next candle open; stop-loss, target and trailing-stop rules manage exits. This is a separate strategy from the stock watchlist.
        
        **Important:** signals are research filters, not guaranteed recommendations. Verify liquidity, spread, underlying trend and risk before any paper trade.
        """)
    st.markdown("#### Automatic multi-stock NSE F&O backtest")
    st.caption("Compares 30, 60 and 90 available trading sessions for one automatically selected CE/PE contract per unique NSE F&O stock/index.")
    st.info("Includes estimated Zerodha NSE option charges, net P&L, maximum drawdown, profit factor, CE vs PE, NIFTY vs BANKNIFTY and directional strategy accuracy. Option contracts expire, so longer horizons are shown only when that exact contract has enough history; no missing data is fabricated.")
    if st.button("RUN FULL NSE MULTI-STOCK BACKTEST",type="primary",key="paper_backtest_all_stocks"):
        if kite is None:
            st.error("Kite login is required to scan NSE F&O instruments and download historical candles.")
        else:
            try:
                with st.spinner("1/4 · Scanning all active NSE F&O underlyings and calculating stock indicators..."):
                    auto_stocks,auto_stats=scan_stock_universe(kite,"FNO",None)
                st.session_state.paper_multi_scan_stats=auto_stats
                auto_directional=auto_stocks[auto_stocks["Signal"].isin(["BUY","SELL"])].copy() if not auto_stocks.empty else pd.DataFrame()
                if not auto_directional.empty:
                    auto_directional=auto_directional.sort_values(["Score","Relative Volume","Turnover ₹"],ascending=[False,False,False]).drop_duplicates("Stock").reset_index(drop=True)
                auto_shortlist=auto_directional.head(30).copy()
                with st.spinner(f"2/4 · Finding one best liquid CE/PE option for {len(auto_shortlist)} unique stocks..."):
                    auto_options=enrich_fno_option_premiums(kite,auto_shortlist,max_stocks=30) if not auto_shortlist.empty else pd.DataFrame()
                horizon_rows=[]
                availability_rows=[]
                if not auto_options.empty:
                    with st.spinner("3/4 · Downloading daily option candles and testing 30/60/90 trading-session horizons..."):
                        auto_master=pd.DataFrame(kite.instruments("NFO"))
                        auto_tokens=dict(zip(auto_master["tradingsymbol"].astype(str),auto_master["instrument_token"].astype(int))) if not auto_master.empty else {}
                        auto_end=datetime.now(IST); auto_start=auto_end-timedelta(days=180)
                        for _,auto_option in auto_options.iterrows():
                            auto_symbol=str(auto_option["Option Symbol"])
                            auto_token=auto_tokens.get(auto_symbol)
                            if not auto_token: continue
                            try:
                                auto_candles=pd.DataFrame(kite.historical_data(auto_token,auto_start,auto_end,"day"))
                                if auto_candles.empty or "date" not in auto_candles.columns:
                                    availability_rows.append({"Stock":str(auto_option["Stock"]),"Contract":auto_symbol,"Status":"No daily option history"})
                                    continue
                                auto_candles["date"]=pd.to_datetime(auto_candles["date"],errors="coerce",utc=True).dt.tz_convert("Asia/Kolkata")
                                comparisons=compare_backtest_horizons(auto_candles,horizons=(30,60,90),fast=9,slow=21,stop_pct=paper_stop,target_pct=paper_target,trailing_pct=paper_trail_pct)
                                lot=int(auto_option.get("Option Lot Size") or 1)
                                auto_row=auto_directional.loc[auto_directional["Stock"].eq(auto_option["Stock"])]
                                if auto_row.empty: continue
                                sig=auto_row.iloc[0]
                                for horizon,raw in comparisons.items():
                                    if not raw.get("available"):
                                        availability_rows.append({"Stock":str(auto_option["Stock"]),"Contract":auto_symbol,"Horizon (sessions)":horizon,"Sessions available":raw.get("sessions_available",0),"Status":raw.get("reason","Insufficient history")})
                                        continue
                                    metrics=calculate_backtest_metrics(raw,lot_size=lot)
                                    horizon_rows.append({
                                        "Horizon (sessions)":horizon,"Stock":str(auto_option["Stock"]),
                                        "Index / Stock Type":"Index" if str(auto_option["Stock"]) in ("NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY","NIFTYNXT50") else "F&O Stock",
                                        "Option Side":str(auto_option["Option Side"]),"Contract":auto_symbol,"Lot Size":lot,
                                        "Underlying Signal":str(sig["Signal"]),"Strategy":"EMA 9/21 · daily option candles",
                                        "Trades":metrics["trade_count"],"Wins":metrics["wins"],"Losses":metrics["losses"],
                                        "Accuracy (%)":metrics["win_rate_pct"],"Gross P&L (₹)":metrics["gross_pnl"],
                                        "Charges & Taxes (₹)":metrics["total_charges"],"Net P&L (₹)":metrics["net_pnl"],
                                        "Max Drawdown (₹)":metrics["max_drawdown"],"Profit Factor":metrics["profit_factor"],
                                        "Net Return (%)":round(sum(t["net_return_pct"] for t in metrics["trades"]),2),
                                        "Sessions Tested":raw.get("sessions_available",0)
                                    })
                            except Exception as option_exc:
                                availability_rows.append({"Stock":str(auto_option["Stock"]),"Contract":auto_symbol,"Status":str(option_exc)[:160]})
                auto_result_frame=pd.DataFrame(horizon_rows)
                if not auto_result_frame.empty:
                    auto_result_frame=auto_result_frame.sort_values(["Horizon (sessions)","Net P&L (₹)","Profit Factor","Accuracy (%)"],ascending=[True,False,False,False]).reset_index(drop=True)
                    auto_result_frame.insert(0,"Rank",auto_result_frame.groupby("Horizon (sessions)")["Net P&L (₹)"].rank(method="first",ascending=False).astype(int))
                st.session_state.paper_multi_backtest=auto_result_frame
                st.session_state.paper_multi_availability=pd.DataFrame(availability_rows)
                st.session_state.paper_multi_scan_time=datetime.now(IST).strftime("%d-%b-%Y %H:%M:%S IST")
            except Exception as exc:
                st.error(f"Automatic multi-stock backtest failed: {exc}")
    auto_saved=st.session_state.get("paper_multi_backtest")
    auto_stats_saved=st.session_state.get("paper_multi_scan_stats")
    if auto_stats_saved:
        st.caption(f"Last scan: {st.session_state.get('paper_multi_scan_time','')} · Active F&O universe: {auto_stats_saved.get('universe',0)} · Histories checked: {auto_stats_saved.get('history_checked',0)} · Scored stocks: {auto_stats_saved.get('selected',0)} · BUY/SELL: {auto_stats_saved.get('directional',0)} · WAIT: {auto_stats_saved.get('wait',0)} · Detailed contracts: up to 30")
    if auto_saved is not None:
        if not auto_saved.empty:
            st.success(f"{auto_saved['Stock'].nunique()} unique stocks/indexes produced at least one valid horizon result. Each row is one underlying and one horizon.")
            for horizon in (30,60,90):
                part=auto_saved[auto_saved["Horizon (sessions)"].eq(horizon)]
                st.markdown(f"##### {horizon}-trading-session results")
                if part.empty: st.warning(f"No selected option contract had enough history for {horizon} sessions.")
                else: st.dataframe(part,use_container_width=True,hide_index=True)
            st.markdown("##### CE vs PE performance")
            side_summary=auto_saved.groupby(["Horizon (sessions)","Option Side"],as_index=False).agg(
                Stocks=("Stock","nunique"),Trades=("Trades","sum"),Wins=("Wins","sum"),
                Gross_PnL=("Gross P&L (₹)","sum"),Charges=("Charges & Taxes (₹)","sum"),
                Net_PnL=("Net P&L (₹)","sum"),Max_Drawdown=("Max Drawdown (₹)","max"))
            st.dataframe(side_summary,use_container_width=True,hide_index=True)
            st.markdown("##### NIFTY vs BANKNIFTY")
            index_part=auto_saved[auto_saved["Stock"].isin(["NIFTY","BANKNIFTY"])]
            if index_part.empty: st.info("NIFTY/BANKNIFTY did not produce valid selected-contract history in this scan.")
            else: st.dataframe(index_part,use_container_width=True,hide_index=True)
            st.markdown("##### Strategy-wise BUY / SELL accuracy")
            strategy_summary=auto_saved.groupby(["Horizon (sessions)","Underlying Signal","Option Side","Strategy"],as_index=False).agg(
                Stocks=("Stock","nunique"),Trades=("Trades","sum"),Wins=("Wins","sum"),Losses=("Losses","sum"),Net_PnL=("Net P&L (₹)","sum"))
            strategy_summary["Accuracy (%)"]=(strategy_summary["Wins"]/strategy_summary["Trades"].replace(0,pd.NA)*100).round(2)
            st.dataframe(strategy_summary,use_container_width=True,hide_index=True)
            st.download_button("Download all horizon metrics",auto_saved.to_csv(index=False),"arvi_multi_stock_horizon_metrics.csv","text/csv")
        else:
            st.warning("No selected option contract produced enough daily candles and at least one valid EMA trade.")
        missing=st.session_state.get("paper_multi_availability")
        if missing is not None and not missing.empty:
            with st.expander("Contracts / horizons with insufficient history"):
                st.dataframe(missing,use_container_width=True,hide_index=True)
    else:
        st.info("Click RUN FULL NSE MULTI-STOCK BACKTEST. ARVI scans the NSE F&O universe and compares available 30/60/90-session results.")
    st.caption("Paper positions are marked when live prices are refreshed. Stop/target are simulated checks, not exchange orders or guaranteed fills.")
