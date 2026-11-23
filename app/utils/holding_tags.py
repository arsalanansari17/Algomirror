"""Strategy tags for Holdings rows, taken from the strategy book.

OpenAlgo (fork-only POST /api/v1/pnl/attribution) joins an account's broker
holdings with its strategy book, which is built from the strategy tag on every
order. AlgoMirror used to rely on manual per-symbol labels (PositionTag) that the
Holdings page deleted when a symbol left the holdings, so a stopped-out and
re-bought stock lost its tag. The book needs no pruning: a re-buy is tagged the
moment the order is placed.

Manual tags stay as the fallback for what the book cannot explain (an
`Unattributed` slice: pre-OpenAlgo holdings, manual trades, a mismatching book)
and for accounts whose attribution call fails.

`tag_map` is pure; `fetch_attribution` does the HTTP and never raises.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 20

# Manual labels typed before the strategy book named strategies. Mapped on read so
# one strategy shows one name (and one filter chip), whichever way the row was tagged.
MANUAL_ALIASES = {'RSR': 'RSRotationPositional'}


def canonical_name(name):
    return MANUAL_ALIASES.get(name, name)


def tags_to_json(tags: dict) -> list:
    """A tag map as a JSON-safe list, to keep with the account's cached holdings."""
    return [[symbol, exchange, strategy, detail] for (symbol, exchange), (strategy, detail) in tags.items()]


def tags_from_json(value) -> dict:
    """Inverse of tags_to_json; anything malformed gives an empty map."""
    out = {}
    try:
        for symbol, exchange, strategy, detail in value or []:
            if strategy:
                out[(symbol, exchange)] = (strategy, detail)
    except (TypeError, ValueError):
        return {}
    return out


def _qty(value) -> float:
    try:
        return abs(float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def strategy_for_row(row: dict):
    """(strategy, detail) for one attributed holding row, or (None, None).

    * only slices the book really attributes count (`attributed`), with a quantity;
    * a row the book cannot reconcile with the broker (`mismatch`, e.g. a stale leg
      larger than the real holding) is not trusted: the caller falls back to the
      manual tag;
    * one strategy: that name; several: the one with the largest slice, and
      `detail` lists all of them ("RSRotationPositional 90, EquityBreakoutPositional 40").
    """
    if not isinstance(row, dict) or row.get('mismatch'):
        return None, None
    by_strategy = {}
    for piece in row.get('slices') or []:
        if not piece.get('attributed') or not piece.get('strategy'):
            continue
        qty = _qty(piece.get('quantity'))
        if qty > 0:
            by_strategy[piece['strategy']] = by_strategy.get(piece['strategy'], 0.0) + qty
    if not by_strategy:
        return None, None
    ranked = sorted(by_strategy.items(), key=lambda item: (-item[1], item[0]))
    detail = None
    if len(ranked) > 1:
        detail = ', '.join(f"{name} {qty:g}" for name, qty in ranked)
    return ranked[0][0], detail


def tag_map(rows) -> dict:
    """{(symbol, exchange): (strategy, detail)} for the rows the book explains."""
    out = {}
    for row in rows or []:
        strategy, detail = strategy_for_row(row)
        if strategy:
            out[(row.get('symbol'), row.get('exchange'))] = (strategy, detail)
    return out


def fetch_attribution(targets) -> dict:
    """{account_id: rows or None} from each account's OpenAlgo.

    `targets` is [(account_id, api_key, host_url)]. The calls run in parallel and
    only do HTTP (no Flask context needed). A failure, an error reply or a timeout
    gives None for that account, which makes its rows fall back to manual tags.
    """
    from app.utils.openalgo_client import ExtendedOpenAlgoAPI

    def one(api_key, host):
        client = ExtendedOpenAlgoAPI(api_key=api_key, host=host)
        reply = client.strategy_attribution('holdings')
        if isinstance(reply, dict) and reply.get('status') == 'success':
            return (reply.get('data') or {}).get('rows') or []
        return None

    results = {account_id: None for account_id, _, _ in targets}
    if not targets:
        return results
    # No `with`: leaving it would wait for every hung call, so the timeout bounds nothing.
    pool = ThreadPoolExecutor(max_workers=min(5, len(targets)))
    try:
        futures = {pool.submit(one, key, host): account_id for account_id, key, host in targets}
        try:
            for future in as_completed(futures, timeout=FETCH_TIMEOUT_SECONDS):
                account_id = futures[future]
                try:
                    results[account_id] = future.result()
                except Exception as exc:
                    logger.warning('Holdings attribution failed for account %s: %s', account_id, exc)
        except Exception as exc:
            logger.warning('Holdings attribution timed out: %s', exc)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return results
