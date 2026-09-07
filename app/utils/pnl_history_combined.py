"""
Combined multi-day realized P&L across multiple trading accounts.

Each account's own OpenAlgo instance already does the FIFO matching
server-side (openalgo's fork-only utils/pnl_fifo.py, exposed at
GET /api/v1/pnl/history and GET /api/v1/pnl/trades - see that repo's
docs/design/56-pnl-history/README.md). AlgoMirror just calls each selected
account once, in parallel, and merges the results - the same
parallel-fetch/per-account-error-isolation/merge shape as
app/utils/pnl_curve.py's compute_combined_pnl, but far lighter: no
intraday MTM replay, just summing numbers OpenAlgo already computed.

Nothing here is persisted - every call re-fetches and re-merges, matching
the "compute on read" philosophy the OpenAlgo feature itself is built on.
"""
import concurrent.futures
import logging

from app.utils.openalgo_client import ExtendedOpenAlgoAPI

logger = logging.getLogger(__name__)


def _fetch_one(account, start_date, end_date, symbol, segment, strategy):
    try:
        client = ExtendedOpenAlgoAPI(api_key=account.get_api_key(), host=account.host_url)
        resp = client.pnl_history(start_date, end_date, symbol, segment, strategy)
        if resp.get('status') != 'success':
            return account, None, resp.get('message', 'Unknown error')
        return account, resp.get('data'), None
    except Exception:
        logger.exception(f'Error fetching P&L history for account {account.id}')
        return account, None, 'Unexpected error fetching P&L history'


def _fetch_one_strategy_legs(account, strategy):
    try:
        client = ExtendedOpenAlgoAPI(api_key=account.get_api_key(), host=account.host_url)
        resp = client.strategy_legs(strategy)
        if resp.get('status') != 'success':
            return account, None, resp.get('message', 'Unknown error')
        return account, resp.get('data'), None
    except Exception:
        logger.exception(f'Error fetching strategy legs for account {account.id}')
        return account, None, 'Unexpected error fetching strategy legs'


def _merge_scrip_rows(closed_trades):
    """Merge every closed lot by symbol+exchange+product, across accounts -
    the same Scrip-wise aggregation as OpenAlgo's own PnlHistory.tsx
    scripRows memo, ported here since this runs server-side once on the
    combined list rather than client-side per account. entry_action says
    which leg of the lot was the entry: a BUY entry closed by a sell is a
    long (buy value = entry leg, sell value = exit leg); a SELL entry is a
    short (reversed). Merging across accounts is the point - the same
    symbol held in two accounts nets into one row, not two.
    """
    rows = {}
    for trade in closed_trades:
        key = (trade['symbol'], trade['exchange'], trade.get('product'))
        is_long = trade.get('entry_action') == 'BUY'
        quantity = trade['quantity']
        buy_value = quantity * (trade['entry_price'] if is_long else trade['exit_price'])
        sell_value = quantity * (trade['exit_price'] if is_long else trade['entry_price'])
        row = rows.get(key)
        if row is None:
            rows[key] = {
                'symbol': trade['symbol'],
                'exchange': trade['exchange'],
                'product': trade.get('product'),
                'quantity': quantity,
                'buy_value': buy_value,
                'sell_value': sell_value,
                'realized_pnl': trade['realized_pnl'],
                'trade_count': 1,
            }
        else:
            row['quantity'] += quantity
            row['buy_value'] += buy_value
            row['sell_value'] += sell_value
            row['realized_pnl'] += trade['realized_pnl']
            row['trade_count'] += 1
    return sorted(rows.values(), key=lambda r: r['symbol'])


def compute_combined_pnl_history(accounts, start_date, end_date, symbol=None, segment=None, strategy=None):
    """Fetch GET /api/v1/pnl/history from every account in parallel, merge
    into one combined report. A failed account contributes nothing to the
    totals but is named in per_account/failed_accounts rather than
    silently making the combined total look smaller than it really is -
    same guarantee compute_combined_pnl makes for the intraday curve.
    """
    if not accounts:
        return _empty_result()

    if len(accounts) == 1:
        results = [_fetch_one(accounts[0], start_date, end_date, symbol, segment, strategy)]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(accounts))) as executor:
            results = list(
                executor.map(
                    lambda a: _fetch_one(a, start_date, end_date, symbol, segment, strategy),
                    accounts,
                )
            )

    per_account = []
    failed_accounts = []
    daily_totals = {}  # date -> {'realized_pnl': float, 'trade_count': int}
    all_closed_trades = []
    all_open_positions = []
    total_realized_pnl = 0.0
    total_trade_count = 0

    for account, data, error in results:
        account_pnl = data['total_realized_pnl'] if data else 0.0
        per_account.append({
            'account_id': account.id,
            'account_name': account.account_name,
            'realized_pnl': round(account_pnl, 2) if data else 0.0,
            'error': error,
        })
        if error:
            failed_accounts.append(account.account_name)
            continue

        total_realized_pnl += data['total_realized_pnl']
        total_trade_count += data['trade_count']

        for row in data.get('daily', []):
            bucket = daily_totals.setdefault(row['date'], {'realized_pnl': 0.0, 'trade_count': 0})
            bucket['realized_pnl'] += row['realized_pnl']
            bucket['trade_count'] += row['trade_count']

        for trade in data.get('closed_trades', []):
            tagged = dict(trade)
            tagged['account_id'] = account.id
            tagged['account_name'] = account.account_name
            all_closed_trades.append(tagged)

        for position in data.get('open_positions', []):
            tagged = dict(position)
            tagged['account_id'] = account.id
            tagged['account_name'] = account.account_name
            all_open_positions.append(tagged)

    daily = [
        {'date': date, 'realized_pnl': round(bucket['realized_pnl'], 2), 'trade_count': bucket['trade_count']}
        for date, bucket in sorted(daily_totals.items())
    ]

    return {
        'start_date': start_date,
        'end_date': end_date,
        'total_realized_pnl': round(total_realized_pnl, 2),
        'trade_count': total_trade_count,
        'daily': daily,
        'closed_trades': all_closed_trades,
        'open_positions': all_open_positions,
        'scrip_rows': _merge_scrip_rows(all_closed_trades),
        'per_account': per_account,
        'failed_accounts': failed_accounts,
    }


def _empty_result():
    return {
        'start_date': None,
        'end_date': None,
        'total_realized_pnl': 0.0,
        'trade_count': 0,
        'daily': [],
        'closed_trades': [],
        'open_positions': [],
        'scrip_rows': [],
        'per_account': [],
        'failed_accounts': [],
    }


def compute_combined_strategy_legs(accounts, strategy=None):
    """Fetch GET /api/v1/pnl/strategy-legs from every account in parallel,
    merge by (strategy, symbol, exchange, product) across accounts - same
    merge key shape as _merge_scrip_rows above, keyed by strategy+symbol
    instead of just symbol. This is "holdings, per strategy" already
    computed by each account's own strategy book
    (openalgo's database/strategy_book_db.py) - not derived from
    pnl_history/the FIFO ledger at all.
    """
    if not accounts:
        return {'legs': [], 'per_account': [], 'failed_accounts': []}

    if len(accounts) == 1:
        results = [_fetch_one_strategy_legs(accounts[0], strategy)]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(accounts))) as executor:
            results = list(
                executor.map(lambda a: _fetch_one_strategy_legs(a, strategy), accounts)
            )

    per_account = []
    failed_accounts = []
    merged = {}

    for account, legs, error in results:
        per_account.append({
            'account_id': account.id,
            'account_name': account.account_name,
            'leg_count': len(legs) if legs else 0,
            'error': error,
        })
        if error:
            failed_accounts.append(account.account_name)
            continue

        for leg in legs:
            key = (leg['strategy'], leg['symbol'], leg['exchange'], leg['product'])
            row = merged.get(key)
            if row is None:
                merged[key] = {
                    'strategy': leg['strategy'],
                    'symbol': leg['symbol'],
                    'exchange': leg['exchange'],
                    'product': leg['product'],
                    'quantity': leg['quantity'],
                    # Weighted-average cost across accounts - matches how
                    # each account's own strategy book averages a position
                    # flipping through partial fills.
                    'notional': leg['quantity'] * leg['average_price'],
                    'realized_pnl': leg['realized_pnl'],
                    'today_realized_pnl': leg['today_realized_pnl'],
                    'account_ids': [account.id],
                }
            else:
                row['quantity'] += leg['quantity']
                row['notional'] += leg['quantity'] * leg['average_price']
                row['realized_pnl'] += leg['realized_pnl']
                row['today_realized_pnl'] += leg['today_realized_pnl']
                row['account_ids'].append(account.id)

    legs_out = []
    for row in merged.values():
        average_price = (row['notional'] / row['quantity']) if row['quantity'] else 0.0
        legs_out.append({
            'strategy': row['strategy'],
            'symbol': row['symbol'],
            'exchange': row['exchange'],
            'product': row['product'],
            'quantity': row['quantity'],
            'average_price': round(average_price, 2),
            'realized_pnl': round(row['realized_pnl'], 2),
            'today_realized_pnl': round(row['today_realized_pnl'], 2),
            'account_ids': row['account_ids'],
        })
    legs_out.sort(key=lambda leg: (leg['strategy'], leg['symbol']))

    return {'legs': legs_out, 'per_account': per_account, 'failed_accounts': failed_accounts}
