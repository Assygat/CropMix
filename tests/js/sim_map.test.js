// Тесты чистых функций web/sim_map.js (модуль 10, этап 4). Запуск: node --test tests/js/sim_map.test.js
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const M = require(path.join(ROOT, "web", "sim_map.js"));
const GEO = JSON.parse(fs.readFileSync(path.join(ROOT, "web", "data", "geo.json"), "utf8"));
const DISTRICTS = GEO.districts.features;

// Квадрат 1×1 с левым нижним углом (x0, y0) — ручные примеры.
const sq = (x0, y0, id) => ({ properties: { id }, geometry: { type: "Polygon",
  coordinates: [[[x0, y0], [x0 + 1, y0], [x0 + 1, y0 + 1], [x0, y0 + 1], [x0, y0]]] } });

test("outer boundary of two adjacent squares drops the shared edge (hand example)", () => {
  const rings = M.outerBoundary([sq(0, 0, "a"), sq(1, 0, "b")]);
  assert.equal(rings.length, 1);
  const ring = rings[0];
  assert.deepEqual(ring[0], ring[ring.length - 1]);           // замкнуто
  assert.equal(ring.length - 1, 6);                            // 6 рёбер: периметр прямоугольника 2×1
  const sharedEdgeUsed = ring.some((p, i) => i < ring.length - 1 &&
    p[0] === 1 && ring[i + 1][0] === 1 && Math.abs(p[1] - ring[i + 1][1]) === 1);
  assert.equal(sharedEdgeUsed, false);
});

test("outer boundary of the 8 real territories is one closed ring of 158 edges", () => {
  const rings = M.outerBoundary(DISTRICTS);
  assert.equal(rings.length, 1);
  const ring = rings[0];
  assert.deepEqual(ring[0], ring[ring.length - 1]);
  assert.equal(ring.length - 1, 158);
  // каждая вершина внешней границы — вершина реального района (геометрия не выдумана)
  const verts = new Set(DISTRICTS.flatMap((f) => M.featureRings(f).flat().map((p) => p.join(","))));
  assert.ok(ring.every((p) => verts.has(p.join(","))));
  // внешняя граница не проходит по общим рёбрам районов: каждое ребро встречается ровно у одного района
  const owners = new Map();
  for (const f of DISTRICTS) for (const r of M.featureRings(f)) for (let i = 0; i < r.length - 1; i++) {
    const k = [r[i].join(","), r[i + 1].join(",")].sort().join("|");
    owners.set(k, (owners.get(k) || 0) + 1);
  }
  for (let i = 0; i < ring.length - 1; i++) {
    const k = [ring[i].join(","), ring[i + 1].join(",")].sort().join("|");
    assert.equal(owners.get(k), 1);
  }
});

test("inconsistent topology (squares touching at one vertex) is detected, not silently drawn", () => {
  assert.throws(() => M.outerBoundary([sq(0, 0, "a"), sq(1, 1, "c")]), /simple closed rings/);
  assert.equal(M.outerBoundary([sq(0, 0, "a"), sq(5, 5, "b")]).length, 2);   // два отдельных контура — норма
});

test("projection: bbox corners map to the frame; 1 unit = 1.1132 km", () => {
  const p = M.createProjection([60, 40, 70, 50]);
  assert.deepEqual(p.project([60, 50]), [0, 0]);
  const [x, y] = p.project([70, 40]);
  assert.ok(Math.abs(x - 10 * Math.cos(45 * Math.PI / 180) * 100) < 1e-9);
  assert.ok(Math.abs(y - 1000) < 1e-9);
  assert.ok(Math.abs(p.kmPerUnit - 1.1132) < 1e-12);
  assert.ok(Math.abs(p.width - x) < 1e-9 && Math.abs(p.height - 1000) < 1e-9);
});

test("label point lies inside each territory, including concave shapes", () => {
  const L = [[0, 0], [10, 0], [10, 2], [2, 2], [2, 10], [0, 10], [0, 0]];   // L-образная фигура
  const [lx, ly] = M.labelPoint(L);
  assert.ok(M.pointInRing(lx, ly, L));
  const proj = M.createProjection(GEO.bbox);
  for (const f of DISTRICTS) {
    const ring = M.featureRings(f)[0].map(proj.project);
    const [x, y] = M.labelPoint(ring);
    assert.ok(M.pointInRing(x, y, ring), f.properties.id);
  }
});

test("zoom keeps the anchor point fixed and respects min/max zoom", () => {
  const base = M.baseView(1000, 500);
  const v1 = M.zoomAt(base, base, 2, 300, 200);
  assert.ok(Math.abs(M.zoomLevel(v1, base) - 2) < 1e-12);
  assert.ok(Math.abs((300 - v1.x) / v1.w - (300 - base.x) / base.w) < 1e-12);   // точка остаётся на месте
  assert.ok(Math.abs((200 - v1.y) / v1.h - (200 - base.y) / base.h) < 1e-12);
  const tooFar = M.zoomAt(base, base, 1000, 500, 250);
  assert.ok(Math.abs(M.zoomLevel(tooFar, base) - M.MAX_ZOOM) < 1e-9);
  const tooOut = M.zoomAt(v1, base, 0.001, 500, 250);
  assert.ok(Math.abs(M.zoomLevel(tooOut, base) - M.MIN_ZOOM) < 1e-9);
  assert.ok(Math.abs(tooOut.h / tooOut.w - base.h / base.w) < 1e-12);           // пропорции окна сохраняются
});

test("pan moves the view and keeps its centre inside the region frame", () => {
  const base = M.baseView(1000, 500);
  const v = M.zoomAt(base, base, 4, 500, 250);
  const moved = M.panBy(v, base, 50, -20);
  assert.ok(Math.abs(moved.x - (v.x + 50)) < 1e-9 && Math.abs(moved.y - (v.y - 20)) < 1e-9);
  const far = M.panBy(v, base, 1e6, 1e6);
  assert.ok(Math.abs(far.x + far.w / 2 - (base.x + base.w)) < 1e-9);
  assert.ok(Math.abs(far.y + far.h / 2 - (base.y + base.h)) < 1e-9);
  assert.equal(far.w, v.w);                                                       // pan не меняет масштаб
});

test("scale bar uses 1-2-5 steps", () => {
  assert.equal(M.niceDistance(137), 100);
  assert.equal(M.niceDistance(260), 200);
  assert.equal(M.niceDistance(9.9), 5);
  assert.equal(M.niceDistance(50), 50);
});

test("geo data carries geography only: no crop, area-by-crop or water values by district", () => {
  assert.equal(DISTRICTS.length, 8);
  for (const f of DISTRICTS) {
    const keys = Object.keys(f.properties);
    assert.ok(!keys.some((k) => /crop|areas_ha|water|m3/i.test(k)), f.properties.id + ": " + keys);
    assert.equal(f.properties.boundary_year, 2017);
  }
});
