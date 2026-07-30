"""
Combined intraday P&L curve across multiple trading accounts.

Ports OpenAlgo's own intraday mark-to-market algorithm
(openalgo/blueprints/pnltracker.py get_pnl_data) so it can run once per
TradingAccount using AlgoMirror's per-account ExtendedOpenAlgoAPI client
(instead of OpenAlgo's single Flask session), then merges every account's
Total_PnL series into one portfolio curve. OpenAlgo itself cannot do this
merge because each OpenAlgo instance only ever sees its own broker session.

Intraday only - nothing here is persisted, the curve is rebuilt from each
account's tradebook + positionbook + today's 1m candles on every call.
"""
import concurrent.futures
import logging
import threading
import time as time_module
from datetime import datetime
from datetime import time as dt_time

import pandas as pd
import pytz

from app.utils.openalgo_client import ExtendedOpenAlgoAPI

logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')


class AccountPnlError(Exception):
    """Raised when an account's P&L can't be computed because both its
    tradebook and positionbook fetches failed - distinct from the normal
    "no trades or positions today" case (which legitimately returns None),
    so the caller can warn instead of silently treating the account as
    contributing zero to the combined total."""


class _RateLimiter:
    """Per-account throttle for the 1m history calls (2/sec, under the broker's 3/sec cap)."""

    def __init__(self, calls_per_second=2):
        self.min_interval = 1.0 / calls_per_second
        self.last_call_time = 0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            elapsed = time_module.time() - self.last_call_time
            if elapsed < self.min_interval:
                time_module.sleep(self.min_interval - elapsed)
            self.last_call_time = time_module.time()


def _parse_trade_timestamp(timestamp_str, fallback_date=None):
    """Parse a broker trade timestamp (several known formats) into an IST-aware datetime."""
    if timestamp_str is None:
        return None

    if isinstance(timestamp_str, (int, float)):
        try:
            dt = pd.to_datetime(timestamp_str, unit='s')
            return dt.tz_localize('UTC').tz_convert(IST) if dt.tz is None else dt.tz_convert(IST)
        except Exception:
            return None

    if not isinstance(timestamp_str, str):
        return None
    timestamp_str = timestamp_str.strip()
    if not timestamp_str:
        return None

    formats = [
        '%d-%b-%Y %H:%M:%S',
        '%H:%M:%S %d-%m-%Y',
        '%d-%m-%Y %H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%dT%H:%M:%S',
    ]
    for fmt in formats:
        try:
            return IST.localize(datetime.strptime(timestamp_str, fmt))
        except ValueError:
            continue

    if ':' in timestamp_str and ' ' not in timestamp_str:
        try:
            parts = timestamp_str.split(':')
            if len(parts) >= 2 and len(parts[0]) <= 2:
                today = fallback_date or datetime.now(IST).date()
                dt = datetime.combine(today, dt_time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0))
                return IST.localize(dt)
        except (ValueError, IndexError):
            pass

    try:
        dt = pd.to_datetime(timestamp_str)
        return dt.tz_localize(IST) if dt.tz is None else dt.tz_convert(IST)
    except Exception:
        return None


def _effective_trade_qty(trade):
    """Quantity to use for a trade, applying the same fallback everywhere it's
    needed: some broker fill records report quantity=0 with the real size
    only inferable from trade_value/average_price."""
    try:
        qty = float(trade.get('quantity', 0))
        price = float(trade.get('average_price', 0))
    except (TypeError, ValueError):
        return 0.0
    if qty == 0 and price > 0:
        try:
            trade_value = float(trade.get('trade_value', 0) or 0)
        except (TypeError, ValueError):
            trade_value = 0
        qty = 1 if trade_value == price else (trade_value / price if trade_value > 0 else 0)
    return qty


def _history_df(client, symbol, exchange, today_str, rate_limiter):
    """Fetch today's 1m candles for a symbol, indexed by IST datetime. None on failure/empty.

    The openalgo SDK's history() returns a pandas DataFrame directly (index
    already tz-aware IST, sorted, deduped) on success, or an error dict on
    failure - see openalgo/data.py DataAPI.history().
    """
    rate_limiter.wait()
    try:
        result = client.history(symbol=symbol, exchange=exchange, interval='1m',
                                 start_date=today_str, end_date=today_str)
    except Exception:
        logger.exception(f'Error fetching history for {symbol}/{exchange}')
        return None

    if not isinstance(result, pd.DataFrame) or result.empty or 'close' not in result.columns:
        return None
    return result


def _build_position_windows(trades_list):
    """Reconstruct BUY/SELL open/close windows for one symbol's trades, in
    trade order. A trade first closes existing opposite-side open windows
    (oldest first; partial closes split the window into a closed portion and
    a smaller still-open remainder); any quantity beyond what's open on the
    opposite side opens a new same-side window. This correctly handles
    partial closes, full closes, and reversals (a single trade crossing from
    long to short or vice versa) symmetrically in either direction - a SELL
    that exceeds an open long closes it and opens a new short for the
    excess, and just as importantly, a BUY that covers an open short closes
    it the same way (the original version only ever matched SELL-closes-BUY,
    so a covering BUY for a short position was never recognized as a close
    at all and just opened an unrelated second window).
    """
    windows = []

    for trade in trades_list:
        action = trade.get('action', '')
        if action not in ('BUY', 'SELL'):
            continue
        trade_time = trade.get('parsed_time')
        try:
            executed_price = float(trade.get('average_price', 0) or 0)
        except (TypeError, ValueError):
            continue
        qty = _effective_trade_qty(trade)
        if qty <= 0:
            continue

        opposite = 'SELL' if action == 'BUY' else 'BUY'
        remaining = qty
        for window in windows:
            if remaining <= 0:
                break
            if window['action'] != opposite or window['end_time'] is not None:
                continue
            close_qty = min(window['qty'], remaining)
            if close_qty == window['qty']:
                window['end_time'] = trade_time
                window['exit_price'] = executed_price
            else:
                window['qty'] -= close_qty
                closed = window.copy()
                closed['qty'] = close_qty
                closed['end_time'] = trade_time
                closed['exit_price'] = executed_price
                windows.append(closed)
            remaining -= close_qty

        if remaining > 0:
            windows.append({'start_time': trade_time, 'end_time': None, 'qty': remaining,
                             'price': executed_price, 'action': action, 'exit_price': None})

    return windows


def _replay_symbol_pnl(df_hist, col_key, windows, current_time):
    """Mark each position window to the historical close price; freeze at
    realized P&L once closed. Each window's contribution is computed as its
    own independent series and summed at the end, rather than accumulated
    into one shared column - multiple windows can be open or closing on the
    same symbol at once (partial closes, reversals), and their contributions
    must compose additively. The original version wrote every window's
    result into one shared column and, on close, overwrote every future
    timestamp with just that window's realized amount - which silently
    erased any other still-open window's ongoing mark-to-market contribution
    at those same timestamps (the main symptom: a partial close made the
    remaining open position's P&L freeze/vanish instead of keep moving).
    """
    df_hist = df_hist[['close']].copy()
    total = pd.Series(0.0, index=df_hist.index)

    for window in windows:
        if window['start_time'] is None:
            continue
        start = window['start_time']
        end = window['end_time'] if window['end_time'] else current_time
        mask = (df_hist.index >= start) & (df_hist.index <= end)
        has_data = mask.any()
        is_closed = window['end_time'] is not None and window.get('exit_price') is not None

        if not has_data and not is_closed:
            continue

        contribution = pd.Series(0.0, index=df_hist.index)
        if has_data:
            price_col = df_hist.loc[mask, 'close']
            if window['action'] == 'BUY':
                contribution.loc[mask] = (price_col - window['price']) * window['qty']
            else:
                contribution.loc[mask] = (window['price'] - price_col) * window['qty']

        if is_closed:
            if window['action'] == 'BUY':
                realized = (window['exit_price'] - window['price']) * window['qty']
            else:
                realized = (window['price'] - window['exit_price']) * window['qty']

            future_mask = df_hist.index > window['end_time']
            if future_mask.any():
                contribution.loc[future_mask] = realized
            elif len(df_hist) > 0:
                # Close happened at/after the last available candle - no data
                # to mark the position to between the last candle and the
                # actual close, so show the known realized result on that
                # final point rather than a stale pre-close MTM estimate.
                contribution.iloc[-1] = realized

        total = total.add(contribution, fill_value=0.0)

    return total.rename(f'{col_key}_pnl').to_frame()


def compute_account_series(client, today=None):
    """
    Reconstruct today's minute-by-minute mark-to-market P&L for one account
    from its tradebook + open positions.

    Returns a pandas Series (IST datetime index -> cumulative Total P&L), or
    None if the account genuinely has neither trades nor open positions
    today. Raises AccountPnlError if both the tradebook and positionbook
    fetches themselves failed - the caller should surface that distinctly
    rather than silently treating the account as contributing zero.
    """
    rate_limiter = _RateLimiter()
    current_time = datetime.now(IST)
    today_date = today or current_time.date()
    today_str = today_date.strftime('%Y-%m-%d')

    tradebook_ok = False
    try:
        trades_resp = client.tradebook()
        tradebook_ok = isinstance(trades_resp, dict) and trades_resp.get('status') == 'success'
    except Exception:
        logger.exception('Error fetching tradebook')
        trades_resp = None
    raw_trades = trades_resp.get('data', []) if tradebook_ok else []

    positionbook_ok = False
    current_positions = {}
    try:
        pos_resp = client.positionbook()
        positionbook_ok = isinstance(pos_resp, dict) and pos_resp.get('status') == 'success'
        if positionbook_ok:
            for pos in pos_resp.get('data', []):
                try:
                    key = f"{pos['symbol']}_{pos['exchange']}"
                    current_positions[key] = {
                        'symbol': pos['symbol'],
                        'exchange': pos['exchange'],
                        'quantity': float(pos.get('quantity', 0)),
                        'average_price': float(pos.get('average_price', 0)),
                    }
                except (ValueError, TypeError, KeyError):
                    continue
    except Exception:
        logger.exception('Error fetching positionbook')

    if not tradebook_ok and not positionbook_ok:
        raise AccountPnlError('Both tradebook and positionbook fetches failed')

    # Some broker tradebook responses aren't guaranteed to be scoped to just
    # today - drop anything that doesn't actually land on today_date so a
    # stray prior-session entry can't feed a window with a stale entry price
    # or (as the original version did) redefine which calendar date the
    # whole computation targets by taking the earliest trade's date as
    # "today".
    trades = []
    for trade in raw_trades:
        ts = trade.get('timestamp') or trade.get('fill_timestamp') or trade.get('fill_time')
        parsed_time = _parse_trade_timestamp(ts, fallback_date=today_date) if ts else None
        if parsed_time is None or parsed_time.date() != today_date:
            continue
        trade = dict(trade)
        trade['parsed_time'] = parsed_time
        trades.append(trade)

    if not trades and not current_positions:
        return None

    symbol_trades = {}
    for trade in trades:
        symbol, exchange = trade.get('symbol', ''), trade.get('exchange', '')
        if not symbol or not exchange:
            continue
        symbol_trades.setdefault(f'{symbol}_{exchange}', []).append(trade)

    all_keys = set(symbol_trades.keys()) | set(current_positions.keys())
    portfolio_pnl = None

    for pos_key in all_keys:
        trades_list = sorted(symbol_trades.get(pos_key, []), key=lambda t: t['parsed_time'])
        pos_data = current_positions.get(pos_key)
        if trades_list:
            symbol, exchange = trades_list[0].get('symbol', ''), trades_list[0].get('exchange', '')
        elif pos_data:
            symbol, exchange = pos_data['symbol'], pos_data['exchange']
        else:
            continue
        if not symbol or not exchange:
            continue

        df_hist = _history_df(client, symbol, exchange, today_str, rate_limiter)
        if df_hist is None or df_hist.empty:
            continue
        # Whatever candle actually opens the symbol's day, rather than
        # assuming NSE's 09:15 - the original hardcoded 09:15 meant a
        # carry-forward position's morning MTM could start from the wrong
        # point (or be silently clipped) for any other exchange/session.
        day_start = df_hist.index[0]

        # If this symbol carries a position from before today (whether or
        # not it also traded today), seed a synthetic opening trade for that
        # overnight quantity at day_start so the normal window-building/
        # replay logic below tracks it uniformly alongside today's real
        # trades - handles pure carry-forward (no trades today), carry-
        # forward closed today, and carry-forward adjusted (not fully
        # closed) today the same way. The seed price uses positionbook's
        # average_price, which is exact for a carry-forward left untouched
        # or fully closed today, and an approximation (blended with today's
        # fills) if today's trades also added to the position - the best
        # available without full historical cost-basis tracking across days.
        seed_trades = []
        if pos_data:
            today_net_qty = sum(
                _effective_trade_qty(t) if t.get('action') == 'BUY' else -_effective_trade_qty(t)
                for t in trades_list
            )
            overnight_qty = pos_data['quantity'] - today_net_qty
            if abs(overnight_qty) > 1e-6:
                seed_trades = [{
                    'action': 'BUY' if overnight_qty > 0 else 'SELL',
                    'quantity': abs(overnight_qty),
                    'average_price': pos_data['average_price'],
                    'parsed_time': day_start,
                }]

        windows = _build_position_windows(seed_trades + trades_list)
        if not windows:
            continue

        replay_start = day_start if seed_trades else max(day_start, trades_list[0]['parsed_time'])
        df_hist_trimmed = df_hist[(df_hist.index >= replay_start) & (df_hist.index <= current_time)]
        if df_hist_trimmed.empty:
            continue

        # Keyed by symbol_exchange (not just symbol) so the same symbol
        # traded on two exchanges the same day (e.g. RELIANCE on NSE and
        # BSE) gets two distinct columns instead of colliding into one and
        # failing the join below.
        symbol_pnl = _replay_symbol_pnl(df_hist_trimmed, pos_key, windows, current_time)
        portfolio_pnl = symbol_pnl if portfolio_pnl is None else portfolio_pnl.join(symbol_pnl, how='outer')

    if portfolio_pnl is None or portfolio_pnl.empty:
        return None

    portfolio_pnl = portfolio_pnl.sort_index().ffill().fillna(0)
    return portfolio_pnl.sum(axis=1).rename('Total_PnL')


def compute_combined_pnl(accounts):
    """
    Compute each account's intraday P&L series in parallel, then merge them
    into one combined portfolio curve (outer-join on timestamp, forward-fill,
    sum) - the same trick OpenAlgo uses to combine symbols within one
    account, applied here across accounts instead.

    Returns a dict shaped like OpenAlgo's /pnltracker/api/pnl response, plus
    a 'per_account' breakdown for the modal's summary cards and a
    'failed_accounts' list naming any account whose data couldn't be
    fetched at all - those accounts contribute nothing to the combined
    total, so the caller needs to know when the total is understated rather
    than genuinely complete.
    """
    def _one(account):
        try:
            client = ExtendedOpenAlgoAPI(api_key=account.get_api_key(), host=account.host_url)
            return account, compute_account_series(client), None
        except AccountPnlError as e:
            logger.error(f'Account {account.id} P&L unavailable: {e}')
            return account, None, str(e)
        except Exception:
            logger.exception(f'Error computing intraday P&L for account {account.id}')
            return account, None, 'Unexpected error computing P&L'

    if len(accounts) <= 1:
        results = [_one(accounts[0])] if accounts else []
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(accounts))) as executor:
            results = list(executor.map(_one, accounts))

    per_account = []
    failed_accounts = []
    combined = None
    for account, series, error in results:
        current_value = float(series.iloc[-1]) if series is not None and len(series) else 0.0
        per_account.append({
            'account_id': account.id,
            'account_name': account.account_name,
            'current_pnl': round(current_value, 2),
            'series': [],
            'error': error,
        })
        if error:
            failed_accounts.append(account.account_name)
        if series is None or series.empty:
            continue
        frame = series.rename(f'account_{account.id}').to_frame()
        combined = frame if combined is None else combined.join(frame, how='outer')

    empty_result = {
        'current_mtm': 0, 'max_mtm': 0, 'max_mtm_time': None,
        'min_mtm': 0, 'min_mtm_time': None, 'max_drawdown': 0,
        'pnl_series': [], 'drawdown_series': [], 'per_account': per_account,
        'failed_accounts': failed_accounts,
    }
    if combined is None:
        return empty_result

    combined = combined.sort_index().ffill().fillna(0)
    account_cols = list(combined.columns)
    combined['Total_PnL'] = combined[account_cols].sum(axis=1)
    combined['Peak'] = combined['Total_PnL'].cummax()
    combined['Drawdown'] = combined['Total_PnL'] - combined['Peak']
    if combined.empty:
        return empty_result

    def _series_to_points(col):
        points = []
        for idx, val in combined[col].items():
            ts_ms = int(idx.tz_convert('UTC').timestamp() * 1000) if getattr(idx, 'tz', None) is not None else int(idx.timestamp() * 1000)
            points.append({'time': ts_ms, 'value': round(float(val), 2)})
        return points

    pnl_series = _series_to_points('Total_PnL')
    drawdown_series = _series_to_points('Drawdown')

    # Each account's own aligned series (zero-filled before that account's
    # first trade, same timestamps as the combined curve) so the frontend can
    # overlay per-account lines and show a per-account breakdown on hover.
    for entry in per_account:
        col = f"account_{entry['account_id']}"
        entry['series'] = _series_to_points(col) if col in account_cols else []

    return {
        'current_mtm': round(float(combined['Total_PnL'].iloc[-1]), 2),
        'max_mtm': round(float(combined['Total_PnL'].max()), 2),
        'max_mtm_time': combined['Total_PnL'].idxmax().strftime('%H:%M'),
        'min_mtm': round(float(combined['Total_PnL'].min()), 2),
        'min_mtm_time': combined['Total_PnL'].idxmin().strftime('%H:%M'),
        'max_drawdown': round(float(combined['Drawdown'].min()), 2),
        'pnl_series': pnl_series,
        'drawdown_series': drawdown_series,
        'per_account': per_account,
        'failed_accounts': failed_accounts,
    }
