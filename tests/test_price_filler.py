#!/usr/bin/env python
"""The evening filler: what it plans, when it may run, and how it stops.

Only the broker call, the clock and the sleep are faked; planning, the window
and the store run for real on an in-memory SQLite.
"""
import os
import sys
from datetime import date, datetime

import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db
from app.models import DailyClose, PriceSymbol
from app.utils import price_filler, price_store

IST = price_filler.IST
FRI = date(2026, 11, 13)
# Friday 15:50 IST, inside the window
NOW = IST.localize(datetime(2026, 11, 13, 15, 50))
START, END = date(2026, 11, 2), date(2026, 11, 6)
BARS = {date(2026, 11, 3): 100.5, date(2026, 11, 4): 101.5}


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite://", SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(db.engine, tables=[DailyClose.__table__, PriceSymbol.__table__])
        yield app
        db.session.remove()


class Fetcher:
    """Answers per symbol from a dict of (status, payload); records every call."""

    def __init__(self, answers=None, default=("ok", BARS)):
        self.answers = answers or {}
        self.default = default
        self.calls = []

    def __call__(self, symbol, exchange, start, end):
        self.calls.append((symbol, exchange, start, end))
        return self.answers.get(symbol, self.default)


def _run(fetcher, now=NOW, force=False):
    sleeps = []
    summary = price_filler.run(fetcher, now_fn=lambda: now, sleep=sleeps.append, force=force)
    return summary, sleeps


def _wish(symbol, start=START, end=END):
    price_store.record_ask(symbol, "NSE", start, end)


# --- window ----------------------------------------------------------------


def test_window_is_a_weekday_after_the_close_and_before_the_vm_stops():
    assert price_filler.in_window(IST.localize(datetime(2026, 11, 13, 15, 40)))
    assert price_filler.in_window(IST.localize(datetime(2026, 11, 13, 16, 9)))
    assert not price_filler.in_window(IST.localize(datetime(2026, 11, 13, 15, 39)))
    assert not price_filler.in_window(IST.localize(datetime(2026, 11, 13, 16, 10)))
    assert not price_filler.in_window(IST.localize(datetime(2026, 11, 14, 15, 50)))  # Saturday
    assert not price_filler.in_window(IST.localize(datetime(2026, 11, 13, 9, 30)))  # trading


def test_outside_the_window_nothing_is_fetched(app):
    _wish("ABC")
    fetcher = Fetcher()

    summary, _ = _run(fetcher, now=IST.localize(datetime(2026, 11, 13, 11, 0)))

    assert fetcher.calls == []
    assert summary["stopped"] == "outside the window"


def test_force_runs_outside_the_window_for_a_manual_backfill(app):
    _wish("ABC")
    fetcher = Fetcher()

    summary, _ = _run(fetcher, now=IST.localize(datetime(2026, 11, 14, 11, 0)), force=True)

    assert len(fetcher.calls) == 1
    assert summary["ok"] == 1


def test_the_run_stops_when_the_window_closes_mid_way(app):
    for symbol in ("A", "B", "C"):
        _wish(symbol)
    clock = iter(
        [
            NOW,  # entry check
            NOW,  # work date
            NOW,  # before A
            NOW,  # before B
            IST.localize(datetime(2026, 11, 13, 16, 10)),  # before C: closed
        ]
    )
    fetcher = Fetcher()

    summary = price_filler.run(fetcher, now_fn=lambda: next(clock), sleep=lambda s: None)

    assert [c[0] for c in fetcher.calls] == ["A", "B"]
    assert summary["stopped"] == "window closed"
    assert summary["left"] == 1


# --- what gets fetched -----------------------------------------------------


def test_a_wish_is_fetched_and_stored_then_not_fetched_again(app):
    _wish("ABC")
    fetcher = Fetcher()

    summary, sleeps = _run(fetcher)

    assert fetcher.calls == [("ABC", "NSE", START, END)]
    assert summary["ok"] == 1
    assert [b["close"] for b in price_store.get_bars("ABC", "NSE", START, END)] == [100.5, 101.5]
    assert sleeps == [price_filler.PAUSE_SECONDS]
    assert price_store.pending_wishes() == []

    again = Fetcher()
    _run(again)
    assert again.calls == []


def test_a_wish_for_an_earlier_start_fetches_the_whole_wanted_span(app):
    price_store.upsert_closes("ABC", "NSE", BARS, date(2026, 11, 2), date(2026, 11, 6))
    _wish("ABC", start=date(2026, 10, 1), end=date(2026, 11, 6))
    fetcher = Fetcher()

    _run(fetcher)

    assert fetcher.calls == [("ABC", "NSE", date(2026, 10, 1), date(2026, 11, 6))]


def test_a_wish_for_a_later_end_fetches_only_the_tail(app):
    price_store.upsert_closes("ABC", "NSE", BARS, date(2026, 11, 2), date(2026, 11, 6))
    _wish("ABC", start=date(2026, 11, 2), end=date(2026, 11, 20))
    fetcher = Fetcher()

    _run(fetcher)

    assert fetcher.calls == [("ABC", "NSE", date(2026, 11, 2), date(2026, 11, 20))]


def test_an_open_position_gets_a_daily_top_up_but_a_closed_one_does_not(app):
    # both fully covered up to Thursday; OPEN is still asked about up to today, CLOSED only to its exit
    for symbol in ("OPEN", "CLOSED"):
        price_store.upsert_closes(symbol, "NSE", BARS, date(2026, 11, 2), date(2026, 11, 12))
    price_store.record_ask("OPEN", "NSE", date(2026, 11, 2), FRI)
    price_store.record_ask("CLOSED", "NSE", date(2026, 11, 2), date(2026, 11, 6))
    fetcher = Fetcher()

    _run(fetcher)

    assert fetcher.calls == [("OPEN", "NSE", date(2026, 11, 7), FRI)]


def test_a_symbol_nobody_asks_about_any_more_is_not_topped_up(app):
    price_store.upsert_closes("OLD", "NSE", BARS, date(2026, 11, 2), date(2026, 11, 6))
    price_store.record_ask("OLD", "NSE", date(2026, 11, 2), date(2026, 11, 6))
    fetcher = Fetcher()

    _run(fetcher)

    assert fetcher.calls == []


def test_wishes_come_before_top_ups_and_each_symbol_is_fetched_once(app):
    price_store.upsert_closes("OPEN", "NSE", BARS, date(2026, 11, 2), date(2026, 11, 12))
    price_store.record_ask("OPEN", "NSE", date(2026, 11, 2), FRI)
    _wish("NEW")
    fetcher = Fetcher()

    _run(fetcher)

    assert [c[0] for c in fetcher.calls] == ["NEW", "OPEN"]


# --- how it ends -----------------------------------------------------------


def test_an_unknown_instrument_is_marked_no_data_and_not_retried(app):
    _wish("HEG")
    fetcher = Fetcher({"HEG": ("no_data", "symbol not found")})

    summary, _ = _run(fetcher)

    assert summary["no_data"] == 1
    assert price_store.get_symbol("HEG", "NSE").status == "no_data"
    assert price_store.get_symbol("HEG", "NSE").note == "symbol not found"
    again = Fetcher()
    _run(again)
    assert again.calls == []


def test_an_empty_answer_for_a_never_stored_symbol_is_no_data(app):
    _wish("NEW", start=date(2026, 1, 1), end=END)

    summary, _ = _run(Fetcher(default=("ok", {})))

    assert summary["no_data"] == 1
    assert price_store.get_symbol("NEW", "NSE").status == "no_data"


def test_an_empty_answer_for_a_stored_symbol_changes_nothing_and_is_retried(app):
    price_store.upsert_closes("HELD", "NSE", BARS, START, date(2026, 11, 12))
    price_store.record_ask("HELD", "NSE", START, FRI)

    summary, _ = _run(Fetcher(default=("ok", {})))

    held = price_store.get_symbol("HELD", "NSE")
    assert summary["errors"] == 1 and summary["no_data"] == 0
    assert held.status == "ok" and held.covered_to == date(2026, 11, 12)  # not extended, not retired
    retry = Fetcher()
    _run(retry)
    assert len(retry.calls) == 1  # tried again next time


def test_a_failing_source_stops_the_run_after_a_few_failures(app):
    for index in range(10):
        _wish(f"S{index:02d}")
    fetcher = Fetcher(default=("error", "http 500"))

    summary, _ = _run(fetcher)

    assert len(fetcher.calls) == price_filler.MAX_CONSECUTIVE_FAILURES
    assert summary["stopped"] == "source keeps failing"
    assert summary["errors"] == price_filler.MAX_CONSECUTIVE_FAILURES
    assert summary["left"] == 10 - price_filler.MAX_CONSECUTIVE_FAILURES
    assert len(price_store.pending_wishes()) == 10  # nothing lost; tomorrow tries again


def test_an_isolated_failure_does_not_stop_the_run(app):
    for symbol in ("A", "B", "C"):
        _wish(symbol)
    fetcher = Fetcher({"B": ("error", "http 500")})

    summary, _ = _run(fetcher)

    assert summary["ok"] == 2 and summary["errors"] == 1 and summary["stopped"] is None
    assert [p.symbol for p in price_store.pending_wishes()] == ["B"]


def test_a_second_run_at_the_same_time_does_nothing(app):
    _wish("ABC")
    assert price_filler._run_lock.acquire(blocking=False)
    try:
        summary, _ = _run(Fetcher())
    finally:
        price_filler._run_lock.release()

    assert summary["stopped"] == "already running"


# --- the fetcher -----------------------------------------------------------


class _Resp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class _Account:
    host_url = "https://primary.example/"

    def get_api_key(self):
        return "secret-key"


def _fetch_with(monkeypatch, response=None, error=None):
    posted = []

    def fake_post(url, json=None, timeout=None):
        posted.append({"url": url, "json": json, "timeout": timeout})
        if error:
            raise error
        return response

    monkeypatch.setattr(price_filler.httpx, "post", fake_post)
    return price_filler.make_fetcher(_Account()), posted


def test_the_fetcher_posts_to_the_accounts_history_and_reads_the_bars(monkeypatch):
    bars = [{"timestamp": 1793664000, "close": 100.5}, {"timestamp": 1793750400, "close": 101.5}]
    fetch, posted = _fetch_with(monkeypatch, _Resp(200, {"status": "success", "data": bars}))

    status, closes = fetch("ABC", "NSE", START, END)

    assert (status, closes) == ("ok", {date(2026, 11, 3): 100.5, date(2026, 11, 4): 101.5})
    assert posted[0]["url"] == "https://primary.example/api/v1/history"
    assert posted[0]["json"]["interval"] == "D"
    assert posted[0]["json"]["start_date"] == "2026-11-02"
    assert posted[0]["timeout"] == price_filler.REQUEST_TIMEOUT_SECONDS


def test_the_fetcher_tells_an_unknown_symbol_from_a_broker_failure(monkeypatch):
    fetch, _ = _fetch_with(
        monkeypatch, _Resp(400, {"status": "error", "message": "Symbol 'HEG' not found for exchange 'NSE'."})
    )
    assert fetch("HEG", "NSE", START, END)[0] == "no_data"

    fetch, _ = _fetch_with(monkeypatch, _Resp(500, {"status": "error", "message": "boom"}))
    assert fetch("ABC", "NSE", START, END)[0] == "error"

    fetch, _ = _fetch_with(monkeypatch, error=TimeoutError("slow"))
    assert fetch("ABC", "NSE", START, END) == ("error", "TimeoutError")


def test_the_api_key_is_never_in_what_the_fetcher_returns(monkeypatch):
    fetch, _ = _fetch_with(monkeypatch, error=RuntimeError("secret-key leaked here"))

    assert "secret-key" not in str(fetch("ABC", "NSE", START, END))
