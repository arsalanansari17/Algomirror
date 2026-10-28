"""
Real entry average for carried Kotak legs on the Positions page.

Kotak reports a leg carried over from a previous day at the previous
settlement price - its "average" is a valuation, not what the leg cost
(upstream marketcalls/openalgo#2061; Kotak's positions endpoint does not carry
the cost basis at all, and `upldPrc` is 0.00 on our accounts). OpenAlgo's
Kotak adapter flags such rows `average_price_basis = carry_forward_valuation`.
The strategy book (reached through the fork-only /api/v1/pnl/attribution)
keeps the real fills per strategy, so a flagged row is corrected from it.

The rule is deliberately narrow and mirrors OpenAlgo's own Positions page
(frontend/src/lib/trading/strategyAttribution.ts, `applyCostBasis`):

  * only rows the broker flagged;
  * an open row only when the book fully explains it: every open slice
    attributed, all on the broker's side, adding up to exactly the broker
    quantity, and the row not marked as a mismatch;
  * a closed row (a carried leg that was exited today, e.g. an expiry-day
    exit or an NDS roll) takes the P&L the strategies realized on it, because
    Kotak's own figure for it is only that day's slice measured from the
    overnight valuation, not the result since entry; same conditions: no
    mismatch, at least one slice, every slice attributed;
  * anything else (no flag, another broker, unexplained) is left exactly as
    the broker reported it.

Pure functions, no I/O - the route fetches the attribution and passes it in.
"""
CARRY_FORWARD_BASIS = 'carry_forward_valuation'
STRATEGY_BOOK_BASIS = 'strategy_book'
_EPS = 1e-9


def _f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def has_carry_forward_valuation(positions):
    """True if at least one row, open or closed, carries the broker's carry-forward flag."""
    return any(p.get('average_price_basis') == CARRY_FORWARD_BASIS for p in positions)


def _apply_closed_row(pos, row):
    """A flagged row that is flat now: its P&L is what the strategies realized
    on the contract today (closing quantity x (exit - book average)), which is
    measured from the real entry. Kotak's pnl for it is sell - buy with the
    carried leg at its overnight valuation, i.e. only the day's move."""
    if not row or row.get('mismatch'):
        return False
    slices = row.get('slices') or []
    if not slices or any(not s.get('attributed') for s in slices):
        return False
    pos['broker_pnl'] = pos.get('pnl')
    pos['pnl'] = round(sum(_f(s.get('today_realized_pnl')) for s in slices), 2)
    pos['average_price_basis'] = STRATEGY_BOOK_BASIS
    return True


def apply_cost_basis(positions, attribution_rows):
    """Correct flagged rows in place from the strategy book's slices.

    `attribution_rows` is the `rows` list of the attribution response. Returns
    how many rows were corrected. P&L is recomputed from the corrected average
    and the live price, plus what the strategies realized today on the
    contract; with no live price only the realized part is shown. Callers run
    this before computing percentages. A closed row keeps its zero average and
    gets the realized P&L from the book.
    """
    by_key = {
        (r.get('symbol'), r.get('exchange'), r.get('product')): r
        for r in (attribution_rows or [])
    }
    corrected = 0
    for pos in positions:
        if pos.get('average_price_basis') != CARRY_FORWARD_BASIS:
            continue
        qty = _f(pos.get('quantity'))
        row = by_key.get((pos.get('symbol'), pos.get('exchange'), pos.get('product')))
        if qty == 0:
            if _apply_closed_row(pos, row):
                corrected += 1
            continue
        if not row or row.get('mismatch'):
            continue
        slices = row.get('slices') or []
        open_slices = [s for s in slices if _f(s.get('quantity')) != 0]
        if not open_slices or any(not s.get('attributed') for s in open_slices):
            continue
        if any((_f(s.get('quantity')) > 0) != (qty > 0) for s in open_slices):
            continue
        if abs(sum(_f(s.get('quantity')) for s in open_slices) - qty) > _EPS:
            continue
        weight = sum(abs(_f(s.get('quantity'))) for s in open_slices)
        average = sum(abs(_f(s.get('quantity'))) * _f(s.get('average_price')) for s in open_slices) / weight
        if average <= 0:
            continue
        realized = sum(_f(s.get('today_realized_pnl')) for s in slices)
        ltp = _f(pos.get('ltp'))
        pnl = qty * (ltp - average) + realized if ltp > 0 else realized

        pos['broker_average_price'] = pos.get('average_price')
        pos['average_price'] = round(average, 2)
        pos['pnl'] = round(pnl, 2)
        pos['average_price_basis'] = STRATEGY_BOOK_BASIS
        corrected += 1
    return corrected
