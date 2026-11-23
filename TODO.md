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
- [x] **P&L Analysis unrealized vs Holdings (2026-11-24): DEPLOYED, now within about 132 on 23 Nov closes (49,012.73 against 48,881.02).** Three fixes: d9ab8ff reprices the open holdings at the Holdings price chain and moves the curve's last unrealized level by the difference (only holdings with a strategy: book or manual tag; legacy holdings stay out); 081d663 makes a filler run never claim a day that has not finished (a manual run at 00:40 had set coverage to the coming day, which would have stopped the 15:45 top-up; 20 `price_symbols.covered_to` values repaired to 2026-11-23 after a backup in `/var/tmp/algomirror-bak-20261124/`) and adds a 09:03 settle pass (the 15:45 bar is provisional: 23 Nov stored CYIENT 1153.70 against 1160.50, 5 of 7 symbols off; a later re-fetch corrects it exactly); 4d6ed80 fixes the real cause of the 43,031: merge_curves counted an account with no point for a date as zero for the unrealized LEVEL, so the archived acc2 (curve ends at the last stored close) dropped its open CYIENT lot (about 6K) from the Net on the last date. Levels now carry forward. Per account every curve matched its Holdings figure within about 100. Residual 132 (EBP +75, RS +159, acc1 Untagged -102): lot cost from fills (FIFO) against the broker average, not a price or scope error. Not chased, and aligning it would put a one-day jump into the curve. Still open elsewhere: acc3's stale strategy-book leg WELSPUNLIV 332 @167.87 (openalgo TODO 2026-11-19) inflates OpenAlgo's open rows of acc3 (not the curve); Positions/F&O are not covered by the price chain.
- [x] **Holdings strategy tags from the strategy book: DEPLOYED to acc1 2026-11-24 (e75a617, df199c8).** Manual `PositionTag` labels were deleted when a symbol left the holdings; tags now come from OpenAlgo's `/api/v1/pnl/attribution` (kind holdings), the last good map is kept per account, manual labels are the fallback, `RSR` is shown as `RSRotationPositional`. Also (df199c8): an empty holdings reply outside market hours no longer replaces non-empty cached holdings (a logged-out Kotak answered success with nothing at 00:00 and wiped accounts 3, 4, 5, hiding the RS rows and the RSR chip). Still to check in the browser: tags per account, and that the stale acc3 WELSPUNLIV leg (EBP 332 @167.87) falls back to its manual tag.
- [x] **Holdings priced from one market-level source: DEPLOYED to acc1 2026-11-24 (2e44dda, 0b43655).** acc2's archived CYIENT lot carried a stale LTP (1,121.70 against 1,160.50), so Holdings understated it by about 3.8K and Day's P&L by the same. `app/utils/holding_price.py` picks the price per row: live source-account quote in market hours and on a weekday outside them (the official close), the stored close on weekends and holidays, else the account's own LTP marked stale (asterisk on LTP, a note under Day's P&L). Not covered: Positions/F&O (the store has no option prices); a weekday exchange holiday can show a false stale mark.
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
