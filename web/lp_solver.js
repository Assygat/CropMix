/* CropMix Twin — small dense LP solver for the Decision Lab (browser and Node).
 *
 * Two-phase primal simplex with Bland's rule (no cycling). Intended for the planner's problems only:
 * at most a few dozen variables and constraints. The reference solver is SciPy/HiGHS in src/portfolio.py;
 * tests/js/lp_solver.test.js checks this solver against reference solutions exported from Python.
 *
 * solve({c, rows, lower, upper}) minimises c·x subject to
 *   rows: [{a: [...], type: "<=" | ">=" | "=", b: number}]
 *   lower[i] <= x[i] <= upper[i]   (upper may be Infinity)
 * Returns {status: "optimal" | "infeasible" | "unbounded", x, objective}.
 */
(function (root) {
  "use strict";

  var EPS = 1e-9;

  function pivot(T, r, s) {
    var A = T.A, b = T.b, m = T.m, n = T.n;
    var p = A[r][s];
    for (var j = 0; j < n; j++) A[r][j] /= p;
    b[r] /= p;
    for (var i = 0; i < m; i++) {
      if (i === r) continue;
      var f = A[i][s];
      if (f === 0) continue;
      for (var k = 0; k < n; k++) A[i][k] -= f * A[r][k];
      b[i] -= f * b[r];
      if (Math.abs(b[i]) < 1e-13) b[i] = 0;
    }
    T.basis[r] = s;
  }

  function simplex(T, cost, allowed) {
    // Minimise cost·z over the current tableau; allowed(j) — may column j enter the basis?
    var m = T.m, n = T.n, iter = 0;
    for (;;) {
      if (++iter > 20000) throw new Error("simplex iteration limit");
      var enter = -1;
      for (var j = 0; j < n; j++) {
        if (!allowed(j) || T.basis.indexOf(j) >= 0) continue;
        var d = cost[j];
        for (var i = 0; i < m; i++) d -= cost[T.basis[i]] * T.A[i][j];
        if (d < -EPS) { enter = j; break; }            // Bland: smallest entering index
      }
      if (enter < 0) return "optimal";
      var leave = -1, best = Infinity;
      for (var r = 0; r < m; r++) {
        var a = T.A[r][enter];
        if (a > EPS) {
          var ratio = T.b[r] / a;
          if (ratio < best - 1e-12 || (Math.abs(ratio - best) <= 1e-12 && leave >= 0 && T.basis[r] < T.basis[leave])) {
            best = ratio; leave = r;
          }
        }
      }
      if (leave < 0) return "unbounded";
      pivot(T, leave, enter);
    }
  }

  function dot(a, b) { var s = 0; for (var i = 0; i < a.length; i++) s += a[i] * b[i]; return s; }

  function solve(problem) {
    var c = problem.c, nx = c.length, j;
    var lower = problem.lower || c.map(function () { return 0; });
    var upper = problem.upper || c.map(function () { return Infinity; });
    for (j = 0; j < nx; j++) {
      if (!(upper[j] >= lower[j] - 1e-9 * Math.max(1, Math.abs(upper[j])))) {
        return { status: "infeasible", x: null, objective: NaN };
      }
    }
    // x = lower + y, y >= 0; finite upper bounds become rows y <= u - l
    var rows = [];
    (problem.rows || []).forEach(function (r) {
      rows.push({ a: r.a.slice(), type: r.type, b: r.b - dot(r.a, lower) });
    });
    for (j = 0; j < nx; j++) {
      if (isFinite(upper[j])) {
        var e = new Array(nx).fill(0); e[j] = 1;
        rows.push({ a: e, type: "<=", b: Math.max(0, upper[j] - lower[j]) });
      }
    }
    // scale each row to max |a| = 1 and make the right-hand side non-negative
    rows.forEach(function (r) {
      var s = 0;
      for (var k = 0; k < nx; k++) s = Math.max(s, Math.abs(r.a[k]));
      if (s > 0) { r.a = r.a.map(function (v) { return v / s; }); r.b /= s; }
      if (r.b < 0) {
        r.a = r.a.map(function (v) { return -v; }); r.b = -r.b;
        r.type = r.type === "<=" ? ">=" : r.type === ">=" ? "<=" : "=";
      }
    });
    var m = rows.length;
    if (m === 0) {
      for (j = 0; j < nx; j++) if (c[j] < 0) return { status: "unbounded", x: null, objective: -Infinity };
      return { status: "optimal", x: lower.slice(), objective: dot(c, lower) };
    }
    var nSlack = rows.filter(function (r) { return r.type !== "="; }).length;
    var nArt = rows.filter(function (r) { return r.type !== "<="; }).length;
    var artStart = nx + nSlack, n = artStart + nArt;
    var A = [], b = [], basis = [], si = nx, ai = artStart;
    rows.forEach(function (r) {
      var row = new Array(n).fill(0);
      for (var k = 0; k < nx; k++) row[k] = r.a[k];
      if (r.type === "<=") { basis.push(si); row[si++] = 1; }
      else if (r.type === ">=") { row[si++] = -1; basis.push(ai); row[ai++] = 1; }
      else { basis.push(ai); row[ai++] = 1; }
      A.push(row); b.push(r.b);
    });
    var T = { A: A, b: b, basis: basis, m: m, n: n };
    var bsum = b.reduce(function (s, v) { return s + Math.abs(v); }, 0);
    if (nArt > 0) {
      var cost1 = new Array(n).fill(0);
      for (j = artStart; j < n; j++) cost1[j] = 1;
      simplex(T, cost1, function () { return true; });
      var infeas = 0;
      for (var i = 0; i < m; i++) if (T.basis[i] >= artStart) infeas += T.b[i];
      if (infeas > 1e-8 * Math.max(1, bsum)) return { status: "infeasible", x: null, objective: NaN };
      for (var r2 = 0; r2 < m; r2++) {          // drive zero-level artificials out of the basis
        if (T.basis[r2] < artStart) continue;
        for (j = 0; j < artStart; j++) {
          if (Math.abs(T.A[r2][j]) > 1e-9 && T.basis.indexOf(j) < 0) { pivot(T, r2, j); break; }
        }
      }
    }
    var cmax = 0;
    for (j = 0; j < nx; j++) cmax = Math.max(cmax, Math.abs(c[j]));
    var cost2 = new Array(n).fill(0);
    for (j = 0; j < nx; j++) cost2[j] = cmax > 0 ? c[j] / cmax : 0;
    var st = simplex(T, cost2, function (k) { return k < artStart; });
    if (st === "unbounded") return { status: "unbounded", x: null, objective: -Infinity };
    var y = new Array(nx).fill(0);
    for (var i3 = 0; i3 < m; i3++) if (T.basis[i3] < nx) y[T.basis[i3]] = T.b[i3];
    var x = y.map(function (v, idx) { return Math.min(lower[idx] + Math.max(0, v), upper[idx]); });
    return { status: "optimal", x: x, objective: dot(c, x) };
  }

  var api = { solve: solve, dot: dot };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CropMixLP = api;
})(this);
