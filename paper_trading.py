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
