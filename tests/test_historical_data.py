from io import BytesIO
from zipfile import ZipFile
import pandas as pd
from historical_data import read_nse_bhavcopy

class Upload:
    name="sample.csv"
    def getvalue(self):
        return b"TradDt,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol,OpnIntrst,StrkPric,OptnTp,XpryDt\n2026-11-13,RELIANCE,EQ,100,110,95,108,50000,0,,,,\n2026-11-13,RELIANCE,BE,100,110,95,108,200,0,,,,"

def test_parse_nse_udiff_equity_bhavcopy_and_filter_eq():
    frame=read_nse_bhavcopy(Upload())
    assert len(frame)==1
    assert frame.iloc[0]["SYMBOL"]=="RELIANCE"
    assert frame.iloc[0]["CLOSE"]==108
    assert frame.iloc[0]["VOLUME"]==50000
    assert frame.iloc[0]["DATA_SOURCE"]=="NSE official bhavcopy upload"

def test_parse_nse_bhavcopy_zip():
    data=b"SYMBOL,SERIES,CLOSE,OPEN,HIGH,LOW,VOLUME\nSBIN,EQ,600,590,605,580,1000\n"
    buff=BytesIO()
    with ZipFile(buff,"w") as zf: zf.writestr("bhav.csv",data)
    class ZipUpload:
        name="sample.zip"
        def getvalue(self): return buff.getvalue()
    frame=read_nse_bhavcopy(ZipUpload())
    assert frame.iloc[0]["SYMBOL"]=="SBIN"
    assert frame.iloc[0]["CLOSE"]==600

def test_missing_required_fields_raise():
    class BadUpload:
        name="bad.csv"
        def getvalue(self): return b"FOO,BAR\n1,2\n"
    try:
        read_nse_bhavcopy(BadUpload())
        assert False
    except ValueError as exc:
        assert "missing required columns" in str(exc)
