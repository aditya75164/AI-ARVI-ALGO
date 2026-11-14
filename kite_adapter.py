import os
from pathlib import Path
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

def persist_access_token(access_token: str) -> None:
    """Persist the short-lived Kite access token to the local, git-ignored .env file."""
    token = str(access_token or "").strip()
    if not token or "\n" in token or "\r" in token:
        raise ValueError("A valid Kite access token is required")
    env_path = Path(__file__).resolve().parent / ".env"
    existing = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    output = []
    replaced = False
    for line in existing:
        if line.strip().startswith("KITE_ACCESS_TOKEN="):
            if not replaced:
                output.append("KITE_ACCESS_TOKEN=" + token)
                replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append("KITE_ACCESS_TOKEN=" + token)
    temp_path = env_path.with_suffix(".env.tmp")
    temp_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.replace(temp_path, env_path)
    os.environ["KITE_ACCESS_TOKEN"] = token

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
    buy_levels = depth.get("buy") or []
    sell_levels = depth.get("sell") or []
    buy = (buy_levels or [{}])[0].get("price", 0) or 0
    sell = (sell_levels or [{}])[0].get("price", 0) or 0
    # Five-level order-book depth snapshot, not executed trade volume.
    buyer_depth_qty = sum(int(level.get("quantity") or 0) for level in buy_levels[:5])
    seller_depth_qty = sum(int(level.get("quantity") or 0) for level in sell_levels[:5])
    buyer_seller_depth_ratio = (buyer_depth_qty / seller_depth_qty) if seller_depth_qty > 0 else None
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
        "oi": int(quote.get("oi") or 0),
        "buyer_depth_qty": buyer_depth_qty, "seller_depth_qty": seller_depth_qty,
        "buyer_seller_depth_ratio": buyer_seller_depth_ratio,
        "quote_time": str(quote.get("timestamp") or quote.get("last_trade_time") or "")
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


def validate_option_liquidity(snapshot, max_spread_pct=3.0, max_age_seconds=180):
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
    elif age>max_age_seconds: reasons.append(f"quote stale ({age:.0f} seconds old)")
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


def filter_live_option_contracts(kite, contracts, exchange='NFO', max_age_seconds=180, max_spread_pct=3.0, batch_size=200):
    """Return live liquid contracts during market hours; closed-session data is reference-only."""
    if contracts is None or contracts.empty:
        return pd.DataFrame(), {'checked':0,'eligible':0,'rejected':0,'underlyings':0,'reason':'No unexpired instruments'}
    if exchange not in ('NFO','BFO'):
        raise ValueError('Unsupported derivatives exchange')
    now=datetime.now(IST)
    market_open = now.weekday()<5 and '09:15'<=now.strftime('%H:%M')<='15:30'
    unique_underlyings=int(contracts['name'].astype(str).nunique()) if 'name' in contracts.columns else 0
    total_contracts=len(contracts)
    if not market_open:
        # Do not call quote() on a closed exchange and mislabel absent depth as a dead stock.
        # Historical candle data is shown separately for an individually selected contract.
        reference=contracts.copy()
        for col in ('last_price','volume','oi','bid','ask','spread_pct'):
            reference[col]=None
        reference['quote_status']='SELECT TO LOAD LAST-SESSION CANDLE'
        return reference, {
            'checked':0,'eligible':0,'rejected':0,'underlyings':unique_underlyings,
            'total_contracts':total_contracts,'reason':'Market closed - reference universe only'
        }
    eligible=[]; rejected=0
    symbols=contracts['tradingsymbol'].astype(str).tolist()
    for start in range(0,len(symbols),batch_size):
        batch=symbols[start:start+batch_size]
        quotes=kite.quote([f'{exchange}:{s}' for s in batch])
        for symbol in batch:
            q=quotes.get(f'{exchange}:{symbol}')
            if not q:
                rejected+=1; continue
            depth=q.get('depth') or {}
            bid=float(((depth.get('buy') or [{}])[0]).get('price') or 0)
            ask=float(((depth.get('sell') or [{}])[0]).get('price') or 0)
            ltp=float(q.get('last_price') or 0); volume=int(q.get('volume') or 0); oi=int(q.get('oi') or 0)
            stamp=q.get('timestamp') or q.get('last_trade_time')
            if not stamp or ltp<=0 or volume<=0 or oi<=0 or bid<=0 or ask<=0 or ask<bid:
                rejected+=1; continue
            age=quote_timestamp_age_seconds(stamp,now)
            if age is None or age>max_age_seconds or pd.Timestamp(stamp).date()!=now.date():
                rejected+=1; continue
            spread=(ask-bid)/ltp*100
            if spread>max_spread_pct:
                rejected+=1; continue
            row=contracts[contracts['tradingsymbol'].astype(str)==symbol].iloc[0].to_dict()
            row.update({'last_price':ltp,'volume':volume,'oi':oi,'bid':bid,'ask':ask,
                        'spread_pct':round(spread,2),'quote_time':str(stamp),
                        'quote_age_seconds':round(age,1),'quote_status':'LIVE'})
            eligible.append(row)
    result=pd.DataFrame(eligible)
    if not result.empty:
        # One contract per underlying: highest OI among contracts that passed all live liquidity gates.
        result=result.sort_values(['oi','volume'],ascending=False)
        result=result.drop_duplicates(subset=['name'],keep='first').reset_index(drop=True)
    return result, {
        'checked':total_contracts,'eligible':len(result),'rejected':rejected,
        'underlyings':unique_underlyings,'total_contracts':total_contracts,
        'reason':'Live liquidity filters applied'
    }


def build_stock_option_watchlist(kite, exchange="NFO", option_side="PE", underlying_filter=None,
                                 target_pct=10.0, stop_pct=5.0, batch_size=180):
    """One near-ATM, highest-OI option per F&O stock, with transparent reference signals."""
    if exchange not in ("NFO","BFO") or option_side not in ("CE","PE"):
        raise ValueError("Unsupported derivatives exchange or option side")
    instruments=pd.DataFrame(kite.instruments(exchange))
    required={"name","instrument_type","expiry","strike","lot_size","tradingsymbol","instrument_token"}
    if instruments.empty or not required.issubset(instruments.columns):
        raise RuntimeError("Derivative instrument master is incomplete")
    today=datetime.now(IST).date()
    frame=instruments[instruments["instrument_type"].astype(str).str.upper().eq(option_side)].copy()
    frame["expiry"]=pd.to_datetime(frame["expiry"],errors="coerce").dt.date
    frame=frame[frame["expiry"]>=today]
    if underlying_filter:
        frame=frame[frame["name"].astype(str).str.upper().eq(underlying_filter.upper())]
    if frame.empty:
        return pd.DataFrame(), {"underlyings":0,"candidates":0,"selected":0}
    # Use nearest expiry per underlying and a narrow ATM window, not every listed strike.
    frame=frame.sort_values(["name","expiry","strike"])
    frame=frame[frame["expiry"].eq(frame.groupby("name")["expiry"].transform("min"))]
    names=sorted(frame["name"].astype(str).unique())
    spot_keys=[f"{'NSE' if exchange=='NFO' else 'BSE'}:{name}" for name in names]
    spots={}
    for i in range(0,len(spot_keys),batch_size):
        try: spots.update(kite.ltp(spot_keys[i:i+batch_size]))
        except Exception: pass
    candidates=[]
    for name in names:
        key=f"{'NSE' if exchange=='NFO' else 'BSE'}:{name}"
        spot=float((spots.get(key) or {}).get("last_price") or 0)
        rows=frame[frame["name"].astype(str).eq(name)].copy()
        if spot<=0 or rows.empty: continue
        strikes=sorted(float(x) for x in rows["strike"].dropna().unique())
        if not strikes: continue
        nearest=min(strikes,key=lambda x:abs(x-spot))
        step=min((b-x for x,b in zip(strikes,strikes[1:]) if b>x),default=0)
        if step<=0: continue
        near=[x for x in strikes if abs(x-nearest)<=3*step]
        candidates.extend(rows[rows["strike"].astype(float).isin(near)].to_dict("records"))
    if not candidates:
        return pd.DataFrame(), {"underlyings":len(names),"candidates":0,"selected":0}
    quote_map={}
    keys=[f"{exchange}:{r['tradingsymbol']}" for r in candidates]
    for i in range(0,len(keys),batch_size):
        quote_map.update(kite.quote(keys[i:i+batch_size]))
    market_now=datetime.now(IST)
    market_open=market_now.weekday()<5 and "09:15"<=market_now.strftime("%H:%M")<="15:30"
    picked=[]
    for row in candidates:
        q=quote_map.get(f"{exchange}:{row['tradingsymbol']}",{})
        ltp=float(q.get("last_price") or 0)
        volume=int(q.get("volume") or 0)
        oi=int(q.get("oi") or 0)
        ohlc=q.get("ohlc") or {}
        close=float(ohlc.get("close") or 0)
        net=float(q.get("net_change") or (ltp-close if close else 0))
        stamp=q.get("timestamp") or q.get("last_trade_time")
        if ltp<=0 or volume<=0 or oi<=0 or close<=0: continue
        if not market_open:
            # Reference quote must have a dated last trade, not an undated cached LTP.
            if not stamp: continue
            age=quote_timestamp_age_seconds(stamp,market_now)
            if age is None or age>4*24*60*60: continue
        else:
            age=quote_timestamp_age_seconds(stamp,market_now) if stamp else None
            if age is None or age>180: continue
        change_pct=net/close*100 if close else 0
        if change_pct>=0.5: signal="BUY"
        elif change_pct<=-0.5: signal="SELL"
        else: signal="WAIT"
        entry=ltp
        if signal=="BUY":
            target=entry*(1+target_pct/100); stop=entry*(1-stop_pct/100)
        elif signal=="SELL":
            target=entry*(1-target_pct/100); stop=entry*(1+stop_pct/100)
        else:
            target=entry*(1+target_pct/100); stop=entry*(1-stop_pct/100)
        picked.append({
            "Stock":row["name"],"Side":option_side,"Expiry":row["expiry"],
            "Strike":float(row["strike"]),"Option":row["tradingsymbol"],
            "Premium":round(ltp,2),"OI":oi,"Volume":volume,
            "Change %":round(change_pct,2),"Signal":signal,
            "Entry":round(entry,2),"Target":round(target,2),"Stop Loss":round(stop,2),
            "Lot Size":int(row["lot_size"]),"Quote Time":str(stamp or ""),
            "Data Status":"LIVE" if market_open else "LAST SESSION",
            "Signal Reason":f"Premium change vs previous close: {change_pct:+.2f}%"
        })
    result=pd.DataFrame(picked)
    if not result.empty:
        result=result.sort_values(["OI","Volume"],ascending=False).drop_duplicates("Stock").reset_index(drop=True)
    return result, {"underlyings":len(names),"candidates":len(candidates),"selected":len(result),
                    "reason":"Live quote ranking" if market_open else "Last-session quote reference"}
