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
from bot_ledger import init_db, record_event, dashboard_data
from order_executor import place_guarded_entry, place_protective_stop, reconcile_order, cancel_order, ExecutionBlocked, live_enabled

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
    return cfg


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
        "risk_rupees":round((entry-stop)*qty,2)
    }


def run_scan_cycle(kite,cfg):
    init_db()
    events=[]
    data=dashboard_data()
    open_positions=data["positions"]
    if len(open_positions)>=int(cfg["max_open_positions"]):
        return [{"status":"BLOCKED","reason":"Maximum open positions reached"}]
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
            if not live_enabled():
                record_event(bot_name,"TRADE_CANDIDATE","READY","Live trading disabled; candidate not sent to broker",intent)
                events.append({"bot":bot_name,"status":"CANDIDATE_ONLY","symbol":intent["tradingsymbol"],"entry":intent["entry_price"],"sl":intent["stop_price"],"target":intent["target_price"],"risk":intent["risk_rupees"]})
                continue
            placed=place_guarded_entry(kite,intent,bot_name,float(cfg["max_risk_per_trade"]),max_lots=int(cfg["max_lots"]))
            order_id=placed["order_id"]
            # Wait briefly for broker confirmation; never assume an acknowledgement is a fill.
            time.sleep(2)
            latest=reconcile_order(kite,order_id,bot_name)
            if latest.get("status")!="COMPLETE" or int(latest.get("filled_quantity") or 0)<=0:
                if latest.get("status") in ("OPEN","PENDING"):
                    try: cancel_order(kite,order_id)
                    except Exception: pass
                record_event(bot_name,"ENTRY_NOT_FILLED",latest.get("status","UNKNOWN"),"Entry was not confirmed filled; no protective stop was sent",{"order_id":order_id})
                events.append({"bot":bot_name,"status":"ENTRY_NOT_FILLED","order_id":order_id})
                continue
            filled=int(latest["filled_quantity"]); average=float(latest.get("average_price") or intent["entry_price"])
            intent["entry_price"]=average
            sl_id=place_protective_stop(kite,intent,filled,bot_name,order_id)
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


def main():
    signal.signal(signal.SIGTERM,_stop); signal.signal(signal.SIGINT,_stop)
    cfg=load_config(); kite=create_kite()
    LOG.info("ARVI worker started; live execution=%s; symbols=%s",live_enabled(),cfg["symbols"])
    while not STOP:
        now=datetime.now(IST)
        if now.weekday()<5 and "09:20"<=now.strftime("%H:%M")<="15:20":
            try:
                result=run_scan_cycle(kite,cfg)
                LOG.info("Cycle result: %s",result)
            except Exception:
                LOG.exception("Worker cycle failed")
        time.sleep(max(10,int(cfg["poll_seconds"])))
    LOG.info("ARVI worker stopped")


if __name__=="__main__":
    main()
