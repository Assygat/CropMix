// Тесты чистых функций web/sim_compare.js (модуль 10, этап 6): экономия, разницы сценариев, диапазон по 612 условиям.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const read = (n) => JSON.parse(fs.readFileSync(path.join(ROOT, "web", "data", n), "utf8"));
const deepFreeze = (o) => { if (o && typeof o === "object" && !Object.isFrozen(o)) { Object.freeze(o); Object.values(o).forEach(deepFreeze); } return o; };
const MODEL = deepFreeze(read("model.json"));
const SIM = deepFreeze(read("simulator.json"));
const core = require(path.join(ROOT, "web", "sim_core.js")).createSimCore(MODEL, SIM);
const Cond = require(path.join(ROOT, "web", "sim_conditions.js"));
const X = require(path.join(ROOT, "web", "sim_compare.js"));
const opts = Cond.createOptions(SIM);
const COMBOS = Cond.allCombinations(opts);
const BASE = SIM.baseline.areas_ha;
const LEVELS = ["plant", "field", "river"];
const MY = deepFreeze(Object.assign({}, BASE, { rice: BASE.rice * 0.8, fodder: BASE.fodder + BASE.rice * 0.2 }));

test("saving = (Baseline − Scenario) / Baseline × 100; negative means more water; null when baseline is 0", () => {
  const b = core.evaluate(BASE, "2016", "low|high|base");
  const s = core.evaluate(MY, "2016", "low|high|base");
  const ch = core.calculateChanges(b, s);
  assert.equal(X.savingPct(ch.river), 100 * (b.m3.river - s.m3.river) / b.m3.river);
  const more = core.evaluate(Object.assign({}, BASE, { rice: BASE.rice * 1.2 }), "2016", "low|high|base");
  assert.ok(X.savingPct(core.calculateChanges(b, more).river) < 0);
  assert.equal(X.savingPct({ pct: null }), null);
  assert.equal(X.savingPct({ pct: 0 }), 0);                           // не −0
});

test("My = Baseline gives zero differences and zero saving on every level", () => {
  const r = X.compareAll(core, BASE, "moderate", { climate: "2021", efficiency: "low|pessimistic|high" });
  for (const l of LEVELS) {
    assert.equal(r.cmp.changes.my[l].abs_m3, 0);
    assert.equal(r.saving.my[l], 0);
    assert.ok(Number.isFinite(r.myVsOptimized[l].pct));
  }
});

test("My − Optimized = (My − Baseline) − (Optimized − Baseline) on all levels for all 612 conditions", () => {
  for (const c of COMBOS) {
    const r = X.compareAll(core, MY, "flexible", c);
    for (const l of LEVELS) {
      const lhs = r.myVsOptimized[l].abs_m3;
      const rhs = r.cmp.changes.my[l].abs_m3 - r.cmp.changes.optimized[l].abs_m3;
      assert.ok(Math.abs(lhs - rhs) <= 1e-3, `${c.climate} ${c.efficiency} ${l}`);   // 1e-3 м³ = 1e-12 км³
    }
  }
});

test("crop impacts sum to the total change and Optimized areas never change, for all 612 conditions", () => {
  for (const c of COMBOS) {
    const r = X.compareAll(core, MY, "tight", c);
    assert.deepEqual(r.cmp.scenarios.optimized.areas, SIM.optimized.presets.tight.areas_ha);
    assert.equal(r.cmp.optimizedNote.reoptimized, false);
    for (const who of ["my", "optimized"]) {
      const imp = r.cmp.impacts[who];
      const sum = Object.values(imp.byCrop).reduce((t, v) => t + v.river, 0);
      assert.ok(Math.abs(sum - r.cmp.changes[who].river.abs_m3) <= 1e-3);
    }
  }
});

test("all three scenarios share the selected climate and efficiency", () => {
  const r = X.compareAll(core, MY, "moderate", { climate: "2013", efficiency: "base|low|low" });
  for (const s of ["baseline", "my", "optimized"]) {
    assert.equal(r.cmp.scenarios[s].climate, "2013");
    assert.equal(r.cmp.scenarios[s].efficiency, "base|low|low");
  }
});

test("saving range over 612 conditions: n, bounds contain the reference value, argmin/argmax are real conditions", () => {
  for (const pid of ["tight", "moderate", "flexible"]) {
    const range = X.savingRange(core, COMBOS, MY, pid);
    assert.equal(range.n, 612);
    const ref = X.compareAll(core, MY, pid, { climate: "mean", efficiency: "base|base|base" });
    for (const who of ["my", "optimized"]) {
      const r = range[who];
      assert.ok(r.min <= ref.saving[who].river && ref.saving[who].river <= r.max, `${pid} ${who}`);
      for (const at of [r.minAt, r.maxAt]) {
        const v = X.compareAll(core, MY, pid, at).saving[who].river;
        assert.equal(v, at === r.minAt ? r.min : r.max);
      }
    }
  }
});

test("sign convention holds at the extremes: negative saving ⇔ scenario withdraws more than Baseline", () => {
  // Факт модели (не допущение теста): при низком КПД полива и низкой перколяции риса Optimized может брать
  // больше воды, чем Baseline, — забор на рис не зависит от КПД полива. Диапазон обязан это показывать.
  for (const pid of ["tight", "moderate", "flexible"]) {
    const range = X.savingRange(core, COMBOS, BASE, pid);
    for (const at of [range.optimized.minAt, range.optimized.maxAt]) {
      const r = X.compareAll(core, BASE, pid, at);
      const more = r.cmp.scenarios.optimized.m3.river > r.cmp.scenarios.baseline.m3.river;
      assert.equal(r.saving.optimized.river < 0, more, `${pid} ${at.climate} ${at.efficiency}`);
    }
    assert.ok(range.optimized.min < range.optimized.max);
  }
});

test("axis maximum is the smallest nice value >= data (7.5 and 8 allowed) and ticks are round", () => {
  assert.equal(X.niceMax(7.30), 7.5);
  assert.equal(X.niceMax(7.6), 8);
  assert.equal(X.niceMax(8.01), 10);
  assert.equal(X.niceMax(12.18), 20);          // pessimistic canal efficiency: never clipped
  assert.equal(X.niceMax(4.75), 5);
  assert.equal(X.niceMax(0), 1);
  assert.deepEqual(X.axisTicks(7.5), [0, 2.5, 5, 7.5]);
  assert.deepEqual(X.axisTicks(8), [0, 2, 4, 6, 8]);
  assert.deepEqual(X.axisTicks(10), [0, 2, 4, 6, 8, 10]);
  assert.deepEqual(X.axisTicks(20), [0, 5, 10, 15, 20]);
  assert.deepEqual(X.axisTicks(2.5), [0, 0.5, 1, 1.5, 2, 2.5]);
  // over all 612 conditions and all three presets the axis is >= the largest of the nine values
  for (const pid of ["tight", "moderate", "flexible"]) for (const c of COMBOS) {
    const r = X.compareAll(core, MY, pid, c);
    const top = Math.max(...["baseline", "my", "optimized"].map((s) => r.cmp.scenarios[s].km3.river));
    const m = X.niceMax(top);
    assert.ok(m >= top && m < 2 * top + 1e-9, `${pid} ${c.climate} ${c.efficiency}`);
  }
});

test("inputs are not mutated", () => {
  const before = JSON.stringify(MY);
  X.savingRange(core, COMBOS.slice(0, 20), MY, "moderate");
  X.compareAll(core, MY, "moderate", COMBOS[5]);
  assert.equal(JSON.stringify(MY), before);
});
