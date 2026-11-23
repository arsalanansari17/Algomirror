#!/usr/bin/env python
"""Which price a Holdings row gets: live in the session, the stored close after it.

The case that started it: acc2's archived CYIENT lot carried LTP 1121.70 while the
market had it at 1160.50, so the Holdings page understated that row by about 3.8K.
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db
from app.models import DailyClose
from app.utils import holding_price as hp

IST = timezone(timedelta(hours=5, minutes=30))


def at(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)


# 2026-11-20 is a Friday, 2026-11-21/22 the weekend, 2026-11-23 a Monday.
FRI, MON = date(2026, 11, 20), date(2026, 11, 23)
CLOSES = [(date(2026, 11, 19), 1111.0), (FRI, 1155.5), (MON, 1160.5)]


def test_market_hours_use_the_source_quote():
    p = hp.pick_price(1121.7, {'ltp': 1160.5, 'prev_close': 1155.5}, CLOSES[:2], at(23, 11, 0))
    assert (p['ltp'], p['prev_close'], p['source'], p['stale']) == (1160.5, 1155.5, 'live', False)


def test_market_hours_without_prev_close_use_the_last_stored_bar():
    p = hp.pick_price(1121.7, {'ltp': 1160.5}, CLOSES[:2], at(23, 11, 0))
    assert p['prev_close'] == 1155.5 and p['source'] == 'live'


def test_after_the_filler_the_stored_close_wins_over_a_stale_account_price():
    # the acc2 archive case: account says 1121.70, the store has the real close
    p = hp.pick_price(1121.7, None, CLOSES, at(23, 17, 0))
    assert (p['ltp'], p['prev_close'], p['source'], p['stale']) == (1160.5, 1155.5, 'close', False)
    assert p['asof'] == '2026-11-23'


def test_off_hours_quotes_are_not_trusted_when_the_store_has_a_close():
    # Kotak once returned 1387.9 for CYIENT on a Saturday
    p = hp.pick_price(1121.7, {'ltp': 1387.9, 'prev_close': 1100.0}, CLOSES[:2], at(21, 12, 0))
    assert p['ltp'] == 1155.5 and p['source'] == 'close'


def test_between_the_bell_and_the_filler_a_quote_beats_yesterdays_close():
    # without this the Day's P&L would silently become yesterday's move
    p = hp.pick_price(1121.7, {'ltp': 1160.5, 'prev_close': 1155.5}, CLOSES[:2], at(23, 15, 45))
    assert (p['ltp'], p['prev_close'], p['source'], p['stale']) == (1160.5, 1155.5, 'quote', True)


def test_between_the_bell_and_the_filler_without_a_quote_the_old_close_is_flagged_stale():
    p = hp.pick_price(1121.7, None, CLOSES[:2], at(23, 15, 45))
    assert (p['ltp'], p['source'], p['stale']) == (1155.5, 'close', True)
    assert p['asof'] == '2026-11-20'


def test_a_store_stuck_two_sessions_back_does_not_win_over_a_quote():
    # the filler stopped updating once (17 to 19 Nov): the quote is the better number
    stuck = [(date(2026, 11, 17), 1086.1)]
    p = hp.pick_price(1121.7, {'ltp': 1160.5, 'prev_close': 1155.5}, stuck, at(23, 17, 0))
    assert (p['ltp'], p['source'], p['stale']) == (1160.5, 'quote', True)


def test_a_stuck_store_and_no_quote_still_shows_a_stale_close():
    stuck = [(date(2026, 11, 17), 1086.1)]
    p = hp.pick_price(1121.7, None, stuck, at(23, 17, 0))
    assert (p['ltp'], p['source'], p['stale']) == (1086.1, 'close', True)


def test_saturday_garbage_quote_loses_to_fridays_stored_close():
    p = hp.pick_price(1121.7, {'ltp': 1387.9, 'prev_close': 1100.0}, CLOSES[:2], at(21, 12, 0))
    assert (p['ltp'], p['source'], p['stale']) == (1155.5, 'close', False)


def test_weekend_with_fridays_close_is_not_stale():
    p = hp.pick_price(1121.7, None, CLOSES[:2], at(21, 12, 0))
    assert p['ltp'] == 1155.5 and p['stale'] is False


def test_before_the_open_yesterdays_close_is_current():
    p = hp.pick_price(1121.7, None, CLOSES[:2], at(23, 8, 0))
    assert p['stale'] is False


def test_single_bar_gives_no_prev_close():
    p = hp.pick_price(0, None, [(MON, 1160.5)], at(23, 17, 0))
    assert p['ltp'] == 1160.5 and p['prev_close'] is None


def test_no_store_data_falls_back_to_the_source_quote_marked_stale():
    p = hp.pick_price(1121.7, {'ltp': 1160.5, 'prev_close': 1155.5}, None, at(23, 17, 0))
    assert (p['ltp'], p['source'], p['stale']) == (1160.5, 'quote', True)


def test_nothing_available_keeps_the_account_price_marked_stale():
    p = hp.pick_price(1121.7, None, None, at(23, 17, 0))
    assert (p['ltp'], p['source'], p['stale']) == (1121.7, 'account', True)


def test_nothing_at_all_returns_no_price():
    p = hp.pick_price(0, None, None, at(23, 17, 0))
    assert p['ltp'] is None and p['stale'] is True


def test_live_market_without_a_source_quote_marks_the_account_price_stale():
    p = hp.pick_price(1160.0, None, CLOSES[:2], at(23, 11, 0))
    assert (p['ltp'], p['source'], p['stale']) == (1160.0, 'account', True)


@pytest.mark.parametrize('now, expected', [
    (at(23, 8, 0), FRI),                    # Monday before the open
    (at(23, 15, 30), MON),                  # at the bell
    (at(21, 12, 0), FRI),                   # Saturday
    (at(22, 20, 0), FRI),                   # Sunday
    (at(24, 10, 0), MON),                   # Tuesday morning
])
def test_expected_close_date(now, expected):
    assert hp.expected_close_date(now) == expected


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False, TESTING=True)
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(db.engine, tables=[DailyClose.__table__])
        yield app
        db.session.remove()


def test_latest_closes_groups_by_symbol_and_exchange_and_skips_old_days(app):
    rows = [
        ('CYIENT', 'NSE', date(2026, 11, 3), 1000.0),   # outside the lookback window
        ('CYIENT', 'NSE', FRI, 1155.5),
        ('CYIENT', 'NSE', MON, 1160.5),
        ('CYIENT', 'BSE', MON, 1159.0),                 # other exchange, not asked for
        ('OTHER', 'NSE', MON, 50.0),                    # not held
    ]
    for symbol, exchange, day, close in rows:
        db.session.add(DailyClose(symbol=symbol, exchange=exchange, trade_date=day, close=close))
    db.session.commit()
    out = hp.latest_closes({('CYIENT', 'NSE'), ('MISSING', 'NSE')}, at(23, 17, 0))
    assert out == {('CYIENT', 'NSE'): [(FRI, 1155.5), (MON, 1160.5)]}


def test_latest_closes_survives_a_missing_table():
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False, TESTING=True)
    db.init_app(app)
    with app.app_context():
        assert hp.latest_closes({('CYIENT', 'NSE')}, at(23, 17, 0)) == {}
