/*
 * Shared timestamp display formatting (fork-only), ported from OpenAlgo's
 * frontend/src/pages/TradeBook.tsx (parseTimestamp/formatTime/
 * formatDateTime) so both apps show a trade/order timestamp the same way.
 * app/__init__.py's `time_only`/`date_time` Jinja filters have the same two
 * functions for server-rendered rows - kept in sync by hand, same as
 * tradebook.html's EXCHANGE_SEGMENT_MAP already is with OpenAlgo's
 * Python-side derive_segment().
 *
 * Every current broker (Zerodha, Kotak) now normalizes its own order/trade
 * timestamps to canonical ISO 8601 before OpenAlgo ever returns them
 * (broker/{zerodha,kotak}/mapping/order_data.py on the OpenAlgo side) - the
 * fallback regexes below exist only in case one of the 3 accounts is
 * running an OpenAlgo build from before that normalization landed, not the
 * common case.
 */

function formatTimeParseTimestamp(timestamp) {
    if (!timestamp) return 0;
    var date = new Date(timestamp);
    if (isNaN(date.getTime())) {
        var norentm = String(timestamp).match(/^(\d{2}:\d{2}:\d{2})\s+(\d{2})-(\d{2})-(\d{4})$/);
        if (norentm) {
            date = new Date(norentm[4] + '-' + norentm[3] + '-' + norentm[2] + 'T' + norentm[1]);
        }
    }
    if (isNaN(date.getTime())) {
        var ddmmyyyy = String(timestamp).match(/^(\d{2})-(\d{2})-(\d{4})\s+(\d{2}:\d{2}:\d{2})$/);
        if (ddmmyyyy) {
            date = new Date(ddmmyyyy[3] + '-' + ddmmyyyy[2] + '-' + ddmmyyyy[1] + 'T' + ddmmyyyy[4]);
        }
    }
    return date.getTime() || 0;
}

// Time-only, for a live (always-today) row - matches OpenAlgo's OrderBook/
// TradeBook formatTime().
function formatTimeOnly(timestamp) {
    if (!timestamp) return '-';
    var timeValue = formatTimeParseTimestamp(timestamp);
    if (timeValue === 0) {
        var m = String(timestamp).match(/(\d{2}:\d{2}:\d{2})/);
        return m ? m[1] : timestamp;
    }
    var date = new Date(timeValue);
    return date.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// Full date+time, for a historical (any-day) row - matches OpenAlgo's
// TradeBook formatDateTime().
function formatDateTime(timestamp) {
    if (!timestamp) return '-';
    var timeValue = formatTimeParseTimestamp(timestamp);
    if (timeValue === 0) return timestamp;
    var date = new Date(timeValue);
    return date.toLocaleString('en-IN', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
}
