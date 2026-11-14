import pandas as pd
import numpy as np
from stock_selector import headline_score, score_stock


def test_headline_score_neutral_when_no_matching_story():
    score, text = headline_score("Reliance Industries", "RELIANCE", ["US markets rally on tech shares"])
    assert score == 0
    assert text == "No matching headline found"


def test_headline_score_positive_for_relevant_positive_story():
    score, text = headline_score("Reliance Industries", "RELIANCE", ["Reliance Industries reports record profit growth"])
    assert score > 0
    assert "Reliance" in text


def test_stock_filter_rejects_insufficient_history():
    frame = pd.DataFrame({
        "Open": [100] * 20, "High": [102] * 20, "Low": [99] * 20,
        "Close": np.linspace(100, 110, 20), "Volume": [10000] * 20
    })
    assert score_stock(frame, "Example", "EXAMPLE", []) is None

from stock_selector import quote_is_usable

def test_rejects_zero_volume_quote():
    valid, reason = quote_is_usable({"last_price":100,"volume":0,"timestamp":pd.Timestamp.now(tz="Asia/Kolkata"),"depth":{"buy":[{"price":99}],"sell":[{"price":101}]}})
    assert not valid and "volume" in reason

def test_rejects_missing_bid_ask():
    valid, reason = quote_is_usable({"last_price":100,"volume":1000,"timestamp":pd.Timestamp.now(tz="Asia/Kolkata"),"depth":{"buy":[{"price":0}],"sell":[{"price":0}]}})
    assert not valid and "bid-ask" in reason

def test_rejects_old_quote():
    old=pd.Timestamp.now(tz="Asia/Kolkata")-pd.Timedelta(days=5)
    valid, reason = quote_is_usable({"last_price":100,"volume":1000,"timestamp":old,"depth":{"buy":[{"price":99.5}],"sell":[{"price":100.5}]}})
    assert not valid and "four days" in reason

def test_accepts_valid_quote():
    valid, reason = quote_is_usable({"last_price":100,"volume":1000,"timestamp":pd.Timestamp.now(tz="Asia/Kolkata"),"depth":{"buy":[{"price":99.5}],"sell":[{"price":100.5}]}})
    assert valid
