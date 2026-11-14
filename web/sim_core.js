/* CropMix Twin — calculation core of the Crop Allocation Simulator (module 10, stage 3).
 *
 * W_l(A, C, E) = Σ_c A_c × k_l(c, C, E),  l ∈ {plant, field, river}
 *
 * - k comes only from web/data/model.json (coef_m3_ha[E][C][crop] = [plant, field, river] m³/ha), computed in
 *   Python (modules 1–3). There are no water formulas here: the multiplication itself is delegated to
 *   CropMixCalc.compute from web/model_calc.js (module 4), so Σ A × k exists in exactly one JS file.
 * - Optimized structures come from web/data/simulator.json (module 6, Python LP under Cmean / E_base). They are
 *   never re-optimized here; under another C or E they are only re-evaluated.
 * - All functions are pure: inputs are never mutated, every result is a fresh object, nothing is rounded.
 *
 * Works in the browser (window.CropMixSimCore; load data/model.js, data/simulator.js and model_calc.js first)
 * and in Node (require). Tests: tests/js/sim_core.test.js, tests/test_sim_core.py (parity with Python).
 */
(function (root, factory) {
  "use strict";
  if (typeof module !== "undefined" && module.exports) {
    module.exports = factory(require("./model_calc.js"));
  } else {
    root.CropMixSimCore = factory(root.CropMixCalc);
  }
})(typeof self !== "undefined" ? self : this, function (CropMixCalc) {
  "use strict";

  const LEVELS = Object.freeze(["plant", "field", "river"]);
  const M3_PER_KM3 = 1e9;
  // Relative tolerance for constraint checks: the LP optimum sits exactly on bounds up to ~1e-11 ha.
  const CONSTRAINT_REL_TOL = 1e-9;

  class SimCoreError extends Error {
    constructor(code, message, details) {
      super(message);
      this.name = "SimCoreError";
      this.code = code;
      this.details = details === undefined ? null : details;
    }
  }

  const hasOwn = (obj, key) => obj !== null && typeof obj === "object" && Object.prototype.hasOwnProperty.call(obj, key);

  /** Deep copy of plain data (objects, arrays, primitives). Never shares references with the input. */
  function deepCopy(value) {
    if (Array.isArray(value)) return value.map(deepCopy);
    if (value !== null && typeof value === "object") {
      const out = {};
      for (const key of Object.keys(value)) out[key] = deepCopy(value[key]);
      return out;
    }
    return value;
  }

  function emptyLevels() {
    return { plant: 0, field: 0, river: 0 };
  }

  /**
   * Creates a core bound to the exported data.
   * @param {object} model      web/data/model.json (coefficients, crops)
   * @param {object} simulator  web/data/simulator.json (baseline, optimizer presets, scenario lists)
   */
  function createSimCore(model, simulator) {
    if (!CropMixCalc || typeof CropMixCalc.compute !== "function") {
      throw new SimCoreError("MISSING_DEPENDENCY", "model_calc.js (CropMixCalc) must be loaded before sim_core.js");
    }
    if (!model || !model.coef_m3_ha || !Array.isArray(model.crops)) {
      throw new SimCoreError("BAD_DATA", "model.json is missing coef_m3_ha or crops");
    }
    if (!simulator || !simulator.optimized || !simulator.baseline || !simulator.scenarios) {
      throw new SimCoreError("BAD_DATA", "simulator.json is missing baseline, optimized or scenarios");
    }

    const cropIds = Object.freeze(model.crops.map((c) => c.id));
    const climateKeys = new Set(simulator.scenarios.climate.map((c) => c.key));
    const efficiencyKeys = new Set(simulator.scenarios.efficiency.map((e) => e.key));
    const foodCrops = new Set(simulator.crops.filter((c) => c.food_crop).map((c) => c.id));

    // ---------------------------------------------------------------- validation

    /**
     * Checks that areas has exactly the 8 model crops, each a finite number ≥ 0 (ha).
     * @returns {{ok: boolean, errors: Array<{code: string, crop: (string|null), message: string}>}}
     */
    function validateAreas(areas) {
      const errors = [];
      if (areas === null || typeof areas !== "object" || Array.isArray(areas)) {
        return { ok: false, errors: [{ code: "NOT_AN_OBJECT", crop: null, message: "Areas must be an object {crop: ha}" }] };
      }
      for (const crop of cropIds) {
        if (!hasOwn(areas, crop)) {
          errors.push({ code: "MISSING_CROP", crop, message: `Missing area for ${crop}` });
          continue;
        }
        const v = areas[crop];
        if (typeof v !== "number" || Number.isNaN(v)) {
          errors.push({ code: "NOT_A_NUMBER", crop, message: `Area of ${crop} is not a number` });
        } else if (!Number.isFinite(v)) {
          errors.push({ code: "NOT_FINITE", crop, message: `Area of ${crop} is not finite` });
        } else if (v < 0) {
          errors.push({ code: "NEGATIVE", crop, message: `Area of ${crop} is negative` });
        }
      }
      for (const key of Object.keys(areas)) {
        if (!cropIds.includes(key)) errors.push({ code: "UNKNOWN_CROP", crop: key, message: `Unknown crop ${key}` });
      }
      return { ok: errors.length === 0, errors };
    }

    function assertScenario(climate, efficiency) {
      if (typeof efficiency !== "string" || !efficiencyKeys.has(efficiency) || !hasOwn(model.coef_m3_ha, efficiency)) {
        throw new SimCoreError("UNKNOWN_EFFICIENCY", `Unknown efficiency scenario ${String(efficiency)}`);
      }
      if (typeof climate !== "string" || !climateKeys.has(climate) || !hasOwn(model.coef_m3_ha[efficiency], climate)) {
        throw new SimCoreError("UNKNOWN_CLIMATE", `Unknown climate scenario ${String(climate)}`);
      }
    }

    function getPreset(presetId) {
      if (!hasOwn(simulator.optimized.presets, presetId)) {
        throw new SimCoreError("UNKNOWN_PRESET", `Unknown preset ${String(presetId)}`);
      }
      return simulator.optimized.presets[presetId];
    }

    function assertSameScenario(a, b) {
      if (!a || !b || a.climate !== b.climate || a.efficiency !== b.efficiency) {
        throw new SimCoreError("SCENARIO_MISMATCH",
          "Results must be evaluated under the same climate and efficiency to be compared");
      }
    }

    // ---------------------------------------------------------------- evaluation

    /**
     * W_l(A, C, E) for the three levels. Throws SimCoreError for invalid areas or unknown scenarios.
     * @returns {{climate, efficiency, areas, totalArea, m3: {plant, field, river}, km3: {...},
     *            byCrop: Object<string, {area, coef: {plant, field, river}, plant, field, river}>}}
     */
    function evaluate(areas, climate, efficiency) {
      const check = validateAreas(areas);
      if (!check.ok) throw new SimCoreError("INVALID_AREAS", check.errors[0].message, check.errors);
      assertScenario(climate, efficiency);

      const calc = CropMixCalc.compute(model, efficiency, climate, areas);   // single Σ A × k implementation
      const byCrop = {};
      for (const row of calc.rows) {
        byCrop[row.id] = { area: row.area, coef: { plant: row.coef.plant, field: row.coef.field, river: row.coef.river },
                           plant: row.plant, field: row.field, river: row.river };
      }
      const m3 = { plant: calc.totals.plant, field: calc.totals.field, river: calc.totals.river };
      const km3 = {};
      for (const l of LEVELS) km3[l] = m3[l] / M3_PER_KM3;
      return { climate, efficiency, areas: deepCopy(areas), totalArea: calc.totals.area, m3, km3, byCrop };
    }

    /**
     * Absolute and relative change from → to (same C and E required). pct is null when the reference is 0.
     */
    function calculateChanges(from, to) {
      assertSameScenario(from, to);
      const out = { climate: to.climate, efficiency: to.efficiency };
      for (const l of LEVELS) {
        const abs = to.m3[l] - from.m3[l];
        out[l] = { from_m3: from.m3[l], to_m3: to.m3[l], abs_m3: abs, abs_km3: abs / M3_PER_KM3,
                   pct: from.m3[l] === 0 ? null : 100 * abs / from.m3[l] };
      }
      const dA = to.totalArea - from.totalArea;
      out.area = { from_ha: from.totalArea, to_ha: to.totalArea, abs_ha: dA,
                   pct: from.totalArea === 0 ? null : 100 * dA / from.totalArea };
      return out;
    }

    /**
     * Contribution of each crop's area change to the total change: ΔA_c × k_l(c, C, E), m³.
     * Σ over crops equals the total change (up to floating-point summation).
     */
    function calculateCropImpacts(from, to) {
      assertSameScenario(from, to);
      const byCrop = {};
      const areaChange = {};
      const total = emptyLevels();
      for (const crop of cropIds) {
        const dA = to.byCrop[crop].area - from.byCrop[crop].area;
        areaChange[crop] = dA;
        byCrop[crop] = {};
        for (const l of LEVELS) {
          byCrop[crop][l] = dA * to.byCrop[crop].coef[l];
          total[l] += byCrop[crop][l];
        }
      }
      const shareOfChange = {};
      for (const crop of cropIds) {
        shareOfChange[crop] = {};
        for (const l of LEVELS) shareOfChange[crop][l] = total[l] === 0 ? null : 100 * byCrop[crop][l] / total[l];
      }
      return { climate: to.climate, efficiency: to.efficiency, areaChange, byCrop, total, shareOfChange };
    }

    // ---------------------------------------------------------------- constraints

    function within(value, min, max) {
      const tolMin = CONSTRAINT_REL_TOL * Math.max(1, Math.abs(min));
      const tolMax = CONSTRAINT_REL_TOL * Math.max(1, Math.abs(max));
      return value >= min - tolMin && value <= max + tolMax;
    }

    /**
     * Checks areas against one optimizer preset (module 6 rules, same parameters):
     * corridor x0(1−d) ≤ x ≤ x0(1+d) per crop; Σ food ≥ f · Σ food0; Σ x = s · Σ x0 (equality).
     * x0 = the preset's baseline areas (2025). Does not throw for invalid areas: reports them instead.
     */
    function validateConstraints(areas, presetId) {
      const preset = getPreset(presetId);
      const areaCheck = validateAreas(areas);
      if (!areaCheck.ok) {
        return { ok: false, presetId, checks: [],
                 violations: areaCheck.errors.map((e) => ({ type: "areas", crop: e.crop, message: e.message })) };
      }
      const d = preset.params.area_change_max;
      const f = preset.params.food_area_min_share;
      const s = preset.params.total_area_share;
      const x0 = preset.base_areas_ha;
      const checks = [];

      for (const crop of cropIds) {
        const min = x0[crop] * (1 - d);
        const max = x0[crop] * (1 + d);
        checks.push({ type: "corridor", crop, value: areas[crop], min, max, ok: within(areas[crop], min, max) });
      }
      let food = 0;
      let food0 = 0;
      let total = 0;
      let total0 = 0;
      for (const crop of cropIds) {
        total += areas[crop];
        total0 += x0[crop];
        if (foodCrops.has(crop)) { food += areas[crop]; food0 += x0[crop]; }
      }
      const foodMin = f * food0;
      checks.push({ type: "food_min", crop: null, value: food, min: foodMin, max: null,
                    ok: food >= foodMin - CONSTRAINT_REL_TOL * Math.max(1, foodMin) });
      const target = s * total0;
      checks.push({ type: "total_area", crop: null, value: total, min: target, max: target, ok: within(total, target, target) });

      const violations = checks.filter((c) => !c.ok).map((c) => Object.assign({}, c));
      return { ok: violations.length === 0, presetId, checks, violations };
    }

    // ---------------------------------------------------------------- comparison

    /**
     * Baseline, My Scenario and Optimized (preset) — all under the same climate and efficiency.
     * Optimized areas stay as optimized under Cmean / E_base; only water is re-evaluated.
     */
    function compareScenarios(myAreas, presetId, climate, efficiency) {
      const preset = getPreset(presetId);
      const baseline = evaluate(simulator.baseline.areas_ha, climate, efficiency);
      const my = evaluate(myAreas, climate, efficiency);
      const optimized = evaluate(preset.areas_ha, climate, efficiency);
      return {
        climate, efficiency, presetId,
        scenarios: { baseline, my, optimized },
        changes: { my: calculateChanges(baseline, my), optimized: calculateChanges(baseline, optimized) },
        impacts: { my: calculateCropImpacts(baseline, my), optimized: calculateCropImpacts(baseline, optimized) },
        constraints: { my: validateConstraints(myAreas, presetId) },
        optimizedNote: {
          optimizedUnder: deepCopy(preset.evaluated_under),
          objective: preset.objective,
          reoptimized: false,
          sameAsSelected: climate === preset.evaluated_under.climate && efficiency === preset.evaluated_under.efficiency,
        },
      };
    }

    /** Independent deep copy of a scenario (or any plain data); the original is never touched. */
    function cloneScenario(scenario) {
      return deepCopy(scenario);
    }

    return Object.freeze({
      LEVELS, cropIds,
      evaluate, compareScenarios, calculateChanges, validateAreas, validateConstraints,
      calculateCropImpacts, cloneScenario,
    });
  }

  return Object.freeze({ createSimCore, SimCoreError, LEVELS, M3_PER_KM3 });
});
