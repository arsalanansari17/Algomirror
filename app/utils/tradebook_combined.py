"""
Combined Trade Book across multiple trading accounts, live or historical.

Mirrors OpenAlgo's own isHistorical switch (frontend/src/pages/TradeBook.tsx):
a date range other than today calls the ledger-backed GET /api/v1/pnl/trades
per account instead of the live tradebook() call, since today's trades
aren't captured into that ledger until the account's own 16:00 IST daily
job runs. Same parallel-fetch/per-account-error-isolation shape as
app/utils/pnl_history_combined.py and pnl_curve.py.
"""
import concurrent.futures
import logging
from datetime import date

from app.utils.openalgo_client import ExtendedOpenAlgoAPI

logger = logging.getLogger(__name__)


def _today_str():
    return date.today().isoformat()


def _fetch_one(account, is_historical, start_date, end_date, symbol, segment):
    try:
        client = ExtendedOpenAlgoAPI(api_key=account.get_api_key(), host=account.host_url)
        if is_historical:
            resp = client.pnl_trades(start_date, end_date, symbol, segment)
        else:
            resp = client.tradebook()

        if resp.get('status') != 'success':
            return account, None, resp.get('message', 'Unknown error')
        return account, resp.get('data') or [], None
    except Exception:
        logger.exception(f'Error fetching trades for account {account.id}')
        return account, None, 'Unexpected error fetching trades'


def compute_combined_tradebook(accounts, start_date=None, end_date=None, symbol=None, segment=None):
    """start_date/end_date both equal to today (or omitted) -> live,
    today-only tradebook() per account, same as the existing /tradebook
    page's default. Any other range -> historical GET /pnl/trades per
    account. Segment/Symbol are only meaningful for the historical path -
    the live tradebook() call has no such filter and returns everything
    for the day, matching how OpenAlgo's own live call behaves too.
    """
    today = _today_str()
    is_historical = bool(start_date and end_date) and not (start_date == today and end_date == today)

    if not accounts:
        return {'trades': [], 'per_account': [], 'failed_accounts': [], 'is_historical': is_historical}

    if len(accounts) == 1:
        results = [_fetch_one(accounts[0], is_historical, start_date, end_date, symbol, segment)]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(accounts))) as executor:
            results = list(
                executor.map(
                    lambda a: _fetch_one(a, is_historical, start_date, end_date, symbol, segment),
                    accounts,
                )
            )

    per_account = []
    failed_accounts = []
    all_trades = []

    for account, trades, error in results:
        per_account.append({
            'account_id': account.id,
            'account_name': account.account_name,
            'trade_count': len(trades) if trades else 0,
            'error': error,
        })
        if error:
            failed_accounts.append(account.account_name)
            continue

        for trade in trades:
            tagged = dict(trade)
            tagged['account_id'] = account.id
            tagged['account_name'] = account.account_name
            tagged['broker'] = account.broker_name
            all_trades.append(tagged)

    return {
        'trades': all_trades,
        'per_account': per_account,
        'failed_accounts': failed_accounts,
        'is_historical': is_historical,
    }
