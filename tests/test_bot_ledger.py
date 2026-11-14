import sqlite3
from bot_ledger import init_db, record_event, upsert_order, dashboard_data, save_equity_snapshot


def test_ledger_initialises_and_records_event(tmp_path):
    db=str(tmp_path/"ledger.db")
    init_db(db)
    record_event("NIFTY_5M","SCAN","WAIT","No signal",{"score":50},db)
    data=dashboard_data(db)
    assert len(data["events"])==1
    assert data["events"][0]["bot_name"]=="NIFTY_5M"
    assert data["events"][0]["status"]=="WAIT"


def test_order_upsert_updates_status_without_duplicate(tmp_path):
    db=str(tmp_path/"ledger.db")
    init_db(db)
    order={"order_id":"123","tradingsymbol":"NIFTY26NOV25000CE","exchange":"NFO",
           "transaction_type":"BUY","quantity":25,"order_type":"MARKET","product":"MIS",
           "status":"OPEN","average_price":0,"filled_quantity":0}
    upsert_order(order,"NIFTY_BOT",db)
    order.update({"status":"COMPLETE","average_price":120.5,"filled_quantity":25})
    upsert_order(order,"NIFTY_BOT",db)
    rows=dashboard_data(db)["orders"]
    assert len(rows)==1
    assert rows[0]["status"]=="COMPLETE"
    assert rows[0]["average_price"]==120.5


def test_equity_snapshots_store_realised_and_unrealised_values(tmp_path):
    db=str(tmp_path/"ledger.db")
    init_db(db)
    save_equity_snapshot("BANKNIFTY_BOT",1200,-200,{"source":"broker"},db)
    row=dashboard_data(db)["snapshots"][0]
    assert row["realised_pnl"]==1200
    assert row["unrealised_pnl"]==-200
    assert row["net_pnl"]==1000
