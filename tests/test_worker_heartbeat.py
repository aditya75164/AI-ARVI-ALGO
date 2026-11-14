import bot_ledger


def test_worker_heartbeat_is_persisted_and_returned(tmp_path):
    db=str(tmp_path/"heartbeat.db")
    bot_ledger.init_db(db)
    bot_ledger.update_worker_heartbeat("INDEX_OPTIONS","RUNNING","connected",{"symbols":["NIFTY"]},db)
    data=bot_ledger.dashboard_data(db)
    assert len(data["heartbeats"])==1
    assert data["heartbeats"][0]["worker_name"]=="INDEX_OPTIONS"
    assert data["heartbeats"][0]["status"]=="RUNNING"
