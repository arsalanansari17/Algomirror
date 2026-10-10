#!/usr/bin/env python
"""
Tests for app/utils/position_cost_basis.py - the rule that puts the strategy
book's real entry average on a carried Kotak leg (whose broker "average" is
the previous settlement price, upstream marketcalls/openalgo#2061).

Mirrors the cases of OpenAlgo's frontend test
(strategyAttribution.test.ts, `applyCostBasis`) so the two pages behave the
same. Standalone script, print+assert, like tests/test_pnl_history_combined.py;
the functions are also plain pytest tests.
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.position_cost_basis import apply_cost_basis, has_carry_forward_valuation  # noqa: E402

FLAG = 'carry_forward_valuation'


def pos(**over):
    p = {
        'symbol': 'NIFTY13OCT2622800CE', 'exchange': 'NFO', 'product': 'NRML',
        'quantity': -130, 'average_price': 12.35, 'ltp': 16.65, 'pnl': -559.0,
        'average_price_basis': FLAG,
    }
    p.update(over)
    return p


def sl(strategy, quantity, average_price, today=0.0, attributed=None):
    return {
        'strategy': strategy, 'quantity': quantity, 'average_price': average_price,
        'today_realized_pnl': today,
        'attributed': (strategy != 'Unattributed') if attributed is None else attributed,
    }


def row(slices, **over):
    r = {'symbol': 'NIFTY13OCT2622800CE', 'exchange': 'NFO', 'product': 'NRML',
         'quantity': 0, 'average_price': 0, 'slices': slices, 'mismatch': False}
    r.update(over)
    return r


def test_flagged_fully_explained_row_gets_the_book_average_and_a_recomputed_pnl():
    rows = [pos()]
    n = apply_cost_basis(rows, [row([sl('NDS', -130, 59.85)])])
    assert n == 1
    assert rows[0]['average_price'] == 59.85
    assert rows[0]['average_price_basis'] == 'strategy_book'
    assert rows[0]['broker_average_price'] == 12.35
    # short 130 from 59.85, now 16.65: +5,616, not Kotak's -559
    assert abs(rows[0]['pnl'] - 130 * (59.85 - 16.65)) < 0.01


def test_long_leg_is_corrected_too():
    rows = [pos(quantity=130, ltp=6.2, pnl=0.0)]
    apply_cost_basis(rows, [row([sl('NDS', 130, 22.65)])])
    assert rows[0]['average_price'] == 22.65
    assert abs(rows[0]['pnl'] - 130 * (6.2 - 22.65)) < 0.01


def test_two_strategies_are_weighted_by_quantity():
    rows = [pos()]
    apply_cost_basis(rows, [row([sl('A', -100, 50), sl('B', -30, 60)])])
    assert abs(rows[0]['average_price'] - round((100 * 50 + 30 * 60) / 130, 2)) < 0.011


def test_realized_today_is_added_and_no_ltp_shows_only_that():
    rows = [pos()]
    apply_cost_basis(rows, [row([sl('NDS', -130, 59.85, today=400.0)])])
    assert abs(rows[0]['pnl'] - (130 * (59.85 - 16.65) + 400)) < 0.01
    rows = [pos(ltp=0)]
    apply_cost_basis(rows, [row([sl('NDS', -130, 59.85, today=250.0)])])
    assert rows[0]['average_price'] == 59.85 and rows[0]['pnl'] == 250.0


def test_unflagged_rows_are_left_exactly_alone():
    plain = pos(average_price=59.85)
    del plain['average_price_basis']
    before = copy.deepcopy(plain)
    assert apply_cost_basis([plain], [row([sl('NDS', -130, 40)])]) == 0
    assert plain == before


def test_rows_the_book_does_not_fully_explain_keep_the_brokers_numbers():
    cases = [
        row([sl('NDS', -100, 59.85), sl('Unattributed', -30, 12.35)]),   # part unattributed
        row([sl('NDS', -100, 59.85)]),                                   # 100 of 130
        row([sl('NDS', 130, 59.85)]),                                    # wrong side
        row([sl('NDS', -130, 59.85)], mismatch=True),                    # book says mismatch
        row([]),                                                         # no slices
    ]
    for r in cases:
        rows = [pos()]
        before = copy.deepcopy(rows)
        assert apply_cost_basis(rows, [r]) == 0
        assert rows == before


def test_closed_rows_and_other_contracts_are_left_alone():
    closed = [pos(quantity=0, average_price=0.0)]
    before = copy.deepcopy(closed)
    assert apply_cost_basis(closed, [row([sl('NDS', -130, 59.85)])]) == 0
    assert closed == before
    other = [pos(symbol='OTHER')]
    assert apply_cost_basis(other, [row([sl('NDS', -130, 59.85)])]) == 0
    assert other[0]['average_price'] == 12.35


def test_helpers_handle_missing_input():
    assert has_carry_forward_valuation([pos()]) is True
    assert has_carry_forward_valuation([pos(quantity=0)]) is False
    p = pos()
    del p['average_price_basis']
    assert has_carry_forward_valuation([p]) is False
    assert apply_cost_basis([pos()], None) == 0
    assert apply_cost_basis([], [row([])]) == 0


if __name__ == '__main__':
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for name, fn in tests:
        fn()
        print('ok  ', name)
    print(f'\n{len(tests)}/{len(tests)} passed')
