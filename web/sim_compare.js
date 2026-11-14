/* CropMix Twin — comparison of Baseline, My scenario and Optimized (module 10, stage 6).
 *
 * All numbers come from sim_core.js: compareScenarios (the three scenarios under ONE climate and efficiency),
 * calculateChanges (differences) and calculateCropImpacts (per-crop contributions, inside compareScenarios).
 * Saving = (Baseline − Scenario) / Baseline × 100 %, river withdrawal; negative saving = more water than Baseline.
 * It is taken as −pct of sim_core's change (identical in floating point). Optimized structures are module 6
 * results for Cmean / E_base; under other conditions they are only re-evaluated, never re-optimized.
 * Pure helpers are exported for Node tests (tests/js/sim_compare.test.js); the DOM part runs in browsers.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CropMixCompare = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const LEVELS = Object.freeze(["plant", "field", "river"]);
  const LEVEL_LABELS = Object.freeze({ plant: "Crop need", field: "At the field", river: "River withdrawal" });
  const SCENARIOS = Object.freeze(["baseline", "my", "optimized"]);

  // ------------------------------------------------------------------------------------------ pure helpers

  /** Saving (%) from a sim_core change whose reference is Baseline: (B − S) / B × 100. Null when B = 0. */
  function savingPct(change) {
    if (change.pct === null || change.pct === undefined) return null;
    const s = -change.pct;
    return s === 0 ? 0 : s;
  }

  /** One sim_core.compareScenarios call + My vs Optimized difference + savings on all levels. */
  function compareAll(core, myAreas, presetId, cond) {
    const cmp = core.compareScenarios(myAreas, presetId, cond.climate, cond.efficiency);
    const myVsOptimized = core.calculateChanges(cmp.scenarios.optimized, cmp.scenarios.my);
    const saving = { my: {}, optimized: {} };
    for (const who of ["my", "optimized"]) for (const l of LEVELS) saving[who][l] = savingPct(cmp.changes[who][l]);
    return { cond: { climate: cond.climate, efficiency: cond.efficiency }, cmp, myVsOptimized, saving };
  }

  /**
   * Range of the river-withdrawal saving of My scenario and Optimized over the given conditions
   * (normally all 17 climates × 36 efficiencies). Each condition is evaluated by sim_core exactly as compareAll.
   */
  function savingRange(core, combos, myAreas, presetId) {
    const acc = { my: null, optimized: null };
    for (const c of combos) {
      const r = compareAll(core, myAreas, presetId, c);
      for (const who of ["my", "optimized"]) {
        const v = r.saving[who].river;
        if (v === null) continue;
        const a = acc[who];
        if (!a) { acc[who] = { min: v, max: v, minAt: c, maxAt: c }; continue; }
        if (v < a.min) { a.min = v; a.minAt = c; }
        if (v > a.max) { a.max = v; a.maxAt = c; }
      }
    }
    return { n: combos.length, my: acc.my, optimized: acc.optimized };
  }

  const NICE_MANTISSAS = Object.freeze([1, 2, 2.5, 5, 7.5, 8, 10]);
  const TICK_STEPS = Object.freeze([0.5, 1, 2, 2.5, 5]);

  /** Smallest "nice" axis maximum (1, 2, 2.5, 5, 7.5, 8 × 10^n) at or above v — never below the data. */
  function niceMax(v) {
    if (!(v > 0)) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of NICE_MANTISSAS) if (m * p >= v) return m * p;
    return 10 * p;
  }

  /** 3–5 evenly spaced round ticks from 0 to max (e.g. 7.5 → 0, 2.5, 5, 7.5; 8 → 0, 2, 4, 6, 8). */
  function axisTicks(max) {
    const p = Math.pow(10, Math.floor(Math.log10(max)));
    for (const base of [p / 10, p]) {
      for (const s of TICK_STEPS) {
        const step = s * base;
        const n = max / step;
        if (Math.abs(n - Math.round(n)) < 1e-9 && n >= 3 && n <= 5) {
          return Array.from({ length: Math.round(n) + 1 }, (_, i) => +(i * step).toFixed(10));
        }
      }
    }
    return [0, max / 2, max];
  }

  // ------------------------------------------------------------------------------------------ DOM

  function h(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined) continue;
      if (k === "text") node.textContent = v;
      else if (k === "html") node.innerHTML = v;            // static icons only
      else if (k === "style") node.style.cssText = v;
      else node.setAttribute(k, v);
    }
    for (const c of [].concat(children || [])) if (c !== null && c !== undefined && c !== false) node.append(c);
    return node;
  }

  const WARN = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.8 15 14H1Z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M8 6v4M8 11.9v.1" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';
  const OK = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="m5 8.2 2 2 4-4.4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  /**
   * options: { sim, State (fmt), Cond, condOptions, onStartFromOptimized(presetId) }
   * render(result, presetId, constraintsOk, range) — result from compareAll; range from savingRange.
   */
  function createComparison(rootEl, options) {
    const { sim, State, Cond, condOptions } = options;
    const fmt = State.fmt;
    const crops = sim.crops;
    const presets = sim.optimized.presets;

    const condLine = h("p", { class: "cmp-conditions" });
    const banner = h("p", { class: "cmp-banner", role: "note", hidden: "" });
    const kpis = h("div", { class: "cmp-kpis" });
    const bars = h("div", { class: "cmp-bars", role: "img" });
    const diffTable = h("table", { class: "data-table cmp-table" });
    const diffCards = h("div", { class: "cmp-cards" });
    const rangeBox = h("div", { class: "cmp-range" });
    const contrib = h("div", { class: "cmp-contrib" });
    const startBtn = h("button", { type: "button", class: "tool-btn", text: "Start from Optimized" });
    startBtn.addEventListener("click", () => options.onStartFromOptimized(currentPreset));
    let currentPreset = null;

    rootEl.append(
      h("div", { class: "cmp-head" }, [
        h("p", { class: "kicker", text: "Comparison · whole region" }),
        h("h2", { id: "compare-title", text: "Scenario comparison" }),
        h("p", { class: "section-sub", text: "Baseline, My scenario and Optimized, all evaluated under the same climate and efficiency." }),
        condLine, banner,
      ]),
      kpis,
      h("div", { class: "cmp-grid" }, [
        h("section", { class: "cmp-block", "aria-labelledby": "cmp-bars-title" }, [
          h("h3", { class: "section-title", id: "cmp-bars-title", text: "Water by level, km³" }),
          h("ul", { class: "cmp-legend", "aria-label": "Scenario key" }, [
            h("li", {}, [h("span", { class: "key key-baseline", "aria-hidden": "true" }), "Baseline 2025"]),
            h("li", {}, [h("span", { class: "key key-my", "aria-hidden": "true" }), "My scenario"]),
            h("li", {}, [h("span", { class: "key key-optimized", "aria-hidden": "true" }), "Optimized"]),
          ]),
          bars,
        ]),
        h("section", { class: "cmp-block", "aria-labelledby": "cmp-range-title" }, [
          h("h3", { class: "section-title", id: "cmp-range-title", text: "Saving in river withdrawal" }),
          h("p", { class: "mini-note", text: "Saving = (Baseline − Scenario) / Baseline × 100 %, both under the same conditions. Positive: the scenario withdraws less water than Baseline; negative: it withdraws more." }),
          rangeBox,
        ]),
      ]),
      h("section", { class: "cmp-block", "aria-labelledby": "cmp-table-title" }, [
        h("h3", { class: "section-title", id: "cmp-table-title", text: "Differences between scenarios" }),
        h("p", { class: "mini-note", text: "Difference = second scenario − first, km³ and % of the first. Positive: more water." }),
        h("div", { class: "table-scroll" }, diffTable),
        diffCards,
      ]),
      h("section", { class: "cmp-block", "aria-labelledby": "cmp-contrib-title" }, [
        h("h3", { class: "section-title", id: "cmp-contrib-title", text: "Which crops drive the change in river withdrawal" }),
        h("p", { class: "mini-note", text: "Contribution of each crop = its area change × its coefficient under the selected conditions. Bars to the left: less water; to the right: more water." }),
        contrib,
      ]),
      h("section", { class: "cmp-block cmp-notes", "aria-labelledby": "cmp-notes-title" }, [
        h("h3", { class: "section-title", id: "cmp-notes-title", text: "How to read these results" }),
        h("ul", { class: "plain" }, NOTES.map((t) => h("li", { text: t }))),
      ]),
    );

    // ---------------------------------------------------------------- KPI strip
    function kpi(who, r, extra) {
      const sc = r.cmp.scenarios[who];
      const sv = who === "baseline" ? null : r.saving[who].river;
      const ch = who === "baseline" ? null : r.cmp.changes[who].river;
      const titles = { baseline: "Baseline 2025", my: "My scenario", optimized: `Optimized · ${presets[currentPreset].label}` };
      return h("div", { class: `kpi kpi-${who}` }, [
        h("p", { class: "kpi-title" }, [h("span", { class: `key key-${who}`, "aria-hidden": "true" }), titles[who]]),
        h("p", { class: "kpi-value" }, [h("span", { class: "kpi-num", text: fmt.km3(sc.km3.river) }), h("span", { class: "kpi-unit", text: "km³ river" })]),
        who === "baseline"
          ? h("p", { class: "kpi-sub", text: "Reference for savings" })
          : h("p", { class: "kpi-sub", "data-dir": sv === null || sv === 0 ? "0" : sv > 0 ? "down" : "up" },
              `Saving ${sv === null ? "—" : fmt.signedPct(sv)} · ${fmt.signedKm3(ch.abs_km3)} km³`),
        h("dl", { class: "kpi-levels" }, [
          h("dt", { text: "At the field" }), h("dd", { text: `${fmt.km3(sc.km3.field)} km³` }),
          h("dt", { text: "Crop need" }), h("dd", { text: `${fmt.km3(sc.km3.plant)} km³` }),
          h("dt", { text: "Sown area" }), h("dd", { text: `${fmt.ha(sc.totalArea)} ha` }),
        ]),
        extra || null,
      ]);
    }

    function renderKpis(r, constraintsOk) {
      const p = presets[currentPreset];
      const myStatus = h("p", { class: "kpi-status " + (constraintsOk ? "is-ok" : "is-bad") },
        [h("span", { class: "icon", html: constraintsOk ? OK : WARN }), constraintsOk ? `Within ${p.label} constraints` : `Outside ${p.label} constraints`]);
      const optNote = h("div", { class: "kpi-extra" }, [
        h("p", { class: "kpi-note", text: "Optimized for mean climate and baseline efficiencies (Cmean / E_base); re-evaluated here, not re-optimized." }),
        startBtn,
      ]);
      kpis.replaceChildren(kpi("baseline", r), kpi("my", r, myStatus), kpi("optimized", r, optNote));
    }

    // ---------------------------------------------------------------- grouped bars (one shared km³ axis)
    function renderBars(r) {
      // The largest of the 9 values sets the axis (river withdrawal is always the largest level).
      const max = niceMax(Math.max(...SCENARIOS.map((s) => r.cmp.scenarios[s].km3.river)));
      const ticks = axisTicks(max);
      const groups = LEVELS.slice().reverse().map((l) => h("div", { class: "bar-group" }, [
        h("span", { class: "bar-level", text: LEVEL_LABELS[l] }),
        h("div", { class: "bar-set" }, SCENARIOS.map((s) => {
          const v = r.cmp.scenarios[s].km3[l];
          return h("div", { class: "bar-row" }, [
            h("span", { class: "bar-track" }, h("span", { class: `bar bar-${s}`, style: `width: ${100 * v / max}%` })),
            h("span", { class: "bar-val", text: fmt.km3(v) }),
          ]);
        })),
      ]));
      const axis = h("div", { class: "bar-axis", "aria-hidden": "true" }, ticks.map((t) =>
        h("span", { style: `left: ${100 * t / max}%`, text: fmt.km3(t) })));
      bars.replaceChildren(...groups, h("div", { class: "bar-group axis-group" }, [h("span"), axis]));
      bars.setAttribute("aria-label", LEVELS.map((l) => `${LEVEL_LABELS[l]}: ` +
        SCENARIOS.map((s) => `${s === "my" ? "My scenario" : s === "baseline" ? "Baseline" : "Optimized"} ${fmt.km3(r.cmp.scenarios[s].km3[l])} km³`).join(", ")).join("; "));
    }

    // ---------------------------------------------------------------- difference table
    function diffCell(change) {
      return h("td", { class: "num" }, [h("span", { class: "diff-abs", text: `${fmt.signedKm3(change.abs_km3)}` }),
        h("span", { class: "diff-pct", text: fmt.signedPct(change.pct) })]);
    }
    function renderTable(r) {
      const head = h("thead", {}, h("tr", {}, [
        h("th", { scope: "col", text: "Level, km³" }),
        h("th", { scope: "col", class: "num", text: "Baseline" }), h("th", { scope: "col", class: "num", text: "My scenario" }),
        h("th", { scope: "col", class: "num", text: "Optimized" }),
        h("th", { scope: "col", class: "num", text: "My − Baseline" }), h("th", { scope: "col", class: "num", text: "Optimized − Baseline" }),
        h("th", { scope: "col", class: "num", text: "My − Optimized" }),
      ]));
      const body = h("tbody", {}, LEVELS.slice().reverse().map((l) => h("tr", {}, [
        h("th", { scope: "row", text: LEVEL_LABELS[l] }),
        ...SCENARIOS.map((s) => h("td", { class: "num", text: fmt.km3(r.cmp.scenarios[s].km3[l]) })),
        diffCell(r.cmp.changes.my[l]), diffCell(r.cmp.changes.optimized[l]), diffCell(r.myVsOptimized[l]),
      ])));
      diffTable.replaceChildren(h("caption", { class: "visually-hidden", text: "Water by level and differences between scenarios" }), head, body);

      // Phone layout (≤ 720 px, CSS switches): one card per level with the same 7 values and percentages.
      const pair = (label, change) => [h("dt", { text: label }),
        h("dd", {}, [h("span", { class: "diff-abs", text: `${fmt.signedKm3(change.abs_km3)} km³` }), h("span", { class: "diff-pct", text: fmt.signedPct(change.pct) })])];
      diffCards.replaceChildren(...LEVELS.slice().reverse().map((l) => h("section", { class: "cmp-card", "aria-label": LEVEL_LABELS[l] }, [
        h("h4", { class: "cmp-card-title", text: `${LEVEL_LABELS[l]}, km³` }),
        h("dl", { class: "cmp-card-values" }, SCENARIOS.flatMap((s) => [
          h("dt", {}, [h("span", { class: `key key-${s}`, "aria-hidden": "true" }), s === "baseline" ? "Baseline" : s === "my" ? "My scenario" : "Optimized"]),
          h("dd", { text: fmt.km3(r.cmp.scenarios[s].km3[l]) })])),
        h("dl", { class: "cmp-card-diffs" }, [
          ...pair("My − Baseline", r.cmp.changes.my[l]),
          ...pair("Optimized − Baseline", r.cmp.changes.optimized[l]),
          ...pair("My − Optimized", r.myVsOptimized[l]),
        ]),
      ])));
    }

    // ---------------------------------------------------------------- saving range
    function rangeRow(label, cls, current, rg) {
      if (!rg) return h("p", { class: "range-row", text: `${label}: not available` });
      const lo = Math.min(0, rg.min, current);
      const hi = Math.max(0, rg.max, current);
      const span = hi - lo || 1;
      const pos = (v) => `${100 * (v - lo) / span}%`;
      return h("div", { class: "range-row" }, [
        h("p", { class: "range-head" }, [h("span", { class: `key key-${cls}`, "aria-hidden": "true" }), h("strong", { text: label }),
          h("span", { class: "range-now", text: `Selected conditions: ${fmt.signedPct(current)}` })]),
        h("div", { class: "range-track", "aria-hidden": "true" }, [
          h("span", { class: "range-zero", style: `left: ${pos(0)}` }),
          h("span", { class: `range-band band-${cls}`, style: `left: ${pos(rg.min)}; width: ${100 * (rg.max - rg.min) / span}%` }),
          h("span", { class: "range-now-mark", style: `left: ${pos(current)}` }),
        ]),
        h("p", { class: "range-text" }, rg.min === rg.max
          ? `Across all ${rangeN} conditions: ${fmt.signedPct(rg.min)}, the same under every condition.`
          : `Across all ${rangeN} conditions: ${fmt.signedPct(rg.min)} to ${fmt.signedPct(rg.max)}. ` +
            `Lowest: ${Cond.describe(condOptions, rg.minAt)}. Highest: ${Cond.describe(condOptions, rg.maxAt)}.`),
      ]);
    }
    let rangeN = 0;
    function renderRange(r, range) {
      rangeN = range.n;
      rangeBox.replaceChildren(
        rangeRow("My scenario", "my", r.saving.my.river, range.my),
        rangeRow(`Optimized · ${presets[currentPreset].label}`, "optimized", r.saving.optimized.river, range.optimized),
        h("p", { class: "mini-note", text: `Range = spread over 17 climates (mean and 2010–2025) × 36 efficiency scenarios, all assumptions. It is not a probability or confidence interval. Zero line: no change. Marker: selected conditions.` }),
        h("p", { class: "mini-note", text: "Canal efficiency divides the withdrawal of every crop by the same factor, so it does not change the saving in %; the lowest and highest values hold for every canal level. It does change the volumes in km³." }));
    }

    // ---------------------------------------------------------------- crop contributions (diverging, river)
    function contribList(title, imp) {
      const vals = crops.map((c) => imp.byCrop[c.id].river / 1e9);
      const max = Math.max(1e-9, ...vals.map(Math.abs));
      if (vals.every((v) => v === 0)) {
        return h("div", { class: "contrib-col" }, [h("h4", { class: "mini-title", text: title }),
          h("p", { class: "mini-note", text: "No change from Baseline: every crop area is the same." })]);
      }
      return h("div", { class: "contrib-col" }, [
        h("h4", { class: "mini-title", text: title }),
        h("ul", { class: "contrib-list" }, crops.map((c, i) => {
          const v = vals[i];
          const w = 50 * Math.abs(v) / max;
          return h("li", { class: "contrib-row" }, [
            h("span", { class: "contrib-name" }, [h("span", { class: "swatch", style: `background: var(--crop-${c.id})`, "aria-hidden": "true" }), c.name]),
            h("span", { class: "contrib-track", "aria-hidden": "true" }, [
              h("span", { class: "contrib-axis" }),
              v === 0 ? null : h("span", { class: "contrib-bar " + (v < 0 ? "is-down" : "is-up"),
                style: v < 0 ? `right: 50%; width: ${w}%` : `left: 50%; width: ${w}%` }),
            ]),
            h("span", { class: "contrib-val", "data-dir": v === 0 ? "0" : v < 0 ? "down" : "up", text: v === 0 ? "—" : `${fmt.signedKm3(v)} km³` }),
          ]);
        })),
        h("p", { class: "contrib-total", text: `Total: ${fmt.signedKm3(imp.total.river / 1e9)} km³` }),
      ]);
    }
    function renderContrib(r) {
      contrib.replaceChildren(contribList("My scenario vs Baseline", r.cmp.impacts.my),
        contribList(`Optimized · ${presets[currentPreset].label} vs Baseline`, r.cmp.impacts.optimized));
    }

    /** Re-renders everything from one compareAll result and one savingRange result. */
    function render(r, presetId, constraintsOk, range) {
      currentPreset = presetId;
      const ref = Cond.isReference(r.cond);
      condLine.replaceChildren(h("span", { class: "cmp-cond-label", text: "Conditions: " }), Cond.describe(condOptions, r.cond),
        ref ? h("span", { class: "chip chip-ref", text: "Reference" }) : null);
      banner.hidden = ref;
      banner.replaceChildren(h("span", { class: "icon", html: WARN }),
        "Optimized structures were computed for mean climate and baseline efficiencies (Cmean / E_base). Under the selected conditions they are only re-evaluated; they may not be the minimum for these conditions.");
      renderKpis(r, constraintsOk);
      renderBars(r);
      renderTable(r);
      renderRange(r, range);
      renderContrib(r);
    }

    return { render };
  }

  const NOTES = Object.freeze([
    "Planning model, not a field measurement. It is not validated: in the backtest the model is 1.3–1.7 times above observed withdrawal.",
    "Optimized = minimum modelled river withdrawal under Cmean / E_base within the preset's limits (module 6). It is not an economic optimum: income is not modelled. It is not re-optimized when conditions change.",
    "Savings are always shown with their range over 17 climates × 36 efficiency scenarios. The range reflects assumptions, not a probability.",
    "Climate: NASA POWER reanalysis at one grid point. 'Mean 2010–2025' averages the yearly coefficients; it is not a projection. The 2026 climate is not available here.",
    "Field and canal efficiencies and rice percolation are assumptions (status 'assumed'); canal efficiency 0.40 is a pessimistic scenario level.",
    "Crop need = crop water need minus effective rainfall. At the field = crop need / field efficiency, plus rice flooding and percolation. River withdrawal = at the field / canal efficiency.",
    "All sown areas are treated as irrigated. Rice water use is an upper estimate. Five crop groups use a proxy crop. Districts are geographic context only.",
    "Experimental area-reduction cases (−5/10/15 % of total area) are not part of this comparison.",
  ]);

  return Object.freeze({ LEVELS, LEVEL_LABELS, savingPct, compareAll, savingRange, niceMax, axisTicks, createComparison, NOTES });
});
