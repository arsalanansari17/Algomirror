# AlgoMirror — Known Issues

Tracker for issues found during code review but deliberately deferred rather
than fixed immediately. Revisit here before the next dashboard/funds-related
change, or whenever one of these actually bites.

| # | Severity | Area | Status |
|---|---|---|---|
| 1 | 🟠 Medium | Dashboard — `/api/accounts/<id>/funds` | Open |
| 2 | 🟡 Low (cosmetic) | Trade Book — timestamp display | Fix filed upstream, pending live verification |
| 3 | 🟡 Low (feature gap) | Order Book / Trade Book — missing OpenAlgo features | Open |
| 4 | 🟡 Low (feature gap) | Holdings — architectural gaps vs OpenAlgo (needs live infra) | Open |
| 5 | 🟡 Low (feature gap) | Positions — Account column removed, needs a new home (Holdings resolved) | Open |
| 6 | 🟡 Low (feature gap) | Holdings — "Exit from all accounts" deferred | Open |

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

**Root cause found and fixed upstream 2026-09-06** - not a Zerodha backend
quirk after all. Kite's own docs (kite.trade/docs/connect/v3/orders/)
document `order_timestamp` as an order-level field ("when the order was
registered by the API"), identical across every fill under one multi-fill
order - not the per-trade fill time. `fill_timestamp` ("when the trade was
filled at the exchange") is the field actually correct for a trade record,
and OpenAlgo's own `blueprints/pnltracker.py` already independently falls
back to it when `timestamp` looks wrong, corroborating this was already
suspected. Filed as [openalgo#2006](https://github.com/marketcalls/openalgo/issues/2006)
/ [PR #2007](https://github.com/marketcalls/openalgo/pull/2007), applied
to our fork's `upgrade-main-2026-09` branch - **not yet deployed or
live-verified** (filed over a weekend with all 3 VMs off; next step is
confirming on a real account, iram's in particular, once a VM is back up).
See `openalgo/SKYSHIELD_PATCHES.md`'s 2026-09-06 entry for the full
writeup. The display-side workaround below is superseded by this - no
longer needed once the upstream fix is live.

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

**Superseded display-side workaround (not needed once the upstream fix
lands):** normalization in `tradebook.html` (or wherever `trade.timestamp`
is assembled) — if the value doesn't match a full-date pattern, prepend the
trade's own date before rendering. Left here only in case the upstream fix
is delayed and a stopgap is needed sooner.

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

### 4. Holdings — four gaps left open after the 2026-09-01 element-by-element pass, all needing infra AlgoMirror doesn't have yet
**Where:** `app/templates/trading/holdings.html`

Found during the same page-by-page comparison pass as #3, in a much more
thorough element-by-element re-check of Holdings specifically (two earlier
passes on this same page had already missed real things - see
`project_algomirror_ui_redesign_plan.md` for the full account of what those
passes fixed). These four remain open, distinct from the earlier fixes,
because each depends on infrastructure AlgoMirror doesn't have, not just a
missed class name:

- **No Live/Paused status badge next to the page title.** OpenAlgo's
  `Holdings.tsx` shows a pulsing "Live" or "Paused" badge reflecting its
  WebSocket connection state (`useLivePrice` hook). AlgoMirror has no
  WebSocket price feed on this page at all - it's a one-shot server render
  plus a page reload for refresh, so there's no live/paused state to
  represent honestly. Building this for real means giving Holdings a live
  price feed, not just adding a badge.
- **No stale-data warning banner.** Same root cause - OpenAlgo's banner
  fires from `usePageVisibility` + a live-fetch staleness check; AlgoMirror
  has no notion of "the tab was hidden and data might be stale" without a
  live feed to become stale in the first place.
- **Order dialog has no live quote header, market depth panel, or
  price/trigger +/- step buttons.** OpenAlgo's `PlaceOrderDialog` fetches
  live LTP/bid/ask/depth via `useLiveQuote` while the dialog is open.
  AlgoMirror's `orderModal` is a plain form with no live data source wired
  up - would need a new quote-fetching endpoint plus polling JS to add
  this properly, not just markup.
- **Filters dialog description/label text uses `text-base-content/60`
  where the rest of the page uses `text-muted-foreground`.** Unlike the
  three items above, this one has no architectural blocker - it's a
  trivial token swap. Left open only because both tokens render as
  near-identical grays in practice; genuinely low priority, listed here
  so it doesn't get lost rather than because it's hard.

**Proposed fix (not yet implemented, not yet scoped):** the first three
need a live-quote/WebSocket layer for Holdings before any of this is
worth building - that's a real feature project, not a quick fix, and
should get its own scoping pass before starting. The fourth is a one-line
fix whenever someone's already touching this file for something else.

### 5. Positions — Account column removed (2026-09-01), needs a new home
**Where:** `app/templates/trading/positions.html`

**Holdings resolved 2026-09-02** - see the "Holding Detail Dialog" note in
`holdings.html` (the `info-btn` in the Actions cell, next to Add/Exit,
opens `holdingDetailModal` showing Account/Broker plus a fuller breakdown
of the row, like Zerodha's own app). Not offered on merged rows, same
reasoning as the tag section below. Positions doesn't have an equivalent
popup yet, so its Account column is still gone with nothing replacing it.

Neither of OpenAlgo's own Holdings/Positions tables has an Account column
at all (they're single-account pages by design), and this column was an
AlgoMirror-only addition to identify which account a row belongs to when
viewing "All Accounts" or several selected accounts. Removed from both
pages at the user's request to get closer to OpenAlgo's real table shape
(Holdings first, Positions the same day once the Value column - also
AlgoMirror-only, also absent from OpenAlgo - was removed alongside it).

The account/broker data is still available on Positions for this: each
`<tr>` carries `data-account-name`/`data-account-id`, and the account/broker
fields are still passed through in `positions_data` server-side (nothing
was removed from the Python side, only the rendered column and its
dead-code cleanup in `renderMergedView()` - the collected `accountNames`
array is kept but no longer rendered anywhere).

**Proposed fix:** port the same Holding-Detail-Dialog pattern onto
Positions (a `positionDetailModal` + `info-btn`) when that page gets its
own tagging/detail pass - reuses the exact same approach, no new design
needed.

### 6. Holdings — "Exit from all accounts" deferred (2026-09-01)
**Where:** `app/templates/trading/holdings.html`, `app/trading/routes.py`

Discussed alongside the merged-row Add/Exit + account-picker feature
(landed 2026-09-01): a merged position's Exit flow currently requires
picking one account at a time from the Account dropdown, each with its
own quantity and its own order submission. "Exit from all accounts" would
place a full-exit sell order across every account in the merge group in
one action - deliberately scoped out of that work at the user's request
("let's skip exit from all, that can be taken later").

**Why it's a separate piece of work, not a quick add-on:**
- Needs a new **backend route** (not a client-side loop calling the
  existing single-account `/holdings/order` N times) - matching the
  pattern the Dashboard's "Close All Orphans" already uses: one request,
  server-side loop over accounts, one aggregated response, so the
  frontend gets a clean "2 of 2 exited" / "1 of 2 exited - iram failed:
  <reason>" result instead of juggling N separate fetches and partial UI
  states itself.
- Needs a **partial-failure policy** - if one account's order succeeds and
  another's fails (broker error, insufficient holdings, whatever), should
  it attempt both and report both (matching "Close All Orphans"'s own
  behavior), or something else? Not decided.
- Needs its own **confirmation step** before firing multiple real sell
  orders in one click across accounts - likely a modal similar to the
  Dashboard's "Close All Positions" confirmation, not decided in detail.
- The Quantity field doesn't make sense as a single editable number once
  "all accounts" is selected (each account holds a different amount) -
  would need to become a read-only summary of what's about to be sold
  per account instead.

**Proposed fix:** none chosen yet - scope this properly (new route,
failure policy, confirmation UX) before starting, rather than bolting it
onto the existing single-account order modal.

### 7. Analytics ideas discussed 2026-09-06 - not scoped, not started
**Where:** P&L History (`app/templates/trading/pnl_history.html`,
`app/utils/pnl_history_combined.py`), Positions, Holdings

Brainstormed the day after the consolidated P&L History + Tradebook
history feature landed (item 9e4e5ac). None of these are scoped or
started - listed here so the ideas aren't lost, not as a commitment to
build any of them. Ranked roughly by how directly they build on
infrastructure that already exists.

**P&L report:**
- **Strategy-wise P&L** - tag closed trades by strategy (DonchianSwing,
  IronCondor, IntradayIronFly, ...), not just symbol/segment. The
  strategy-tagging concept already exists for Holdings
  (`PositionTag` in `app/models.py`) - this would need the same idea
  applied to trades/closed-trade rows instead of holdings rows. Answers
  "which strategy is actually making money after costs," which nothing
  built so far can answer.
- **Win rate / expectancy per strategy or symbol** - win%, avg win, avg
  loss, profit factor, computed from `closed_trades` (already
  FIFO-matched, no new data needed).
- **Charges/cost drag** - gross vs net P&L and cost as a % of gross, per
  strategy. OpenAlgo's tradebook already carries per-trade charge data;
  not yet surfaced anywhere in this feature.
- **Equity curve + drawdown from realized P&L** - cumulative P&L line +
  max drawdown/recovery time, per account and combined. Distinct from the
  existing intraday-only `pnl_curve.py`/P&L Plot page (mark-to-market,
  today only) - this would be multi-day, realized-only, built from the
  same `daily` data the heat map already uses.

**Positions:**
- **Combined Greeks exposure** across accounts for the options books
  (IronCondor/IntradayIronFly) - net delta/theta/vega, to catch
  unintended directional exposure that looks fine per-account but isn't
  in aggregate.
- **Margin utilization over time** - capital is sized dynamically (85% of
  cash+holdings, see SkyShieldAT's dynamic-capital change) and Kotak's
  SPAN margin is a hardcoded estimate (`feat/kotak-span-margin`); a
  historical utilization view would catch capital inefficiency or a
  near-breach before it's a live problem instead of after.

**Holdings:**
- **Pledge coverage tracking over time** - related to the existing
  "exit position if removed from pledge CSV" TODO in SkyShieldAT and the
  manual pledge-CSV-sync pain point already logged there; a view showing
  pledge utilization/coverage drifting over time turns that from
  "noticed manually" into "visible before it's a problem."

**Proposed fix:** none - this is an idea list, not a plan. Pick one,
scope it properly (most of these need new tagging/capture, not just a
new report view), before starting.

### 8. Strategy attribution - CORRECTED 2026-09-07, then built the same day
**Where:** OpenAlgo `database/strategy_book_db.py`, `services/pnl_capture_service.py`,
`services/pnl_history_service.py`, `restx_api/pnl_history.py`,
`database/pnl_db.py`; AlgoMirror `app/utils/openalgo_client.py`,
`app/utils/pnl_history_combined.py`, `app/trading/routes.py`,
`app/templates/trading/pnl_history.html`, `app/templates/trading/tradebook.html`

**This entry originally claimed** (2026-09-07, same day) that
SkyShieldAT's `strategy` field - required on every `placeorder` call - is
submitted then genuinely discarded, never persisted anywhere. **That was
wrong**, caught and corrected the same day before any code was written
against the false premise. What was actually missed: OpenAlgo already has
a real, already-running upstream feature called the strategy book
(`database/strategy_book_db.py` + `subscribers/strategy_book_subscriber.py`,
built for Flow's per-strategy risk management) whose own docstring says
*"orders placed through `/api/v1` are tracked exactly like Flow-placed
ones as long as they carry a `strategy`"* - a **generic** event-bus
subscription (`order.placed`/`order.update`, plus the batch-completion
topics), not a Flow-only hook. Verified directly against a real account's
`openalgo.db`: 54 real `strategy_positions` rows, real strategy names
(`DonchianSwing`, `IntradayIronFly`, `IronCondor`), persisting across days
(only `today_realized_pnl` resets daily). So the capture problem was
already solved; the actual gap was narrower - nothing exposed it via a
REST endpoint or UI, and `PnlTrade` (the P&L History ledger) had no
`strategy` column to filter/group by.

**Built the same day** (not just proposed - both layers from the original
correction, plus the AlgoMirror side, landed together per explicit user
direction "everything at once"):

- **`PnlTrade.strategy` column** (`database/pnl_db.py`, same migration
  pattern as `segment`) - backfilled by the daily capture job and the CSV
  import path, joining each fill's `orderid` against
  `strategy_book_db.get_order_tag()` (already existed, previously only
  called internally). `strategy` also became a third pre-filter alongside
  segment/symbol (`_parse_range_and_build_query`) - applied to `PnlTrade`
  rows *before* FIFO matching runs, not threaded through
  `utils/pnl_fifo.py`'s lot objects, so a strategy-filtered response is
  single-strategy by construction with zero changes to the FIFO matcher
  itself.
- **`GET /api/v1/pnl/strategy-legs`** (new, `restx_api/pnl_history.py`) -
  a thin read wrapper over `strategy_book_db.get_strategy_legs()`. This
  is "holdings, per strategy" already computed server-side (quantity,
  average price, cumulative realized P&L per leg) - not derived from
  `pnl_trades`/FIFO at all.
- **`PATCH /api/v1/pnl/trades/<id>/strategy`** (new) - the manual fallback
  for CSV-imported history and anything placed outside OpenAlgo entirely
  (no `orderid` to join against). Both OpenAlgo's Trade Book (per-row
  inline editor) and AlgoMirror's combined Trade Book proxy to this.
- **AlgoMirror**: `ExtendedOpenAlgoAPI.strategy_legs()`/`set_trade_strategy()`,
  `compute_combined_strategy_legs()` (merges legs by
  strategy+symbol+exchange+product across accounts, weighted-average cost
  - same merge shape as the existing Scrip-wise merge, keyed by strategy
  too), a new "Strategy Positions" section on the P&L History page, and a
  Strategy filter + manual-tag column on Trade Book.
- Verified: a real unit test (`tests/test_pnl_history_combined.py`)
  confirms two synthetic accounts' `DonchianSwing`/`INFY` legs merge into
  one row with correctly weighted-averaged cost - the exact case originally
  discussed (a position split across accounts).

**Known real data-quality gotcha, found while verifying against a real
account**: `strategy_positions` already has a `'Holdings'` strategy value
(from OpenAlgo's own Holdings page hardcoding `strategy="Holdings"` on any
manual Add/Exit click - `frontend/src/pages/Holdings.tsx:1011`) and a
live-diverging `DonchianSwing`/`CREDITACC` quantity (a manual top-up
placed outside OpenAlgo's own order flow, so the strategy book has no
record of it). Neither is a bug - both are exactly the class of gap the
"holdings-from-tradebook, reconciliation not replacement" framing below
was designed for.

**Holdings-from-tradebook, still not built**: the P&L ledger's FIFO
matcher already computes `open_positions` (symbol/qty/avg price) as a
byproduct - a from-scratch Holdings view derived purely from trade history
is already half-built, just not surfaced. Still deliberately not done:
don't replace the broker's Holdings API with it outright, since a position
changed via a route OpenAlgo never saw (broker corporate action, or an
order placed directly in the broker's own app) would silently drift if the
ledger were trusted as sole source of truth. The right framing, per the
same 2026-09-07 discussion: show both, flag a mismatch as a reconciliation
check instead of picking one - now that `PnlTrade.strategy` and
`strategy-legs` both exist, that reconciled view would get strategy
attribution for free too. Not scoped or started.
