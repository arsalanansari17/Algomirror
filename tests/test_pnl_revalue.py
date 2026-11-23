#!/usr/bin/env python
"""P&L Analysis reprices open holdings with the Holdings page's price chain, so the two
pages agree on the price part of unrealized P&L.

23 Nov 2026: Holdings showed acc2's CYIENT lot at a stale 1121.70; P&L Analysis valued
lots at the stored closes (CYIENT 1153.70, provisional) against a real 1160.50. Only
holdings that belong to a strategy move the curve: old holdings with no fills in the
ledger (IDEAFORGE) were never in it and must not suddenly enter it.
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils import pnl_revalue as pr
from app.utils.pnl_analysis_combined import compute_combined_pnl_analysis

IST = timezone(timedelta(hours=5, minutes=30))
MON_EVENING = datetime(2026, 11, 23, 17, 0, tzinfo=IST)
EBP, RS = 'EquityBreakoutPositional', 'RSRotationPositional'


def unreal(ltp, avg, qty):
    return round((ltp - avg) * qty, 2)


def row(symbol, qty, avg, ltp, strategy=None, source='holdings', action='BUY'):
    return {'symbol': symbol, 'exchange': 'NSE', 'source': source, 'action': action, 'quantity': qty,
            'average_price': avg, 'strategy': strategy, 'ltp': ltp,
            'unrealized_pnl': unreal(ltp, avg, qty) * (-1 if action == 'SELL' else 1)}


# What OpenAlgo returned: the stored (provisional) close 1153.70 for CYIENT.
ROWS_ACC1 = [row('CYIENT', 143, 1100.17, 1153.7, strategy=EBP),
             row('IDEAFORGE', 100, 500.0, 400.0)]                      # legacy: no strategy, no tag
ROWS_ACC2 = [row('CYIENT', 98, 1099.46, 1153.7)]                       # book cannot attribute it
TAGS = {(2, 'CYIENT'): EBP}                                            # manual tag
REAL = {'CYIENT': 1160.5, 'IDEAFORGE': 410.0}


def price_of(symbol, exchange):
    ltp = REAL.get(symbol)
    return {'ltp': ltp, 'source': 'quote'} if ltp else None


def scope_of(account_id):
    return lambda r: r.get('strategy') or TAGS.get((account_id, r['symbol']))


def test_rows_are_repriced_and_only_strategy_rows_make_a_delta():
    rows, deltas, delta_all = pr.revalue_open_rows(ROWS_ACC1, price_of, scope_of(1))
    cyient, ideaforge = rows
    assert cyient['ltp'] == 1160.5 and cyient['price_source'] == 'quote'
    assert cyient['unrealized_pnl'] == unreal(1160.5, 1100.17, 143)
    assert ideaforge['unrealized_pnl'] == unreal(410.0, 500.0, 100)
    cyient_delta = unreal(1160.5, 1100.17, 143) - unreal(1153.7, 1100.17, 143)
    ideaforge_delta = unreal(410.0, 500.0, 100) - unreal(400.0, 500.0, 100)
    assert deltas == {EBP: cyient_delta}                                  # IDEAFORGE does not move the curve
    assert round(delta_all, 2) == round(cyient_delta + ideaforge_delta, 2)  # but it is in the account total


def test_a_manual_tag_puts_an_unattributed_row_in_scope():
    _, deltas, _ = pr.revalue_open_rows(ROWS_ACC2, price_of, scope_of(2))
    assert deltas == {EBP: unreal(1160.5, 1099.46, 98) - unreal(1153.7, 1099.46, 98)}
    _, none, _ = pr.revalue_open_rows(ROWS_ACC2, price_of, scope_of(9))   # another account: no tag
    assert none == {}


def test_a_row_without_a_price_is_left_as_openalgo_valued_it():
    rows = [row('NOPRICE', 10, 100.0, 110.0, strategy=EBP)]
    out, deltas, delta_all = pr.revalue_open_rows(rows, price_of)
    assert out == rows and deltas == {} and delta_all == 0.0


def test_futures_and_options_rows_pass_through_unchanged():
    fno = row('NIFTY26NOV25000PE', 65, 40.0, 10.0, source='positions', action='SELL')
    out, deltas, delta_all = pr.revalue_open_rows([fno], price_of)
    assert out == [fno] and deltas == {} and delta_all == 0.0


def curve(last_date='2026-11-23', ebp_last=7654.79):
    return {
        'dates': ['2026-11-19', '2026-11-20', last_date],
        'by_strategy': {
            EBP: {'realized': [0, 0, 0], 'unrealized': [1000.0, 2000.0, ebp_last]},
            RS: {'realized': [0, 0, 0], 'unrealized': [0.0, 500.0, 600.0]},
        },
        'basis': 'actual_cost', 'base_date': None, 'notes': {},
    }


def test_only_the_last_unrealized_level_of_a_strategy_in_the_curve_moves():
    fixed, total = pr.revalue_curve(curve(), {EBP: 972.4, 'Untagged': 5000.0}, MON_EVENING)
    assert fixed['by_strategy'][EBP]['unrealized'] == [1000.0, 2000.0, round(7654.79 + 972.4, 2)]
    assert fixed['by_strategy'][RS]['unrealized'] == [0.0, 500.0, 600.0]      # untouched
    assert fixed['by_strategy'][EBP]['realized'] == [0, 0, 0]
    assert 'Untagged' not in fixed['by_strategy'] and total == 972.4         # the ledger never held it


def test_a_curve_that_stops_before_the_latest_session_is_not_touched():
    old = curve(last_date='2026-11-20')
    fixed, total = pr.revalue_curve(old, {EBP: 972.4}, MON_EVENING)
    assert fixed is old and total == 0.0


def test_the_input_curve_is_not_mutated_and_no_deltas_changes_nothing():
    original = curve()
    pr.revalue_curve(original, {EBP: 1.0}, MON_EVENING)
    assert original['by_strategy'][EBP]['unrealized'][-1] == 7654.79
    same, total = pr.revalue_curve(original, {}, MON_EVENING)
    assert same is original and total == 0.0


class FakeAccount:
    def __init__(self, id, name):
        self.id, self.account_name, self.host_url = id, name, f'http://h{id}'

    def get_api_key(self):
        return f'k{self.id}'


def fake_history(self, start_date, end_date, symbol=None, segment=None, strategy=None):
    rows = {'k1': ROWS_ACC1, 'k2': ROWS_ACC2}[self.api_key]
    total = sum(r['unrealized_pnl'] for r in rows)
    return {'status': 'success', 'data': {'closed_trades': [], 'open_positions': rows, 'total_unrealized_pnl': total}}


def fake_curve(self, start_date, end_date, basis='actual_cost', symbol_contains=None):
    # the ledger only knows the EBP/RS lots, valued like OpenAlgo's rows (CYIENT at 1153.70)
    last = unreal(1153.7, 1100.17, 143) if self.api_key == 'k1' else unreal(1153.7, 1099.46, 98)
    return {'status': 'success', 'data': curve(ebp_last=last)}


def run(factory, accounts=None, scope=TAGS):
    accounts = accounts or [FakeAccount(1, 'arsalan'), FakeAccount(2, 'iram')]
    with patch('app.utils.openalgo_client.ExtendedOpenAlgoAPI.pnl_history', fake_history), \
         patch('app.utils.openalgo_client.ExtendedOpenAlgoAPI.pnl_curve', fake_curve):
        return compute_combined_pnl_analysis(
            accounts, '2026-05-01', '2026-11-23', 'equity',
            price_of_factory=factory, now=MON_EVENING, scope_tags=scope)


def test_the_curve_ties_to_the_holdings_page_for_the_strategy_holdings():
    result = run(lambda keys: price_of)
    # Holdings filtered to the two strategies: CYIENT on acc1 (book) and on acc2 (manual tag), at 1160.50
    holdings_filtered = unreal(1160.5, 1100.17, 143) + unreal(1160.5, 1099.46, 98)
    ebp_last = result['curve']['by_strategy'][EBP]['unrealized'][-1]
    assert round(ebp_last, 2) == round(holdings_filtered, 2)
    # RS untouched, no 'Untagged' strategy appeared: the legacy holding did not enter the curve
    assert set(result['curve']['by_strategy']) == {EBP, RS}
    # the open positions table and total are repriced too, legacy stock included (unfiltered Holdings)
    assert [p['ltp'] for p in result['open_positions']] == [1160.5, 410.0, 1160.5]
    assert result['total_unrealized_pnl'] == round(
        holdings_filtered + unreal(410.0, 500.0, 100), 2)
    assert result['curve']['notes']['unrealized_revalued'] == round(
        (unreal(1160.5, 1100.17, 143) - unreal(1153.7, 1100.17, 143))
        + (unreal(1160.5, 1099.46, 98) - unreal(1153.7, 1099.46, 98)), 2)


def test_without_a_manual_tag_an_unattributed_holding_does_not_move_the_curve():
    result = run(lambda keys: price_of, scope={})
    acc2_only = unreal(1153.7, 1099.46, 98)
    assert round(result['curve']['by_strategy'][EBP]['unrealized'][-1], 2) == round(
        unreal(1160.5, 1100.17, 143) + acc2_only, 2)


def test_without_a_price_chain_openalgos_valuation_is_unchanged():
    result = run(None)
    assert 'unrealized_revalued' not in result['curve']['notes']
    assert result['open_positions'][0]['ltp'] == 1153.7


def test_a_failing_price_chain_falls_back_to_openalgos_valuation():
    def boom(keys):
        raise RuntimeError('store down')
    result = run(boom)
    assert result['open_positions'][0]['ltp'] == 1153.7
    assert 'unrealized_revalued' not in result['curve']['notes']


def test_a_range_that_does_not_end_today_has_no_live_figure_and_is_not_revalued():
    def history_past(self, *args, **kwargs):
        return {'status': 'success', 'data': {'closed_trades': [], 'open_positions': [],
                                              'total_unrealized_pnl': None}}
    with patch('app.utils.openalgo_client.ExtendedOpenAlgoAPI.pnl_history', history_past), \
         patch('app.utils.openalgo_client.ExtendedOpenAlgoAPI.pnl_curve', fake_curve):
        result = compute_combined_pnl_analysis(
            [FakeAccount(1, 'arsalan')], '2026-05-01', '2026-05-31', 'equity',
            price_of_factory=lambda keys: price_of, now=MON_EVENING)
    assert result['total_unrealized_pnl'] is None
    assert 'unrealized_revalued' not in result['curve']['notes']


def test_pick_source_account_matches_the_host_substring():
    accounts = [FakeAccount(1, 'a'), FakeAccount(2, 'b')]
    accounts[1].host_url = 'https://acc4.skyshieldedge.com/'
    assert pr.pick_source_account(accounts, 'acc4.').id == 2
    assert pr.pick_source_account(accounts, 'nope') is None
    assert pr.pick_source_account(accounts, '') is None


def test_build_price_of_uses_quotes_on_a_weekday_and_the_store_at_the_weekend(monkeypatch):
    monkeypatch.setattr(pr.holding_price, 'latest_closes',
                        lambda keys, now: {('CYIENT', 'NSE'): [(date(2026, 11, 19), 1111.0), (date(2026, 11, 20), 1155.5)]})
    monkeypatch.setattr(pr, 'fetch_source_quotes',
                        lambda account, keys: {('CYIENT', 'NSE'): {'ltp': 1387.9, 'prev_close': 1100.0}})
    sat = datetime(2026, 11, 21, 12, 0, tzinfo=IST)
    assert pr.build_price_of({('CYIENT', 'NSE')}, object(), MON_EVENING)('CYIENT', 'NSE')['ltp'] == 1387.9
    assert pr.build_price_of({('CYIENT', 'NSE')}, object(), sat)('CYIENT', 'NSE')['ltp'] == 1155.5
    assert pr.build_price_of({('CYIENT', 'NSE')}, object(), sat)('UNKNOWN', 'NSE') is None
