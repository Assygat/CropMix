/* CropMix Twin — Crop Editor view (module 10, stage E3).
 *
 * Draws the SCHEMATIC crop mosaic on the region map in "Edit map" mode and turns brush strokes into area edits.
 * The editor state (sim_state.js via sim_editor.js) is the only source of areas: the mosaic is re-derived from it
 * after every change (cellCounts → reconcile), and a stroke goes back through editor.applyAreas as one undo step.
 * 1 cell = 100 ha of sown area. Cell positions are illustrative only: there are no field locations in the data.
 * No water is computed here.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CropMixMosaicView = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const CELL_SCALE = 0.97;                 // drawn hexagon / grid hexagon: ~3 % gap between cells
  const LABEL_PX = 12;                     // crop label size on screen
  const FADE_MS = 360;                     // crossfade of cells that change crop
  const BRUSH_SIZES = [0, 1, 2, 3];        // hex radius → 1, 7, 19, 37 cells
  const PATTERNED = ["wheat", "vegetables_open", "oilseeds", "grain_other"];
  const TOOLS = ["hand", "brush", "eraser"];

  const ICONS = {
    hand: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.5 8V3.6a1 1 0 0 1 2 0V7m0-.5V2.8a1 1 0 0 1 2 0V7m0-.6V3.6a1 1 0 0 1 2 0V9c0 3-1.6 5-4.3 5-1.9 0-2.9-.9-3.8-2.4L2.3 9.4a1 1 0 0 1 1.6-1.1L5.5 10" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    brush: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m9.5 3.2 3.3 3.3-5.6 5.6-3.3-3.3Z" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M3.9 8.8 2 14l5.2-1.9" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="m11 1.7 3.3 3.3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    eraser: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m9.6 2.6 3.8 3.8-6.3 6.3H4.3L2.6 11a1.2 1.2 0 0 1 0-1.7Z" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M6.1 6.1 9.9 9.9M7.5 12.7h6" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    undo: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.5 3.5 2.5 6.5l3 3M3 6.5h6.5a4 4 0 0 1 0 8H7" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    auto: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5v2.2M8 12.3v2.2M1.5 8h2.2M12.3 8h2.2M3.4 3.4 5 5M11 11l1.6 1.6M3.4 12.6 5 11M11 5l1.6-1.6" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/><circle cx="8" cy="8" r="2.2" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>',
    pattern: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="2" width="12" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M2.5 9.5 9.5 2.5M5 13.5 13.5 5M9.5 13.5l4-4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>',
  };

  function svgEl(tag, attrs, parent) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  }

  function h(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined) continue;
      if (k === "text") node.textContent = v;
      else if (k === "html") node.innerHTML = v;            // only the static ICONS above
      else if (k === "style") node.style.cssText = v;
      else node.setAttribute(k, v);
    }
    for (const c of [].concat(children || [])) if (c !== null && c !== undefined) node.append(c);
    return node;
  }

  const media = (q) => typeof window !== "undefined" && !!window.matchMedia && window.matchMedia(q).matches;

  /** Pointy-top hexagon path around (x, y) with circumradius s. */
  function hexPath(x, y, s) {
    let d = "";
    for (let j = 0; j < 6; j++) {
      const a = Math.PI / 180 * (60 * j - 30);
      d += (j ? "L" : "M") + (x + s * Math.cos(a)).toFixed(2) + "," + (y + s * Math.sin(a)).toFixed(2);
    }
    return d + "Z";
  }

  /**
   * options: { map (sim_map instance), Mosaic (sim_mosaic.js), sim, editor (sim_editor API), fmt (sim_state fmt),
   *            panel (element shown in Edit map mode), badge, tooltip }
   */
  function createMosaicView(options) {
    const { map, Mosaic, sim, editor, fmt } = options;
    const crops = sim.crops;
    const cropIds = crops.map((c) => c.id);
    const nameOf = Object.fromEntries(crops.map((c) => [c.id, c.name]));
    const HA = Mosaic.HA_PER_CELL;
    const capacity = Math.round(cropIds.reduce((s, c) => s + sim.baseline.areas_ha[c], 0) / HA);
    const perf = { buildMs: null, updateMs: [], strokeMs: [], labelMs: [] };

    let grid = null;
    let cellD = null;                      // cached hexagon path per cell
    let layout = null;
    let areas = editor.getState().areas;   // last areas received from the editor (never edited here)
    let overflow = 0;
    let tool = "brush";
    let brush = 1;
    let crop = cropIds[0];
    let patterns = media("(forced-colors: active)");
    let focusCrop = null;
    const layoutByAreas = new WeakMap();  // areas object → layout, so Undo restores the exact picture

    // ---------------------------------------------------------------- SVG layers
    const layer = map.layers.mosaic;
    const labelLayer = map.layers.cropLabels;
    const defs = svgEl("defs", {}, layer);
    const cropPaths = {};
    for (const c of cropIds) cropPaths[c] = svgEl("path", { class: "mz-crop", "data-crop": c }, layer);
    const unsownPath = svgEl("path", { class: "mz-unsown" }, layer);
    const ghostLayer = svgEl("g", { class: "mz-ghosts" }, layer);
    const brushPath = svgEl("path", { class: "mz-brush" }, layer);
    const labelNodes = {};

    const fillFor = (c) => (patterns && PATTERNED.includes(c) ? `url(#mz-pat-${c})` : `var(--crop-${c})`);

    function buildPatterns() {
      defs.replaceChildren();
      const step = grid.size * 0.42;
      PATTERNED.forEach((c, j) => {
        const p = svgEl("pattern", { id: `mz-pat-${c}`, width: step.toFixed(3), height: step.toFixed(3), patternUnits: "userSpaceOnUse",
                                     patternTransform: `rotate(${j % 2 ? 135 : 45})` }, defs);
        svgEl("rect", { width: step.toFixed(3), height: step.toFixed(3), style: `fill: var(--crop-${c})` }, p);
        svgEl("line", { x1: 0, y1: 0, x2: 0, y2: step.toFixed(3), class: "mz-hatch", "stroke-width": (step * 0.32).toFixed(3) }, p);
      });
    }

    function applyFills() {
      for (const c of cropIds) cropPaths[c].style.fill = fillFor(c);
    }

    function ensureGrid() {
      if (grid) return;
      const t0 = performance.now();
      grid = Mosaic.buildGrid(map.outlineRing, capacity);
      cellD = grid.cells.map((c) => hexPath(c.x, c.y, grid.size * CELL_SCALE));
      buildPatterns();
      applyFills();
      perf.buildMs = performance.now() - t0;
    }

    // ---------------------------------------------------------------- drawing
    function draw(lay) {
      const parts = Object.fromEntries(cropIds.map((c) => [c, []]));
      const unsown = [];
      for (let i = 0; i < lay.length; i++) (lay[i] === null ? unsown : parts[lay[i]]).push(cellD[i]);
      for (const c of cropIds) cropPaths[c].setAttribute("d", parts[c].join(""));
      unsownPath.setAttribute("d", unsown.join(""));
    }

    /** Old colours of the changed cells fade out over the new picture (skipped with reduced motion). */
    function crossfade(before, after) {
      ghostLayer.replaceChildren();
      if (!before || media("(prefers-reduced-motion: reduce)")) return;
      const diff = Mosaic.diffLayouts(before, after);
      if (!diff.length) return;
      const byFrom = new Map();
      for (const ch of diff) {
        const k = ch.from === null ? "_" : ch.from;
        if (!byFrom.has(k)) byFrom.set(k, []);
        byFrom.get(k).push(cellD[ch.id]);
      }
      for (const [k, ds] of byFrom) {
        const g = svgEl("path", { class: "mz-ghost" + (k === "_" ? " mz-unsown" : ""), d: ds.join("") }, ghostLayer);
        if (k !== "_") g.style.fill = fillFor(k);
      }
      const token = ghostLayer.dataset.token = String(performance.now());
      setTimeout(() => { if (ghostLayer.dataset.token === token) ghostLayer.replaceChildren(); }, FADE_MS + 40);
    }

    function setLayout(next, animate) {
      const before = layout;
      layout = next;
      draw(layout);
      if (animate) crossfade(before, layout);
      scheduleLabels();
      renderPanel();
    }

    // ---------------------------------------------------------------- sync with the editor state
    /** Called on every editor render: re-derives the mosaic from the areas (the only source of truth). */
    function update(nextAreas) {
      areas = nextAreas;
      if (!grid || map.getMode() !== "edit") { renderPanel(); return; }
      const t0 = performance.now();
      const cc = Mosaic.cellCounts(areas, cropIds, HA, capacity);
      overflow = cc.overflow;
      const remembered = layoutByAreas.get(areas);
      let next;
      if (remembered) next = remembered;
      else if (!layout) next = Mosaic.initialLayout(grid, cc.counts, cropIds);
      else next = Mosaic.reconcile(grid, layout, cc.counts, cropIds).layout;
      layoutByAreas.set(areas, next);
      setLayout(next, layout !== null && next !== layout);
      perf.updateMs.push(performance.now() - t0);
    }

    // ---------------------------------------------------------------- brush strokes
    let stroke = null;   // { before, now, last: [x, y] }

    function stamp(pt) {
      const id = Mosaic.cellAt(grid, pt[0], pt[1]);
      if (id === null) return;
      const res = Mosaic.paint(stroke.now, Mosaic.brushCells(grid, id, brush), tool === "eraser" ? null : crop);
      if (res.changed.length) stroke.now = res.layout;
    }

    function strokeTo(pt) {
      const [x0, y0] = stroke.last;
      const dist = Math.hypot(pt[0] - x0, pt[1] - y0);
      const steps = Math.max(1, Math.ceil(dist / (grid.size * 0.7)));     // no gaps when the pointer moves fast
      for (let k = 1; k <= steps; k++) stamp([x0 + (pt[0] - x0) * k / steps, y0 + (pt[1] - y0) * k / steps]);
      stroke.last = pt;
      draw(stroke.now);
    }

    function showBrush(pt) {
      const id = Mosaic.cellAt(grid, pt[0], pt[1]);
      brushPath.setAttribute("d", id === null ? "" : Mosaic.brushCells(grid, id, brush).map((i) => cellD[i]).join(""));
      brushPath.classList.toggle("is-eraser", tool === "eraser");
    }

    // A finger has no hover: once it lifts, the brush outline would stay on the map, so it is cleared. With a mouse
    // the outline keeps following the cursor (hover() redraws it), so nothing changes there.
    function clearTouchBrush(pointerType) {
      if (pointerType === "touch") brushPath.setAttribute("d", "");
    }

    const handler = {
      paints: () => tool !== "hand" && grid !== null && layout !== null,
      down(pt) {
        stroke = { before: layout, now: layout, last: pt };
        ghostLayer.replaceChildren();
        hideTip();
        stamp(pt);
        draw(stroke.now);
        showBrush(pt);
      },
      move(pt) { if (stroke) { strokeTo(pt); showBrush(pt); } },
      up(pointerType) {
        clearTouchBrush(pointerType);
        if (!stroke) return;
        const t0 = performance.now();
        const { before, now } = stroke;
        stroke = null;
        const changes = Mosaic.diffLayouts(before, now);
        if (!changes.length) return;
        const nextAreas = Mosaic.strokeAreas(areas, changes, HA);
        layoutByAreas.set(areas, before);
        layout = now;                                     // reconcile after the commit starts from the painted picture
        editor.applyAreas(nextAreas);                     // → editor render → onRender → update(new areas)
        perf.strokeMs.push(performance.now() - t0);
      },
      cancel(pointerType) {
        clearTouchBrush(pointerType);
        if (!stroke) return;
        stroke = null;
        draw(layout);
      },
      hover(pt, clientX, clientY) {
        if (!pt || !grid || !layout) { hideTip(); brushPath.setAttribute("d", ""); return; }
        if (tool !== "hand") showBrush(pt); else brushPath.setAttribute("d", "");
        const id = Mosaic.cellAt(grid, pt[0], pt[1]);
        if (id === null) { hideTip(); return; }
        const c = layout[id];
        showTip(`${c === null ? "Unsown" : nameOf[c]} · 1 cell = 100 ha · schematic`, clientX, clientY);
      },
    };
    map.setEditHandler(handler);

    // ---------------------------------------------------------------- tooltip
    const tip = options.tooltip;
    function showTip(text, clientX, clientY) {
      if (!tip) return;
      tip.textContent = text;
      tip.hidden = false;
      const box = tip.parentElement.getBoundingClientRect();
      const x = Math.min(box.width - tip.offsetWidth - 8, Math.max(8, clientX - box.left + 14));
      const y = Math.max(8, clientY - box.top - tip.offsetHeight - 12);
      tip.style.transform = `translate(${x}px, ${y}px)`;
    }
    function hideTip() { if (tip) tip.hidden = true; }

    // ---------------------------------------------------------------- direct labels (only where they fit)
    let labelFrame = 0;
    function scheduleLabels() {
      if (labelFrame) return;
      if (typeof requestAnimationFrame !== "function") { renderLabels(); return; }
      labelFrame = requestAnimationFrame(() => { labelFrame = 0; renderLabels(); });
    }

    function renderLabels() {
      if (!grid || !layout || map.getMode() !== "edit") return;
      const t0 = performance.now();
      const upp = map.unitsPerPixel();
      const cellWidthPx = grid.size * Math.sqrt(3) / upp;
      const total = cropIds.reduce((s, c) => s + areas[c], 0);
      const shown = [];
      for (const a of Mosaic.labelAnchors(grid, layout, cropIds)) {
        let node = labelNodes[a.crop];
        if (!node) node = labelNodes[a.crop] = svgEl("text", { class: "mz-label", "text-anchor": "middle", "data-crop": a.crop }, labelLayer);
        const share = total > 0 ? 100 * areas[a.crop] / total : 0;
        node.textContent = `${nameOf[a.crop].replace(/ crops$/, "")} ${fmt.pct(share)}`;
        node.setAttribute("font-size", (LABEL_PX * upp).toFixed(4));
        node.setAttribute("x", a.x.toFixed(2));
        node.setAttribute("y", (a.y + LABEL_PX * 0.36 * upp).toFixed(2));
        node.style.display = "";
        const widthPx = node.getComputedTextLength() / upp;
        if (Mosaic.labelFits(a, widthPx, LABEL_PX * 1.25, cellWidthPx)) shown.push(a.crop);
      }
      for (const c of cropIds) if (labelNodes[c]) labelNodes[c].style.display = shown.includes(c) ? "" : "none";
      labelLayer.dataset.shown = shown.join(",");
      perf.labelMs.push(performance.now() - t0);
    }
    map.onViewChange(scheduleLabels);

    // ---------------------------------------------------------------- panel (tools, crop picker, legend)
    const panel = options.panel;
    const toolGroup = h("div", { class: "mz-seg", role: "radiogroup", "aria-label": "Tool" });
    const TOOL_TITLES = { hand: "Hand: drag to pan the map", brush: "Brush: paint the chosen crop", eraser: "Eraser: remove sown area" };
    for (const t of TOOLS) {
      const id = `mz-tool-${t}`;
      const input = h("input", { type: "radio", name: "mz-tool", id, value: t, class: "visually-hidden-input" });
      input.checked = t === tool;
      input.addEventListener("change", () => setTool(t));
      toolGroup.append(input, h("label", { for: id, title: TOOL_TITLES[t] },
        [h("span", { class: "icon", html: ICONS[t] }), t[0].toUpperCase() + t.slice(1)]));
    }
    const sizeGroup = h("div", { class: "mz-seg mz-sizes", role: "radiogroup", "aria-label": "Brush size" });
    for (const r of BRUSH_SIZES) {
      const n = 3 * r * (r + 1) + 1;
      const id = `mz-size-${r}`;
      const input = h("input", { type: "radio", name: "mz-size", id, value: String(r), class: "visually-hidden-input" });
      input.checked = r === brush;
      input.addEventListener("change", () => { brush = r; });
      sizeGroup.append(input, h("label", { for: id, title: `${n} cell${n > 1 ? "s" : ""} = ${fmt.ha(n * HA)} ha` },
        [h("span", { class: "mz-dot", style: `--d:${5 + r * 3}px`, "aria-hidden": "true" }), h("span", { text: `${fmt.ha(n * HA)} ha` })]));
    }

    const cropList = h("ul", { class: "mz-crops", role: "radiogroup", "aria-label": "Crop to paint" });
    const cropRows = {};
    for (const c of crops) {
      const id = `mz-crop-${c.id}`;
      const input = h("input", { type: "radio", name: "mz-crop", id, value: c.id, class: "visually-hidden-input" });
      input.checked = c.id === crop;
      input.addEventListener("change", () => { crop = c.id; if (tool === "hand") setTool("brush"); renderPanel(); });
      const share = h("span", { class: "mz-share" });
      const cells = h("span", { class: "mz-cells" });
      const label = h("label", { for: id, class: "mz-pick" }, [
        h("span", { class: "mz-swatch", "data-crop": c.id, style: `--c: var(--crop-${c.id})`, "aria-hidden": "true" }),
        h("span", { class: "mz-crop-name", text: c.name }), share, cells]);
      const li = h("li", {}, [input, label]);
      li.addEventListener("pointerenter", () => setFocusCrop(c.id));
      li.addEventListener("pointerleave", () => setFocusCrop(null));
      input.addEventListener("focus", () => setFocusCrop(c.id));
      input.addEventListener("blur", () => setFocusCrop(null));
      cropRows[c.id] = { share, cells, li };
      cropList.append(li);
    }

    const undoBtn = h("button", { type: "button", class: "tool-btn", title: "Undo the last change (Ctrl+Z)" }, [h("span", { class: "icon", html: ICONS.undo }), "Undo"]);
    undoBtn.addEventListener("click", () => editor.undo());
    const autoBtn = h("button", { type: "button", class: "tool-btn", title: "Re-arrange the cells into compact patches; areas do not change" },
      [h("span", { class: "icon", html: ICONS.auto }), "Auto layout"]);
    autoBtn.addEventListener("click", () => autoLayout());
    const patBtn = h("button", { type: "button", class: "tool-btn", "aria-pressed": "false", title: "Hatch wheat, vegetables, oilseeds and other grains" },
      [h("span", { class: "icon", html: ICONS.pattern }), "Patterns"]);
    patBtn.addEventListener("click", () => setPatterns(!patterns));

    const totals = h("p", { class: "mz-totals" });
    const note = h("p", { class: "mz-note", hidden: "" });

    panel.append(
      h("p", { class: "kicker", text: "Crop Editor" }),
      h("h2", { class: "info-title", text: "Paint the crop mix" }),
      h("p", { class: "mz-schematic" }, [h("strong", { text: "Schematic — not actual field locations. " }),
        "1 cell = 100 ha of sown area. Where a cell sits means nothing; only the number of cells per crop changes the scenario."]),
      h("div", { class: "mz-row" }, [h("span", { class: "mz-label-sm", text: "Tool" }), toolGroup]),
      h("div", { class: "mz-row" }, [h("span", { class: "mz-label-sm", text: "Brush size" }), sizeGroup]),
      h("h3", { class: "list-title", text: "Crop to paint" }),
      cropList,
      totals,
      h("div", { class: "mz-actions" }, [undoBtn, autoBtn, patBtn]),
      note,
      h("p", { class: "mz-help", text: "The brush moves 100 ha per cell from the crop underneath to the chosen crop, so the total stays the same. " +
        "The eraser removes sown area: the total then differs from 2025 and the scenario breaks that constraint. " +
        "Keyboard: change areas in the Crop areas table below; the mosaic follows." }));

    function renderPanel() {
      const total = cropIds.reduce((s, c) => s + areas[c], 0);
      const tally = layout ? Mosaic.tallyLayout(layout, cropIds) : null;
      for (const c of cropIds) {
        const r = cropRows[c];
        r.share.textContent = total > 0 ? fmt.pct(100 * areas[c] / total) : "—";
        r.cells.textContent = tally ? `${tally[c]} cells` : "";
        r.li.classList.toggle("is-current", c === crop);
      }
      const unsown = layout ? layout.filter((x) => x === null).length : 0;
      totals.textContent = `Total sown: ${fmt.ha(total)} ha` +
        (layout ? ` · ${layout.length - unsown} cells` + (unsown ? ` · ${unsown} unsown` : "") : "");
      note.textContent = overflow > 0
        ? `+${overflow} cell${overflow > 1 ? "s" : ""} not shown: the total is larger than the map holds (${capacity} cells = 2025 sown area).` : "";
      note.hidden = overflow === 0;
      undoBtn.disabled = editor.getState().history.length === 0;
    }

    function setTool(t) {
      if (!TOOLS.includes(t)) throw new Error("Unknown tool " + t);
      tool = t;
      document.getElementById(`mz-tool-${t}`).checked = true;
      map.svg.parentElement.dataset.tool = t;
      brushPath.setAttribute("d", "");
    }

    function setPatterns(on) {
      patterns = !!on;
      patBtn.setAttribute("aria-pressed", String(patterns));
      panel.classList.toggle("has-patterns", patterns);
      if (grid) applyFills();
    }

    function setFocusCrop(c) {
      focusCrop = c;
      layer.classList.toggle("has-focus", c !== null);
      for (const id of cropIds) cropPaths[id].classList.toggle("is-focus", id === c);
    }

    function autoLayout() {
      if (!grid) return;
      const cc = Mosaic.cellCounts(areas, cropIds, HA, capacity);
      const next = Mosaic.initialLayout(grid, cc.counts, cropIds);
      layoutByAreas.set(areas, next);
      setLayout(next, true);
    }

    // ---------------------------------------------------------------- mode
    function setMode(mode) {
      handler.cancel();
      map.setMode(mode);
      const edit = mode === "edit";
      if (options.badge) options.badge.hidden = !edit;
      panel.hidden = !edit;
      hideTip();
      brushPath.setAttribute("d", "");
      if (edit) {
        ensureGrid();
        setTool(tool);
        update(editor.getState().areas);
        scheduleLabels();
      }
    }

    setPatterns(patterns);
    renderPanel();

    return {
      update, setMode, setTool, setPatterns, autoLayout,
      setBrush: (r) => { if (!BRUSH_SIZES.includes(r)) throw new Error("Brush radius 0–3"); brush = r; document.getElementById(`mz-size-${r}`).checked = true; },
      setCrop: (c) => { if (!cropIds.includes(c)) throw new Error("Unknown crop " + c); crop = c; document.getElementById(`mz-crop-${c}`).checked = true; renderPanel(); },
      getLayout: () => layout, getGrid: () => grid, getCapacity: () => capacity, getOverflow: () => overflow,
      getTool: () => tool, getBrush: () => brush, getPatterns: () => patterns, getFocusCrop: () => focusCrop, perf,
    };
  }

  return Object.freeze({ createMosaicView, hexPath, CELL_SCALE });
});
