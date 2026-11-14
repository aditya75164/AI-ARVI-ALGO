import bot_ledger
from startup_reconciliation import reconcile_startup_state


class FakeKite:
    def __init__(self, positions):
        self._positions = positions

    def orders(self):
        return []

    def trades(self):
        return []

    def positions(self):
        return self._positions


def test_reconciliation_blocks_untracked_broker_position(tmp_path):
    db = str(tmp_path / "recovery.db")
    bot_ledger.init_db(db)
    kite = FakeKite({"net": [{
        "exchange": "NFO", "tradingsymbol": "NIFTY26NOV25000CE", "quantity": 25
    }]})
    result = reconcile_startup_state(kite, db_path=db)
    assert result["safe_for_new_entries"] is False
    assert result["unmanaged_positions"][0]["quantity"] == 25
    assert bot_ledger.dashboard_data(db)["events"][0]["event_type"] == "STARTUP_RECONCILIATION"


def test_reconciliation_allows_when_no_untracked_positions(tmp_path):
    db = str(tmp_path / "recovery.db")
    bot_ledger.init_db(db)
    bot_ledger.upsert_position({
        "position_key": "entry-1", "bot_name": "NIFTY_5M",
        "tradingsymbol": "NIFTY26NOV25000CE", "exchange": "NFO",
        "quantity": 25, "average_price": 100, "target_price": 130,
        "stop_order_id": "stop-1", "status": "OPEN"
    }, db)
    kite = FakeKite({"net": [{
        "exchange": "NFO", "tradingsymbol": "NIFTY26NOV25000CE", "quantity": 25
    }]})
    result = reconcile_startup_state(kite, db_path=db)
    assert result["safe_for_new_entries"] is True
