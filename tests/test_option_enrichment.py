from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from option_enrichment import implied_volatility, theta_per_day, _bs_price

IST=ZoneInfo("Asia/Kolkata")


def test_implied_volatility_recovers_model_volatility():
    spot=1000.0
    strike=1000.0
    t=30/365
    premium=_bs_price(spot,strike,t,0.07,0.25,"CE")
    iv=implied_volatility(premium,spot,strike,t,"CE")
    assert iv is not None
    assert abs(iv-0.25)<1e-5


def test_theta_is_negative_and_per_day_for_call():
    now=datetime(2026,1,1,12,0,tzinfo=IST)
    expiry=(now+timedelta(days=30)).date()
    t=30/365
    premium=_bs_price(1000,1000,t,0.07,0.25,"CE")
    theta,iv=theta_per_day(1000,1000,expiry,premium,"CE",now)
    assert theta is not None and theta<0
    assert 24.9<iv<25.1


def test_theta_rejects_intrinsic_only_or_expired_option():
    now=datetime(2026,1,1,12,0,tzinfo=IST)
    theta,iv=theta_per_day(1100,1000,now.date(),100,"CE",now)
    assert theta is None and iv is None
