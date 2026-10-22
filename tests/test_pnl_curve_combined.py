#!/usr/bin/env python
"""compute_combined_pnl: an account with no trades today must still carry a
zero series on the shared timeline, so the page can sum any subset of accounts
index by index (an empty first series used to blank the plot)."""
import os
import sys
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils import pnl_curve


class FakeAccount:
    def __init__(self, id, account_name):
        self.id = id
        self.account_name = account_name
        self.host_url = 'http://fake'

    def get_api_key(self):
        return 'k'


def test_account_without_trades_gets_a_zero_series():
    idx = pd.date_range('2026-10-22 09:30', periods=3, freq='min', tz='Asia/Kolkata')
    series = {1: None, 2: None, 3: pd.Series([0.0, 100.0, 50.0], index=idx)}

    def fake_series(client, today=None):
        return series[client.id]

    class FakeClient:
        def __init__(self, api_key, host):
            self.id = int(api_key)

    accounts = [FakeAccount(1, 'acc1'), FakeAccount(2, 'acc2'), FakeAccount(3, 'acc3')]
    for a in accounts:
        a.get_api_key = (lambda i=a.id: str(i))

    with patch.object(pnl_curve, 'ExtendedOpenAlgoAPI', FakeClient), \
         patch.object(pnl_curve, 'compute_account_series', fake_series):
        result = pnl_curve.compute_combined_pnl(accounts)

    by_id = {e['account_id']: e for e in result['per_account']}
    assert [p['value'] for p in by_id[1]['series']] == [0.0, 0.0, 0.0]
    assert len(by_id[2]['series']) == len(result['pnl_series']) == 3
    assert [p['value'] for p in by_id[3]['series']] == [0.0, 100.0, 50.0]
    assert [p['time'] for p in by_id[1]['series']] == [p['time'] for p in result['pnl_series']]
    assert result['current_mtm'] == 50.0
    print('zero series: ok')


def test_openalgo_curve_is_used_and_local_is_the_fallback():
    base = 1_760_000_000_000  # ms
    remote = {'status': 'success', 'data': {'pnl_series': [
        {'time': base, 'value': 10.0}, {'time': base + 60000, 'value': 25.0}]}}
    local_idx = pd.date_range('2026-10-22 09:30', periods=2, freq='min', tz='Asia/Kolkata')
    calls = {'local': 0, 'basis': None}

    class FakeClient:
        def __init__(self, api_key, host):
            self.id = int(api_key)

        def pnl_intraday(self, basis):
            calls['basis'] = basis
            if self.id == 1:
                return remote
            if self.id == 2:
                return {'status': 'success', 'data': None}   # cannot build exactly
            return {'status': 'error', 'message': 'Not found'}  # older OpenAlgo

    def fake_local(client, today=None):
        calls['local'] += 1
        return pd.Series([1.0, 2.0], index=local_idx)

    accounts = [FakeAccount(i, f'acc{i}') for i in (1, 2, 3)]
    for a in accounts:
        a.get_api_key = (lambda i=a.id: str(i))
    with patch.object(pnl_curve, 'ExtendedOpenAlgoAPI', FakeClient),          patch.object(pnl_curve, 'compute_account_series', fake_local):
        result = pnl_curve.compute_combined_pnl(accounts, 'm2m')

    assert calls['basis'] == 'm2m'
    assert calls['local'] == 2  # accounts 2 and 3 fell back
    by_id = {e['account_id']: e for e in result['per_account']}
    assert by_id[1]['current_pnl'] == 25.0 and by_id[1]['error'] is None
    print('openalgo curve + fallback: ok')


if __name__ == '__main__':
    test_account_without_trades_gets_a_zero_series()
    test_openalgo_curve_is_used_and_local_is_the_fallback()
    print('ALL OK')
