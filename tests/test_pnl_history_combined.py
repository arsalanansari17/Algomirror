#!/usr/bin/env python
"""
Test script for app/utils/pnl_history_combined.py's merge logic - the
consolidated multi-day P&L aggregator brought over from OpenAlgo's
fork-only P&L History feature. Verifies daily-P&L summing and Scrip-wise
merging across two synthetic accounts holding overlapping dates and the
same symbol, plus that one account's failure doesn't crash the merge for
the others - the same shape of test as tests/test_trading_hours.py
(standalone script, print+assert, not pytest).
"""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.pnl_history_combined import compute_combined_pnl_history


class FakeAccount:
    def __init__(self, id, account_name):
        self.id = id
        self.account_name = account_name
        self.host_url = f'http://fake-host-{id}:5000'

    def get_api_key(self):
        return f'fake-key-{self.id}'


ACCOUNT_1_DATA = {
    'total_realized_pnl': 1000.0,
    'trade_count': 2,
    'daily': [
        {'date': '2026-09-01', 'realized_pnl': 600.0, 'trade_count': 1},
        {'date': '2026-09-02', 'realized_pnl': 400.0, 'trade_count': 1},
    ],
    'closed_trades': [
        {
            'symbol': 'INFY', 'exchange': 'NSE', 'product': 'CNC', 'entry_action': 'BUY',
            'quantity': 10, 'entry_price': 1500.0, 'entry_timestamp': '2026-09-01 09:30:00',
            'exit_price': 1560.0, 'exit_timestamp': '2026-09-01 15:00:00', 'realized_pnl': 600.0,
        },
    ],
    'open_positions': [],
}

ACCOUNT_2_DATA = {
    'total_realized_pnl': 500.0,
    'trade_count': 1,
    'daily': [
        {'date': '2026-09-01', 'realized_pnl': 200.0, 'trade_count': 1},
    ],
    'closed_trades': [
        {
            'symbol': 'INFY', 'exchange': 'NSE', 'product': 'CNC', 'entry_action': 'BUY',
            'quantity': 5, 'entry_price': 1500.0, 'entry_timestamp': '2026-09-01 10:00:00',
            'exit_price': 1600.0, 'exit_timestamp': '2026-09-01 14:00:00', 'realized_pnl': 200.0,
        },
    ],
    'open_positions': [],
}


def fake_pnl_history(self, start_date, end_date, symbol=None, segment=None):
    if self.api_key == 'fake-key-1':
        return {'status': 'success', 'data': ACCOUNT_1_DATA}
    if self.api_key == 'fake-key-2':
        return {'status': 'success', 'data': ACCOUNT_2_DATA}
    return {'status': 'error', 'message': 'Simulated broker failure'}


def test_merge_two_accounts():
    accounts = [FakeAccount(1, 'acc1'), FakeAccount(2, 'acc2')]
    with patch('app.utils.openalgo_client.ExtendedOpenAlgoAPI.pnl_history', fake_pnl_history):
        result = compute_combined_pnl_history(accounts, '2026-09-01', '2026-09-02')

    print('total_realized_pnl:', result['total_realized_pnl'])
    assert result['total_realized_pnl'] == 1500.0, 'expected 1000 (acc1) + 500 (acc2)'

    print('trade_count:', result['trade_count'])
    assert result['trade_count'] == 3

    daily_by_date = {row['date']: row for row in result['daily']}
    print('daily:', daily_by_date)
    assert daily_by_date['2026-09-01']['realized_pnl'] == 800.0, '600 (acc1) + 200 (acc2) on the same day'
    assert daily_by_date['2026-09-01']['trade_count'] == 2
    assert daily_by_date['2026-09-02']['realized_pnl'] == 400.0

    print('scrip_rows:', result['scrip_rows'])
    assert len(result['scrip_rows']) == 1, 'INFY from both accounts must merge into one row'
    infy = result['scrip_rows'][0]
    assert infy['symbol'] == 'INFY'
    assert infy['quantity'] == 15, '10 (acc1) + 5 (acc2)'
    assert infy['realized_pnl'] == 800.0
    assert infy['trade_count'] == 2

    assert len(result['closed_trades']) == 2
    tagged_accounts = {t['account_id'] for t in result['closed_trades']}
    assert tagged_accounts == {1, 2}, 'each closed trade must be tagged with its source account'

    assert result['failed_accounts'] == []
    print('PASS: test_merge_two_accounts')


def test_one_account_fails_isolated():
    accounts = [FakeAccount(1, 'acc1'), FakeAccount(3, 'acc3-broken')]
    with patch('app.utils.openalgo_client.ExtendedOpenAlgoAPI.pnl_history', fake_pnl_history):
        result = compute_combined_pnl_history(accounts, '2026-09-01', '2026-09-02')

    print('total_realized_pnl (one account failed):', result['total_realized_pnl'])
    assert result['total_realized_pnl'] == 1000.0, 'only acc1 contributes; acc3 failed'
    assert result['failed_accounts'] == ['acc3-broken']
    per_account_by_id = {p['account_id']: p for p in result['per_account']}
    assert per_account_by_id[3]['error'] == 'Simulated broker failure'
    assert per_account_by_id[1]['error'] is None
    print('PASS: test_one_account_fails_isolated')


def test_no_accounts():
    result = compute_combined_pnl_history([], '2026-09-01', '2026-09-02')
    assert result['total_realized_pnl'] == 0.0
    assert result['daily'] == []
    assert result['scrip_rows'] == []
    print('PASS: test_no_accounts')


if __name__ == '__main__':
    test_merge_two_accounts()
    test_one_account_fails_isolated()
    test_no_accounts()
    print('\nAll pnl_history_combined tests passed.')
