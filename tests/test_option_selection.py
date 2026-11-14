import pandas as pd
import pytest
import kite_adapter as adapter

class FakeKite:
    def instruments(self, exchange):
        assert exchange == "NFO"
        return [
            {"name":"NIFTY","instrument_type":"CE","expiry":"2026-12-31","strike":25000,"lot_size":75,"tradingsymbol":"NIFTY26DEC25000CE","instrument_token":111},
            {"name":"NIFTY","instrument_type":"CE","expiry":"2026-12-31","strike":25100,"lot_size":75,"tradingsymbol":"NIFTY26DEC25100CE","instrument_token":112},
            {"name":"NIFTY","instrument_type":"PE","expiry":"2026-12-31","strike":25000,"lot_size":75,"tradingsymbol":"NIFTY26DEC25000PE","instrument_token":113},
            {"name":"BANKNIFTY","instrument_type":"CE","expiry":"2026-12-31","strike":55000,"lot_size":30,"tradingsymbol":"BANKNIFTY26DEC55000CE","instrument_token":211},
        ]
    def ltp(self, keys):
        return {keys[0]: {"last_price":25020}}
    def quote(self, keys):
        return {keys[0]: {"last_price":120.0,"volume":100000,"oi":500000,
            "depth":{"buy":[{"price":119.8}],"sell":[{"price":120.2}]},
            "timestamp":"2026-11-14T10:00:00+05:30"}}

def test_select_option_contract_returns_nearest_matching_contract(monkeypatch):
    monkeypatch.setattr(adapter, "get_index_ltp", lambda kite, underlying: 25020.0)
    result = adapter.select_option_contract(FakeKite(), "NIFTY", "CE", "ATM")
    assert result["tradingsymbol"] == "NIFTY26DEC25000CE"
    assert result["lot_size"] == 75
    assert result["option_ltp"] == 120.0
    assert result["spread_pct"] == pytest.approx(0.333333, rel=1e-3)

def test_select_option_contract_rejects_invalid_side():
    with pytest.raises(ValueError):
        adapter.select_option_contract(FakeKite(), "NIFTY", "XX")

def test_select_option_contract_requires_quote(monkeypatch):
    class NoQuote(FakeKite):
        def quote(self, keys):
            return {}
    monkeypatch.setattr(adapter, "get_index_ltp", lambda kite, underlying: 25020.0)
    with pytest.raises(RuntimeError, match="No live quote"):
        adapter.select_option_contract(NoQuote(), "NIFTY", "CE")
