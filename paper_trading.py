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


def backtest_ema_strategy(candles, fast=9, slow=21, stop_pct=2.0, target_pct=4.0,
                        trailing_pct=1.0, min_adx=18.0, min_rsi=52.0):
    """Long-option premium backtest with EMA + RSI + ADX confirmation.

    Signal is evaluated on a completed candle and filled at the next candle open.
    Existing stop/target are checked before updating a trailing stop, so a candle's
    high cannot retroactively tighten the stop used against that same candle's low.
    If stop and target are both touched in one candle, stop is assumed first.
    """
    import pandas as pd
    if candles is None or len(candles) < max(int(slow) + 20, 40):
        raise ValueError("At least 40 historical candles are required for EMA/RSI/ADX warm-up")
    if min(int(fast), int(slow)) <= 0 or int(fast) >= int(slow):
        raise ValueError("EMA fast period must be positive and smaller than slow period")
    if min(float(stop_pct), float(target_pct), float(trailing_pct)) <= 0:
        raise ValueError("Stop, target and trailing percentages must be positive")
    frame = candles.copy()
    frame.columns = [str(x).lower() for x in frame.columns]
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"]).sort_values("date").set_index("date")
    required = {"open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        raise ValueError("Historical candles must include open/high/low/close")
    for col in required:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=list(required)).sort_index()
    frame = frame[(frame["open"] > 0) & (frame["high"] > 0) & (frame["low"] > 0) & (frame["close"] > 0)]
    if len(frame) < max(int(slow) + 20, 40):
        raise ValueError("Not enough valid OHLC candles after cleaning")
    close, high, low = frame["close"], frame["high"], frame["low"]
    frame["ema_fast"] = close.ewm(span=int(fast), adjust=False).mean()
    frame["ema_slow"] = close.ewm(span=int(slow), adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, float("nan"))
    frame["rsi"] = 100 - (100 / (1 + rs))
    frame.loc[(loss == 0) & (gain > 0), "rsi"] = 100.0
    frame.loc[(gain == 0) & (loss > 0), "rsi"] = 0.0
    prev_close = close.shift(1)
    tr = pd.concat([(high-low), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    plus_di = 100 * plus_dm.ewm(alpha=1/14, adjust=False, min_periods=14).mean() / atr.replace(0, float("nan"))
    minus_di = 100 * minus_dm.ewm(alpha=1/14, adjust=False, min_periods=14).mean() / atr.replace(0, float("nan"))
    dx = 100 * (plus_di-minus_di).abs() / (plus_di+minus_di).replace(0, float("nan"))
    frame["adx"] = dx.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    frame["cross_up"] = (frame["ema_fast"] > frame["ema_slow"]) & (frame["ema_fast"].shift(1) <= frame["ema_slow"].shift(1))
    frame["entry_ok"] = frame["cross_up"] & (frame["rsi"] >= float(min_rsi)) & (frame["adx"] >= float(min_adx))
    trades = []
    position = None
    for i in range(1, len(frame)-1):
        row = frame.iloc[i]
        nxt = frame.iloc[i+1]
        if position is None:
            if bool(row["entry_ok"]):
                entry = float(nxt["open"])
                if entry > 0:
                    position = {"entry": entry, "entry_index": i+1,
                                "stop": entry*(1-float(stop_pct)/100),
                                "target": entry*(1+float(target_pct)/100),
                                "peak": entry}
            continue
        # The current candle is the first full candle after entry. Test the
        # stop that existed before this candle; update trailing only afterwards.
        o, h, l = float(row["open"]), float(row["high"]), float(row["low"])
        old_stop = float(position["stop"])
        exit_price = None
        reason = None
        if o <= old_stop:
            exit_price, reason = o, "GAP_STOP"
        elif o >= position["target"]:
            exit_price, reason = position["target"], "TARGET"
        elif l <= old_stop:
            exit_price, reason = old_stop, "STOP_OR_TRAIL"
        elif h >= position["target"]:
            exit_price, reason = position["target"], "TARGET"
        elif not bool(row["ema_fast"] > row["ema_slow"]):
            exit_price, reason = float(nxt["open"]), "EMA_EXIT"
        if exit_price is None:
            position["peak"] = max(float(position["peak"]), h)
            new_trail = position["peak"] * (1-float(trailing_pct)/100)
            position["stop"] = max(old_stop, new_trail)
        if exit_price is not None and exit_price > 0:
            pnl = exit_price-position["entry"]
            trades.append({"entry_time": str(frame.index[position["entry_index"]]),
                           "exit_time": str(frame.index[i]), "entry": position["entry"],
                           "exit": exit_price, "return_pct": pnl/position["entry"]*100,
                           "pnl_per_unit": pnl, "reason": reason})
            position = None
    if position is not None:
        last = float(frame.iloc[-1]["close"])
        pnl = last-position["entry"]
        trades.append({"entry_time": str(frame.index[position["entry_index"]]),
                       "exit_time": str(frame.index[-1]), "entry": position["entry"],
                       "exit": last, "return_pct": pnl/position["entry"]*100,
                       "pnl_per_unit": pnl, "reason": "END_OF_DATA"})
    wins = sum(t["pnl_per_unit"] > 0 for t in trades)
    net = sum(t["pnl_per_unit"] for t in trades)
    return {"trades": trades, "trade_count": len(trades), "wins": wins,
            "losses": len(trades)-wins,
            "win_rate_pct": round(wins/len(trades)*100, 2) if trades else 0.0,
            "net_points_per_unit": round(net, 4),
            "indicator_rule": f"EMA {fast}/{slow} bullish crossover + RSI(14) >= {min_rsi} + ADX(14) >= {min_adx}",
            "note": "Historical option-premium simulation only; excludes brokerage, taxes, slippage, bid-ask spread and execution delay."}


def calculate_backtest_metrics(result, lot_size=1, brokerage_per_order=20.0,
                               exchange_txn_rate=0.0003553, stt_sell_rate=0.0015,
                               stamp_buy_rate=0.00003, sebi_rate=0.000001,
                               gst_rate=0.18, slippage_per_unit=0.0):
    """Calculate approximate NSE option-buy trade costs and closed-trade metrics.

    Zerodha-style defaults: ₹20 per executed order; NSE option transaction
    charge 0.03553%; option sell-side STT 0.15%; buy-side stamp duty 0.003%;
    SEBI ₹10/crore; GST 18% on brokerage + exchange + SEBI charges.
    Change defaults for a different broker/contract note. Slippage is optional.
    """
    trades=list((result or {}).get("trades") or [])
    lot=max(1,int(lot_size))
    enriched=[]
    gross_wins=0.0
    gross_losses=0.0
    cumulative=0.0
    peak=0.0
    max_drawdown=0.0
    total_costs=0.0
    for trade in trades:
        entry=float(trade.get("entry") or 0)
        exit_price=float(trade.get("exit") or 0)
        if entry<=0 or exit_price<=0:
            continue
        buy_turnover=entry*lot
        sell_turnover=exit_price*lot
        turnover=buy_turnover+sell_turnover
        brokerage=2.0*float(brokerage_per_order)
        exchange=turnover*float(exchange_txn_rate)
        sebi=turnover*float(sebi_rate)
        gst=(brokerage+exchange+sebi)*float(gst_rate)
        stt=sell_turnover*float(stt_sell_rate)
        stamp=buy_turnover*float(stamp_buy_rate)
        slippage=2.0*lot*float(slippage_per_unit)
        charges=brokerage+exchange+sebi+gst+stt+stamp+slippage
        gross=(exit_price-entry)*lot
        net=gross-charges
        item=dict(trade)
        item.update({"quantity":lot,"gross_pnl":round(gross,2),
                     "brokerage":round(brokerage,2),"exchange_charges":round(exchange,2),
                     "stt":round(stt,2),"stamp_duty":round(stamp,2),
                     "sebi_charges":round(sebi,4),"gst":round(gst,2),
                     "slippage":round(slippage,2),"total_charges":round(charges,2),
                     "net_pnl":round(net,2),
                     "net_return_pct":round(net/(buy_turnover+charges)*100,3)})
        enriched.append(item)
        total_costs+=charges
        if gross>0: gross_wins+=gross
        elif gross<0: gross_losses+=abs(gross)
        cumulative+=net
        peak=max(peak,cumulative)
        max_drawdown=max(max_drawdown,peak-cumulative)
    wins=sum(t["net_pnl"]>0 for t in enriched)
    losses=sum(t["net_pnl"]<0 for t in enriched)
    net_total=sum(t["net_pnl"] for t in enriched)
    profit_factor=(gross_wins/gross_losses if gross_losses>0 else (float("inf") if gross_wins>0 else 0.0))
    return {
        "trades":enriched,"trade_count":len(enriched),"wins":wins,"losses":losses,
        "win_rate_pct":round(wins/len(enriched)*100,2) if enriched else 0.0,
        "gross_pnl":round(sum(t["gross_pnl"] for t in enriched),2),
        "total_charges":round(total_costs,2),"net_pnl":round(net_total,2),
        "max_drawdown":round(max_drawdown,2),
        "profit_factor":round(profit_factor,3) if profit_factor!=float("inf") else float("inf"),
        "note":"Estimated Zerodha NSE option charges; excludes market impact and any unconfigured slippage."
    }


def compare_backtest_horizons(candles, horizons=(30,60,90), **strategy_kwargs):
    """Run the same strategy over the last N available trading sessions."""
    import pandas as pd
    frame=candles.copy()
    frame.columns=[str(x).lower() for x in frame.columns]
    if "date" in frame.columns:
        frame["date"]=pd.to_datetime(frame["date"],errors="coerce")
        frame=frame.dropna(subset=["date"]).sort_values("date").set_index("date")
    frame=frame.sort_index()
    output={}
    for days in horizons:
        requested=int(days)
        available=len(frame)
        if available<requested:
            output[requested]={"available":False,"sessions_available":available,
                               "reason":f"Only {available} trading sessions available; {requested} required"}
            continue
        sample=frame.tail(requested)
        if len(sample)<30:
            output[requested]={"available":False,"sessions_available":len(sample),
                               "reason":f"Only {len(sample)} trading sessions available; minimum 30 required"}
            continue
        try:
            raw=backtest_ema_strategy(sample,**strategy_kwargs)
            output[int(days)]={"available":True,"sessions_available":len(sample),**raw}
        except Exception as exc:
            output[int(days)]={"available":False,"sessions_available":len(sample),"reason":str(exc)}
    return output


def backtest_directional_underlying(candles, fast=9, slow=21, stop_pct=2.0,
                                    target_pct=4.0, trailing_pct=1.0,
                                    min_adx=18.0, rsi_buy_min=52.0, rsi_sell_max=48.0):
    """Long/short daily EMA crossover with RSI/ADX trend confirmation.

    Signals use completed daily candles and enter at the next session open.
    Stops are evaluated using the stop known before the current candle; a new
    trailing stop is calculated only after the candle survives. When stop and
    target are both touched, the conservative stop-first assumption is used.
    """
    import pandas as pd
    if candles is None or len(candles) < max(int(slow)+20, 40):
        raise ValueError("At least 40 daily OHLC candles are required for EMA/RSI/ADX warm-up")
    if min(int(fast), int(slow)) <= 0 or int(fast) >= int(slow):
        raise ValueError("EMA fast period must be positive and smaller than slow period")
    if min(float(stop_pct), float(target_pct), float(trailing_pct)) <= 0:
        raise ValueError("Stop, target and trailing percentages must be positive")
    frame = candles.copy()
    frame.columns = [str(x).lower() for x in frame.columns]
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"]).sort_values("date").set_index("date")
    required = {"open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        raise ValueError("Underlying candles must include open/high/low/close")
    for col in required:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=list(required)).sort_index()
    frame = frame[(frame["open"] > 0) & (frame["high"] > 0) & (frame["low"] > 0) & (frame["close"] > 0)]
    if len(frame) < max(int(slow)+20, 40):
        raise ValueError("Not enough valid daily OHLC candles after cleaning")
    close, high, low = frame["close"], frame["high"], frame["low"]
    frame["ema_fast"] = close.ewm(span=int(fast), adjust=False).mean()
    frame["ema_slow"] = close.ewm(span=int(slow), adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, float("nan"))
    frame["rsi"] = 100 - (100 / (1 + rs))
    frame.loc[(loss == 0) & (gain > 0), "rsi"] = 100.0
    frame.loc[(gain == 0) & (loss > 0), "rsi"] = 0.0
    prev_close = close.shift(1)
    tr = pd.concat([(high-low), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    up, down = high.diff(), -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    plus_di = 100 * plus_dm.ewm(alpha=1/14, adjust=False, min_periods=14).mean() / atr.replace(0, float("nan"))
    minus_di = 100 * minus_dm.ewm(alpha=1/14, adjust=False, min_periods=14).mean() / atr.replace(0, float("nan"))
    dx = 100 * (plus_di-minus_di).abs() / (plus_di+minus_di).replace(0, float("nan"))
    frame["adx"] = dx.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    frame["bull_cross"] = (frame["ema_fast"] > frame["ema_slow"]) & (frame["ema_fast"].shift(1) <= frame["ema_slow"].shift(1))
    frame["bear_cross"] = (frame["ema_fast"] < frame["ema_slow"]) & (frame["ema_fast"].shift(1) >= frame["ema_slow"].shift(1))
    frame["buy_signal"] = frame["bull_cross"] & (frame["rsi"] >= float(rsi_buy_min)) & (frame["adx"] >= float(min_adx)) & (plus_di > minus_di)
    frame["sell_signal"] = frame["bear_cross"] & (frame["rsi"] <= float(rsi_sell_max)) & (frame["adx"] >= float(min_adx)) & (minus_di > plus_di)
    trades = []
    position = None
    for i in range(1, len(frame)-1):
        row, nxt = frame.iloc[i], frame.iloc[i+1]
        if position is None:
            signal = "BUY" if bool(row["buy_signal"]) else "SELL" if bool(row["sell_signal"]) else None
            if signal:
                entry = float(nxt["open"])
                if entry > 0:
                    direction = 1 if signal == "BUY" else -1
                    position = {"direction": direction, "signal": signal, "entry": entry,
                                "entry_index": i+1,
                                "stop": entry*(1-float(stop_pct)/100) if direction == 1 else entry*(1+float(stop_pct)/100),
                                "target": entry*(1+float(target_pct)/100) if direction == 1 else entry*(1-float(target_pct)/100),
                                "peak": entry, "trough": entry}
            continue
        o, h, l = float(row["open"]), float(row["high"]), float(row["low"])
        direction = position["direction"]
        old_stop = float(position["stop"])
        target = float(position["target"])
        exit_price = None
        reason = None
        if direction == 1:
            if o <= old_stop: exit_price, reason = o, "GAP_STOP"
            elif o >= target: exit_price, reason = target, "TARGET"
            elif l <= old_stop: exit_price, reason = old_stop, "STOP_OR_TRAIL"
            elif h >= target: exit_price, reason = target, "TARGET"
            elif bool(row["sell_signal"]): exit_price, reason = float(nxt["open"]), "REVERSE_SIGNAL"
            else:
                position["peak"] = max(float(position["peak"]), h)
                position["stop"] = max(old_stop, position["peak"]*(1-float(trailing_pct)/100))
        else:
            if o >= old_stop: exit_price, reason = o, "GAP_STOP"
            elif o <= target: exit_price, reason = target, "TARGET"
            elif h >= old_stop: exit_price, reason = old_stop, "STOP_OR_TRAIL"
            elif l <= target: exit_price, reason = target, "TARGET"
            elif bool(row["buy_signal"]): exit_price, reason = float(nxt["open"]), "REVERSE_SIGNAL"
            else:
                position["trough"] = min(float(position["trough"]), l)
                position["stop"] = min(old_stop, position["trough"]*(1+float(trailing_pct)/100))
        if exit_price is not None and exit_price > 0:
            pnl = (exit_price-position["entry"])*direction
            trades.append({"direction": position["signal"],
                           "entry_time": str(frame.index[position["entry_index"]]),
                           "exit_time": str(frame.index[i]), "entry": position["entry"],
                           "exit": exit_price, "return_pct": pnl/position["entry"]*100,
                           "pnl_per_unit": pnl, "reason": reason})
            position = None
    if position is not None:
        last = float(frame.iloc[-1]["close"])
        direction = position["direction"]
        pnl = (last-position["entry"])*direction
        trades.append({"direction": position["signal"],
                       "entry_time": str(frame.index[position["entry_index"]]),
                       "exit_time": str(frame.index[-1]), "entry": position["entry"],
                       "exit": last, "return_pct": pnl/position["entry"]*100,
                       "pnl_per_unit": pnl, "reason": "END_OF_DATA"})
    wins = sum(t["pnl_per_unit"] > 0 for t in trades)
    return {"trades": trades, "trade_count": len(trades), "wins": wins,
            "losses": len(trades)-wins,
            "win_rate_pct": round(wins/len(trades)*100, 2) if trades else 0.0,
            "gross_points_per_share": round(sum(t["pnl_per_unit"] for t in trades), 4),
            "indicator_rule": f"EMA {fast}/{slow} cross + RSI(14) confirmation + ADX(14) >= {min_adx} + directional DI",
            "note": "Underlying directional simulation; BUY is long and SELL is short. No option premium is inferred."}


def calculate_equity_backtest_metrics(result, brokerage_per_order=20.0,
                                      exchange_txn_rate=0.000297, stt_sell_rate=0.00025,
                                      stamp_buy_rate=0.00003, sebi_rate=0.000001,
                                      gst_rate=0.18, quantity=1):
    """Approximate NSE intraday-equity costs for one share/quantity per trade."""
    trades=list((result or {}).get("trades") or [])
    qty=max(1,int(quantity)); enriched=[]; gross_wins=0.0; gross_losses=0.0
    cumulative=0.0; peak=0.0; max_dd=0.0; total_charges=0.0
    for trade in trades:
        entry=float(trade.get("entry") or 0); exit_price=float(trade.get("exit") or 0)
        if entry<=0 or exit_price<=0: continue
        direction=1 if trade.get("direction","BUY")=="BUY" else -1
        buy_turnover=(entry if direction==1 else exit_price)*qty
        sell_turnover=(exit_price if direction==1 else entry)*qty
        turnover=buy_turnover+sell_turnover
        brokerage=2*float(brokerage_per_order)
        exchange=turnover*float(exchange_txn_rate); sebi=turnover*float(sebi_rate)
        gst=(brokerage+exchange+sebi)*float(gst_rate)
        stt=sell_turnover*float(stt_sell_rate); stamp=buy_turnover*float(stamp_buy_rate)
        charges=brokerage+exchange+sebi+gst+stt+stamp
        gross=(exit_price-entry)*direction*qty; net=gross-charges
        item=dict(trade); item.update({"quantity":qty,"gross_pnl":round(gross,2),
            "total_charges":round(charges,2),"net_pnl":round(net,2),
            "net_return_pct":round(net/max(buy_turnover,0.01)*100,3)})
        enriched.append(item); total_charges+=charges
        if gross>0: gross_wins+=gross
        elif gross<0: gross_losses+=abs(gross)
        cumulative+=net; peak=max(peak,cumulative); max_dd=max(max_dd,peak-cumulative)
    wins=sum(t["net_pnl"]>0 for t in enriched)
    pf=gross_wins/gross_losses if gross_losses else (float("inf") if gross_wins else 0.0)
    return {"trades":enriched,"trade_count":len(enriched),"wins":wins,
            "losses":sum(t["net_pnl"]<0 for t in enriched),
            "win_rate_pct":round(wins/len(enriched)*100,2) if enriched else 0.0,
            "gross_pnl":round(sum(t["gross_pnl"] for t in enriched),2),
            "total_charges":round(total_charges,2),"net_pnl":round(sum(t["net_pnl"] for t in enriched),2),
            "max_drawdown":round(max_dd,2),
            "profit_factor":round(pf,3) if pf!=float("inf") else float("inf"),
            "note":"Estimated intraday-equity charges; quantity defaults to one share. Confirm exact taxes with broker contract note."}


def compare_underlying_horizons(candles,horizons=(30,60,90),**strategy_kwargs):
    """Compare underlying strategy on exact trailing trading-session windows."""
    import pandas as pd
    frame=candles.copy(); frame.columns=[str(x).lower() for x in frame.columns]
    if "date" in frame.columns:
        frame["date"]=pd.to_datetime(frame["date"],errors="coerce")
        frame=frame.dropna(subset=["date"]).sort_values("date")
    output={}
    for horizon in horizons:
        requested=int(horizon); available=len(frame)
        if available<requested:
            output[requested]={"available":False,"sessions_available":available,
                "reason":f"Only {available} daily candles available; {requested} required"}
            continue
        sample=frame.tail(requested)
        try:
            result=backtest_directional_underlying(sample,**strategy_kwargs)
            output[requested]={"available":True,"sessions_available":len(sample),**result}
        except Exception as exc:
            output[requested]={"available":False,"sessions_available":len(sample),"reason":str(exc)}
    return output
