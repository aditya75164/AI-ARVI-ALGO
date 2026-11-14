import json
import nse_data_provider as nse

class FakeResponse:
    def __init__(self,payload): self.payload=payload
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self): return json.dumps(self.payload).encode()

def test_nse_feed_normalizes_quote_fields(monkeypatch):
    monkeypatch.setattr(nse,"_setting",lambda key: {"NSE_DATA_API_URL":"https://vendor.example/quotes","NSE_DATA_API_TOKEN":"secret"}.get(key))
    monkeypatch.setattr(nse,"urlopen",lambda request,timeout: FakeResponse({"data":[
        {"symbol":"reliance","last_price":"1234.5","volume":"1000","oi":"200","timestamp":"2026-11-14T10:00:00+05:30"}
    ]}))
    result=nse.fetch_nse_quotes(["RELIANCE"])
    assert result.iloc[0]["symbol"]=="RELIANCE"
    assert result.iloc[0]["last_price"]==1234.5
    assert result.iloc[0]["volume"]==1000
    assert result.iloc[0]["data_source"]=="NSE licensed feed"

def test_nse_feed_requires_authorized_configuration(monkeypatch):
    monkeypatch.setattr(nse,"_setting",lambda key: None)
    try:
        nse.fetch_nse_quotes(["RELIANCE"])
        assert False,"expected configuration error"
    except RuntimeError as exc:
        assert "NSE licensed feed is not configured" in str(exc)

def test_nse_feed_filters_unrequested_symbols(monkeypatch):
    monkeypatch.setattr(nse,"_setting",lambda key: {"NSE_DATA_API_URL":"https://vendor.example/quotes","NSE_DATA_API_TOKEN":"secret"}.get(key))
    monkeypatch.setattr(nse,"urlopen",lambda request,timeout: FakeResponse([
        {"symbol":"RELIANCE","last_price":100},{"symbol":"SBIN","last_price":200}
    ]))
    result=nse.fetch_nse_quotes(["SBIN"])
    assert result["symbol"].tolist()==["SBIN"]
