from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import uuid4

IST = ZoneInfo("Asia/Kolkata")

def quantity_for_risk(capital, risk_pct, entry, stop_pct, lot_size):
    if min(capital, risk_pct, entry, stop_pct, lot_size) <= 0:
        raise ValueError("Capital, risk, entry, stop and lot size must be positive")
    risk_budget = float(capital) * float(risk_pct) / 100
    risk_per_unit = float(entry) * float(stop_pct) / 100
    raw_units = int(risk_budget // risk_per_unit)
    qty = (raw_units // int(lot_size)) * int(lot_size)
    return max(0, qty)

def open_paper_trade(contract, quantity, target_pct, stop_pct, trailing_enabled=False, trailing_pct=1.0):
    if quantity <= 0 or quantity % int(contract["lot_size"]) != 0:
        raise ValueError("Quantity must be a positive multiple of the option lot size")
    entry = float(contract["option_ltp"])
    if entry <= 0 or target_pct <= 0 or stop_pct <= 0:
        raise ValueError("Entry, target and stop percentages must be positive")
    now = datetime.now(IST).isoformat()
    return {
        "id": str(uuid4()), "status": "OPEN", "mode": "PAPER",
        "underlying": contract["underlying"], "side": contract["side"],
        "tradingsymbol": contract["tradingsymbol"], "expiry": contract["expiry"],
        "strike": float(contract["strike"]), "lot_size": int(contract["lot_size"]),
        "quantity": int(quantity), "entry_price": entry, "ltp": entry,
        "target_pct": float(target_pct), "stop_pct": float(stop_pct),
        "target_price": entry * (1 + float(target_pct)/100),
        "initial_stop": entry * (1 - float(stop_pct)/100),
        "stop_price": entry * (1 - float(stop_pct)/100),
        "trailing_enabled": bool(trailing_enabled), "trailing_pct": float(trailing_pct),
        "peak_price": entry, "pnl": 0.0, "realized_pnl": 0.0,
        "opened_at": now, "closed_at": None, "exit_reason": None
    }

def mark_paper_trade(trade, ltp):
    if trade.get("status") != "OPEN":
        return trade
    price = float(ltp)
    if price <= 0:
        raise ValueError("LTP must be positive")
    trade = dict(trade)
    trade["ltp"] = price
    trade["peak_price"] = max(float(trade["peak_price"]), price)
    if trade["trailing_enabled"]:
        trailing_stop = trade["peak_price"] * (1 - trade["trailing_pct"]/100)
        trade["stop_price"] = max(float(trade["initial_stop"]), trailing_stop)
    trade["pnl"] = (price - trade["entry_price"]) * trade["quantity"]
    reason = "TARGET" if price >= trade["target_price"] else "STOP_LOSS" if price <= trade["stop_price"] else None
    if reason:
        trade["status"] = "CLOSED"
        trade["exit_reason"] = reason
        trade["closed_at"] = datetime.now(IST).isoformat()
        trade["realized_pnl"] = trade["pnl"]
    return trade

def close_paper_trade(trade, ltp, reason="MANUAL"):
    if trade.get("status") != "OPEN":
        return trade
    trade = dict(trade)
    price = float(ltp)
    if price <= 0:
        raise ValueError("Exit price must be positive")
    trade["ltp"] = price
    trade["pnl"] = (price - trade["entry_price"]) * trade["quantity"]
    trade["realized_pnl"] = trade["pnl"]
    trade["status"] = "CLOSED"
    trade["exit_reason"] = reason
    trade["closed_at"] = datetime.now(IST).isoformat()
    return trade

def daily_realized_pnl(trades):
    today = datetime.now(IST).date()
    total = 0.0
    for trade in trades:
        if trade.get("status") == "CLOSED" and trade.get("closed_at"):
            closed = datetime.fromisoformat(trade["closed_at"])
            if closed.astimezone(IST).date() == today:
                total += float(trade.get("realized_pnl") or 0)
    return total

def can_open_trade(trades, max_trades, daily_loss_limit):
    today = datetime.now(IST).date()
    closed_today = [
        t for t in trades if t.get("status") == "CLOSED" and t.get("closed_at")
        and datetime.fromisoformat(t["closed_at"]).astimezone(IST).date() == today
    ]
    opened_today = [
        t for t in trades if t.get("opened_at")
        and datetime.fromisoformat(t["opened_at"]).astimezone(IST).date() == today
    ]
    pnl = daily_realized_pnl(trades)
    if len(opened_today) >= int(max_trades):
        return False, "Maximum trades for today reached."
    if pnl <= -abs(float(daily_loss_limit)):
        return False, "Daily realized loss limit reached. New paper trades are blocked."
    if any(t.get("status") == "OPEN" for t in trades):
        return False, "An open paper position already exists. Manage it before opening another."
    return True, "Risk checks passed."


def backtest_ema_strategy(candles, fast=9, slow=21, stop_pct=2.0, target_pct=4.0, trailing_pct=1.0):
    """Long-premium EMA cross backtest on historical option candles.
    Signal is evaluated at candle close; entry/exit fill is next candle open.
    No brokerage, taxes, slippage or latency are included.
    """
    import pandas as pd
    if candles is None or len(candles) < max(slow + 2, 30):
        raise ValueError("At least 30 historical candles are required")
    frame = candles.copy()
    frame.columns = [str(x).lower() for x in frame.columns]
    required = {"open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        raise ValueError("Historical candles must include open/high/low/close")
    frame["ema_fast"] = frame["close"].ewm(span=int(fast), adjust=False).mean()
    frame["ema_slow"] = frame["close"].ewm(span=int(slow), adjust=False).mean()
    frame["cross_up"] = (frame["ema_fast"] > frame["ema_slow"]) & (frame["ema_fast"].shift(1) <= frame["ema_slow"].shift(1))
    trades=[]
    position=None
    for i in range(1,len(frame)-1):
        row=frame.iloc[i]
        nxt=frame.iloc[i+1]
        if position is None and bool(row["cross_up"]):
            entry=float(nxt["open"])
            if entry>0:
                position={"entry":entry,"entry_index":i+1,"stop":entry*(1-stop_pct/100),
                          "target":entry*(1+target_pct/100),"peak":entry}
            continue
        if position is not None:
            high=float(row["high"]); low=float(row["low"])
            position["peak"]=max(position["peak"],high)
            position["stop"]=max(position["stop"],position["peak"]*(1-trailing_pct/100))
            exit_price=None; reason=None
            # Conservative same-candle rule: if stop and target both touched, assume stop first.
            if low <= position["stop"]:
                exit_price=position["stop"]; reason="STOP_OR_TRAIL"
            elif high >= position["target"]:
                exit_price=position["target"]; reason="TARGET"
            elif not bool(row["ema_fast"] > row["ema_slow"]):
                exit_price=float(nxt["open"]); reason="EMA_EXIT"
            if exit_price is not None and exit_price>0:
                pnl=exit_price-position["entry"]
                trades.append({"entry_time":str(frame.index[position["entry_index"]]),
                               "exit_time":str(frame.index[i]),"entry":position["entry"],
                               "exit":exit_price,"return_pct":pnl/position["entry"]*100,
                               "pnl_per_unit":pnl,"reason":reason})
                position=None
    if position is not None:
        last=float(frame.iloc[-1]["close"])
        pnl=last-position["entry"]
        trades.append({"entry_time":str(frame.index[position["entry_index"]]),
                       "exit_time":str(frame.index[-1]),"entry":position["entry"],
                       "exit":last,"return_pct":pnl/position["entry"]*100,
                       "pnl_per_unit":pnl,"reason":"END_OF_DATA"})
    wins=sum(t["pnl_per_unit"]>0 for t in trades)
    net=sum(t["pnl_per_unit"] for t in trades)
    return {"trades":trades,"trade_count":len(trades),"wins":wins,
            "losses":len(trades)-wins,"win_rate_pct":(wins/len(trades)*100 if trades else 0),
            "net_points_per_unit":net,
            "note":"Historical option-premium simulation only; excludes brokerage, taxes, slippage, bid-ask spread and execution delay."}
