import pandas as pd
from market_briefing import build_index_scenarios


def candles():
    dates=pd.date_range("2026-01-01",periods=35,freq="B")
    rows=[]
    for i,date in enumerate(dates):
        close=25000+i*10
        rows.append({"date":date,"Open":close-5,"High":close+50,"Low":close-50,"Close":close,"Volume":0})
    return pd.DataFrame(rows).set_index("date")


def test_index_scenarios_have_conditional_triggers_and_two_targets():
    result=build_index_scenarios(candles(),"NIFTY")
    assert result["bullish"]["trigger"]>result["close"]
    assert result["bullish"]["target1"]>result["bullish"]["trigger"]
    assert result["bullish"]["target2"]>result["bullish"]["target1"]
    assert result["bearish"]["trigger"]<result["close"]
    assert result["bearish"]["target1"]<result["bearish"]["trigger"]
    assert result["bearish"]["target2"]<result["bearish"]["target1"]
    assert result["method"]=="Prior 20-session swing levels + ATR(14)"


def test_short_index_history_rejected():
    try:
        build_index_scenarios(candles().head(10),"BANKNIFTY")
        assert False
    except ValueError as exc:
        assert "25 daily candles" in str(exc)
