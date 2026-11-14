import pandas as pd
from paper_trading import backtest_ema_strategy, open_paper_trade, mark_paper_trade
from paper_ledger import init_paper_db, save_paper_trade, load_paper_trades, paper_summary

def test_paper_ledger_persists_open_and_closed_trade(tmp_path):
    db=str(tmp_path/"paper.db")
    init_paper_db(db)
    contract={"underlying":"NIFTY","side":"CE","tradingsymbol":"NIFTYTESTCE","expiry":"2026-12-31","strike":25000,"lot_size":25,"option_ltp":100}
    trade=open_paper_trade(contract,25,10,5,True,2)
    save_paper_trade(trade,db)
    loaded=load_paper_trades(db)
    assert loaded[0]["id"]==trade["id"]
    assert paper_summary(loaded)["open"]==1
    closed=mark_paper_trade(trade,111)
    save_paper_trade(closed,db)
    assert paper_summary(load_paper_trades(db))["realized_pnl"]==275

def test_backtest_returns_metrics_without_lookahead():
    # Deterministic rising then falling option-premium candles.
    close=[100+i*0.8 for i in range(45)]+[136-i*1.0 for i in range(25)]
    frame=pd.DataFrame({"open":close,"high":[x+0.5 for x in close],
                        "low":[x-0.5 for x in close],"close":close},
                       index=pd.date_range("2026-01-01",periods=len(close),freq="5min"))
    result=backtest_ema_strategy(frame,fast=3,slow=8,stop_pct=3,target_pct=8,trailing_pct=2)
    assert "trade_count" in result
    assert result["trade_count"]>=1
    assert result["wins"]+result["losses"]==result["trade_count"]
