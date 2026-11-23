"""One price for every holding row, whichever account holds it.

A price belongs to the market, not to the account. The Holdings page used to
take each row's LTP from the holding's own account, which is wrong for an account
with no live broker behind it (a free Kite key, or the read-only acc2 archive):
their rows carry whatever price the last snapshot had. This module picks the
price from market-level sources instead:

* market open (weekday 09:15-15:30 IST): the designated source account's live
  quote (LTP and previous close together);
* weekday outside the session: the source quote (the official close). The store's
  newest bar is provisional until the next evening's re-fetch, so it is not
  preferred;
* weekend or holiday: the shared daily-close store (broker quotes are not trusted
  there: Kotak returned a wrong Saturday price once, see openalgo
  SKYSHIELD_PATCHES 2026-10-24);
* otherwise (store behind, quote missing): the quote, then the old stored close,
  then the account's own LTP, marked stale.

`pick_price` is pure so it can be tested without Flask or a database.
"""
import logging
from datetime import date, datetime, time, timedelta, timezone

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
LOOKBACK_DAYS = 10


def ist_now() -> datetime:
    return datetime.now(IST)


def market_open(now: datetime) -> bool:
    return now.weekday() < 5 and MARKET_OPEN <= now.time() < MARKET_CLOSE


def expected_close_date(now: datetime) -> date:
    """The latest session whose close should be in the store.

    After the bell today's close is expected, even though the evening filler has
    not run yet (that gap shows up as stale on purpose: the last bar is then the
    previous session's). Before the open, or on a weekend, it is the last weekday.
    A weekday exchange holiday makes this one day too late, so a stale mark can
    appear on a holiday; it is only a marker, never a number change.
    """
    day = now.date()
    if now.weekday() < 5 and now.time() >= MARKET_CLOSE:
        return day
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _positive(value) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def pick_price(account_ltp, source_quote, closes, now: datetime) -> dict:
    """Choose ltp / prev_close for one holding.

    account_ltp   the LTP in the account's own holdings row (may be stale)
    source_quote  {'ltp': .., 'prev_close': ..} from the source account, or None
    closes        [(date, close), ...] from the store, ascending (or None)
    now           timezone-aware IST datetime

    Returns {'ltp', 'prev_close', 'source', 'asof', 'stale'}; source is one of
    'live', 'close', 'quote', 'account'. prev_close is None when unknown.
    """
    sq_ltp = _positive((source_quote or {}).get('ltp'))
    sq_prev = _positive((source_quote or {}).get('prev_close'))
    bars = sorted((d, float(c)) for d, c in (closes or []) if _positive(c))
    is_open = market_open(now)

    if is_open and sq_ltp:
        prev = sq_prev
        if not prev and bars and bars[-1][0] < now.date():
            prev = bars[-1][1]
        return {'ltp': sq_ltp, 'prev_close': prev or None, 'source': 'live',
                'asof': now.isoformat(timespec='minutes'), 'stale': False}

    store_current = bool(bars) and bars[-1][0] >= expected_close_date(now)
    weekday = now.weekday() < 5

    # A weekday outside the session (evening, early morning): the source quote is
    # the official close, and the store's newest bar is only provisional. The
    # filler captures it at 15:45, before the exchange's close is final (stored
    # 23 Nov: CYIENT 1153.70 against a real 1160.50), and the next evening's
    # re-fetch is what corrects it.
    if weekday and not is_open and sq_ltp:
        return {'ltp': sq_ltp, 'prev_close': sq_prev or None, 'source': 'quote',
                'asof': now.isoformat(timespec='minutes'), 'stale': False}

    # Weekend or holiday: broker quotes are not trusted (Kotak returned a wrong
    # Saturday price), the store's last bar is the best number there is.
    if not is_open and store_current:
        prev = bars[-2][1] if len(bars) > 1 else None
        return {'ltp': bars[-1][1], 'prev_close': prev, 'source': 'close',
                'asof': bars[-1][0].isoformat(), 'stale': False}

    # The store is behind, or market hours without a live quote: any quote beats
    # showing an old close as if it were current.
    if sq_ltp:
        return {'ltp': sq_ltp, 'prev_close': sq_prev or None, 'source': 'quote',
                'asof': now.isoformat(timespec='minutes'), 'stale': True}

    if not is_open and bars:
        prev = bars[-2][1] if len(bars) > 1 else None
        return {'ltp': bars[-1][1], 'prev_close': prev, 'source': 'close',
                'asof': bars[-1][0].isoformat(), 'stale': True}

    return {'ltp': _positive(account_ltp) or None, 'prev_close': None, 'source': 'account',
            'asof': None, 'stale': True}


def latest_closes(keys, now: datetime) -> dict:
    """{(symbol, exchange): [(date, close), ...]} for the last LOOKBACK_DAYS days.

    One query for every held symbol. Never raises: a store problem must not take
    the Holdings page down, rows then fall back to their own price (marked stale).
    """
    symbols = {symbol for symbol, _ in keys if symbol}
    if not symbols:
        return {}
    try:
        from app.models import DailyClose
        rows = DailyClose.query.filter(
            DailyClose.symbol.in_(symbols),
            DailyClose.trade_date >= now.date() - timedelta(days=LOOKBACK_DAYS),
            DailyClose.trade_date <= now.date(),
        ).order_by(DailyClose.trade_date.asc()).all()
    except Exception as exc:
        logger.warning('Price store unavailable for holdings: %s', exc)
        return {}
    wanted = set(keys)
    out = {}
    for row in rows:
        key = (row.symbol, row.exchange)
        if key in wanted:
            out.setdefault(key, []).append((row.trade_date, row.close))
    return out


def empty_reply_to_ignore(response, cached, now: datetime) -> bool:
    """True when a holdings reply should NOT replace the cached holdings.

    A broker that is logged out (Kotak overnight, before the morning login) can
    answer `success` with no holdings and zero totals. Saved as the account's
    cache that wipes the last real holdings, and with them the account's strategy
    tags, the filter chips and the page rows, until the broker is live again
    (accounts 3, 4 and 5 at 00:00 IST on 24 Nov). An empty reply is trusted only
    while the market is open; otherwise the last non-empty cache is kept.
    """
    if not isinstance(response, dict) or response.get('status') != 'success':
        return False
    if (response.get('data') or {}).get('holdings'):
        return False
    previous = (cached or {}).get('holdings') if isinstance(cached, dict) else None
    return bool(previous) and not market_open(now)
