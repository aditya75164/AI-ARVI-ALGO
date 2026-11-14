"""Always-on ARVI bot worker.

Run as a separate long-lived process, not inside Streamlit. It scans NIFTY and
BANKNIFTY 5-minute index candles. Live orders are hard-disabled by default and
require ARVI_LIVE_TRADING=YES plus explicit risk limits in the worker host.
"""
import json
import logging
import os
import signal
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
from kiteconnect import KiteConnect
from engine import add_dtc_style_indicators, build_signal
from kite_adapter import select_option_contract, quote_timestamp_age_seconds
from bot_ledger import init_db, record_event, dashboard_data, upsert_position, close_position, update_worker_heartbeat
from order_executor import place_guarded_entry, place_protective_stop, reconcile_order, cancel_order, ExecutionBlocked, live_enabled
from startup_reconciliation import reconcile_startup_state

IST=ZoneInfo("Asia/Kolkata")
STOP=False
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"),format="%(asctime)s %(levelname)s %(message)s")
LOG=logging.getLogger("arvi-worker")
INDEX_TOKEN={"NIFTY":256265,"BANKNIFTY":260105}


def _stop(*_):
    global STOP
    STOP=True


def load_config(path=None):
    path=path or os.getenv("ARVI_BOT_CONFIG","bot_config.json")
    with open(path,encoding="utf-8") as f: cfg=json.load(f)
    cfg.setdefault("symbols",["NIFTY","BANKNIFTY"])
    cfg.setdefault("interval","5minute")
    cfg.setdefault("poll_seconds",30)
    cfg.setdefault("max_risk_per_trade",500)
    cfg.setdefault("max_lots",1)
    cfg.setdefault("max_open_positions",1)
    cfg.setdefault("daily_loss_limit",1500)
    cfg.setdefault("product","MIS")
    # Safe defaults: the worker can scan and log candidates, never send orders.
    cfg.setdefault("execution_mode", "SIGNAL_ONLY")
    cfg.setdefault("live_trading_approved", False)
    return cfg


def live_authorized(cfg):
    """Require both environment keys and an explicitly reviewed config."""
    return (
        live_enabled()
        and cfg.get("execution_mode") == "AUTO"
        and cfg.get("live_trading_approved") is True
    )


def create_kite():
    key=os.getenv("KITE_API_KEY"); token=os.getenv("KITE_ACCESS_TOKEN")
    if not key or not token: raise RuntimeError("KITE_API_KEY and KITE_ACCESS_TOKEN must be configured in worker environment")
    kite=KiteConnect(api_key=key); kite.set_access_token(token); kite.profile()
    return kite


def fetch_index_frame(kite,symbol,interval="5minute"):
    if symbol not in INDEX_TOKEN: raise ValueError("Unsupported bot index")
    now=datetime.now(IST)
    rows=kite.historical_data(INDEX_TOKEN[symbol],now-timedelta(days=8),now,interval)
    if not rows: return pd.DataFrame()
    frame=pd.DataFrame(rows).set_index("date").sort_index()
    return frame.rename(columns={"open":"Open","high":"High","low":"Low","close":"Close","volume":"Volume"})


def build_option_intent(kite,symbol,signal,max_risk_per_trade,max_lots):
    side="CE" if signal["signal"]=="BUY CE" else "PE"
    contract=select_option_contract(kite,symbol,side,"ATM")
    now=datetime.now(IST)
    stamp=contract.get("quote_time")
    age=quote_timestamp_age_seconds(stamp,now) if stamp else None
    if age is None or age>5: raise ExecutionBlocked("Option quote timestamp missing or older than 5 seconds")
    if contract["volume"]<=0 or contract["oi"]<=0: raise ExecutionBlocked("Option has no volume or open interest")
    buyer_qty=int(contract.get("buyer_depth_qty") or 0)
    seller_qty=int(contract.get("seller_depth_qty") or 0)
    depth_ratio=contract.get("buyer_seller_depth_ratio")
    if seller_qty<=0 or depth_ratio is None:
        raise ExecutionBlocked("Buyer/seller order-book depth is unavailable")
    if float(depth_ratio)<2.0:
        raise ExecutionBlocked(f"Buyer depth is below the required 2:1 ratio ({buyer_qty}:{seller_qty})")
    bid=contract["best_bid"]; ask=contract["best_ask"]; premium=contract["option_ltp"]
    if bid<=0 or ask<=0 or ask<bid: raise ExecutionBlocked("Two-sided option depth unavailable")
    spread=(ask-bid)/premium*100
    if spread>2.5: raise ExecutionBlocked(f"Option spread {spread:.2f}% exceeds 2.5%")
    if premium<=0: raise ExecutionBlocked("Option premium invalid")
    candles=kite.historical_data(contract["instrument_token"],now-timedelta(days=5),now,"5minute")
    if len(candles)<20: raise ExecutionBlocked("Insufficient option candles to calculate protective levels")
    frame=pd.DataFrame(candles)
    tr=pd.concat([frame["high"]-frame["low"],(frame["high"]-frame["close"].shift()).abs(),(frame["low"]-frame["close"].shift()).abs()],axis=1).max(axis=1)
    atr=float(tr.tail(14).mean())
    if atr<=0: raise ExecutionBlocked("Option ATR unavailable")
    tick=0.05
    entry=round(ask/tick)*tick
    stop=round(max(tick,entry-1.5*atr)/tick)*tick
    target=round((entry+2.0*atr)/tick)*tick
    risk_per_unit=entry-stop
    qty_by_risk=int(float(max_risk_per_trade)//risk_per_unit)
    lot=int(contract["lot_size"])
    lots=min(int(max_lots),qty_by_risk//lot)
    if lots<1: raise ExecutionBlocked("Risk budget cannot fund one complete option lot")
    qty=lots*lot
    return {
        "exchange":"NFO","tradingsymbol":contract["tradingsymbol"],"transaction_type":"BUY",
        "quantity":qty,"lot_size":lot,"entry_price":entry,"stop_price":stop,
        "target_price":target,"quote_age_seconds":age,"tick_size":tick,
        "expiry":contract["expiry"],"strike":contract["strike"],"side":side,
        "underlying":symbol,"option_atr":atr,"spread_pct":spread,
        "buyer_depth_qty":buyer_qty,"seller_depth_qty":seller_qty,
        "buyer_seller_depth_ratio":round(float(depth_ratio),2),
        "risk_rupees":round((entry-stop)*qty,2)
    }


def run_scan_cycle(kite,cfg):
    init_db()
    events=[]
    data=dashboard_data()
    open_positions=data["positions"]
    if len(open_positions)>=int(cfg["max_open_positions"]):
        return [{"status":"BLOCKED","reason":"Maximum open positions reached"}]
    try:
        broker_positions=kite.positions() or {}
        broker_day=broker_positions.get("day") or []
        day_pnl=sum(float(p.get("pnl") or 0) for p in broker_day)
        broker_net=broker_positions.get("net") or []
    except Exception as exc:
        record_event("RISK_MANAGER","BROKER_RISK_READ","ERROR","Cannot read broker positions; new entries blocked",{"error":str(exc)})
        return [{"status":"RISK_DATA_UNAVAILABLE"}]
    if day_pnl<=-abs(float(cfg["daily_loss_limit"])):
        record_event("RISK_MANAGER","DAILY_LOSS_LIMIT","BLOCKED",
                     "Daily loss limit reached; no new entries allowed",{"day_pnl":day_pnl})
        return [{"status":"DAILY_LOSS_LIMIT","day_pnl":day_pnl}]
    active_broker=[p for p in broker_net if int(p.get("quantity") or 0)!=0 and str(p.get("exchange","")) in ("NFO","NSE")]
    tracked={(str(p.get("exchange","")).upper(),str(p.get("tradingsymbol","")).upper()) for p in open_positions}
    unmanaged=[p for p in active_broker if (str(p.get("exchange","")).upper(),str(p.get("tradingsymbol","")).upper()) not in tracked]
    if unmanaged:
        record_event("RISK_MANAGER","UNMANAGED_POSITION","BLOCKED",
                     "Untracked broker position detected; no new entries will be sent",{"positions":unmanaged})
        return [{"status":"UNMANAGED_BROKER_POSITION","count":len(unmanaged)}]
    if len(active_broker)>=int(cfg["max_open_positions"]):
        return [{"status":"BROKER_POSITION_LIMIT","open_positions":len(active_broker)}]
    for symbol in cfg["symbols"]:
        bot_name=f"{symbol}_5M"
        try:
            candles=fetch_index_frame(kite,symbol,cfg["interval"])
            if candles.empty:
                record_event(bot_name,"SCAN","NO_DATA","No index candles returned")
                events.append({"bot":bot_name,"status":"NO_DATA"}); continue
            analysed=add_dtc_style_indicators(candles)
            result=build_signal(analysed)
            record_event(bot_name,"SIGNAL",result["signal"],result["reason"],{"score":result["score"]})
            if result["signal"]=="WAIT":
                events.append({"bot":bot_name,"status":"WAIT","score":result["score"]}); continue
            # Avoid repeat entry for same bot while a position or working order exists.
            fresh=dashboard_data()
            if any(p["bot_name"]==bot_name for p in fresh["positions"]):
                events.append({"bot":bot_name,"status":"POSITION_OPEN"}); continue
            if any(o["bot_name"]==bot_name and o["status"] in ("OPEN","PENDING","TRIGGER PENDING","AMO REQ RECEIVED") for o in fresh["orders"]):
                events.append({"bot":bot_name,"status":"ORDER_PENDING"}); continue
            intent=build_option_intent(kite,symbol,result,float(cfg["max_risk_per_trade"]),int(cfg["max_lots"]))
            if not live_authorized(cfg):
                record_event(bot_name,"TRADE_CANDIDATE","READY","Live trading disabled; candidate not sent to broker",intent)
                events.append({"bot":bot_name,"status":"CANDIDATE_ONLY","symbol":intent["tradingsymbol"],"entry":intent["entry_price"],"sl":intent["stop_price"],"target":intent["target_price"],"risk":intent["risk_rupees"]})
                continue
            placed=place_guarded_entry(kite,intent,bot_name,float(cfg["max_risk_per_trade"]),max_lots=int(cfg["max_lots"]))
            order_id=placed["order_id"]
            # Wait briefly for broker confirmation; never assume an acknowledgement is a fill.
            time.sleep(2)
            latest=reconcile_order(kite,order_id,bot_name)
            filled=int(latest.get("filled_quantity") or 0)
            if filled<=0:
                if latest.get("status") in ("OPEN","PENDING"):
                    try: cancel_order(kite,order_id)
                    except Exception: pass
                record_event(bot_name,"ENTRY_NOT_FILLED",latest.get("status","UNKNOWN"),"No entry fill confirmed; no protective stop was sent",{"order_id":order_id})
                events.append({"bot":bot_name,"status":"ENTRY_NOT_FILLED","order_id":order_id})
                continue
            if latest.get("status")!="COMPLETE":
                # Protect any partial fill after cancelling the unfilled remainder.
                try: cancel_order(kite,order_id)
                except Exception: pass
                latest=reconcile_order(kite,order_id,bot_name)
                filled=int(latest.get("filled_quantity") or filled)
            average=float(latest.get("average_price") or intent["entry_price"])
            intent["entry_price"]=average
            sl_id=place_protective_stop(kite,intent,filled,bot_name,order_id)
            upsert_position({"position_key":order_id,"bot_name":bot_name,"tradingsymbol":intent["tradingsymbol"],
                "exchange":"NFO","quantity":filled,"average_price":average,"stop_order_id":sl_id,
                "target_price":intent["target_price"],"status":"OPEN",
                "payload":{"entry_order_id":order_id,"stop_price":intent["stop_price"],"side":intent["side"]}})
            record_event(bot_name,"POSITION_OPEN","PROTECTED","Entry fill verified and broker-side stop submitted",
                         {"entry_order_id":order_id,"stop_order_id":sl_id,"quantity":filled,"target":intent["target_price"]})
            events.append({"bot":bot_name,"status":"OPEN_PROTECTED","order_id":order_id,"stop_order_id":sl_id})
        except ExecutionBlocked as exc:
            record_event(bot_name,"TRADE_BLOCKED","BLOCKED",str(exc))
            events.append({"bot":bot_name,"status":"BLOCKED","reason":str(exc)})
        except Exception as exc:
            LOG.exception("Scan failed for %s",symbol)
            record_event(bot_name,"WORKER_ERROR","ERROR",str(exc))
            events.append({"bot":bot_name,"status":"ERROR","reason":str(exc)})
    return events


def monitor_open_positions(kite):
    """Reconcile broker-side SLs and manage target exits from the always-on worker."""
    data=dashboard_data()
    outcomes=[]
    for position in data["positions"]:
        bot=position["bot_name"]; symbol=position["tradingsymbol"]
        try:
            stop_id=position.get("stop_order_id") or ""
            if stop_id:
                sl=reconcile_order(kite,stop_id,bot)
                if sl.get("status")=="COMPLETE":
                    close_position(position["position_key"])
                    record_event(bot,"POSITION_CLOSED","STOP_FILLED","Broker confirmed protective stop fill",{"stop_order_id":stop_id})
                    outcomes.append({"symbol":symbol,"status":"STOP_FILLED"})
                    continue
            key=f"{position['exchange']}:{symbol}"
            q=kite.quote([key]).get(key,{})
            ltp=float(q.get("last_price") or 0)
            quote_time=q.get("timestamp") or q.get("last_trade_time")
            quote_age=quote_timestamp_age_seconds(quote_time) if quote_time else None
            if ltp<=0 or quote_age is None or quote_age>5: continue
            if ltp>=float(position["target_price"]):
                if not live_enabled():
                    record_event(bot,"TARGET_EXIT_HELD","BLOCKED",
                                 "Target reached but live execution approval is OFF; operator review required",
                                 {"ltp":ltp,"target":position["target_price"]})
                    outcomes.append({"symbol":symbol,"status":"TARGET_EXIT_HELD_LIVE_LOCKED"})
                    continue
                # Reconcile any previously submitted target market order before retrying.
                current=dashboard_data()
                pending_exit=next((o for o in current["orders"] if o["bot_name"]==bot and
                    o["transaction_type"]=="SELL" and o["order_type"]=="MARKET" and
                    o["status"] in ("OPEN","PENDING","VALIDATION PENDING","AMO REQ RECEIVED")),None)
                if pending_exit:
                    latest_exit=reconcile_order(kite,pending_exit["order_id"],bot)
                    if latest_exit.get("status")=="COMPLETE":
                        close_position(position["position_key"])
                        record_event(bot,"POSITION_CLOSED","TARGET_FILLED","Broker confirmed previously submitted target exit",
                                     {"exit_order_id":pending_exit["order_id"]})
                        outcomes.append({"symbol":symbol,"status":"TARGET_FILLED"})
                    else:
                        outcomes.append({"symbol":symbol,"status":"TARGET_EXIT_PENDING"})
                    continue
                # Cancel the protective stop and confirm cancellation before sending target exit.
                if stop_id:
                    try: cancel_order(kite,stop_id)
                    except Exception as exc:
                        record_event(bot,"TARGET_EXIT_BLOCKED","ERROR","Could not cancel SL before target exit",{"error":str(exc)})
                        continue
                    sl=reconcile_order(kite,stop_id,bot)
                    if sl.get("status") not in ("CANCELLED","CANCELED","REJECTED"):
                        record_event(bot,"TARGET_EXIT_BLOCKED","PENDING","SL cancellation not confirmed; target exit withheld",{"stop_status":sl.get("status")})
                        continue
                exit_id=kite.place_order(variety=kite.VARIETY_REGULAR,exchange=position["exchange"],
                    tradingsymbol=symbol,transaction_type=kite.TRANSACTION_TYPE_SELL,
                    quantity=int(position["quantity"]),product=kite.PRODUCT_MIS,
                    order_type=kite.ORDER_TYPE_MARKET,validity=kite.VALIDITY_DAY,
                    tag=("ARVITGT"+str(position["position_key"]))[:20])
                time.sleep(2)
                exit_order=reconcile_order(kite,exit_id,bot)
                if exit_order.get("status")=="COMPLETE":
                    close_position(position["position_key"])
                    record_event(bot,"POSITION_CLOSED","TARGET_FILLED","Broker confirmed target exit fill",
                                 {"exit_order_id":str(exit_id),"average_price":exit_order.get("average_price")})
                    outcomes.append({"symbol":symbol,"status":"TARGET_FILLED"})
                else:
                    record_event(bot,"TARGET_EXIT_PENDING",exit_order.get("status","UNKNOWN"),
                                 "Target exit submitted; worker will reconcile on next cycle",{"exit_order_id":str(exit_id)})
                    outcomes.append({"symbol":symbol,"status":"TARGET_EXIT_PENDING"})
        except Exception as exc:
            LOG.exception("Position monitor failed for %s",symbol)
            record_event(bot,"POSITION_MONITOR_ERROR","ERROR",str(exc))
            outcomes.append({"symbol":symbol,"status":"ERROR","reason":str(exc)})
    return outcomes


def connect_with_retry(worker_name):
    """Keep the worker alive and visible while Kite credentials/network recover."""
    while not STOP:
        try:
            kite=create_kite()
            update_worker_heartbeat(worker_name,"RUNNING","Kite session connected")
            return kite
        except Exception as exc:
            message=str(exc)
            auth_hint=any(word in message.lower() for word in ("token","auth","session","permission","api key"))
            status="AUTH_REQUIRED" if auth_hint else "ERROR"
            # Never log environment values or request headers.
            update_worker_heartbeat(worker_name,status,"Kite connection unavailable: "+message[:240])
            LOG.warning("%s connection unavailable (%s); retrying in 60 seconds",worker_name,status)
            for _ in range(60):
                if STOP: break
                time.sleep(1)
    return None


def main():
    signal.signal(signal.SIGTERM,_stop); signal.signal(signal.SIGINT,_stop)
    cfg=load_config()
    init_db()
    kite=connect_with_retry("INDEX_OPTIONS")
    if kite is None:
        update_worker_heartbeat("INDEX_OPTIONS","STOPPED","Worker shutdown requested")
        return
    recovery=reconcile_startup_state(kite)
    update_worker_heartbeat("INDEX_OPTIONS","RUNNING","Worker connected; startup reconciliation complete",
        {"symbols":cfg["symbols"],"live_enabled":live_authorized(cfg),
         "safe_for_new_entries":recovery["safe_for_new_entries"],
         "unmanaged_positions":len(recovery["unmanaged_positions"])})
    LOG.info("ARVI worker started; live execution=%s; startup safe=%s; symbols=%s",
             live_authorized(cfg),recovery["safe_for_new_entries"],cfg["symbols"])
    while not STOP:
        now=datetime.now(IST)
        if now.weekday()<5 and "09:20"<=now.strftime("%H:%M")<="15:20" and recovery["safe_for_new_entries"]:
            try:
                # Always manage already-open positions, even if the new-entry switch is OFF.
                exits=monitor_open_positions(kite)
                result=run_scan_cycle(kite,cfg)
                update_worker_heartbeat("INDEX_OPTIONS","RUNNING","Last cycle completed",{"position_monitor":exits,"scan":result,"live_enabled":live_authorized(cfg),"safe_for_new_entries":recovery["safe_for_new_entries"]})
                LOG.info("Position monitor: %s | Cycle result: %s",exits,result)
            except Exception as exc:
                update_worker_heartbeat("INDEX_OPTIONS","ERROR",str(exc))
                LOG.exception("Worker cycle failed")
        if recovery["safe_for_new_entries"] is False:
            # Re-check broker/local alignment periodically; never auto-adopt an unknown position.
            try:
                recovery=reconcile_startup_state(kite)
                update_worker_heartbeat("INDEX_OPTIONS","BLOCKED" if not recovery["safe_for_new_entries"] else "RUNNING",
                    "Unmanaged broker position requires manual review" if not recovery["safe_for_new_entries"] else "Position reconciliation cleared",
                    {"unmanaged_positions":len(recovery["unmanaged_positions"])})
            except Exception as exc:
                update_worker_heartbeat("INDEX_OPTIONS","ERROR","Recovery check failed: "+str(exc))
        time.sleep(max(10,int(cfg["poll_seconds"])))
    update_worker_heartbeat("INDEX_OPTIONS","STOPPED","Worker received shutdown signal")
    LOG.info("ARVI worker stopped")


if __name__=="__main__":
    main()
