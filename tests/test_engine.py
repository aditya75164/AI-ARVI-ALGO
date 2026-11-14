import pandas as pd
import numpy as np
from engine import add_dtc_style_indicators, build_signal

def candles(n=100):
    idx=pd.date_range("2026-01-01 09:15",periods=n,freq="3min",tz="Asia/Kolkata")
    close=np.linspace(100,130,n)
    return pd.DataFrame({"Open":close-.1,"High":close+.5,"Low":close-.5,"Close":close,"Volume":np.full(n,1000)},index=idx)

def test_indicators_create_six_ema_columns():
    result=add_dtc_style_indicators(candles())
    for p in (30,35,40,45,50,60):
        assert f"EMA_{p}" in result
    assert "ATR_14" in result and "VWAP" in result

def test_short_history_waits():
    result=build_signal(add_dtc_style_indicators(candles(40)))
    assert result["signal"]=="WAIT"
    assert result["bias"]=="INSUFFICIENT DATA"

def test_signal_is_only_allowed_direction_or_wait():
    result=build_signal(add_dtc_style_indicators(candles()))
    assert result["signal"] in {"BUY CE","BUY PE","WAIT"}
