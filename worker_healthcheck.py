"""Container health check based on the worker's persisted heartbeat."""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from bot_ledger import dashboard_data

IST = ZoneInfo("Asia/Kolkata")


def worker_is_healthy(worker_name, max_age_seconds=180, db_path=None, now=None):
    rows = dashboard_data(db_path).get("heartbeats", [])
    heartbeat = next((row for row in rows if row.get("worker_name") == worker_name), None)
    if not heartbeat or heartbeat.get("status") != "RUNNING":
        return False
    try:
        stamp = datetime.fromisoformat(heartbeat["heartbeat_time"])
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=IST)
        current = now or datetime.now(IST)
        age = (current - stamp).total_seconds()
        return -30 <= age <= max_age_seconds
    except (KeyError, TypeError, ValueError):
        return False


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if not name or not worker_is_healthy(name, int(os.getenv("ARVI_HEALTH_MAX_AGE_SECONDS", "180"))):
        raise SystemExit(1)
