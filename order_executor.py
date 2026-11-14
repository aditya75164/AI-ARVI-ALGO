"""Guarded Zerodha execution primitives.

Live execution is OFF unless ARVI_LIVE_TRADING=YES is set in the worker
environment. This module is not called by Streamlit UI. Every order is risk
checked, persisted, and reconciled against broker order history.
"""
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from bot_ledger import upsert_order, record_event

IST=ZoneInfo("Asia/Kolkata")
ALLOWED_EXCHANGES={"NFO","NSE"}
ALLOWED_PRODUCTS={"MIS"}


class ExecutionBlocked(RuntimeError):
    pass


def live_enabled():
    """Two-key live switch; both values must be explicitly set by the operator."""
    return (
        os.getenv("ARVI_LIVE_TRADING", "").strip().upper() == "YES"
        and os.getenv("ARVI_LIVE_TRADING_APPROVED", "").strip().upper() == "YES"
    )


def validate_order_intent(intent, max_risk_rupees, max_lots=1, market_now=None):
    required=("exchange","tradingsymbol","transaction_type","quantity","lot_size","entry_price","stop_price","target_price")
    missing=[k for k in required if k not in intent or intent[k] is None]
    if missing: raise ExecutionBlocked("Missing order fields: "+", ".join(missing))
    if intent["exchange"] not in ALLOWED_EXCHANGES: raise ExecutionBlocked("Exchange is not enabled for this bot")
    if intent["transaction_type"]!="BUY": raise ExecutionBlocked("Only long-option / cash BUY entries are enabled in initial release")
    symbol=str(intent["tradingsymbol"])
    if not re.fullmatch(r"[A-Z0-9&_-]{2,40}",symbol): raise ExecutionBlocked("Invalid trading symbol")
    qty=int(intent["quantity"]); lot=int(intent["lot_size"])
    if qty<=0 or lot<=0 or qty%lot: raise ExecutionBlocked("Quantity must be a positive whole number of lots")
    if qty//lot>max_lots: raise ExecutionBlocked("Configured maximum lots exceeded")
    entry=float(intent["entry_price"]); stop=float(intent["stop_price"]); target=float(intent["target_price"])
    if min(entry,stop,target)<=0 or not stop<entry<target:
        raise ExecutionBlocked("For long positions, require 0 < stop < entry < target")
    risk=(entry-stop)*qty
    if risk>float(max_risk_rupees): raise ExecutionBlocked(f"Risk ₹{risk:.2f} exceeds per-trade limit ₹{max_risk_rupees:.2f}")
    now=market_now or datetime.now(IST)
    if now.weekday()>=5 or not ("09:20"<=now.strftime("%H:%M")<="15:20"):
        raise ExecutionBlocked("Entry window is closed")
    if not live_enabled(): raise ExecutionBlocked(
            "Live trading locked: ARVI_LIVE_TRADING=YES and "
            "ARVI_LIVE_TRADING_APPROVED=YES are both required after configuration review"
        )
    return {"risk_rupees":round(risk,2),"quantity":qty}


def place_guarded_entry(kite,intent,bot_name,max_risk_rupees,db_path=None,max_lots=1):
    """Submit a LIMIT entry, then confirm broker acknowledgement and persist it."""
    checked=validate_order_intent(intent,max_risk_rupees,max_lots=max_lots)
    if intent.get("quote_age_seconds") is None or float(intent["quote_age_seconds"])>5:
        raise ExecutionBlocked("Entry quote is missing or older than 5 seconds")
    price=float(intent["entry_price"])
    order_id=kite.place_order(
        variety=kite.VARIETY_REGULAR,exchange=intent["exchange"],
        tradingsymbol=intent["tradingsymbol"],transaction_type=kite.TRANSACTION_TYPE_BUY,
        quantity=int(intent["quantity"]),product=kite.PRODUCT_MIS,
        order_type=kite.ORDER_TYPE_LIMIT,price=price,validity=kite.VALIDITY_DAY,
        tag=("ARVI"+re.sub(r"[^A-Z0-9]","",bot_name.upper())[:16])[:20]
    )
    if not order_id: raise ExecutionBlocked("Broker did not return an order ID")
    record_event(bot_name,"ENTRY_SUBMITTED","PENDING","LIMIT entry submitted",{"order_id":str(order_id),"risk":checked["risk_rupees"]},db_path)
    history=kite.order_history(order_id) or []
    latest=history[-1] if history else {"order_id":order_id,"status":"UNKNOWN","tradingsymbol":intent["tradingsymbol"],
                                        "exchange":intent["exchange"],"transaction_type":"BUY","quantity":intent["quantity"],
                                        "order_type":"LIMIT","product":"MIS"}
    latest["order_id"]=str(order_id)
    upsert_order(latest,bot_name,db_path)
    return {"order_id":str(order_id),"status":latest.get("status","UNKNOWN"),"risk_rupees":checked["risk_rupees"]}


def place_protective_stop(kite,intent,quantity,bot_name,parent_order_id,db_path=None):
    """Place a broker-side SL sell order after the entry is confirmed filled."""
    if not live_enabled(): raise ExecutionBlocked("Live trading disabled")
    trigger=float(intent["stop_price"])
    tick=float(intent.get("tick_size") or 0.05)
    price=max(tick,round(trigger-tick,2))
    order_id=kite.place_order(
        variety=kite.VARIETY_REGULAR,exchange=intent["exchange"],
        tradingsymbol=intent["tradingsymbol"],transaction_type=kite.TRANSACTION_TYPE_SELL,
        quantity=int(quantity),product=kite.PRODUCT_MIS,order_type=kite.ORDER_TYPE_SL,
        price=price,trigger_price=trigger,validity=kite.VALIDITY_DAY,
        tag=("ARVISL"+str(parent_order_id))[:20]
    )
    if not order_id: raise ExecutionBlocked("Broker did not return protective stop order ID")
    record_event(bot_name,"PROTECTIVE_SL_SUBMITTED","PENDING","Broker-side stop-loss submitted",
                 {"order_id":str(order_id),"parent_order_id":str(parent_order_id),"trigger":trigger},db_path)
    history=kite.order_history(order_id) or []
    latest=history[-1] if history else {"order_id":order_id,"status":"UNKNOWN","tradingsymbol":intent["tradingsymbol"],
        "exchange":intent["exchange"],"transaction_type":"SELL","quantity":quantity,
        "order_type":"SL","product":"MIS"}
    latest["order_id"]=str(order_id)
    upsert_order(latest,bot_name,db_path)
    return str(order_id)


def reconcile_order(kite,order_id,bot_name,db_path=None):
    history=kite.order_history(order_id) or []
    if not history: raise ExecutionBlocked(f"No broker history returned for order {order_id}")
    latest=dict(history[-1]); latest["order_id"]=str(order_id)
    upsert_order(latest,bot_name,db_path)
    return latest


def cancel_order(kite,order_id):
    return kite.cancel_order(variety=kite.VARIETY_REGULAR,order_id=str(order_id))
