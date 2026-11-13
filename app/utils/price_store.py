"""The shared daily-close store: read, record misses, record fetched prices.

Pure data access (a SQLAlchemy session in, plain values out) so it is tested
without a web app. The HTTP face is app/prices/routes.py; the filler that
fetches missing prices after the market closes is separate and uses upsert_closes
and mark_no_data.
"""
import calendar
from datetime import date, datetime, timedelta, timezone

from app import db
from app.models import DailyClose, PriceSymbol

# A weekend plus a holiday or two: a store that ends this close to the asked end
# is "current"; anything older is a miss for the filler to top up.
TAIL_SLACK_DAYS = 4
# Coverage ranges that touch (or sit within this many days) are merged.
JOIN_SLACK_DAYS = 7


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _epoch(day: date) -> int:
    """00:00 UTC of the date. OpenAlgo reads a daily bar's date as (epoch + 5h30m)
    in UTC, which lands on the right trading day for this value."""
    return calendar.timegm(day.timetuple())


def get_symbol(symbol: str, exchange: str) -> PriceSymbol | None:
    return db.session.get(PriceSymbol, (symbol, exchange))


def get_bars(symbol: str, exchange: str, start: date, end: date) -> list[dict]:
    """Stored closes for [start, end] as OpenAlgo history bars (close only)."""
    rows = (
        DailyClose.query.filter(
            DailyClose.symbol == symbol,
            DailyClose.exchange == exchange,
            DailyClose.trade_date >= start,
            DailyClose.trade_date <= end,
        )
        .order_by(DailyClose.trade_date.asc())
        .all()
    )
    return [{"timestamp": _epoch(r.trade_date), "close": r.close} for r in rows]


def is_covered(ps: PriceSymbol | None, start: date, end: date) -> bool:
    """True when the store already holds what was asked: it starts at or before
    `start` and ends within TAIL_SLACK_DAYS of `end`."""
    if ps is None or ps.covered_from is None or ps.covered_to is None:
        return False
    return ps.covered_from <= start and (end - ps.covered_to).days <= TAIL_SLACK_DAYS


def record_ask(symbol: str, exchange: str, start: date, end: date) -> bool:
    """Note that a caller asked for [start, end]; the one call the endpoint makes.

    Always remembers the latest end asked (asked_to). When the store cannot fully
    serve the range it also records a wish for the filler, widening any earlier
    one; a 'no_data' instrument is left alone. Returns True when a wish was
    recorded.
    """
    ps = get_symbol(symbol, exchange)
    if ps is None:
        ps = PriceSymbol(symbol=symbol, exchange=exchange, status="ok")
        db.session.add(ps)
    ps.asked_to = max(ps.asked_to, end) if ps.asked_to else end
    wished = False
    if ps.status != "no_data" and not is_covered(ps, start, end):
        ps.wanted_from = min(ps.wanted_from, start) if ps.wanted_from else start
        ps.wanted_to = max(ps.wanted_to, end) if ps.wanted_to else end
        ps.requested_at = _utcnow()
        wished = True
    db.session.commit()
    return wished


def upsert_closes(
    symbol: str,
    exchange: str,
    closes: dict[date, float],
    fetched_from: date,
    fetched_to: date,
) -> bool:
    """Store closes fetched for [fetched_from, fetched_to] and extend coverage.

    Coverage only grows when the new span touches the old one (within
    JOIN_SLACK_DAYS); a detached span is stored but not claimed, and the wish
    stays so the filler fetches the bridge. Returns whether coverage grew.
    Clears the wish once it is covered.
    """
    for day, close in closes.items():
        row = db.session.get(DailyClose, (symbol, exchange, day))
        if row is None:
            db.session.add(
                DailyClose(symbol=symbol, exchange=exchange, trade_date=day, close=float(close))
            )
        else:
            row.close = float(close)

    ps = get_symbol(symbol, exchange)
    if ps is None:
        ps = PriceSymbol(symbol=symbol, exchange=exchange, status="ok")
        db.session.add(ps)
    ps.status = "ok"
    ps.note = None
    ps.checked_at = _utcnow()

    grew = False
    if ps.covered_from is None or ps.covered_to is None:
        ps.covered_from, ps.covered_to = fetched_from, fetched_to
        grew = True
    else:
        slack = timedelta(days=JOIN_SLACK_DAYS)
        touches = fetched_from <= ps.covered_to + slack and fetched_to >= ps.covered_from - slack
        if touches:
            ps.covered_from = min(ps.covered_from, fetched_from)
            ps.covered_to = max(ps.covered_to, fetched_to)
            grew = True

    if grew and ps.wanted_from and ps.wanted_to:
        if ps.covered_from <= ps.wanted_from and (ps.wanted_to - ps.covered_to).days <= TAIL_SLACK_DAYS:
            ps.wanted_from = ps.wanted_to = ps.requested_at = None
    db.session.commit()
    return grew


def mark_no_data(symbol: str, exchange: str, note: str) -> None:
    """The source does not know this instrument: report it, stop retrying."""
    ps = get_symbol(symbol, exchange)
    if ps is None:
        ps = PriceSymbol(symbol=symbol, exchange=exchange)
        db.session.add(ps)
    ps.status = "no_data"
    ps.note = (note or "")[:200]
    ps.checked_at = _utcnow()
    db.session.commit()


def pending_wishes() -> list[PriceSymbol]:
    """Instruments the filler still has to fetch, oldest request first."""
    return (
        PriceSymbol.query.filter(PriceSymbol.status == "ok", PriceSymbol.wanted_from.isnot(None))
        .order_by(PriceSymbol.requested_at.asc())
        .all()
    )
