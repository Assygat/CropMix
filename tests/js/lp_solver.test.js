// Ручные примеры для web/lp_solver.js и web/planner_core.js (эталон — src/portfolio.py, сверка — tests/test_planner_crosscheck.py)
const test = require("node:test");
const assert = require("node:assert/strict");
const LP = require("../../web/lp_solver.js");
const P = require("../../web/planner_core.js");

const near = (a, b, tol = 1e-7) => assert.ok(Math.abs(a - b) <= tol * Math.max(1, Math.abs(b)), `${a} != ${b}`);

test("textbook LP: max 3x + 5y, x <= 4, 2y <= 12, 3x + 2y <= 18 → (2, 6), 36", () => {
  const r = LP.solve({ c: [-3, -5], rows: [{ a: [1, 0], type: "<=", b: 4 }, { a: [0, 2], type: "<=", b: 12 },
    { a: [3, 2], type: "<=", b: 18 }] });
  assert.equal(r.status, "optimal");
  near(r.x[0], 2); near(r.x[1], 6); near(-r.objective, 36);
});

test("equality, >= rows and bounds: min x + 2y, x + y = 10, x >= 3, 2 <= y <= 5 → (8, 2)", () => {
  const r = LP.solve({ c: [1, 2], rows: [{ a: [1, 1], type: "=", b: 10 }, { a: [1, 0], type: ">=", b: 3 }],
    lower: [0, 2], upper: [Infinity, 5] });
  assert.equal(r.status, "optimal");
  near(r.x[0], 8); near(r.x[1], 2); near(r.objective, 12);
});

test("degenerate LP that cycles under Dantzig's rule (Beale, 1955) terminates at the optimum", () => {
  // min −3/4 x4 + 20 x5 − 1/2 x6 + 6 x7 (Beale's cycling example); optimum −5/4 at x4 = 1, x6 = 1,
  // confirmed with scipy.optimize.linprog (HiGHS): status 0, fun −1.25, x = (1, 0, 1, 0)
  const r = LP.solve({ c: [-0.75, 20, -0.5, 6], rows: [
    { a: [0.25, -8, -1, 9], type: "<=", b: 0 },
    { a: [0.5, -12, -0.5, 3], type: "<=", b: 0 },
    { a: [0, 0, 1, 0], type: "<=", b: 1 }] });
  assert.equal(r.status, "optimal");
  near(r.objective, -1.25); near(r.x[0], 1); near(r.x[1], 0); near(r.x[2], 1); near(r.x[3], 0);
});

test("planner never reports a plan that breaks a rule: optimal results satisfy every constraint", () => {
  for (const share of [0.3, 0.6, 0.62, 0.9, 1.2]) {
    const p = two({ budget: share * 700, lower: { A: 5, B: 10 } });
    const s = P.solve(p, "max_area");
    if (s.status !== "optimal") { assert.equal(s.status, "infeasible"); continue; }
    assert.ok(s.water <= p.budget * (1 + 1e-9));
    for (const c of p.crops) assert.ok(s.areas[c] >= p.lower[c] - 1e-9 && s.areas[c] <= p.upper[c] + 1e-9);
  }
});

test("infeasible and unbounded problems are reported, not guessed", () => {
  assert.equal(LP.solve({ c: [1], rows: [{ a: [1], type: ">=", b: 5 }], upper: [3] }).status, "infeasible");
  assert.equal(LP.solve({ c: [-1, 0], rows: [{ a: [0, 1], type: "<=", b: 1 }] }).status, "unbounded");
});

const two = (over) => Object.assign({
  crops: ["A", "B"], water: { A: 10, B: 4 }, base: { A: 50, B: 50 }, lower: { A: 0, B: 0 }, upper: { A: 100, B: 50 },
  budget: 600, landMax: 200, landEqual: null, food: [], foodMin: null, value: null, valueMin: null }, over);

test("planner: max area under a water budget, shadow value of water = 1/10 ha per m³ (same as Python test)", () => {
  const s = P.solve(two({}), "max_area");
  assert.equal(s.status, "optimal");
  near(s.area, 90); near(s.areas.A, 40); near(s.areas.B, 50);
  const w = s.constraints.find((c) => c.kind === "water");
  assert.ok(w.binding); near(w.shadow, 0.1, 1e-4);
  assert.ok(s.bounds.some((b) => b.crop === "B" && b.side === "upper"));
});

test("planner: infeasible budget gives a diagnosis with the missing volume", () => {
  const s = P.solve(two({ lower: { A: 0, B: 50 }, budget: 100 }), "max_area");
  assert.equal(s.status, "infeasible");
  assert.match(s.diagnosis.join(" "), /lower the minimum share/);
});

test("planner: value objective refuses incomplete coefficients", () => {
  const s = P.solve(two({ value: { A: 5 } }), "max_value");
  assert.equal(s.status, "unavailable");
  assert.match(s.message, /missing: B/);
});

test("planner: Pareto points never use more water than their budget and are monotone", () => {
  const pts = P.pareto(two({}), "max_area", [100, 200, 400, 800, 2000]);
  for (let i = 0; i < pts.length; i++) {
    assert.ok(pts[i].water <= pts[i].budget * (1 + 1e-9));
    if (i) assert.ok(pts[i].objective >= pts[i - 1].objective - 1e-9);
  }
  near(pts[0].objective, 25); near(pts[pts.length - 1].objective, 150);
});
