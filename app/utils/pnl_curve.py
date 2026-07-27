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
    """Reconstruct BUY/SELL open/close windows for one symbol's trades, in trade order."""
    net_position = 0
    windows = []

    for trade in trades_list:
        try:
            executed_price = float(trade.get('average_price', 0))
            action = trade.get('action', '')
            trade_time = trade.get('parsed_time')
            qty = float(trade.get('quantity', 0))
            if qty == 0 and executed_price > 0:
                trade_value = float(trade.get('trade_value', 0))
                qty = 1 if trade_value == executed_price else (trade_value / executed_price if trade_value > 0 else 0)
            if qty <= 0:
                continue
        except (TypeError, ValueError):
            continue

        if action == 'BUY':
            windows.append({'start_time': trade_time, 'end_time': None, 'qty': qty,
                             'price': executed_price, 'action': 'BUY', 'exit_price': None})
            net_position += qty
        else:
            if net_position > 0:
                remaining = qty
                for window in windows:
                    if window['action'] == 'BUY' and window['end_time'] is None and remaining > 0:
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
                net_position -= qty
            else:
                windows.append({'start_time': trade_time, 'end_time': None, 'qty': qty,
                                 'price': executed_price, 'action': 'SELL', 'exit_price': None})
                net_position -= qty

    return windows


def _replay_symbol_pnl(df_hist, symbol, windows, current_time):
    """Mark each position window to the historical close price; freeze at realized P&L once closed."""
    df_hist = df_hist[['close']].copy()
    df_hist.rename(columns={'close': f'{symbol}_price'}, inplace=True)
    col = f'{symbol}_pnl'
    df_hist[col] = 0.0

    cumulative_realized = 0.0
    for window in sorted(windows, key=lambda w: w['start_time'] or datetime.min.replace(tzinfo=pytz.UTC)):
        if window['start_time'] is None:
            continue
        start = window['start_time']
        end = window['end_time'] if window['end_time'] else current_time
        mask = (df_hist.index >= start) & (df_hist.index <= end)
        has_data = mask.any()
        is_closed = window['end_time'] is not None and window.get('exit_price') is not None

        if not has_data and not is_closed:
            continue

        if has_data:
            price_col = df_hist.loc[mask, f'{symbol}_price']
            if window['action'] == 'BUY':
                df_hist.loc[mask, col] += (price_col - window['price']) * window['qty']
            else:
                df_hist.loc[mask, col] += (window['price'] - price_col) * window['qty']

        if is_closed:
            if window['action'] == 'BUY':
                realized = (window['exit_price'] - window['price']) * window['qty']
            else:
                realized = (window['price'] - window['exit_price']) * window['qty']
            cumulative_realized += realized

        if window['end_time'] is not None:
            future_mask = df_hist.index > window['end_time']
            if future_mask.any():
                df_hist.loc[future_mask, col] = cumulative_realized
            elif cumulative_realized != 0 and len(df_hist) > 0:
                df_hist.loc[df_hist.index[-1], col] = cumulative_realized

    return df_hist[[col]]


def compute_account_series(client, today=None):
    """
    Reconstruct today's minute-by-minute mark-to-market P&L for one account
    from its tradebook + open positions.

    Returns a pandas Series (IST datetime index -> cumulative Total P&L),
    or None if the account has neither trades nor open positions today.
    """
    rate_limiter = _RateLimiter()
    current_time = datetime.now(IST)
    today_date = today or current_time.date()
    today_str = today_date.strftime('%Y-%m-%d')

    try:
        trades_resp = client.tradebook()
    except Exception:
        logger.exception('Error fetching tradebook')
        trades_resp = None
    trades = trades_resp.get('data', []) if isinstance(trades_resp, dict) and trades_resp.get('status') == 'success' else []

    current_positions = {}
    try:
        pos_resp = client.positionbook()
        if isinstance(pos_resp, dict) and pos_resp.get('status') == 'success':
            for pos in pos_resp.get('data', []):
                key = f"{pos['symbol']}_{pos['exchange']}"
                try:
                    current_positions[key] = {
                        'quantity': float(pos.get('quantity', 0)),
                        'average_price': float(pos.get('average_price', 0)),
                        'pnl': float(pos.get('pnl', 0) or 0),
                    }
                except (ValueError, TypeError):
                    continue
    except Exception:
        logger.exception('Error fetching positionbook')

    if not trades and not current_positions:
        return None

    # Determine the trading date from the first trade (handles overnight-carried trades).
    first_trade_time = None
    for trade in trades:
        ts = trade.get('timestamp') or trade.get('fill_timestamp') or trade.get('fill_time')
        parsed = _parse_trade_timestamp(ts) if ts else None
        if parsed and (first_trade_time is None or parsed < first_trade_time):
            first_trade_time = parsed
    if first_trade_time is None:
        first_trade_time = current_time.replace(hour=9, minute=15, second=0, microsecond=0)
    else:
        today_date = first_trade_time.date()
        today_str = today_date.strftime('%Y-%m-%d')

    symbol_trades = {}
    for trade in trades:
        symbol, exchange = trade.get('symbol', ''), trade.get('exchange', '')
        if not symbol or not exchange:
            continue
        ts = trade.get('timestamp') or trade.get('fill_timestamp') or trade.get('fill_time')
        trade = dict(trade)
        trade['parsed_time'] = _parse_trade_timestamp(ts) if ts else None
        symbol_trades.setdefault(f'{symbol}_{exchange}', []).append(trade)

    portfolio_pnl = None

    for trades_list in symbol_trades.values():
        trades_list = sorted(trades_list, key=lambda t: t.get('parsed_time') or datetime.min.replace(tzinfo=pytz.UTC))
        symbol, exchange = trades_list[0].get('symbol', ''), trades_list[0].get('exchange', '')
        if not symbol or not exchange:
            continue

        windows = _build_position_windows(trades_list)
        df_hist = _history_df(client, symbol, exchange, today_str, rate_limiter)
        if df_hist is None:
            continue
        df_hist = df_hist[(df_hist.index >= first_trade_time) & (df_hist.index <= current_time)]
        if df_hist.empty:
            continue

        symbol_pnl = _replay_symbol_pnl(df_hist, symbol, windows, current_time)
        portfolio_pnl = symbol_pnl if portfolio_pnl is None else portfolio_pnl.join(symbol_pnl, how='outer')

    # Carry-forward positions: open from a prior day (no trade today) or closed today via exit-only trades.
    for pos_key, pos_data in current_positions.items():
        parts = pos_key.rsplit('_', 1)
        if len(parts) != 2:
            continue
        symbol, exchange = parts
        pnl_col = f'{symbol}_pnl'
        qty, avg_price, position_pnl_value = pos_data['quantity'], pos_data['average_price'], pos_data['pnl']

        if qty != 0 and pos_key not in symbol_trades:
            df_hist = _history_df(client, symbol, exchange, today_str, rate_limiter)
            if df_hist is None or df_hist.empty:
                continue
            market_open = df_hist.index[0].replace(hour=9, minute=15, second=0, microsecond=0)
            df_hist = df_hist[(df_hist.index >= market_open) & (df_hist.index <= current_time)]
            if df_hist.empty:
                continue
            price = df_hist['close']
            pnl = (price - avg_price) * qty if qty > 0 else (avg_price - price) * abs(qty)
            frame = pnl.rename(pnl_col).to_frame()
            portfolio_pnl = frame if portfolio_pnl is None else portfolio_pnl.join(frame, how='outer')

        elif qty == 0 and position_pnl_value != 0 and pos_key in symbol_trades:
            trades_for_symbol = symbol_trades[pos_key]
            actions = [t.get('action') for t in trades_for_symbol]
            if 'BUY' in actions and 'SELL' in actions:
                continue  # same-day round-trip, already handled above
            if all(a == 'SELL' for a in actions):
                was_long = True
            elif all(a == 'BUY' for a in actions):
                was_long = False
            else:
                continue

            total_exit_qty = sum(float(t.get('quantity', 0)) for t in trades_for_symbol)
            if total_exit_qty == 0:
                continue
            total_value = sum(float(t.get('average_price', 0)) * float(t.get('quantity', 0)) for t in trades_for_symbol)
            exit_price = total_value / total_exit_qty
            entry_price = (exit_price - position_pnl_value / total_exit_qty if was_long
                           else exit_price + position_pnl_value / total_exit_qty)
            close_time = trades_for_symbol[-1].get('parsed_time')

            df_hist = _history_df(client, symbol, exchange, today_str, rate_limiter)
            if df_hist is None or df_hist.empty:
                continue
            market_open = df_hist.index[0].replace(hour=9, minute=15, second=0, microsecond=0)
            df_hist = df_hist[(df_hist.index >= market_open) & (df_hist.index <= current_time)][['close']].copy()
            if df_hist.empty:
                continue
            df_hist[pnl_col] = 0.0
            before_close = df_hist.index <= close_time if close_time else pd.Series(True, index=df_hist.index)
            after_close = df_hist.index > close_time if close_time else pd.Series(False, index=df_hist.index)
            if was_long:
                df_hist.loc[before_close, pnl_col] = (df_hist.loc[before_close, 'close'] - entry_price) * total_exit_qty
            else:
                df_hist.loc[before_close, pnl_col] = (entry_price - df_hist.loc[before_close, 'close']) * total_exit_qty
            if after_close.any():
                df_hist.loc[after_close, pnl_col] = position_pnl_value

            if portfolio_pnl is not None and pnl_col in portfolio_pnl.columns:
                portfolio_pnl.drop(columns=[pnl_col], inplace=True)
                if len(portfolio_pnl.columns) == 0:
                    portfolio_pnl = None
            frame = df_hist[[pnl_col]]
            portfolio_pnl = frame if portfolio_pnl is None else portfolio_pnl.join(frame, how='outer')

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
    a 'per_account' breakdown for the modal's summary cards.
    """
    def _one(account):
        try:
            client = ExtendedOpenAlgoAPI(api_key=account.get_api_key(), host=account.host_url)
            return account, compute_account_series(client)
        except Exception:
            logger.exception(f'Error computing intraday P&L for account {account.id}')
            return account, None

    if len(accounts) <= 1:
        results = [_one(accounts[0])] if accounts else []
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(accounts))) as executor:
            results = list(executor.map(_one, accounts))

    per_account = []
    combined = None
    for account, series in results:
        current_value = float(series.iloc[-1]) if series is not None and len(series) else 0.0
        per_account.append({
            'account_id': account.id,
            'account_name': account.account_name,
            'current_pnl': round(current_value, 2),
        })
        if series is None or series.empty:
            continue
        frame = series.rename(f'account_{account.id}').to_frame()
        combined = frame if combined is None else combined.join(frame, how='outer')

    empty_result = {
        'current_mtm': 0, 'max_mtm': 0, 'max_mtm_time': None,
        'min_mtm': 0, 'min_mtm_time': None, 'max_drawdown': 0,
        'pnl_series': [], 'drawdown_series': [], 'per_account': per_account,
    }
    if combined is None:
        return empty_result

    combined = combined.sort_index().ffill().fillna(0)
    combined['Total_PnL'] = combined.sum(axis=1)
    combined['Peak'] = combined['Total_PnL'].cummax()
    combined['Drawdown'] = combined['Total_PnL'] - combined['Peak']
    if combined.empty:
        return empty_result

    pnl_series, drawdown_series = [], []
    for idx, row in combined.iterrows():
        ts_ms = int(idx.tz_convert('UTC').timestamp() * 1000) if getattr(idx, 'tz', None) is not None else int(idx.timestamp() * 1000)
        pnl_series.append({'time': ts_ms, 'value': round(float(row['Total_PnL']), 2)})
        drawdown_series.append({'time': ts_ms, 'value': round(float(row['Drawdown']), 2)})

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
    }
