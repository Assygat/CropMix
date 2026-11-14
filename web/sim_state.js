/* CropMix Twin — Crop Area Editor state (module 10, stage 5).
 *
 * Immutable editor state: current areas (ha, full precision), selected optimizer preset, undo history.
 * No water calculations here — those are done only by sim_core.js. Display formatting helpers live here too,
 * so the same rounding rules (simulator.json "precision") are used everywhere and are unit-tested.
 * Works in the browser (window.CropMixState) and in Node (tests/js/sim_state.test.js).
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CropMixState = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const PRESETS = Object.freeze(["tight", "moderate", "flexible"]);
  const HISTORY_LIMIT = 100;
  const COALESCE_MS = 1200;      // consecutive edits of one crop within this window are one undo step
  const AREA_ROUND_HA = 10;      // simulator.json precision.area_ha_round_to
  const KM3_DECIMALS = 2;        // precision.volume_km3_decimals
  const PCT_DECIMALS = 1;        // precision.percent_decimals
  const MINUS = "−";

  const isValidArea = (v) => typeof v === "number" && Number.isFinite(v) && v >= 0;

  /** New editor state starting from the baseline (copied, never shared). */
  function createEditorState(baseline, preset) {
    if (!PRESETS.includes(preset)) throw new Error("Unknown preset " + preset);
    return Object.freeze({ areas: Object.freeze(Object.assign({}, baseline)), preset, history: Object.freeze([]), lastEdit: null });
  }

  function pushHistory(history, areas) {
    const next = history.concat([areas]);
    return Object.freeze(next.length > HISTORY_LIMIT ? next.slice(next.length - HISTORY_LIMIT) : next);
  }

  /**
   * Sets one crop's area (ha). Value must be a finite number ≥ 0; it is stored exactly as given.
   * Consecutive edits of the same crop within COALESCE_MS form one undo step.
   */
  function applyArea(state, crop, value, nowMs) {
    if (!Object.prototype.hasOwnProperty.call(state.areas, crop)) throw new Error("Unknown crop " + crop);
    if (!isValidArea(value)) throw new Error("Area must be a non-negative finite number");
    if (state.areas[crop] === value) return state;
    const coalesce = state.lastEdit && state.lastEdit.crop === crop && nowMs - state.lastEdit.t <= COALESCE_MS;
    const areas = Object.freeze(Object.assign({}, state.areas, { [crop]: value }));
    return Object.freeze({
      areas, preset: state.preset,
      history: coalesce ? state.history : pushHistory(state.history, state.areas),
      lastEdit: { crop, t: nowMs },
    });
  }

  function canUndo(state) {
    return state.history.length > 0;
  }

  /** Restores the areas before the last undo step. Preset is not part of the history. */
  function undo(state) {
    if (!canUndo(state)) return state;
    return Object.freeze({
      areas: state.history[state.history.length - 1], preset: state.preset,
      history: Object.freeze(state.history.slice(0, -1)), lastEdit: null,
    });
  }

  function changedCrops(areas, baseline) {
    return Object.keys(baseline).filter((c) => areas[c] !== baseline[c]);
  }

  /** Back to the baseline as one undoable step; returns the same state if nothing changed. */
  function resetToBaseline(state, baseline) {
    if (changedCrops(state.areas, baseline).length === 0) return state;
    return Object.freeze({ areas: Object.freeze(Object.assign({}, baseline)), preset: state.preset,
                           history: pushHistory(state.history, state.areas), lastEdit: null });
  }

  /**
   * Replaces all areas at once (e.g. "Start from Optimized") as ONE undo step. The source object is copied,
   * never kept; it must have exactly the current crops with valid areas. Same values → same state.
   */
  function replaceAreas(state, areas) {
    const keys = Object.keys(state.areas);
    if (!areas || Object.keys(areas).length !== keys.length || !keys.every((c) => Object.prototype.hasOwnProperty.call(areas, c))) {
      throw new Error("Areas must have the same crops as the editor");
    }
    if (!keys.every((c) => isValidArea(areas[c]))) throw new Error("Area must be a non-negative finite number");
    if (keys.every((c) => areas[c] === state.areas[c])) return state;
    const copy = {};
    for (const c of keys) copy[c] = areas[c];
    return Object.freeze({ areas: Object.freeze(copy), preset: state.preset,
                           history: pushHistory(state.history, state.areas), lastEdit: null });
  }

  function setPreset(state, preset) {
    if (!PRESETS.includes(preset)) throw new Error("Unknown preset " + preset);
    return Object.freeze({ areas: state.areas, preset, history: state.history, lastEdit: state.lastEdit });
  }

  /**
   * Parses a typed area. Accepts "81696.6", "81,696.6", "1 600". Rejects empty, negative, non-numeric, infinite.
   * @returns {{ok: true, value: number} | {ok: false, code: string, message: string}}
   */
  function parseAreaInput(text) {
    const raw = String(text === undefined || text === null ? "" : text).trim();
    if (raw === "") return { ok: false, code: "EMPTY", message: "Enter an area in hectares." };
    const cleaned = raw.replace(/−/g, "-").replace(/[\s  ,]/g, "");
    if (!/^-?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(cleaned)) {
      return { ok: false, code: "NOT_A_NUMBER", message: "Use digits only, e.g. 12500 or 12,500.5." };
    }
    const value = Number(cleaned);
    if (!Number.isFinite(value)) return { ok: false, code: "NOT_FINITE", message: "The number is too large." };
    if (value < 0) return { ok: false, code: "NEGATIVE", message: "Area cannot be negative." };
    return { ok: true, value: value === 0 ? 0 : value };
  }

  /** Largest 1-2-5 × 10^n not above x (at least 1). */
  function niceStep(x) {
    if (!(x >= 1)) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(x)));
    for (const m of [5, 2, 1]) if (m * p <= x) return m * p;
    return p;
  }

  function stepArea(value, step, direction) {
    return Math.max(0, value + direction * step);
  }

  // ---------------------------------------------------------------- display formatting (never fed back)

  const enInt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
  const signOf = (v) => (v > 0 ? "+" : v < 0 ? MINUS : "");
  const fixed = (v, d) => new Intl.NumberFormat("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }).format(v);

  const fmt = Object.freeze({
    ha: (v) => enInt.format(Math.round(v / AREA_ROUND_HA) * AREA_ROUND_HA + 0),
    signedHa: (v) => {
      const r = Math.round(v / AREA_ROUND_HA) * AREA_ROUND_HA;
      return r === 0 ? "0" : signOf(r) + enInt.format(Math.abs(r));
    },
    km3: (v) => fixed(v, KM3_DECIMALS),
    signedKm3: (v) => {
      if (v === 0) return fixed(0, KM3_DECIMALS);
      const min = 0.5 * Math.pow(10, -KM3_DECIMALS);
      // "+ <0.01" / "− <0.01": the space keeps the sign readable next to "<", and the direction is not lost
      if (Math.abs(v) < min) return signOf(v) + " <" + fixed(2 * min, KM3_DECIMALS);
      return signOf(v) + fixed(Math.abs(v), KM3_DECIMALS);
    },
    pct: (v) => fixed(v, PCT_DECIMALS) + "%",
    signedPct: (v) => (v === null || v === undefined ? "—"
      : (Math.abs(v) < 0.05 ? fixed(0, PCT_DECIMALS) : signOf(v) + fixed(Math.abs(v), PCT_DECIMALS)) + "%"),
    signedPp: (v) => (Math.abs(v) < 0.05 ? fixed(0, PCT_DECIMALS) : signOf(v) + fixed(Math.abs(v), PCT_DECIMALS)) + " pp",
  });

  return Object.freeze({
    PRESETS, HISTORY_LIMIT, COALESCE_MS,
    createEditorState, applyArea, undo, canUndo, resetToBaseline, replaceAreas, setPreset, changedCrops,
    parseAreaInput, niceStep, stepArea, isValidArea, fmt,
  });
});
