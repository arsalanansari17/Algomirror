#!/usr/bin/env python
"""
Test script for app/utils/pnl_analysis_combined.py - the multi-account merge
behind the P&L Analysis page. Two synthetic accounts hold overlapping dates
and strategies; a third fails. Same shape as tests/test_pnl_history_combined.py
(standalone script, print+assert, not pytest).
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.pnl_analysis_combined import compute_combined_pnl_analysis, merge_curves


class FakeAccount:
    def __init__(self, id, account_name):
        self.id = id
        self.account_name = account_name
        self.host_url = f'http://fake-host-{id}:5000'

    def get_api_key(self):
        return f'fake-key-{self.id}'


TRADE = {
    'symbol': 'INFY', 'exchange': 'NSE', 'product': 'CNC', 'entry_action': 'BUY',
    'quantity': 10, 'entry_price': 1500.0, 'entry_timestamp': '2026-05-04 09:30:00',
    'exit_price': 1560.0, 'exit_timestamp': '2026-05-05 15:00:00', 'realized_pnl': 600.0,
    'strategy': 'EquityBreakoutPositional',
}

HISTORY_1 = {
    'closed_trades': [TRADE],
    'open_positions': [{'symbol': 'ABC', 'exchange': 'NSE', 'product': 'CNC', 'action': 'BUY',
                        'quantity': 5, 'average_price': 100.0, 'strategy': None, 'ltp': 110.0,
                        'unrealized_pnl': 50.0, 'source': 'holdings'}],
    'total_unrealized_pnl': 50.0,
}
HISTORY_2 = {
    'closed_trades': [dict(TRADE, realized_pnl=200.0, quantity=5)],
    'open_positions': [],
    'total_unrealized_pnl': 0.0,
}

CURVE_1 = {
    'dates': ['2026-05-04', '2026-05-05', '2026-05-06'],
    'by_strategy': {
        'EquityBreakoutPositional': {'realized': [0, 600, 0], 'unrealized': [40, 0, 0]},
        'Untagged': {'realized': [0, 0, 0], 'unrealized': [10, 10, 10]},
    },
    'basis': 'actual_cost', 'base_date': '2026-05-01',
    'notes': {'orphan_sells': [{'symbol': 'X', 'date': '2025-01-01'}], 'missing_close': ['AAA'],
              'missing_base': []},
}
CURVE_2 = {
    'dates': ['2026-05-04', '2026-05-05', '2026-05-06'],
    'by_strategy': {
        'EquityBreakoutPositional': {'realized': [0, 200, 0], 'unrealized': [5, 0, 0]},
    },
    'basis': 'actual_cost', 'base_date': '2026-05-01',
    'notes': {'orphan_sells': [], 'missing_close': ['AAA', 'BBB'], 'missing_base': [], 'calendar': 'weekdays'},
}


def fake_history(self, start_date, end_date, symbol=None, segment=None, strategy=None):
    if self.api_key == 'fake-key-1':
        return {'status': 'success', 'data': HISTORY_1}
    if self.api_key == 'fake-key-2':
        return {'status': 'success', 'data': HISTORY_2}
    return {'status': 'error', 'message': 'Simulated broker failure'}


def fake_curve(self, start_date, end_date, basis='actual_cost', symbol_contains=None):
    if self.api_key == 'fake-key-1':
        return {'status': 'success', 'data': CURVE_1}
    if self.api_key == 'fake-key-2':
        return {'status': 'success', 'data': CURVE_2}
    return {'status': 'error', 'message': 'Simulated failure'}


def test_merge_curves_sums_by_date_and_strategy():
    merged = merge_curves([CURVE_1, CURVE_2])
    ebp = merged['by_strategy']['EquityBreakoutPositional']
    assert ebp['realized'] == [0, 800, 0], ebp
    assert ebp['unrealized'] == [45, 0, 0], ebp
    assert merged['by_strategy']['Untagged']['unrealized'] == [10, 10, 10]
    # Notes are the union, with no repeated symbol.
    assert merged['notes']['missing_close'] == ['AAA', 'BBB']
    assert len(merged['notes']['orphan_sells']) == 1
    assert merged['notes']['calendar'] == 'weekdays'
    print('merge_curves: ok')


def test_merge_curves_aligns_different_date_axes():
    short = {
        'dates': ['2026-05-05'],
        'by_strategy': {'S': {'realized': [100], 'unrealized': [1]}},
        'basis': 'actual_cost', 'base_date': None, 'notes': {},
    }
    long_ = {
        'dates': ['2026-05-04', '2026-05-05'],
        'by_strategy': {'S': {'realized': [10, 20], 'unrealized': [2, 3]}},
        'basis': 'actual_cost', 'base_date': None, 'notes': {},
    }
    merged = merge_curves([short, long_])
    assert merged['dates'] == ['2026-05-04', '2026-05-05']
    assert merged['by_strategy']['S']['realized'] == [10, 120]
    assert merge_curves([None, None]) is None
    print('merge_curves alignment: ok')


def test_combined_equity_merges_lots_curves_and_isolates_a_failed_account():
    accounts = [FakeAccount(1, 'Arsalan'), FakeAccount(2, 'Iram'), FakeAccount(3, 'Broken')]
    with patch('app.utils.openalgo_client.ExtendedOpenAlgoAPI.pnl_history', fake_history), \
         patch('app.utils.openalgo_client.ExtendedOpenAlgoAPI.pnl_curve', fake_curve):
        result = compute_combined_pnl_analysis(accounts, '2026-05-01', '2026-05-31', 'equity')

    assert result['failed_accounts'] == ['Broken'], result['failed_accounts']
    assert [t['account_name'] for t in result['closed_trades']] == ['Arsalan', 'Iram']
    assert [p['account_name'] for p in result['open_positions']] == ['Arsalan']
    assert result['total_unrealized_pnl'] == 50.0
    assert result['curve']['by_strategy']['EquityBreakoutPositional']['realized'] == [0, 800, 0]
    assert result['curve_missing_accounts'] == []
    print('combined equity: ok')


def test_other_segments_skip_the_curve():
    accounts = [FakeAccount(1, 'Arsalan')]
    calls = []

    def spy_curve(self, *args, **kwargs):
        calls.append(1)
        return fake_curve(self, *args, **kwargs)

    with patch('app.utils.openalgo_client.ExtendedOpenAlgoAPI.pnl_history', fake_history), \
         patch('app.utils.openalgo_client.ExtendedOpenAlgoAPI.pnl_curve', spy_curve):
        result = compute_combined_pnl_analysis(accounts, '2026-05-01', '2026-05-31', 'fno')

    assert calls == [], 'the curve is Equity only'
    assert result['curve'] is None
    assert len(result['closed_trades']) == 1
    print('other segments: ok')


def test_account_without_the_curve_endpoint_is_reported_not_fatal():
    accounts = [FakeAccount(1, 'Arsalan'), FakeAccount(2, 'Iram')]

    def curve_only_for_1(self, *args, **kwargs):
        if self.api_key == 'fake-key-1':
            return fake_curve(self, *args, **kwargs)
        return {'status': 'error', 'message': 'Not found'}

    with patch('app.utils.openalgo_client.ExtendedOpenAlgoAPI.pnl_history', fake_history), \
         patch('app.utils.openalgo_client.ExtendedOpenAlgoAPI.pnl_curve', curve_only_for_1):
        result = compute_combined_pnl_analysis(accounts, '2026-05-01', '2026-05-31', 'equity')

    assert result['failed_accounts'] == []
    assert result['curve_missing_accounts'] == ['Iram']
    assert result['curve']['by_strategy']['EquityBreakoutPositional']['realized'] == [0, 600, 0]
    assert len(result['closed_trades']) == 2
    print('missing curve: ok')


def test_no_accounts():
    result = compute_combined_pnl_analysis([], '2026-05-01', '2026-05-31', 'equity')
    assert result['closed_trades'] == [] and result['curve'] is None
    print('no accounts: ok')


if __name__ == '__main__':
    test_merge_curves_sums_by_date_and_strategy()
    test_merge_curves_aligns_different_date_axes()
    test_combined_equity_merges_lots_curves_and_isolates_a_failed_account()
    test_other_segments_skip_the_curve()
    test_account_without_the_curve_endpoint_is_reported_not_fatal()
    test_no_accounts()
    print('ALL OK')
