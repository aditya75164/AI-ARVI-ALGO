"""Stock universe scanners with indicator-derived price objectives."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
from engine import add_dtc_style_indicators
from kite_adapter import quote_timestamp_age_seconds

IST=ZoneInfo("Asia/Kolkata")


def headline_score(company_name,symbol,headlines):
    """Small transparent keyword match helper retained for legacy reports."""
    tokens={str(company_name).lower(),str(symbol).lower()}
    matches=[]
    for headline in headlines or []:
        text=str(headline)
        low=text.lower()
        if any(token and token in low for token in tokens):
            matches.append(text)
    if not matches:
        return 0,"No matching headline found"
    positive=("profit growth","record profit","strong results","upgrade","growth","surge","beats estimates","expansion")
    negative=("loss","downgrade","fraud","default","misses estimates","decline","weak results")
    score=0
    for item in matches:
        low=item.lower()
        score+=sum(1 for word in positive if word in low)
        score-=sum(1 for word in negative if word in low)
    return score,matches[0]


def score_stock(frame,company_name,symbol,headlines=None):
    """Compatibility wrapper for legacy callers; delegates to daily candle scorer."""
    if frame is None or len(frame)<65:
        return None
    data=frame.copy()
    if isinstance(data.index,pd.DatetimeIndex):
        data=data.reset_index().rename(columns={"index":"date"})
    elif "date" not in data.columns:
        data=data.reset_index().rename(columns={"index":"date"})
    records=[]
    for row in data.to_dict("records"):
        records.append({str(k).lower():v for k,v in row.items()})
    result=score_daily_candles(records,symbol,"EQUITY")
    if result:
        hs,_=headline_score(company_name,symbol,headlines or [])
        result["Headline Score"]=hs
    return result


def quote_is_usable(quote,max_age_days=4):
    """Legacy quote quality check for the watchlist tests."""
    reasons=[]
    ltp=float(quote.get("last_price") or 0)
    volume=int(quote.get("volume") or 0)
    if ltp<=0: reasons.append("invalid price")
    if volume<=0: reasons.append("volume is zero")
    depth=quote.get("depth") or {}
    bid=float(((depth.get("buy") or [{}])[0]).get("price") or 0)
    ask=float(((depth.get("sell") or [{}])[0]).get("price") or 0)
    if bid<=0 or ask<=0 or ask<bid: reasons.append("bid-ask depth unavailable")
    stamp=quote.get("timestamp") or quote.get("last_trade_time")
    if not stamp:
        reasons.append("quote timestamp unavailable")
    else:
        age=quote_timestamp_age_seconds(stamp)
        if age is None or age>max_age_days*86400:
            reasons.append(f"quote older than {max_age_days} days")
    return not reasons,"; ".join(reasons)


def _universe(kite, market):
    cash=pd.DataFrame(kite.instruments("NSE"))
    if cash.empty or not {"tradingsymbol","instrument_token","segment"}.issubset(cash.columns):
        raise RuntimeError("NSE instrument master is unavailable")
    cash=cash[cash["segment"].astype(str).eq("NSE")].copy().drop_duplicates("tradingsymbol")
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
        try: quotes=kite.quote(keys[i:i+batch_size])
        except Exception: continue
        for symbol,token in universe[i:i+batch_size]:
            q=quotes.get(f"NSE:{symbol}",{})
            price=float(q.get("last_price") or 0)
            volume=int(q.get("volume") or 0)
            if price>0 and volume>0:
                rows.append((symbol,token,price,volume,price*volume))
    return sorted(rows,key=lambda r:r[4],reverse=True)


def _indicator_levels(d, signal):
    """Use ATR and recent 20-session swing levels, never fixed return percentages."""
    row=d.iloc[-1]
    entry=float(row["Close"])
    atr=float(row["ATR_14"])
    if not pd.notna(atr) or atr<=0:
        return None
    prior=d.iloc[:-1].tail(20)
    if len(prior)<10:
        return None
    resistance=float(prior["High"].max())
    support=float(prior["Low"].min())
    if signal=="BUY":
        stop=min(support,entry-1.5*atr)
        stop=min(stop,entry-0.25*atr)
        candidates=[x for x in (resistance,entry+2.0*atr,entry+3.0*atr) if x>entry]
        target1=min(candidates) if candidates else entry+2.0*atr
        target2=max(x for x in (resistance,entry+3.0*atr) if x>entry)
    elif signal=="SELL":
        stop=max(resistance,entry+1.5*atr)
        stop=max(stop,entry+0.25*atr)
        candidates=[x for x in (support,entry-2.0*atr,entry-3.0*atr) if 0<x<entry]
        target1=max(candidates) if candidates else max(0.01,entry-2.0*atr)
        target2=min(x for x in (support,entry-3.0*atr) if 0<x<entry)
    else:
        # WAIT: show indicator reference levels but explicitly do not imply an entry.
        stop=entry-1.5*atr
        target1=entry+2.0*atr
        target2=entry+3.0*atr
    risk=abs(entry-stop)
    reward=abs(target1-entry)
    return {
        "Target 1":round(target1,2),"Target 2":round(target2,2),
        "Stop Loss":round(stop,2),"ATR 14":round(atr,2),
        "Support 20D":round(support,2),"Resistance 20D":round(resistance,2),
        "Expected P/L per share":round((target1-entry) if signal!="SELL" else (entry-target1),2),
        "Expected P/L %":round(((target1-entry)/entry*100) if signal!="SELL" else ((entry-target1)/entry*100),2),
        "Risk/Reward":round(reward/risk,2) if risk>0 else None,
        "Level Method":"20D swing + ATR(14)"
    }


def score_daily_candles(candles, symbol, market):
    if not candles: return None
    frame=pd.DataFrame(candles)
    if not {"date","open","high","low","close","volume"}.issubset(frame.columns): return None
    frame=frame.set_index("date").sort_index().rename(columns={
        "open":"Open","high":"High","low":"Low","close":"Close","volume":"Volume"
    })
    if len(frame)<65: return None
    d=add_dtc_style_indicators(frame)
    tr=pd.concat([
        d["High"]-d["Low"],
        (d["High"]-d["Close"].shift()).abs(),
        (d["Low"]-d["Close"].shift()).abs()
    ],axis=1).max(axis=1)
    d["ATR_14"]=tr.rolling(14,min_periods=14).mean()
    row=d.iloc[-1]
    required=["EMA_30","EMA_35","EMA_40","EMA_45","EMA_50","EMA_60","RSI_14","RELATIVE_VOLUME","VWAP","ATR_14"]
    if any(pd.isna(row.get(col)) for col in required): return None
    close=float(row["Close"])
    momentum=(close/float(d["Close"].iloc[-6])-1)*100 if float(d["Close"].iloc[-6]) else 0
    relvol=float(row["RELATIVE_VOLUME"]); rsi=float(row["RSI_14"])
    bull=bool(row["EMA_BULL"] and close>float(row["VWAP"]) and rsi>=52 and momentum>0)
    bear=bool(row["EMA_BEAR"] and close<float(row["VWAP"]) and rsi<=48 and momentum<0)
    signal="BUY" if bull else "SELL" if bear else "WAIT"
    levels=_indicator_levels(d,signal)
    if levels is None: return None
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
        "Volume":int(row["Volume"]),"Entry":round(close,2),**levels,
        "Candle Date":str(pd.Timestamp(d.index[-1]).date()),
        "Data Source":"Kite historical daily candles"
    }


def scan_stock_universe(kite, market="FNO", max_candidates=35):
    if market not in ("FNO","EQUITY"): raise ValueError("market must be FNO or EQUITY")
    universe=_universe(kite,market)
    turnover=_quote_turnover(kite,universe)
    now=datetime.now(IST); start=now-timedelta(days=180)
    picks=[]
    if turnover:
        candidates=turnover[:max_candidates]
        for symbol,token,price,volume,value in candidates:
            try:
                candles=kite.historical_data(token,start,now,"day")
                row=score_daily_candles(candles,symbol,market)
                if row:
                    row["Turnover ₹"]=int(value)
                    row["Data Freshness"]="Quote-ranked + historical candle"
                    picks.append(row)
            except Exception: continue
        ranked=len(turnover); checked=len(candidates); source="Kite quote + historical candles"
    else:
        # Market-closed fallback: rank by last completed daily candle turnover.
        # Scan a bounded universe, then rank by actual historical close x volume.
        candidates=universe[:min(len(universe),max(100,max_candidates*4))]
        historical_rank=[]
        for symbol,token in candidates:
            try:
                candles=kite.historical_data(token,start,now,"day")
                if not candles: continue
                last=candles[-1]
                close=float(last.get("close") or 0); volume=int(last.get("volume") or 0)
                if close<=0 or volume<=0: continue
                historical_rank.append((symbol,token,candles,close,volume,close*volume))
            except Exception: continue
        historical_rank.sort(key=lambda x:x[5],reverse=True)
        selected=historical_rank[:max_candidates]
        for symbol,token,candles,close,volume,value in selected:
            row=score_daily_candles(candles,symbol,market)
            if row:
                row["Turnover ₹"]=int(value)
                row["Data Freshness"]="Last completed session"
                picks.append(row)
        ranked=len(historical_rank); checked=len(candidates); source="Kite last-session historical candles"
    picks.sort(key=lambda r:(r["Signal"]=="BUY",r["Score"],r["Relative Volume"]),reverse=True)
    return pd.DataFrame(picks),{
        "universe":len(universe),"quote_ranked":ranked,
        "history_checked":checked,"selected":len(picks),
        "data_source":source,
        "reason":None if picks else "No instruments had sufficient historical OHLCV data and valid indicator levels"
    }


def scan_fno_stock_candidates(kite,max_stocks=25):
    frame,_=scan_stock_universe(kite,"FNO",max_candidates=max_stocks)
    return frame.to_dict("records")
