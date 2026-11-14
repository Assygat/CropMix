/* CropMix Twin — evaluation conditions for the simulator (module 10, stage 6).
 *
 * Conditions = climate C (mean 2010–2025 or one year) + efficiency scenario E (field | canal | rice percolation).
 * Options come only from web/data/simulator.json (the same 17 × 36 keys as model.json); nothing is computed here.
 * Conditions are immutable values shared by the editor and the comparison, so all three scenarios are always
 * evaluated under the same C and E. Works in the browser (window.CropMixConditions) and in Node.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CropMixConditions = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const REFERENCE = Object.freeze({ climate: "mean", efficiency: "base|base|base" });
  const PARTS = Object.freeze(["field", "canal", "percolation"]);
  const NOTES = { canal: { pessimistic: "pessimistic scenario level" } };

  const fmtEff = (v) => (Math.round(v * 100) === v * 100 ? v.toFixed(2) : String(v));

  /** Climate and efficiency options from simulator.json "scenarios". */
  function createOptions(sim) {
    const sc = sim.scenarios;
    const lv = sc.efficiency_levels;
    const level = (part, l) => Object.freeze({ id: l.id, value: l.value, note: (NOTES[part] || {})[l.id] || null,
      label: part === "percolation" ? `${l.value} mm/day` : fmtEff(l.value) });
    const opts = {
      climates: Object.freeze(sc.climate.map((c) => Object.freeze({ key: c.key, label: c.label }))),
      field: Object.freeze(lv.eff_field.map((l) => level("field", l))),
      canal: Object.freeze(lv.eff_canal.map((l) => level("canal", l))),
      percolation: Object.freeze(lv.rice_percolation_mm_day.map((l) => level("percolation", l))),
      efficiencyKeys: new Set(sc.efficiency.map((e) => e.key)),
      climateKeys: new Set(sc.climate.map((c) => c.key)),
      efficiencyStatus: Object.freeze(Object.fromEntries(sc.efficiency.map((e) => [e.key, e.status]))),
    };
    return Object.freeze(opts);
  }

  function composeKey(parts) {
    return `${parts.field}|${parts.canal}|${parts.percolation}`;
  }

  function parseKey(key) {
    const p = String(key).split("|");
    if (p.length !== 3 || p.some((x) => x === "")) throw new Error("Malformed efficiency key " + key);
    return { field: p[0], canal: p[1], percolation: p[2] };
  }

  function allEfficiencyKeys(opts) {
    const out = [];
    for (const f of opts.field) for (const c of opts.canal) for (const p of opts.percolation) {
      out.push(composeKey({ field: f.id, canal: c.id, percolation: p.id }));
    }
    return out;
  }

  /** All 17 × 36 = 612 (climate, efficiency) pairs. */
  function allCombinations(opts) {
    const effs = allEfficiencyKeys(opts);
    const out = [];
    for (const c of opts.climates) for (const e of effs) out.push({ climate: c.key, efficiency: e });
    return out;
  }

  function makeConditions(opts, climate, efficiency) {
    if (typeof climate !== "string" || !opts.climateKeys.has(climate)) throw new Error("Unknown climate " + climate);
    if (typeof efficiency !== "string" || !opts.efficiencyKeys.has(efficiency)) throw new Error("Unknown efficiency " + efficiency);
    return Object.freeze({ climate, efficiency });
  }

  function reference(opts) {
    return makeConditions(opts, REFERENCE.climate, REFERENCE.efficiency);
  }

  function isReference(cond) {
    return cond.climate === REFERENCE.climate && cond.efficiency === REFERENCE.efficiency;
  }

  function withClimate(opts, cond, climate) {
    if (cond.climate === climate) return cond;
    return makeConditions(opts, climate, cond.efficiency);
  }

  function withEfficiencyPart(opts, cond, part, id) {
    if (!PARTS.includes(part)) throw new Error("Unknown efficiency part " + part);
    const parts = parseKey(cond.efficiency);
    if (parts[part] === id) return cond;
    if (!opts[part].some((l) => l.id === id)) throw new Error(`Unknown efficiency level ${part}=${id}`);
    return makeConditions(opts, cond.climate, composeKey(Object.assign({}, parts, { [part]: id })));
  }

  function levelOf(opts, part, id) {
    return opts[part].find((l) => l.id === id);
  }

  /** Full, explicit text of the conditions (shown wherever results are shown). */
  function describe(opts, cond) {
    const p = parseKey(cond.efficiency);
    const canal = levelOf(opts, "canal", p.canal);
    return [
      cond.climate === "mean" ? "Mean climate 2010–2025" : `Climate of ${cond.climate}`,
      `field efficiency ${levelOf(opts, "field", p.field).label}`,
      `canal efficiency ${canal.label}${canal.note ? " (pessimistic)" : ""}`,
      `rice percolation ${levelOf(opts, "percolation", p.percolation).label}`,
    ].join(" · ");
  }

  return Object.freeze({
    REFERENCE, PARTS, createOptions, composeKey, parseKey, allEfficiencyKeys, allCombinations,
    makeConditions, reference, isReference, withClimate, withEfficiencyPart, levelOf, describe,
  });
});
