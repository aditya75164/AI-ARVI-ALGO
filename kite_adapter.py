import os
import pandas as pd
from kiteconnect import KiteConnect
import streamlit as st

def get_secret(name):
    value=os.getenv(name)
    if value:
        return value
    try:
        return st.secrets.get(name)
    except Exception:
        return None

# Index instrument tokens from the NSE index segment. Verify against the
# current instrument master before deployment; broker symbols can change.
INDEX_TOKENS={"NIFTY":256265,"BANKNIFTY":260105}
INTERVALS={"3minute":"3minute","5minute":"5minute","15minute":"15minute"}

def kite_client():
    api_key=get_secret("KITE_API_KEY")
    access_token=st.session_state.get("kite_access_token") or get_secret("KITE_ACCESS_TOKEN")
    if not api_key or not access_token:
        return None
    kite=KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    return kite

def login_url():
    key=get_secret("KITE_API_KEY")
    if not key: raise RuntimeError("KITE_API_KEY is not configured")
    return KiteConnect(api_key=key).login_url()

def generate_session(request_token: str) -> str:
    key=_secret("KITE_API_KEY"); secret=get_secret("KITE_API_SECRET")
    if not key or not secret: raise RuntimeError("Kite API credentials are missing")
    session=KiteConnect(api_key=key).generate_session(request_token,api_secret=secret)
    return session["access_token"]

def fetch_index_candles(kite, symbol: str, interval: str) -> pd.DataFrame:
    if symbol not in INDEX_TOKENS or interval not in INTERVALS:
        raise ValueError("Unsupported index or interval")
    from datetime import datetime,timedelta
    from zoneinfo import ZoneInfo
    now=datetime.now(ZoneInfo("Asia/Kolkata"))
    rows=kite.historical_data(INDEX_TOKENS[symbol],now-timedelta(days=5),now,INTERVALS[interval])
    if not rows: return pd.DataFrame()
    df=pd.DataFrame(rows).set_index("date")
    return df.rename(columns={"open":"Open","high":"High","low":"Low","close":"Close","volume":"Volume"})
