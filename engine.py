import pandas as pd
import numpy as np

EMA_PERIODS=(30,35,40,45,50,60)

def add_dtc_style_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise ValueError("Candle data is empty")
    required={"Open","High","Low","Close","Volume"}
    missing=required-set(frame.columns)
    if missing:
        raise ValueError(f"Missing candle columns: {sorted(missing)}")
    d=frame.copy().sort_index()
    close=d["Close"].astype(float); high=d["High"].astype(float); low=d["Low"].astype(float)
    for period in EMA_PERIODS:
        d[f"EMA_{period}"]=close.ewm(span=period,adjust=False,min_periods=period).mean()
    prev=close.shift(1)
    tr=pd.concat([high-low,(high-prev).abs(),(low-prev).abs()],axis=1).max(axis=1)
    d["ATR_14"]=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    d["ATR_PCT"]=100*d["ATR_14"]/close.replace(0,np.nan)
    delta=close.diff()
    gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    loss=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    rs=gain/loss.replace(0,np.nan)
    d["RSI_14"]=100-100/(1+rs)
    vol=d["Volume"].fillna(0).astype(float)
    typical=(high+low+close)/3
    if isinstance(d.index,pd.DatetimeIndex):
        session=pd.Index(d.index.date)
        session_volume=vol.groupby(session).cumsum().replace(0,np.nan)
        weighted=(typical*vol).groupby(session).cumsum()/session_volume\n        # Index candles often carry zero volume; use an explicitly documented\n        # session typical-price mean proxy instead of returning all-NaN VWAP.\n        proxy=typical.groupby(session).cumsum()/pd.Series(1.0,index=d.index).groupby(session).cumsum()\n        d["VWAP"]=weighted.where(session_volume.notna(),proxy)
    else:
        d["VWAP"]=(typical*vol).rolling(20,min_periods=5).sum()/vol.rolling(20,min_periods=5).sum().replace(0,np.nan)
    d["EMA_BULL"]=d[[f"EMA_{p}" for p in EMA_PERIODS]].apply(lambda r: all(pd.notna(r)) and all(r.iloc[i]>r.iloc[i+1] for i in range(len(r)-1)),axis=1)
    d["EMA_BEAR"]=d[[f"EMA_{p}" for p in EMA_PERIODS]].apply(lambda r: all(pd.notna(r)) and all(r.iloc[i]<r.iloc[i+1] for i in range(len(r)-1)),axis=1)
    d["ATR_ACTIVE"]=d["ATR_PCT"]>=0.08
    return d

def build_signal(data: pd.DataFrame) -> dict:
    if len(data)<65:
        return {"bias":"INSUFFICIENT DATA","signal":"WAIT","score":0,"reason":"At least 65 candles are required for EMA 60 warm-up."}
    row=data.iloc[-1]
    if row[["EMA_30","EMA_35","EMA_40","EMA_45","EMA_50","EMA_60","VWAP","RSI_14","ATR_PCT"]].isna().any():
        return {"bias":"WARMING UP","signal":"WAIT","score":0,"reason":"Indicator values are not ready."}
    bull=[bool(row["EMA_BULL"]),row["Close"]>row["VWAP"],row["RSI_14"]>=55,bool(row["ATR_ACTIVE"])]
    bear=[bool(row["EMA_BEAR"]),row["Close"]<row["VWAP"],row["RSI_14"]<=45,bool(row["ATR_ACTIVE"])]
    bull_score=sum(bull)*25; bear_score=sum(bear)*25
    if bull_score>=75:
        return {"bias":"BULLISH","signal":"BUY CE","score":bull_score,"reason":"Bullish six-EMA stack, VWAP, RSI and ATR filters confirmed."}
    if bear_score>=75:
        return {"bias":"BEARISH","signal":"BUY PE","score":bear_score,"reason":"Bearish six-EMA stack, VWAP, RSI and ATR filters confirmed."}
    bias="BULLISH" if bull_score>bear_score else "BEARISH" if bear_score>bull_score else "MIXED"
    return {"bias":bias,"signal":"WAIT","score":max(bull_score,bear_score),"reason":"Trend/ VWAP/ RSI / ATR confirmations are incomplete; no trade."}
