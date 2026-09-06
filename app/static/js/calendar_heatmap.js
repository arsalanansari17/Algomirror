/*
 * Shared calendar-grid heat map renderer (fork-only P&L feature).
 * Ports frontend/src/components/reports/CalendarHeatmap.tsx from the
 * OpenAlgo React app to vanilla JS - same month-enumeration/grid-cell
 * logic, since AlgoMirror's pages are server-rendered + vanilla JS, not
 * React. Used by both P&L History (green/red by realized P&L) and Trade
 * Book (blue by trade count) - each page supplies its own `days` array
 * and `colorFor` function; the grid layout itself is identical.
 */

function calendarHeatmapEnumerateMonths(startDate, endDate) {
    var sParts = startDate.split('-').map(Number);
    var eParts = endDate.split('-').map(Number);
    var months = [];
    var y = sParts[0], m = sParts[1] - 1;
    var endIdx = eParts[0] * 12 + (eParts[1] - 1);
    while (y * 12 + m <= endIdx) {
        months.push({ year: y, month: m });
        m += 1;
        if (m > 11) { m = 0; y += 1; }
    }
    return months;
}

function calendarHeatmapUTCDateStr(year, month, day) {
    var d = new Date(Date.UTC(year, month, day));
    return d.toISOString().split('T')[0];
}

var CALENDAR_HEATMAP_WEEKDAY_LABELS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

function renderCalendarHeatmapMonth(year, month, dayMap, maxAbs, startDate, endDate, colorFor) {
    var firstWeekday = new Date(Date.UTC(year, month, 1)).getUTCDay();
    var daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
    var cells = [];
    for (var i = 0; i < firstWeekday; i++) cells.push(null);
    for (var day = 1; day <= daysInMonth; day++) {
        cells.push({ dateStr: calendarHeatmapUTCDateStr(year, month, day), day: day });
    }
    while (cells.length % 7 !== 0) cells.push(null);

    var monthLabel = new Date(Date.UTC(year, month, 1)).toLocaleString('en-US', {
        month: 'short', year: 'numeric', timeZone: 'UTC',
    });

    var html = '<div class="flex flex-col items-center gap-1">';
    html += '<p class="text-xs font-medium text-base-content/60">' + monthLabel + '</p>';
    html += '<div class="grid grid-cols-7 gap-0.5">';
    CALENDAR_HEATMAP_WEEKDAY_LABELS.forEach(function (label) {
        html += '<div class="w-6 h-3 text-[9px] leading-3 text-center text-base-content/60">' + label + '</div>';
    });
    cells.forEach(function (cell) {
        if (!cell) {
            html += '<div class="w-6 h-6"></div>';
            return;
        }
        var inRange = cell.dateStr >= startDate && cell.dateStr <= endDate;
        var entry = inRange ? dayMap[cell.dateStr] : undefined;
        var bg = !inRange
            ? 'transparent'
            : entry ? colorFor(entry.value, maxAbs) : 'rgba(148, 163, 184, 0.12)';
        var title = inRange ? (entry ? entry.tooltip : (cell.dateStr + ': no data')) : '';
        html += '<div class="w-6 h-6 rounded-sm border border-base-300 flex items-center justify-center text-[9px] text-base-content/60" '
            + 'style="background-color:' + bg + '" title="' + title.replace(/"/g, '&quot;') + '">'
            + (inRange ? cell.day : '') + '</div>';
    });
    html += '</div></div>';
    return html;
}

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

    var months = calendarHeatmapEnumerateMonths(startDate, endDate);
    var html = '<div class="flex flex-wrap gap-6">';
    months.forEach(function (m) {
        html += renderCalendarHeatmapMonth(m.year, m.month, dayMap, maxAbs, startDate, endDate, colorFor);
    });
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
