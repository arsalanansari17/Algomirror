// Smoke test of the P&L Analysis page's JS in jsdom: renders the Jinja page (see
// tests/render_pnl_analysis_page.py), runs the real scripts with a stubbed
// chart library and fetch, and checks the page fills in from one API response.
// Run: node tests/pnl_analysis_page_check.js <rendered.html> <path-to-jsdom>
const fs = require('fs')
const path = require('path')
const { JSDOM } = require(process.argv[3])

const html = fs.readFileSync(process.argv[2], 'utf8').replace(/<script[\s\S]*?<\/script>/g, '')
const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/trading/pnl-analysis' })
const w = dom.window
const read = (p) => fs.readFileSync(path.join(__dirname, '..', p), 'utf8')

const fakeSeries = () => ({ setData() {}, applyOptions() {} })
const fakeChart = () => ({
  addSeries: fakeSeries,
  panes: () => [{ setHeight() {} }, { setHeight() {} }],
  timeScale: () => ({ fitContent() {} }),
  subscribeCrosshairMove() {}, remove() {}, applyOptions() {},
  takeScreenshot: () => w.document.createElement('canvas'),
})
w.LightweightCharts = {
  createChart: fakeChart, LineSeries: 'L', BaselineSeries: 'B', HistogramSeries: 'H',
}
w.html2canvas = () => Promise.resolve(w.document.createElement('canvas'))
w.showToast = (message, type) => { w.__toasts = (w.__toasts || []).concat([[type, message]]) }

const API = {
  status: 'success',
  data: {
    start_date: '2026-05-01', end_date: '2026-05-31', segment: 'equity',
    closed_trades: [{
      symbol: 'WOCKPHARMA', exchange: 'NSE', product: 'CNC', entry_action: 'BUY', quantity: 45,
      entry_price: 1530.4, entry_timestamp: '2026-05-05T15:16:00', exit_price: 1915.1,
      exit_timestamp: '2026-05-07T15:15:00', realized_pnl: 200, strategy: 'EquityBreakoutPositional',
      account_id: 1, account_name: 'Arsalan',
    }],
    open_positions: [], total_unrealized_pnl: null,
    curve: {
      dates: ['2026-05-05', '2026-05-06', '2026-05-07'],
      by_strategy: {
        EquityBreakoutPositional: { realized: [0, 0, 200], unrealized: [50, 150, 0] },
        Untagged: { realized: [0, 0, 0], unrealized: [30, 30, 30] },
      },
      basis: 'actual_cost', base_date: '2026-05-04',
      notes: { orphan_sells: [], missing_close: ['AAA'], missing_base: [] },
    },
    per_account: [], failed_accounts: [], curve_missing_accounts: [],
  },
}
w.fetch = (url) => { w.__url = url; return Promise.resolve({ json: () => Promise.resolve(API) }) }

const run = (code) => w.eval(code)
run(read('app/static/js/vendor/pnl-model.js').replace('var PnlModel =', 'window.PnlModel ='))
run(read('app/static/js/calendar_heatmap.js'))
run(read('app/static/js/date_range_presets.js'))
run(read('app/static/js/pnl_analysis.js'))
w.PnlAnalysisPage.init({ dataUrl: '/trading/api/pnl-analysis' })

const $ = (id) => w.document.getElementById(id)
const assert = (cond, msg) => { if (!cond) { console.error('FAIL:', msg); process.exit(1) } }

assert($('paFetchBtn').disabled, 'Fetch is disabled until a segment and a P&L type are chosen')
$('paSegment').value = 'equity'
w.paOnControlChange()
assert($('paFetchBtn').disabled, 'still disabled with only a segment')
$('paPnlType').value = 'combined'
w.paOnPnlTypeChange()
assert(!$('paFetchBtn').disabled, 'Fetch enabled once both are chosen')

w.paFetch().then(() => {
  assert(w.__url.includes('segment=equity') && w.__url.includes('start_date='), 'request params: ' + w.__url)
  assert(!$('paContent').classList.contains('hidden'), 'content is shown after the fetch')
  const summary = $('paSummary').textContent
  assert(summary.includes('Net P&L (realized + unrealized)'), 'net card')
  assert(summary.includes('Current drawdown') && summary.includes('Max drawdown'), 'drawdown cards')
  assert(summary.includes('\u20B9230.00'), 'net = realized 200 + open level 30: ' + summary)
  const rows = $('paStrategiesBodyRows').textContent
  assert(rows.includes('EquityBreakoutPositional') && rows.includes('Untagged'), 'strategy rows')
  assert($('paCurveTableBody').children.length === 3, 'curve table has one row per day')
  assert($('paBreakdownBody').textContent.length > 0, 'breakdown rendered')
  assert((w.__toasts || []).some((t) => t[1].includes('no daily price for AAA')), 'one toast for the notes')

  // Filter to one strategy: Untagged leaves the strategies table and the net changes.
  w.PnlAnalysisPage.init // (init is idempotent enough for this check)
  const chip = Array.from(w.document.querySelectorAll('#paFiltersModal [data-chip-key="strategies"]'))
    .find((b) => b.getAttribute('data-chip-value') === 'EquityBreakoutPositional')
  assert(chip, 'strategy chip with Untagged and EquityBreakoutPositional options')
  chip.click()
  const after = $('paStrategiesBodyRows').textContent
  assert(!after.includes('Untagged') && after.includes('EquityBreakoutPositional'), 'strategies follow the filter')
  assert($('paAppliedTags').textContent.includes('EquityBreakoutPositional'), 'applied tag shown')

  // Breakdown views.
  w.paSetBreakdown('week'); w.paSetBreakdownMode('table')
  assert($('paBreakdownBody').textContent.includes('Days'), 'week table')
  w.paSetBreakdown('month')
  assert($('paBreakdownBody').textContent.includes('May') || $('paBreakdownBody').textContent.includes('Year'), 'month grid')
  w.paSetBreakdown('scrip')
  assert($('paBreakdownBody').textContent.includes('WOCKPHARMA'), 'scrip table')
  console.log('pnl_analysis page check: ok')
}).catch((e) => { console.error(e); process.exit(1) })
