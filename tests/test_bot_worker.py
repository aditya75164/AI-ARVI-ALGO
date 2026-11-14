import bot_ledger
from bot_worker import run_scan_cycle


class BrokenBroker:
    def positions(self):
        raise RuntimeError("broker unavailable")


def test_worker_fails_closed_when_broker_risk_data_unavailable(tmp_path,monkeypatch):
    monkeypatch.setattr(bot_ledger,"DEFAULT_DB",str(tmp_path/"worker.db"))
    result=run_scan_cycle(BrokenBroker(),{
        "symbols":["NIFTY","BANKNIFTY"],"interval":"5minute",
        "max_open_positions":1,"daily_loss_limit":1500,
        "max_risk_per_trade":500,"max_lots":1
    })
    assert result==[{"status":"RISK_DATA_UNAVAILABLE"}]
    events=bot_ledger.dashboard_data()["events"]
    assert events[0]["event_type"]=="BROKER_RISK_READ"
    assert events[0]["status"]=="ERROR"
