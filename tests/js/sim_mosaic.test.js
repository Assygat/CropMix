// Tests for web/sim_mosaic.js — schematic crop mosaic engine (Crop Editor, stage E2).
// Pure functions only: hex grid inside the region outline, cell counts, layout, reconcile, brush, stroke → areas, labels.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const Mo = require(path.join(ROOT, "web", "sim_mosaic.js"));
const MapLib = require(path.join(ROOT, "web", "sim_map.js"));
const GEO = JSON.parse(fs.readFileSync(path.join(ROOT, "web", "data", "geo.json"), "utf8"));
const SIM = JSON.parse(fs.readFileSync(path.join(ROOT, "web", "data", "simulator.json"), "utf8"));
const CROPS = SIM.crops.map((c) => c.id);
const BASE = SIM.baseline.areas_ha;
const proj = MapLib.createProjection(GEO.bbox);
const RING = MapLib.outerBoundary(GEO.districts.features)[0].map(proj.project);
const CAPACITY = Math.round(Object.values(BASE).reduce((a, b) => a + b, 0) / Mo.HA_PER_CELL);   // 1881
const deepFreeze = (o) => { if (o && typeof o === "object" && !Object.isFrozen(o)) { Object.freeze(o); Object.values(o).forEach(deepFreeze); } return o; };
const tally = (layout) => { const t = Object.fromEntries(CROPS.map((c) => [c, 0])); let unsown = 0; for (const c of layout) c === null ? unsown++ : t[c]++; return { t, unsown }; };

const GRID = Mo.buildGrid(RING, CAPACITY);

test("grid: exactly the capacity, every cell centre inside the region outline, hex neighbours are mutual", () => {
  assert.equal(CAPACITY, 1881);
  assert.equal(GRID.cells.length, CAPACITY);
  for (const c of GRID.cells) assert.ok(MapLib.pointInRing(c.x, c.y, RING), `cell ${c.id} outside`);
  for (const c of GRID.cells) {
    assert.ok(GRID.neighbors[c.id].length <= 6);
    for (const n of GRID.neighbors[c.id]) assert.ok(GRID.neighbors[n].includes(c.id));
  }
  // flat-to-flat width of a pointy hex = sqrt(3) * size; ~12 km for 100 ha per cell over ≈ 229 600 km²
  const acrossKm = Math.sqrt(3) * GRID.size * proj.kmPerUnit;
  assert.ok(acrossKm > 8 && acrossKm < 16, acrossKm);
});

test("grid is deterministic", () => {
  const g2 = Mo.buildGrid(RING, CAPACITY);
  assert.deepEqual(g2.cells.map((c) => [c.q, c.r]), GRID.cells.map((c) => [c.q, c.r]));
});

test("cell counts: largest remainder, sum = round(total / 100), hand example", () => {
  const r = Mo.cellCounts({ a: 250, b: 149, c: 101 }, ["a", "b", "c"], 100, 10);
  // floors 2,1,1 = 4; total 500 → 5 cells; largest remainder: a .5, b .49, c .01 → a gets the extra
  assert.deepEqual(r.counts, { a: 3, b: 1, c: 1 });
  assert.equal(r.total, 5); assert.equal(r.overflow, 0);
  const base = Mo.cellCounts(BASE, CROPS, 100, CAPACITY);
  assert.equal(Object.values(base.counts).reduce((a, b) => a + b, 0), CAPACITY);
  assert.equal(base.counts.rice, 817); assert.equal(base.counts.potato, 16); assert.equal(base.counts.grain_other, 27);
  const zero = Mo.cellCounts(Object.fromEntries(CROPS.map((c) => [c, 0])), CROPS, 100, CAPACITY);
  assert.equal(zero.total, 0);
});

test("cell counts above capacity: shares scaled to capacity, overflow reported", () => {
  const big = Object.assign({}, BASE, { rice: BASE.rice + 20000 });
  const r = Mo.cellCounts(big, CROPS, 100, CAPACITY);
  assert.equal(Object.values(r.counts).reduce((a, b) => a + b, 0), CAPACITY);
  assert.equal(r.overflow, Math.round((Object.values(big).reduce((a, b) => a + b, 0)) / 100) - CAPACITY);
});

test("initial layout: counts match, crops form compact patches (not a checkerboard)", () => {
  const { counts } = Mo.cellCounts(BASE, CROPS, 100, CAPACITY);
  const layout = Mo.initialLayout(GRID, counts, CROPS);
  const { t, unsown } = tally(layout);
  assert.deepEqual(t, counts); assert.equal(unsown, 0);
  for (const crop of CROPS) {
    const comps = Mo.components(GRID, layout, crop);
    const largest = Math.max(...comps.map((c) => c.length));
    assert.ok(largest / counts[crop] >= 0.8, `${crop}: largest patch ${largest} of ${counts[crop]}`);
  }
  // patchiness: most neighbours of a cell share its crop
  let same = 0, all = 0;
  for (const c of GRID.cells) for (const n of GRID.neighbors[c.id]) { all++; if (layout[n] === layout[c.id]) same++; }
  assert.ok(same / all > 0.85, same / all);
  assert.deepEqual(Mo.initialLayout(GRID, counts, CROPS), layout);   // deterministic
});

test("reconcile: changes exactly the cells needed; unchanged crops keep every cell; new cells grow at the patch edge", () => {
  const before = Mo.cellCounts(BASE, CROPS, 100, CAPACITY).counts;
  const layout = deepFreeze(Mo.initialLayout(GRID, before, CROPS));
  const after = Object.assign({}, before, { rice: before.rice - 40, wheat: before.wheat + 40 });
  const r = Mo.reconcile(GRID, layout, after, CROPS);
  assert.equal(r.changed.length, 40);
  assert.deepEqual(tally(r.layout).t, after);
  for (const ch of r.changed) { assert.equal(ch.from, "rice"); assert.equal(ch.to, "wheat"); }
  for (let i = 0; i < layout.length; i++) if (!["rice", "wheat"].includes(layout[i])) assert.equal(r.layout[i], layout[i]);
  // new wheat cells touch wheat (grow from the existing patch)
  const touching = r.changed.filter((ch) => GRID.neighbors[ch.id].some((n) => r.layout[n] === "wheat" && n !== ch.id)).length;
  assert.ok(touching / 40 >= 0.9, touching);
  // shrinking total area frees cells as "unsown"; same counts → no change
  const less = Object.assign({}, after, { fodder: after.fodder - 100 });
  const r2 = Mo.reconcile(GRID, r.layout, less, CROPS);
  assert.equal(tally(r2.layout).unsown, 100);
  assert.equal(r2.changed.length, 100);
  assert.equal(Mo.reconcile(GRID, r.layout, after, CROPS).changed.length, 0);
  // growing back fills the unsown cells first
  const r3 = Mo.reconcile(GRID, r2.layout, after, CROPS);
  assert.equal(tally(r3.layout).unsown, 0);
  assert.equal(r3.changed.length, 100);
});

test("reconcile across non-touching crops: cells are passed along a chain, counts exact, patches stay whole", () => {
  const before = Mo.cellCounts(BASE, CROPS, 100, CAPACITY).counts;
  const layout = Mo.initialLayout(GRID, before, CROPS);
  const touches = (a, b) => GRID.cells.some((c) => layout[c.id] === a && GRID.neighbors[c.id].some((n) => layout[n] === b));
  let pair = null;
  for (const recv of CROPS) for (const donor of CROPS) {
    if (!pair && recv !== donor && before[donor] > 20 && !touches(recv, donor)) pair = [recv, donor];
  }
  assert.ok(pair, "the baseline layout has at least one pair of crops without a shared border");
  const [recv, donor] = pair;
  const after = Object.assign({}, before, { [recv]: before[recv] + 12, [donor]: before[donor] - 12 });
  const r = Mo.reconcile(GRID, layout, after, CROPS);
  assert.deepEqual(tally(r.layout).t, after);
  assert.ok(r.changed.length >= 12);                                     // chains move a few extra cells
  for (const crop of [recv, donor]) {
    const comps = Mo.components(GRID, r.layout, crop);
    assert.ok(Math.max(...comps.map((c) => c.length)) / after[crop] >= 0.8, `${crop} stays one main patch`);
  }
  // every crop not involved keeps its count (its shape may shift along the chain)
  for (const crop of CROPS) if (crop !== recv && crop !== donor) assert.equal(tally(r.layout).t[crop], before[crop]);
});

test("no stray fragments (stage 3.5 audit): baseline is one patch per crop; Tight/Flexible stay whole; painted fragments are kept", () => {
  const base = Mo.cellCounts(BASE, CROPS, 100, CAPACITY).counts;
  const L0 = Mo.initialLayout(GRID, base, CROPS);
  assert.deepEqual(tally(L0).t, base);
  for (const crop of CROPS) assert.equal(Mo.components(GRID, L0, crop).length, 1, `${crop} is one patch`);
  for (const pid of ["tight", "flexible"]) {
    const counts = Mo.cellCounts(SIM.optimized.presets[pid].areas_ha, CROPS, 100, CAPACITY).counts;
    const r = Mo.reconcile(GRID, L0, counts, CROPS);
    assert.deepEqual(tally(r.layout).t, counts);                          // counts stay exact after tidying
    for (const crop of CROPS) assert.equal(Mo.components(GRID, r.layout, crop).length, 1, `${pid}: ${crop} is one patch`);
  }
  // a cell painted on purpose inside another crop is a fragment that reconcile must never move
  const lone = L0.findIndex((c, i) => c === "fodder" && GRID.neighbors[i].length === 6 && GRID.neighbors[i].every((n) => L0[n] === "fodder"));
  const painted = Mo.paint(L0, [lone], "rice");
  const areas = Mo.strokeAreas(BASE, painted.changed, 100);
  const counts = Mo.cellCounts(areas, CROPS, 100, CAPACITY).counts;
  const r = Mo.reconcile(GRID, painted.layout, Object.assign({}, counts, { wheat: counts.wheat + 5, fodder: counts.fodder - 5 }), CROPS);
  assert.equal(r.layout[lone], "rice");
});

test("brush: cell lookup and hex-radius brushes of 1 / 7 / 19 / 37 cells in the interior", () => {
  const c = GRID.cells[Math.floor(GRID.cells.length / 2)];
  assert.equal(Mo.cellAt(GRID, c.x, c.y), c.id);
  assert.equal(Mo.cellAt(GRID, c.x + GRID.size * 0.3, c.y - GRID.size * 0.2), c.id);
  assert.equal(Mo.cellAt(GRID, -1e6, -1e6), null);
  const interior = GRID.cells.find((x) => Mo.brushCells(GRID, x.id, 3).length === 37);
  assert.ok(interior);
  assert.deepEqual([0, 1, 2, 3].map((r) => Mo.brushCells(GRID, interior.id, r).length), [1, 7, 19, 37]);
});

test("paint: crop-to-crop keeps the cell total; eraser makes cells unsown; painting the same crop changes nothing", () => {
  const counts = Mo.cellCounts(BASE, CROPS, 100, CAPACITY).counts;
  const layout = deepFreeze(Mo.initialLayout(GRID, counts, CROPS));
  const riceCell = layout.indexOf("rice");
  const ids = Mo.brushCells(GRID, riceCell, 1);
  const p = Mo.paint(layout, ids, "melons");
  assert.equal(tally(p.layout).t.melons - counts.melons, ids.filter((i) => layout[i] !== "melons").length);
  assert.equal(p.layout.filter((x) => x !== null).length, CAPACITY);
  const e = Mo.paint(layout, ids, null);
  assert.equal(tally(e.layout).unsown, ids.length);
  const same = Mo.paint(layout, [riceCell], "rice");
  assert.equal(same.changed.length, 0);
});

test("stroke → areas: transfers keep the total exactly; eraser removes 100 ha per cell; no negative areas", () => {
  const areas = deepFreeze(Object.assign({}, BASE));
  const tr = Mo.strokeAreas(areas, [{ from: "rice", to: "wheat" }, { from: "rice", to: "wheat" }, { from: "fodder", to: "wheat" }]);
  assert.equal(tr.rice, BASE.rice - 200); assert.equal(tr.fodder, BASE.fodder - 100); assert.equal(tr.wheat, BASE.wheat + 300);
  const sum = (o) => Object.values(o).reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(sum(tr) - sum(BASE)) < 1e-6);
  const er = Mo.strokeAreas(areas, [{ from: "melons", to: null }]);
  assert.equal(er.melons, BASE.melons - 100);
  const add = Mo.strokeAreas(areas, [{ from: null, to: "potato" }]);
  assert.equal(add.potato, BASE.potato + 100);
  // a crop with less than 100 ha left gives what it has (never negative); the receiver gets exactly that
  const tiny = Object.assign({}, BASE, { grain_other: 30 });
  const t2 = Mo.strokeAreas(tiny, [{ from: "grain_other", to: "rice" }]);
  assert.equal(t2.grain_other, 0); assert.equal(t2.rice, BASE.rice + 30);
  assert.equal(areas.rice, BASE.rice);                                   // input untouched
});

test("visual and model stay in sync: after a stroke, counts from the new areas reproduce the painted counts", () => {
  const counts = Mo.cellCounts(BASE, CROPS, 100, CAPACITY).counts;
  const layout = Mo.initialLayout(GRID, counts, CROPS);
  const start = layout.indexOf("fodder");
  const ids = Mo.brushCells(GRID, start, 2);
  const p = Mo.paint(layout, ids, "rice");
  const areas = Mo.strokeAreas(BASE, p.changed);
  const recount = Mo.cellCounts(areas, CROPS, 100, CAPACITY).counts;
  assert.deepEqual(recount, tally(p.layout).t);
  assert.equal(Mo.reconcile(GRID, p.layout, recount, CROPS).changed.length, 0);   // nothing to fix after the stroke
});

test("label anchors: one per crop patch, anchor inside the patch, depth measured in cells", () => {
  const counts = Mo.cellCounts(BASE, CROPS, 100, CAPACITY).counts;
  const layout = Mo.initialLayout(GRID, counts, CROPS);
  const anchors = Mo.labelAnchors(GRID, layout, CROPS);
  for (const a of anchors) {
    assert.equal(layout[a.id], a.crop);
    assert.ok(a.depth >= 1 && a.size >= 1);
  }
  const rice = anchors.find((a) => a.crop === "rice"), potato = anchors.find((a) => a.crop === "potato");
  assert.ok(rice.depth > potato.depth);                                  // big patch has more room than a 16-cell patch
  assert.ok(anchors.filter((a) => a.depth >= 3).length < CROPS.length);  // small crops do not reach depth 3
});

test("diffLayouts: net change of a stroke (a cell painted twice counts once, back-and-forth counts zero)", () => {
  const a = ["rice", "rice", "wheat", null];
  const b = ["melons", "rice", "wheat", "potato"];
  assert.deepEqual(Mo.diffLayouts(a, b), [{ id: 0, from: "rice", to: "melons" }, { id: 3, from: null, to: "potato" }]);
  assert.deepEqual(Mo.diffLayouts(a, a.slice()), []);
});

test("labelFits: the label must fit inside the patch at the current zoom (width and height)", () => {
  // cell flat-to-flat width 10 px; depth 3 → usable width (2·3 − 1)·10·0.9 = 45 px, height 2·3·10·0.75·0.9 = 40.5 px
  assert.equal(Mo.labelFits({ depth: 3 }, 40, 12, 10), true);
  assert.equal(Mo.labelFits({ depth: 3 }, 50, 12, 10), false);   // too wide
  assert.equal(Mo.labelFits({ depth: 1 }, 8, 12, 10), false);    // single-cell rim: never labelled
  assert.equal(Mo.labelFits({ depth: 6 }, 95, 12, 10), true);    // (2·6 − 1)·10·0.9 = 99 px available
  assert.equal(Mo.labelFits({ depth: 6 }, 100, 12, 10), false);
  assert.equal(Mo.labelFits({ depth: 6 }, 95, 12, 4), false);    // zoomed out: cells 4 px → no room
});

test("pure: inputs are never mutated", () => {
  const counts = deepFreeze(Mo.cellCounts(BASE, CROPS, 100, CAPACITY).counts);
  const layout = deepFreeze(Mo.initialLayout(GRID, counts, CROPS));
  assert.doesNotThrow(() => Mo.reconcile(GRID, layout, Object.assign({}, counts, { rice: counts.rice - 5, melons: counts.melons + 5 }), CROPS));
  assert.doesNotThrow(() => Mo.paint(layout, [0, 1, 2], "rice"));
  assert.doesNotThrow(() => Mo.labelAnchors(GRID, layout, CROPS));
});
