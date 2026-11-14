// Тесты web/sim_state.js (модуль 10, этап 5): состояние редактора, Undo/Reset, разбор ввода, форматирование.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const S = require(path.join(ROOT, "web", "sim_state.js"));
const SIM = JSON.parse(fs.readFileSync(path.join(ROOT, "web", "data", "simulator.json"), "utf8"));
const BASE = Object.freeze(Object.assign({}, SIM.baseline.areas_ha));

test("initial state copies the baseline and has nothing to undo", () => {
  const s = S.createEditorState(BASE, "moderate");
  assert.deepEqual(s.areas, BASE);
  assert.notEqual(s.areas, BASE);
  assert.equal(s.preset, "moderate");
  assert.equal(S.canUndo(s), false);
  assert.deepEqual(S.changedCrops(s.areas, BASE), []);
});

test("applyArea returns a new state, keeps full precision, never mutates the old state or the baseline", () => {
  const s0 = S.createEditorState(BASE, "tight");
  const s1 = S.applyArea(s0, "rice", 70000.123456789, 1000);
  assert.equal(s1.areas.rice, 70000.123456789);                // без округления
  assert.equal(s0.areas.rice, BASE.rice);
  assert.equal(BASE.rice, SIM.baseline.areas_ha.rice);
  assert.deepEqual(S.changedCrops(s1.areas, BASE), ["rice"]);
  assert.equal(S.canUndo(s1), true);
});

test("edits to the same crop within the coalescing window are one undo step; other crops are separate", () => {
  let s = S.createEditorState(BASE, "tight");
  s = S.applyArea(s, "rice", 80000, 0);
  s = S.applyArea(s, "rice", 79000, 300);         // та же культура, < окна — склеивается
  s = S.applyArea(s, "rice", 78000, 600);
  s = S.applyArea(s, "wheat", 12000, 700);        // другая культура — новый шаг
  assert.equal(s.history.length, 2);
  s = S.undo(s);
  assert.equal(s.areas.wheat, BASE.wheat);
  assert.equal(s.areas.rice, 78000);
  s = S.undo(s);
  assert.deepEqual(s.areas, BASE);
  assert.equal(S.canUndo(s), false);
  assert.deepEqual(S.undo(s), s);                 // пустая история — без изменений
});

test("separate edits after the window are separate undo steps", () => {
  let s = S.createEditorState(BASE, "tight");
  s = S.applyArea(s, "melons", 9000, 0);
  s = S.applyArea(s, "melons", 9500, S.COALESCE_MS + 1);
  assert.equal(s.history.length, 2);
  assert.equal(S.undo(s).areas.melons, 9000);
});

test("setting the same value adds no history step", () => {
  const s = S.createEditorState(BASE, "tight");
  assert.equal(S.applyArea(s, "rice", BASE.rice, 0), s);
});

test("reset to baseline is undoable and is a no-op when nothing changed", () => {
  let s = S.createEditorState(BASE, "flexible");
  assert.equal(S.resetToBaseline(s, BASE), s);
  s = S.applyArea(s, "fodder", 90000, 0);
  s = S.applyArea(s, "oilseeds", 0, 5000);
  const r = S.resetToBaseline(s, BASE);
  assert.deepEqual(r.areas, BASE);
  const back = S.undo(r);
  assert.equal(back.areas.fodder, 90000);
  assert.equal(back.areas.oilseeds, 0);
});

test("setPreset changes only the preset, not areas or history", () => {
  const s = S.applyArea(S.createEditorState(BASE, "tight"), "rice", 60000, 0);
  const p = S.setPreset(s, "flexible");
  assert.equal(p.preset, "flexible");
  assert.deepEqual(p.areas, s.areas);
  assert.equal(p.history, s.history);
  assert.throws(() => S.setPreset(s, "extreme"), /Unknown preset/);
});

test("history is capped", () => {
  let s = S.createEditorState(BASE, "tight");
  for (let i = 0; i < S.HISTORY_LIMIT + 20; i++) s = S.applyArea(s, i % 2 ? "rice" : "wheat", 1000 + i, i * 10000);
  assert.equal(s.history.length, S.HISTORY_LIMIT);
});

test("applyArea rejects invalid values and unknown crops", () => {
  const s = S.createEditorState(BASE, "tight");
  for (const bad of [-1, NaN, Infinity, -Infinity, "5", null, undefined]) {
    assert.throws(() => S.applyArea(s, "rice", bad, 0), /non-negative finite/);
  }
  assert.throws(() => S.applyArea(s, "cotton", 5, 0), /Unknown crop/);
  assert.equal(S.applyArea(s, "rice", 0, 0).areas.rice, 0);            // ноль допустим
});

test("replaceAreas (Start from Optimized) is one undo step, copies values and never shares the source object", () => {
  const OPT = Object.freeze(Object.assign({}, SIM.optimized.presets.moderate.areas_ha));
  let s = S.applyArea(S.createEditorState(BASE, "moderate"), "melons", 9000, 0);
  const r = S.replaceAreas(s, OPT);
  assert.deepEqual(r.areas, OPT);
  assert.notEqual(r.areas, OPT);
  assert.equal(r.history.length, s.history.length + 1);
  assert.equal(S.undo(r).areas.melons, 9000);                          // одним шагом назад
  assert.deepEqual(OPT, SIM.optimized.presets.moderate.areas_ha);       // источник не тронут
  assert.equal(S.replaceAreas(r, OPT), r);                              // то же самое — без шага
  assert.throws(() => S.replaceAreas(s, Object.assign({}, OPT, { rice: -1 })), /non-negative finite/);
  const missing = Object.assign({}, OPT);
  delete missing.rice;
  assert.throws(() => S.replaceAreas(s, missing), /same crops/);
  assert.throws(() => S.replaceAreas(s, Object.assign({}, OPT, { cotton: 1 })), /same crops/);
});

test("parseAreaInput: plain numbers, thousands separators, decimals; rejects negatives, text, empty, infinity", () => {
  assert.deepEqual(S.parseAreaInput("81696.6"), { ok: true, value: 81696.6 });
  assert.deepEqual(S.parseAreaInput(" 81,696.6 "), { ok: true, value: 81696.6 });
  assert.deepEqual(S.parseAreaInput("0"), { ok: true, value: 0 });
  assert.deepEqual(S.parseAreaInput("1 600"), { ok: true, value: 1600 });
  for (const [text, code] of [["", "EMPTY"], ["  ", "EMPTY"], ["-5", "NEGATIVE"], ["−5", "NEGATIVE"], ["abc", "NOT_A_NUMBER"],
    ["12abc", "NOT_A_NUMBER"], ["1e400", "NOT_FINITE"], ["Infinity", "NOT_A_NUMBER"], ["NaN", "NOT_A_NUMBER"], ["1.2.3", "NOT_A_NUMBER"]]) {
    const r = S.parseAreaInput(text);
    assert.equal(r.ok, false, text);
    assert.equal(r.code, code, text);
    assert.ok(r.message.length > 0);
  }
});

test("niceStep gives 1-2-5 steps and stepArea never goes below zero", () => {
  assert.equal(S.niceStep(1634), 1000);
  assert.equal(S.niceStep(32), 20);
  assert.equal(S.niceStep(5.5), 5);
  assert.equal(S.niceStep(0), 1);
  assert.equal(S.stepArea(1600, 500, -1), 1100);
  assert.equal(S.stepArea(300, 500, -1), 0);
  assert.equal(S.stepArea(81696.6, 1000, 1), 82696.6);                 // шаг не округляет значение
});

test("formatting is for display only and handles signs, small values and nulls", () => {
  assert.equal(S.fmt.ha(81696.6), "81,700");
  assert.equal(S.fmt.ha(4), "0");
  assert.equal(S.fmt.ha(6), "10");
  assert.equal(S.fmt.signedHa(-1234), "−1,230");
  assert.equal(S.fmt.signedHa(0), "0");
  assert.equal(S.fmt.km3(7.304938), "7.30");
  assert.equal(S.fmt.signedKm3(-0.0441), "−0.04");
  assert.equal(S.fmt.signedKm3(0.004), "+ <0.01");      // direction kept, separated from the threshold
  assert.equal(S.fmt.signedKm3(-0.004), "− <0.01");
  assert.equal(S.fmt.signedKm3(0), "0.00");
  assert.equal(S.fmt.pct(43.4321), "43.4%");
  assert.equal(S.fmt.signedPct(-1.54), "−1.5%");
  assert.equal(S.fmt.signedPct(null), "—");
  assert.equal(S.fmt.signedPp(2.04), "+2.0 pp");
});
