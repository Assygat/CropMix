/* CropMix Twin — Decision Lab model (no DOM). Mirrors src/portfolio.py; checked against it by
 * tests/test_planner_crosscheck.py (Python/HiGHS reference vs this code on the same problems).
 *
 * Problem p = {crops, water (m³/ha), base (ha), lower, upper (ha), budget (m³|null),
 *              landMax (ha|null), landEqual (ha|null), food: [crop], foodMin (ha|null),
 *              value (KZT/ha per crop, optional), valueMin (KZT|null)}
 * Objectives: min_water, max_area, max_food_area, max_value.
 */
(function (root) {
  "use strict";
  var LP = (typeof module !== "undefined" && module.exports) ? require("./lp_solver.js") : root.CropMixLP;
  var REL_TOL = 1e-6, TIE_TOL = 1e-9;   // 1 ppm: float64 simplex rounding must not change which bound is reported
  var UNITS = { min_water: "m³", max_area: "ha", max_food_area: "ha", max_value: "KZT" };

  function vec(p, d) { return p.crops.map(function (c) { return Number(d[c]); }); }
  function isFood(p) { return p.crops.map(function (c) { return p.food.indexOf(c) >= 0 ? 1 : 0; }); }
  function valueComplete(p) {
    return !!p.value && p.crops.every(function (c) { return p.value[c] !== null && p.value[c] !== undefined && isFinite(p.value[c]); });
  }

  function rows(p) {
    var out = [], n = p.crops.length;
    if (p.budget !== null && p.budget !== undefined)
      out.push({ name: "water budget", kind: "water", unit: "m³", a: vec(p, p.water), type: "<=", b: p.budget });
    if (p.landMax !== null && p.landMax !== undefined)
      out.push({ name: "land available", kind: "land", unit: "ha", a: new Array(n).fill(1), type: "<=", b: p.landMax });
    if (p.landEqual !== null && p.landEqual !== undefined)
      out.push({ name: "land fixed", kind: "land", unit: "ha", a: new Array(n).fill(1), type: "=", b: p.landEqual });
    if (p.foodMin !== null && p.foodMin !== undefined && p.food.length)
      out.push({ name: "food-crop area minimum", kind: "food", unit: "ha", a: isFood(p), type: ">=", b: p.foodMin });
    if (p.valueMin !== null && p.valueMin !== undefined && valueComplete(p))
      out.push({ name: "value minimum", kind: "value", unit: "KZT", a: vec(p, p.value), type: ">=", b: p.valueMin });
    return out;
  }

  function objectiveVector(p, objective) {
    if (objective === "min_water") return { c: vec(p, p.water), sign: 1 };
    if (objective === "max_area") return { c: p.crops.map(function () { return -1; }), sign: -1 };
    if (objective === "max_food_area") return { c: isFood(p).map(function (v) { return -v; }), sign: -1 };
    if (objective === "max_value") return { c: vec(p, p.value).map(function (v) { return -v; }), sign: -1 };
    throw new Error("unknown objective " + objective);
  }

  function lp(p, c, rs, extra) {
    var all = rs.map(function (r) { return { a: r.a, type: r.type, b: r.b }; });
    if (extra) all.push(extra);
    return LP.solve({ c: c, rows: all, lower: vec(p, p.lower), upper: vec(p, p.upper) });
  }

  function primary(p, objective) {
    var rs = rows(p), o = objectiveVector(p, objective);
    var r = lp(p, o.c, rs);
    return { r: r, rs: rs, o: o, value: r.status === "optimal" ? o.sign * r.objective : NaN };
  }

  function relax(p, row, delta) {
    // a copy of p where one constraint is relaxed by delta (in its own units)
    var q = Object.assign({}, p);
    if (row.kind === "water") q.budget = p.budget + delta;
    else if (row.name === "land available") q.landMax = p.landMax + delta;
    else if (row.name === "land fixed") q.landEqual = p.landEqual + delta;
    else if (row.kind === "food") q.foodMin = p.foodMin - delta;
    else if (row.kind === "value") q.valueMin = p.valueMin - delta;
    return q;
  }

  function solve(p, objective, opts) {
    opts = opts || {};
    if (objective === "max_value" && !valueComplete(p)) {
      var missing = p.crops.filter(function (c) { return !p.value || p.value[c] === null || p.value[c] === undefined || !isFinite(p.value[c]); });
      return { status: "unavailable", objective: objective,
               message: "Gross-value objective needs a value per hectare for every crop; missing: " + missing.join(", ") + "." };
    }
    var bad = p.crops.filter(function (c) { return p.lower[c] > p.upper[c] * (1 + 1e-12); });
    if (bad.length) return { status: "infeasible", objective: objective, message: "Minimum above maximum for " + bad.join(", "),
                             diagnosis: ["minimum area above maximum area for " + bad.join(", ")] };
    var P = primary(p, objective);
    if (P.r.status !== "optimal")
      return { status: P.r.status, objective: objective, message: "No feasible allocation: the constraints conflict.",
               diagnosis: P.r.status === "infeasible" ? diagnose(p) : [] };
    var x = P.r.x;
    if (opts.tieBreak !== false) {
      var tol = TIE_TOL * Math.max(1, Math.abs(P.r.objective));
      var sec = objective === "min_water" ? p.crops.map(function () { return -1; }) : vec(p, p.water);
      var r2 = lp(p, sec, P.rs, { a: P.o.c, type: "<=", b: P.r.objective + tol });
      if (r2.status === "optimal") x = r2.x;
    }
    // A posteriori check: a plan that breaks any rule by more than 1 ppm is never reported as feasible.
    var bad = P.rs.filter(function (row) {
      var lhs = LP.dot(row.a, x), tol = 1e-6 * Math.max(1, Math.abs(row.b));
      return row.type === "<=" ? lhs > row.b + tol : row.type === ">=" ? lhs < row.b - tol : Math.abs(lhs - row.b) > tol;
    }).concat(p.crops.filter(function (c, i) {
      return x[i] < p.lower[c] - 1e-6 * Math.max(1, p.lower[c]) || x[i] > p.upper[c] + 1e-6 * Math.max(1, p.upper[c]);
    }));
    if (bad.length) return { status: "numerical_error", objective: objective,
      message: "The solver returned a plan that does not meet every rule within 1 ppm, so it is not shown. Please report this case.",
      diagnosis: [] };
    var areas = {}, w = vec(p, p.water), f = isFood(p);
    p.crops.forEach(function (c, i) { areas[c] = x[i]; });
    var res = { status: "optimal", objective: objective, objectiveValue: P.value, areas: areas,
                water: LP.dot(w, x), area: x.reduce(function (s, v) { return s + v; }, 0), foodArea: LP.dot(f, x),
                value: valueComplete(p) ? LP.dot(vec(p, p.value), x) : null, constraints: [], bounds: [] };
    P.rs.forEach(function (row) {
      var lhs = LP.dot(row.a, x);
      var slack = row.type === "<=" ? row.b - lhs : row.type === ">=" ? lhs - row.b : 0;
      var binding = row.type === "=" || slack <= REL_TOL * Math.max(1, Math.abs(row.b));
      var shadow = 0;
      if (binding && opts.shadow !== false) {
        // value of relaxing the constraint by one unit, estimated by re-solving (exact for an LP while
        // the set of binding constraints does not change)
        var delta = 1e-6 * Math.max(1, Math.abs(row.b));
        var Q = primary(relax(p, row, delta), objective);
        if (Q.r.status === "optimal") {
          var gain = (Q.value - P.value) / delta;
          shadow = objective === "min_water" ? -gain : gain;
          if (Math.abs(shadow) < 1e-12) shadow = 0;
        }
      }
      res.constraints.push({ name: row.name, kind: row.kind, unit: row.unit, lhs: lhs, rhs: row.b, slack: slack,
                             binding: binding, shadow: shadow, shadowUnit: UNITS[objective] + " per " + row.unit });
    });
    p.crops.forEach(function (c, i) {
      var lo = p.lower[c], hi = p.upper[c];
      if (hi - lo <= REL_TOL * Math.max(1, hi)) res.bounds.push({ crop: c, side: "fixed", value: x[i] });
      else if (x[i] - lo <= REL_TOL * Math.max(1, lo)) res.bounds.push({ crop: c, side: "lower", value: x[i] });
      else if (hi - x[i] <= REL_TOL * Math.max(1, hi)) res.bounds.push({ crop: c, side: "upper", value: x[i] });
    });
    return res;
  }

  function sum(a) { return a.reduce(function (s, v) { return s + v; }, 0); }
  function km3(v) { return (v / 1e9).toFixed(3) + " km³"; }
  function ha(v) { return Math.round(v).toLocaleString("en-US") + " ha"; }

  function diagnose(p) {
    var out = [];
    var lo = sum(p.crops.map(function (c) { return p.lower[c]; }));
    var hi = sum(p.crops.map(function (c) { return p.upper[c]; }));
    var land = (p.landEqual !== null && p.landEqual !== undefined) ? p.landEqual : p.landMax;
    if (land !== null && land !== undefined && lo > land * (1 + 1e-12))
      out.push("Minimum areas add up to " + ha(lo) + ", more than the land limit of " + ha(land) + ".");
    if (p.landEqual !== null && p.landEqual !== undefined && hi < p.landEqual)
      out.push("Maximum areas add up to " + ha(hi) + ", less than the required total of " + ha(p.landEqual) + ".");
    if (p.foodMin !== null && p.foodMin !== undefined) {
      var fhi = sum(p.food.map(function (c) { return p.upper[c] || 0; }));
      if (p.foodMin > fhi) out.push("The food-crop minimum (" + ha(p.foodMin) + ") exceeds the food crops' maximum areas (" + ha(fhi) + ").");
    }
    if (p.budget !== null && p.budget !== undefined) {
      var free = primary(Object.assign({}, p, { budget: null }), "min_water");
      if (free.r.status !== "optimal") {
        out.push("No allocation exists even with unlimited water: the land, area and food limits conflict.");
      } else if (free.value > p.budget) {
        out.push("Water: these limits need at least " + km3(free.value) + ", but only " + km3(p.budget) +
                 " is available. Add " + km3(free.value - p.budget) + " or relax the minimums.");
        if (p.foodMin !== null && p.foodMin !== undefined) {
          var mf = primary(Object.assign({}, p, { foodMin: null }), "max_food_area");
          if (mf.r.status === "optimal" && mf.value < p.foodMin)
            out.push("Food: with this water the food-crop area can reach at most " + ha(mf.value) + " (minimum asked: " + ha(p.foodMin) + ").");
          else if (mf.r.status !== "optimal")
            out.push("Food: even without the food minimum, the water cannot cover the minimum crop areas.");
        }
        var mins = primary(Object.assign({}, p, { budget: null, foodMin: null }), "min_water");
        if (mins.r.status === "optimal" && mins.value > p.budget)
          out.push("The minimum retained areas alone need " + km3(mins.value) + ": lower the minimum share kept for each crop.");
      }
    }
    return out.length ? out : ["The constraints conflict (no single simple cause found)."];
  }

  function pareto(p, objective, budgets) {
    return budgets.map(function (b) {
      var s = solve(Object.assign({}, p, { budget: b }), objective, { shadow: false });
      return { budget: b, status: s.status, objective: s.status === "optimal" ? s.objectiveValue : null,
               water: s.status === "optimal" ? s.water : null, area: s.status === "optimal" ? s.area : null };
    });
  }

  function emergencyProblem(d) {
    // d: {crops, water, base, food, minRetained, maxIncrease, foodShare, supplyShare, baseWater, allowFallow}
    var lower = {}, upper = {};
    d.crops.forEach(function (c) { lower[c] = d.base[c] * d.minRetained; upper[c] = d.base[c] * (1 + d.maxIncrease); });
    var total = sum(d.crops.map(function (c) { return d.base[c]; }));
    var foodBase = sum(d.food.map(function (c) { return d.base[c]; }));
    return { crops: d.crops, water: d.water, base: d.base, lower: lower, upper: upper,
             budget: d.supplyShare === null ? null : d.supplyShare * d.baseWater,
             landMax: d.allowFallow === false ? null : total, landEqual: d.allowFallow === false ? total : null,
             food: d.food, foodMin: d.foodShare * foodBase, value: d.value || null, valueMin: null };
  }

  var api = { solve: solve, diagnose: diagnose, pareto: pareto, emergencyProblem: emergencyProblem, rows: rows };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CropMixPlanner = api;
})(this);
