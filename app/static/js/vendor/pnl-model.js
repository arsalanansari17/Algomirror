/*
 * OpenAlgo P&L model, vendored (window.PnlModel). GENERATED - do not edit by hand.
 * Source: openalgo frontend/src/lib/pnlModel.ts, pnlCurve.ts, pnlBuckets.ts, pnlPalette.ts
 * at fork commit 070f1007e, bundled with rolldown (IIFE, no minify).
 * Regenerate from the openalgo repo when those files change, so AlgoMirror keeps the same numbers.
 */
var PnlModel = (function(exports) {

Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });

//#region src/lib/pnlCurve.ts
/**
	* Pure maths for the P&L Curve page (fork-only, see SKYSHIELD_PATCHES.md):
	* daily and cumulative realized P&L, drawdown, summary statistics and the
	* monthly table, from the closed lots GET /api/v1/pnl/history returns. No I/O
	* and no React, so every figure on the page is covered by tests.
	*
	* Everything is by the day a lot was closed out (its exit date), the same
	* basis as the P&L History day-wise table. A lot's strategy is the strategy
	* of the fill that opened it; a lot with none is "Untagged".
	*/
	const UNTAGGED = "Untagged";
	function strategyOf(lot) {
		return lot.strategy || "Untagged";
	}
	function dailySeries(lots) {
		const perDay = /* @__PURE__ */ new Map();
		for (const lot of lots) {
			const date = lot.exit_timestamp.slice(0, 10);
			const strategy = strategyOf(lot);
			const day = perDay.get(date) ?? /* @__PURE__ */ new Map();
			day.set(strategy, (day.get(strategy) ?? 0) + lot.realized_pnl);
			perDay.set(date, day);
		}
		const dates = Array.from(perDay.keys()).sort();
		const names = /* @__PURE__ */ new Set();
		for (const day of perDay.values()) for (const name of day.keys()) names.add(name);
		const byStrategy = /* @__PURE__ */ new Map();
		for (const name of names) byStrategy.set(name, dates.map((date) => perDay.get(date)?.get(name) ?? 0));
		return {
			dates,
			total: dates.map((date) => {
				let sum = 0;
				for (const value of perDay.get(date)?.values() ?? []) sum += value;
				return sum;
			}),
			byStrategy
		};
	}
	function cumulative(daily) {
		let running = 0;
		return daily.map((value) => {
			running += value;
			return running;
		});
	}
	function dayDiff(from, to) {
		return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 864e5);
	}
	/** The curve starts at zero before the first date, so the first peak is zero. */
	function drawdown(dates, cum) {
		const series = [];
		let peak = 0;
		let peakDate = null;
		let worst = 0;
		let worstPeakDate = null;
		let worstPeakValue = 0;
		let worstTroughIdx = -1;
		cum.forEach((value, i) => {
			if (value > peak) {
				peak = value;
				peakDate = dates[i];
			}
			const depth = value - peak;
			series.push(depth);
			if (depth < worst) {
				worst = depth;
				worstPeakDate = peakDate;
				worstPeakValue = peak;
				worstTroughIdx = i;
			}
		});
		if (worstTroughIdx < 0) return {
			series,
			max: {
				depth: 0,
				peakDate: null,
				troughDate: null,
				recoveryDate: null,
				days: 0
			}
		};
		let recoveryDate = null;
		for (let i = worstTroughIdx + 1; i < cum.length; i++) if (cum[i] >= worstPeakValue) {
			recoveryDate = dates[i];
			break;
		}
		const startDate = worstPeakDate ?? dates[0];
		const endDate = recoveryDate ?? dates[dates.length - 1];
		return {
			series,
			max: {
				depth: worst,
				peakDate: worstPeakDate,
				troughDate: dates[worstTroughIdx],
				recoveryDate,
				days: dayDiff(startDate, endDate)
			}
		};
	}
	/** Where the curve stands now against its own running peak. */
	function currentDrawdown(dates, cum) {
		let peak = 0;
		let peakDate = null;
		cum.forEach((value, i) => {
			if (value > peak) {
				peak = value;
				peakDate = dates[i];
			}
		});
		if (cum.length === 0) return {
			depth: 0,
			peakValue: 0,
			peakDate: null,
			daysSincePeak: 0,
			atHigh: true
		};
		const depth = cum[cum.length - 1] - peak;
		const lastDate = dates[dates.length - 1];
		const from = peakDate ?? dates[0];
		return {
			depth,
			peakValue: peak,
			peakDate,
			daysSincePeak: depth < 0 ? dayDiff(from, lastDate) : 0,
			atHigh: depth >= 0
		};
	}
	/** The deepest drawdown seen so far on each date (a running minimum, never rises). */
	function runningMaxDrawdown(series) {
		let worst = 0;
		return series.map((value) => {
			if (value < worst) worst = value;
			return worst;
		});
	}
	function stats(dates, daily) {
		let netPnl = 0;
		let winSum = 0;
		let lossSum = 0;
		let winDays = 0;
		let lossDays = 0;
		let best = null;
		let worst = null;
		let winStreak = 0;
		let lossStreak = 0;
		let longestWin = 0;
		let longestLoss = 0;
		daily.forEach((value, i) => {
			netPnl += value;
			if (best === null || value > best.value) best = {
				date: dates[i],
				value
			};
			if (worst === null || value < worst.value) worst = {
				date: dates[i],
				value
			};
			if (value > 0) {
				winDays += 1;
				winSum += value;
				winStreak += 1;
				lossStreak = 0;
			} else if (value < 0) {
				lossDays += 1;
				lossSum += value;
				lossStreak += 1;
				winStreak = 0;
			} else {
				winStreak = 0;
				lossStreak = 0;
			}
			longestWin = Math.max(longestWin, winStreak);
			longestLoss = Math.max(longestLoss, lossStreak);
		});
		const decided = winDays + lossDays;
		return {
			netPnl,
			activeDays: daily.length,
			winDays,
			lossDays,
			winRate: decided > 0 ? winDays / decided : null,
			avgWinDay: winDays > 0 ? winSum / winDays : null,
			avgLossDay: lossDays > 0 ? lossSum / lossDays : null,
			profitFactor: lossDays > 0 ? winSum / Math.abs(lossSum) : null,
			bestDay: best,
			worstDay: worst,
			longestWinStreak: longestWin,
			longestLossStreak: longestLoss
		};
	}
	function monthly(dates, daily) {
		const byYear = /* @__PURE__ */ new Map();
		dates.forEach((date, i) => {
			const year = Number(date.slice(0, 4));
			const month = Number(date.slice(5, 7)) - 1;
			const row = byYear.get(year) ?? new Array(12).fill(null);
			row[month] = (row[month] ?? 0) + daily[i];
			byYear.set(year, row);
		});
		return Array.from(byYear.entries()).sort((a, b) => a[0] - b[0]).map(([year, months]) => ({
			year,
			months,
			total: months.reduce((sum, value) => sum + (value ?? 0), 0)
		}));
	}
	/** One row per strategy, each judged on its own days. */
	function strategySummaries(series) {
		const rows = [];
		for (const [strategy, daily] of series.byStrategy) {
			const dates = [];
			const active = [];
			daily.forEach((value, i) => {
				if (value !== 0) {
					dates.push(series.dates[i]);
					active.push(value);
				}
			});
			const summary = stats(dates, active);
			rows.push({
				strategy,
				netPnl: summary.netPnl,
				maxDrawdown: drawdown(dates, cumulative(active)).max.depth,
				winRate: summary.winRate,
				profitFactor: summary.profitFactor,
				activeDays: summary.activeDays
			});
		}
		return rows.sort((a, b) => b.netPnl - a.netPnl);
	}
	const OTHER_STRATEGY = "Other";
	/**
	* Keep the first `maxNames` strategies (sorted by name) and fold the rest into
	* "Other"; "Untagged" stays its own series. Returns the kept names in colour
	* order and every series by display name.
	*/
	function foldCurveStrategies(byStrategy, maxNames) {
		const all = Object.keys(byStrategy).filter((n) => n !== UNTAGGED).sort();
		const kept = all.slice(0, maxNames);
		const byName = /* @__PURE__ */ new Map();
		const add = (name, series) => {
			const existing = byName.get(name);
			if (!existing) {
				byName.set(name, {
					realized: [...series.realized],
					unrealized: [...series.unrealized]
				});
				return;
			}
			series.realized.forEach((v, i) => {
				existing.realized[i] += v;
			});
			series.unrealized.forEach((v, i) => {
				existing.unrealized[i] += v;
			});
		};
		for (const name of all) add(kept.includes(name) ? name : OTHER_STRATEGY, byStrategy[name]);
		if (byStrategy["Untagged"]) add(UNTAGGED, byStrategy[UNTAGGED]);
		return {
			names: kept,
			byName
		};
	}
	/** One strategy's daily change for the chosen mode; cumulating it gives the curve. */
	function dailyChange(series, mode) {
		return series.realized.map((realized, i) => {
			const step = series.unrealized[i] - (i > 0 ? series.unrealized[i - 1] : 0);
			if (mode === "realized") return realized;
			if (mode === "unrealized") return step;
			return realized + step;
		});
	}
	/**
	* The page's DailySeries for a curve: total and per strategy as daily changes,
	* so cumulative(), drawdown(), stats() and monthly() work on it unchanged.
	* `include` picks the selected strategies; the total is theirs alone.
	*/
	function curveSeries(dates, byName, mode, include = () => true) {
		const total = dates.map(() => 0);
		const byStrategy = /* @__PURE__ */ new Map();
		for (const [name, series] of byName) {
			if (!include(name)) continue;
			const change = dailyChange(series, mode);
			byStrategy.set(name, change);
			change.forEach((v, i) => {
				total[i] += v;
			});
		}
		return {
			dates,
			total,
			byStrategy
		};
	}

//#endregion
//#region src/lib/pnlModel.ts
/** Marks "no strategy selected" inside the inclusion list. */
	const NO_STRATEGY = "∅";
	const EMPTY = {
		dates: [],
		total: [],
		byStrategy: /* @__PURE__ */ new Map()
	};
	function nameOf(strategy) {
		return strategy || "Untagged";
	}
	function buildPnlModel(input) {
		const { closedTrades, openPositions, curve, filters, maxStrategies } = input;
		const hasCurve = !!curve && input.segment === "equity";
		const mode = hasCurve ? input.pnlType : "realized";
		const selectedNames = filters.strategies;
		const isSelected = (name) => selectedNames.length === 0 || selectedNames.includes(name);
		const needle = filters.symbol.trim().toUpperCase();
		const matchesBase = (symbol, exchange, product) => {
			if (needle && !symbol.toUpperCase().includes(needle)) return false;
			if (filters.exchanges.length > 0 && !filters.exchanges.includes(exchange)) return false;
			if (filters.products.length > 0 && !(product && filters.products.includes(product))) return false;
			return true;
		};
		const lots = closedTrades.filter((t) => matchesBase(t.symbol, t.exchange, t.product) && isSelected(nameOf(t.strategy)));
		const open = openPositions.filter((p) => matchesBase(p.symbol, p.exchange, p.product) && isSelected(nameOf(p.strategy)));
		const strategyOptions = /* @__PURE__ */ new Set();
		for (const t of closedTrades) strategyOptions.add(nameOf(t.strategy));
		for (const p of openPositions) strategyOptions.add(nameOf(p.strategy));
		if (curve) for (const name of Object.keys(curve.by_strategy)) strategyOptions.add(name);
		const options = {
			strategies: Array.from(strategyOptions).sort(),
			exchanges: Array.from(new Set([...closedTrades.map((t) => t.exchange), ...openPositions.map((p) => p.exchange)])).sort(),
			products: Array.from(new Set([...closedTrades.map((t) => t.product), ...openPositions.map((p) => p.product)].filter((p) => !!p))).sort()
		};
		const curveIgnoresFilters = hasCurve && (filters.exchanges.length > 0 || filters.products.length > 0);
		if (hasCurve && curve) {
			const folded = foldCurveStrategies(curve.by_strategy, maxStrategies);
			const present = new Set(folded.byName.keys());
			const strategyNames = [
				...folded.names,
				...present.has("Other") ? [OTHER_STRATEGY] : [],
				...present.has("Untagged") ? [UNTAGGED] : []
			];
			const allSeries = curveSeries(curve.dates, folded.byName, mode);
			const series = curveSeries(curve.dates, folded.byName, mode, isSelected);
			const realizedSeries = curveSeries(curve.dates, folded.byName, "realized", isSelected);
			const unrealizedLevel = cumulative(curveSeries(curve.dates, folded.byName, "unrealized", isSelected).total);
			const perStrategy = /* @__PURE__ */ new Map();
			for (const [name, s] of folded.byName) {
				if (!isSelected(name)) continue;
				perStrategy.set(name, {
					realized: s.realized.reduce((a, b) => a + b, 0),
					unrealized: s.unrealized.length ? s.unrealized[s.unrealized.length - 1] : 0
				});
			}
			return {
				mode,
				hasCurve: true,
				strategyNames,
				coloured: folded.names,
				allSeries,
				series,
				realizedSeries,
				perStrategy,
				splitLines: mode === "combined" ? {
					realized: cumulative(realizedSeries.total),
					unrealized: unrealizedLevel
				} : null,
				lots,
				open,
				split: {
					realized: realizedSeries.total.reduce((a, b) => a + b, 0),
					unrealized: unrealizedLevel.length ? unrealizedLevel[unrealizedLevel.length - 1] : 0
				},
				options,
				isSelected,
				curveIgnoresFilters
			};
		}
		const baseLots = closedTrades.filter((t) => matchesBase(t.symbol, t.exchange, t.product)).map((t) => ({
			exit_timestamp: t.exit_timestamp,
			realized_pnl: t.realized_pnl,
			strategy: t.strategy,
			symbol: t.symbol,
			exchange: t.exchange,
			product: t.product
		}));
		const kept = Array.from(new Set(baseLots.map(strategyOf))).filter((n) => n !== UNTAGGED).sort().slice(0, maxStrategies);
		const foldedLots = baseLots.map((lot) => {
			const name = strategyOf(lot);
			return name === "Untagged" || kept.includes(name) ? lot : {
				...lot,
				strategy: OTHER_STRATEGY
			};
		});
		const presentNames = new Set(foldedLots.map(strategyOf));
		const strategyNames = [
			...kept,
			...presentNames.has("Other") ? [OTHER_STRATEGY] : [],
			...presentNames.has("Untagged") ? [UNTAGGED] : []
		];
		const allSeries = foldedLots.length ? dailySeries(foldedLots) : EMPTY;
		const selected = foldedLots.filter((lot) => isSelected(strategyOf(lot)));
		const series = selected.length ? dailySeries(selected) : EMPTY;
		const foldName = (strategy) => {
			const name = nameOf(strategy);
			return name === "Untagged" || kept.includes(name) ? name : OTHER_STRATEGY;
		};
		const perStrategy = /* @__PURE__ */ new Map();
		for (const [name, daily] of series.byStrategy) perStrategy.set(name, {
			realized: daily.reduce((a, b) => a + b, 0),
			unrealized: input.unrealizedAvailable ? 0 : null
		});
		if (input.unrealizedAvailable) for (const p of open) {
			const row = perStrategy.get(foldName(p.strategy));
			if (row) row.unrealized = (row.unrealized ?? 0) + (p.unrealized_pnl ?? 0);
		}
		const unrealized = input.unrealizedAvailable ? open.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0) : null;
		return {
			mode: "realized",
			hasCurve: false,
			strategyNames,
			coloured: kept,
			allSeries,
			series,
			realizedSeries: series,
			perStrategy,
			splitLines: null,
			lots,
			open,
			split: {
				realized: series.total.reduce((a, b) => a + b, 0),
				unrealized
			},
			options,
			isSelected,
			curveIgnoresFilters: false
		};
	}

//#endregion
//#region src/lib/pnlBuckets.ts
	const MONTHS = [
		"Jan",
		"Feb",
		"Mar",
		"Apr",
		"May",
		"Jun",
		"Jul",
		"Aug",
		"Sep",
		"Oct",
		"Nov",
		"Dec"
	];
	function parts(date) {
		const [y, m, d] = date.split("-").map(Number);
		return [
			y,
			m,
			d
		];
	}
	/** The Monday of the ISO week containing `date`. */
	function weekStart(date) {
		const [y, m, d] = parts(date);
		const dt = new Date(Date.UTC(y, m - 1, d));
		const offset = (dt.getUTCDay() + 6) % 7;
		dt.setUTCDate(dt.getUTCDate() - offset);
		return dt.toISOString().slice(0, 10);
	}
	function label(unit, key) {
		if (unit === "day") return key;
		if (unit === "week") {
			const [, m, d] = parts(key);
			return `Week of ${String(d).padStart(2, "0")} ${MONTHS[m - 1]}`;
		}
		const [y, m] = parts(`${key}-01`);
		return `${MONTHS[m - 1]} ${y}`;
	}
	function keyOf(unit, date) {
		if (unit === "day") return {
			key: date,
			start: date
		};
		if (unit === "week") {
			const start = weekStart(date);
			return {
				key: start,
				start
			};
		}
		const key = date.slice(0, 7);
		return {
			key,
			start: `${key}-01`
		};
	}
	/**
	* Group an ascending daily series into buckets. Idle days are simply absent, so
	* a bucket with no activity does not appear.
	*/
	function bucketize(dates, values, unit) {
		const out = [];
		const index = /* @__PURE__ */ new Map();
		dates.forEach((date, i) => {
			const { key, start } = keyOf(unit, date);
			let bucket = index.get(key);
			if (!bucket) {
				bucket = {
					key,
					start,
					label: label(unit, key),
					value: 0,
					days: 0,
					cumulative: 0
				};
				index.set(key, bucket);
				out.push(bucket);
			}
			bucket.value += values[i] ?? 0;
			bucket.days += 1;
		});
		let running = 0;
		for (const bucket of out) {
			running += bucket.value;
			bucket.cumulative = running;
		}
		return out;
	}

//#endregion
//#region src/lib/pnlPalette.ts
/**
	* Colours for the P&L page's canvases (fork-only). A canvas cannot read CSS
	* tokens, so the values are literal. Strategies keep a colour by position in
	* the sorted name list and never cycle; Other and Untagged are neutral.
	*/
	const SERIES_COLORS = {
		light: [
			"#2a78d6",
			"#eb6834",
			"#1baf7a",
			"#eda100",
			"#e87ba4",
			"#008300",
			"#4a3aa7",
			"#e34948"
		],
		dark: [
			"#3987e5",
			"#d95926",
			"#199e70",
			"#c98500",
			"#d55181",
			"#008300",
			"#9085e9",
			"#e66767"
		]
	};
	const INK = {
		light: {
			total: "#0b0b0b",
			untagged: "#8a8984",
			other: "#6b6a66",
			text: "#52514e"
		},
		dark: {
			total: "#ffffff",
			untagged: "#8f8e86",
			other: "#a9a89f",
			text: "#c3c2b7"
		}
	};
	const MAX_STRATEGY_SERIES = SERIES_COLORS.light.length;
	const REALIZED_COLOR = "#16a34a";
	const UNREALIZED_COLOR = "#d97706";
	function positive(isDark) {
		return isDark ? "#22c55e" : "#16a34a";
	}
	function negative(isDark) {
		return isDark ? "#ef4444" : "#dc2626";
	}
	/** The colour of a strategy name given the ordered coloured names. */
	function strategyColor(name, coloured, isDark) {
		const ink = isDark ? INK.dark : INK.light;
		if (name === "Untagged") return ink.untagged;
		const index = coloured.indexOf(name);
		if (index < 0) return ink.other;
		return (isDark ? SERIES_COLORS.dark : SERIES_COLORS.light)[index] ?? ink.other;
	}
	/** Heat colour for a day's realized P&L (matches Console's calendar). */
	function pnlHeatColor(value, maxAbs) {
		if (value === 0) return "rgba(148, 163, 184, 0.3)";
		const alpha = .15 + (maxAbs > 0 ? Math.min(Math.abs(value) / maxAbs, 1) : 0) * .75;
		return value > 0 ? `rgba(34, 197, 94, ${alpha})` : `rgba(239, 68, 68, ${alpha})`;
	}

//#endregion
exports.INK = INK;
exports.MAX_STRATEGY_SERIES = MAX_STRATEGY_SERIES;
exports.NO_STRATEGY = NO_STRATEGY;
exports.REALIZED_COLOR = REALIZED_COLOR;
exports.SERIES_COLORS = SERIES_COLORS;
exports.UNREALIZED_COLOR = UNREALIZED_COLOR;
exports.UNTAGGED = UNTAGGED;
exports.bucketize = bucketize;
exports.buildPnlModel = buildPnlModel;
exports.cumulative = cumulative;
exports.currentDrawdown = currentDrawdown;
exports.drawdown = drawdown;
exports.monthly = monthly;
exports.negative = negative;
exports.pnlHeatColor = pnlHeatColor;
exports.positive = positive;
exports.runningMaxDrawdown = runningMaxDrawdown;
exports.stats = stats;
exports.strategyColor = strategyColor;
exports.strategySummaries = strategySummaries;
exports.weekStart = weekStart;
return exports;
})({});