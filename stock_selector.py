"""Rank equity F&O underlyings using trend, momentum, relative volume and headline context.

This is a watchlist filter, not a return predictor. A 10% target is a user-defined
watch horizon and is never represented as a likely or guaranteed return.
"""
from datetime import datetime, timedelta
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo
import pandas as pd
from engine import add_dtc_style_indicators

IST=ZoneInfo("Asia/Kolkata")
POSITIVE={"beats","growth","profit","upgrade","order win","strong","record","buyback","approval","expansion","raises","surge","partnership"}
NEGATIVE={"miss","loss","downgrade","fraud","probe","default","weak","decline","fall","cuts","ban","warning","resigns"}

def fetch_global_headlines(timeout=6):
    query=quote("global markets OR crude oil OR US markets OR Federal Reserve OR India stocks")
    url=f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 AI-ARVI-ALGO market research"})
    try:
        with urlopen(req,timeout=timeout) as response:
            root=ET.fromstring(response.read())
        return [item.findtext("title","") for item in root.findall(".//item")][:40]
    except Exception:
        return []

def headline_score(name, symbol, headlines):
    related=[h.lower() for h in headlines if name.lower() in h.lower() or symbol.lower() in h.lower()]
    if not related:
        return 0, "No matching headline found"
    text=" ".join(related)
    pos=sum(1 for word in POSITIVE if word in text)
    neg=sum(1 for word in NEGATIVE if word in text)
    score=max(-1,min(1,(pos-neg)/max(1,pos+neg)))
    return score, " | ".join(related[:2])


def quote_is_usable(quote, now=None):
    """Require positive volume, two-sided depth, tight spread and a recent quote."""
    if not quote:
        return False, "missing quote"
    price=float(quote.get("last_price") or 0)
    volume=int(quote.get("volume") or 0)
    depth=quote.get("depth") or {}
    bid=float(((depth.get("buy") or [{}])[0]).get("price") or 0)
    ask=float(((depth.get("sell") or [{}])[0]).get("price") or 0)
    if price<=0 or volume<=0:
        return False, "zero price or traded volume"
    if bid<=0 or ask<=0 or ask<bid:
        return False, "missing/invalid bid-ask depth"
    spread=(ask-bid)/price*100
    if spread>2.0:
        return False, f"spread too wide ({spread:.2f}%)"
    stamp=quote.get("timestamp") or quote.get("last_trade_time")
    if not stamp:
        return False, "quote timestamp missing"
    ts=pd.Timestamp(stamp)
    if ts.tzinfo is None:
        ts=ts.tz_localize(IST)
    else:
        ts=ts.tz_convert(IST)
    current=pd.Timestamp(now or datetime.now(IST))
    if current.tzinfo is None:
        current=current.tz_localize(IST)
    else:
        current=current.tz_convert(IST)
    if (current-ts).total_seconds()>4*24*60*60:
        return False, "quote older than four days"
    return True, "ok"

def score_stock(frame, name, symbol, headlines):
    if frame is None or len(frame)<65:
        return None
    d=add_dtc_style_indicators(frame)
    row=d.iloc[-1]; prev=d.iloc[-2]
    required=["EMA_30","EMA_35","EMA_40","EMA_45","EMA_50","EMA_60","RSI_14","RELATIVE_VOLUME","VWAP"]
    if any(pd.isna(row.get(k)) for k in required):
        return None
    trend=bool(row["EMA_BULL"] and row["Close"]>row["VWAP"])
    momentum=(float(row["Close"])/float(d["Close"].iloc[-5])-1)*100 if float(d["Close"].iloc[-5]) else 0
    relvol=float(row["RELATIVE_VOLUME"])
    rsi=float(row["RSI_14"])
    news, headline=headline_score(name,symbol,headlines)
    trend_pts=30 if trend else 0
    volume_pts=min(25,max(0,(relvol-1)*12.5))
    momentum_pts=min(20,max(0,momentum*4))
    rsi_pts=10 if 55<=rsi<=75 else 5 if 50<=rsi<55 else 0
    news_pts=7.5+7.5*news
    total=round(trend_pts+volume_pts+momentum_pts+rsi_pts+news_pts,1)
    if not (trend and relvol>=1.5 and momentum>0 and 55<=rsi<=80):
        return None
    return {
        "name":name,"symbol":symbol,"score":total,"last_price":float(row["Close"]),
        "momentum_pct":round(momentum,2),"relative_volume":round(relvol,2),
        "rsi":round(rsi,1),"news_score":round(news,2),"headline":headline,
        "target_reference_pct":10.0,
    }

def scan_fno_stock_candidates(kite, max_stocks=25):
    """Scan liquid F&O underlyings; bounded history calls to reduce API load."""
    fno=pd.DataFrame(kite.instruments("NFO"))
    cash=pd.DataFrame(kite.instruments("NSE"))
    required={"name","instrument_type","tradingsymbol","expiry"}
    if fno.empty or cash.empty or not required.issubset(fno.columns):
        raise RuntimeError("Kite NFO/NSE instrument master is unavailable")
    today=datetime.now(IST).date()
    fno=fno[(fno["instrument_type"].astype(str)=="FUT")].copy()
    fno["expiry"]=pd.to_datetime(fno["expiry"],errors="coerce").dt.date
    fno=fno[fno["expiry"]>=today].sort_values("expiry").drop_duplicates("name")
    cash=cash[cash["segment"].astype(str).eq("NSE")].drop_duplicates("tradingsymbol")
    mapping={str(r.tradingsymbol):int(r.instrument_token) for r in cash.itertuples() if hasattr(r,"instrument_token")}
    names=[]
    for n in fno["name"].astype(str).tolist():
        if n in mapping: names.append((n,mapping[n]))
    if not names: return []
    headlines=fetch_global_headlines()
    keys=[f"NSE:{name}" for name,_ in names[:500]]
    quotes=kite.quote(keys)
    liquid=[]
    for name,token in names:
        q=quotes.get(f"NSE:{name}",{})
        volume=int(q.get("volume") or 0)
        price=float(q.get("last_price") or 0)
        valid, _reason=quote_is_usable(q)
        if valid:
            liquid.append((name,token,volume,price))
    liquid=sorted(liquid,key=lambda x:x[2]*x[3],reverse=True)[:max_stocks]
    now=datetime.now(IST)
    picks=[]
    for name,token,volume,price in liquid:
        try:
            candles=kite.historical_data(token,now-timedelta(days=8),now,"5minute")
            if not candles: continue
            frame=pd.DataFrame(candles).set_index("date").sort_index()
            frame=frame.rename(columns={"open":"Open","high":"High","low":"Low","close":"Close","volume":"Volume"})
            if frame.empty:
                continue
            last_bar=pd.Timestamp(frame.index[-1])
            if last_bar.tzinfo is None:
                last_bar=last_bar.tz_localize(IST)
            if (pd.Timestamp(now)-last_bar).total_seconds()>4*24*60*60:
                continue
            result=score_stock(frame,name,name,headlines)
            if result:
                result["day_volume"]=volume
                picks.append(result)
        except Exception:
            continue
    return sorted(picks,key=lambda x:x["score"],reverse=True)
