"""Stock universe scanners for F&O underlyings and NSE cash equities.

Selection is based on Kite instrument masters, quote turnover and historical daily
candles. It never requires a matching news headline to return a technically valid stock.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
from engine import add_dtc_style_indicators

IST=ZoneInfo("Asia/Kolkata")


def _universe(kite, market):
    cash=pd.DataFrame(kite.instruments("NSE"))
    if cash.empty or not {"tradingsymbol","instrument_token","segment"}.issubset(cash.columns):
        raise RuntimeError("NSE instrument master is unavailable")
    cash=cash[cash["segment"].astype(str).eq("NSE")].copy()
    cash=cash.drop_duplicates("tradingsymbol")
    if market=="EQUITY":
        if "instrument_type" in cash:
            cash=cash[cash["instrument_type"].astype(str).isin(["EQ",""])]
        return [(str(r.tradingsymbol),int(r.instrument_token)) for r in cash.itertuples()]
    fno=pd.DataFrame(kite.instruments("NFO"))
    if fno.empty or not {"name","instrument_type","expiry"}.issubset(fno.columns):
        raise RuntimeError("NFO instrument master is unavailable")
    today=datetime.now(IST).date()
    fut=fno[fno["instrument_type"].astype(str).eq("FUT")].copy()
    fut["expiry"]=pd.to_datetime(fut["expiry"],errors="coerce").dt.date
    fut=fut[fut["expiry"]>=today].sort_values("expiry").drop_duplicates("name")
    token_map={str(r.tradingsymbol):int(r.instrument_token) for r in cash.itertuples()}
    return [(str(name),token_map[str(name)]) for name in fut["name"] if str(name) in token_map]


def _quote_turnover(kite, universe, batch_size=150):
    keys=[f"NSE:{symbol}" for symbol,_ in universe]
    rows=[]
    for i in range(0,len(keys),batch_size):
        try:
            quotes=kite.quote(keys[i:i+batch_size])
        except Exception:
            continue
        for symbol,token in universe[i:i+batch_size]:
            q=quotes.get(f"NSE:{symbol}",{})
            price=float(q.get("last_price") or 0)
            volume=int(q.get("volume") or 0)
            if price>0 and volume>0:
                rows.append((symbol,token,price,volume,price*volume))
    return sorted(rows,key=lambda r:r[4],reverse=True)


def score_daily_candles(candles, symbol, market, target_pct=10.0, stop_pct=5.0):
    if not candles:
        return None
    frame=pd.DataFrame(candles)
    if not {"date","open","high","low","close","volume"}.issubset(frame.columns):
        return None
    frame=frame.set_index("date").sort_index().rename(columns={
        "open":"Open","high":"High","low":"Low","close":"Close","volume":"Volume"
    })
    if len(frame)<65:
        return None
    d=add_dtc_style_indicators(frame)
    row=d.iloc[-1]
    required=["EMA_30","EMA_35","EMA_40","EMA_45","EMA_50","EMA_60","RSI_14","RELATIVE_VOLUME","VWAP"]
    if any(pd.isna(row.get(col)) for col in required):
        return None
    close=float(row["Close"])
    momentum=(close/float(d["Close"].iloc[-6])-1)*100 if float(d["Close"].iloc[-6]) else 0
    relvol=float(row["RELATIVE_VOLUME"])
    rsi=float(row["RSI_14"])
    bull=bool(row["EMA_BULL"] and close>float(row["VWAP"]) and rsi>=52 and momentum>0)
    bear=bool(row["EMA_BEAR"] and close<float(row["VWAP"]) and rsi<=48 and momentum<0)
    if bull:
        signal="BUY"
        target=close*(1+target_pct/100)
        stop=close*(1-stop_pct/100)
    elif bear:
        signal="SELL"
        target=close*(1-target_pct/100)
        stop=close*(1+stop_pct/100)
    else:
        signal="WAIT"
        target=close*(1+target_pct/100)
        stop=close*(1-stop_pct/100)
    score=0
    score+=30 if bull or bear else 0
    score+=min(25,max(0,(relvol-1)*12.5))
    score+=min(20,abs(momentum)*3)
    score+=10 if (52<=rsi<=75 or 25<=rsi<=48) else 0
    score+=15 if abs(momentum)>=1 and relvol>=1.5 else 0
    return {
        "Market":market,"Stock":symbol,"Price":round(close,2),
        "Signal":signal,"Trend":str(row["TREND_LABEL"]),
        "Score":round(min(100,score),1),"RSI":round(rsi,1),
        "Relative Volume":round(relvol,2),"Momentum %":round(momentum,2),
        "Volume":int(row["Volume"]),"Entry":round(close,2),
        "Target":round(target,2),"Stop Loss":round(stop,2),
        "Candle Date":str(pd.Timestamp(d.index[-1]).date()),
        "Data Source":"Kite historical daily candles"
    }


def scan_stock_universe(kite, market="FNO", max_candidates=35, target_pct=10.0, stop_pct=5.0):
    if market not in ("FNO","EQUITY"):
        raise ValueError("market must be FNO or EQUITY")
    universe=_universe(kite,market)
    turnover=_quote_turnover(kite,universe)
    # Never substitute an arbitrary alphabetical slice when quote turnover is absent.
    # That would present random instruments as selected stocks.
    if not turnover:
        return pd.DataFrame(),{
            "universe":len(universe),"quote_ranked":0,
            "history_checked":0,"selected":0,
            "data_source":"Kite historical daily candles",
            "reason":"No quote turnover available; scan withheld to avoid arbitrary picks"
        }
    candidates=turnover[:max_candidates]
    now=datetime.now(IST)
    start=now-timedelta(days=180)
    picks=[]
    for symbol,token,price,volume,value in candidates:
        try:
            candles=kite.historical_data(token,start,now,"day")
            row=score_daily_candles(candles,symbol,market,target_pct,stop_pct)
            if row:
                row["Turnover ₹"]=int(value)
                picks.append(row)
        except Exception:
            continue
    picks.sort(key=lambda r:(r["Signal"]=="BUY",r["Score"],r["Relative Volume"]),reverse=True)
    return pd.DataFrame(picks),{
        "universe":len(universe),"quote_ranked":len(turnover),
        "history_checked":len(candidates),"selected":len(picks),
        "data_source":"Kite historical daily candles"
    }


# Backward-compatible wrapper for the old dashboard entry point.
def scan_fno_stock_candidates(kite,max_stocks=25):
    frame,_=scan_stock_universe(kite,"FNO",max_candidates=max_stocks)
    return frame.to_dict("records")
