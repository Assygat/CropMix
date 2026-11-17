/* CropMix Twin — data-driven views on the content pages (methodology, evidence, about).
 *
 * No model formulas live here. Every number comes from the exported data and the existing modules:
 *   - window.CROPMIX_MODEL     (data/model.js, written by src/export_web.py): m³/ha coefficients, areas by year,
 *                               official comparison rows;
 *   - window.CROPMIX_SIMULATOR (data/simulator.js, src/export_simulator.py): English crop names and proxies;
 *   - window.CropMixCalc       (model_calc.js): Σ area × coefficient — the same function the simulator core uses;
 *   - window.CROPMIX_GEO + window.CropMixMap (data/geo.js, sim_map.js): projection and boundary helpers.
 * Each view starts only if its container exists on the page, and fails visibly (not silently) if data are missing.
 */
(function () {
  "use strict";

  var M = window.CROPMIX_MODEL, S = window.CROPMIX_SIMULATOR, Calc = window.CropMixCalc;

  function $(id) { return document.getElementById(id); }
  function fmt(x, digits) {
    return Number(x).toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits }).replace(/,/g, " ");
  }
  function el(tag, attrs, children) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") e.textContent = attrs[k]; else if (k === "class") e.className = attrs[k]; else e.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c != null) e.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return e;
  }
  function fail(container, what) {
    container.replaceChildren(el("p", { class: "note", role: "alert", text: "This view could not load " + what +
      ". The rest of the page is unaffected; open the page from the web/ folder of the project so data/ is next to it." }));
  }
  function cropMeta() {
    var byId = {};
    ((S && S.crops) || []).forEach(function (c) { byId[c.id] = c; });
    return byId;
  }
  function option(value, label, selected) {
    var o = el("option", { value: value, text: label });
    if (selected) o.selected = true;
    return o;
  }
  function efficiencySelects(prefix) {
    // levels come from the model export (data/efficiency.csv, data/rice_water.csv via src/export_web.py)
    var sc = M.scenarios;
    function sel(id, label, list, unit, digits) {
      var s = el("select", { id: prefix + id });
      list.forEach(function (l) { s.appendChild(option(l.id, l.id + " · " + fmt(l.value, digits) + unit, l.id === "base")); });
      return el("label", { class: "ctl" }, [el("span", { text: label }), s]);
    }
    return [sel("field", "Field efficiency", sc.eff_field, "", 2),
            sel("canal", "Canal efficiency", sc.eff_canal, "", 3),
            sel("perc", "Rice percolation", sc.rice_percolation, " mm/d", 0)];
  }
  function climateSelect(id, label, withSame) {
    var s = el("select", { id: id });
    if (withSame) s.appendChild(option("same", "Same year", true));
    s.appendChild(option(M.mean_key, "Mean 2010–2025", !withSame));
    M.years.forEach(function (y) { s.appendChild(option(y, "Climate of " + y)); });
    return el("label", { class: "ctl" }, [el("span", { text: label }), s]);
  }
  function key(prefix) { return Calc.scenarioKey($(prefix + "field").value, $(prefix + "canal").value, $(prefix + "perc").value); }
  function chosen(id) { return $(id).selectedOptions[0].textContent; }

  // ------------------------------------------------------------------ methodology: m³/ha per crop
  function coefficientTable(box) {
    var meta = cropMeta();
    var controls = el("div", { class: "explorer-controls" }, [climateSelect("cf-climate", "Climate", false)].concat(efficiencySelects("cf-")));
    var table = el("table", { class: "data", id: "coef-data" });
    var status = el("p", { class: "explorer-status", "aria-live": "polite" });
    box.replaceChildren(controls, status, el("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Water per hectare by crop" }, [table]));

    function render() {
      var k = key("cf-"), c = $("cf-climate").value;
      var ones = {};
      M.crops.forEach(function (cr) { ones[cr.id] = 1; });
      var rows = Calc.cropRows(M, k, c, ones);        // 1 ha of each crop: plant/field/river equal the coefficients
      rows.sort(function (a, b) { return b.coef.river - a.coef.river; });
      table.replaceChildren(
        el("caption", {}, ["Seasonal water per hectare, m³/ha",
          el("small", { text: (c === M.mean_key ? "Mean of the 16 annual values 2010–2025" : "Climate of " + c) +
            " · field efficiency " + chosen("cf-field") + " · canal efficiency " + chosen("cf-canal") + " · rice percolation " + chosen("cf-perc") })]),
        el("thead", {}, [el("tr", {}, [el("th", { scope: "col", text: "Crop group" }), el("th", { scope: "col", text: "Described by" }),
          el("th", { scope: "col", class: "num", text: "Crop need" }), el("th", { scope: "col", class: "num", text: "At the field" }),
          el("th", { scope: "col", class: "num", text: "River withdrawal" })])]),
        el("tbody", {}, rows.map(function (r) {
          var m = meta[r.id] || {};
          return el("tr", { "data-crop": r.id }, [el("th", { scope: "row", text: m.name || r.id }), el("td", { text: m.proxy || "" }),
            el("td", { class: "num", text: fmt(r.coef.plant, 0) }), el("td", { class: "num", text: fmt(r.coef.field, 0) }),
            el("td", { class: "num", text: fmt(r.coef.river, 0) })]);
        })));
      var rice = rows.filter(function (r) { return r.id === "rice"; })[0];
      var others = rows.filter(function (r) { return r.id !== "rice"; }).map(function (r) { return r.coef.river; });
      status.replaceChildren(el("strong", { text: "Rice: " + fmt(rice.coef.river, 0) + " m³/ha" }),
        " from the river; the other seven groups " + fmt(Math.min.apply(null, others), 0) + "–" + fmt(Math.max.apply(null, others), 0) + " m³/ha.");
    }
    box.querySelectorAll("select").forEach(function (s) { s.addEventListener("change", render); });
    render();
  }

  // ------------------------------------------------------------------ evidence: historical crop structures
  function historyExplorer(box) {
    var meta = cropMeta();
    var area = el("select", { id: "hx-area" });
    M.years.slice().reverse().forEach(function (y) { area.appendChild(option(y, "Areas of " + y, y === "2024")); });
    var controls = el("div", { class: "explorer-controls" },
      [el("label", { class: "ctl" }, [el("span", { text: "Crop areas" }), area]), climateSelect("hx-climate", "Climate", true)].concat(efficiencySelects("hx-")));
    var kpis = el("dl", { class: "explorer-kpis" });
    var status = el("p", { class: "explorer-status", "aria-live": "polite" });
    var table = el("table", { class: "data", id: "hx-data" });
    box.replaceChildren(controls, kpis, status, el("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Areas and water by crop" }, [table]));

    function km3(m3) { return fmt(m3 / 1e9, 2); }
    function render() {
      var ay = area.value, cv = $("hx-climate").value, cy = cv === "same" ? ay : cv, k = key("hx-");
      var res = Calc.compute(M, k, cy, M.areas_ha[ay]);
      var t = res.totals;
      kpis.replaceChildren.apply(kpis, [["Crop need", t.plant], ["At the field", t.field], ["River withdrawal", t.river]].map(function (p) {
        return el("div", {}, [el("dt", { text: p[0] }), el("dd", {}, [km3(p[1]), el("small", { text: "km³" })])]);
      }));
      // official figure of the same year; the documented pairing uses areas and climate of that year
      var row = (M.comparison.rows || []).filter(function (r) { return String(r.year) === ay; })[0];
      var label = row ? (row.official_measure === "limit_vegetation" ? "irrigation limit" : "irrigation plan") : null;
      var parts = [el("strong", { text: "W(A" + ay + ", C" + (cy === M.mean_key ? "mean" : cy) + ", E)" }),
        " = " + km3(t.river) + " km³ of river withdrawal for " + fmt(t.area, 0) + " ha of sown area. "];
      if (row && cy === ay) {
        parts.push("Official " + label + " for " + ay + ": " + km3(row.official_m3) + " km³; the model gives ×" + fmt(t.river / row.official_m3, 2) +
          " of it. A limit or plan is an allocated volume, not a measured withdrawal.");
      } else if (row) {
        parts.push("An official " + label + " exists for " + ay + " (" + km3(row.official_m3) + " km³); choose the climate of the same year to compare.");
      } else {
        parts.push("No official withdrawal figure is available for " + ay + ".");
      }
      status.replaceChildren.apply(status, parts);
      var rows = res.rows.slice().sort(function (a, b) { return b.river - a.river; });
      table.replaceChildren(
        el("caption", {}, ["Areas of " + ay + " and modelled water by crop group",
          el("small", { text: "Areas: Bureau of National Statistics (real; other grains derived as all grains − rice − wheat). Water: modelled." })]),
        el("thead", {}, [el("tr", {}, [el("th", { scope: "col", text: "Crop group" }), el("th", { scope: "col", class: "num", text: "Area, ha" }),
          el("th", { scope: "col", class: "num", text: "Share" }), el("th", { scope: "col", class: "num", text: "River, m³/ha" }),
          el("th", { scope: "col", class: "num", text: "River, million m³" })])]),
        el("tbody", {}, rows.map(function (r) {
          return el("tr", { "data-crop": r.id }, [el("th", { scope: "row", text: (meta[r.id] || {}).name || r.id }),
            el("td", { class: "num", text: fmt(r.area, 0) }), el("td", { class: "num", text: fmt(100 * r.area / t.area, 1) + " %" }),
            el("td", { class: "num", text: fmt(r.coef.river, 0) }), el("td", { class: "num", text: fmt(r.river / 1e6, 0) })]);
        })),
        el("tfoot", {}, [el("tr", {}, [el("th", { scope: "row", text: "Total" }), el("td", { class: "num", text: fmt(t.area, 0) }),
          el("td", { class: "num", text: "100 %" }), el("td", { class: "num", text: fmt(t.river / t.area, 0) }),
          el("td", { class: "num", text: fmt(t.river / 1e6, 0) })])]));
    }
    box.querySelectorAll("select").forEach(function (s) { s.addEventListener("change", render); });
    render();
  }

  // ------------------------------------------------------------------ about: region figure from the simulator's geodata
  function regionFigure(svg) {
    var G = window.CROPMIX_GEO, Map = window.CropMixMap;
    var NS = "http://www.w3.org/2000/svg";
    function node(tag, attrs, parent) {
      var n = document.createElementNS(NS, tag);
      Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
      if (parent) parent.appendChild(n);
      return n;
    }
    var proj = Map.createProjection(G.bbox);
    var pad = 6;
    svg.setAttribute("viewBox", [-pad, -pad, proj.width + 2 * pad, proj.height + 2 * pad].join(" "));
    var feats = G.districts.features;
    var outlineD = Map.outerBoundary(feats).map(function (r) { return Map.pathData(r, proj.project, true); }).join("");
    var defs = node("defs", {}, svg);
    var clip = node("clipPath", { id: "rf-clip" }, defs);
    node("path", { d: outlineD }, clip);
    feats.forEach(function (f) {
      node("path", { class: "rf-district", d: Map.featureRings(f).map(function (r) { return Map.pathData(r, proj.project, true); }).join("") }, svg);
    });
    var riverD = G.river.geometry.coordinates.map(function (l) { return Map.pathData(l, proj.project, false); }).join("");
    node("path", { class: "rf-river", d: riverD, opacity: ".3" }, svg);
    node("path", { class: "rf-river", d: riverD, "clip-path": "url(#rf-clip)" }, svg);
    node("path", { class: "rf-outline", d: outlineD }, svg);
    var city = feats.filter(function (f) { return f.properties.kind === "city"; })[0];
    if (city) {
      var p = Map.labelPoint(Map.featureRings(city)[0].map(proj.project), 24);
      node("circle", { class: "rf-city", cx: p[0], cy: p[1], r: 3.2 }, svg);
      node("text", { class: "rf-label", x: p[0] + 7, y: p[1] - 6 }, svg).textContent = "Kyzylorda";
    }
  }

  var coefBox = $("coef-view"), histBox = $("history-explorer"), fig = $("region-svg");
  if (coefBox) { if (M && S && Calc) coefficientTable(coefBox); else fail(coefBox, "the model coefficients"); }
  if (histBox) { if (M && S && Calc) historyExplorer(histBox); else fail(histBox, "the model data"); }
  if (fig) {
    if (window.CROPMIX_GEO && window.CropMixMap) regionFigure(fig);
    else fig.parentNode.replaceChild(el("p", { class: "note", text: "The region map could not load." }), fig);
  }
})();
