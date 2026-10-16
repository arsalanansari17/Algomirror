"""
Combined P&L Analysis data across multiple trading accounts.

Each account's own OpenAlgo instance (the SkyShieldEdge fork) already does
the matching. For the P&L Analysis page AlgoMirror fetches, per account,

  * GET /api/v1/pnl/history  - closed lots and open positions (every segment)
  * GET /api/v1/pnl/curve    - daily realized / unrealized per strategy
                               (Equity only; the fork's endpoint)

in parallel, and merges the raw data: lots and positions are concatenated
(each tagged with its account) and the curves are summed by date and
strategy. The page then runs OpenAlgo's own model code (vendored as
static/js/vendor/pnl-model.js) on the merged data, so one account selected
gives the numbers OpenAlgo shows for that account.

Nothing here is persisted: every call re-fetches and re-merges, like
app/utils/pnl_history_combined.py. One account failing never fails the
page: it is named in per_account / failed_accounts and left out, the same
guarantee the other combined views make.
"""
import concurrent.futures
import logging

from app.utils.openalgo_client import ExtendedOpenAlgoAPI

logger = logging.getLogger(__name__)

# The fork's /pnl/curve takes the symbol part as a pre-filter on the fills.
EQUITY = 'equity'


def _fetch_history(account, start_date, end_date, segment):
    try:
        client = ExtendedOpenAlgoAPI(api_key=account.get_api_key(), host=account.host_url)
        resp = client.pnl_history(start_date, end_date, None, segment, None)
        if resp.get('status') != 'success':
            return None, resp.get('message', 'Unknown error')
        return resp.get('data'), None
    except Exception:
        logger.exception(f'Error fetching P&L history for account {account.id}')
        return None, 'Unexpected error fetching P&L history'


def _fetch_curve(account, start_date, end_date, symbol_contains):
    try:
        client = ExtendedOpenAlgoAPI(api_key=account.get_api_key(), host=account.host_url)
        resp = client.pnl_curve(start_date, end_date, 'actual_cost', symbol_contains)
        if resp.get('status') != 'success':
            return None, resp.get('message', 'Unknown error')
        return resp.get('data'), None
    except Exception:
        logger.exception(f'Error fetching P&L curve for account {account.id}')
        return None, 'Unexpected error fetching the P&L curve'


def _fetch_account(account, start_date, end_date, segment, symbol_contains):
    history, history_error = _fetch_history(account, start_date, end_date, segment)
    curve, curve_error = (None, None)
    # The curve exists for Equity only, and only for an account whose history
    # came back (otherwise the account is already counted as failed).
    if history is not None and segment == EQUITY:
        curve, curve_error = _fetch_curve(account, start_date, end_date, symbol_contains)
    return account, history, history_error, curve, curve_error


def merge_curves(curves):
    """Sum several accounts' curves by date and strategy.

    `curves` is a list of the data dicts /pnl/curve returned. The date axis is
    the union of every account's dates (accounts normally share one: the
    trading days of the same range), and an account missing a date contributes
    zero there. Both series are summed: realized is a daily amount, unrealized
    a level, and the sum of levels is the level of the sum.
    """
    curves = [c for c in curves if c]
    if not curves:
        return None

    dates = sorted({d for c in curves for d in c.get('dates', [])})
    index = {d: i for i, d in enumerate(dates)}
    n = len(dates)

    by_strategy = {}
    for curve in curves:
        own = {d: i for i, d in enumerate(curve.get('dates', []))}
        for name, series in (curve.get('by_strategy') or {}).items():
            merged = by_strategy.setdefault(
                name, {'realized': [0.0] * n, 'unrealized': [0.0] * n}
            )
            for kind in ('realized', 'unrealized'):
                values = series.get(kind) or []
                for date, i in own.items():
                    if i < len(values):
                        merged[kind][index[date]] += values[i]

    notes = {'orphan_sells': [], 'missing_close': [], 'missing_base': []}
    calendar = None
    for curve in curves:
        n_ = curve.get('notes') or {}
        notes['orphan_sells'].extend(n_.get('orphan_sells') or [])
        for key in ('missing_close', 'missing_base'):
            for symbol in n_.get(key) or []:
                if symbol not in notes[key]:
                    notes[key].append(symbol)
        calendar = calendar or n_.get('calendar')
    if calendar:
        notes['calendar'] = calendar

    return {
        'dates': dates,
        'by_strategy': {
            name: {
                'realized': [round(v, 2) for v in s['realized']],
                'unrealized': [round(v, 2) for v in s['unrealized']],
            }
            for name, s in sorted(by_strategy.items())
        },
        'basis': curves[0].get('basis', 'actual_cost'),
        'base_date': curves[0].get('base_date'),
        'notes': notes,
    }


def compute_combined_pnl_analysis(accounts, start_date, end_date, segment=None, symbol_contains=None):
    """Fetch and merge history (and, for Equity, the curve) from every account."""
    if not accounts:
        return _empty_result(start_date, end_date, segment)

    if len(accounts) == 1:
        results = [_fetch_account(accounts[0], start_date, end_date, segment, symbol_contains)]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(accounts))) as executor:
            results = list(
                executor.map(
                    lambda a: _fetch_account(a, start_date, end_date, segment, symbol_contains),
                    accounts,
                )
            )

    per_account = []
    failed_accounts = []
    curve_missing_accounts = []
    closed_trades = []
    open_positions = []
    curves = []
    unrealized_total = None

    for account, history, history_error, curve, curve_error in results:
        entry = {
            'account_id': account.id,
            'account_name': account.account_name,
            'error': history_error,
            'curve_error': curve_error,
        }
        per_account.append(entry)
        if history_error or history is None:
            failed_accounts.append(account.account_name)
            continue

        for trade in history.get('closed_trades', []):
            tagged = dict(trade)
            tagged['account_id'] = account.id
            tagged['account_name'] = account.account_name
            closed_trades.append(tagged)
        for position in history.get('open_positions', []):
            tagged = dict(position)
            tagged['account_id'] = account.id
            tagged['account_name'] = account.account_name
            open_positions.append(tagged)

        # The live open figure exists only when the range ends today; one
        # account having it is enough to make the others' zeros meaningful.
        account_unrealized = history.get('total_unrealized_pnl')
        if account_unrealized is not None:
            unrealized_total = (unrealized_total or 0.0) + account_unrealized

        if segment == EQUITY:
            if curve is not None:
                curves.append(curve)
            else:
                curve_missing_accounts.append(account.account_name)

    return {
        'start_date': start_date,
        'end_date': end_date,
        'segment': segment or 'all',
        'closed_trades': closed_trades,
        'open_positions': open_positions,
        'total_unrealized_pnl': round(unrealized_total, 2) if unrealized_total is not None else None,
        'curve': merge_curves(curves),
        'per_account': per_account,
        'failed_accounts': failed_accounts,
        'curve_missing_accounts': curve_missing_accounts,
    }


def _empty_result(start_date, end_date, segment):
    return {
        'start_date': start_date,
        'end_date': end_date,
        'segment': segment or 'all',
        'closed_trades': [],
        'open_positions': [],
        'total_unrealized_pnl': None,
        'curve': None,
        'per_account': [],
        'failed_accounts': [],
        'curve_missing_accounts': [],
    }
