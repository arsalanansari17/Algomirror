"""Fills the shared daily-close store after the market closes.

The store (app/utils/price_store.py) never calls a broker; this is the one place
that does. It runs once an evening, inside a window that starts after the live
accounts have finished trading (15:40 IST) and ends before the primary account's
VM stops, and it asks the primary account's OpenAlgo for daily bars one
instrument at a time with a pause between calls, so a live account is never
loaded while it trades. Nothing runs at boot.

Two kinds of work, wishes first:

* a wish: a caller asked for a span the store does not hold (a new symbol, an
  earlier start), so the span is fetched;
* a top-up: a symbol callers still ask about up to today (an open position)
  has no bar for the latest days, so the last few days are fetched. A closed
  position is never asked about beyond its exit, so it is never topped up.

An instrument the source does not know is marked "no data" and reported, not
retried every evening. A source that keeps failing stops the run (a broker
outage must not turn into hundreds of failed calls).
"""
import logging
import os
import threading
import time as time_module
from datetime import date, datetime, time, timedelta, timezone

import httpx
import pytz

from app.models import PriceSymbol, TradingAccount
from app.utils import price_store

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")
WINDOW_START = time(15, 40)
WINDOW_END = time(16, 10)
# A second, short pass before the open. The 15:45 bar is only provisional (the exchange
# close is not final yet: 23 Nov stored CYIENT 1153.70 against a real 1160.50), and a
# later re-fetch corrects it exactly (verified at 00:40 on 24 Nov). The morning pass
# makes yesterday's bar final before the day's valuations read it, instead of at the
# next 15:45. It ends before 09:15, when the live accounts start trading.
MORNING_START = time(9, 0)
MORNING_END = time(9, 12)
PAUSE_SECONDS = 1.0
MAX_CONSECUTIVE_FAILURES = 5
REQUEST_TIMEOUT_SECONDS = 30
# Days re-fetched before the stored end, so a late correction to a recent bar lands.
OVERLAP_DAYS = 5
# A top-up covers symbols asked about within this many days of today (a long weekend
# plus a day), so an open position stays current while nobody opens the pages.
RECENT_ASK_DAYS = 5

_run_lock = threading.Lock()


def in_window(now_ist: datetime) -> bool:
    """A weekday, in the evening window (WINDOW_START to WINDOW_END) or the morning one
    (MORNING_START to MORNING_END), IST."""
    if now_ist.weekday() >= 5:
        return False
    t = now_ist.time()
    return WINDOW_START <= t < WINDOW_END or MORNING_START <= t < MORNING_END


def last_final_session(now_ist: datetime) -> date:
    """The latest day a run may fetch a bar for (and claim coverage through).

    Today once the evening window has opened on a weekday (15:40), otherwise the
    previous weekday. A bar for a day whose session has not finished does not exist
    yet; fetching "up to today" before the close would still set the stored coverage
    to today, and the evening top-up (which looks for coverage older than today) would
    then find nothing to fetch and the store would have no bar for today all evening.
    """
    day = now_ist.date()
    if now_ist.weekday() < 5 and now_ist.time() >= WINDOW_START:
        return day
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def plan_range(ps, today: date) -> tuple[date, date] | None:
    """The span to fetch for one instrument, or None when it needs nothing."""
    if ps.status != "ok":
        return None
    overlap = timedelta(days=OVERLAP_DAYS)
    if ps.wanted_from and ps.wanted_to:
        if ps.covered_from is None or ps.covered_to is None or ps.wanted_from < ps.covered_from:
            return ps.wanted_from, ps.wanted_to
        return max(ps.wanted_from, ps.covered_to - overlap), ps.wanted_to
    if ps.asked_to and ps.covered_to and ps.asked_to >= today - timedelta(days=RECENT_ASK_DAYS):
        # Up to today, not up to the last day anyone asked for: nobody has to open a
        # page for a held symbol to stay current (on 2026-11-18 the store stopped at
        # the 17th because the last ask was the 17th, and the pages valued open lots
        # at the 17th's close for two days).
        if ps.covered_to < today:
            return ps.covered_to - overlap, today
    return None


def pending_work(today: date) -> list[tuple]:
    """(symbol, exchange, from, to), wishes first (oldest request first), then
    top-ups. Each instrument appears once."""
    work = []
    seen = set()
    for ps in price_store.pending_wishes():
        span = plan_range(ps, today)
        if span:
            work.append((ps.symbol, ps.exchange, *span))
            seen.add((ps.symbol, ps.exchange))
    for ps in PriceSymbol.query.filter(
        PriceSymbol.status == "ok", PriceSymbol.asked_to.isnot(None), PriceSymbol.covered_to.isnot(None)
    ).all():
        if (ps.symbol, ps.exchange) in seen:
            continue
        span = plan_range(ps, today)
        if span:
            work.append((ps.symbol, ps.exchange, *span))
    return work


def _bars_to_closes(records) -> dict[date, float]:
    out = {}
    for rec in records or []:
        try:
            ts = int(rec["timestamp"])
            close = float(rec["close"])
        except (KeyError, TypeError, ValueError):
            continue
        out[datetime.fromtimestamp(ts + 19800, tz=timezone.utc).date()] = close
    return out


def make_fetcher(account):
    """A fetch(symbol, exchange, start, end) bound to one account's OpenAlgo.

    Returns ("ok", {date: close}), ("no_data", message) when the source does not
    know the instrument, or ("error", message) when it could not answer."""
    host = account.host_url.rstrip("/")
    api_key = account.get_api_key()

    def fetch(symbol: str, exchange: str, start: date, end: date):
        try:
            response = httpx.post(
                host + "/api/v1/history",
                json={
                    "apikey": api_key,
                    "symbol": symbol,
                    "exchange": exchange,
                    "interval": "D",
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            body = response.json()
        except Exception as exc:
            return "error", type(exc).__name__
        if response.status_code == 200 and isinstance(body, dict) and body.get("status") == "success":
            return "ok", _bars_to_closes(body.get("data"))
        message = str(body.get("message", "")) if isinstance(body, dict) else ""
        lowered = message.lower()
        if response.status_code in (400, 404) and ("not found" in lowered or "no data" in lowered):
            return "no_data", message[:200]
        return "error", f"http {response.status_code}"

    return fetch


def source_account():
    """The account whose OpenAlgo serves the history: PRICE_SOURCE_ACCOUNT_ID, else
    the active primary account."""
    wanted = os.environ.get("PRICE_SOURCE_ACCOUNT_ID")
    if wanted and wanted.isdigit():
        return TradingAccount.query.filter_by(id=int(wanted), is_active=True).first()
    return TradingAccount.query.filter_by(is_primary=True, is_active=True).first()


def run(fetch, now_fn=None, sleep=time_module.sleep, force: bool = False) -> dict:
    """One filling pass. Outside the window it does nothing unless `force` (a
    manual first backfill, started by a person at a quiet hour).

    Returns counts: ok, no_data, errors, left, stopped (why it ended early)."""
    now_fn = now_fn or (lambda: datetime.now(IST))
    summary = {"ok": 0, "no_data": 0, "errors": 0, "left": 0, "stopped": None}
    if not _run_lock.acquire(blocking=False):
        summary["stopped"] = "already running"
        return summary
    try:
        if not force and not in_window(now_fn()):
            summary["stopped"] = "outside the window"
            return summary
        started = now_fn()
        work = pending_work(started.date())
        cap = last_final_session(started)
        failures = 0
        for index, (symbol, exchange, start, end) in enumerate(work):
            if not force and not in_window(now_fn()):
                summary["stopped"] = "window closed"
                summary["left"] = len(work) - index
                return summary
            end = min(end, cap)
            if end < start:
                continue
            status, payload = fetch(symbol, exchange, start, end)
            if status == "ok":
                if not payload:
                    # No bars. For an instrument never stored that is "the source does
                    # not know it"; for one already stored it is a bad answer (a held
                    # stock always has bars in the overlap), so change nothing and retry.
                    known = price_store.get_symbol(symbol, exchange)
                    if known is None or known.covered_from is None:
                        failures = 0
                        price_store.mark_no_data(symbol, exchange, "source returned no bars")
                        summary["no_data"] += 1
                    else:
                        failures += 1
                        summary["errors"] += 1
                        logger.warning("Price fill: %s:%s returned no bars", exchange, symbol)
                        if failures >= MAX_CONSECUTIVE_FAILURES:
                            summary["stopped"] = "source keeps failing"
                            summary["left"] = len(work) - index - 1
                            return summary
                else:
                    failures = 0
                    price_store.upsert_closes(symbol, exchange, payload, start, end)
                    summary["ok"] += 1
            elif status == "no_data":
                failures = 0
                price_store.mark_no_data(symbol, exchange, payload)
                summary["no_data"] += 1
            else:
                failures += 1
                summary["errors"] += 1
                logger.warning("Price fill: %s:%s failed (%s)", exchange, symbol, payload)
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    summary["stopped"] = "source keeps failing"
                    summary["left"] = len(work) - index - 1
                    return summary
            sleep(PAUSE_SECONDS)
        return summary
    finally:
        _run_lock.release()


def run_scheduled(app) -> None:
    """The scheduler's entry: one pass for the active primary account."""
    with app.app_context():
        account = source_account()
        if account is None:
            logger.warning("Price fill skipped: no active source account")
            return
        summary = run(make_fetcher(account))
        # Fields spelled out: a dict as the only logging argument is read as a
        # mapping for %-formatting, which raised and lost this line.
        text = ", ".join(f"{key}={value}" for key, value in summary.items())
        if summary["errors"] or summary["stopped"]:
            logger.warning("Price fill finished with problems: %s", text)
        else:
            logger.info("Price fill finished: %s", text)


_scheduler = None


def start_scheduler(app) -> None:
    """Run the evening fill at 15:45 IST on weekdays, once per process. Off
    unless PRICE_FILLER_ENABLED=1 (see create_app)."""
    global _scheduler
    if _scheduler is not None:
        return
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    _scheduler = BackgroundScheduler(timezone=IST)
    _scheduler.add_job(
        run_scheduled,
        trigger=CronTrigger(day_of_week="mon-fri", hour=15, minute=45, timezone=IST),
        args=[app],
        id="price_fill",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
        replace_existing=True,
    )
    _scheduler.add_job(
        run_scheduled,
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=3, timezone=IST),
        args=[app],
        id="price_fill_morning",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Price fill scheduled for 09:03 and 15:45 IST on weekdays")
