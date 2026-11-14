from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from order_executor import validate_order_intent, ExecutionBlocked

IST=ZoneInfo("Asia/Kolkata")
BASE={"exchange":"NFO","tradingsymbol":"NIFTY26NOV25000CE","transaction_type":"BUY",
      "quantity":25,"lot_size":25,"entry_price":100,"stop_price":85,
      "target_price":130,"quote_age_seconds":1}


def test_order_intent_passes_all_risk_checks_when_live_enabled(monkeypatch):
    monkeypatch.setenv("ARVI_LIVE_TRADING","YES")
    checked=validate_order_intent(BASE, max_risk_rupees=500, max_lots=1,
        market_now=datetime(2026,11,16,10,0,tzinfo=IST))
    assert checked["risk_rupees"]==375
    assert checked["quantity"]==25


def test_live_mode_off_blocks_entry(monkeypatch):
    monkeypatch.delenv("ARVI_LIVE_TRADING",raising=False)
    with pytest.raises(ExecutionBlocked,match="Live trading disabled"):
        validate_order_intent(BASE,500,1,datetime(2026,11,16,10,0,tzinfo=IST))


@pytest.mark.parametrize("changes,reason",[
    ({"quantity":26},"whole number of lots"),
    ({"exchange":"BSE"},"Exchange is not enabled"),
    ({"stop_price":105},"require 0 < stop < entry < target"),
    ({"entry_price":200},"require 0 < stop < entry < target"),
    ({"quantity":50},"maximum lots"),
])
def test_invalid_intents_are_blocked(monkeypatch,changes,reason):
    monkeypatch.setenv("ARVI_LIVE_TRADING","YES")
    intent={**BASE,**changes}
    with pytest.raises(ExecutionBlocked,match=reason):
        validate_order_intent(intent,500,1,datetime(2026,11,16,10,0,tzinfo=IST))


def test_outside_entry_window_blocked(monkeypatch):
    monkeypatch.setenv("ARVI_LIVE_TRADING","YES")
    with pytest.raises(ExecutionBlocked,match="Entry window is closed"):
        validate_order_intent(BASE,500,1,datetime(2026,11,16,15,25,tzinfo=IST))


def test_risk_budget_exceeded_blocked(monkeypatch):
    monkeypatch.setenv("ARVI_LIVE_TRADING","YES")
    with pytest.raises(ExecutionBlocked,match="exceeds per-trade limit"):
        validate_order_intent(BASE,100,1,datetime(2026,11,16,10,0,tzinfo=IST))
