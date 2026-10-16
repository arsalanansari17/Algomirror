/*
 * P&L Analysis page (fork-only): AlgoMirror's port of OpenAlgo's P&L Analysis.
 *
 * The data comes from /trading/api/pnl-analysis, which already merged every
 * selected account's /pnl/history and /pnl/curve (app/utils/
 * pnl_analysis_combined.py). Everything shown is computed in the browser by
 * OpenAlgo's own model code, vendored as static/js/vendor/pnl-model.js
 * (window.PnlModel), so one account selected gives the numbers OpenAlgo shows
 * for it. This file only draws: filters, summary, curve, strategies, calendar
 * and the Day / Week / Month / Scrip breakdown.
 */
(function () {
    'use strict';

    var PM = window.PnlModel;
    var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    var CURVE_PANE = 340;
    var DRAWDOWN_PANE = 120;

    var S = {
        dataUrl: '',
        raw: null,
        model: null,
        seq: 0,
        filters: { symbol: '', strategies: [], exchanges: [], products: [] },
        options: { strategies: [], exchanges: [], products: [] },
        breakdown: 'day',
        brMode: 'chart',
        curveView: 'chart',
        hiddenLines: {},
        curveChart: null,
        barChart: null,
        symbolTimer: null,
        presetKey: null
    };

    // ------------------------------------------------------------ helpers
    function $(id) { return document.getElementById(id); }

    function isDark() {
        return document.documentElement.getAttribute('data-theme') === 'dark';
    }

    function money(value) {
        var v = Number(value) || 0;
        var abs = Math.abs(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return (v < 0 ? '-' : '') + '₹' + abs;
    }

    function cls(value) { return value >= 0 ? 'text-success' : 'text-error'; }

    function esc(text) {
        return String(text == null ? '' : text)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function pct(value) { return value === null ? '-' : Math.round(value * 100) + '%'; }
    function ratio(value) { return value === null ? '-' : value.toFixed(2); }

    function dateStr(d) {
        return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }

    function selectedAccountIds() {
        var boxes = document.querySelectorAll('#accountFilterDropdown .account-filter-checkbox');
        var checked = document.querySelectorAll('#accountFilterDropdown .account-filter-checkbox:checked');
        if (boxes.length === 0 || checked.length === boxes.length) return [];
        return Array.prototype.map.call(checked, function (cb) { return cb.value; });
    }

    function segmentValue() { return $('paSegment').value; }
    function typeValue() { return $('paPnlType').value; }
    function isReady() { return !!segmentValue() && !!typeValue(); }

    function palette() {
        return isDark()
            ? { text: '#c3c2b7', grid: 'rgba(166, 173, 187, 0.12)', axis: 'rgba(166, 173, 187, 0.25)', total: '#ffffff' }
            : { text: '#52514e', grid: 'rgba(0, 0, 0, 0.08)', axis: 'rgba(0, 0, 0, 0.2)', total: '#0b0b0b' };
    }

    // ------------------------------------------------------------ model
    function buildModel() {
        if (!S.raw) return null;
        var segment = S.raw.segment === 'all' ? 'all' : S.raw.segment;
        var model = PM.buildPnlModel({
            closedTrades: S.raw.closed_trades || [],
            openPositions: S.raw.open_positions || [],
            unrealizedAvailable: S.raw.total_unrealized_pnl !== null && S.raw.total_unrealized_pnl !== undefined,
            curve: S.raw.curve || null,
            segment: segment,
            pnlType: typeValue() || 'combined',
            filters: S.filters,
            maxStrategies: PM.MAX_STRATEGY_SERIES
        });
        S.options = model.options;
        return model;
    }

    // ------------------------------------------------------------ fetch
    function paFetch() {
        if (!isReady()) return;
        var start = $('paStartDate').value;
        var end = $('paEndDate').value;
        var errorEl = $('paError');
        if (!start || !end) {
            errorEl.textContent = 'Select both a start and end date';
            errorEl.classList.remove('hidden');
            return;
        }
        errorEl.classList.add('hidden');
        var seq = ++S.seq;
        $('paFetchBtn').disabled = true;
        $('paFetchLabel').textContent = 'Loading...';
        $('paLoading').classList.remove('hidden');

        var params = new URLSearchParams({ start_date: start, end_date: end });
        var segment = segmentValue();
        if (segment !== 'all') params.set('segment', segment);
        var needle = S.filters.symbol.trim().toUpperCase();
        if (needle && segment === 'equity') params.set('symbol_contains', needle);
        selectedAccountIds().forEach(function (id) { params.append('account', id); });

        return fetch(S.dataUrl + '?' + params.toString())
            .then(function (r) { return r.json(); })
            .then(function (result) {
                if (seq !== S.seq) return;
                if (result.status !== 'success') throw new Error(result.message || 'Failed to load P&L');
                S.raw = result.data;
                S.raw.segment = segment;
                S.raw.start = start;
                S.raw.end = end;
                $('paEmpty').classList.add('hidden');
                $('paContent').classList.remove('hidden');
                renderAll();
                reportNotes();
            })
            .catch(function (err) {
                if (seq !== S.seq) return;
                errorEl.textContent = err.message || 'Failed to load P&L';
                errorEl.classList.remove('hidden');
            })
            .then(function () {
                if (seq !== S.seq) return;
                $('paFetchBtn').disabled = !isReady();
                $('paFetchLabel').textContent = 'Fetch';
                $('paLoading').classList.add('hidden');
            });
    }

    function reportNotes() {
        var raw = S.raw;
        var failed = raw.failed_accounts || [];
        var failedEl = $('paFailedAccounts');
        if (failed.length) {
            failedEl.textContent = 'Could not fetch data for: ' + failed.join(', ') +
                " - the totals below don't include " + (failed.length > 1 ? 'these accounts' : 'this account') + '.';
            failedEl.classList.remove('hidden');
        } else {
            failedEl.classList.add('hidden');
        }
        var missing = raw.curve_missing_accounts || [];
        var missingEl = $('paCurveMissing');
        if (missing.length) {
            missingEl.textContent = 'No daily curve from: ' + missing.join(', ') +
                ' (that account needs the P&L Analysis build of OpenAlgo). Its closed trades are in the Scrip view only.';
            missingEl.classList.remove('hidden');
        } else {
            missingEl.classList.add('hidden');
        }
        // One toast, not a standing list.
        var notes = (raw.curve && raw.curve.notes) || null;
        if (notes && typeof showToast === 'function') {
            var brief = function (names) {
                return names.length > 4 ? names.slice(0, 4).join(', ') + ' +' + (names.length - 4) + ' more' : names.join(', ');
            };
            var parts = [];
            var orphan = {};
            (notes.orphan_sells || []).forEach(function (o) { orphan[o.symbol] = true; });
            var orphanNames = Object.keys(orphan);
            if (orphanNames.length) {
                parts.push(orphanNames.length + ' symbols had a sell with no earlier buy in the ledger and were left out (' + brief(orphanNames) + ')');
            }
            if ((notes.missing_close || []).length) {
                parts.push('no daily price for ' + brief(notes.missing_close) + ', held at cost');
            }
            if (notes.calendar) parts.push('trading days: ' + notes.calendar);
            if (parts.length) showToast(parts.join('; '), 'warning');
        }
    }

    // ------------------------------------------------------------ render
    function renderAll() {
        S.model = buildModel();
        if (!S.model) return;
        renderTags();
        renderNotice();
        renderCalendar();
        renderSummary();
        renderCurve();
        renderStrategies();
        renderBreakdown();
    }

    function renderNotice() {
        var el = $('paNotice');
        if (S.model.curveIgnoresFilters) {
            el.textContent = 'Exchange and product narrow the Scrip view only: for Equity the curve, summary and time views treat NSE and BSE as one position.';
            el.classList.remove('hidden');
        } else {
            el.classList.add('hidden');
        }
    }

    function filterTags() {
        var f = S.filters;
        var tags = [];
        if (f.symbol.trim()) tags.push({ label: 'Symbol: ' + f.symbol.trim(), kind: 'symbol', value: '' });
        f.strategies.forEach(function (v) { tags.push({ label: v === PM.NO_STRATEGY ? 'No strategy' : v, kind: 'strategies', value: v }); });
        f.exchanges.forEach(function (v) { tags.push({ label: v, kind: 'exchanges', value: v }); });
        f.products.forEach(function (v) { tags.push({ label: v, kind: 'products', value: v }); });
        return tags;
    }

    function renderTags() {
        var tags = filterTags();
        var el = $('paAppliedTags');
        if (!tags.length) {
            el.innerHTML = '<span class="text-muted-foreground">No filters applied</span>';
        } else {
            el.innerHTML = '<span class="text-muted-foreground">Applied:</span>' + tags.map(function (t, i) {
                return '<button type="button" class="btn btn-xs btn-outline rounded-full" data-tag="' + i + '">' + esc(t.label) + ' &times;</button>';
            }).join('');
            Array.prototype.forEach.call(el.querySelectorAll('[data-tag]'), function (btn) {
                btn.addEventListener('click', function () {
                    var t = tags[Number(btn.getAttribute('data-tag'))];
                    if (t.kind === 'symbol') { S.filters.symbol = ''; $('paFilterSymbol').value = ''; }
                    else S.filters[t.kind] = S.filters[t.kind].filter(function (v) { return v !== t.value; });
                    onFiltersChanged(t.kind === 'symbol');
                });
            });
        }
        $('paFiltersDot').classList.toggle('hidden', !tags.length);
        renderFilterChips();
    }

    function chipGroup(title, key, options) {
        if (!options.length) return '';
        return '<div><div class="label"><span class="label-text">' + title + '</span></div><div class="flex flex-wrap gap-2">' +
            options.map(function (opt) {
                var on = S.filters[key].indexOf(opt) >= 0;
                return '<button type="button" class="btn btn-xs rounded-full ' + (on ? 'btn-primary' : 'btn-outline') +
                    '" data-chip-key="' + key + '" data-chip-value="' + esc(opt) + '">' + esc(opt) + '</button>';
            }).join('') + '</div></div>';
    }

    function renderFilterChips() {
        $('paFilterStrategies').innerHTML = chipGroup('Strategy', 'strategies', S.options.strategies);
        $('paFilterExchanges').innerHTML = chipGroup('Exchange', 'exchanges', S.options.exchanges);
        $('paFilterProducts').innerHTML = chipGroup('Product', 'products', S.options.products);
        Array.prototype.forEach.call(document.querySelectorAll('#paFiltersModal [data-chip-key]'), function (btn) {
            btn.addEventListener('click', function () {
                var key = btn.getAttribute('data-chip-key');
                var value = btn.getAttribute('data-chip-value');
                var list = S.filters[key];
                S.filters[key] = list.indexOf(value) >= 0 ? list.filter(function (v) { return v !== value; }) : list.concat([value]);
                onFiltersChanged(false);
            });
        });
    }

    function renderCalendar() {
        var rs = S.model.realizedSeries;
        var days = rs.dates.map(function (date, i) {
            return { date: date, value: rs.total[i], tooltip: date + ': ' + money(rs.total[i]) };
        });
        renderCalendarHeatmap('paHeatmap', days, S.raw.start, S.raw.end, window.pnlHeatColor);
    }

    function card(label, valueHtml, sub) {
        return '<div class="border border-border rounded-lg px-4 py-3 bg-card shadow-sm">' +
            '<div class="text-xs text-muted-foreground">' + label + '</div>' + valueHtml +
            (sub ? '<div class="text-xs text-muted-foreground mt-1">' + sub + '</div>' : '') + '</div>';
    }

    function renderSummary() {
        var m = S.model;
        var s = m.series;
        var summary = PM.stats(s.dates, s.total);
        var cum = PM.cumulative(s.total);
        var dd = PM.drawdown(s.dates, cum).max;
        var now = PM.currentDrawdown(s.dates, cum);
        var type = typeValue();
        var realized = m.split.realized;
        var unrealized = m.split.unrealized;
        var net = type === 'realized' ? realized : type === 'unrealized' ? (unrealized || 0) : realized + (unrealized || 0);
        var netLabel = type === 'realized' ? 'Net realized P&amp;L' : type === 'unrealized' ? 'Unrealized P&amp;L' : 'Net P&amp;L (realized + unrealized)';

        var netCard = card(netLabel, '<div class="text-3xl font-bold ' + cls(net) + '">' + money(net) + '</div>',
            'Realized <span class="font-medium ' + cls(realized) + '">' + money(realized) + '</span> &nbsp; Unrealized ' +
            (unrealized === null ? '<span>not available</span>' : '<span class="font-medium ' + cls(unrealized) + '">' + money(unrealized) + '</span>'));
        var ddSub = dd.troughDate
            ? (dd.peakDate || 'start') + ' to ' + dd.troughDate + '; ' +
              (dd.recoveryDate ? 'recovered ' + dd.recoveryDate + ' (' + dd.days + ' days)' : 'not recovered (' + dd.days + ' days so far)')
            : 'The curve never fell below a previous high';
        var ddCard = card('Max drawdown', '<div class="text-3xl font-bold">' + money(dd.depth) + '</div>', ddSub);
        var nowCard = card('Current drawdown',
            '<div class="text-3xl font-bold ' + (now.atHigh ? 'text-success' : 'text-error') + '">' + money(now.depth) + '</div>',
            now.atHigh ? 'At a new high'
                : 'Below the ' + money(now.peakValue) + ' peak' + (now.peakDate ? ' of ' + now.peakDate : '') + ', ' +
                  now.daysSincePeak + ' day' + (now.daysSincePeak === 1 ? '' : 's') + ' ago');

        var best = summary.bestDay, worst = summary.worstDay;
        var small = [
            card('Win days', '<div class="text-2xl font-bold">' + pct(summary.winRate) + '</div>',
                summary.winDays + ' up, ' + summary.lossDays + ' down, of ' + summary.activeDays + ' days'),
            card('Profit factor', '<div class="text-2xl font-bold">' + ratio(summary.profitFactor) + '</div>', 'Winning days over losing days'),
            card('Average win / loss day',
                '<div class="text-lg font-bold"><span class="text-success">' + (summary.avgWinDay === null ? '-' : money(summary.avgWinDay)) +
                '</span> / <span class="text-error">' + (summary.avgLossDay === null ? '-' : money(summary.avgLossDay)) + '</span></div>',
                'Longest streak ' + summary.longestWinStreak + ' up / ' + summary.longestLossStreak + ' down'),
            card('Best / worst day',
                '<div class="text-lg font-bold"><span class="text-success">' + (best ? money(best.value) : '-') +
                '</span> / <span class="text-error">' + (worst ? money(worst.value) : '-') + '</span></div>',
                (best ? best.date : '') + ' / ' + (worst ? worst.date : ''))
        ];
        $('paSummary').innerHTML =
            '<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">' + netCard + ddCard + nowCard + '</div>' +
            '<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-4">' + small.join('') + '</div>';
    }

    // ------------------------------------------------------------ curve
    function curveLines() {
        var m = S.model;
        var p = palette();
        var dark = isDark();
        var cum = PM.cumulative(m.series.total);
        var lines = [{ name: 'Total', color: p.total, width: 3, values: cum }];
        m.strategyNames.forEach(function (name) {
            var daily = m.series.byStrategy.get(name);
            if (daily) lines.push({ name: name, color: PM.strategyColor(name, m.coloured, dark), width: 2, values: PM.cumulative(daily) });
        });
        if (m.splitLines) {
            lines.push({ name: 'Realized', color: PM.REALIZED_COLOR, width: 2, values: m.splitLines.realized });
            lines.push({ name: 'Unrealized', color: PM.UNREALIZED_COLOR, width: 2, values: m.splitLines.unrealized });
        }
        return lines;
    }

    function renderCurve() {
        var m = S.model;
        var type = typeValue();
        $('paCurveTitle').textContent = type === 'realized' ? 'Realized P&L (cumulative)'
            : type === 'unrealized' ? 'Unrealized P&L' : 'Cumulative P&L (realized + unrealized)';

        var series = m.series;
        var cum = PM.cumulative(series.total);
        var dd = PM.drawdown(series.dates, cum);

        // Table view.
        $('paCurveTableBody').innerHTML = series.dates.map(function (date, i) {
            return '<tr><td>' + date + '</td><td class="text-right font-medium ' + cls(series.total[i]) + '">' + money(series.total[i]) +
                '</td><td class="text-right font-medium ' + cls(cum[i]) + '">' + money(cum[i]) +
                '</td><td class="text-right text-muted-foreground">' + money(dd.series[i]) + '</td></tr>';
        }).join('');

        if (S.curveChart) { S.curveChart.remove(); S.curveChart = null; }
        var host = $('paCurveChart');
        host.innerHTML = '';
        var legend = $('paCurveLegend');
        legend.innerHTML = '';
        $('paCurveTooltip').classList.add('hidden');
        if (!series.dates.length) {
            host.innerHTML = '<div class="flex items-center justify-center h-full text-base-content/50">Nothing to plot for these filters</div>';
            return;
        }

        var lines = curveLines();
        legend.innerHTML = lines.map(function (line, i) {
            var off = S.hiddenLines[line.name];
            return '<button type="button" class="btn btn-xs rounded-full bg-base-100/80 border-base-300 ' + (off ? 'opacity-40' : '') +
                '" data-line="' + i + '"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + line.color + '"></span>' +
                esc(line.name) + '</button>';
        }).join('');
        Array.prototype.forEach.call(legend.querySelectorAll('[data-line]'), function (btn) {
            btn.addEventListener('click', function () {
                var name = lines[Number(btn.getAttribute('data-line'))].name;
                S.hiddenLines[name] = !S.hiddenLines[name];
                renderCurve();
            });
        });

        var p = palette();
        var dark = isDark();
        var chart = LightweightCharts.createChart(host, {
            width: host.clientWidth,
            height: host.clientHeight,
            layout: {
                background: { type: 'solid', color: 'transparent' },
                textColor: p.text,
                attributionLogo: false,
                panes: { enableResize: true, separatorColor: p.axis, separatorHoverColor: p.axis }
            },
            grid: { vertLines: { visible: false }, horzLines: { color: p.grid } },
            rightPriceScale: { borderColor: p.axis, scaleMargins: { top: 0.08, bottom: 0.08 } },
            timeScale: { borderColor: p.axis },
            crosshair: { vertLine: { labelVisible: false } },
            localization: { priceFormatter: money }
        });
        var drawn = [];
        lines.forEach(function (line) {
            if (S.hiddenLines[line.name]) return;
            var s = chart.addSeries(LightweightCharts.LineSeries, {
                color: line.color, lineWidth: line.width, priceLineVisible: false, lastValueVisible: false
            }, 0);
            s.setData(series.dates.map(function (date, i) { return { time: date, value: line.values[i] }; }));
            drawn.push({ series: s, name: line.name, color: line.color });
        });

        var ddColor = dark ? 'rgba(201, 200, 190, 0.85)' : 'rgba(82, 81, 78, 0.85)';
        var ddSeries = chart.addSeries(LightweightCharts.BaselineSeries, {
            baseValue: { type: 'price', price: 0 },
            topLineColor: ddColor, topFillColor1: 'rgba(0, 0, 0, 0)', topFillColor2: 'rgba(0, 0, 0, 0)',
            bottomLineColor: ddColor,
            bottomFillColor1: dark ? 'rgba(201, 200, 190, 0.04)' : 'rgba(82, 81, 78, 0.04)',
            bottomFillColor2: dark ? 'rgba(201, 200, 190, 0.3)' : 'rgba(82, 81, 78, 0.3)',
            lineWidth: 2, priceLineVisible: false, lastValueVisible: false
        }, 1);
        ddSeries.setData(series.dates.map(function (date, i) { return { time: date, value: dd.series[i] }; }));
        var mdd = PM.runningMaxDrawdown(dd.series);
        var mddSeries = chart.addSeries(LightweightCharts.LineSeries, {
            color: dark ? 'rgba(230, 103, 103, 0.9)' : 'rgba(227, 73, 72, 0.9)',
            lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false
        }, 1);
        mddSeries.setData(series.dates.map(function (date, i) { return { time: date, value: mdd[i] }; }));

        var panes = chart.panes();
        if (panes[0]) panes[0].setHeight(CURVE_PANE);
        if (panes[1]) panes[1].setHeight(DRAWDOWN_PANE);
        chart.timeScale().fitContent();

        var tip = $('paCurveTooltip');
        chart.subscribeCrosshairMove(function (param) {
            if (!param.point || !param.time || param.point.x < 0 || param.point.y < 0) {
                tip.classList.add('hidden');
                return;
            }
            var rows = drawn.map(function (d) {
                var point = param.seriesData.get(d.series);
                if (!point || typeof point.value !== 'number') return '';
                return '<div class="flex items-center justify-between gap-4"><span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' +
                    d.color + '"></span> ' + esc(d.name) + '</span><span class="font-mono">' + money(point.value) + '</span></div>';
            }).join('');
            var dv = param.seriesData.get(ddSeries);
            var mv = param.seriesData.get(mddSeries);
            if (dv && typeof dv.value === 'number') {
                rows += '<div class="mt-1 flex justify-between gap-4 border-t border-base-300 pt-1 text-base-content/60"><span>Current drawdown</span><span class="font-mono">' + money(dv.value) + '</span></div>';
            }
            if (mv && typeof mv.value === 'number') {
                rows += '<div class="flex justify-between gap-4 text-base-content/60"><span>Max drawdown so far</span><span class="font-mono">' + money(mv.value) + '</span></div>';
            }
            tip.innerHTML = '<div class="mb-1 font-medium">' + String(param.time) + '</div>' + rows;
            tip.classList.remove('hidden');
            var boxWidth = host.clientWidth;
            tip.style.left = Math.min(param.point.x + 16, boxWidth - 220) + 'px';
            tip.style.top = Math.max(param.point.y - 20, 0) + 'px';
        });
        S.curveChart = chart;
        window.addEventListener('resize', onResize);
    }

    function onResize() {
        var host = $('paCurveChart');
        if (S.curveChart && host) S.curveChart.applyOptions({ width: host.clientWidth });
        var bar = $('paBarChart');
        if (S.barChart && bar) S.barChart.applyOptions({ width: bar.clientWidth });
    }

    function paSetCurveView(view) {
        S.curveView = view;
        $('paCurveChartWrap').classList.toggle('hidden', view !== 'chart');
        $('paCurveTableWrap').classList.toggle('hidden', view !== 'table');
        $('paCurveShotBtn').disabled = view !== 'chart';
        $('paCurveChartBtn').className = (view === 'chart' ? 'btn btn-primary btn-sm' : 'btn btn-outline btn-sm');
        $('paCurveTableBtn').className = (view === 'table' ? 'btn btn-primary btn-sm' : 'btn btn-outline btn-sm');
        if (view === 'chart' && S.model) renderCurve();
    }

    function downloadCanvas(canvas, filename) {
        canvas.toBlob(function (blob) {
            if (!blob) return;
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }, 'image/png');
    }

    function paDownloadCurvePng() {
        if (!S.curveChart || !S.model) return;
        var shot = S.curveChart.takeScreenshot();
        var band = 56;
        var out = document.createElement('canvas');
        out.width = shot.width;
        out.height = shot.height + band;
        var ctx = out.getContext('2d');
        var dark = isDark();
        ctx.fillStyle = dark ? '#0b0b0b' : '#ffffff';
        ctx.fillRect(0, 0, out.width, out.height);
        ctx.fillStyle = dark ? '#ffffff' : '#0b0b0b';
        ctx.font = 'bold 16px sans-serif';
        ctx.fillText('P&L Analysis  ' + S.raw.start + ' to ' + S.raw.end, 12, 22);
        ctx.font = '13px sans-serif';
        var x = 12;
        curveLines().filter(function (l) { return !S.hiddenLines[l.name]; }).forEach(function (line) {
            ctx.fillStyle = line.color;
            ctx.fillRect(x, 36, 10, 10);
            ctx.fillStyle = dark ? '#c3c2b7' : '#52514e';
            var label = line.name + '  ' + money(line.values[line.values.length - 1] || 0);
            ctx.fillText(label, x + 16, 46);
            x += 16 + ctx.measureText(label).width + 18;
        });
        ctx.save();
        ctx.font = 'bold 42px Arial, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = dark ? 'rgba(166, 173, 187, 0.2)' : 'rgba(0, 0, 0, 0.15)';
        ctx.fillText('AlgoMirror', out.width / 2, band + shot.height / 2);
        ctx.restore();
        ctx.drawImage(shot, 0, band);
        downloadCanvas(out, 'PnL_Analysis_' + new Date().toISOString().slice(0, 10) + '.png');
    }

    // ------------------------------------------------------------ strategies
    function renderStrategies() {
        var m = S.model;
        var rows = PM.strategySummaries(m.series);
        $('paStrategiesCard').classList.toggle('hidden', rows.length === 0);
        var dates = m.series.dates;
        var dark = isDark();
        $('paStrategiesBodyRows').innerHTML = rows.map(function (row) {
            var daily = m.series.byStrategy.get(row.strategy) || [];
            var parts = m.perStrategy.get(row.strategy) || { realized: 0, unrealized: null };
            var now = PM.currentDrawdown(dates, PM.cumulative(daily)).depth;
            var color = PM.strategyColor(row.strategy, m.coloured, dark);
            return '<tr><td><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:' + color + '"></span> ' + esc(row.strategy) + '</td>' +
                '<td class="text-right font-medium ' + cls(row.netPnl) + '">' + money(row.netPnl) + '</td>' +
                '<td class="text-right ' + cls(parts.realized) + '">' + money(parts.realized) + '</td>' +
                '<td class="text-right ' + (parts.unrealized === null ? 'text-muted-foreground' : cls(parts.unrealized)) + '">' +
                    (parts.unrealized === null ? '-' : money(parts.unrealized)) + '</td>' +
                '<td class="text-right">' + money(row.maxDrawdown) + '</td>' +
                '<td class="text-right ' + (now < 0 ? 'text-error' : 'text-success') + '">' + money(now) + '</td>' +
                '<td class="text-right">' + pct(row.winRate) + '</td>' +
                '<td class="text-right">' + ratio(row.profitFactor) + '</td>' +
                '<td class="text-right">' + row.activeDays + '</td></tr>';
        }).join('');
    }

    // ------------------------------------------------------------ breakdown
    function scripRows() {
        var rows = {};
        var order = [];
        function blank(symbol, exchange, product) {
            return { key: symbol + '|' + exchange, symbol: symbol, exchange: exchange, product: product, closedQuantity: 0,
                buyValue: 0, sellValue: 0, realized: 0, openQuantity: 0, averagePrice: null, ltp: null, unrealized: null, notional: 0 };
        }
        S.model.lots.forEach(function (t) {
            var key = t.symbol + '|' + t.exchange;
            var row = rows[key];
            if (!row) { row = rows[key] = blank(t.symbol, t.exchange, t.product); order.push(key); }
            var isLong = t.entry_action === 'BUY';
            row.closedQuantity += t.quantity;
            row.buyValue += t.quantity * (isLong ? t.entry_price : t.exit_price);
            row.sellValue += t.quantity * (isLong ? t.exit_price : t.entry_price);
            row.realized += t.realized_pnl;
        });
        S.model.open.forEach(function (p) {
            var key = p.symbol + '|' + p.exchange;
            var row = rows[key];
            if (!row) { row = rows[key] = blank(p.symbol, p.exchange, p.product); order.push(key); }
            if (!row.product) row.product = p.product;
            row.openQuantity += p.action === 'BUY' ? p.quantity : -p.quantity;
            row.notional += p.quantity * p.average_price;
            row.averagePrice = row.notional / Math.abs(row.openQuantity || 1);
            row.ltp = p.ltp;
            if (p.unrealized_pnl !== null && p.unrealized_pnl !== undefined) row.unrealized = (row.unrealized || 0) + p.unrealized_pnl;
        });
        return order.map(function (k) { return rows[k]; }).sort(function (a, b) { return a.symbol.localeCompare(b.symbol); });
    }

    function paSetBreakdown(view) {
        S.breakdown = view;
        ['Day', 'Week', 'Month', 'Scrip'].forEach(function (name) {
            $('paTab' + name).classList.toggle('tab-active', name.toLowerCase() === view);
        });
        if (S.model) renderBreakdown();
    }

    function paSetBreakdownMode(mode) {
        S.brMode = mode;
        $('paBrChartBtn').className = mode === 'chart' ? 'btn btn-primary btn-sm' : 'btn btn-outline btn-sm';
        $('paBrTableBtn').className = mode === 'table' ? 'btn btn-primary btn-sm' : 'btn btn-outline btn-sm';
        $('paBrExportBtn').textContent = mode === 'chart' ? 'Image' : 'CSV';
        if (S.model) renderBreakdown();
    }

    function bucketTable(buckets, view) {
        var head = '<tr><th>' + (view === 'day' ? 'Date' : 'Week of') + '</th>' + (view === 'week' ? '<th class="text-right">Days</th>' : '') +
            '<th class="text-right">P&amp;L</th><th class="text-right">Cumulative</th></tr>';
        var body = buckets.slice().reverse().map(function (b) {
            return '<tr><td>' + b.start + '</td>' + (view === 'week' ? '<td class="text-right">' + b.days + '</td>' : '') +
                '<td class="text-right font-medium ' + cls(b.value) + '">' + money(b.value) + '</td>' +
                '<td class="text-right ' + cls(b.cumulative) + '">' + money(b.cumulative) + '</td></tr>';
        }).join('');
        return '<div class="max-h-[560px] overflow-auto"><table class="table table-sm"><thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>';
    }

    function monthTable() {
        var rows = PM.monthly(S.model.series.dates, S.model.series.total);
        var maxAbs = 0;
        rows.forEach(function (r) { r.months.forEach(function (v) { if (v !== null) maxAbs = Math.max(maxAbs, Math.abs(v)); }); });
        function tint(value) {
            if (value === 0 || maxAbs === 0) return 'transparent';
            var alpha = 0.1 + Math.min(Math.abs(value) / maxAbs, 1) * 0.5;
            return value > 0 ? 'rgba(34, 197, 94, ' + alpha + ')' : 'rgba(239, 68, 68, ' + alpha + ')';
        }
        var head = '<tr><th>Year</th>' + MONTHS.map(function (m) { return '<th class="text-right">' + m + '</th>'; }).join('') + '<th class="text-right">Year</th></tr>';
        var body = rows.map(function (r) {
            return '<tr><td class="font-medium">' + r.year + '</td>' + r.months.map(function (v) {
                return v === null ? '<td class="text-right text-muted-foreground">-</td>'
                    : '<td class="text-right ' + cls(v) + '" style="background-color:' + tint(v) + '">' + money(v) + '</td>';
            }).join('') + '<td class="text-right font-medium ' + cls(r.total) + '">' + money(r.total) + '</td></tr>';
        }).join('');
        return '<div class="overflow-x-auto"><table class="table table-sm"><thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>';
    }

    function scripTable(rows) {
        var head = '<tr><th>Symbol</th><th>Exchange</th><th>Product</th><th class="text-right">Qty</th><th class="text-right">Buy Value</th>' +
            '<th class="text-right">Sell Value</th><th class="text-right">Realized P&amp;L</th><th class="text-right">Open Qty</th>' +
            '<th class="text-right">Avg Price</th><th class="text-right">LTP</th><th class="text-right">Unrealized P&amp;L</th></tr>';
        var body = rows.map(function (r) {
            return '<tr><td>' + esc(r.symbol) + '</td><td>' + esc(r.exchange) + '</td><td>' + esc(r.product || '-') + '</td>' +
                '<td class="text-right">' + (r.closedQuantity || '-') + '</td>' +
                '<td class="text-right">' + (r.closedQuantity ? money(r.buyValue) : '-') + '</td>' +
                '<td class="text-right">' + (r.closedQuantity ? money(r.sellValue) : '-') + '</td>' +
                '<td class="text-right font-medium ' + (r.closedQuantity ? cls(r.realized) : 'text-muted-foreground') + '">' + (r.closedQuantity ? money(r.realized) : '-') + '</td>' +
                '<td class="text-right">' + (r.openQuantity || '-') + '</td>' +
                '<td class="text-right">' + (r.averagePrice === null ? '-' : money(r.averagePrice)) + '</td>' +
                '<td class="text-right">' + (r.ltp === null ? '-' : money(r.ltp)) + '</td>' +
                '<td class="text-right font-medium ' + (r.unrealized === null ? 'text-muted-foreground' : cls(r.unrealized)) + '">' + (r.unrealized === null ? '-' : money(r.unrealized)) + '</td></tr>';
        }).join('');
        return '<div class="max-h-[560px] overflow-auto"><table class="table table-sm"><thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>';
    }

    function scripBars(rows) {
        var type = typeValue();
        var showR = type !== 'unrealized';
        var showU = type !== 'realized';
        var items = rows.map(function (r) {
            return { symbol: r.symbol, total: (showR ? r.realized : 0) + (showU ? (r.unrealized || 0) : 0) };
        }).filter(function (r) { return r.total !== 0; }).sort(function (a, b) { return b.total - a.total; });
        if (items.length > 30) items = items.slice(0, 15).concat(items.slice(-15));
        if (!items.length) return '<p class="py-8 text-center text-muted-foreground">Nothing to plot</p>';
        var maxAbs = Math.max.apply(null, items.map(function (r) { return Math.abs(r.total); }).concat([1]));
        var up = isDark() ? '#22c55e' : '#16a34a';
        var down = isDark() ? '#ef4444' : '#dc2626';
        return '<div class="space-y-1">' + items.map(function (r) {
            var width = (Math.abs(r.total) / maxAbs * 50) + '%';
            var positive = r.total >= 0;
            return '<div class="flex items-center gap-3 text-sm"><span class="w-28 shrink-0 truncate">' + esc(r.symbol) + '</span>' +
                '<div class="relative h-5 flex-1"><div class="absolute inset-y-0 left-1/2 w-px bg-base-300"></div>' +
                '<div class="absolute inset-y-0 rounded-sm" style="width:' + width + ';background:' + (positive ? up : down) + ';' +
                (positive ? 'left:50%' : 'right:50%') + '"></div></div>' +
                '<span class="w-28 shrink-0 text-right font-mono text-xs ' + cls(r.total) + '">' + money(r.total) + '</span></div>';
        }).join('') + '</div>';
    }

    function renderBreakdown() {
        var m = S.model;
        var view = S.breakdown;
        var hint = { day: 'P&L for each trading day, for the selected P&L type.', week: 'P&L for each week, Monday to Sunday.',
            month: 'P&L for each calendar month.', scrip: 'Every closed lot and open position merged by symbol. Biggest winners first.' };
        $('paBreakdownHint').textContent = hint[view];
        var body = $('paBreakdownBody');
        if (S.barChart) { S.barChart.remove(); S.barChart = null; }

        var title = view === 'scrip' ? 'Scrip-wise P&L' : (view === 'day' ? 'Daily' : view === 'week' ? 'Weekly' : 'Monthly') + ' P&L';
        var caption = '<p class="mb-2 text-sm font-medium">' + title + ', ' + S.raw.start + ' to ' + S.raw.end + '</p>';

        if (view === 'scrip') {
            var rows = scripRows();
            if (!rows.length) { body.innerHTML = '<p class="py-8 text-center text-muted-foreground">No matching trades in this date range</p>'; return; }
            if (S.brMode === 'chart') {
                body.innerHTML = '<div id="paBrCapture"><div class="relative">' + watermarkHtml() + '<div class="relative" style="z-index:1">' + caption + scripBars(rows) + '</div></div></div>';
            } else {
                body.innerHTML = scripTable(rows);
            }
            return;
        }

        var buckets = PM.bucketize(m.series.dates, m.series.total, view);
        if (!buckets.length) { body.innerHTML = '<p class="py-8 text-center text-muted-foreground">Nothing in this date range</p>'; return; }

        if (S.brMode === 'table') {
            body.innerHTML = view === 'month' ? monthTable() : bucketTable(buckets, view);
            return;
        }
        body.innerHTML = '<div id="paBrCapture">' + caption + '<div class="relative" style="height:340px">' + watermarkHtml() +
            '<div id="paBarChart" class="absolute inset-0" style="z-index:1"></div>' +
            '<div id="paBarTip" class="hidden absolute pointer-events-none rounded-md border border-base-300 bg-base-100 px-3 py-2 text-xs shadow-md" style="z-index:6"></div></div></div>';
        drawBars(buckets);
    }

    function watermarkHtml() {
        return '<div class="absolute inset-0 flex items-center justify-center pointer-events-none select-none text-base-content/15" style="z-index:0">' +
            '<div class="text-center"><div style="font-family:Arial,sans-serif;font-weight:bold;font-size:36px">AlgoMirror</div>' +
            '<div style="font-family:Arial,sans-serif;font-size:14px">Powered by OpenAlgo</div></div></div>';
    }

    function drawBars(buckets) {
        var host = $('paBarChart');
        var p = palette();
        var dark = isDark();
        var chart = LightweightCharts.createChart(host, {
            width: host.clientWidth,
            height: host.clientHeight,
            layout: { background: { type: 'solid', color: 'transparent' }, textColor: p.text, attributionLogo: false },
            grid: { vertLines: { visible: false }, horzLines: { color: p.grid } },
            rightPriceScale: { borderColor: p.axis, scaleMargins: { top: 0.1, bottom: 0.1 } },
            timeScale: { borderColor: p.axis },
            crosshair: { vertLine: { labelVisible: false } },
            localization: { priceFormatter: money }
        });
        var bars = chart.addSeries(LightweightCharts.HistogramSeries, { priceLineVisible: false, lastValueVisible: false, base: 0 });
        var up = PM.positive(dark);
        var down = PM.negative(dark);
        bars.setData(buckets.map(function (b) { return { time: b.start, value: b.value, color: b.value >= 0 ? up : down }; }));
        chart.timeScale().fitContent();
        var byStart = {};
        buckets.forEach(function (b) { byStart[b.start] = b; });
        var tip = $('paBarTip');
        chart.subscribeCrosshairMove(function (param) {
            var b = param.time ? byStart[String(param.time)] : null;
            if (!param.point || !b || param.point.x < 0 || param.point.y < 0) { tip.classList.add('hidden'); return; }
            tip.innerHTML = '<div class="mb-1 font-medium">' + esc(b.label) + ' (' + b.days + ' day' + (b.days === 1 ? '' : 's') + ')</div><div class="font-mono">' + money(b.value) + '</div>';
            tip.classList.remove('hidden');
            tip.style.left = Math.min(param.point.x + 16, host.clientWidth - 200) + 'px';
            tip.style.top = Math.max(param.point.y - 20, 0) + 'px';
        });
        S.barChart = chart;
        window.addEventListener('resize', onResize);
    }

    function csvEscape(value) {
        var s = String(value == null ? '' : value);
        if (/^[=+\-@]/.test(s)) s = "'" + s;
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    }

    function paExportBreakdown() {
        if (!S.model) return;
        var view = S.breakdown;
        var name = 'pnl_' + view + '_' + S.raw.start + '_' + S.raw.end;
        if (S.brMode === 'chart') {
            var el = $('paBrCapture');
            if (!el || typeof html2canvas !== 'function') return;
            html2canvas(el, { backgroundColor: isDark() ? '#1f2937' : '#ffffff', scale: 2, logging: false, useCORS: true })
                .then(function (canvas) { downloadCanvas(canvas, name + '.png'); });
            return;
        }
        var headers, rows;
        if (view === 'scrip') {
            headers = ['Symbol', 'Exchange', 'Product', 'Closed Qty', 'Buy Value', 'Sell Value', 'Realized P&L', 'Open Qty', 'Avg Price', 'LTP', 'Unrealized P&L'];
            rows = scripRows().map(function (r) {
                return [r.symbol, r.exchange, r.product || '', r.closedQuantity, r.buyValue.toFixed(2), r.sellValue.toFixed(2), r.realized.toFixed(2),
                    r.openQuantity, r.averagePrice === null ? '' : r.averagePrice.toFixed(2), r.ltp === null ? '' : r.ltp.toFixed(2),
                    r.unrealized === null ? '' : r.unrealized.toFixed(2)];
            });
        } else {
            headers = [view === 'day' ? 'Date' : view === 'week' ? 'Week of' : 'Month', 'Days', 'P&L', 'Cumulative'];
            rows = PM.bucketize(S.model.series.dates, S.model.series.total, view).map(function (b) {
                return [b.start, b.days, b.value.toFixed(2), b.cumulative.toFixed(2)];
            });
        }
        if (!rows.length) return;
        var csv = [headers].concat(rows).map(function (row) { return row.map(csvEscape).join(','); }).join('\n');
        var url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
        var a = document.createElement('a');
        a.href = url;
        a.download = name + '.csv';
        a.click();
        URL.revokeObjectURL(url);
    }

    // ------------------------------------------------------------ controls
    function paToggle(bodyId, chevronId) {
        var body = $(bodyId);
        var hidden = body.classList.toggle('hidden');
        $(chevronId).innerHTML = hidden ? '&#9656;' : '&#9662;';
    }

    function updateFetchState() {
        $('paFetchBtn').disabled = !isReady();
    }

    function paOnControlChange() {
        updateFetchState();
        // Unrealized and Combined mean something only for Equity; keep Fetch honest.
        if (S.raw && isReady()) paFetch();
    }

    function paOnPnlTypeChange() {
        updateFetchState();
        if (S.raw) renderAll();
    }

    function onFiltersChanged(symbolChanged) {
        if (!S.raw) { renderTags(); return; }
        if (symbolChanged && segmentValue() === 'equity') {
            renderTags();
            paFetch();
        } else {
            renderAll();
        }
    }

    function paOnSymbolInput() {
        S.filters.symbol = $('paFilterSymbol').value;
        clearTimeout(S.symbolTimer);
        S.symbolTimer = setTimeout(function () { onFiltersChanged(true); }, 400);
    }

    function paClearFilters() {
        S.filters = { symbol: '', strategies: [], exchanges: [], products: [] };
        $('paFilterSymbol').value = '';
        onFiltersChanged(true);
    }

    function onAccountFilterChange() {
        if (S.raw && isReady()) paFetch();
    }

    function paSubmitImport() {
        var accountId = $('paImportAccount').value;
        var fileInput = $('paImportFile');
        var errorEl = $('paImportError');
        var submitBtn = $('paImportSubmitBtn');
        errorEl.classList.add('hidden');
        if (!fileInput.files.length) {
            errorEl.textContent = 'Please select a CSV file';
            errorEl.classList.remove('hidden');
            return;
        }
        var formData = new FormData();
        formData.append('account_id', accountId);
        formData.append('file', fileInput.files[0]);
        submitBtn.disabled = true;
        fetch(S.importUrl, { method: 'POST', body: formData })
            .then(function (r) { return r.json(); })
            .then(function (result) {
                if (result.status !== 'success') throw new Error(result.message || 'Failed to import CSV');
                $('paImportModal').close();
                fileInput.value = '';
                if (typeof showToast === 'function') showToast('CSV imported', 'success');
                if (S.raw && isReady()) paFetch();
            })
            .catch(function (err) {
                errorEl.textContent = err.message || 'Failed to import CSV';
                errorEl.classList.remove('hidden');
            })
            .then(function () { submitBtn.disabled = false; });
    }

    function init(cfg) {
        S.dataUrl = cfg.dataUrl;
        S.importUrl = cfg.importUrl;
        var end = new Date();
        var start = new Date();
        start.setDate(start.getDate() - 30);
        $('paStartDate').value = dateStr(start);
        $('paEndDate').value = dateStr(end);
        $('paEndDate').max = dateStr(end);
        renderDateRangePresets('paDatePresets', S.presetKey, function (s, e, key) {
            S.presetKey = key;
            $('paStartDate').value = s;
            $('paEndDate').value = e;
            if (isReady()) paFetch();
        });
        document.addEventListener('keydown', function (event) {
            if (event.altKey && !event.ctrlKey && !event.metaKey && String(event.key).toLowerCase() === 'r') {
                event.preventDefault();
                // The scale only: filters and line toggles stay as they are.
                if (S.curveChart) S.curveChart.timeScale().fitContent();
                if (S.barChart) S.barChart.timeScale().fitContent();
            }
        });
        paSetBreakdownMode('chart');
        updateFetchState();
    }

    window.PnlAnalysisPage = { init: init };
    window.paFetch = paFetch;
    window.paOnControlChange = paOnControlChange;
    window.paOnPnlTypeChange = paOnPnlTypeChange;
    window.paToggle = paToggle;
    window.paSetCurveView = paSetCurveView;
    window.paDownloadCurvePng = paDownloadCurvePng;
    window.paSetBreakdown = paSetBreakdown;
    window.paSetBreakdownMode = paSetBreakdownMode;
    window.paExportBreakdown = paExportBreakdown;
    window.paOnSymbolInput = paOnSymbolInput;
    window.paClearFilters = paClearFilters;
    window.paSubmitImport = paSubmitImport;
    window.onPnlAnalysisAccountFilterChange = onAccountFilterChange;
})();
