// Тесты web/sim_core.js (модуль 10, этап 3). Запуск: node --test tests/js/
// Без зависимостей: node:test + node:assert. Данные — реальные web/data/model.json и simulator.json.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const SimCore = require(path.join(ROOT, "web", "sim_core.js"));
const readJson = (name) => JSON.parse(fs.readFileSync(path.join(ROOT, "web", "data", name), "utf8"));
const MODEL = readJson("model.json");
const SIM = readJson("simulator.json");
const CROPS = MODEL.crops.map((c) => c.id);
const LEVELS = ["plant", "field", "river"];
const PRESETS = ["tight", "moderate", "flexible"];
const KM3_TOL = 1e-12;            // требование этапа 3: |JS − Python| ≤ 1e-12 км³

function deepFreeze(o) {
  if (o && typeof o === "object" && !Object.isFrozen(o)) {
    Object.freeze(o);
    Object.values(o).forEach(deepFreeze);
  }
  return o;
}

// Входы замораживаются: любая мутация внутри ядра бросит TypeError (strict mode).
deepFreeze(MODEL);
deepFreeze(SIM);
const core = SimCore.createSimCore(MODEL, SIM);
const BASE = SIM.baseline.areas_ha;

// Ручной эталон: Σ A·k напрямую из model.json, независимо от ядра.
function manual(areas, climate, eff) {
  const k = MODEL.coef_m3_ha[eff][climate];
  const out = { plant: 0, field: 0, river: 0 };
  for (const c of CROPS) LEVELS.forEach((l, i) => { out[l] += areas[c] * k[c][i]; });
  return out;
}

test("baseline at Cmean/E_base equals the Python planning base 7.30 km3", () => {
  const r = core.evaluate(BASE, "mean", "base|base|base");
  const pythonBase = SIM.optimized.presets.tight.base_river_m3;      // из optimizer_feasibility.csv (Python)
  assert.ok(Math.abs(r.km3.river - pythonBase / 1e9) <= KM3_TOL);
  assert.equal(r.km3.river.toFixed(2), "7.30");
  assert.equal(r.km3.river, r.m3.river / 1e9);                       // единицы: м³ → км³ делением на 1e9
});

for (const pid of PRESETS) {
  test(`optimized preset ${pid} reproduces Python optimum at Cmean/E_base`, () => {
    const p = SIM.optimized.presets[pid];
    const r = core.evaluate(p.areas_ha, "mean", "base|base|base");
    assert.ok(Math.abs(r.km3.river - p.optimized_river_m3 / 1e9) <= KM3_TOL);
  });
}

test("all 36 efficiency x 17 climate scenarios evaluate and match the manual sum", () => {
  const effs = SIM.scenarios.efficiency.map((e) => e.key);
  const clims = SIM.scenarios.climate.map((c) => c.key);
  assert.equal(effs.length, 36);
  assert.equal(clims.length, 17);
  for (const e of effs) for (const c of clims) {
    const r = core.evaluate(BASE, c, e);
    const m = manual(BASE, c, e);
    for (const l of LEVELS) assert.ok(Math.abs(r.km3[l] - m[l] / 1e9) <= KM3_TOL, `${e} ${c} ${l}`);
    assert.ok(r.m3.plant <= r.m3.field && r.m3.field <= r.m3.river, `levels ordered ${e} ${c}`);
  }
});

test("zero area change gives exactly zero water change", () => {
  const a = core.evaluate(BASE, "2016", "low|high|base");
  const b = core.evaluate(core.cloneScenario(BASE), "2016", "low|high|base");
  const ch = core.calculateChanges(a, b);
  for (const l of LEVELS) {
    assert.equal(ch[l].abs_m3, 0);
    assert.equal(ch[l].pct, 0);
  }
  const imp = core.calculateCropImpacts(a, b);
  for (const c of CROPS) for (const l of LEVELS) assert.equal(imp.byCrop[c][l], 0);
});

test("changing one crop changes each level by delta area x coefficient", () => {
  const combos = [["mean", "base|base|base"], ["2021", "low|pessimistic|high"], ["2010", "high|high|low"]];
  for (const [clim, eff] of combos) {
    const my = Object.assign({}, BASE, { rice: BASE.rice - 1000, wheat: BASE.wheat + 1000 });
    const ch = core.calculateChanges(core.evaluate(BASE, clim, eff), core.evaluate(my, clim, eff));
    const k = MODEL.coef_m3_ha[eff][clim];
    LEVELS.forEach((l, i) => {
      const expected = -1000 * k.rice[i] + 1000 * k.wheat[i];
      assert.ok(Math.abs(ch[l].abs_m3 - expected) <= 1e-3, `${clim} ${eff} ${l}`);   // 1e-3 м³ = 1e-12 км³
    });
    assert.ok(ch.river.abs_m3 < 0);             // рис требует больше воды, чем пшеница
  }
});

test("sum of per-crop impacts equals the total change on every level", () => {
  for (const pid of PRESETS) for (const [clim, eff] of [["mean", "base|base|base"], ["2016", "high|low|low"]]) {
    const b = core.evaluate(BASE, clim, eff);
    const o = core.evaluate(SIM.optimized.presets[pid].areas_ha, clim, eff);
    const imp = core.calculateCropImpacts(b, o);
    const ch = core.calculateChanges(b, o);
    for (const l of LEVELS) {
      const sum = CROPS.reduce((s, c) => s + imp.byCrop[c][l], 0);
      assert.ok(Math.abs(sum - ch[l].abs_m3) <= 1e-3, `${pid} ${l}`);
      assert.ok(Math.abs(imp.total[l] - ch[l].abs_m3) <= 1e-3);
    }
  }
});

test("negative, NaN, Infinity, non-number areas are rejected", () => {
  const bad = { negative: -1, nan: NaN, inf: Infinity, ninf: -Infinity, str: "100", nul: null };
  for (const [name, v] of Object.entries(bad)) {
    const a = Object.assign({}, BASE, { rice: v });
    const res = core.validateAreas(a);
    assert.equal(res.ok, false, name);
    assert.equal(res.errors[0].crop, "rice");
    assert.throws(() => core.evaluate(a, "mean", "base|base|base"), { code: "INVALID_AREAS" }, name);
    const cons = core.validateConstraints(a, "tight");             // проверка ограничений сообщает, а не бросает
    assert.equal(cons.ok, false, name);
    assert.equal(cons.violations[0].type, "areas");
    assert.equal(cons.violations[0].crop, "rice");
  }
  assert.equal(core.validateAreas(BASE).ok, true);
  assert.equal(core.validateAreas(Object.assign({}, BASE, { rice: 0 })).ok, true);   // ноль допустим
});

test("missing crop, unknown crop, unknown climate or efficiency are reported", () => {
  const missing = Object.assign({}, BASE);
  delete missing.melons;
  assert.equal(core.validateAreas(missing).errors[0].code, "MISSING_CROP");
  assert.equal(core.validateAreas(Object.assign({}, BASE, { cotton: 5 })).errors[0].code, "UNKNOWN_CROP");
  assert.equal(core.validateAreas(null).errors[0].code, "NOT_AN_OBJECT");
  assert.throws(() => core.evaluate(BASE, "2030", "base|base|base"), { code: "UNKNOWN_CLIMATE" });
  assert.throws(() => core.evaluate(BASE, "mean", "base|base|ultra"), { code: "UNKNOWN_EFFICIENCY" });
  assert.throws(() => core.evaluate(BASE, "constructor", "base|base|base"), { code: "UNKNOWN_CLIMATE" });
  assert.throws(() => core.validateConstraints(BASE, "extreme"), { code: "UNKNOWN_PRESET" });
});

test("inputs are never mutated and results are independent copies", () => {
  const my = deepFreeze(Object.assign({}, BASE, { rice: 70000 }));
  const r = core.evaluate(my, "mean", "base|base|base");
  r.areas.rice = 1;                       // правка результата не трогает вход
  assert.equal(my.rice, 70000);
  const cmp = core.compareScenarios(my, "moderate", "2018", "low|base|base");
  assert.equal(cmp.scenarios.baseline.areas.rice, BASE.rice);
  const clone = core.cloneScenario({ name: "A", areas: my });
  clone.areas.rice = 5;
  assert.equal(my.rice, 70000);
  assert.notEqual(clone.areas, my);
});

test("switching climate/efficiency changes water but not areas; all three under the same C and E", () => {
  const my = Object.assign({}, BASE, { rice: 75000, fodder: 76796.6 });
  const a = core.compareScenarios(my, "flexible", "mean", "base|base|base");
  const b = core.compareScenarios(my, "flexible", "2021", "low|low|high");
  for (const s of ["baseline", "my", "optimized"]) {
    assert.deepEqual(a.scenarios[s].areas, b.scenarios[s].areas);
    assert.notEqual(a.scenarios[s].m3.river, b.scenarios[s].m3.river);
    assert.equal(b.scenarios[s].climate, "2021");
    assert.equal(b.scenarios[s].efficiency, "low|low|high");
  }
  assert.deepEqual(b.scenarios.optimized.areas, SIM.optimized.presets.flexible.areas_ha);   // не переоптимизируется
  assert.equal(b.optimizedNote.reoptimized, false);
  assert.deepEqual(b.optimizedNote.optimizedUnder, { climate: "mean", efficiency: "base|base|base" });
  // экономия — от Baseline при тех же C и E
  const expected = b.scenarios.optimized.m3.river - b.scenarios.baseline.m3.river;
  assert.ok(Math.abs(b.changes.optimized.river.abs_m3 - expected) <= 1e-3);
  assert.throws(() => core.calculateChanges(a.scenarios.baseline, b.scenarios.my), { code: "SCENARIO_MISMATCH" });
});

test("preset constraints: each optimum satisfies its own preset; stricter presets reject flexible's structure", () => {
  for (const pid of PRESETS) {
    assert.equal(core.validateConstraints(SIM.optimized.presets[pid].areas_ha, pid).ok, true, pid);
    assert.equal(core.validateConstraints(BASE, pid).ok, true, `baseline within ${pid}`);
  }
  const t = core.validateConstraints(SIM.optimized.presets.flexible.areas_ha, "tight");
  assert.equal(t.ok, false);
  assert.ok(t.violations.some((v) => v.type === "corridor" && v.crop === "rice"));
  assert.equal(core.validateConstraints(SIM.optimized.presets.flexible.areas_ha, "moderate").ok, false);
  // tight-оптимум укладывается во все более мягкие пресеты
  for (const pid of PRESETS) assert.equal(core.validateConstraints(SIM.optimized.presets.tight.areas_ha, pid).ok, true);
  // общая площадь — равенство: +1 000 га к рису нарушает его во всех пресетах
  for (const pid of PRESETS) {
    const r = core.validateConstraints(Object.assign({}, BASE, { rice: BASE.rice + 1000 }), pid);
    assert.ok(r.violations.some((v) => v.type === "total_area"), pid);
  }
});

test("food-crop minimum checked against each preset share (hand example)", () => {
  const FOOD = ["rice", "wheat", "potato", "vegetables_open", "melons"];
  assert.deepEqual(SIM.crops.filter((c) => c.food_crop).map((c) => c.id).sort(), [...FOOD].sort());
  const foodBase = FOOD.reduce((s, c) => s + BASE[c], 0);
  const my = Object.assign({}, BASE);
  for (const c of FOOD) my[c] = BASE[c] * 0.55;       // 55 % продовольственных: < 60 % flexible
  const expectedShare = { tight: 0.95, moderate: 0.8, flexible: 0.6 };
  for (const pid of PRESETS) {
    const check = core.validateConstraints(my, pid).checks.find((c) => c.type === "food_min");
    assert.ok(Math.abs(check.value - 0.55 * foodBase) < 1e-6);
    assert.ok(Math.abs(check.min - expectedShare[pid] * foodBase) < 1e-6, pid);
    assert.equal(check.ok, false, pid);
  }
  // 65 % проходит в flexible, но не в moderate
  for (const c of FOOD) my[c] = BASE[c] * 0.65;
  const f = (pid) => core.validateConstraints(my, pid).checks.find((c) => c.type === "food_min").ok;
  assert.equal(f("flexible"), true);
  assert.equal(f("moderate"), false);
});

test("no division by zero: zero baseline gives pct = null, not NaN/Infinity", () => {
  const zero = Object.fromEntries(CROPS.map((c) => [c, 0]));
  const z = core.evaluate(zero, "mean", "base|base|base");
  const b = core.evaluate(BASE, "mean", "base|base|base");
  const ch = core.calculateChanges(z, b);
  for (const l of LEVELS) {
    assert.equal(ch[l].pct, null);
    assert.ok(Number.isFinite(ch[l].abs_m3));
  }
  const imp = core.calculateCropImpacts(z, z);
  for (const c of CROPS) assert.equal(imp.shareOfChange[c].river, null);
  assert.ok(!/NaN|Infinity/.test(JSON.stringify([ch, imp, z])));
  assert.equal(core.validateConstraints(zero, "tight").ok, false);   // нулевая структура не проходит, но без NaN
  assert.ok(!/NaN|Infinity/.test(JSON.stringify(core.validateConstraints(zero, "tight"))));
});

test("no hidden rounding: values are full precision and km3 = m3 / 1e9", () => {
  const r = core.evaluate(SIM.optimized.presets.tight.areas_ha, "2013", "base|low|low");
  const m = manual(SIM.optimized.presets.tight.areas_ha, "2013", "base|low|low");
  for (const l of LEVELS) {
    assert.ok(Math.abs(r.m3[l] - m[l]) <= 1e-3);
    assert.equal(r.km3[l], r.m3[l] / 1e9);
    assert.notEqual(r.m3[l], Math.round(r.m3[l] / 1e6) * 1e6);   // не округлено до млн м³
  }
  const b = core.evaluate(BASE, "2013", "base|low|low");
  const ch = core.calculateChanges(b, r);
  assert.equal(ch.river.pct, 100 * ch.river.abs_m3 / b.m3.river);
});

test("cloneScenario returns a deep independent copy and keeps the base structure untouched", () => {
  const scenario = { id: "s1", name: "My scenario", areas: Object.assign({}, BASE), history: [{ rice: 1 }] };
  const copy = core.cloneScenario(scenario);
  assert.deepEqual(copy, scenario);
  copy.areas.rice = 0;
  copy.history[0].rice = 2;
  assert.equal(scenario.areas.rice, BASE.rice);
  assert.equal(scenario.history[0].rice, 1);
  assert.equal(SIM.baseline.areas_ha.rice, BASE.rice);
});
