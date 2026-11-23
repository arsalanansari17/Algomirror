#!/usr/bin/env python
"""Strategy tags for Holdings rows come from the strategy book, not from labels
that disappear when a symbol leaves the holdings (LAURUSLABS lost its tag when it
was stopped out on 16 Nov and re-bought on 17 Nov)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils import holding_tags as ht


def piece(strategy, qty, attributed=True):
    return {'strategy': strategy, 'quantity': qty, 'average_price': 100.0, 'attributed': attributed}


def row(symbol, slices, mismatch=False, exchange='NSE'):
    return {'symbol': symbol, 'exchange': exchange, 'slices': slices, 'mismatch': mismatch}


def test_one_strategy_gives_its_name():
    assert ht.strategy_for_row(row('LAURUSLABS', [piece('RSRotationPositional', 90)])) == ('RSRotationPositional', None)


def test_two_strategies_give_the_largest_with_a_detail_line():
    r = row('WELSPUNLIV', [piece('RSRotationPositional', 332), piece('EquityBreakoutPositional', 40)])
    assert ht.strategy_for_row(r) == ('RSRotationPositional', 'RSRotationPositional 332, EquityBreakoutPositional 40')


def test_an_unattributed_remainder_does_not_count():
    r = row('CYIENT', [piece('Unattributed', 98, attributed=False)])
    assert ht.strategy_for_row(r) == (None, None)


def test_attributed_part_plus_unattributed_remainder_uses_the_attributed_part():
    r = row('CYIENT', [piece('EquityBreakoutPositional', 143), piece('Unattributed', 98, attributed=False)])
    assert ht.strategy_for_row(r) == ('EquityBreakoutPositional', None)


def test_a_mismatching_book_is_not_trusted():
    # a stale leg larger than the real holding: the caller falls back to the manual tag
    r = row('WELSPUNLIV', [piece('EquityBreakoutPositional', 808)], mismatch=True)
    assert ht.strategy_for_row(r) == (None, None)


def test_a_flat_slice_gives_no_tag():
    assert ht.strategy_for_row(row('X', [piece('RSRotationPositional', 0)])) == (None, None)


def test_equal_slices_pick_the_alphabetically_first_so_the_tag_is_stable():
    r = row('X', [piece('B', 10), piece('A', 10)])
    assert ht.strategy_for_row(r)[0] == 'A'


def test_garbage_input_is_ignored():
    assert ht.strategy_for_row(None) == (None, None)
    assert ht.strategy_for_row({'slices': None}) == (None, None)
    assert ht.strategy_for_row(row('X', [{'strategy': None, 'quantity': 5, 'attributed': True}])) == (None, None)
    assert ht.strategy_for_row(row('X', [piece('S', 'abc')])) == (None, None)


def test_tag_map_is_keyed_by_symbol_and_exchange_and_skips_untagged_rows():
    rows = [
        row('LAURUSLABS', [piece('RSRotationPositional', 90)]),
        row('CYIENT', [piece('Unattributed', 98, attributed=False)]),
        row('LAURUSLABS', [piece('Other', 5)], exchange='BSE'),
    ]
    assert ht.tag_map(rows) == {
        ('LAURUSLABS', 'NSE'): ('RSRotationPositional', None),
        ('LAURUSLABS', 'BSE'): ('Other', None),
    }
    assert ht.tag_map(None) == {}


def test_fetch_attribution_with_no_targets():
    assert ht.fetch_attribution([]) == {}


def test_fetch_attribution_returns_none_for_a_failing_account(monkeypatch):
    class Fake:
        def __init__(self, api_key, host):
            self.api_key = api_key

        def strategy_attribution(self, kind):
            if self.api_key == 'bad':
                raise RuntimeError('boom')
            if self.api_key == 'err':
                return {'status': 'error', 'message': 'no book'}
            return {'status': 'success', 'data': {'rows': [row('A', [piece('S', 1)])]}}

    import app.utils.openalgo_client as client_module
    monkeypatch.setattr(client_module, 'ExtendedOpenAlgoAPI', Fake)
    out = ht.fetch_attribution([(1, 'good', 'h1'), (2, 'bad', 'h2'), (3, 'err', 'h3')])
    assert out[1] == [row('A', [piece('S', 1)])]
    assert out[2] is None and out[3] is None


def test_tags_round_trip_through_json_and_malformed_input_gives_nothing():
    tags = {('LAURUSLABS', 'NSE'): ('RSRotationPositional', None), ('WELSPUNLIV', 'NSE'): ('A', 'A 3, B 2')}
    assert ht.tags_from_json(ht.tags_to_json(tags)) == tags
    assert ht.tags_from_json(None) == {}
    assert ht.tags_from_json('oops') == {}
    assert ht.tags_from_json([['only', 'two']]) == {}


def test_a_down_account_keeps_its_saved_tags():
    # the page reads the saved tags before overwriting the cached holdings, and uses
    # them when the attribution call returns None (its VM is off)
    saved = ht.tags_to_json({('LAURUSLABS', 'NSE'): ('RSRotationPositional', None)})
    fresh = None
    tags = ht.tag_map(fresh) if fresh is not None else ht.tags_from_json(saved)
    assert tags[('LAURUSLABS', 'NSE')][0] == 'RSRotationPositional'


def test_manual_rsr_label_is_shown_under_the_book_name():
    assert ht.canonical_name('RSR') == 'RSRotationPositional'
    assert ht.canonical_name('EquityBreakoutPositional') == 'EquityBreakoutPositional'


def test_a_hung_account_does_not_hold_the_page_up(monkeypatch):
    import time

    class Slow:
        def __init__(self, api_key, host):
            pass

        def strategy_attribution(self, kind):
            time.sleep(3)
            return {'status': 'success', 'data': {'rows': []}}

    import app.utils.openalgo_client as client_module
    monkeypatch.setattr(client_module, 'ExtendedOpenAlgoAPI', Slow)
    monkeypatch.setattr(ht, 'FETCH_TIMEOUT_SECONDS', 0.3)
    started = time.monotonic()
    out = ht.fetch_attribution([(1, 'k', 'h')])
    assert out == {1: None}
    assert time.monotonic() - started < 1.5
