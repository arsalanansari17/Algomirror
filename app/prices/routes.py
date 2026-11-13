"""The shared price store as an OpenAlgo-compatible history endpoint.

POST /prices/api/v1/history takes the same body OpenAlgo's /api/v1/history takes
(apikey, symbol, exchange, interval "D", start_date, end_date) and answers with
the same shape, close only, so an OpenAlgo instance reads it through its
existing PNL_HISTORY_FALLBACK_URL setting with no code of its own.

It reads the store and never calls a broker. A request the store cannot fully
serve is recorded as a wish for the filler to fetch after the market closes.
The key is PRICE_STORE_API_KEY from the environment; without it the endpoint is
off. Prices are public, but the endpoint sits behind a public name.
"""
import hmac
import os
from datetime import date

from flask import current_app, jsonify, request

from app.prices import prices_bp
from app.utils import price_store


def _error(message: str, status: int):
    return jsonify({"status": "error", "message": message}), status


def _parse_day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


@prices_bp.route("/api/v1/history", methods=["POST"])
def history():
    expected = os.environ.get("PRICE_STORE_API_KEY", "")
    if not expected:
        return _error("The price store is not enabled.", 503)

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("Send a JSON body.", 400)

    provided = str(body.get("apikey") or "")
    if not hmac.compare_digest(provided.encode(), expected.encode()):
        return _error("Invalid key.", 401)

    symbol = str(body.get("symbol") or "").strip().upper()
    exchange = str(body.get("exchange") or "").strip().upper()
    start = _parse_day(body.get("start_date"))
    end = _parse_day(body.get("end_date"))
    if not symbol or not exchange or start is None or end is None or end < start:
        return _error("symbol, exchange, start_date and end_date are required.", 400)
    if str(body.get("interval") or "D").upper() != "D":
        return _error("Only daily bars are stored.", 400)

    try:
        bars = price_store.get_bars(symbol, exchange, start, end)
        price_store.record_ask(symbol, exchange, start, end)
    except Exception:
        current_app.logger.exception("Price store read failed")
        return _error("The price store could not be read.", 500)

    if not bars:
        return _error("No stored prices for this instrument yet.", 404)
    return jsonify({"status": "success", "data": bars})
