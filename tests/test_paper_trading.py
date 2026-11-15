import pytest
from paper_trading import quantity_for_risk, open_paper_trade, mark_paper_trade, close_paper_trade, can_open_trade

CONTRACT={"underlying":"NIFTY","side":"CE","tradingsymbol":"NIFTY26DEC25000CE","expiry":"2026-12-31","strike":25000,"lot_size":25,"option_ltp":100.0}

def test_quantity_respects_lot_size_and_risk_budget():
    qty=quantity_for_risk(50000,1,100,2,25)
    assert qty == 250
    assert qty % 25 == 0

def test_quantity_returns_zero_if_one_lot_exceeds_risk_budget():
    assert quantity_for_risk(1000,0.25,500,5,25) == 0

def test_trade_rejects_non_lot_quantity():
    with pytest.raises(ValueError,match="lot size"):
        open_paper_trade(CONTRACT,26,3,2)

def test_target_closes_paper_trade():
    trade=open_paper_trade(CONTRACT,25,3,2)
    updated=mark_paper_trade(trade,103.0)
    assert updated["status"] == "CLOSED"
    assert updated["exit_reason"] == "TARGET"
    assert updated["realized_pnl"] == 75.0

def test_stop_loss_closes_paper_trade():
    trade=open_paper_trade(CONTRACT,25,3,2)
    updated=mark_paper_trade(trade,97.0)
    assert updated["status"] == "CLOSED"
    assert updated["exit_reason"] == "STOP_LOSS"
    assert updated["realized_pnl"] == -75.0

def test_trailing_stop_moves_up_and_closes_when_hit():
    trade=open_paper_trade(CONTRACT,25,20,10,True,2)
    updated=mark_paper_trade(trade,110)
    assert updated["stop_price"] == pytest.approx(107.8)
    closed=mark_paper_trade(updated,107.0)
    assert closed["status"] == "CLOSED"
    assert closed["exit_reason"] == "STOP_LOSS"

def test_manual_close_records_pnl():
    trade=open_paper_trade(CONTRACT,25,5,2)
    closed=close_paper_trade(trade,101)
    assert closed["status"] == "CLOSED"
    assert closed["realized_pnl"] == 25

def test_risk_guard_blocks_second_open_position():
    trade=open_paper_trade(CONTRACT,25,5,2)
    allowed,reason=can_open_trade([trade],3,1000)
    assert not allowed
    assert "open paper position" in reason


def test_backtest_costs_and_net_metrics_are_calculated():
    from paper_trading import calculate_backtest_metrics
    result={"trades":[
        {"entry":100.0,"exit":110.0,"return_pct":10.0,"pnl_per_unit":10.0},
        {"entry":100.0,"exit":95.0,"return_pct":-5.0,"pnl_per_unit":-5.0},
    ]}
    metrics=calculate_backtest_metrics(result,lot_size=25)
    assert metrics["trade_count"]==2
    assert metrics["gross_pnl"]==125.0
    assert metrics["total_charges"]>0
    assert metrics["net_pnl"]<metrics["gross_pnl"]
    assert metrics["max_drawdown"]>0
    assert metrics["profit_factor"]==2.0
    assert all("net_pnl" in trade for trade in metrics["trades"])


def test_horizon_comparison_reports_insufficient_history():
    import pandas as pd
    from paper_trading import compare_backtest_horizons
    candles=pd.DataFrame({
        "date":pd.date_range("2026-01-01",periods=40,freq="D"),
        "open":[100+i for i in range(40)],
        "high":[102+i for i in range(40)],
        "low":[99+i for i in range(40)],
        "close":[101+i for i in range(40)],
    })
    result=compare_backtest_horizons(candles,horizons=(30,60,90))
    assert result[30]["available"] is True
    assert result[60]["available"] is False
    assert result[90]["available"] is False
