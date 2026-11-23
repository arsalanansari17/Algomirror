# AlgoMirror - TODO

The single place for open AlgoMirror work. Convention: one line per item with the
date it was added and the **next action**; when finished, move it to **Done**
with the date. Known gaps that are not scheduled work live in `KNOWN_ISSUES.md`
(#3 order/trade book gaps, #4 holdings, #5 positions account column, #6 exit-all,
#7 analytics ideas) - link them here, don't copy them.

Runs on the acc1 VM (`/var/python/algomirror/app`, `trade.skyshieldedge.com`).
Working branch `feat/multi-account-filter`, pushed to the `fork` remote.
**Never `git pull` on the VM** (its history is divergent, HEAD `59dba24`): copy the
changed files and restart `algomirror.service`. VM files are LF, the repo is CRLF.

## Open

### Do next
- [ ] **Holdings strategy tags from the strategy book (2026-11-24): written and tested locally (100 tests pass), NOT committed or deployed.** Manual `PositionTag` labels were deleted whenever a symbol left the holdings, so LAURUSLABS lost its RSR tag when it was stopped out on 16 Nov and re-bought on 17 Nov. `app/utils/holding_tags.py` takes tags from OpenAlgo's `/api/v1/pnl/attribution` (kind holdings) per account, keeps the last good map in each account's cached holdings (an account whose VM is off keeps its tags), falls back to manual labels for Unattributed or mismatching rows, maps the manual label `RSR` to `RSRotationPositional`, and a saved filter in the browser is mapped the same way. The attribution call is bounded by a timeout and runs in parallel. Caveat: OpenAlgo's strategy book still holds stale legs on acc3 (see openalgo TODO 2026-11-19), which come out as `mismatch` and fall back to the manual tag. Next action: user's go to commit and deploy (holding_tags.py, routes.py, holdings.html; hash the VM copies against 0b43655 first), then, with the VMs up, call `strategy_attribution('holdings')` on each account read-only and check GABRIEL/CYIENT = EBP and CPPLUS/ATHERENERG/LAURUSLABS/WELSPUNLIV/CUPID = RS rotation, that the endpoint survived the 11-22 sync, and that the acc2 archive answers or fails cleanly.
- [ ] **Holdings priced from one market-level source (2026-11-23): written and tested locally (83 tests pass), NOT committed or deployed.** acc2's archived CYIENT lot (98 sh) carried LTP 1,121.70 while the market was 1,160.50, so Holdings understated it by about 3.8K and Day's P&L by the same. `app/utils/holding_price.py` picks the price per row: live source-account quote in market hours, the shared daily-close store after the close when it holds the latest session, else the quote or the old close or the account's own LTP, marked stale (asterisk on LTP, a note under Day's P&L). Needs the two-commit split (the earlier uncommitted prev_close-from-source hunks in `routes.py` and `config.py`, then this), the VM started for the copy (files: holding_price.py, routes.py, config.py, holdings.html; compare the VM's copies with the working tree first), and a check that every held symbol has a `daily_closes` row for the latest session. Follow-ups: Positions/F&O are not covered (the store holds no option prices); weekday exchange holidays show a false stale mark; about 2.4K between Holdings and P&L Analysis unrealised is still unexplained (probably cost basis). Next action: user's go to commit and deploy.
- [ ] **Upstream merge deferred (2026-11-04, user: do it later, carefully).** `origin/master` is 29 commits ahead (merge-base `fda812bf`), almost all a new Equity trading module (~40k lines: live order placement, auto stop-loss/target exit monitor, per-account order stream, migrations 016/017, service lock). Trial merge conflicts: `app/__init__.py`, `models.py`, `compiled.css`, `layout.html` (upstream sidebar vs our top navbar), `main/dashboard.html`. Next action: decide whether to adopt Equity at all; if not, cherry-pick only the non-equity fixes (stylesheet guard, websocket-manager shapes, service lock) after checking they do not depend on it; if yes, rebuild its menu in the navbar, merge service startup with `strategy_engine_enabled`/`start_background_services`, test locally, deploy only after review.
- [ ] **Closed carried-leg P&L fix, 2026-10-27: DEPLOYED to acc1 2026-10-28 ~15:55 IST (a1b95cb, 3 files copied, backup `/var/tmp/algomirror-bak-20261028`; service active, login 200, journal clean). Positions page itself is behind the login and was not opened - check it in the browser after the next roll**: after the ExpiryFade exits and the NDS roll the Positions P&L was wrong for the closed legs (Kotak reports only the day's slice for a carried leg once flat). `position_cost_basis.apply_cost_basis` now gives a flagged closed row the strategy book's realized P&L (10 tests pass); OpenAlgo got the same fix in `strategyAttribution.ts` (see `openalgo/SKYSHIELD_PATCHES.md`). Same round: an open Kotak row whose price was missing in OpenAlgo (pnl 0.0 placeholder) is now recomputed once AlgoMirror backfills the price; the Positions page shows a red notice when an account's rows are the cached copy; a row still on Kotak's carry valuation gets `*` on its P&L. Next action: after market, deploy the AlgoMirror file to acc1 and compare Positions total P&L with Kotak after the next roll; commit both repos (uncommitted).
- [ ] **P&L Analysis deployed to acc1 2026-10-16; old P&L History page retired** (user confirmed it works). `/trading/pnl-analysis` (template `trading/pnl_analysis.html`, `static/js/pnl_analysis.js`) reads `/trading/api/pnl-analysis` (`app/utils/pnl_analysis_combined.py`: per-account `/pnl/history` + `/pnl/curve`, lots concatenated, curves summed) and runs OpenAlgo's model, vendored as `static/js/vendor/pnl-model.js` (generated from the openalgo fork at 070f1007e; regenerate when `pnlModel.ts`/`pnlCurve.ts`/`pnlBuckets.ts`/`pnlPalette.ts` change). `/trading/pnl-history` now redirects to it, the Reports menu has the one entry, and the CSV upload moved onto the new page. The intraday P&L Plot stays. VM backups: `/var/tmp/algomirror-bak-20261016*`. Next action: compare a two-account selection with OpenAlgo's page for one range; push the commit to the `fork` remote.
- [ ] **Check the retag in the UI** (2026-10-01). `position_tags.strategy` on acc1 was
  rewritten `DonchianSwing -> EquityBreakoutPositional` (13 rows) at DB level.
  Open Holdings/Positions and confirm the strategy tag shows the new name.
- [ ] **Delete the pre-retag DB backup** (user: later) -
  `/home/arsalanansari17/retag_work/algomirror__algomirror.db.pre-retag-20261001` on
  the acc1 VM (root-owned, holds credentials).
- [ ] **Browser-test the P&L History fixes** deployed 2026-09-21 (commit `98d96f4`:
  account-filter label never updating, no out-of-order guard in `loadPnlHistory`).
  They were deployed but never exercised in a browser.
- [ ] Uncommitted work in `app/templates/trading/pnl_curve.html` (not Claude's, reviewed 2026-10-02):
  a new "Post to X" quick-post button (74 lines added) that opens X's compose window with today's
  P&L caption prefilled, plus `autoOpenXComposeIfRequested()` and a `lastRenderedStats` block. Looks
  like unfinished work on the share feature: finish and commit, or discard.

### Mobile friendly (added 2026-10-01, user request)
- [ ] Make AlgoMirror usable on a phone. Static audit done 2026-10-02: viewport tag set and every
  template with a table (all 18) has a horizontal-scroll wrapper, so nothing is structurally broken;
  how it looks and feels is unknown. The 2026-08 redesign
  already added a mobile bottom nav and slide-out menu, so the likely gaps are the
  wide multi-account tables (Holdings, Positions, Orderbook, Tradebook, Funds), modals
  and the account filter. Next action: open each page at ~390px width, list what breaks
  in this file, fix the worst first. Remember `npm run build-css` and commit
  `compiled.css` after any template change that adds or removes a Tailwind class.

### UI parity with OpenAlgo
- [ ] **Port all of OpenAlgo's Reports features to AlgoMirror** (2026-10-12, user request). Next action: inventory the
  OpenAlgo report pages (P&L History, strategy P&L views, tradebook/orderbook exports and any other "Reports"
  entries, from `openalgo/frontend/src/config/navigation.ts`), mark which AlgoMirror already has, then build the gaps
  page by page with the parity checklist (memory `reference_openalgo_parity_review_checklist`). Multi-account data
  comes from the per-account OpenAlgo APIs, so each report needs an account filter.
- [ ] Positions page: next in the page-by-page parity pass (Holdings is done). Use the
  checklist in memory `reference_openalgo_parity_review_checklist`.
- [ ] Orderbook/Tradebook feature gaps: sorting, filters, per-order Cancel / Cancel All /
  Modify, GTT tab (`KNOWN_ISSUES.md` #3). Cancel/Modify touch live orders - scope
  with the user before building. Read-only sort/filter can go first.

### Upstream PRs (marketcalls/Algomirror)
- [ ] `pnl-plot`, `share-feature` and `privacy-mode`: deployed to acc1, still
  live-testing. Privacy Mode is waiting on a real-screenshot check. Next action per
  feature: squash the `feat/*` branch into its `upstream/*` branch and open the PR.

### Tooling
- [ ] `migrations/` has no `env.py`/`alembic.ini` anywhere (local or VM), so
  `flask db upgrade` cannot run; schema changes are applied by hand with `ALTER TABLE`.
  Fix the scaffold once, then go back to normal migrations.

- **Shared price store: roll out and follow up** (2026-11-14). Deployed on acc1 only (commit `69c2813`, local, not pushed). Filler runs 15:45 IST Mon-Fri in the gunicorn worker (`PRICE_FILLER_ENABLED=1`), source = primary account (acc4), by hand `python fill_prices.py --now`. Next: (1) a general corporate-actions/rename layer (HEG, LTIM, SGLTL, SMLISUZU were fixed by a one-time NSE-file import on 2026-11-16; TATASTLBSL has no ledger conversion and BSE BILNCD2021 is unpriced); a recurring NSE-file fallback if more symbols appear; (3) check the 15:45 job logged a run (price_symbols covered_to moves each weekday); (4) push `69c2813` to the fork remote once approved.
- **Left after the acc2 deletion** (2026-11-16): Cloudflare DNS record for `acc2.skyshieldedge.com` removed and acc2's Kite API app deleted (both by the user, 2026-11-16; no nginx entry was left, it went with the VM); snapshot `iram-skyshield-final-20261116` deleted by the user's decision (acc2 data is reproducible, the tradebook can be re-downloaded from the Kite console); decide whether the 112 TATASTLBSL shares (merged into Tata Steel 15:1) need a ledger conversion.

## Done

- 2026-11-16: acc2 archived. Its ledger is served by `openalgo-archive-acc2.service` on acc1 (127.0.0.1:5001, read-only, no broker); AlgoMirror acc2 host switched to it; combined pages show all five accounts; acc2 VM and static IP deleted (snapshot `iram-skyshield-final-20261116`, local copy in `C:/Users/Arsalan/SkyShieldBackups`). Closes for LTIM/SGLTL/SMLISUZU/HEG imported from NSE files.

- 2026-11-13: shared daily-close store (`/prices/api/v1/history`, `daily_closes`, `price_symbols`, evening filler) deployed to acc1; first backfill 119 stored / 7 no data; acc1 curve loads in 3 s.
- 2026-10-10 Positions page: real entry average for carried Kotak legs (`app/utils/position_cost_basis.py`, route
  `correct_carried_cost_basis`, `ExtendedOpenAlgoAPI.strategy_attribution`, tooltip + asterisk). Kotak reports the
  previous settlement price as a carried leg's average (upstream openalgo#2061); a row OpenAlgo flags
  `average_price_basis = carry_forward_valuation` is replaced from `POST /api/v1/pnl/attribution` only when the strategy
  book fully explains it. Commit `3f3b903`, 8 tests (`tests/test_position_cost_basis.py`). **Deployed** to acc1
  2026-10-10: the VM's two hand-edited templates (`account_filter.html`, `pnl_history.html`) were byte-identical to
  `77d5511`, so the VM was reset to `3f3b903` (`git fetch origin feat/multi-account-filter; git reset --hard FETCH_HEAD`)
  and its old commits (`c9149be` + revert `59dba24`, net zero) are kept on the VM branch `backup-vm-20261010`. The VM tree
  is now clean and equals the fork branch, so the "never git pull / copy the files" note above no longer applies; a plain
  `git fetch` + `git reset --hard` or fast-forward pull works. Still to confirm in the browser on a Monday carried position.
- 2026-10-01 Strategy tag retag at DB level on acc1 (`position_tags`, 13 rows).
