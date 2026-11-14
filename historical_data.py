"""Historical market data helpers for NSE bhavcopy imports and Kite candle history."""
from io import BytesIO
from zipfile import ZipFile, BadZipFile
import pandas as pd


def read_nse_bhavcopy(uploaded_file):
    """Read an official NSE CM bhavcopy CSV or ZIP supplied by the user."""
    raw=uploaded_file.getvalue() if hasattr(uploaded_file,"getvalue") else uploaded_file
    name=getattr(uploaded_file,"name","").lower()
    try:
        if name.endswith(".zip") or raw[:2]==b"PK":
            with ZipFile(BytesIO(raw)) as zf:
                csv_names=[n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not csv_names:
                    raise ValueError("ZIP does not contain a CSV file")
                with zf.open(csv_names[0]) as f:
                    frame=pd.read_csv(f)
        else:
            frame=pd.read_csv(BytesIO(raw))
    except (BadZipFile,UnicodeDecodeError,pd.errors.ParserError) as exc:
        raise ValueError(f"Unable to read NSE bhavcopy file: {exc}") from exc
    frame.columns=[str(c).strip().upper() for c in frame.columns]
    aliases={
        "SYMBOL":["TCKRSYMB","SYMBOL","SYMBOL_NAME"],
        "DATE":["TRADDT","TIMESTAMP","DATE1","DATE"],
        "OPEN":["OPNPRIC","OPEN","OPEN_PRICE"],
        "HIGH":["HGHPRIC","HIGH","HIGH_PRICE"],
        "LOW":["LWPRIC","LOW","LOW_PRICE"],
        "CLOSE":["CLSPRIC","CLOSE","CLOSE_PRICE"],
        "VOLUME":["TOTTRDQTY","TTL_TRD_QNTY","TOTTRDQTY","VOLUME"],
        "SERIES":["SCTYSRS","SERIES"],
    }
    rename={}
    for target,choices in aliases.items():
        for col in choices:
            if col in frame.columns:
                rename[col]=target; break
    frame=frame.rename(columns=rename)
    required=["SYMBOL","CLOSE"]
    missing=[x for x in required if x not in frame.columns]
    if missing:
        raise ValueError(f"Bhavcopy missing required columns: {', '.join(missing)}")
    for col in ("OPEN","HIGH","LOW","CLOSE","VOLUME"):
        if col in frame:
            frame[col]=pd.to_numeric(frame[col],errors="coerce")
    if "DATE" in frame:
        frame["DATE"]=pd.to_datetime(frame["DATE"],errors="coerce",dayfirst=True)
    if "SERIES" in frame:
        frame=frame[frame["SERIES"].astype(str).str.upper().eq("EQ")]
    frame["SYMBOL"]=frame["SYMBOL"].astype(str).str.upper().str.strip()
    frame["DATA_SOURCE"]="NSE official bhavcopy upload"
    return frame.reset_index(drop=True)


def fetch_kite_historical(kite, symbols, start_date, end_date, interval="day"):
    """Fetch historical NSE equity candles using Kite's documented historical API."""
    instruments=pd.DataFrame(kite.instruments("NSE"))
    if instruments.empty:
        raise RuntimeError("Kite returned an empty NSE instrument master")
    token_map=dict(zip(instruments["tradingsymbol"].astype(str).str.upper(),instruments["instrument_token"]))
    results=[]
    for symbol in sorted({str(s).strip().upper() for s in symbols if str(s).strip()}):
        token=token_map.get(symbol)
        if token is None:
            continue
        candles=kite.historical_data(int(token),start_date,end_date,interval)
        if not candles:
            continue
        df=pd.DataFrame(candles)
        df["SYMBOL"]=symbol
        df["DATA_SOURCE"]="Kite historical candles (NSE instrument)"
        results.append(df)
    return pd.concat(results,ignore_index=True) if results else pd.DataFrame()
