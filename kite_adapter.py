import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from kiteconnect import KiteConnect

IST = ZoneInfo("Asia/Kolkata")
INDEX_TOKENS = {"NIFTY": 256265, "BANKNIFTY": 260105}
INDEX_QUOTE_KEYS = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK"}
INTERVALS = {"3minute": "3minute", "5minute": "5minute", "15minute": "15minute"}

def get_secret(name):
    value = os.getenv(name)
    if value:
        return value
    try:
        return st.secrets.get(name)
    except Exception:
        return None

def kite_client():
    api_key = get_secret("KITE_API_KEY")
    access_token = st.session_state.get("kite_access_token") or get_secret("KITE_ACCESS_TOKEN")
    if not api_key or not access_token:
        return None
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    return kite

def login_url():
    key = get_secret("KITE_API_KEY")
    if not key:
        raise RuntimeError("KITE_API_KEY is not configured")
    return KiteConnect(api_key=key).login_url()

def generate_session(request_token: str) -> str:
    key = get_secret("KITE_API_KEY")
    secret = get_secret("KITE_API_SECRET")
    if not key or not secret:
        raise RuntimeError("Kite API credentials are missing")
    if not request_token or not request_token.strip():
        raise ValueError("Request token is required")
    session = KiteConnect(api_key=key).generate_session(request_token.strip(), api_secret=secret)
    return session["access_token"]

def fetch_index_candles(kite, symbol: str, interval: str) -> pd.DataFrame:
    if symbol not in INDEX_TOKENS or interval not in INTERVALS:
        raise ValueError("Unsupported index or interval")
    now = datetime.now(IST)
    rows = kite.historical_data(INDEX_TOKENS[symbol], now - timedelta(days=5), now, INTERVALS[interval])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).set_index("date").sort_index()
    return df.rename(columns={"open":"Open","high":"High","low":"Low","close":"Close","volume":"Volume"})

def fetch_option_contracts(kite, underlying: str, option_side: str, expiry_date=None) -> pd.DataFrame:
    if underlying not in INDEX_TOKENS or option_side not in ("CE", "PE"):
        raise ValueError("Unsupported underlying or option side")
    instruments = pd.DataFrame(kite.instruments("NFO"))
    required = {"name", "instrument_type", "expiry", "strike", "lot_size", "tradingsymbol", "instrument_token"}
    if instruments.empty or not required.issubset(instruments.columns):
        raise RuntimeError("Kite NFO instrument master is empty or missing required fields")
    today = datetime.now(IST).date()
    options = instruments[
        (instruments["name"].astype(str).str.upper() == underlying) &
        (instruments["instrument_type"].astype(str).str.upper() == option_side)
    ].copy()
    options["expiry"] = pd.to_datetime(options["expiry"], errors="coerce").dt.date
    options = options[options["expiry"] >= today]
    if expiry_date is not None:
        options = options[options["expiry"] == expiry_date]
    return options.sort_values(["expiry", "strike"]).reset_index(drop=True)

def get_index_ltp(kite, underlying: str) -> float:
    if underlying not in INDEX_QUOTE_KEYS:
        raise ValueError("Unsupported underlying")
    quote = kite.ltp([INDEX_QUOTE_KEYS[underlying]])
    item = quote.get(INDEX_QUOTE_KEYS[underlying], {})
    ltp = float(item.get("last_price") or 0)
    if ltp <= 0:
        raise RuntimeError(f"No valid {underlying} index LTP returned by Kite")
    return ltp

def select_option_contract(kite, underlying: str, option_side: str, moneyness="ATM"):
    if moneyness not in ("ATM", "1 ITM", "2 ITM", "1 OTM", "2 OTM"):
        raise ValueError("Unsupported moneyness")
    spot = get_index_ltp(kite, underlying)
    contracts = fetch_option_contracts(kite, underlying, option_side)
    if contracts.empty:
        raise RuntimeError(f"No unexpired {underlying} {option_side} contracts found")
    expiry = contracts["expiry"].min()
    contracts = contracts[contracts["expiry"] == expiry].copy()
    strikes = sorted(float(x) for x in contracts["strike"].dropna().unique())
    if not strikes:
        raise RuntimeError("Option strike list is empty")
    step = min((b-a for a,b in zip(strikes, strikes[1:]) if b>a), default=0)
    if step <= 0:
        raise RuntimeError("Could not determine strike interval")
    atm = min(strikes, key=lambda strike: abs(strike-spot))
    steps = {"ATM":0, "1 ITM":1, "2 ITM":2, "1 OTM":-1, "2 OTM":-2}[moneyness]
    target = atm + steps*step if option_side == "CE" else atm - steps*step
    strike = min(strikes, key=lambda value: abs(value-target))
    selected = contracts[contracts["strike"].astype(float) == strike]
    if selected.empty:
        raise RuntimeError("Could not find matching option contract")
    contract = selected.iloc[0].to_dict()
    key = f"NFO:{contract['tradingsymbol']}"
    quote = kite.quote([key]).get(key)
    if not quote:
        raise RuntimeError(f"No live quote returned for {key}")
    depth = quote.get("depth") or {}
    buy = (depth.get("buy") or [{}])[0].get("price", 0) or 0
    sell = (depth.get("sell") or [{}])[0].get("price", 0) or 0
    ltp = float(quote.get("last_price") or 0)
    if ltp <= 0:
        raise RuntimeError("Option premium is unavailable")
    spread_pct = ((float(sell)-float(buy))/ltp*100) if buy and sell and sell >= buy else None
    return {
        "underlying": underlying, "side": option_side,
        "tradingsymbol": str(contract["tradingsymbol"]),
        "instrument_token": int(contract["instrument_token"]),
        "expiry": str(contract["expiry"]), "strike": float(contract["strike"]),
        "lot_size": int(contract["lot_size"]), "spot_ltp": spot,
        "option_ltp": ltp, "best_bid": float(buy or 0),
        "best_ask": float(sell or 0), "spread_pct": spread_pct,
        "volume": int(quote.get("volume") or 0),
        "oi": int(quote.get("oi") or 0), "quote_time": str(quote.get("timestamp") or quote.get("last_trade_time") or "")
    }

def get_option_ltp(kite, tradingsymbol: str) -> float:
    key = f"NFO:{tradingsymbol}"
    quote = kite.ltp([key]).get(key, {})
    value = float(quote.get("last_price") or 0)
    if value <= 0:
        raise RuntimeError(f"Invalid LTP for {tradingsymbol}")
    return value


def fetch_derivative_contracts(kite, exchange="NFO", underlying=None, option_side="CE"):
    """Return current unexpired stock/index option contracts from Kite's instrument master."""
    if exchange not in ("NFO", "BFO") or option_side not in ("CE", "PE"):
        raise ValueError("Only NFO/BFO CE/PE contracts are supported")
    instruments = pd.DataFrame(kite.instruments(exchange))
    required = {"name","instrument_type","expiry","strike","lot_size","tradingsymbol","instrument_token","exchange"}
    if instruments.empty or not required.issubset(instruments.columns):
        raise RuntimeError(f"{exchange} instrument master is empty or incomplete")
    today = datetime.now(IST).date()
    frame = instruments[
        instruments["instrument_type"].astype(str).str.upper().eq(option_side)
    ].copy()
    frame["expiry"] = pd.to_datetime(frame["expiry"], errors="coerce").dt.date
    frame = frame[frame["expiry"] >= today]
    if underlying:
        frame = frame[frame["name"].astype(str).str.upper().eq(underlying.upper())]
    return frame.sort_values(["name","expiry","strike"]).reset_index(drop=True)



def quote_timestamp_age_seconds(value, now=None):
    """Return quote age in seconds; None means provider supplied no usable timestamp."""
    if not value:
        return None
    stamp=pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp=stamp.tz_localize(IST)
    else:
        stamp=stamp.tz_convert(IST)
    current=pd.Timestamp(now or datetime.now(IST))
    if current.tzinfo is None:
        current=current.tz_localize(IST)
    else:
        current=current.tz_convert(IST)
    return max(0.0,(current-stamp).total_seconds())


def validate_option_liquidity(snapshot, max_spread_pct=3.0):
    """Strict gate: no volume/OI, two-sided depth, or reasonable spread => reject."""
    reasons=[]
    if snapshot.get("last_price",0)<=0: reasons.append("invalid LTP")
    if snapshot.get("volume",0)<=0: reasons.append("zero traded volume")
    if snapshot.get("oi",0)<=0: reasons.append("zero open interest")
    bid=snapshot.get("bid",0); ask=snapshot.get("ask",0); ltp=snapshot.get("last_price",0)
    if bid<=0 or ask<=0 or ask<bid: reasons.append("missing/invalid two-sided bid-ask depth")
    spread=((ask-bid)/ltp*100) if ltp>0 and bid>0 and ask>=bid else None
    if spread is None: reasons.append("spread unavailable")
    elif spread>max_spread_pct: reasons.append(f"spread too wide ({spread:.2f}%)")
    age=snapshot.get("age_seconds")
    if age is None: reasons.append("quote timestamp unavailable")
    elif age>4*24*60*60: reasons.append(f"quote stale ({age/3600:.1f} hours old)")
    return {"eligible":not reasons,"reasons":reasons,"spread_pct":spread}

def get_quote_snapshot(kite, exchange, tradingsymbol):
    if exchange not in ("NSE","BSE","NFO","BFO"):
        raise ValueError("Unsupported exchange")
    key=f"{exchange}:{tradingsymbol}"
    data=kite.quote([key]).get(key)
    if not data:
        raise RuntimeError(f"No quote returned for {key}")
    depth=data.get("depth") or {}
    bid=(depth.get("buy") or [{}])[0].get("price") or 0
    ask=(depth.get("sell") or [{}])[0].get("price") or 0
    timestamp=data.get("timestamp") or data.get("last_trade_time")
    age=quote_timestamp_age_seconds(timestamp) if timestamp else None
    return {
        "key":key,
        "last_price":float(data.get("last_price") or 0),
        "volume":int(data.get("volume") or 0),
        "oi":int(data.get("oi") or 0),
        "bid":float(bid),
        "ask":float(ask),
        "timestamp":str(timestamp or ""),
        "age_seconds":age,
    }
