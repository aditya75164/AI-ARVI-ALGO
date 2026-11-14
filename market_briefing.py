"""Daily NIFTY/BANK NIFTY market brief: ATR/swing levels and RSS headlines."""
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo
import pandas as pd

IST=ZoneInfo("Asia/Kolkata")
INDEX_TOKENS={"NIFTY":256265,"BANKNIFTY":260105}


def fetch_index_daily_candles(kite,index,days=180,now=None):
    if index not in INDEX_TOKENS:
        raise ValueError("Unsupported index")
    end=now or datetime.now(IST)
    start=end-timedelta(days=days)
    rows=kite.historical_data(INDEX_TOKENS[index],start,end,"day")
    if not rows:
        raise RuntimeError(f"No daily candles returned for {index}")
    frame=pd.DataFrame(rows).set_index("date").sort_index()
    today=end.date()
    if end.weekday()<5 and end.strftime("%H:%M")<"15:35":
        frame=frame[pd.to_datetime(frame.index).date<today]
    return frame.rename(columns={"open":"Open","high":"High","low":"Low","close":"Close","volume":"Volume"})


def build_index_scenarios(candles,index):
    """Create conditional bullish/bearish triggers from latest completed daily candle."""
    if candles is None or len(candles)<25:
        raise ValueError("At least 25 daily candles are required")
    d=candles.copy().sort_index()
    required={"High","Low","Close"}
    if not required.issubset(d.columns):
        raise ValueError("Daily candles must include High, Low and Close")
    tr=pd.concat([d["High"]-d["Low"],(d["High"]-d["Close"].shift()).abs(),(d["Low"]-d["Close"].shift()).abs()],axis=1).max(axis=1)
    atr=float(tr.rolling(14,min_periods=14).mean().iloc[-1])
    if pd.isna(atr) or atr<=0:
        raise ValueError("ATR(14) is not available")
    last=d.iloc[-1]
    prior=d.iloc[:-1].tail(20)
    close=float(last["Close"])
    support=float(prior["Low"].min())
    resistance=float(prior["High"].max())
    bullish_trigger=max(float(last["High"]),close+0.15*atr)
    bearish_trigger=min(float(last["Low"]),close-0.15*atr)
    bull_t1=max(resistance,bullish_trigger+0.75*atr)
    bull_t2=max(bull_t1+0.75*atr,bullish_trigger+1.5*atr)
    bear_t1=min(support,bearish_trigger-0.75*atr)
    bear_t2=min(bear_t1-0.75*atr,bearish_trigger-1.5*atr)
    if bear_t1<=0 or bear_t2<=0:
        raise ValueError("Calculated downside levels are invalid")
    return {
        "index":index,"close":round(close,2),"atr":round(atr,2),
        "support":round(support,2),"resistance":round(resistance,2),
        "bullish":{"trigger":round(bullish_trigger,2),"target1":round(bull_t1,2),"target2":round(bull_t2,2),"invalidation":round(min(support,bullish_trigger-atr),2)},
        "bearish":{"trigger":round(bearish_trigger,2),"target1":round(bear_t1,2),"target2":round(bear_t2,2),"invalidation":round(max(resistance,bearish_trigger+atr),2)},
        "candle_date":str(pd.Timestamp(d.index[-1]).date()),
        "method":"Prior 20-session swing levels + ATR(14)",
    }


def fetch_market_news(query="India stock market NIFTY BANK NIFTY RBI FII DII global markets",limit=8,timeout=12):
    """Read public Google News RSS results; headline links lead to publisher articles."""
    url="https://news.google.com/rss/search?q="+quote_plus(query)+"&hl=en-IN&gl=IN&ceid=IN:en"
    request=Request(url,headers={"User-Agent":"Mozilla/5.0 AI-ARVI-ALGO market briefing"})
    with urlopen(request,timeout=timeout) as response:
        root=ET.fromstring(response.read())
    items=[]
    for item in root.findall("./channel/item")[:limit]:
        title=item.findtext("title") or ""
        link=item.findtext("link") or ""
        source=item.find("source")
        publisher=(source.text or "") if source is not None else "News source"
        pubdate=item.findtext("pubDate") or ""
        try:
            stamp=parsedate_to_datetime(pubdate).astimezone(IST).strftime("%d-%b %H:%M IST")
        except Exception:
            stamp=pubdate
        if title and link:
            items.append({"title":title,"link":link,"publisher":publisher,"published":stamp})
    return items
