"""Option premium enrichment for F&O stock scanner.

Theta is an estimated Black-Scholes calendar-day decay derived from the quoted
premium and inferred implied volatility. Buyer pressure is a Level-2 bid/ask
quantity proxy, not a guaranteed aggressor-side trade classification.
"""
from datetime import datetime
from math import erf, exp, log, pi, sqrt
from zoneinfo import ZoneInfo
import pandas as pd

IST=ZoneInfo("Asia/Kolkata")
RISK_FREE_RATE=0.07


def _cdf(x):
    return 0.5*(1.0+erf(x/sqrt(2.0)))


def _bs_price(spot,strike,t,rate,vol,side):
    if t<=0 or vol<=0:
        return max(spot-strike,0.0) if side=="CE" else max(strike-spot,0.0)
    d1=(log(spot/strike)+(rate+0.5*vol*vol)*t)/(vol*sqrt(t))
    d2=d1-vol*sqrt(t)
    if side=="CE":
        return spot*_cdf(d1)-strike*exp(-rate*t)*_cdf(d2)
    return strike*exp(-rate*t)*_cdf(-d2)-spot*_cdf(-d1)


def implied_volatility(premium,spot,strike,t,side,rate=RISK_FREE_RATE):
    intrinsic=max(spot-strike,0.0) if side=="CE" else max(strike-spot,0.0)
    if premium<=intrinsic or t<=0:
        return None
    lo,hi=0.01,5.0
    if _bs_price(spot,strike,t,rate,hi,side)<premium:
        return None
    for _ in range(70):
        mid=(lo+hi)/2
        if _bs_price(spot,strike,t,rate,mid,side)<premium:
            lo=mid
        else:
            hi=mid
    return (lo+hi)/2


def theta_per_day(spot,strike,expiry,premium,side,now=None,rate=RISK_FREE_RATE):
    current=now or datetime.now(IST)
    exp_date=pd.Timestamp(expiry).date()
    expiry_dt=pd.Timestamp(datetime.combine(exp_date,datetime.min.time()),tz=IST)+pd.Timedelta(hours=15,minutes=30)
    t=max((expiry_dt-pd.Timestamp(current)).total_seconds(),0)/(365.0*24*3600)
    iv=implied_volatility(float(premium),float(spot),float(strike),t,side,rate)
    if iv is None or t<=0:
        return None,None
    d1=(log(spot/strike)+(rate+0.5*iv*iv)*t)/(iv*sqrt(t))
    d2=d1-iv*sqrt(t)
    density=exp(-0.5*d1*d1)/sqrt(2*pi)
    if side=="CE":
        theta=-(spot*density*iv)/(2*sqrt(t))-rate*strike*exp(-rate*t)*_cdf(d2)
    else:
        theta=-(spot*density*iv)/(2*sqrt(t))+rate*strike*exp(-rate*t)*_cdf(-d2)
    return theta/365.0,iv*100


def enrich_fno_option_premiums(kite,stocks,max_stocks=35,batch_size=150):
    """Add one liquid, low-theta, bid-quantity-dominant option per selected stock."""
    if stocks is None or stocks.empty:
        return pd.DataFrame()
    instruments=pd.DataFrame(kite.instruments("NFO"))
    required={"name","instrument_type","expiry","strike","lot_size","tradingsymbol","instrument_token"}
    if instruments.empty or not required.issubset(instruments.columns):
        raise RuntimeError("NFO option instrument master is unavailable")
    now=datetime.now(IST); today=now.date()
    opts=instruments[instruments["instrument_type"].astype(str).isin(["CE","PE"])].copy()
    opts["expiry"]=pd.to_datetime(opts["expiry"],errors="coerce").dt.date
    opts=opts[opts["expiry"]>=today]
    selected_stocks=stocks.head(max_stocks).copy()
    names=selected_stocks["Stock"].astype(str).tolist()
    opts=opts[opts["name"].astype(str).isin(names)]
    if opts.empty:
        return pd.DataFrame()
    index_aliases={
        "NIFTY":"NIFTY 50",
        "BANKNIFTY":"NIFTY BANK",
        "FINNIFTY":"NIFTY FIN SERVICE",
        "MIDCPNIFTY":"NIFTY MID SELECT",
        "NIFTYNXT50":"NIFTY NEXT 50",
    }
    quote_names={name:index_aliases.get(name,name) for name in names}
    spot_keys=[f"NSE:{quote_names[name]}" for name in names]
    spots={}
    for i in range(0,len(spot_keys),batch_size):
        try: spots.update(kite.ltp(spot_keys[i:i+batch_size]))
        except Exception: pass
    candidates=[]
    for name in names:
        spot=float((spots.get(f"NSE:{quote_names[name]}") or {}).get("last_price") or 0)
        if spot<=0: continue
        rows=opts[opts["name"].astype(str).eq(name)]
        if rows.empty: continue
        # Use the trend-aligned side: BUY -> CE, SELL -> PE; WAIT stays unselected.
        signal=str(selected_stocks.loc[selected_stocks["Stock"].astype(str).eq(name),"Signal"].iloc[0])
        if signal not in ("BUY","SELL"): continue
        side="CE" if signal=="BUY" else "PE"
        rows=rows[rows["instrument_type"].eq(side)]
        if rows.empty: continue
        expiry=rows["expiry"].min()
        rows=rows[rows["expiry"].eq(expiry)].copy()
        strikes=sorted(float(x) for x in rows["strike"].dropna().unique())
        if not strikes: continue
        atm=min(strikes,key=lambda x:abs(x-spot))
        step=min((b-a for a,b in zip(strikes,strikes[1:]) if b>a),default=0)
        if step<=0: continue
        # ATM and up to 3 adjacent strikes on either side; lets liquidity/theta decide.
        allowed=[x for x in strikes if abs(x-atm)<=3*step]
        rows=rows[rows["strike"].astype(float).isin(allowed)]
        for row in rows.to_dict("records"):
            candidates.append((name,side,spot,row))
    keys=[f"NFO:{r[3]['tradingsymbol']}" for r in candidates]
    quotes={}
    for i in range(0,len(keys),batch_size):
        try: quotes.update(kite.quote(keys[i:i+batch_size]))
        except Exception: continue
    picks=[]
    for name,side,spot,row in candidates:
        q=quotes.get(f"NFO:{row['tradingsymbol']}",{})
        premium=float(q.get("last_price") or 0)
        volume=int(q.get("volume") or 0); oi=int(q.get("oi") or 0)
        depth=q.get("depth") or {}
        bids=(depth.get("buy") or [])
        asks=(depth.get("sell") or [])
        bid_qty=sum(int(x.get("quantity") or 0) for x in bids)
        ask_qty=sum(int(x.get("quantity") or 0) for x in asks)
        bid=float((bids[0] if bids else {}).get("price") or 0)
        ask=float((asks[0] if asks else {}).get("price") or 0)
        if premium<=0 or volume<=0 or oi<=0 or bid<=0 or ask<=0 or ask<bid or bid_qty<=0 or ask_qty<=0:
            continue
        stamp=q.get("timestamp") or q.get("last_trade_time")
        if not stamp: continue
        stamp=pd.Timestamp(stamp)
        if stamp.tzinfo is None: stamp=stamp.tz_localize(IST)
        if (pd.Timestamp(now)-stamp.tz_convert(IST)).total_seconds()>240: continue
        theta,iv=theta_per_day(spot,float(row["strike"]),row["expiry"],premium,side,now)
        if theta is None: continue
        spread=(ask-bid)/premium*100
        if spread>5: continue
        buyer_ratio=bid_qty/max(ask_qty,1)
        picks.append({
            "Stock":name,"Option Side":side,"Option Symbol":row["tradingsymbol"],
            "Option Expiry":str(row["expiry"]),"Option Strike":float(row["strike"]),
            "Option Premium":round(premium,2),"Option Theta / Day":round(theta,3),
            "Implied Volatility %":round(iv,2),"Buyer Bid Qty":bid_qty,
            "Seller Ask Qty":ask_qty,"Buyer Pressure":round(buyer_ratio,2),
            "Option Volume":volume,"Option OI":oi,"Option Spread %":round(spread,2),
            "Option Lot Size":int(row["lot_size"]),"Option Quote Time":str(stamp),
        })
    if not picks: return pd.DataFrame()
    frame=pd.DataFrame(picks)
    # Per stock: insist on stronger bid quantity than ask quantity; prefer low theta,
    # then stronger buyer pressure and OI, without pretending this is a live BUY order.
    frame=frame[frame["Buyer Pressure"]>=1.2]
    if frame.empty: return frame
    # Prefer the smallest absolute daily theta decay, then stronger displayed
    # bid-side depth, OI, volume and tighter spread for each unique underlying.
    frame["Absolute Theta / Day"] = frame["Option Theta / Day"].abs()
    frame=frame.sort_values(
        ["Stock","Absolute Theta / Day","Buyer Pressure","Option OI","Option Volume","Option Spread %"],
        ascending=[True,True,False,False,False,True]
    )
    return frame.drop_duplicates("Stock").drop(columns=["Absolute Theta / Day"]).reset_index(drop=True)
