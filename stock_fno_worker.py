"""Stock F&O candidate worker. This worker is signal-only and never submits orders."""
import json
import logging
import os
import signal
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from kiteconnect import KiteConnect
from stock_selector import scan_stock_universe
from option_enrichment import enrich_fno_option_premiums
from bot_ledger import init_db, record_event, update_worker_heartbeat

IST=ZoneInfo("Asia/Kolkata")
STOP=False
LOG=logging.getLogger("arvi-stock-fno")
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"),format="%(asctime)s %(levelname)s %(message)s")


def create_kite():
    key=os.getenv("KITE_API_KEY"); token=os.getenv("KITE_ACCESS_TOKEN")
    if not key or not token: raise RuntimeError("KITE_API_KEY and KITE_ACCESS_TOKEN are required")
    kite=KiteConnect(api_key=key); kite.set_access_token(token); kite.profile()
    return kite


def scan_cycle(kite,max_stocks=25):
    init_db()
    stocks,stats=scan_stock_universe(kite,"FNO",max_candidates=max_stocks)
    options=enrich_fno_option_premiums(kite,stocks,max_stocks=max_stocks) if not stocks.empty else None
    count=0 if options is None else len(options)
    record_event("STOCK_FNO","SCAN_COMPLETE","OK",
        "Stock F&O scan completed; candidates are signal-only and no orders were placed",
        {"stats":stats,"candidates":0 if options is None else options.to_dict("records")})
    update_worker_heartbeat("STOCK_FNO","RUNNING","Last stock F&O candidate scan completed",
        {"stats":stats,"candidate_count":count,"execution":"DISABLED"})
    return stocks,options,stats


def _stop(*_):
    global STOP
    STOP=True


def main():
    signal.signal(signal.SIGTERM,_stop); signal.signal(signal.SIGINT,_stop)
    kite=create_kite()
    interval=max(300,int(os.getenv("ARVI_STOCK_SCAN_SECONDS","900")))
    limit=max(10,min(100,int(os.getenv("ARVI_STOCK_MAX_STOCKS","25"))))
    init_db(); update_worker_heartbeat("STOCK_FNO","RUNNING","Worker connected; order execution disabled")
    while not STOP:
        now=datetime.now(IST)
        if now.weekday()<5 and "09:20"<=now.strftime("%H:%M")<="15:20":
            try:
                stocks,options,stats=scan_cycle(kite,limit)
                LOG.info("Stock F&O scan: %s | option candidates=%s",stats,0 if options is None else len(options))
            except Exception as exc:
                LOG.exception("Stock F&O scan failed")
                update_worker_heartbeat("STOCK_FNO","ERROR",str(exc))
                record_event("STOCK_FNO","SCAN_ERROR","ERROR",str(exc))
        time.sleep(interval)
    update_worker_heartbeat("STOCK_FNO","STOPPED","Worker received shutdown signal")


if __name__=="__main__":
    main()
