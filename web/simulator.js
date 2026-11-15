/* CropMix Twin — Crop Allocation Simulator page bootstrap (module 10, stage 4: map and territory panel).
 * Reads window.CROPMIX_GEO (web/data/geo.js). No calculations here; the map is geographic context only.
 */
(function () {
  "use strict";

  const geo = window.CROPMIX_GEO;
  const MapLib = window.CropMixMap;
  const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

  const $ = (sel) => document.querySelector(sel);

  function h(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "text") node.textContent = v;
      else node.setAttribute(k, v);
    }
    for (const c of [].concat(children || [])) node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    return node;
  }

  function showFatal(message) {
    const map = $("#map");
    map.replaceChildren(h("p", { class: "map-error", role: "alert", text: message }));
  }

  if (!geo || !MapLib) {
    showFatal("Map data could not be loaded (web/data/geo.js or sim_map.js is missing).");
    return;
  }

  const territories = geo.districts.features.slice().sort((a, b) => {
    if (a.properties.kind !== b.properties.kind) return a.properties.kind === "city" ? -1 : 1;
    return a.properties.name.localeCompare(b.properties.name);
  });
  const totalKm2 = territories.reduce((s, f) => s + f.properties.area_km2_approx, 0);
  const kindLabel = (k) => (k === "city" ? "City" : "District");

  // ---------------------------------------------------------------- info panel

  function noDataNote() {
    return h("div", { class: "callout" }, [
      h("strong", { text: "No district-level data. " }),
      "The model has no crop areas or water use by district; it treats Kyzylorda Region as one unit. " +
      "This map is geographic context only.",
    ]);
  }

  function dl(rows) {
    const list = h("dl", { class: "facts" });
    for (const [term, value, note] of rows) {
      list.appendChild(h("dt", { text: term }));
      list.appendChild(h("dd", {}, note ? [value, h("span", { class: "fact-note", text: note })] : [value]));
    }
    return list;
  }

  function renderOverview() {
    $("#info").replaceChildren(
      h("p", { class: "kicker", text: "Modelling unit" }),
      h("h2", { id: "info-title", class: "info-title", text: "Kyzylorda Region" }),
      dl([
        ["Territories", "7 districts and Kyzylorda City", "Administrative division of 2017"],
        ["Approx. area", `≈ ${fmt.format(Math.round(totalKm2 / 100) * 100)} km²`,
          "Sum of the simplified 2017 territories; not an official figure"],
        ["Boundary data", "geoBoundaries, OpenStreetMap", "ODbL 1.0 · boundary year 2017"],
      ]),
      noDataNote(),
      h("p", { class: "hint", text: "Select a territory on the map or in the list for its details." })
    );
  }

  function renderTerritory(feature) {
    const p = feature.properties;
    const clear = h("button", { type: "button", class: "text-btn", text: "Back to region overview" });
    clear.addEventListener("click", () => { map.select(null); document.getElementById("map").focus(); });
    $("#info").replaceChildren(
      h("p", { class: "kicker", text: kindLabel(p.kind) }),
      h("h2", { id: "info-title", class: "info-title", text: p.name }),
      dl([
        ["2017 boundary label", p.source_name, "Original name in the source data"],
        ["Approx. area", `≈ ${fmt.format(p.area_km2_approx)} km²`, "From the simplified 2017 boundary"],
        ["Boundary source", "geoBoundaries ADM2 (OpenStreetMap)", "ODbL 1.0 · boundary year 2017"],
      ]),
      noDataNote(),
      clear
    );
  }

  // ---------------------------------------------------------------- territory list

  const listButtons = new Map();
  for (const f of territories) {
    const p = f.properties;
    const btn = h("button", { type: "button", class: "territory", "aria-pressed": "false", "data-id": p.id }, [
      h("span", { class: "territory-name", text: p.name }),
      h("span", { class: "territory-kind", text: kindLabel(p.kind) }),
    ]);
    btn.addEventListener("click", () => map.select(p.id === map.selected ? null : p.id));
    btn.addEventListener("mouseenter", () => document.querySelector(`path.district[data-id="${p.id}"]`)?.classList.add("is-hover"));
    btn.addEventListener("mouseleave", () => document.querySelector(`path.district[data-id="${p.id}"]`)?.classList.remove("is-hover"));
    listButtons.set(p.id, btn);
    $("#territories").appendChild(h("li", {}, [btn]));
  }

  // ---------------------------------------------------------------- attribution

  const a = geo.meta.attribution;
  const link = (href, text) => h("a", { href, target: "_blank", rel: "noopener noreferrer", text });
  $("#attribution").append(
    h("li", {}, [a.boundaries + ". ", link(a.osm_copyright_url, "© OpenStreetMap contributors"), " · ",
                 link(a.boundaries_license_url, "ODbL 1.0")]),
    h("li", {}, [a.river + ". ", link(a.river_terms_url, "Natural Earth terms of use")]),
    h("li", { text: "Current English names: Wikipedia (secondary source), used for labels only." })
  );

  // ---------------------------------------------------------------- map

  let selected = null;
  const instance = MapLib.createMap(document.getElementById("map"), {
    geo,
    tooltip: document.getElementById("map-tooltip"),
    scaleBar: document.getElementById("scale-bar"),
    scaleLabel: document.getElementById("scale-label"),
    onSelect(feature) {
      selected = feature ? feature.properties.id : null;
      for (const [id, btn] of listButtons) btn.setAttribute("aria-pressed", String(id === selected));
      if (feature) renderTerritory(feature);
      else renderOverview();
    },
  });
  const map = {
    select: (id) => instance.select(id),
    get selected() { return selected; },
  };

  $("#zoom-in").addEventListener("click", instance.zoomIn);
  $("#zoom-out").addEventListener("click", instance.zoomOut);
  $("#zoom-reset").addEventListener("click", instance.reset);

  renderOverview();

  // ---------------------------------------------------------------- crop area editor (whole region)

  function deepFreeze(o) {
    if (o && typeof o === "object" && !Object.isFrozen(o)) {
      Object.freeze(o);
      Object.values(o).forEach(deepFreeze);
    }
    return o;
  }

  let editor = null;
  const model = window.CROPMIX_MODEL;
  const sim = window.CROPMIX_SIMULATOR;
  const editorRoot = document.getElementById("editor");
  let compare = null;
  let conditionsApi = null;
  let mosaic = null;
  const perf = { rangeMs: [] };          // measured durations of the 612-condition saving range (browser QA)
  if (!model || !sim || !window.CropMixSimCore || !window.CropMixState || !window.CropMixEditor || !window.CropMixStructure ||
      !window.CropMixConditions || !window.CropMixCompare) {
    editorRoot.append(h("p", { class: "map-error", role: "alert",
      text: "Model data could not be loaded (data/model.js, data/simulator.js or a simulator script is missing)." }));
  } else {
    // Exported data are read-only: any accidental mutation (Baseline, Optimized, coefficients) throws.
    deepFreeze(model);
    deepFreeze(sim);
    const core = window.CropMixSimCore.createSimCore(model, sim);
    const State = window.CropMixState;
    const Cond = window.CropMixConditions;
    const X = window.CropMixCompare;
    const condOpts = Cond.createOptions(sim);
    const combos = Cond.allCombinations(condOpts);
    let cond = Cond.reference(condOpts);                 // ONE shared climate + efficiency for all three scenarios

    // The saving range covers all 612 conditions, so it depends only on My areas and the preset: cache it.
    let rangeCache = { key: null, value: null };
    function rangeFor(areas, presetId) {
      const key = presetId + "|" + core.cropIds.map((c) => areas[c]).join(",");
      if (rangeCache.key !== key) {
        const t0 = performance.now();
        const value = X.savingRange(core, combos, areas, presetId);
        perf.rangeMs.push(performance.now() - t0);
        rangeCache = { key, value };
      }
      return rangeCache.value;
    }

    compare = X.createComparison(document.getElementById("compare"), {
      sim, State, Cond, condOptions: condOpts, onStartFromOptimized: () => editor.startFromOptimized(),
    });
    editor = window.CropMixEditor.createEditor(editorRoot, {
      sim, State, Structure: window.CropMixStructure,
      compute: (areas, presetId) => X.compareAll(core, areas, presetId, cond),
      describeConditions: () => Cond.describe(condOpts, cond),
      onRender: (result, st) => {
        compare.render(result, st.preset, result.cmp.constraints.my.ok, rangeFor(st.areas, st.preset));
        if (mosaic) mosaic.update(st.areas);             // the mosaic follows the editor state (one source of areas)
      },
    });
    mosaic = buildCropEditor(State);
    conditionsApi = buildConditionsPanel(Cond, condOpts, () => cond, (next) => {
      if (next === cond) return;
      cond = next;
      editor.refresh();                                  // areas, preset and undo history stay as they are
    });
  }

  // ---------------------------------------------------------------- Crop Editor (schematic mosaic, Edit map mode)

  function buildCropEditor(State) {
    if (!window.CropMixMosaic || !window.CropMixMosaicView) return null;   // Explore keeps working without it
    const view = window.CropMixMosaicView.createMosaicView({
      map: instance, Mosaic: window.CropMixMosaic, sim, editor, fmt: State.fmt,
      panel: document.getElementById("mosaic-panel"),
      badge: document.getElementById("schematic-badge"),
      tooltip: document.getElementById("map-tooltip"),
    });
    const sw = document.getElementById("mode-switch");
    const setMode = (mode) => {
      view.setMode(mode);
      const edit = mode === "edit";
      document.getElementById(`mode-${mode}`).checked = true;
      document.getElementById("explore-panel").hidden = edit;
      document.getElementById("map-help").hidden = edit;
      document.getElementById("map-help-edit").hidden = !edit;
      document.getElementById("map").setAttribute("aria-describedby", edit ? "map-help-edit" : "map-help");
      document.querySelector(".map-card").classList.toggle("is-edit", edit);
    };
    for (const m of ["explore", "edit"]) document.getElementById(`mode-${m}`).addEventListener("change", () => setMode(m));
    sw.hidden = false;
    view.setPageMode = setMode;
    return view;
  }

  // ---------------------------------------------------------------- conditions panel (climate + 36 efficiencies)

  function buildConditionsPanel(Cond, opts, getCond, setCond) {
    const controls = document.getElementById("cond-controls");
    const text = document.getElementById("cond-text");
    const toggle = document.getElementById("cond-toggle");

    const select = h("select", { id: "cond-climate", class: "cond-select" },
      opts.climates.map((c) => h("option", { value: c.key, text: c.key === "mean" ? "Mean 2010–2025 (reference)" : c.key })));
    select.addEventListener("change", () => { setCond(Cond.withClimate(opts, getCond(), select.value)); sync(); });

    function radioGroup(part, legend) {
      const fs = h("fieldset", { class: "cond-group" }, [h("legend", { text: legend })]);
      const row = h("div", { class: "cond-seg" });
      for (const l of opts[part]) {
        const id = `cond-${part}-${l.id}`;
        const input = h("input", { type: "radio", name: `cond-${part}`, id, value: l.id, class: "visually-hidden-input" });
        input.addEventListener("change", () => { setCond(Cond.withEfficiencyPart(opts, getCond(), part, l.id)); sync(); });
        row.append(input, h("label", { for: id, title: l.note ? `${l.label} — ${l.note}` : l.label },
          l.note ? [l.label, h("span", { class: "cond-note", text: " pess." })] : [l.label]));
      }
      fs.append(row);
      return fs;
    }

    const refBtn = h("button", { type: "button", class: "cond-ref",
      title: "Mean climate 2010–2025 and baseline efficiencies. Efficiencies and percolation are assumptions (S073, S074, S082); climate: NASA POWER." },
      "Reference: Cmean · E_base");
    refBtn.addEventListener("click", () => { setCond(Cond.reference(opts)); sync(); });

    controls.append(
      h("div", { class: "cond-group" }, [h("label", { for: "cond-climate", class: "cond-legend", text: "Climate" }), select]),
      radioGroup("field", "Field efficiency"),
      radioGroup("canal", "Canal efficiency"),
      radioGroup("percolation", "Rice percolation"),
      h("div", { class: "cond-group cond-end" }, [refBtn,
        h("p", { class: "cond-foot", text: "Efficiencies and percolation are assumptions (S073, S074, S082). Climate: NASA POWER." })]));

    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", String(open));
      toggle.textContent = open ? "Done" : "Change";
      document.getElementById("conditions").classList.toggle("is-open", open);
    });

    function sync() {
      const c = getCond();
      const p = Cond.parseKey(c.efficiency);
      select.value = c.climate;
      for (const part of Cond.PARTS) {
        const input = document.getElementById(`cond-${part}-${p[part]}`);
        if (input) input.checked = true;
      }
      const ref = Cond.isReference(c);
      refBtn.disabled = ref;
      text.replaceChildren(Cond.describe(opts, c), ref ? h("span", { class: "chip chip-ref", text: "Reference" }) : "");
      document.getElementById("conditions").classList.toggle("is-reference", ref);
    }
    sync();
    return { sync, set: (next) => { setCond(next); sync(); } };
  }

  window.CropMixSimulatorPage = { map: instance, editor, compare, perf, mosaic,                      // for browser QA only
    setConditions: (climate, efficiency) => conditionsApi.set(window.CropMixConditions.makeConditions(
      window.CropMixConditions.createOptions(window.CROPMIX_SIMULATOR), climate, efficiency)) };
})();
