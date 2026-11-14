// Тесты web/sim_conditions.js (модуль 10, этап 6): варианты климата и КПД, ключи, эталонные условия.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const C = require(path.join(ROOT, "web", "sim_conditions.js"));
const read = (n) => JSON.parse(fs.readFileSync(path.join(ROOT, "web", "data", n), "utf8"));
const SIM = read("simulator.json");
const MODEL = read("model.json");
const opts = C.createOptions(SIM);

test("options: 17 climates (mean first) and 3 x 4 x 3 = 36 efficiency keys equal to model.json", () => {
  assert.equal(opts.climates.length, 17);
  assert.equal(opts.climates[0].key, "mean");
  assert.deepEqual(opts.climates.map((c) => c.key), ["mean", ...MODEL.years]);
  assert.equal(opts.field.length, 3);
  assert.equal(opts.canal.length, 4);
  assert.equal(opts.percolation.length, 3);
  const keys = C.allEfficiencyKeys(opts);
  assert.equal(keys.length, 36);
  assert.deepEqual([...keys].sort(), Object.keys(MODEL.coef_m3_ha).sort());
  assert.equal(C.allCombinations(opts).length, 612);
});

test("labels carry the real values and statuses from simulator.json", () => {
  assert.deepEqual(opts.field.map((l) => l.value), [0.5, 0.6, 0.7]);
  assert.deepEqual(opts.canal.map((l) => l.value), [0.4, 0.5, 0.575, 0.65]);
  assert.deepEqual(opts.percolation.map((l) => l.value), [4, 6, 8]);
  assert.equal(opts.canal.find((l) => l.id === "pessimistic").note, "pessimistic scenario level");
  assert.ok(opts.climates.every((c) => typeof c.label === "string" && c.label.length > 0));
});

test("compose and parse an efficiency key round-trip; unknown parts are rejected", () => {
  for (const key of C.allEfficiencyKeys(opts)) assert.equal(C.composeKey(C.parseKey(key)), key);
  assert.deepEqual(C.parseKey("low|pessimistic|high"), { field: "low", canal: "pessimistic", percolation: "high" });
  assert.throws(() => C.parseKey("low|base"), /efficiency key/);
  assert.throws(() => C.makeConditions(opts, "mean", "base|base|ultra"), /Unknown efficiency/);
  assert.throws(() => C.makeConditions(opts, "2030", "base|base|base"), /Unknown climate/);
  assert.throws(() => C.makeConditions(opts, "constructor", "base|base|base"), /Unknown climate/);
});

test("reference conditions are Cmean / E_base and detected as such", () => {
  const ref = C.reference(opts);
  assert.deepEqual({ climate: ref.climate, efficiency: ref.efficiency }, { climate: "mean", efficiency: "base|base|base" });
  assert.equal(C.isReference(ref), true);
  assert.equal(C.isReference(C.withClimate(opts, ref, "2016")), false);
  assert.equal(C.isReference(C.withEfficiencyPart(opts, ref, "canal", "pessimistic")), false);
});

test("updates return new frozen objects and never mutate the previous conditions", () => {
  const ref = C.reference(opts);
  const a = C.withClimate(opts, ref, "2021");
  const b = C.withEfficiencyPart(opts, a, "field", "low");
  const c = C.withEfficiencyPart(opts, b, "percolation", "high");
  assert.deepEqual([ref.climate, ref.efficiency], ["mean", "base|base|base"]);
  assert.deepEqual([c.climate, c.efficiency], ["2021", "low|base|high"]);
  assert.ok(Object.isFrozen(c));
  assert.equal(C.withClimate(opts, c, "2021"), c);                       // без изменений — тот же объект
  assert.throws(() => C.withEfficiencyPart(opts, c, "drip", "low"), /Unknown efficiency part/);
  assert.throws(() => C.withEfficiencyPart(opts, c, "canal", "huge"), /Unknown efficiency/);
});

test("describe() states every condition explicitly", () => {
  const ref = C.reference(opts);
  assert.equal(C.describe(opts, ref), "Mean climate 2010–2025 · field efficiency 0.60 · canal efficiency 0.575 · rice percolation 6 mm/day");
  const p = C.withEfficiencyPart(opts, C.withClimate(opts, ref, "2021"), "canal", "pessimistic");
  assert.equal(C.describe(opts, p), "Climate of 2021 · field efficiency 0.60 · canal efficiency 0.40 (pessimistic) · rice percolation 6 mm/day");
});
