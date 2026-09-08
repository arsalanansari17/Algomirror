/*
 * Shared quick date-range presets (fork-only), ported from OpenAlgo's
 * frontend/src/lib/dateRangePresets.ts + DateRangePresets.tsx - see that
 * file for the full rationale. AlgoMirror's pages are server-rendered +
 * vanilla JS, not React, so this renders the chip row directly into a
 * container element instead of being a component.
 *
 * "Current week" is Monday of this week through today (not a rolling
 * 7-day window - that's the separate "Last 7 Days" preset). "Current
 * month" is the 1st of this month through today. Financial year follows
 * the Indian FY convention: Apr 1 - Mar 31. "Current FY" runs to today
 * (it isn't over yet); "Prev. FY" is the full closed year, Apr 1 to the
 * following Mar 31 - not truncated, since it already ended.
 */

// Deliberately NOT toISOString() - that converts to UTC, which rolls a
// local-midnight date (e.g. the 1st of the month, built via
// `new Date(year, month, day)`) back to the previous day for any
// timezone ahead of UTC, IST included. Building the string from local
// getters keeps every preset on the calendar day it actually means.
function dateRangePresetToDateStr(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
}

function dateRangePresetAddDays(base, delta) {
    var d = new Date(base);
    d.setDate(d.getDate() + delta);
    return d;
}

function dateRangePresetStartOfWeekMonday(base) {
    var day = base.getDay(); // 0=Sun..6=Sat
    var daysSinceMonday = day === 0 ? 6 : day - 1;
    return dateRangePresetAddDays(base, -daysSinceMonday);
}

function dateRangePresetStartOfMonth(base) {
    return new Date(base.getFullYear(), base.getMonth(), 1);
}

// The calendar year an Indian FY *starts* in - e.g. FY2026-27 (Apr 2026 -
// Mar 2027) has a start year of 2026. Before April, we're still in the FY
// that started the previous calendar year.
function dateRangePresetCurrentFYStartYear(base) {
    return base.getMonth() >= 3 ? base.getFullYear() : base.getFullYear() - 1;
}

var DATE_RANGE_PRESETS = [
    {
        key: 'current_week', label: 'Current Week', range: function () {
            var today = new Date();
            return { start: dateRangePresetToDateStr(dateRangePresetStartOfWeekMonday(today)), end: dateRangePresetToDateStr(today) };
        }
    },
    {
        key: 'current_month', label: 'Current Month', range: function () {
            var today = new Date();
            return { start: dateRangePresetToDateStr(dateRangePresetStartOfMonth(today)), end: dateRangePresetToDateStr(today) };
        }
    },
    {
        key: 'last_7_days', label: 'Last 7 Days', range: function () {
            var today = new Date();
            return { start: dateRangePresetToDateStr(dateRangePresetAddDays(today, -7)), end: dateRangePresetToDateStr(today) };
        }
    },
    {
        key: 'last_30_days', label: 'Last 30 Days', range: function () {
            var today = new Date();
            return { start: dateRangePresetToDateStr(dateRangePresetAddDays(today, -30)), end: dateRangePresetToDateStr(today) };
        }
    },
    {
        key: 'current_fy', label: 'Current FY', range: function () {
            var today = new Date();
            var fyStartYear = dateRangePresetCurrentFYStartYear(today);
            return { start: dateRangePresetToDateStr(new Date(fyStartYear, 3, 1)), end: dateRangePresetToDateStr(today) };
        }
    },
    {
        key: 'prev_fy', label: 'Prev. FY', range: function () {
            var today = new Date();
            var fyStartYear = dateRangePresetCurrentFYStartYear(today) - 1;
            return {
                start: dateRangePresetToDateStr(new Date(fyStartYear, 3, 1)),
                end: dateRangePresetToDateStr(new Date(fyStartYear + 1, 2, 31)),
            };
        }
    },
];

/**
 * Renders the chip row into the element with id `containerId`. Clicking a
 * chip calls onSelect(start, end, key) - the caller is responsible for
 * filling its own date inputs and re-fetching, then re-rendering this
 * with the new activeKey so the clicked chip stays highlighted.
 */
function renderDateRangePresets(containerId, activeKey, onSelect) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = DATE_RANGE_PRESETS.map(function (preset) {
        var cls = preset.key === activeKey ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-outline';
        return '<button type="button" class="' + cls + '" data-preset-key="' + preset.key + '">' + preset.label + '</button>';
    }).join('');
    Array.prototype.forEach.call(container.querySelectorAll('[data-preset-key]'), function (btn) {
        btn.addEventListener('click', function () {
            var key = btn.getAttribute('data-preset-key');
            var preset = DATE_RANGE_PRESETS.filter(function (p) { return p.key === key; })[0];
            var range = preset.range();
            onSelect(range.start, range.end, preset.key);
        });
    });
}
