/*
 * Shared calendar heat map renderer (fork-only P&L feature).
 * Ports frontend/src/components/reports/CalendarHeatmap.tsx from the
 * OpenAlgo React app to vanilla JS - since AlgoMirror's pages are
 * server-rendered + vanilla JS, not React. Used by both P&L History
 * (green/red by realized P&L) and Trade Book (blue by trade count) - each
 * page supplies its own `days` array and `colorFor` function; the layout
 * itself is identical.
 *
 * Layout is a continuous strip - weeks as columns, Sun-Sat as rows, month
 * labels placed under whichever column that month first appears in - a
 * GitHub-contributions-graph style, matching Zerodha Console's own
 * reference exactly (confirmed against a real Zerodha Console
 * screenshot). An earlier version rendered separate bordered per-month
 * calendar blocks instead; replaced because it doesn't match the
 * reference and needs far more space (12 month-blocks wrap into several
 * tall rows, where this layout fits a full year in ~740px of width and 7
 * cells of height).
 *
 * Always a trailing 12-month frame ending at endDate's own month,
 * regardless of how narrow the actual searched/filtered range is (another
 * confirmed Zerodha behavior) - days outside the real fetched range still
 * render, just very faint, so the frame's size never jumps around between
 * a 7-day and a 90-day search.
 */

function calendarHeatmapUTCDateStr(year, month, day) {
    var d = new Date(Date.UTC(year, month, day));
    return d.toISOString().split('T')[0];
}

function calendarHeatmapAddDays(dateStr, delta) {
    var parts = dateStr.split('-').map(Number);
    var dt = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    dt.setUTCDate(dt.getUTCDate() + delta);
    return dt.toISOString().split('T')[0];
}

function calendarHeatmapMonthShortLabel(year, month) {
    return new Date(Date.UTC(year, month, 1)).toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
}

// Continuous week-column grid for the trailing 12 months ending at
// endDate's month. Weeks start on Sunday; the first/last columns are
// padded with `null` cells outside the actual frame so every column has
// exactly 7 entries. A month label is emitted for the first column in
// which that month's days appear.
function calendarHeatmapBuildColumns(endDate) {
    var eParts = endDate.split('-').map(Number);
    var ey = eParts[0], em = eParts[1];
    var frameEnd = new Date(Date.UTC(ey, em, 0)).toISOString().split('T')[0]; // last day of endDate's month

    var frameStartIdx = ey * 12 + (em - 1) - 11;
    var frameStartYear = Math.floor(frameStartIdx / 12);
    var frameStartMonth = ((frameStartIdx % 12) + 12) % 12;
    var frameStart = calendarHeatmapUTCDateStr(frameStartYear, frameStartMonth, 1);

    var frameStartWeekday = new Date(frameStart + 'T00:00:00Z').getUTCDay();
    var gridStart = calendarHeatmapAddDays(frameStart, -frameStartWeekday);

    var weeks = [];
    var monthLabels = [];
    var lastLabeledMonth = '';
    var cursor = gridStart;
    var col = 0;

    while (cursor <= frameEnd) {
        var week = [];
        var monthOfLastRealDay = '';
        for (var row = 0; row < 7; row++) {
            if (cursor < frameStart || cursor > frameEnd) {
                week.push(null);
            } else {
                week.push(cursor);
                monthOfLastRealDay = cursor.slice(0, 7); // YYYY-MM
            }
            cursor = calendarHeatmapAddDays(cursor, 1);
        }
        if (monthOfLastRealDay && monthOfLastRealDay !== lastLabeledMonth) {
            var mParts = monthOfLastRealDay.split('-').map(Number);
            monthLabels.push({ col: col, label: calendarHeatmapMonthShortLabel(mParts[0], mParts[1] - 1) });
            lastLabeledMonth = monthOfLastRealDay;
        }
        weeks.push(week);
        col += 1;
    }

    return { weeks: weeks, monthLabels: monthLabels };
}

var CALENDAR_HEATMAP_CELL = 11;
var CALENDAR_HEATMAP_GAP = 3;
var CALENDAR_HEATMAP_STEP = CALENDAR_HEATMAP_CELL + CALENDAR_HEATMAP_GAP;

/**
 * Renders a calendar heat map into the element with id `containerId`.
 * days: [{date: 'YYYY-MM-DD', value: number, tooltip: string}]
 * colorFor: (value, maxAbs) => CSS color string
 */
function renderCalendarHeatmap(containerId, days, startDate, endDate, colorFor) {
    var container = document.getElementById(containerId);
    if (!container) return;

    var dayMap = {};
    var maxAbs = 1;
    days.forEach(function (d) {
        dayMap[d.date] = d;
        maxAbs = Math.max(maxAbs, Math.abs(d.value));
    });

    var built = calendarHeatmapBuildColumns(endDate);
    var weeks = built.weeks;
    var monthLabels = built.monthLabels;

    var html = '<div class="inline-flex flex-col gap-1">';
    html += '<div class="flex" style="gap:' + CALENDAR_HEATMAP_GAP + 'px">';
    weeks.forEach(function (week) {
        html += '<div class="flex flex-col" style="gap:' + CALENDAR_HEATMAP_GAP + 'px">';
        week.forEach(function (dateStr) {
            if (!dateStr) {
                html += '<div style="width:' + CALENDAR_HEATMAP_CELL + 'px;height:' + CALENDAR_HEATMAP_CELL + 'px"></div>';
                return;
            }
            var inRange = dateStr >= startDate && dateStr <= endDate;
            var entry = inRange ? dayMap[dateStr] : undefined;
            var bg = !inRange
                ? 'rgba(148, 163, 184, 0.08)'
                : entry ? colorFor(entry.value, maxAbs) : 'rgba(148, 163, 184, 0.15)';
            var title = inRange ? (entry ? entry.tooltip : (dateStr + ': no data')) : '';
            html += '<div class="rounded-sm" style="width:' + CALENDAR_HEATMAP_CELL + 'px;height:' + CALENDAR_HEATMAP_CELL + 'px;background-color:' + bg + '" title="' + title.replace(/"/g, '&quot;') + '"></div>';
        });
        html += '</div>';
    });
    html += '</div>';

    html += '<div class="relative h-4" style="width:' + (weeks.length * CALENDAR_HEATMAP_STEP) + 'px">';
    monthLabels.forEach(function (m) {
        html += '<span class="absolute text-[9px] text-base-content/60" style="left:' + (m.col * CALENDAR_HEATMAP_STEP) + 'px">' + m.label + '</span>';
    });
    html += '</div>';
    html += '</div>';

    container.innerHTML = html;
}

// Green/red-by-realized-P&L, matching OpenAlgo's PnlHistory.tsx pnlHeatColor.
function pnlHeatColor(value, maxAbs) {
    if (value === 0) return 'rgba(148, 163, 184, 0.3)';
    var intensity = Math.min(Math.abs(value) / maxAbs, 1);
    var alpha = 0.15 + intensity * 0.75;
    return value > 0 ? 'rgba(34, 197, 94, ' + alpha + ')' : 'rgba(239, 68, 68, ' + alpha + ')';
}

// Blue-by-trade-count, matching OpenAlgo's TradeBook.tsx tradeCountHeatColor.
function tradeCountHeatColor(value, maxAbs) {
    if (value <= 0) return 'rgba(148, 163, 184, 0.12)';
    var intensity = Math.min(value / maxAbs, 1);
    var alpha = 0.2 + intensity * 0.7;
    return 'rgba(59, 130, 246, ' + alpha + ')';
}
