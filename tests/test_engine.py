import pandas as pd
import numpy as np
import pytest
from engine import add_dtc_style_indicators, build_signal

def candles(n=120, direction="up", volume=1000):
    idx = pd.date_range("2026-01-01 09:15", periods=n, freq="3min", tz="Asia/Kolkata")
    if direction == "up":
        close = np.linspace(100, 140, n)
    elif direction == "down":
        close = np.linspace(140, 100, n)
    else:
        close = np.full(n, 100.0)
    return pd.DataFrame({
        "Open": close - 0.1, "High": close + 0.5,
        "Low": close - 0.5, "Close": close,
        "Volume": np.full(n, volume)
    }, index=idx)

def test_all_six_ema_columns_and_atr_vwap_exist():
    out = add_dtc_style_indicators(candles())
    for period in (30, 35, 40, 45, 50, 60):
        assert f"EMA_{period}" in out
    assert out["ATR_14"].notna().any()
    assert out["VWAP"].notna().all()

def test_short_history_returns_wait():
    result = build_signal(add_dtc_style_indicators(candles(40)))
    assert result["signal"] == "WAIT"
    assert result["bias"] == "INSUFFICIENT DATA"

def test_monotonic_uptrend_has_defined_rsi_and_ce_signal():
    out = add_dtc_style_indicators(candles())
    assert out["RSI_14"].iloc[-1] == pytest.approx(100.0)
    assert build_signal(out)["signal"] == "BUY CE"

def test_monotonic_downtrend_has_defined_rsi_and_pe_signal():
    out = add_dtc_style_indicators(candles(direction="down"))
    assert out["RSI_14"].iloc[-1] == pytest.approx(0.0)
    assert build_signal(out)["signal"] == "BUY PE"

def test_flat_market_does_not_create_directional_signal():
    out = add_dtc_style_indicators(candles(direction="flat"))
    assert out["RSI_14"].iloc[-1] == pytest.approx(50.0)
    assert build_signal(out)["signal"] == "WAIT"

def test_zero_volume_index_vwap_uses_documented_price_proxy():
    out = add_dtc_style_indicators(candles(volume=0))
    assert out["VWAP"].notna().all()

def test_missing_required_column_fails_clearly():
    frame = candles().drop(columns=["Volume"])
    with pytest.raises(ValueError, match="Volume"):
        add_dtc_style_indicators(frame)

def test_input_frame_is_not_mutated():
    frame = candles()
    original = frame.copy(deep=True)
    add_dtc_style_indicators(frame)
    pd.testing.assert_frame_equal(frame, original)
