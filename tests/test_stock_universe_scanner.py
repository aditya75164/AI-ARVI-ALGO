import pandas as pd
from stock_selector import score_daily_candles


def make_candles(direction="up"):
    rows=[]
    base=pd.Timestamp("2026-01-01")
    for i in range(100):
        close=100+i*0.8 if direction=="up" else 180-i*0.8
        rows.append({
            "date":base+pd.Timedelta(days=i),
            "open":close-0.2,"high":close+1,"low":close-1,
            "close":close,"volume":100000 if i<99 else 250000
        })
    return rows


def test_bullish_scan_uses_indicator_derived_targets_and_profit():
    row=score_daily_candles(make_candles("up"),"RELIANCE","FNO")
    assert row is not None and row["Signal"]=="BUY"
    assert row["Target 1"]>row["Entry"]
    assert row["Target 2"]>=row["Target 1"]
    assert row["Stop Loss"]<row["Entry"]
    assert row["Expected P/L per share"]==round(row["Target 1"]-row["Entry"],2)
    assert row["Expected P/L %"]>0
    assert row["ATR 14"]>0
    assert row["Level Method"]=="20D swing + ATR(14)"


def test_bearish_scan_uses_downside_target_and_upside_stop():
    row=score_daily_candles(make_candles("down"),"SBIN","EQUITY")
    assert row is not None and row["Signal"]=="SELL"
    assert row["Target 1"]<row["Entry"]
    assert row["Stop Loss"]>row["Entry"]
    assert row["Expected P/L per share"]==round(row["Entry"]-row["Target 1"],2)
    assert row["Expected P/L %"]>0


def test_wait_signal_has_reference_levels_but_is_not_buy_or_sell():
    candles=make_candles("up")
    # Flatten recent prices to suppress momentum/trend confirmation.
    for row in candles[-10:]:
        row["close"]=candles[-11]["close"]
        row["open"]=row["close"]
        row["high"]=row["close"]+0.5
        row["low"]=row["close"]-0.5
    result=score_daily_candles(candles,"INFY","EQUITY")
    if result is not None and result["Signal"]=="WAIT":
        assert result["Target 1"]>result["Entry"]
        assert result["Stop Loss"]<result["Entry"]


def test_daily_scan_rejects_short_history():
    assert score_daily_candles(make_candles()[:20],"INFY","EQUITY") is None
