# AlgoMirror — Known Issues

Tracker for issues found during code review but deliberately deferred rather
than fixed immediately. Revisit here before the next dashboard/funds-related
change, or whenever one of these actually bites.

| # | Severity | Area | Status |
|---|---|---|---|
| 1 | 🟠 Medium | Dashboard — `/api/accounts/<id>/funds` | Open |
| 2 | 🟡 Low (cosmetic) | Trade Book — timestamp display | Open |
| 3 | 🟡 Low (feature gap) | Order Book / Trade Book — missing OpenAlgo features | Open |

---

### 1. Unbounded stale-cache fallback on funds() failure, no staleness indicator in the UI
**Where:** `app/api/routes.py:90-234` (`get_account_funds`), consumed by `loadAccountFunds()` in `app/templates/main/dashboard.html`

The funds endpoint has two cache paths. The normal path (line ~143-165) only
serves cached data if it's `<30s` old — fine. But when the live
`get_client().funds()` call to the broker fails, the fallback path
(line ~205-224) serves `account.last_funds_data` from the DB with **no
staleness limit at all** — it could be minutes or hours old — and still
returns `"status": "success"` with just a `cached: true` flag. The dashboard
JS (`loadAccountFunds()`) treats that identically to genuinely fresh data, so
an account's "Today's P&L" / Available Margin cards can silently freeze with
no visual cue that anything is stale.

**Found:** 2026-08-18, investigating a live report that the Iqbal (acc3,
Kotak, Analyzer mode) account's dashboard P&L wasn't updating while the
Positions page (a different, live-computed code path) showed the correct
current P&L, and a manual refresh fixed it. The specific incident that day
was traced to Claude's own VM stop/start actions during that session (all
three accounts' `/api/accounts/*/funds` polling shows identical multi-minute
gaps in `access.log` lining up with the VM downtime) — **not** confirmed as
caused by this bug. But the bug itself is real and independently verified by
reading the code, and `algomirror.log`'s "Slow ping response" entries show
Iqbal's Kotak connection is measurably slower/more failure-prone (repeated
15-30s+ pings) than the two Zerodha accounts, making it the account most
likely to actually trigger this fallback path in practice.

**Proposed fix (not yet implemented):** cap the failure-fallback to recent
data only (e.g. don't serve `last_funds_data` if it's older than ~2-3 min —
show an explicit error/stale state past that instead of silently substituting
old numbers), and surface staleness in the UI (e.g. grey out or tag the
card) rather than rendering a `cached: true` response identically to a fresh
one.

### 2. Trade Book timestamps missing the date for some accounts (Zerodha `order_timestamp` inconsistency)
**Where:** `app/templates/trading/tradebook.html:102` (`{{ trade.timestamp ... }}`), sourced from OpenAlgo `broker/zerodha/mapping/order_data.py:151` (`transform_tradebook_data`)

On 2026-08-18, iram's (acc2, Zerodha) rows on the Trade Book page showed
time-only values (`09:30:02`) while arsalan's (acc1, also Zerodha) and
iqbal's (acc3, Kotak/Analyzer) rows on the same page showed full
`YYYY-MM-DD HH:MM:SS` timestamps for the same trading day.

Traced both layers of code we control and both are a pure passthrough with
zero timestamp formatting:
- AlgoMirror's template renders `trade.timestamp` verbatim, no parsing/
  reformatting.
- OpenAlgo's `transform_tradebook_data()` for Zerodha does
  `"timestamp": trade.get("order_timestamp", "")` — straight passthrough of
  whatever Kite's own `/trades` REST response contains, no SDK-level
  datetime parsing involved (OpenAlgo calls Zerodha's REST API directly,
  not the pykiteconnect SDK, for this endpoint).

Since the identical code path handles both arsalan's and iram's accounts
(same OpenAlgo version, same broker plugin) yet produced different formats,
the inconsistency has to originate from Zerodha's own backend — Kite Connect's
`/trades` endpoint appears to sometimes return `order_timestamp` as a bare
`HH:MM:SS` string instead of the full datetime, for reasons not established
here. Not confirmed against the raw Kite response (couldn't locate the bot's
API key on the acc2 VM to query it directly) — this is the leading
explanation given what's verifiable in our own code, not a certainty.

**Impact:** cosmetic only — qty/price/P&L/order ID are unaffected, only the
displayed date prefix is missing for the affected rows.

**Proposed fix (not yet implemented):** display-side normalization in
`tradebook.html` (or wherever `trade.timestamp` is assembled) — if the value
doesn't match a full-date pattern, prepend the trade's own date (available
elsewhere in the same response, or today's date since Kite's `/trades` only
ever returns the current session's trades) before rendering.

### 3. Order Book / Trade Book missing several real OpenAlgo features (deferred scope, not a defect)
**Where:** `app/templates/trading/orderbook.html`, `app/templates/trading/tradebook.html`

Found during the 2026-08-31/09-01 page-by-page OpenAlgo-vs-AlgoMirror
comparison pass (same session that fixed Holdings' Add/Exit + the
DaisyUI-opacity badge bug — see `project_algomirror_ui_redesign_plan.md`).
Cosmetic parity (stat card colors/icons, status icon+text, badge styling)
was brought in line with OpenAlgo's real `OrderBook.tsx`/`TradeBook.tsx` in
that pass, but these still don't exist in AlgoMirror at all:

- **Column sorting** (Symbol/Action/Price/Status/Time headers, both pages)
- **Filters dialog** (status filter on Orderbook; action/exchange/product
  filters on Tradebook)
- **Per-order Cancel** button + **Cancel All** confirmation dialog (Orderbook,
  open orders only)
- **Modify order** dialog with live quotes (Orderbook, open orders only)
- **GTT tab** (Orderbook only - OpenAlgo's `GttTab` component)

Cancel/Modify/Cancel-All touch live order execution, not just display, so
they need explicit go-ahead before building (per user direction 2026-09-01:
do cosmetic parity now, scope the feature builds separately). Sort and
filters are read-only UI work and lower-risk to pick up first if/when this
gets prioritized.
