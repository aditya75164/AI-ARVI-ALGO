"""Authorized NSE market-data connector.

This adapter intentionally does not scrape nseindia.com. Configure an NSE/NSE Data
subscription or an authorized vendor's documented JSON endpoint in secrets.
The endpoint must return normalized quote fields documented below.
"""
import json
import os
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import pandas as pd
import streamlit as st


def _setting(name):
    value=os.getenv(name)
    if value:
        return value
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def nse_feed_configured():
    return bool(_setting("NSE_DATA_API_URL") and _setting("NSE_DATA_API_TOKEN"))


def fetch_nse_quotes(symbols, timeout=12):
    """Fetch normalized quotes from an authorized NSE/vendor endpoint.

    Request: GET <NSE_DATA_API_URL>?symbols=RELIANCE,SBIN
    Header: Authorization: Bearer <NSE_DATA_API_TOKEN>

    Response JSON may be {"data":[...]} or a list. Each row:
    symbol, last_price, open, high, low, previous_close, volume, oi,
    bid, ask, timestamp, exchange.
    """
    base=_setting("NSE_DATA_API_URL")
    token=_setting("NSE_DATA_API_TOKEN")
    if not base or not token:
        raise RuntimeError("NSE licensed feed is not configured. Add NSE_DATA_API_URL and NSE_DATA_API_TOKEN to app secrets.")
    clean=sorted({str(s).strip().upper() for s in symbols if str(s).strip()})
    if not clean:
        return pd.DataFrame()
    from urllib.parse import urlencode
    separator="&" if "?" in base else "?"
    url=base+separator+urlencode({"symbols":",".join(clean)})
    request=Request(url,headers={"Authorization":f"Bearer {token}","Accept":"application/json"})
    try:
        with urlopen(request,timeout=timeout) as response:
            payload=json.loads(response.read().decode("utf-8"))
    except (HTTPError,URLError,TimeoutError,ValueError) as exc:
        raise RuntimeError(f"NSE authorized feed request failed: {exc}") from exc
    rows=payload.get("data",[]) if isinstance(payload,dict) else payload
    if not isinstance(rows,list):
        raise RuntimeError("NSE feed response must be a list or an object containing a data list")
    frame=pd.DataFrame(rows)
    if frame.empty:
        return frame
    if "symbol" not in frame.columns or "last_price" not in frame.columns:
        raise RuntimeError("NSE feed response missing required symbol/last_price fields")
    frame["symbol"]=frame["symbol"].astype(str).str.upper()
    for col in ("last_price","open","high","low","previous_close","volume","oi","bid","ask"):
        if col in frame:
            frame[col]=pd.to_numeric(frame[col],errors="coerce")
    frame["data_source"]="NSE licensed feed"
    return frame[frame["symbol"].isin(clean)].reset_index(drop=True)
