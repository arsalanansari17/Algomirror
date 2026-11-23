"""Value the P&L Analysis's open holdings with the Holdings page's price chain.

The two pages answer the same question (what are the open holdings worth against
what was paid), so they must give one number. They did not:

* Holdings priced each row from the market (live quote, then the official close),
  the P&L page from the stored daily close, whose newest bar is provisional until
  the next evening's re-fetch (23 Nov: CYIENT stored 1153.70 against a real 1160.50);
* Holdings costs a lot at the broker's average, the P&L page's curve rebuilt it from
  fills (FIFO) and counted lots the broker no longer holds.

Here the PRICE part is made the same: each account's open rows (OpenAlgo's
`/pnl/history` rows, the broker's own holdings) are repriced at the chain's price, and
the difference to the price OpenAlgo used is added to the curve's LAST unrealized level,
per strategy. Only holdings that belong to a strategy (from the strategy book or a
manual tag, the Holdings page's own strategy chips) move the curve: old holdings with
no fills in the ledger (IDEAFORGE, acc2's legacy stocks) were never in the curve and
must not suddenly enter it. History before the last day stays as the store has it
(those bars are final); realized P&L and the cost basis are untouched.

Pure functions plus `build_price_of`, the one piece that touches the store and the
source account's quotes.
"""
import logging

from app.utils import holding_price

logger = logging.getLogger(__name__)

UNTAGGED = 'Untagged'


def pick_source_account(accounts, source_host):
    """The account whose quotes supply market prices (QUOTE_SOURCE_HOST in its host_url)."""
    source_host = (source_host or '').lower()
    if not source_host:
        return None
    return next((a for a in accounts if source_host in (getattr(a, 'host_url', '') or '').lower()), None)


def fetch_source_quotes(source_account, keys) -> dict:
    """{(symbol, exchange): {'ltp', 'prev_close'}} from the source account; {} on any failure."""
    if source_account is None or not keys:
        return {}
    try:
        from app.utils.openalgo_client import ExtendedOpenAlgoAPI
        client = ExtendedOpenAlgoAPI(api_key=source_account.get_api_key(), host=source_account.host_url)
        reply = client.multiquotes(symbols=[{'symbol': s, 'exchange': e} for s, e in sorted(keys)])
        if not reply or reply.get('status') != 'success':
            return {}
        out = {}
        for item in reply.get('results', []) or []:
            data = item.get('data') or {}
            out[(item.get('symbol'), item.get('exchange'))] = {
                'ltp': data.get('ltp'), 'prev_close': data.get('prev_close')}
        return out
    except Exception as exc:
        logger.warning('Source quotes unavailable for the P&L revaluation: %s', exc)
        return {}


def build_price_of(keys, source_account, now=None):
    """price_of(symbol, exchange) -> pick_price result, or None when only a stale
    account price would be available (the caller then keeps OpenAlgo's valuation)."""
    now = now or holding_price.ist_now()
    keys = {key for key in keys if key[0]}
    closes = holding_price.latest_closes(keys, now) if keys else {}
    # Quotes are only used on weekdays (live, or the official close in the evening);
    # weekends are the store's, see holding_price.pick_price.
    quotes = fetch_source_quotes(source_account, keys) if now.weekday() < 5 else {}

    def price_of(symbol, exchange):
        key = (symbol, exchange)
        picked = holding_price.pick_price(None, quotes.get(key), closes.get(key), now)
        if picked['ltp'] and picked['source'] in ('live', 'quote', 'close'):
            return picked
        return None

    return price_of


def revalue_open_rows(rows, price_of, scope_of=None):
    """Reprice the holdings rows at the chain's price. Returns (rows, deltas, delta_all):

    deltas     {strategy: price difference summed over the rows that belong to a strategy}
    delta_all  the same over every holdings row, to correct the account's total
    scope_of(row) gives a row's strategy (book or manual tag) or None; default: row['strategy'].
    Rows that are not holdings (F&O positions) and rows with no price pass through unchanged.
    """
    scope_of = scope_of or (lambda row: row.get('strategy'))
    out, deltas, delta_all = [], {}, 0.0
    for row in rows:
        new_row = dict(row)
        if new_row.get('source') == 'holdings' and new_row.get('unrealized_pnl') is not None:
            picked = price_of(new_row.get('symbol'), new_row.get('exchange'))
            if picked:
                qty = float(new_row.get('quantity') or 0) * (-1.0 if new_row.get('action') == 'SELL' else 1.0)
                avg = float(new_row.get('average_price') or 0)
                new_value = round((float(picked['ltp']) - avg) * qty, 2)
                change = new_value - float(new_row['unrealized_pnl'])
                new_row.update(ltp=round(float(picked['ltp']), 2), unrealized_pnl=new_value,
                               price_source=picked['source'])
                delta_all += change
                name = scope_of(new_row)
                if name:
                    deltas[name] = deltas.get(name, 0.0) + change
        out.append(new_row)
    return out, deltas, delta_all


def revalue_curve(curve, deltas, now):
    """The curve with each strategy's LAST unrealized level moved by `deltas`.

    Returns (curve, delta). A strategy that is not in the curve is ignored (the ledger
    never held it). Nothing is done when the curve does not reach the latest expected
    session: today's price difference must not land on an older date.
    """
    if not curve or not curve.get('dates') or not deltas:
        return curve, 0.0
    dates = curve['dates']
    last = len(dates) - 1
    if dates[last] < holding_price.expected_close_date(now).isoformat():
        return curve, 0.0
    series_by = {name: {'realized': list(s.get('realized') or []), 'unrealized': list(s.get('unrealized') or [])}
                 for name, s in (curve.get('by_strategy') or {}).items()}
    total = 0.0
    for name, change in deltas.items():
        series = series_by.get(name)
        if series is None:
            continue
        series['unrealized'] += [0.0] * (len(dates) - len(series['unrealized']))
        series['unrealized'][last] = round(series['unrealized'][last] + change, 2)
        total += change
    revalued = dict(curve)
    revalued['by_strategy'] = series_by
    return revalued, total
