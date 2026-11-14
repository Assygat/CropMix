/* CropMix Twin — vector map of Kyzylorda Region for the Crop Allocation Simulator (module 10, stage 4).
 *
 * Geographic context only: real 2017 boundaries (geoBoundaries ADM2, OpenStreetMap, ODbL) and the Syr Darya
 * centreline (Natural Earth, public domain) from web/data/geo.js. No tiles, no network, no crop or water data.
 *
 * The region outline is built from the OUTER edges of the district layer (edges used by exactly one district),
 * so the outline and the districts always match. The separately simplified ADM1 polygon is not drawn: it differs
 * from the ADM2 layer by ~2 % of area and would leave slivers along the border.
 *
 * Pure geometry helpers are exported for Node tests (tests/js/sim_map.test.js); the DOM part runs in browsers.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CropMixMap = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const UNITS_PER_DEGREE = 100;          // SVG units per degree of latitude
  const KM_PER_DEGREE_LAT = 111.32;      // mean length of one degree of latitude, km
  const MIN_ZOOM = 1;
  const MAX_ZOOM = 16;
  const VIEW_PADDING = 0.04;             // share of the extent added around the region
  const DRAG_THRESHOLD_PX = 4;           // movement below this is a click, not a pan
  const WHEEL_ZOOM_SPEED = 0.0015;
  const BUTTON_ZOOM_STEP = 1.6;
  const KEY_PAN_SHARE = 0.12;            // arrow keys pan by this share of the view
  const ANIMATION_MS = 220;
  const SCALE_BAR_TARGET_PX = 110;
  const LABEL_FONT_PX = 13;
  const SVG_NS = "http://www.w3.org/2000/svg";

  // ------------------------------------------------------------------------------------------ pure helpers

  /** Equirectangular projection centred on the bbox: x scaled by cos(φ0) so distances are true near φ0. */
  function createProjection(bbox) {
    const [lon0, lat0, lon1, lat1] = bbox;
    const phi0 = (lat0 + lat1) / 2;
    const kx = Math.cos(phi0 * Math.PI / 180);
    const project = ([lon, lat]) => [(lon - lon0) * kx * UNITS_PER_DEGREE, (lat1 - lat) * UNITS_PER_DEGREE];
    return { project, width: (lon1 - lon0) * kx * UNITS_PER_DEGREE, height: (lat1 - lat0) * UNITS_PER_DEGREE,
             centreLat: phi0, kmPerUnit: KM_PER_DEGREE_LAT / UNITS_PER_DEGREE };
  }

  /** All rings of all polygons of a Polygon / MultiPolygon feature. */
  function featureRings(feature) {
    const g = feature.geometry;
    const polys = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
    return polys.reduce((acc, poly) => acc.concat(poly), []);
  }

  const pointId = (p) => p[0] + "," + p[1];

  function edgeKey(a, b) {
    const ka = pointId(a);
    const kb = pointId(b);
    return ka < kb ? ka + "|" + kb : kb + "|" + ka;
  }

  /**
   * Outer boundary of polygons that share edges: edges used exactly once, chained into closed rings.
   * Throws if those edges do not form simple closed rings (inconsistent topology).
   */
  function outerBoundary(features) {
    const edges = new Map();
    for (const f of features) {
      for (const ring of featureRings(f)) {
        for (let i = 0; i < ring.length - 1; i++) {
          const k = edgeKey(ring[i], ring[i + 1]);
          const e = edges.get(k);
          if (e) e.n += 1;
          else edges.set(k, { n: 1, a: ring[i], b: ring[i + 1] });
        }
      }
    }
    const adjacency = new Map();
    const link = (p, q) => {
      if (!adjacency.has(pointId(p))) adjacency.set(pointId(p), { p, next: [] });
      adjacency.get(pointId(p)).next.push(q);
    };
    for (const e of edges.values()) {
      if (e.n !== 1) continue;
      link(e.a, e.b);
      link(e.b, e.a);
    }
    for (const node of adjacency.values()) {
      if (node.next.length !== 2) throw new Error("Outer boundary is not a set of simple closed rings");
    }
    const used = new Set();
    const rings = [];
    for (const [startId, start] of adjacency) {
      if (used.has(startId)) continue;
      used.add(startId);
      const ring = [start.p];
      let prevId = null;
      let cur = start;
      for (;;) {
        const curId = pointId(cur.p);
        const next = cur.next.find((q) => pointId(q) !== prevId && (!used.has(pointId(q)) || (pointId(q) === startId && ring.length > 2)));
        if (!next) throw new Error("Outer boundary ring does not close");
        if (pointId(next) === startId) { ring.push(start.p); break; }
        ring.push(next);
        used.add(pointId(next));
        prevId = curId;
        cur = adjacency.get(pointId(next));
      }
      rings.push(ring);
    }
    return rings;
  }

  function pointInRing(x, y, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i];
      const [xj, yj] = ring[j];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }

  function distanceToSegment(px, py, a, b) {
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len2 = dx * dx + dy * dy;
    const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / len2));
    return Math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy));
  }

  /**
   * Label anchor inside a projected ring: the grid point farthest from the edge (approximate pole of
   * inaccessibility). Always inside the ring, unlike the centroid of a concave shape.
   */
  function labelPoint(ring, gridSize) {
    const n = gridSize || 40;
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const [x, y] of ring) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    let best = null;
    for (let i = 0; i <= n; i++) {
      for (let j = 0; j <= n; j++) {
        const x = x0 + (x1 - x0) * i / n;
        const y = y0 + (y1 - y0) * j / n;
        if (!pointInRing(x, y, ring)) continue;
        let d = Infinity;
        for (let k = 0; k < ring.length - 1; k++) d = Math.min(d, distanceToSegment(x, y, ring[k], ring[k + 1]));
        if (!best || d > best.d) best = { x, y, d };
      }
    }
    if (!best) throw new Error("No interior point found for label");
    return [best.x, best.y];
  }

  function pathData(coords, project, close) {
    const d = coords.map((p, i) => {
      const [x, y] = project(p);
      return (i === 0 ? "M" : "L") + x.toFixed(2) + " " + y.toFixed(2);
    }).join("");
    return close ? d + "Z" : d;
  }

  /** Base view: projected extent plus padding. */
  function baseView(width, height) {
    const pad = Math.max(width, height) * VIEW_PADDING;
    return { x: -pad, y: -pad, w: width + 2 * pad, h: height + 2 * pad };
  }

  /** Keeps zoom in [MIN_ZOOM, MAX_ZOOM] and the view centre inside the base extent. Returns a new view. */
  function clampView(view, base) {
    const w = Math.min(base.w / MIN_ZOOM, Math.max(base.w / MAX_ZOOM, view.w));
    const h = w * (base.h / base.w);
    const cx = Math.min(base.x + base.w, Math.max(base.x, view.x + view.w / 2));
    const cy = Math.min(base.y + base.h, Math.max(base.y, view.y + view.h / 2));
    return { x: cx - w / 2, y: cy - h / 2, w, h };
  }

  /** Zoom by factor (> 1 zooms in) keeping the SVG point (px, py) fixed on screen. */
  function zoomAt(view, base, factor, px, py) {
    const w = Math.min(base.w / MIN_ZOOM, Math.max(base.w / MAX_ZOOM, view.w / factor));
    const s = w / view.w;
    return clampView({ x: px - (px - view.x) * s, y: py - (py - view.y) * s, w, h: view.h * s }, base);
  }

  function panBy(view, base, dx, dy) {
    return clampView({ x: view.x + dx, y: view.y + dy, w: view.w, h: view.h }, base);
  }

  function zoomLevel(view, base) {
    return base.w / view.w;
  }

  /** Largest "nice" distance (1, 2, 5 × 10^n km) not longer than maxKm. */
  function niceDistance(maxKm) {
    const p = Math.pow(10, Math.floor(Math.log10(maxKm)));
    for (const m of [5, 2, 1]) if (m * p <= maxKm) return m * p;
    return p;
  }

  // ------------------------------------------------------------------------------------------ DOM map

  function svgEl(name, attrs, parent) {
    const node = document.createElementNS(SVG_NS, name);
    for (const k of Object.keys(attrs || {})) node.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(node);
    return node;
  }

  const prefersReducedMotion = () =>
    typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

  /**
   * Renders the map into `container`.
   * options: { geo, tooltip: HTMLElement, scaleBar: HTMLElement, scaleLabel: HTMLElement,
   *            onSelect(feature|null), onHover(feature|null) }
   * Returns { select(id|null), zoomIn(), zoomOut(), reset(), getView(), getZoom(), destroy() }.
   */
  function createMap(container, options) {
    const geo = options.geo;
    const districts = geo.districts.features;
    const proj = createProjection(geo.bbox);
    const base = baseView(proj.width, proj.height);
    let view = Object.assign({}, base);
    let selectedId = null;
    let hoverId = null;

    const svg = svgEl("svg", { class: "map-svg", viewBox: `${base.x} ${base.y} ${base.w} ${base.h}`,
                               preserveAspectRatio: "xMidYMid meet", "aria-labelledby": "map-svg-title map-svg-desc" });
    svgEl("title", { id: "map-svg-title" }, svg).textContent = "Map of Kyzylorda Region";
    svgEl("desc", { id: "map-svg-desc" }, svg).textContent =
      "Seven districts and Kyzylorda City with 2017 administrative boundaries, and the Syr Darya river. " +
      "Geographic context only; there is no crop or water data by district.";

    const outlineD = outerBoundary(districts).map((r) => pathData(r, proj.project, true)).join("");
    const clip = svgEl("clipPath", { id: "region-clip" }, svgEl("defs", {}, svg));
    svgEl("path", { d: outlineD }, clip);

    // 1° graticule (real coordinates) for orientation; drawn under everything
    const [lonA, latA, lonB, latB] = geo.bbox;
    const gridLines = [];
    for (let lon = Math.floor(lonA) - 1; lon <= Math.ceil(lonB) + 1; lon++) gridLines.push([[lon, latA - 1], [lon, latB + 1]]);
    for (let lat = Math.floor(latA) - 1; lat <= Math.ceil(latB) + 1; lat++) gridLines.push([[lonA - 1.5, lat], [lonB + 1.5, lat]]);
    svgEl("path", { class: "graticule", d: gridLines.map((l) => pathData(l, proj.project, false)).join(""),
                    "aria-hidden": "true" }, svg);

    const riverD = geo.river.geometry.coordinates.map((l) => pathData(l, proj.project, false)).join("");
    const gDistricts = svgEl("g", { class: "districts" }, svg);
    svgEl("path", { class: "river river-outside", d: riverD, "aria-hidden": "true" }, svg);
    const gRiverIn = svgEl("g", { "clip-path": "url(#region-clip)", "aria-hidden": "true" }, svg);
    svgEl("path", { class: "river river-casing", d: riverD }, gRiverIn);
    svgEl("path", { class: "river river-inside", d: riverD }, gRiverIn);
    svgEl("path", { class: "region-outline", d: outlineD, "aria-hidden": "true" }, svg);
    // Hover / selection borders are separate overlay paths: the district paths never move in the DOM,
    // because re-inserting a focused element would drop keyboard focus.
    const gHighlight = svgEl("g", { class: "highlights", "aria-hidden": "true" }, svg);
    const hoverRing = svgEl("path", { class: "highlight highlight-hover", d: "" }, gHighlight);
    const selectRing = svgEl("path", { class: "highlight highlight-selected", d: "" }, gHighlight);
    const gLabels = svgEl("g", { class: "labels", "aria-hidden": "true" }, svg);

    const paths = new Map();
    const labels = new Map();
    for (const f of districts) {
      const p = f.properties;
      const d = featureRings(f).map((r) => pathData(r, proj.project, true)).join("");
      const path = svgEl("path", { class: "district" + (p.kind === "city" ? " is-city" : ""), d, tabindex: "0",
                                   role: "button", "aria-pressed": "false", "data-id": p.id,
                                   "aria-label": `${p.name}: show details` }, gDistricts);
      paths.set(p.id, { path, feature: f });
      const [lx, ly] = labelPoint(featureRings(f)[0].map(proj.project));
      const g = svgEl("g", { class: "label" + (p.kind === "city" ? " is-city" : ""), "data-id": p.id }, gLabels);
      const dot = p.kind === "city" ? svgEl("circle", { class: "city-dot", cx: lx, cy: ly, r: 1 }, g) : null;
      const text = svgEl("text", { x: lx, y: ly }, g);
      text.textContent = p.kind === "city" ? p.name : p.name.replace(/ District$/, "");
      labels.set(p.id, { g, text, dot, x: lx, y: ly });
    }
    container.appendChild(svg);

    // ---------------------------------------------------------------- view

    function unitsPerPixel() {
      const rect = svg.getBoundingClientRect();
      if (!rect.width || !rect.height) return 1;
      return Math.max(view.w / rect.width, view.h / rect.height);   // "meet" uses the larger ratio
    }

    function updateScaleBar(upp) {
      if (!options.scaleBar || !options.scaleLabel) return;
      const km = niceDistance(SCALE_BAR_TARGET_PX * upp * proj.kmPerUnit);
      options.scaleBar.style.width = (km / proj.kmPerUnit / upp).toFixed(1) + "px";
      options.scaleLabel.textContent = `${km} km`;
    }

    function applyView(next) {
      view = next;
      svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
      const upp = unitsPerPixel();
      for (const { text, dot, x, y } of labels.values()) {
        text.setAttribute("font-size", (LABEL_FONT_PX * upp).toFixed(3));   // constant on-screen size
        if (dot) {
          dot.setAttribute("r", (3.5 * upp).toFixed(3));
          text.setAttribute("x", (x + 7 * upp).toFixed(3));
          text.setAttribute("y", (y + 4.5 * upp).toFixed(3));
        }
      }
      updateScaleBar(upp);
      container.dataset.zoom = zoomLevel(view, base).toFixed(2);
    }

    let animation = null;
    function animateTo(target) {
      if (animation) cancelAnimationFrame(animation);
      animation = null;
      if (prefersReducedMotion()) { applyView(target); return; }
      const from = Object.assign({}, view);
      const t0 = performance.now();
      const step = (now) => {
        const t = Math.min(1, (now - t0) / ANIMATION_MS);
        const e = 1 - Math.pow(1 - t, 3);
        applyView({ x: from.x + (target.x - from.x) * e, y: from.y + (target.y - from.y) * e,
                    w: from.w + (target.w - from.w) * e, h: from.h + (target.h - from.h) * e });
        animation = t < 1 ? requestAnimationFrame(step) : null;
      };
      animation = requestAnimationFrame(step);
    }

    const centre = () => [view.x + view.w / 2, view.y + view.h / 2];

    function toSvgPoint(clientX, clientY) {
      const rect = svg.getBoundingClientRect();
      const upp = unitsPerPixel();
      const offX = (rect.width * upp - view.w) / 2;
      const offY = (rect.height * upp - view.h) / 2;
      return [view.x - offX + (clientX - rect.left) * upp, view.y - offY + (clientY - rect.top) * upp];
    }

    // ---------------------------------------------------------------- hover & selection

    function setHover(id) {
      if (hoverId === id) return;
      if (hoverId) {
        paths.get(hoverId).path.classList.remove("is-hover");
        labels.get(hoverId).g.classList.remove("is-hover");
      }
      hoverId = id;
      if (id) {
        paths.get(id).path.classList.add("is-hover");
        labels.get(id).g.classList.add("is-hover");
      }
      hoverRing.setAttribute("d", id && id !== selectedId ? paths.get(id).path.getAttribute("d") : "");
      if (options.onHover) options.onHover(id ? paths.get(id).feature : null);
    }

    function select(id) {
      if (id !== null && !paths.has(id)) throw new Error("Unknown territory " + id);
      if (selectedId) {
        paths.get(selectedId).path.classList.remove("is-selected");
        paths.get(selectedId).path.setAttribute("aria-pressed", "false");
        labels.get(selectedId).g.classList.remove("is-selected");
      }
      selectedId = id;
      if (id) {
        paths.get(id).path.classList.add("is-selected");
        paths.get(id).path.setAttribute("aria-pressed", "true");
        labels.get(id).g.classList.add("is-selected");
      }
      selectRing.setAttribute("d", id ? paths.get(id).path.getAttribute("d") : "");
      hoverRing.setAttribute("d", hoverId && hoverId !== id ? paths.get(hoverId).path.getAttribute("d") : "");
      container.dataset.selected = id || "";
      if (options.onSelect) options.onSelect(id ? paths.get(id).feature : null);
    }

    function showTooltip(id, clientX, clientY) {
      const tip = options.tooltip;
      if (!tip) return;
      if (!id) { tip.hidden = true; return; }
      tip.textContent = paths.get(id).feature.properties.name;
      tip.hidden = false;
      const box = container.getBoundingClientRect();
      const x = Math.min(box.width - tip.offsetWidth - 8, Math.max(8, clientX - box.left + 14));
      const y = Math.max(8, clientY - box.top - tip.offsetHeight - 12);
      tip.style.transform = `translate(${x}px, ${y}px)`;
    }

    // ---------------------------------------------------------------- pointer: hover, click, pan, pinch

    const pointers = new Map();
    let drag = null;
    let pinch = null;

    function districtIdAt(target) {
      const t = target && target.closest ? target.closest("path.district") : null;
      return t ? t.getAttribute("data-id") : null;
    }

    function onPointerDown(e) {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size === 1) {
        drag = { startX: e.clientX, startY: e.clientY, lastX: e.clientX, lastY: e.clientY, moved: false,
                 id: districtIdAt(e.target), pointerId: e.pointerId };
        if (e.pointerType !== "touch") { setHover(drag.id); showTooltip(drag.id, e.clientX, e.clientY); }
      } else if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        pinch = { dist: Math.hypot(a.x - b.x, a.y - b.y) };
        drag = null;
      }
    }

    function onPointerMove(e) {
      if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pinch && pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        const dist = Math.hypot(a.x - b.x, a.y - b.y);
        if (pinch.dist > 0 && dist > 0) {
          const [px, py] = toSvgPoint((a.x + b.x) / 2, (a.y + b.y) / 2);
          applyView(zoomAt(view, base, dist / pinch.dist, px, py));
        }
        pinch.dist = dist;
        return;
      }
      if (drag && pointers.has(e.pointerId)) {
        if (!drag.moved && Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) > DRAG_THRESHOLD_PX) {
          drag.moved = true;
          svg.setPointerCapture(e.pointerId);       // capture only once a pan starts, so clicks reach paths
          container.classList.add("is-panning");
          setHover(null);
          showTooltip(null);
        }
        if (drag.moved) {
          const upp = unitsPerPixel();
          applyView(panBy(view, base, -(e.clientX - drag.lastX) * upp, -(e.clientY - drag.lastY) * upp));
          drag.lastX = e.clientX;
          drag.lastY = e.clientY;
          return;
        }
      }
      if (e.pointerType !== "touch") {
        const id = districtIdAt(e.target);
        setHover(id);
        showTooltip(id, e.clientX, e.clientY);
      }
    }

    function onPointerUp(e) {
      const wasClick = drag && !drag.moved && drag.pointerId === e.pointerId && pointers.size === 1;
      pointers.delete(e.pointerId);
      if (svg.hasPointerCapture(e.pointerId)) svg.releasePointerCapture(e.pointerId);
      if (pointers.size < 2) pinch = null;
      if (wasClick && e.type === "pointerup") {
        const id = drag.id;
        select(id && id !== selectedId ? id : null);   // clicking the selected territory or empty map clears it
      }
      if (pointers.size === 0) {
        drag = null;
        container.classList.remove("is-panning");
      }
    }

    function onPointerLeave(e) {
      if (pointers.size === 0 && e.pointerType !== "touch") { setHover(null); showTooltip(null); }
    }

    function onWheel(e) {
      e.preventDefault();
      const [px, py] = toSvgPoint(e.clientX, e.clientY);
      applyView(zoomAt(view, base, Math.exp(-e.deltaY * WHEEL_ZOOM_SPEED), px, py));
    }

    // ---------------------------------------------------------------- keyboard

    function onKeyDown(e) {
      const id = e.target.getAttribute && e.target.getAttribute("data-id");
      if (id && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        select(id === selectedId ? null : id);
        return;
      }
      const [cx, cy] = centre();
      if (e.key === "+" || e.key === "=") { e.preventDefault(); animateTo(zoomAt(view, base, BUTTON_ZOOM_STEP, cx, cy)); }
      else if (e.key === "-" || e.key === "_") { e.preventDefault(); animateTo(zoomAt(view, base, 1 / BUTTON_ZOOM_STEP, cx, cy)); }
      else if (e.key === "0") { e.preventDefault(); animateTo(base); }
      else if (e.key === "Escape" && selectedId) { e.preventDefault(); select(null); }
      else if (e.key.startsWith("Arrow") && e.target === container) {
        e.preventDefault();
        const dx = e.key === "ArrowLeft" ? -1 : e.key === "ArrowRight" ? 1 : 0;
        const dy = e.key === "ArrowUp" ? -1 : e.key === "ArrowDown" ? 1 : 0;
        animateTo(panBy(view, base, dx * view.w * KEY_PAN_SHARE, dy * view.h * KEY_PAN_SHARE));
      }
    }

    svg.addEventListener("pointerdown", onPointerDown);
    svg.addEventListener("pointermove", onPointerMove);
    svg.addEventListener("pointerup", onPointerUp);
    svg.addEventListener("pointercancel", onPointerUp);
    svg.addEventListener("pointerleave", onPointerLeave);
    svg.addEventListener("wheel", onWheel, { passive: false });
    // Focus listeners live on the HTML container, not on the SVG <g>: Chromium makes an SVG element with
    // focus listeners keyboard-focusable, which added an invisible extra Tab stop (stage 7 audit, I1).
    container.addEventListener("focusin", (e) => {
      const id = e.target.getAttribute && e.target.getAttribute("data-id");
      if (id && paths.has(id)) setHover(id);
    });
    container.addEventListener("focusout", (e) => {
      const id = e.target.getAttribute && e.target.getAttribute("data-id");
      if (id && paths.has(id)) setHover(null);
    });
    container.addEventListener("keydown", onKeyDown);

    const resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(() => applyView(view)) : null;
    if (resizeObserver) resizeObserver.observe(svg);
    applyView(view);

    return {
      select,
      zoomIn: () => { const [cx, cy] = centre(); animateTo(zoomAt(view, base, BUTTON_ZOOM_STEP, cx, cy)); },
      zoomOut: () => { const [cx, cy] = centre(); animateTo(zoomAt(view, base, 1 / BUTTON_ZOOM_STEP, cx, cy)); },
      reset: () => animateTo(base),
      getView: () => Object.assign({}, view),
      getZoom: () => zoomLevel(view, base),
      destroy: () => { if (resizeObserver) resizeObserver.disconnect(); svg.remove(); },
    };
  }

  return Object.freeze({
    createProjection, featureRings, outerBoundary, pointInRing, labelPoint, pathData,
    baseView, clampView, zoomAt, panBy, zoomLevel, niceDistance, createMap,
    MIN_ZOOM, MAX_ZOOM, KM_PER_DEGREE_LAT, UNITS_PER_DEGREE,
  });
});
