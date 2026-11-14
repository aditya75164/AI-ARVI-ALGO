import pandas as pd
import kite_adapter as adapter

class WatchKite:
    def instruments(self, exchange):
        return [
            {"name":"AAA","instrument_type":"PE","expiry":"2026-11-23","strike":95,"lot_size":100,"tradingsymbol":"AAA95PE","instrument_token":1},
            {"name":"AAA","instrument_type":"PE","expiry":"2026-11-23","strike":100,"lot_size":100,"tradingsymbol":"AAA100PE","instrument_token":2},
            {"name":"AAA","instrument_type":"PE","expiry":"2026-11-23","strike":105,"lot_size":100,"tradingsymbol":"AAA105PE","instrument_token":3},
            {"name":"BBB","instrument_type":"PE","expiry":"2026-11-23","strike":195,"lot_size":50,"tradingsymbol":"BBB195PE","instrument_token":4},
            {"name":"BBB","instrument_type":"PE","expiry":"2026-11-23","strike":200,"lot_size":50,"tradingsymbol":"BBB200PE","instrument_token":5},
        ]
    def ltp(self, keys):
        return {key:{"last_price":100 if key.endswith(":AAA") else 200} for key in keys}
    def quote(self, keys):
        result={}
        for key in keys:
            sym=key.split(":")[1]
            oi={"AAA95PE":1000,"AAA100PE":9000,"AAA105PE":2000,"BBB195PE":500,"BBB200PE":7000}[sym]
            result[key]={"last_price":50,"volume":10000,"oi":oi,"net_change":1.0,
                "ohlc":{"close":49},"timestamp":pd.Timestamp.now(tz="Asia/Kolkata").isoformat()}
        return result

def test_watchlist_returns_one_highest_oi_premium_per_underlying(monkeypatch):
    result, stats=adapter.build_stock_option_watchlist(WatchKite(),"NFO","PE")
    assert len(result)==2
    assert set(result["Stock"])=={"AAA","BBB"}
    assert result.set_index("Stock").loc["AAA","Option"]=="AAA100PE"
    assert result.set_index("Stock").loc["BBB","Option"]=="BBB200PE"
    assert stats["selected"]==2

def test_watchlist_calculates_entry_target_stop_and_signal(monkeypatch):
    result,_=adapter.build_stock_option_watchlist(WatchKite(),"NFO","PE",target_pct=10,stop_pct=5)
    row=result.iloc[0]
    assert row["Entry"]==50
    assert row["Target"]==55
    assert row["Stop Loss"]==47.5
    assert row["Signal"]=="BUY"
