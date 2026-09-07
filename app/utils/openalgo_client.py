"""
Extended OpenAlgo API client with additional methods
"""
import httpx
from openalgo import api


class ExtendedOpenAlgoAPI(api):
    """Extended OpenAlgo API client with ping method and optimized timeout"""

    def __init__(self, api_key, host="http://127.0.0.1:5000", version="v1", ws_port=8765, ws_url=None, timeout=30):
        """
        Initialize with a 30 second timeout (default).
        Uses keyword args for super().__init__() because openalgo>=1.0.50
        changed the api.__init__ signature (timeout is now the 4th positional
        arg, displacing ws_port).
        """
        super().__init__(
            api_key=api_key,
            host=host,
            version=version,
            timeout=timeout,
            ws_port=ws_port,
            ws_url=ws_url,
        )

    def _make_request(self, endpoint, payload):
        """Override to guarantee timeout is applied regardless of SDK version"""
        url = self.base_url + endpoint
        try:
            response = httpx.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            return self._handle_response(response)
        except Exception as e:
            return self._request_error(e)

    def _request_error(self, e):
        """Shared error shape for the request-level (not HTTP-response-level)
        failures every _make_request/_get_request/import call can hit -
        factored out once here rather than in each of them, since there are
        now four call sites instead of the original one."""
        if isinstance(e, httpx.TimeoutException):
            return {
                'status': 'error',
                'message': f'Request timed out after {self.timeout}s. The server took too long to respond.',
                'error_type': 'timeout_error'
            }
        if isinstance(e, httpx.ConnectError):
            return {
                'status': 'error',
                'message': 'Failed to connect to the server. Please check if the server is running.',
                'error_type': 'connection_error'
            }
        if isinstance(e, httpx.HTTPError):
            return {
                'status': 'error',
                'message': f'HTTP error occurred: {str(e)}',
                'error_type': 'http_error'
            }
        return {
            'status': 'error',
            'message': f'An unexpected error occurred: {str(e)}',
            'error_type': 'unknown_error'
        }

    def _get_request(self, endpoint, params):
        """GET counterpart to _make_request. The fork-only /pnl/history and
        /pnl/trades endpoints (openalgo's restx_api/pnl_history.py) take
        query params validated via request.args, not a JSON body - apikey
        has to be one of those params here, not sent the way every other
        SDK call sends it.
        """
        url = self.base_url + endpoint
        try:
            response = httpx.get(url, params=params, headers=self.headers, timeout=self.timeout)
            return self._handle_response(response)
        except Exception as e:
            return self._request_error(e)

    def pnl_history(self, start_date, end_date, symbol=None, segment=None, strategy=None):
        """Realized P&L for a date range - fork-only endpoint, see
        openalgo's restx_api/pnl_history.py. AlgoMirror's combined P&L
        History page calls this once per account and merges the results
        (app/utils/pnl_history_combined.py).
        """
        params = {"apikey": self.api_key, "start_date": start_date, "end_date": end_date}
        if symbol:
            params["symbol"] = symbol
        if segment:
            params["segment"] = segment
        if strategy:
            params["strategy"] = strategy
        return self._get_request("pnl/history", params)

    def pnl_trades(self, start_date, end_date, symbol=None, segment=None, strategy=None):
        """Raw fills for a date range, no FIFO matching - fork-only
        endpoint. Backs Trade Book's historical mode once the date range
        moves off today (mirrors OpenAlgo's own isHistorical switch).
        """
        params = {"apikey": self.api_key, "start_date": start_date, "end_date": end_date}
        if symbol:
            params["symbol"] = symbol
        if segment:
            params["segment"] = segment
        if strategy:
            params["strategy"] = strategy
        return self._get_request("pnl/trades", params)

    def strategy_legs(self, strategy=None):
        """Every currently-tracked strategy leg for this account - a thin
        read over openalgo's already-running strategy book
        (database/strategy_book_db.py), exposed via the fork-only
        GET /api/v1/pnl/strategy-legs. "Holdings, per strategy" - not
        date-ranged like pnl_history/pnl_trades, since this tracks current
        open legs, not historical trades.
        """
        params = {"apikey": self.api_key}
        if strategy:
            params["strategy"] = strategy
        return self._get_request("pnl/strategy-legs", params)

    def set_trade_strategy(self, trade_id, strategy):
        """Manual strategy-tag fallback for one historical trade row -
        fork-only PATCH /api/v1/pnl/trades/<id>/strategy. For CSV-imported
        history and any trade with no orderid to automatically join
        against the strategy book.
        """
        url = self.base_url + f"pnl/trades/{trade_id}/strategy"
        try:
            response = httpx.patch(
                url,
                json={"apikey": self.api_key, "strategy": strategy},
                headers=self.headers,
                timeout=self.timeout,
            )
            return self._handle_response(response)
        except Exception as e:
            return self._request_error(e)

    def import_pnl_csv(self, file_bytes, filename):
        """Backfill one account's ledger from an exported tradebook CSV -
        fork-only endpoint. multipart/form-data with apikey as a form
        field (restx_api/pnl_history_schema.py's PnlImportSchema), not a
        query param or JSON body - a different shape again from both
        _make_request and _get_request above.
        """
        url = self.base_url + "pnl/import"
        try:
            response = httpx.post(
                url,
                data={"apikey": self.api_key},
                files={"file": (filename, file_bytes, "text/csv")},
                timeout=self.timeout,
            )
            return self._handle_response(response)
        except Exception as e:
            return self._request_error(e)

    def ping(self):
        """
        Test connectivity and validate API key authentication
        
        This endpoint checks connectivity and validates the API key 
        authentication with the OpenAlgo platform.
        
        Returns:
            dict: Response with status, broker info, and message
            
        Example Response:
            {
                "data": {
                    "broker": "upstox",
                    "message": "pong"
                },
                "status": "success"
            }
        """
        payload = {"apikey": self.api_key}
        return self._make_request("ping", payload)