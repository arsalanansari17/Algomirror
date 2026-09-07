/*
 * Shared calendar heat map renderer (fork-only P&L feature).
 * Ports frontend/src/components/reports/CalendarHeatmap.tsx from the
 * OpenAlgo React app to vanilla JS - since AlgoMirror's pages are
 * server-rendered + vanilla JS, not React. Used by both P&L History
 * (green/red by realized P&L) and Trade Book (blue by trade count) - each
 * page supplies its own `days` array and `colorFor` function; the layout
 * itself is identical.
 *
 * Layout: 12 discrete month blocks (each its own small grid of week-
 * columns, Sun-Sat as rows, no weekday header), spread across the full
 * container width with the gaps between them growing to fill it -
 * confirmed against a real Zerodha Console screenshot, which shows
 * visible whitespace *between* months (not one continuous flowing strip)
 * and the whole row stretched to fill its pane rather than sitting
 * compact on the left. An earlier version tried a true continuous
 * GitHub-contributions-style strip (weeks shared across month
 * boundaries, no gaps) - replaced because side-by-side comparison with
 * the reference showed Zerodha's months are visually distinct blocks.
 *
 * Always a trailing 12-month frame ending at endDate's own month,
 * regardless of how narrow the actual searched/filtered range is
 * (confirmed Zerodha behavior) - days outside the real fetched range
 * still render, just very faint, so the frame's size never jumps around
 * between a 7-day and a 90-day search.
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

// One month's own week-columns, padded to whole weeks at both ends (like
// a mini calendar) but not sharing columns with neighboring months - each
// group is a self-contained block. Trailing 12 months ending at endDate's
// own month.
function calendarHeatmapBuildMonthGroups(endDate) {
    var eParts = endDate.split('-').map(Number);
    var ey = eParts[0], em = eParts[1];
    var endIdx = ey * 12 + (em - 1);
    var startIdx = endIdx - 11;

    var groups = [];
    for (var idx = startIdx; idx <= endIdx; idx++) {
        var year = Math.floor(idx / 12);
        var month = ((idx % 12) + 12) % 12;
        var firstOfMonth = calendarHeatmapUTCDateStr(year, month, 1);
        var daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
        var lastOfMonth = calendarHeatmapUTCDateStr(year, month, daysInMonth);
        var firstWeekday = new Date(firstOfMonth + 'T00:00:00Z').getUTCDay();
        var gridStart = calendarHeatmapAddDays(firstOfMonth, -firstWeekday);

        var weeks = [];
        var cursor = gridStart;
        while (cursor <= lastOfMonth) {
            var week = [];
            for (var row = 0; row < 7; row++) {
                week.push(cursor >= firstOfMonth && cursor <= lastOfMonth ? cursor : null);
                cursor = calendarHeatmapAddDays(cursor, 1);
            }
            weeks.push(week);
        }

        groups.push({ label: calendarHeatmapMonthShortLabel(year, month), weeks: weeks });
    }
    return groups;
}

var CALENDAR_HEATMAP_CELL = 9;
var CALENDAR_HEATMAP_GAP = 2;

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

    var groups = calendarHeatmapBuildMonthGroups(endDate);

    var html = '<div class="flex justify-between w-full">';
    groups.forEach(function (group) {
        html += '<div class="flex flex-col items-center gap-1">';
        html += '<div class="flex" style="gap:' + CALENDAR_HEATMAP_GAP + 'px">';
        group.weeks.forEach(function (week) {
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
        html += '<span class="text-[9px] text-base-content/60 whitespace-nowrap">' + group.label + '</span>';
        html += '</div>';
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
