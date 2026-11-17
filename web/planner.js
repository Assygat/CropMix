/* CropMix Twin — Decision Lab page (planner.html).
 *
 * Data: window.CROPMIX_PLANNER (data/planner.js, written by src/decision_support.py from outputs/).
 * Optimisation: window.CropMixPlanner (planner_core.js) on window.CropMixLP (lp_solver.js), checked against
 * SciPy/HiGHS by tests/test_planner_crosscheck.py. No water formulas here: m³/ha come from Python.
 */
(function () {
  "use strict";

  var D = window.CROPMIX_PLANNER, PL = window.CropMixPlanner;
  var NAMES = { rice: "Rice", wheat: "Wheat", potato: "Potato", fodder: "Fodder crops", vegetables_open: "Open-field vegetables",
                melons: "Melons", oilseeds: "Oilseeds", grain_other: "Other grains" };
  var RULES = {
    protective: { label: "Protective (assumed)", minRetained: 0.5, maxIncrease: 0.3, foodShare: 0.8, allowFallow: true },
    flexible: { label: "Flexible (assumed)", minRetained: 0.25, maxIncrease: 0.5, foodShare: 0.6, allowFallow: true },
    same_land: { label: "Same land, ±30 % (original moderate preset)", minRetained: 0.7, maxIncrease: 0.3, foodShare: 0.8, allowFallow: false },
    custom: { label: "Custom", minRetained: 0.5, maxIncrease: 0.3, foodShare: 0.8, allowFallow: true }
  };
  var OBJECTIVES = { max_area: "Keep the most cropped area", max_food_area: "Keep the most food-crop area",
                     min_water: "Use the least water", max_value: "Maximise gross value (needs your economic inputs)" };

  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, children) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") e.textContent = attrs[k]; else if (k === "class") e.className = attrs[k];
      else if (k === "html") e.innerHTML = attrs[k]; else e.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c != null) e.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return e;
  }
  function fmt(x, d) {
    if (x === null || x === undefined || !isFinite(x)) return "—";
    return Number(x).toLocaleString("en-GB", { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 }).replace(/,/g, " ");
  }
  function signed(x, d) { return (x > 0 ? "+" : x < 0 ? "−" : "") + fmt(Math.abs(x), d); }
  function km3(m3, d) { return fmt(m3 / 1e9, d === undefined ? 2 : d); }
  function tag(kind, text) { return el("span", { class: "tag tag-" + kind, text: text }); }
  function table(caption, head, rows, foot) {
    var t = el("table", { class: "data" });
    t.appendChild(el("caption", { html: caption }));
    t.appendChild(el("thead", {}, [el("tr", {}, head.map(function (h, i) {
      return el("th", { scope: "col", class: i ? "num" : "", html: h });
    }))]));
    t.appendChild(el("tbody", {}, rows.map(function (r) {
      return el("tr", {}, r.map(function (c, i) {
        if (i === 0) return el("th", { scope: "row" }, [c]);
        return el("td", { class: "num" }, [c]);
      }));
    })));
    if (foot) t.appendChild(el("tfoot", {}, foot.map(function (r) {
      return el("tr", {}, r.map(function (c, i) { return i ? el("td", { class: "num" }, [c]) : el("th", { scope: "row" }, [c]); }));
    })));
    return el("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": caption.replace(/<[^>]+>/g, "") }, [t]);
  }
  function fail(box, what) {
    box.replaceChildren(el("p", { class: "note", role: "alert", text: "This view could not load " + what +
      ". Open the page from the web/ folder of the project so data/ is next to it." }));
  }

  // ---------- economics (user-editable; empty = missing) ----------
  var econ = {};
  function initEcon() {
    D.economics.forEach(function (r) { econ[r.crop] = { y: r.yield_t_ha, p: r.price_kzt_t, c: null }; });
  }
  function valuePerHa() {
    // only crops with both a yield and a price get a value; the solver reports the others as missing
    var v = {};
    D.crops.forEach(function (c) {
      var e = econ[c];
      if (e.y === null || e.p === null || !isFinite(e.y) || !isFinite(e.p)) return;
      v[c] = e.y * e.p - (e.c && isFinite(e.c) ? e.c : 0);
    });
    return v;
  }

  // ---------- climate coefficients from the precomputed grid ----------
  function coefFor(dt, pf) {
    var w = {};
    D.climate_grid.rows.forEach(function (r) {
      if (r.delta_t_c === dt && r.precip_factor === pf) w[r.crop] = r.river_m3_ha;
    });
    return w;
  }
  function et0For(dt, pf) {
    var r = D.climate_grid.rows.find(function (x) { return x.delta_t_c === dt && x.precip_factor === pf; });
    return r ? r.et0_season_mm : NaN;
  }

  // ---------- planner ----------
  function initPlanner(box) {
    var state = { dt: 0, pf: 1, share: 0.7, rules: "protective", objective: "max_area" };
    Object.assign(state, RULES.protective);

    function select(id, label, opts, value) {
      var s = el("select", { id: id });
      opts.forEach(function (o) { var op = el("option", { value: o[0], text: o[1] }); if (String(o[0]) === String(value)) op.selected = true; s.appendChild(op); });
      return { wrap: el("label", { class: "ctl", for: id }, [el("span", { text: label }), s]), input: s };
    }
    function number(id, label, value, min, max, step, suffix) {
      var i = el("input", { id: id, type: "number", min: min, max: max, step: step, value: value, inputmode: "decimal" });
      return { wrap: el("label", { class: "ctl ctl-num", for: id }, [el("span", { text: label }), el("div", { class: "num-wrap" }, [i, el("i", { text: suffix })])]), input: i };
    }

    var cDt = select("pl-dt", "Warming (experiment)", [[0, "None (2010–2025 climate)"], [1, "+1 °C"], [2, "+2 °C"], [3, "+3 °C"], [4, "+4 °C"]], 0);
    var cPf = select("pl-pf", "Rainfall (experiment)", [[1, "As observed"], [0.85, "−15 %"], [0.7, "−30 %"], [0.5, "−50 %"]], 1);
    var cRules = select("pl-rules", "Planning rules", Object.keys(RULES).map(function (k) { return [k, RULES[k].label]; }), "protective");
    var cObj = select("pl-obj", "Objective", Object.keys(OBJECTIVES).map(function (k) { return [k, OBJECTIVES[k]]; }), "max_area");
    var range = el("input", { id: "pl-share", type: "range", min: "40", max: "110", step: "1", value: "70", "aria-describedby": "pl-share-out" });
    var shareOut = el("output", { id: "pl-share-out", for: "pl-share" });
    var shareCtl = el("div", { class: "ctl ctl-range" }, [el("label", { for: "pl-share" }, [el("span", { text: "Water available" })]), range, shareOut]);
    var nMin = number("pl-min", "Each crop keeps at least", 50, 0, 100, 5, "% of 2025");
    var nMax = number("pl-max", "Each crop grows by at most", 30, 0, 200, 5, "%");
    var nFood = number("pl-food", "Food crops keep at least", 80, 0, 130, 5, "% of 2025");
    var fallow = el("input", { id: "pl-fallow", type: "checkbox", checked: "checked" });
    var fallowCtl = el("label", { class: "ctl ctl-check", for: "pl-fallow" }, [fallow, el("span", { text: "Land may stay unsown" })]);

    var kpis = el("dl", { class: "explorer-kpis pl-kpis" });
    var status = el("div", { class: "pl-status", "aria-live": "polite" });
    var cropsBox = el("div");
    var explainBox = el("div", { class: "pl-explain" });
    var paretoBox = el("figure", { class: "pl-pareto" });

    box.replaceChildren(
      el("div", { class: "explorer" }, [
        el("div", { class: "explorer-controls" }, [shareCtl, cDt.wrap, cPf.wrap]),
        el("div", { class: "explorer-controls pl-row" }, [cRules.wrap, cObj.wrap]),
        el("div", { class: "explorer-controls pl-row" }, [nMin.wrap, nMax.wrap, nFood.wrap, fallowCtl]),
        kpis, status]),
      el("div", { class: "pl-grid" }, [el("div", {}, [el("h3", { text: "Crop areas in the plan" }), cropsBox]),
        el("div", {}, [el("h3", { text: "Why this plan" }), explainBox])]),
      el("h3", { text: "Water versus area kept" }), paretoBox);

    function syncRuleInputs() {
      nMin.input.value = Math.round(state.minRetained * 100);
      nMax.input.value = Math.round(state.maxIncrease * 100);
      nFood.input.value = Math.round(state.foodShare * 100);
      fallow.checked = state.allowFallow;
    }
    function read() {
      state.dt = Number(cDt.input.value); state.pf = Number(cPf.input.value);
      state.share = Number(range.value) / 100; state.objective = cObj.input.value;
      state.minRetained = clamp(Number(nMin.input.value) / 100, 0, 1);
      state.maxIncrease = clamp(Number(nMax.input.value) / 100, 0, 2);
      state.foodShare = clamp(Number(nFood.input.value) / 100, 0, 1.3);
      state.allowFallow = fallow.checked;
    }
    function clamp(v, a, b) { return isFinite(v) ? Math.min(b, Math.max(a, v)) : a; }

    function problem(share) {
      return PL.emergencyProblem({ crops: D.crops, water: coefFor(state.dt, state.pf), base: D.base_ha, food: D.food,
        minRetained: state.minRetained, maxIncrease: state.maxIncrease, foodShare: state.foodShare,
        supplyShare: share, baseWater: D.base_water_m3, allowFallow: state.allowFallow, value: valuePerHa() });
    }

    function render() {
      read();
      var p = problem(state.share);
      var budget = state.share * D.base_water_m3;
      var demand = D.crops.reduce(function (s, c) { return s + p.water[c] * D.base_ha[c]; }, 0);
      shareOut.textContent = Math.round(state.share * 100) + " % · " + km3(budget) + " km³";
      var s = PL.solve(p, state.objective);
      var total = D.crops.reduce(function (a, c) { return a + D.base_ha[c]; }, 0);
      kpis.replaceChildren();
      function kpi(t, v, u) { kpis.appendChild(el("div", {}, [el("dt", { text: t }), el("dd", {}, [v, u ? el("small", { text: u }) : null])])); }
      kpi("Demand of the 2025 mix", km3(demand), "km³");
      kpi("Water available", km3(budget), "km³");
      if (s.status === "optimal") {
        kpi("Water used by the plan", km3(s.water), "km³");
        kpi("Area kept", fmt(100 * s.area / total, 1), "% of 2025");
      } else { kpi("Water used by the plan", "—"); kpi("Area kept", "—"); }

      var climateNote = (state.dt || state.pf !== 1) ?
        " Climate: " + (state.dt ? "+" + state.dt + " °C" : "observed temperature") + ", rainfall " + (state.pf === 1 ? "as observed" : "× " + state.pf) +
        " (season ET₀ " + fmt(et0For(state.dt, state.pf)) + " mm vs " + fmt(et0For(0, 1)) + " mm); a sensitivity experiment, not a projection." : "";
      if (s.status === "optimal") {
        var u = Math.min(1, budget / demand);
        var uniformOk = u >= state.minRetained && u >= state.foodShare;
        status.replaceChildren(el("p", { class: "pl-ok" }, [tag("model", "plan found"), " ",
          (demand <= budget * (1 + 1e-9) ? "The 2025 mix already fits within the available water; the plan changes it only where the objective gains." :
            "The 2025 mix needs " + km3(demand - budget) + " km³ more than is available, so it cannot be kept as it is." +
            " A uniform cut would keep " + fmt(100 * u, 1) + " % of the area" + (uniformOk ? "" : " and would break the minimum-area or food rule") +
            "; this plan keeps " + fmt(100 * s.area / total, 1) + " %."),
          climateNote]));
      } else if (s.status === "unavailable") {
        status.replaceChildren(el("p", { class: "note", role: "status" }, [tag("assumed", "needs inputs"), " ", s.message,
          " Enter the missing values in section 05 below."]));
      } else if (s.status !== "infeasible") {
        status.replaceChildren(el("p", { class: "note pl-bad", role: "alert" }, [el("strong", { text: "No plan shown. " }),
          s.message || "The solver did not return a usable plan (" + s.status + ")."]));
      } else {
        status.replaceChildren(el("div", { class: "note pl-bad", role: "status" }, [el("div", {}, [
          el("p", {}, [el("strong", { text: "No plan meets all the rules with this much water." }),
            " Nothing was relaxed automatically. To restore feasibility:"]),
          el("ul", {}, (s.diagnosis || []).map(function (d) { return el("li", { text: d }); }))])]));
      }

      // crop table
      var rows = D.crops.map(function (c) {
        var x = s.status === "optimal" ? s.areas[c] : null, b0 = D.base_ha[c];
        var y = econ[c].y;
        var bar = el("span", { class: "pl-bar", "aria-hidden": "true" });
        if (x !== null) bar.style.setProperty("--w", Math.min(100, 100 * x / (b0 * (1 + state.maxIncrease) || 1)) + "%");
        var bn = s.status === "optimal" ? (s.bounds || []).find(function (q) { return q.crop === c; }) : null;
        return [el("span", {}, [NAMES[c] || c, D.food.indexOf(c) >= 0 ? el("small", { class: "pl-food", text: " food" }) : null]),
          fmt(b0), x === null ? "—" : el("span", { class: "pl-cell" }, [bar, fmt(x)]),
          x === null ? "—" : signed(100 * (x / b0 - 1), 0) + " %" + (bn ? (bn.side === "lower" ? " · min" : bn.side === "upper" ? " · max" : "") : ""),
          fmt(p.water[c]), x === null || !y ? "—" : fmt(x * y)];
      });
      cropsBox.replaceChildren(table("Plan by crop group<small>m³/ha: river withdrawal per hectare under the chosen climate. Output (t) only where a regional yield exists.</small>",
        ["Crop group", "2025, ha", "Plan, ha", "Change", "m³/ha", "Output, t"], rows,
        s.status === "optimal" ? [["Total", fmt(total), fmt(s.area), signed(100 * (s.area / total - 1), 1) + " %", "", ""],
          ["River withdrawal, km³", km3(demand), km3(s.water), signed(100 * (s.water / demand - 1), 1) + " %", "", ""]] : null));

      // explanation
      explainBox.replaceChildren(explain(s, p));
      drawPareto();
    }

    function explain(s, p) {
      var ul = el("ul", { class: "pl-why" });
      if (s.status !== "optimal") { ul.appendChild(el("li", { text: "No explanation: there is no feasible plan (see the box above)." })); return ul; }
      var unit = s.objective === "min_water" ? "m³" : s.objective === "max_value" ? "KZT" : "ha";
      s.constraints.forEach(function (c) {
        if (c.kind === "water") {
          if (c.binding && s.objective !== "min_water") {
            ul.appendChild(el("li", {}, [el("b", { text: "Water is the limiting rule. " }),
              "Each extra million m³ would add about " + fmt(c.shadow * 1e6, unit === "KZT" ? 0 : 1) + " " + unit +
              " to the objective (shadow price, valid only for small changes)."]));
          } else {
            ul.appendChild(el("li", {}, [el("b", { text: "Water is not limiting. " }), fmt(c.slack / 1e9, 3) + " km³ of the budget is left unused."]));
          }
        } else if (c.kind === "food" && c.binding) {
          ul.appendChild(el("li", {}, [el("b", { text: "The food-crop minimum binds. " }),
            "Lowering it by 1 000 ha would " + (s.objective === "min_water" ? "save about " + fmt(c.shadow * 1000) + " m³" :
              "add about " + fmt(c.shadow * 1000, 0) + " " + unit + " to the objective") + ". Food crops keep " + fmt(c.lhs) + " ha."]));
        } else if (c.kind === "land" && c.binding) {
          ul.appendChild(el("li", {}, [el("b", { text: c.name === "land fixed" ? "Total area is fixed. " : "All land is in use. " }),
            (s.objective === "min_water" ? "Each additional hectare that must be sown costs about " + fmt(Math.abs(c.shadow)) + " m³" :
              "Each additional hectare of land would add about " + fmt(c.shadow, 2) + " " + unit) + " (shadow price)."]));
        }
      });
      var lows = (s.bounds || []).filter(function (b) { return b.side === "lower"; }).map(function (b) { return NAMES[b.crop]; });
      var highs = (s.bounds || []).filter(function (b) { return b.side === "upper"; }).map(function (b) { return NAMES[b.crop]; });
      if (lows.length) ul.appendChild(el("li", {}, [el("b", { text: "At their minimum area: " }), lows.join(", ") + ". These lose the most land; the rule stops them falling further."]));
      if (highs.length) ul.appendChild(el("li", {}, [el("b", { text: "At their maximum area: " }), highs.join(", ") + ". These use the least water per hectare and grow as far as the rules allow."]));
      var free = D.crops.filter(function (c) { return !(s.bounds || []).some(function (b) { return b.crop === c; }); });
      if (free.length) ul.appendChild(el("li", {}, [el("b", { text: "Between their limits: " }), free.map(function (c) { return NAMES[c]; }).join(", ") +
        (free.length > 1 ? ". These crops absorb" : ". This crop absorbs") + " the remaining water or land, so their water per hectare sets the shadow prices."]));
      return ul;
    }

    function drawPareto() {
      var shares = []; for (var v = 40; v <= 110; v += 2.5) shares.push(v / 100);
      var base = problem(1);
      var pts = PL.pareto(base, "max_area", shares.map(function (s) { return s * D.base_water_m3; }));
      var total = D.crops.reduce(function (a, c) { return a + D.base_ha[c]; }, 0);
      var W = 640, H = 300, L = 54, R = 16, T = 16, B = 44;
      function X(s) { return L + (s - 0.4) / 0.7 * (W - L - R); }
      function Y(a) { return T + (1 - (a - 30) / 80) * (H - T - B); }
      var svg = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-labelledby="pl-par-t">';
      svg += '<title id="pl-par-t">Largest cropped area achievable (percent of 2025) for each water share, with the current rules and climate</title>';
      [30, 50, 70, 90, 110].forEach(function (a) {
        svg += '<line class="g" x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(a) + '" y2="' + Y(a) + '"/><text class="ax" x="' + (L - 8) + '" y="' + (Y(a) + 4) + '" text-anchor="end">' + a + "%</text>";
      });
      [0.4, 0.6, 0.8, 1.0].forEach(function (s) {
        svg += '<text class="ax" x="' + X(s) + '" y="' + (H - B + 18) + '" text-anchor="middle">' + Math.round(s * 100) + "%</text>";
      });
      svg += '<text class="ax" x="' + ((L + W - R) / 2) + '" y="' + (H - 6) + '" text-anchor="middle">water available, % of the 2025 mix’s average-year demand</text>';
      svg += '<line class="uni" x1="' + X(0.4) + '" y1="' + Y(40) + '" x2="' + X(1.0) + '" y2="' + Y(100) + '"/>';
      var d = "", infeas = [];
      pts.forEach(function (q, i) {
        if (q.status === "optimal") { d += (d ? "L" : "M") + X(shares[i]).toFixed(1) + " " + Y(100 * q.area / total).toFixed(1); }
        else infeas.push(shares[i]);
      });
      if (infeas.length) svg += '<rect class="nf" x="' + X(0.4) + '" y="' + T + '" width="' + (X(Math.max.apply(null, infeas) + 0.0125) - X(0.4)) + '" height="' + (H - T - B) + '"/>';
      svg += '<path class="pf" d="' + d + '"/>';
      var cur = PL.solve(problem(state.share), "max_area", { shadow: false });
      if (cur.status === "optimal") svg += '<circle class="cur" cx="' + X(state.share) + '" cy="' + Y(100 * cur.area / total) + '" r="6"/>';
      svg += "</svg>";
      paretoBox.innerHTML = svg;
      paretoBox.appendChild(el("figcaption", {}, [
        "Solid line: the most area any plan can keep (Pareto curve, objective “keep the most cropped area”). Dashed: a uniform cut. ",
        infeas.length ? "Shaded: no plan meets the rules (below " + Math.round((Math.max.apply(null, infeas) + 0.025) * 100) + " % of demand). " : "",
        "Dot: your current setting. Each point is a separate linear programme solved in your browser."]));
    }

    cRules.input.addEventListener("change", function () {
      state.rules = cRules.input.value;
      if (state.rules !== "custom") Object.assign(state, RULES[state.rules]);
      syncRuleInputs(); render();
    });
    [nMin.input, nMax.input, nFood.input, fallow].forEach(function (i) {
      i.addEventListener("change", function () { cRules.input.value = "custom"; render(); });
    });
    [cDt.input, cPf.input, cObj.input].forEach(function (i) { i.addEventListener("change", render); });
    range.addEventListener("input", render);
    syncRuleInputs();
    render();
    return render;
  }

  // ---------- static views from Python results ----------
  function stressView(box) {
    var em = {};
    D.stress_emergency.forEach(function (r) { em[r.scenario] = r; });
    var rows = D.stress.map(function (r) {
      var e = em[r.scenario] || {};
      var kind = r.scenario === "normal" ? tag("real", "observed climate") : r.scenario === "drought_year" ? tag("real", "observed year " + r.climate.replace("C", "")) : tag("assumed", "experiment");
      return [el("span", {}, [r.label, " ", kind]),
        r.delta_t_c ? "+" + fmt(r.delta_t_c) + " °C" : "—", r.precip_factor === 1 ? "—" : signed(100 * (r.precip_factor - 1), 0) + " %",
        fmt(r.et0_season_mm), km3(r.river_m3), signed(r.river_vs_normal_pct, 1) + " %", km3(r.available_m3),
        fmt(r.deficit_pct_of_demand, 1) + " %", e.status === "optimal" ? fmt(e.opt_area_pct, 1) + " %" : "no plan"];
    });
    box.replaceChildren(table("Stress scenarios, 2025 crop mix<small>ET₀: April–October sum. Withdrawal: model, base efficiencies.</small>",
      ["Scenario", "ΔT", "Rain", "ET₀, mm", "Demand, km³", "vs normal", "Available, km³", "Shortfall", "Area kept"], rows));
  }

  function referenceView(box) {
    var groups = {};
    D.emergency_summary.forEach(function (r) { (groups[r.preset] = groups[r.preset] || []).push(r); });
    var rows = [];
    Object.keys(groups).forEach(function (k) {
      groups[k].forEach(function (r) {
        rows.push([(k === "protective" ? "Protective" : "Flexible") + " · " + Math.round(r.supply_share * 100) + " % water",
          km3(r.budget_m3), r.status === "optimal" ? fmt(r.opt_area_pct, 1) + " %" : "no plan",
          fmt(100 * r.supply_share, 0) + " %" + (r.uniform_respects_constraints ? "" : " *"),
          r.status === "optimal" ? signed(r.area_gain_vs_uniform_ha) : "—",
          r.status === "optimal" ? fmt(r.water_shadow_ha_per_mln_m3, 1) : "—"]);
      });
    });
    box.replaceChildren(table("Scarcity levels, average climate<small>From outputs/emergency_summary.csv (SciPy/HiGHS). * a uniform cut breaks the minimum-area rule.</small>",
      ["Rules · water", "Available, km³", "Area kept (plan)", "Area kept (uniform cut)", "Plan vs uniform, ha", "ha per extra million m³"], rows));
    var bad = D.emergency_summary.filter(function (r) { return r.status !== "optimal"; });
    if (bad.length) {
      box.appendChild(el("p", { class: "table-note", text: "Where there is no plan, the solver reports why. For example, protective rules at " +
        Math.round(bad[0].supply_share * 100) + " % water: " + bad[0].diagnosis.split(" | ")[0] + "." }));
    }
  }

  function whyView(box) {
    var rows = D.attribution.map(function (r) { return [r.experiment, fmt(r.saving_pct, 2) + " %"]; });
    var dec = D.attribution_crops.map(function (r) {
      return [NAMES[r.crop], signed(r.change_ha), fmt(r.water_m3_ha), signed(r.water_change_m3 / 1e9, 3)];
    });
    var cut = D.attribution_crops.filter(function (r) { return r.water_change_m3 < 0; }).reduce(function (s, r) { return s - r.water_change_m3; }, 0);
    var back = D.attribution_crops.filter(function (r) { return r.water_change_m3 > 0; }).reduce(function (s, r) { return s + r.water_change_m3; }, 0);
    var fod = D.attribution_crops.find(function (r) { return r.crop === "fodder"; });
    box.replaceChildren(
      table("One rule relaxed at a time (moderate preset, same land, average climate)<small>From outputs/decision_attribution.csv. Diagnostic runs, not recommendations.</small>",
        ["Experiment", "Water saved"], rows),
      table("Where the moderate plan’s saving goes<small>From outputs/decision_attribution_crops.csv.</small>",
        ["Crop group", "Area change, ha", "m³/ha", "Water change, km³"], dec),
      el("ul", {}, [
        el("li", { text: "Cutting rice frees " + km3(cut, 3) + " km³, but " + km3(back, 3) + " km³ (" + fmt(100 * back / cut, 0) +
          " %) is used again by the crops that take over its land. Fodder alone takes " + km3(fod.water_change_m3, 3) +
          " km³, because it needs nearly as much water per hectare as rice." }),
        el("li", { text: "The food-crop minimum is not binding in this preset: removing it changes nothing." }),
        el("li", { text: "The upper limits of the low-water crops bind hardest. Wheat, melons, vegetables, oilseeds and potato are small groups, so +30 % of a small area is little land. Doubling their limits more than doubles the saving." }),
        el("li", { text: "Large savings appear only when land may be left unsown. That is a decision about how much to farm, not about which crops to grow, so it is shown separately and labelled." })
      ]));
  }

  function econView(box, rerender) {
    var rows = D.economics.map(function (r) {
      function inp(field, val, label) {
        var i = el("input", { type: "number", min: "0", step: "any", value: val === null ? "" : String(val), "aria-label": label + ", " + NAMES[r.crop], class: "pl-econ" });
        i.addEventListener("change", function () { econ[r.crop][field] = i.value === "" ? null : Number(i.value); rerender(); });
        return i;
      }
      function st(s) { return s === "missing" ? tag("assumed", "missing") : s === "real" ? tag("real", "regional statistic") : tag("assumed", "assumed / national"); }
      return [el("span", {}, [NAMES[r.crop], r.note ? el("small", { class: "pl-econ-note", text: " — " + r.note }) : null]),
        el("span", {}, [inp("y", r.yield_t_ha, "Yield t/ha"), " ", st(r.yield_status)]),
        el("span", {}, [inp("p", r.price_kzt_t, "Price KZT/t"), " ", st(r.price_status)]),
        el("span", {}, [inp("c", null, "Cost KZT/ha"), " ", tag("assumed", "not in data")])];
    });
    box.replaceChildren(table("Yield, price and cost per crop group<small>Defaults from data/yields.csv (2025) and data/prices.csv (2026). Edits stay in this browser tab.</small>",
      ["Crop group", "Yield, t/ha", "Price, KZT/t", "Cost, KZT/ha"], rows));
  }

  document.addEventListener("DOMContentLoaded", function () {
    var box = $("planner");
    if (!box) return;
    if (!D || !PL || !window.CropMixLP) { fail(box, "the planner data or solver"); return; }
    initEcon();
    var rerender = initPlanner(box);
    var sv = $("stress-view"), rv = $("reference-view"), wv = $("why-view"), ev = $("econ-view");
    if (sv) stressView(sv);
    if (rv) referenceView(rv);
    if (wv) whyView(wv);
    if (ev) econView(ev, rerender);
  });
})();
