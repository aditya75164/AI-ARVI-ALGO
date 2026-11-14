"""Persistent SQLite ledger for simulated paper trades; never places broker orders."""
import json, os, sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

IST=ZoneInfo("Asia/Kolkata")
DB=os.getenv("ARVI_DB_PATH","arvi_local.db")

def _connect(db_path=None):
    conn=sqlite3.connect(db_path or DB,timeout=20)
    conn.row_factory=sqlite3.Row
    return conn

def init_paper_db(db_path=None):
    with _connect(db_path) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS paper_trades(
            trade_id TEXT PRIMARY KEY, status TEXT NOT NULL, opened_at TEXT NOT NULL,
            closed_at TEXT, tradingsymbol TEXT NOT NULL, payload_json TEXT NOT NULL)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_paper_status ON paper_trades(status,opened_at)")

def save_paper_trade(trade,db_path=None):
    init_paper_db(db_path)
    with _connect(db_path) as c:
        c.execute("""INSERT INTO paper_trades(trade_id,status,opened_at,closed_at,tradingsymbol,payload_json)
        VALUES(?,?,?,?,?,?) ON CONFLICT(trade_id) DO UPDATE SET status=excluded.status,
        closed_at=excluded.closed_at,payload_json=excluded.payload_json""",
        (trade["id"],trade["status"],trade["opened_at"],trade.get("closed_at"),
         trade["tradingsymbol"],json.dumps(trade,default=str)))

def load_paper_trades(db_path=None):
    init_paper_db(db_path)
    with _connect(db_path) as c:
        rows=c.execute("SELECT payload_json FROM paper_trades ORDER BY opened_at DESC").fetchall()
    return [json.loads(r["payload_json"]) for r in rows]

def paper_summary(trades):
    closed=[t for t in trades if t.get("status")=="CLOSED"]
    opened=[t for t in trades if t.get("status")=="OPEN"]
    return {"open":len(opened),"closed":len(closed),
            "realized_pnl":sum(float(t.get("realized_pnl") or 0) for t in closed),
            "unrealized_pnl":sum(float(t.get("pnl") or 0) for t in opened),
            "wins":sum(float(t.get("realized_pnl") or 0)>0 for t in closed),
            "losses":sum(float(t.get("realized_pnl") or 0)<0 for t in closed)}
