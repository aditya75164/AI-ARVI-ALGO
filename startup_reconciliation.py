"""Broker/local position reconciliation helpers.

A broker position without a matching persisted bot position is treated as
unmanaged. The worker blocks fresh entries rather than guessing its stop/target.
"""
from bot_ledger import dashboard_data, record_event, sync_broker_history


def reconcile_startup_state(kite, bot_name="RISK_MANAGER", db_path=None):
    """Sync broker history and compare open NFO positions with the local ledger."""
    sync_result = sync_broker_history(kite, bot_name="Kite/Startup", db_path=db_path)
    broker = kite.positions() or {}
    net = broker.get("net") or []
    active = [
        p for p in net
        if str(p.get("exchange", "")).upper() == "NFO"
        and int(p.get("quantity") or 0) != 0
    ]
    local = dashboard_data(db_path).get("positions", [])
    tracked = {
        (str(p.get("exchange", "")).upper(), str(p.get("tradingsymbol", "")).upper())
        for p in local
    }
    unmanaged = [
        p for p in active
        if (str(p.get("exchange", "")).upper(), str(p.get("tradingsymbol", "")).upper()) not in tracked
    ]
    result = {
        "broker_positions": len(active),
        "tracked_positions": len(local),
        "unmanaged_positions": unmanaged,
        "safe_for_new_entries": len(unmanaged) == 0,
        "synced_orders": sync_result["orders"],
        "synced_trades": sync_result["trades"],
    }
    if unmanaged:
        record_event(
            bot_name, "STARTUP_RECONCILIATION", "BLOCKED",
            "Unmanaged broker NFO position detected; new entries are blocked. Review broker position and protective orders manually.",
            {"unmanaged_positions": unmanaged}, db_path,
        )
    else:
        record_event(
            bot_name, "STARTUP_RECONCILIATION", "OK",
            "Broker positions reconciled with persisted bot positions",
            {k: v for k, v in result.items() if k != "unmanaged_positions"}, db_path,
        )
    return result
