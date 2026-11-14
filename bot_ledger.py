"""Persistent trade ledger for the AI ARVI ALGO bot control centre.

This module records broker-reported orders/trades and strategy runs. It never
creates simulated fills. SQLite is suitable for local development; production
should use a persistent volume or managed PostgreSQL database.
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

IST=ZoneInfo("Asia/Kolkata")
DEFAULT_DB=os.getenv("ARVI_DB_PATH","arvi_bot.db")


@contextmanager
def connect(db_path=None):
    path=db_path or DEFAULT_DB
    conn=sqlite3.connect(path,timeout=20)
    conn.row_factory=sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path=None):
    with connect(db_path) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS bot_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          event_time TEXT NOT NULL, bot_name TEXT NOT NULL,
          event_type TEXT NOT NULL, status TEXT NOT NULL,
          message TEXT, payload_json TEXT
        );
        CREATE TABLE IF NOT EXISTS broker_orders(
          order_id TEXT PRIMARY KEY, parent_order_id TEXT, bot_name TEXT NOT NULL,
          tradingsymbol TEXT NOT NULL, exchange TEXT NOT NULL, transaction_type TEXT NOT NULL,
          quantity INTEGER NOT NULL, order_type TEXT NOT NULL, product TEXT NOT NULL,
          status TEXT NOT NULL, average_price REAL NOT NULL DEFAULT 0,
          filled_quantity INTEGER NOT NULL DEFAULT 0, placed_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, payload_json TEXT
        );
        CREATE TABLE IF NOT EXISTS broker_trades(
          trade_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, bot_name TEXT NOT NULL,
          tradingsymbol TEXT NOT NULL, exchange TEXT NOT NULL, transaction_type TEXT NOT NULL,
          quantity INTEGER NOT NULL, price REAL NOT NULL, trade_time TEXT NOT NULL,
          payload_json TEXT
        );
        CREATE TABLE IF NOT EXISTS bot_positions(
          position_key TEXT PRIMARY KEY, bot_name TEXT NOT NULL, tradingsymbol TEXT NOT NULL,
          exchange TEXT NOT NULL, quantity INTEGER NOT NULL, average_price REAL NOT NULL,
          stop_order_id TEXT, target_price REAL, status TEXT NOT NULL,
          opened_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT
        );
        CREATE TABLE IF NOT EXISTS worker_heartbeats(
          worker_name TEXT PRIMARY KEY, heartbeat_time TEXT NOT NULL,
          status TEXT NOT NULL, message TEXT, payload_json TEXT
        );
        CREATE TABLE IF NOT EXISTS equity_snapshots(
          id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_time TEXT NOT NULL,
          bot_name TEXT NOT NULL, realised_pnl REAL NOT NULL, unrealised_pnl REAL NOT NULL,
          net_pnl REAL NOT NULL, payload_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_time ON bot_events(event_time);
        CREATE INDEX IF NOT EXISTS idx_orders_time ON broker_orders(placed_at);
        CREATE INDEX IF NOT EXISTS idx_trades_time ON broker_trades(trade_time);
        CREATE INDEX IF NOT EXISTS idx_snapshots_time ON equity_snapshots(snapshot_time);
        """)


def record_event(bot_name,event_type,status,message="",payload=None,db_path=None):
    now=datetime.now(IST).isoformat()
    with connect(db_path) as c:
        c.execute("INSERT INTO bot_events(event_time,bot_name,event_type,status,message,payload_json) VALUES(?,?,?,?,?,?)",
                  (now,bot_name,event_type,status,message,json.dumps(payload or {},default=str)))


def upsert_order(order,bot_name,db_path=None):
    now=datetime.now(IST).isoformat()
    with connect(db_path) as c:
        c.execute("""INSERT INTO broker_orders(order_id,parent_order_id,bot_name,tradingsymbol,exchange,transaction_type,
        quantity,order_type,product,status,average_price,filled_quantity,placed_at,updated_at,payload_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(order_id) DO UPDATE SET status=excluded.status,average_price=excluded.average_price,
        filled_quantity=excluded.filled_quantity,updated_at=excluded.updated_at,payload_json=excluded.payload_json""",
        (str(order["order_id"]),str(order.get("parent_order_id") or ""),bot_name,
         order.get("tradingsymbol",""),order.get("exchange",""),order.get("transaction_type",""),
         int(order.get("quantity") or 0),order.get("order_type",""),order.get("product","MIS"),
         order.get("status","UNKNOWN"),float(order.get("average_price") or 0),
         int(order.get("filled_quantity") or 0),order.get("order_timestamp",now),now,
         json.dumps(order,default=str)))


def sync_broker_history(kite,bot_name="Manual/Kite",db_path=None):
    """Import broker orders and tradebook as reported by Kite."""
    orders=kite.orders() or []
    trades=kite.trades() or []
    for order in orders:
        upsert_order(order,bot_name,db_path)
    with connect(db_path) as c:
        for trade in trades:
            trade_id=str(trade.get("trade_id") or trade.get("exchange_order_id") or "")
            if not trade_id: continue
            c.execute("""INSERT OR REPLACE INTO broker_trades
            (trade_id,order_id,bot_name,tradingsymbol,exchange,transaction_type,quantity,price,trade_time,payload_json)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (trade_id,str(trade.get("order_id") or ""),bot_name,trade.get("tradingsymbol",""),
             trade.get("exchange",""),trade.get("transaction_type",""),int(trade.get("quantity") or 0),
             float(trade.get("average_price") or trade.get("price") or 0),
             str(trade.get("fill_timestamp") or trade.get("exchange_timestamp") or datetime.now(IST).isoformat()),
             json.dumps(trade,default=str)))
    return {"orders":len(orders),"trades":len(trades)}


def upsert_position(position,db_path=None):
    now=datetime.now(IST).isoformat()
    with connect(db_path) as c:
        c.execute("""INSERT INTO bot_positions(position_key,bot_name,tradingsymbol,exchange,quantity,average_price,
        stop_order_id,target_price,status,opened_at,updated_at,payload_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(position_key) DO UPDATE SET quantity=excluded.quantity,average_price=excluded.average_price,
        stop_order_id=excluded.stop_order_id,target_price=excluded.target_price,status=excluded.status,
        updated_at=excluded.updated_at,payload_json=excluded.payload_json""",
        (str(position['position_key']),position['bot_name'],position['tradingsymbol'],position['exchange'],
         int(position['quantity']),float(position['average_price']),str(position.get('stop_order_id') or ''),
         float(position['target_price']),position.get('status','OPEN'),position.get('opened_at',now),now,
         json.dumps(position,default=str)))


def close_position(position_key,db_path=None):
    with connect(db_path) as c:
        c.execute("UPDATE bot_positions SET status='CLOSED',quantity=0,updated_at=? WHERE position_key=?",
                  (datetime.now(IST).isoformat(),str(position_key)))

def dashboard_data(db_path=None):
    with connect(db_path) as c:
        events=[dict(r) for r in c.execute("SELECT * FROM bot_events ORDER BY id DESC LIMIT 100")]
        orders=[dict(r) for r in c.execute("SELECT * FROM broker_orders ORDER BY placed_at DESC LIMIT 100")]
        trades=[dict(r) for r in c.execute("SELECT * FROM broker_trades ORDER BY trade_time DESC LIMIT 250")]
        positions=[dict(r) for r in c.execute("SELECT * FROM bot_positions WHERE status='OPEN' ORDER BY opened_at DESC")]
        snapshots=[dict(r) for r in c.execute("SELECT * FROM equity_snapshots ORDER BY snapshot_time")]
        heartbeats=[dict(r) for r in c.execute("SELECT * FROM worker_heartbeats ORDER BY worker_name")]
    # Broker tradebook may contain both entry and exit fills. Net realised P&L is
    # computed from broker positions by the caller; do not infer closed P&L from fills alone.
    return {"events":events,"orders":orders,"trades":trades,"positions":positions,"snapshots":snapshots,"heartbeats":heartbeats}



def update_worker_heartbeat(worker_name,status="RUNNING",message="",payload=None,db_path=None):
    now=datetime.now(IST).isoformat()
    with connect(db_path) as c:
        c.execute("""INSERT INTO worker_heartbeats(worker_name,heartbeat_time,status,message,payload_json)
        VALUES(?,?,?,?,?) ON CONFLICT(worker_name) DO UPDATE SET
        heartbeat_time=excluded.heartbeat_time,status=excluded.status,
        message=excluded.message,payload_json=excluded.payload_json""",
        (worker_name,now,status,message,json.dumps(payload or {},default=str)))


def save_equity_snapshot(bot_name,realised,unrealised,payload=None,db_path=None):
    now=datetime.now(IST).isoformat()
    with connect(db_path) as c:
        c.execute("INSERT INTO equity_snapshots(snapshot_time,bot_name,realised_pnl,unrealised_pnl,net_pnl,payload_json) VALUES(?,?,?,?,?,?)",
                  (now,bot_name,float(realised),float(unrealised),float(realised)+float(unrealised),json.dumps(payload or {},default=str)))
