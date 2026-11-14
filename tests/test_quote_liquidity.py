import pytest
from kite_adapter import validate_option_liquidity

def test_rejects_zero_volume_and_oi():
    result=validate_option_liquidity({"last_price":100,"volume":0,"oi":0,"bid":99,"ask":101,"age_seconds":5})
    assert not result["eligible"]
    assert "zero traded volume" in result["reasons"]
    assert "zero open interest" in result["reasons"]

def test_rejects_missing_depth():
    result=validate_option_liquidity({"last_price":100,"volume":1000,"oi":5000,"bid":0,"ask":0,"age_seconds":5})
    assert not result["eligible"]
    assert any("bid-ask" in reason for reason in result["reasons"])

def test_rejects_wide_spread():
    result=validate_option_liquidity({"last_price":100,"volume":1000,"oi":5000,"bid":90,"ask":110,"age_seconds":5})
    assert not result["eligible"]
    assert result["spread_pct"] == 20

def test_rejects_missing_timestamp():
    result=validate_option_liquidity({"last_price":100,"volume":1000,"oi":5000,"bid":99,"ask":100,"age_seconds":None})
    assert not result["eligible"]
    assert "quote timestamp unavailable" in result["reasons"]

def test_accepts_valid_quote():
    result=validate_option_liquidity({"last_price":100,"volume":1000,"oi":5000,"bid":99.5,"ask":100.5,"age_seconds":10})
    assert result["eligible"]

def test_rejects_quote_older_than_three_minutes():
    result=validate_option_liquidity({"last_price":100,"volume":1000,"oi":5000,"bid":99.5,"ask":100.5,"age_seconds":181})
    assert not result["eligible"]
    assert any("stale" in reason for reason in result["reasons"])

def test_rejects_friday_quote_on_saturday():
    result=validate_option_liquidity({"last_price":100,"volume":1000,"oi":5000,"bid":99.5,"ask":100.5,"age_seconds":18*60*60})
    assert not result["eligible"]

def test_last_session_reference_quote_can_pass_relaxed_age_window():
    result=validate_option_liquidity({"last_price":100,"volume":1000,"oi":5000,"bid":99.5,"ask":100.5,"age_seconds":18*60*60},max_age_seconds=4*24*60*60)
    assert result["eligible"]

def test_same_quote_is_rejected_by_live_age_window():
    result=validate_option_liquidity({"last_price":100,"volume":1000,"oi":5000,"bid":99.5,"ask":100.5,"age_seconds":181},max_age_seconds=180)
    assert not result["eligible"]
