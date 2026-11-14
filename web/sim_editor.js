/* CropMix Twin — Crop Area Editor (module 10, stage 5).
 *
 * Edits the areas of the 8 crop groups for the WHOLE Kyzylorda Region. Every number about water or constraints
 * comes from sim_core.js (one compareScenarios call per change, passed in by the page); this file only
 * renders. Areas are passed to the core exactly as typed or stepped (no rounding); rounding is display-only.
 * Values outside the preset's limits are allowed: the editor warns and marks the scenario infeasible.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CropMixEditor = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Climate and efficiency are chosen on the page (stage 6) and applied through options.compute.
  const DEFAULT_PRESET = "moderate";
  const STEP_SHARE = 0.01;          // −/+ step ≈ 1 % of the crop's baseline area (rounded to 1-2-5)
  const SLIDER_MAX_FACTOR = 2;      // slider spans 0 … 2 × baseline (typed values may go beyond)
  const SLIDER_STEPS = 400;

  const ICONS = {
    ok: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="m5 8.2 2 2 4-4.4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    warn: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.8 15 14H1Z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M8 6v4M8 11.9v.1" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    undo: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.5 3.5 2.5 6.5l3 3M3 6.5h6.5a4 4 0 0 1 0 8H7" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    reset: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.8 8a5.2 5.2 0 1 0 1.6-3.8M2.5 2.2v2.6h2.6" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    minus: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8h9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    plus: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3.5v9M3.5 8h9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    opt: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 12.5 6 9l2.5 2.5 5-6M10 5.5h3.5V9" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  };

  function h(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined) continue;
      if (k === "text") node.textContent = v;
      else if (k === "html") node.innerHTML = v;            // only for the static ICONS above
      else if (k === "style") node.style.cssText = v;
      else node.setAttribute(k, v);
    }
    for (const c of [].concat(children || [])) if (c !== null && c !== undefined) node.append(c);
    return node;
  }

  const inputText = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

  /**
   * options: { sim, State, Structure,
   *            compute(areas, presetId) → CropMixCompare.compareAll result under the page's current conditions,
   *            describeConditions() → text, onRender(result, state) }
   * The editor never chooses conditions itself: the page passes one compute function, so the editor and the
   * comparison always show numbers from the same sim_core call.
   * Returns a small API used by the page and by browser QA.
   */
  function createEditor(rootEl, options) {
    const { sim, State } = options;
    const fmt = State.fmt;
    const crops = sim.crops;
    const baseline = sim.baseline.areas_ha;
    const presets = sim.optimized.presets;

    let state = State.createEditorState(baseline, DEFAULT_PRESET);
    const invalid = new Map();                 // crop → message, while the typed text cannot be used
    const rows = new Map();
    let lastStatusKey = "";

    // ---------------------------------------------------------------- header: preset + actions
    const presetGroup = h("div", { class: "segmented", role: "radiogroup", "aria-labelledby": "preset-label" });
    for (const pid of sim.optimized.presets_order) {
      const p = presets[pid].params;
      const id = `preset-${pid}`;
      presetGroup.append(
        h("input", { type: "radio", name: "preset", id, value: pid, class: "visually-hidden-input" }),
        h("label", { for: id, title: `Each crop within ±${Math.round(p.area_change_max * 100)}% of 2025; food crops ≥ ${Math.round(p.food_area_min_share * 100)}% of 2025 food area; total area unchanged` },
          [h("span", { class: "seg-name", text: presets[pid].label }),
           h("span", { class: "seg-sub", text: `±${Math.round(p.area_change_max * 100)}% · food ≥ ${Math.round(p.food_area_min_share * 100)}%` })]));
    }
    const undoBtn = h("button", { type: "button", class: "tool-btn", "aria-keyshortcuts": "Control+Z", title: "Undo (Ctrl+Z)" },
      [h("span", { class: "icon", html: ICONS.undo }), "Undo"]);
    const resetBtn = h("button", { type: "button", class: "tool-btn" }, [h("span", { class: "icon", html: ICONS.reset }), "Reset to baseline"]);
    const fromOptBtn = h("button", { type: "button", class: "tool-btn", title: "Copy the Optimized areas of the selected preset into My scenario (one undo step)" },
      [h("span", { class: "icon", html: ICONS.opt }), "Start from Optimized"]);

    const head = h("div", { class: "editor-head" }, [
      h("div", { class: "editor-title" }, [
        h("p", { class: "kicker", text: "Scenario · whole region" }),
        h("h2", { id: "editor-title", text: "Crop area editor" }),
        h("p", { class: "section-sub", text: "Edit the sown area of each crop group. Results update instantly." }),
      ]),
      h("div", { class: "editor-controls" }, [
        h("div", { class: "preset-picker" }, [h("span", { class: "control-label", id: "preset-label", text: "Constraint preset" }), presetGroup]),
        h("div", { class: "editor-actions" }, [undoBtn, resetBtn, fromOptBtn]),
      ]),
    ]);

    // ---------------------------------------------------------------- summary strip
    const statusBox = h("div", { class: "status" });
    // announced only when the status itself changes, not on every keystroke
    const announcer = h("p", { class: "visually-hidden", role: "status", "aria-live": "polite" });
    const consList = h("ul", { class: "cons-list", "aria-label": "Constraints of the selected preset" });
    const resultBox = h("div", { class: "live-result" });
    const summary = h("div", { class: "summary" }, [
      h("div", { class: "summary-cell" }, [h("h3", { class: "cell-title", text: "Scenario status" }), statusBox]),
      h("div", { class: "summary-cell" }, [h("h3", { class: "cell-title", id: "cons-title", text: "Constraints" }), consList]),
      h("div", { class: "summary-cell" }, [h("h3", { class: "cell-title", text: "River withdrawal · My scenario" }), resultBox]),
    ]);

    // ---------------------------------------------------------------- crop rows
    const list = h("ul", { class: "crop-list", "aria-labelledby": "editor-title" });
    const colHead = h("div", { class: "crop-colhead", "aria-hidden": "true" },
      ["Crop group", "Area, ha", "Allowed range · baseline tick", "Change vs 2025", "Water impact", "Share"].map((t) => h("span", { text: t })));

    for (const c of crops) {
      const base = baseline[c.id];
      const step = State.niceStep(base * STEP_SHARE);
      const sliderMax = base * SLIDER_MAX_FACTOR;
      const ids = { input: `area-${c.id}`, hint: `hint-${c.id}`, err: `err-${c.id}` };

      const input = h("input", { id: ids.input, class: "area-input", type: "text", inputmode: "decimal", autocomplete: "off",
                                 spellcheck: "false", "aria-describedby": `${ids.hint} ${ids.err}`, "data-crop": c.id });
      const dec = h("button", { type: "button", class: "step-btn", "aria-label": `Decrease ${c.name} by ${fmt.ha(step)} ha`, html: ICONS.minus });
      const inc = h("button", { type: "button", class: "step-btn", "aria-label": `Increase ${c.name} by ${fmt.ha(step)} ha`, html: ICONS.plus });
      const range = h("input", { type: "range", class: "range", min: "0", max: String(sliderMax), step: String(sliderMax / SLIDER_STEPS),
                                 "aria-label": `${c.name} area slider`, "aria-describedby": ids.hint });
      const band = h("span", { class: "band" });
      const tick = h("span", { class: "base-tick", style: `left: ${100 / SLIDER_MAX_FACTOR}%` });
      const fillTo = h("span", { class: "range-fill", style: `background: var(--crop-${c.id})` });
      const hint = h("span", { class: "range-hint", id: ids.hint });
      const flag = h("span", { class: "range-flag" });
      const dHa = h("span", { class: "delta-ha" });
      const dPct = h("span", { class: "delta-pct" });
      const water = h("span", { class: "water-val" });
      const shareTxt = h("span", { class: "share-txt" });
      const shareBar = h("span", { class: "share-mini" }, h("i", { style: `background: var(--crop-${c.id})` }));
      const err = h("p", { class: "field-error", id: ids.err, "aria-live": "polite" });

      const row = h("li", { class: "crop-row", "data-crop": c.id }, [
        h("div", { class: "cell crop-id" }, [
          h("span", { class: "swatch", style: `background: var(--crop-${c.id})`, "aria-hidden": "true" }),
          h("div", {}, [
            h("label", { for: ids.input, class: "crop-name", text: c.name }),
            h("span", { class: "crop-meta" }, [c.food_crop ? h("span", { class: "tag", text: "Food" }) : null, c.proxy]),
          ]),
        ]),
        h("div", { class: "cell crop-input" }, [dec, h("div", { class: "field" }, [input, h("span", { class: "unit", "aria-hidden": "true", text: "ha" })]), inc]),
        h("div", { class: "cell crop-range" }, [
          h("div", { class: "track" }, [band, fillTo, tick, range]),
          h("div", { class: "range-meta" }, [hint, flag]),
        ]),
        h("div", { class: "cell crop-delta" }, [h("span", { class: "visually-hidden", text: "Change vs 2025: " }), dHa, dPct]),
        h("div", { class: "cell crop-water" }, [h("span", { class: "visually-hidden", text: "Change in river withdrawal: " }), water]),
        h("div", { class: "cell crop-share" }, [h("span", { class: "visually-hidden", text: "Share of total area: " }), shareTxt, shareBar]),
        err,
      ]);
      rows.set(c.id, { row, input, range, band, fillTo, hint, flag, dHa, dPct, water, shareTxt, shareBar, err, step, sliderMax });
      list.append(row);

      // typing: commit every valid value immediately (full precision); keep invalid text visible with an error
      input.addEventListener("input", () => {
        const parsed = State.parseAreaInput(input.value);
        if (!parsed.ok) { invalid.set(c.id, parsed.message); render(); return; }
        invalid.delete(c.id);
        commit(State.applyArea(state, c.id, parsed.value, Date.now()));
      });
      input.addEventListener("blur", () => { if (!invalid.has(c.id)) input.value = inputText.format(state.areas[c.id]); });
      input.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
        e.preventDefault();
        stepCrop(c.id, e.key === "ArrowUp" ? 1 : -1, e.shiftKey ? 10 : 1);
      });
      dec.addEventListener("click", (e) => stepCrop(c.id, -1, e.shiftKey ? 10 : 1));
      inc.addEventListener("click", (e) => stepCrop(c.id, 1, e.shiftKey ? 10 : 1));
      range.addEventListener("input", () => {
        invalid.delete(c.id);
        commit(State.applyArea(state, c.id, Number(range.value), Date.now()));
      });
    }

    function stepCrop(crop, direction, mult) {
      const r = rows.get(crop);
      invalid.delete(crop);
      commit(State.applyArea(state, crop, State.stepArea(state.areas[crop], r.step * mult, direction), Date.now()));
    }

    const totalsRow = h("div", { class: "crop-total" });
    const editorBody = h("div", { class: "editor-body" }, [colHead, list, totalsRow]);
    const structureRoot = h("section", { class: "structure", "aria-labelledby": "structure-title" });

    rootEl.append(head, summary, editorBody, structureRoot, announcer);
    const structure = options.Structure.createStructureChart(structureRoot, { crops, fmt });

    // ---------------------------------------------------------------- actions
    presetGroup.addEventListener("change", (e) => commit(State.setPreset(state, e.target.value)));
    undoBtn.addEventListener("click", () => { invalid.clear(); commit(State.undo(state), true); });
    resetBtn.addEventListener("click", () => { invalid.clear(); commit(State.resetToBaseline(state, baseline), true); });
    fromOptBtn.addEventListener("click", () => startFromOptimized());

    /** Copies the selected preset's Optimized areas into My scenario as one undo step (source untouched). */
    function startFromOptimized() {
      invalid.clear();
      commit(State.replaceAreas(state, presets[state.preset].areas_ha), true);
    }
    document.addEventListener("keydown", (e) => {
      const inText = e.target instanceof HTMLInputElement && e.target.type === "text";
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "z" && !inText && State.canUndo(state)) {
        e.preventDefault();
        invalid.clear();
        commit(State.undo(state), true);
      }
    });

    function commit(next, refreshInputs) {
      const changed = next !== state;
      state = next;
      render(refreshInputs || changed);
      if (changed && options.onChange) options.onChange(state);
    }

    // ---------------------------------------------------------------- render (all numbers from sim_core)
    function render(refreshInputs) {
      const result = options.compute(state.areas, state.preset);   // one sim_core.compareScenarios call
      const cmp = result.cmp;
      const ev = cmp.scenarios.my;
      const ch = cmp.changes.my;
      const imp = cmp.impacts.my;
      const cons = cmp.constraints.my;
      const preset = presets[state.preset];
      fromOptBtn.disabled = State.changedCrops(state.areas, preset.areas_ha).length === 0;
      const total = ev.totalArea;

      presetGroup.querySelector(`input[value="${state.preset}"]`).checked = true;
      undoBtn.disabled = !State.canUndo(state);
      resetBtn.disabled = State.changedCrops(state.areas, baseline).length === 0;

      for (const c of crops) {
        const r = rows.get(c.id);
        const a = state.areas[c.id];
        const corridor = cons.checks.find((k) => k.type === "corridor" && k.crop === c.id);
        const bad = invalid.get(c.id);
        if (document.activeElement !== r.input && !bad) r.input.value = inputText.format(a);
        else if (refreshInputs && !bad) r.input.value = inputText.format(a);
        r.input.setAttribute("aria-invalid", bad ? "true" : "false");
        r.err.textContent = bad ? `${bad} Using the last valid value, ${fmt.ha(a)} ha.` : "";
        r.row.classList.toggle("is-invalid", !!bad);
        if (document.activeElement !== r.range) r.range.value = String(Math.min(a, r.sliderMax));
        r.fillTo.style.width = `${100 * Math.min(a, r.sliderMax) / r.sliderMax}%`;
        r.band.style.left = `${100 * corridor.min / r.sliderMax}%`;
        r.band.style.width = `${100 * (corridor.max - corridor.min) / r.sliderMax}%`;
        r.hint.textContent = `Allowed ${fmt.ha(corridor.min)}–${fmt.ha(corridor.max)} ha`;
        const above = !corridor.ok && a > corridor.max;
        r.flag.innerHTML = corridor.ok ? "" : ICONS.warn;
        r.flag.append(corridor.ok ? "" : (above ? " Above range" : " Below range") + (a > r.sliderMax ? " · beyond slider" : ""));
        r.row.classList.toggle("is-violation", !corridor.ok);
        const dA = imp.areaChange[c.id];
        r.row.classList.toggle("is-changed", dA !== 0);
        r.dHa.textContent = dA === 0 ? "—" : `${fmt.signedHa(dA)} ha`;
        r.dPct.textContent = dA === 0 ? "" : fmt.signedPct(baseline[c.id] > 0 ? 100 * dA / baseline[c.id] : null);
        const w = imp.byCrop[c.id].river / 1e9;
        r.water.textContent = dA === 0 ? "—" : `${fmt.signedKm3(w)} km³`;
        r.water.dataset.dir = dA === 0 ? "0" : w > 0 ? "up" : "down";
        const share = total > 0 ? 100 * a / total : null;
        r.shareTxt.textContent = share === null ? "—" : fmt.pct(share);
        r.shareBar.firstChild.style.width = `${share === null ? 0 : share}%`;
      }

      // totals row
      const dTotal = ch.area.abs_ha;
      totalsRow.replaceChildren(
        h("span", { class: "total-label", text: "Total sown area" }),
        h("span", { class: "total-value" }, [h("strong", { text: `${fmt.ha(total)} ha` }),
          h("span", { class: "total-delta", text: dTotal === 0 ? "same as 2025" : `${fmt.signedHa(dTotal)} ha vs 2025 (${fmt.ha(ch.area.from_ha)} ha)` })]),
        h("span", { class: "total-note", text: `${State.changedCrops(state.areas, baseline).length} of ${crops.length} crops changed` }));

      renderConstraints(cons, preset);
      renderStatus(cons, preset);
      renderResult(ev, ch);
      structure.render(baseline, state.areas);
      if (options.onRender) options.onRender(result, state);
    }

    function consItem(ok, title, detail) {
      return h("li", { class: "cons-item " + (ok ? "is-ok" : "is-bad") }, [
        h("span", { class: "cons-icon", html: ok ? ICONS.ok : ICONS.warn }),
        h("div", {}, [h("span", { class: "cons-title" }, [title, h("span", { class: "visually-hidden", text: ok ? " — met" : " — violated" })]),
                      h("span", { class: "cons-detail", text: detail })]),
      ]);
    }

    function renderConstraints(cons, preset) {
      const p = preset.params;
      const corridorBad = cons.violations.filter((v) => v.type === "corridor");
      const food = cons.checks.find((k) => k.type === "food_min");
      const tot = cons.checks.find((k) => k.type === "total_area");
      const names = (vs) => vs.map((v) => crops.find((c) => c.id === v.crop).name).join(", ");
      consList.replaceChildren(
        consItem(corridorBad.length === 0, `Each crop within ±${Math.round(p.area_change_max * 100)}% of 2025`,
          corridorBad.length === 0 ? `${crops.length} of ${crops.length} crops in range` : `Out of range: ${names(corridorBad)}`),
        consItem(food.ok, `Food crops ≥ ${Math.round(p.food_area_min_share * 100)}% of 2025 food area`,
          `${fmt.ha(food.value)} ha now · ${fmt.ha(food.min)} ha required`),
        consItem(tot.ok, "Total area equal to 2025",
          tot.ok ? `${fmt.ha(tot.value)} ha` : `${fmt.ha(tot.value)} ha now · ${fmt.ha(tot.min)} ha required (${fmt.signedHa(tot.value - tot.min)} ha)`));
    }

    function renderStatus(cons, preset) {
      const n = cons.violations.length;
      const ok = cons.ok && invalid.size === 0;
      const key = `${state.preset}|${n}|${invalid.size}`;
      statusBox.className = "status " + (ok ? "is-ok" : "is-bad");
      const lines = [];
      if (invalid.size) lines.push(h("span", { class: "status-detail", text: `Invalid entry in ${[...invalid.keys()].map((id) => crops.find((c) => c.id === id).name).join(", ")}; the last valid value is used.` }));
      lines.push(h("span", { class: "status-detail", text: cons.ok
        ? `Meets all ${preset.label} constraints.`
        : `${n} of ${cons.checks.length} ${preset.label} constraints violated. You can keep exploring; the scenario is outside the preset.` }));
      statusBox.replaceChildren(
        h("span", { class: "status-badge" }, [h("span", { class: "icon", html: ok ? ICONS.ok : ICONS.warn }),
          invalid.size ? "Invalid entry" : cons.ok ? "Scenario feasible" : "Scenario infeasible"]),
        ...lines);
      if (key !== lastStatusKey && lastStatusKey !== "") {
        announcer.textContent = cons.ok ? `Scenario feasible under ${preset.label}.`
          : `Scenario infeasible: ${n} ${preset.label} constraint${n === 1 ? "" : "s"} violated.`;
      }
      lastStatusKey = key;
    }

    function renderResult(ev, ch) {
      const r = ch.river;
      resultBox.replaceChildren(
        h("p", { class: "result-main" }, [h("span", { class: "result-value", text: fmt.km3(ev.km3.river) }), h("span", { class: "result-unit", text: "km³" })]),
        h("p", { class: "result-delta", "data-dir": r.abs_m3 === 0 ? "0" : r.abs_m3 > 0 ? "up" : "down" },
          `${fmt.signedKm3(r.abs_km3)} km³ (${fmt.signedPct(r.pct)}) vs baseline ${fmt.km3(r.from_m3 / 1e9)} km³`),
        h("dl", { class: "result-levels" }, [
          h("dt", { text: "At the field" }), h("dd", { text: `${fmt.km3(ev.km3.field)} km³` }),
          h("dt", { text: "Crop need" }), h("dd", { text: `${fmt.km3(ev.km3.plant)} km³` }),
        ]),
        h("p", { class: "result-note", text: `${options.describeConditions()}. Model estimate, not a measurement.` }));
    }

    render(true);

    return {
      getState: () => state,
      setPreset: (pid) => commit(State.setPreset(state, pid)),
      setArea: (crop, value) => { invalid.delete(crop); commit(State.applyArea(state, crop, value, Date.now()), true); },
      undo: () => { invalid.clear(); commit(State.undo(state), true); },
      reset: () => { invalid.clear(); commit(State.resetToBaseline(state, baseline), true); },
      startFromOptimized,
      /** Re-evaluates under new conditions; areas, preset and undo history are unchanged. */
      refresh: () => render(false),
    };
  }

  return Object.freeze({ createEditor });
});
