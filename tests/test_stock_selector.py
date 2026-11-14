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
