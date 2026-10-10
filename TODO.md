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

## Done
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
