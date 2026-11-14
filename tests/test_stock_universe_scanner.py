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


def test_daily_fno_or_equity_scan_returns_actionable_fields():
    row=score_daily_candles(make_candles("up"),"RELIANCE","FNO",10,5)
    assert row is not None
    assert row["Signal"]=="BUY"
    assert row["Target"]==round(row["Entry"]*1.10,2)
    assert row["Stop Loss"]==round(row["Entry"]*0.95,2)
    assert row["Data Source"]=="Kite historical daily candles"


def test_daily_scan_identifies_bearish_trend():
    row=score_daily_candles(make_candles("down"),"SBIN","EQUITY",10,5)
    assert row is not None
    assert row["Signal"]=="SELL"
    assert row["Target"]<row["Entry"]
    assert row["Stop Loss"]>row["Entry"]


def test_daily_scan_rejects_short_history():
    assert score_daily_candles(make_candles()[:20],"INFY","EQUITY") is None
