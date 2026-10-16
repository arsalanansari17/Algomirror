// Node check of the vendored OpenAlgo P&L model (static/js/vendor/pnl-model.js):
// the same vectors OpenAlgo's own tests use, so a stale or broken copy is caught.
// Run: node tests/pnl_model_vendor_check.js
const fs = require('fs')
const path = require('path')
const vm = require('vm')
const code = fs.readFileSync(path.join(__dirname, '..', 'app/static/js/vendor/pnl-model.js'), 'utf8')
const ctx = {}
vm.createContext(ctx)
vm.runInContext(code + '\n;this.PnlModel = PnlModel;', ctx)
const PM = ctx.PnlModel
const assert = (cond, msg) => { if (!cond) { console.error('FAIL', msg); process.exit(1) } }
const eq = (a, b, msg) => assert(JSON.stringify(a) === JSON.stringify(b), `${msg}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`)

// Buckets (weeks run Monday to Sunday).
const dates = ['2026-05-04', '2026-05-05', '2026-05-08', '2026-05-11', '2026-06-01']
const values = [100, -40, 25, 10, -5]
eq(PM.bucketize(dates, values, 'week').map((b) => b.value), [85, 10, -5], 'week buckets')
eq(PM.bucketize(dates, values, 'month').map((b) => b.value), [95, -5], 'month buckets')

// Drawdown helpers.
const cum = [100, 160, 90, 60, 120]
const d5 = ['2026-05-04', '2026-05-05', '2026-05-06', '2026-05-07', '2026-05-08']
const now = PM.currentDrawdown(d5, cum)
eq([now.depth, now.peakValue, now.daysSincePeak], [-40, 160, 3], 'current drawdown')
eq(PM.runningMaxDrawdown(PM.drawdown(d5, cum).series), [0, 0, -70, -100, -100], 'running max drawdown')

// Model on an equity curve: combined = realized + change in the open level.
const curve = {
  dates: ['2026-05-05', '2026-05-06', '2026-05-07'],
  by_strategy: {
    EBP: { realized: [0, 0, 200], unrealized: [50, 150, 0] },
    Untagged: { realized: [0, 0, 0], unrealized: [30, 30, 30] },
  },
  basis: 'actual_cost', base_date: '2026-05-04',
  notes: { orphan_sells: [], missing_close: [], missing_base: [] },
}
const base = {
  closedTrades: [], openPositions: [], unrealizedAvailable: false, curve,
  segment: 'equity', pnlType: 'combined',
  filters: { symbol: '', strategies: [], exchanges: [], products: [] }, maxStrategies: 8,
}
const all = PM.buildPnlModel(base)
eq(all.series.total, [80, 100, 50], 'combined series')
eq(all.split, { realized: 200, unrealized: 30 }, 'split')
const ebp = PM.buildPnlModel({ ...base, filters: { ...base.filters, strategies: ['EBP'] } })
eq(ebp.series.total, [50, 100, 50], 'EBP only')
eq(Array.from(ebp.perStrategy.keys()), ['EBP'], 'per strategy follows the filter')
console.log('pnl-model vendor check: ok')
