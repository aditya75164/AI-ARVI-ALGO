from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import bot_ledger
from worker_healthcheck import worker_is_healthy

IST = ZoneInfo("Asia/Kolkata")


def test_healthcheck_accepts_fresh_running_heartbeat(tmp_path):
    db = str(tmp_path / "health.db")
    now = datetime.now(IST)
    bot_ledger.init_db(db)
    bot_ledger.update_worker_heartbeat("INDEX_OPTIONS", "RUNNING", "ok", db_path=db)
    assert worker_is_healthy("INDEX_OPTIONS", db_path=db, now=now)


def test_healthcheck_rejects_stale_or_stopped_worker(tmp_path):
    db = str(tmp_path / "health.db")
    bot_ledger.init_db(db)
    old = (datetime.now(IST) - timedelta(minutes=10)).isoformat()
    with bot_ledger.connect(db) as conn:
        conn.execute(
            "INSERT INTO worker_heartbeats(worker_name,heartbeat_time,status,message,payload_json) VALUES(?,?,?,?,?)",
            ("STOCK_FNO", old, "RUNNING", "old", "{}"),
        )
    assert not worker_is_healthy("STOCK_FNO", db_path=db)
    bot_ledger.update_worker_heartbeat("STOCK_FNO", "STOPPED", "stopped", db_path=db)
    assert not worker_is_healthy("STOCK_FNO", db_path=db)


def test_healthcheck_accepts_fresh_safety_blocked_worker(tmp_path):
    db = str(tmp_path / "blocked.db")
    now = datetime.now(IST)
    bot_ledger.init_db(db)
    bot_ledger.update_worker_heartbeat(
        "INDEX_OPTIONS", "BLOCKED", "Unmanaged broker position requires manual review", db_path=db
    )
    assert worker_is_healthy("INDEX_OPTIONS", db_path=db, now=now)


def test_healthcheck_accepts_fresh_auth_required_worker(tmp_path):
    db = str(tmp_path / "auth.db")
    now = datetime.now(IST)
    bot_ledger.init_db(db)
    bot_ledger.update_worker_heartbeat(
        "INDEX_OPTIONS", "AUTH_REQUIRED", "Kite session needs renewal", db_path=db
    )
    assert worker_is_healthy("INDEX_OPTIONS", db_path=db, now=now)


def test_healthcheck_accepts_fresh_error_state_worker_process(tmp_path):
    db = str(tmp_path / "error.db")
    now = datetime.now(IST)
    bot_ledger.init_db(db)
    bot_ledger.update_worker_heartbeat(
        "INDEX_OPTIONS", "ERROR", "Temporary broker API issue", db_path=db
    )
    assert worker_is_healthy("INDEX_OPTIONS", db_path=db, now=now)
