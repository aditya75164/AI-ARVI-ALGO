import pandas as pd
import pytest
import kite_adapter as adapter

def test_missing_credentials_returns_no_client(monkeypatch):
    monkeypatch.delenv("KITE_API_KEY", raising=False)
    monkeypatch.delenv("KITE_ACCESS_TOKEN", raising=False)
    # Secrets may be absent in the test environment.
    assert adapter.kite_client() is None

def test_invalid_symbol_and_interval_rejected_before_api_call():
    class FakeKite:
        def historical_data(self, *args, **kwargs):
            raise AssertionError("API must not be called")
    with pytest.raises(ValueError, match="Unsupported"):
        adapter.fetch_index_candles(FakeKite(), "SENSEX", "3minute")
    with pytest.raises(ValueError, match="Unsupported"):
        adapter.fetch_index_candles(FakeKite(), "NIFTY", "1minute")

def test_fetch_index_candles_normalizes_broker_columns(monkeypatch):
    class FakeKite:
        def historical_data(self, token, start, end, interval):
            assert token == adapter.INDEX_TOKENS["NIFTY"]
            assert interval == "3minute"
            return [{"date": pd.Timestamp("2026-01-01 09:15", tz="Asia/Kolkata"),
                     "open": 100, "high": 102, "low": 99, "close": 101, "volume": 10}]
    result = adapter.fetch_index_candles(FakeKite(), "NIFTY", "3minute")
    assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert result.iloc[0]["Close"] == 101

def test_empty_historical_data_returns_empty_frame():
    class FakeKite:
        def historical_data(self, *args, **kwargs):
            return []
    assert adapter.fetch_index_candles(FakeKite(), "BANKNIFTY", "5minute").empty
