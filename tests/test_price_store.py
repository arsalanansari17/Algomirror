#!/usr/bin/env python
"""The shared daily-close store and its OpenAlgo-compatible history endpoint.

A bare Flask app with an in-memory SQLite and only the two price tables, so the
store logic and the endpoint run for real without the rest of AlgoMirror.
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db
from app.models import DailyClose, PriceSymbol
from app.prices import prices_bp
from app.utils import price_store

KEY = "test-store-key"
START, END = date(2026, 11, 2), date(2026, 11, 6)
CLOSES = {date(2026, 11, 3): 100.5, date(2026, 11, 4): 101.5}


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("PRICE_STORE_API_KEY", KEY)
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite://",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
    )
    db.init_app(app)
    app.register_blueprint(prices_bp)
    with app.app_context():
        db.metadata.create_all(db.engine, tables=[DailyClose.__table__, PriceSymbol.__table__])
        yield app
        db.session.remove()


def _post(app, **overrides):
    body = {
        "apikey": KEY,
        "symbol": "ABC",
        "exchange": "NSE",
        "interval": "D",
        "start_date": START.isoformat(),
        "end_date": END.isoformat(),
    }
    body.update(overrides)
    return app.test_client().post("/prices/api/v1/history", json=body)


def _fill(symbol="ABC", exchange="NSE", closes=CLOSES, start=START, end=END):
    price_store.upsert_closes(symbol, exchange, closes, start, end)


# --- store ---------------------------------------------------------------


def test_stored_closes_come_back_as_bars_openalgo_reads_to_the_same_day(app):
    _fill()
    bars = price_store.get_bars("ABC", "NSE", START, END)

    assert [b["close"] for b in bars] == [100.5, 101.5]
    # OpenAlgo's _bars_to_closes: date = utc(epoch + 5h30m)
    days = [datetime.fromtimestamp(b["timestamp"] + 19800, tz=timezone.utc).date() for b in bars]
    assert days == [date(2026, 11, 3), date(2026, 11, 4)]


def test_get_bars_only_returns_the_asked_range_and_instrument(app):
    _fill()
    _fill(symbol="OTHER", closes={date(2026, 11, 3): 9.0})

    bars = price_store.get_bars("ABC", "NSE", date(2026, 11, 4), END)

    assert [b["close"] for b in bars] == [101.5]


def test_a_refetched_day_replaces_the_stored_close(app):
    _fill()
    _fill(closes={date(2026, 11, 4): 111.0})

    assert [b["close"] for b in price_store.get_bars("ABC", "NSE", START, END)] == [100.5, 111.0]


def test_coverage_grows_when_the_new_span_touches_the_old(app):
    _fill(start=date(2026, 11, 1), end=date(2026, 11, 6))
    grew = price_store.upsert_closes("ABC", "NSE", {}, date(2026, 11, 7), date(2026, 11, 12))

    ps = price_store.get_symbol("ABC", "NSE")
    assert grew
    assert (ps.covered_from, ps.covered_to) == (date(2026, 11, 1), date(2026, 11, 12))


def test_a_detached_span_is_stored_but_not_claimed_as_covered(app):
    _fill(start=date(2026, 11, 1), end=date(2026, 11, 6))
    grew = price_store.upsert_closes(
        "ABC", "NSE", {date(2026, 12, 20): 5.0}, date(2026, 12, 15), date(2026, 12, 25)
    )

    ps = price_store.get_symbol("ABC", "NSE")
    assert not grew
    assert ps.covered_to == date(2026, 11, 6)
    assert len(price_store.get_bars("ABC", "NSE", date(2026, 12, 1), date(2026, 12, 31))) == 1


def test_is_covered_tolerates_a_weekend_at_the_end_but_not_a_longer_gap(app):
    _fill(start=date(2026, 11, 1), end=date(2026, 11, 6))
    ps = price_store.get_symbol("ABC", "NSE")

    assert price_store.is_covered(ps, date(2026, 11, 2), date(2026, 11, 9))  # 3 days after
    assert not price_store.is_covered(ps, date(2026, 11, 2), date(2026, 11, 20))
    assert not price_store.is_covered(ps, date(2026, 10, 1), date(2026, 11, 6))  # starts earlier
    assert not price_store.is_covered(None, START, END)


def test_a_wish_is_recorded_widened_and_cleared_once_covered(app):
    assert price_store.record_ask("ABC", "NSE", date(2026, 11, 2), date(2026, 11, 6))
    assert price_store.record_ask("ABC", "NSE", date(2026, 10, 1), date(2026, 11, 3))
    ps = price_store.get_symbol("ABC", "NSE")
    assert (ps.wanted_from, ps.wanted_to) == (date(2026, 10, 1), date(2026, 11, 6))
    assert [p.symbol for p in price_store.pending_wishes()] == ["ABC"]

    _fill(start=date(2026, 10, 1), end=date(2026, 11, 6))

    assert price_store.pending_wishes() == []


def test_no_data_instruments_are_not_asked_for_again(app):
    price_store.mark_no_data("HEG", "NSE", "symbol not found")

    assert not price_store.record_ask("HEG", "NSE", START, END)
    assert price_store.pending_wishes() == []
    assert price_store.get_symbol("HEG", "NSE").status == "no_data"


def test_fetching_a_no_data_instrument_later_revives_it(app):
    price_store.mark_no_data("ABC", "NSE", "symbol not found")
    _fill()

    assert price_store.get_symbol("ABC", "NSE").status == "ok"


# --- endpoint ------------------------------------------------------------


def test_endpoint_serves_stored_bars_in_the_openalgo_shape(app):
    _fill()

    response = _post(app)

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert [b["close"] for b in body["data"]] == [100.5, 101.5]
    assert set(body["data"][0]) == {"timestamp", "close"}


def test_endpoint_rejects_a_wrong_or_missing_key_without_echoing_it(app):
    _fill()

    for key in ("wrong", ""):
        response = _post(app, apikey=key)
        assert response.status_code == 401
        assert KEY not in response.get_data(as_text=True)
        assert "wrong" not in response.get_data(as_text=True)


def test_endpoint_is_off_when_no_key_is_configured(app, monkeypatch):
    monkeypatch.delenv("PRICE_STORE_API_KEY", raising=False)

    assert _post(app).status_code == 503


def test_an_unknown_instrument_is_a_404_and_becomes_a_wish(app):
    response = _post(app, symbol="NEWCO")

    assert response.status_code == 404
    assert response.get_json()["status"] == "error"
    assert [(p.symbol, p.wanted_from, p.wanted_to) for p in price_store.pending_wishes()] == [
        ("NEWCO", START, END)
    ]


def test_a_partly_covered_range_serves_what_it_has_and_records_the_rest(app):
    _fill(start=date(2026, 11, 3), end=date(2026, 11, 6))

    response = _post(app, start_date="2026-10-01")

    assert response.status_code == 200
    assert len(response.get_json()["data"]) == 2
    ps = price_store.get_symbol("ABC", "NSE")
    assert ps.wanted_from == date(2026, 10, 1)


def test_a_fully_covered_request_records_no_wish(app):
    _fill()

    _post(app)

    assert price_store.pending_wishes() == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"symbol": ""},
        {"exchange": ""},
        {"start_date": "not-a-date"},
        {"end_date": "2020-01-01"},
        {"interval": "1m"},
    ],
)
def test_bad_requests_are_400(app, overrides):
    assert _post(app, **overrides).status_code == 400


def test_a_non_json_body_is_400(app):
    response = app.test_client().post("/prices/api/v1/history", data="x")

    assert response.status_code == 400


def test_symbol_and_exchange_are_case_insensitive(app):
    _fill()

    assert _post(app, symbol="abc", exchange="nse").status_code == 200


def test_the_latest_end_asked_is_remembered_even_when_fully_covered(app):
    _fill()

    _post(app, end_date="2026-11-05")
    _post(app, end_date="2026-11-06")
    _post(app, end_date="2026-11-04")

    assert price_store.get_symbol("ABC", "NSE").asked_to == date(2026, 11, 6)
