/* CropMix Twin — crop structure chart for the simulator (module 10, stage 5).
 * Shows how the whole-region crop mix splits (shares of total sown area), Baseline 2025 vs My scenario:
 *  - two 100 % stacked bars on one shared axis (part-to-whole, several wholes);
 *  - a per-crop comparison: scenario share bar with the baseline share marked;
 *  - a table view with the same numbers (accessibility; values are never colour-only).
 * Shares are display arithmetic (area / total); no water is computed here.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CropMixStructure = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const MIN_LABEL_SHARE = 7;     // print the % inside a segment only when it is at least this wide (%)
  const AXIS_TICKS = [0, 25, 50, 75, 100];
  // Display order of stacked-bar segments (palette A′): no two hard-to-separate colours touch. Legend, table and
  // per-crop rows keep the data order.
  const STACK_ORDER = ["rice", "fodder", "vegetables_open", "melons", "potato", "grain_other", "wheat", "oilseeds"];
  const stackOrder = (crops) => [...crops].sort((a, b) => rank(a.id) - rank(b.id));
  const rank = (id) => { const i = STACK_ORDER.indexOf(id); return i < 0 ? STACK_ORDER.length : i; };

  function h(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "text") node.textContent = v;
      else if (k === "style") node.style.cssText = v;
      else node.setAttribute(k, v);
    }
    for (const c of [].concat(children || [])) if (c !== null && c !== undefined) node.append(c);
    return node;
  }

  /** Shares (%) of each crop in the total; null shares when the total is zero (no division by zero). */
  function shares(crops, areas) {
    const total = crops.reduce((s, c) => s + areas[c.id], 0);
    const out = {};
    for (const c of crops) out[c.id] = total > 0 ? 100 * areas[c.id] / total : null;
    return { total, shares: out };
  }

  function createStructureChart(container, options) {
    const crops = options.crops;
    const fmt = options.fmt;
    const baseLabel = options.baselineLabel || "Baseline 2025";

    const tableBtn = h("button", { type: "button", class: "ghost-btn", "aria-pressed": "false", "aria-controls": "structure-table" }, "Table view");
    const head = h("div", { class: "structure-head" }, [
      h("div", {}, [h("h3", { class: "section-title", id: "structure-title", text: "Crop structure" }),
                    h("p", { class: "section-sub", text: "Share of total sown area, whole region" })]),
      tableBtn,
    ]);

    const legend = h("ul", { class: "structure-legend", "aria-label": "Crop colours" },
      crops.map((c) => h("li", {}, [h("span", { class: "swatch", style: `background: var(--crop-${c.id})`, "aria-hidden": "true" }), c.name])));

    const bars = {};
    const barRows = ["baseline", "my"].map((key) => {
      const bar = h("div", { class: "stack", role: "img" });
      bars[key] = bar;
      return h("div", { class: "stack-row" }, [h("span", { class: "stack-label", text: key === "baseline" ? baseLabel : "My scenario" }), bar]);
    });
    const axis = h("div", { class: "stack-axis", "aria-hidden": "true" },
      AXIS_TICKS.map((t) => h("span", { style: `left: ${t}%`, text: `${t}%` })));
    const stacks = h("div", { class: "stacks" }, [...barRows, h("div", { class: "stack-row axis-row" }, [h("span"), axis])]);

    const compare = h("ul", { class: "share-compare", "aria-label": "Share by crop: My scenario compared with baseline" });
    const compareRows = {};
    for (const c of crops) {
      const fill = h("span", { class: "share-fill", style: `background: var(--crop-${c.id})` });
      const mark = h("span", { class: "share-mark", title: "Baseline share" });
      const value = h("span", { class: "share-value" });
      const delta = h("span", { class: "share-delta" });
      compareRows[c.id] = { fill, mark, value, delta };
      compare.append(h("li", { class: "share-row" }, [
        h("span", { class: "share-name" }, [h("span", { class: "swatch", style: `background: var(--crop-${c.id})`, "aria-hidden": "true" }), c.name]),
        h("span", { class: "share-track", "aria-hidden": "true" }, [fill, mark]),
        value, delta,
      ]));
    }

    const tbody = h("tbody");
    const table = h("table", { class: "data-table", id: "structure-table", hidden: "" }, [
      h("caption", { text: "Crop structure: baseline and My scenario (areas in ha, shares of total)" }),
      h("thead", {}, h("tr", {}, ["Crop", "Baseline, ha", "My scenario, ha", "Baseline share", "Scenario share", "Change"]
        .map((t, i) => h("th", { scope: "col", class: i ? "num" : "", text: t })))),
      tbody,
    ]);
    tableBtn.addEventListener("click", () => {
      const show = table.hidden;
      table.hidden = !show;
      tableBtn.setAttribute("aria-pressed", String(show));
      tableBtn.textContent = show ? "Hide table" : "Table view";
    });

    const tooltip = h("div", { class: "chart-tooltip", role: "presentation", hidden: "" });
    const chart = h("div", { class: "structure-chart" }, [stacks, tooltip]);
    container.append(head, legend, chart,
      h("h4", { class: "mini-title", text: "Share by crop" }),
      h("p", { class: "mini-note", text: "Bar: My scenario · tick: baseline" }),
      compare, table);

    function moveTip(e) {
      const box = chart.getBoundingClientRect();
      const x = Math.min(box.width - tooltip.offsetWidth - 4, Math.max(4, e.clientX - box.left + 12));
      const y = Math.max(0, e.clientY - box.top - tooltip.offsetHeight - 10);
      tooltip.style.transform = `translate(${x}px, ${y}px)`;
    }

    function renderStack(bar, areas, sh, label) {
      bar.replaceChildren();
      const desc = [];
      for (const c of stackOrder(crops)) {
        const s = sh.shares[c.id];
        if (s === null) continue;
        desc.push(`${c.name} ${fmt.pct(s)}`);
        if (s <= 0) continue;
        const seg = h("span", { class: "seg", style: `flex: ${s} 0 0; background: var(--crop-${c.id})`, "data-crop": c.id },
          s >= MIN_LABEL_SHARE ? h("span", { class: "seg-label", text: fmt.pct(s) }) : null);
        seg.addEventListener("pointerenter", (e) => {
          tooltip.replaceChildren(h("strong", { text: c.name }), h("span", { text: `${label}: ${fmt.pct(s)} · ${fmt.ha(areas[c.id])} ha` }));
          tooltip.hidden = false;
          moveTip(e);
        });
        seg.addEventListener("pointermove", moveTip);
        seg.addEventListener("pointerleave", () => { tooltip.hidden = true; });
        bar.append(seg);
      }
      if (sh.total <= 0) bar.append(h("span", { class: "stack-empty", text: "No sown area" }));
      bar.setAttribute("aria-label", `${label}: ` + (sh.total > 0 ? desc.join(", ") : "no sown area"));
    }

    /** Re-draws everything for the given baseline and scenario areas (ha). */
    function render(baseAreas, myAreas) {
      const b = shares(crops, baseAreas);
      const m = shares(crops, myAreas);
      renderStack(bars.baseline, baseAreas, b, baseLabel);
      renderStack(bars.my, myAreas, m, "My scenario");
      const maxShare = Math.max(1, ...crops.map((c) => Math.max(b.shares[c.id] || 0, m.shares[c.id] || 0)));
      const rows = [];
      for (const c of crops) {
        const r = compareRows[c.id];
        const bs = b.shares[c.id];
        const ms = m.shares[c.id];
        r.fill.style.width = `${ms === null ? 0 : 100 * ms / maxShare}%`;
        r.mark.style.left = `${bs === null ? 0 : 100 * bs / maxShare}%`;
        r.value.textContent = ms === null ? "—" : fmt.pct(ms);
        const d = ms === null || bs === null ? null : ms - bs;
        r.delta.textContent = d === null ? "—" : fmt.signedPp(d);
        r.delta.dataset.dir = d === null || Math.abs(d) < 0.05 ? "0" : d > 0 ? "up" : "down";
        rows.push(h("tr", {}, [
          h("th", { scope: "row", text: c.name }),
          h("td", { class: "num", text: fmt.ha(baseAreas[c.id]) }),
          h("td", { class: "num", text: fmt.ha(myAreas[c.id]) }),
          h("td", { class: "num", text: bs === null ? "—" : fmt.pct(bs) }),
          h("td", { class: "num", text: ms === null ? "—" : fmt.pct(ms) }),
          h("td", { class: "num", text: d === null ? "—" : fmt.signedPp(d) }),
        ]));
      }
      rows.push(h("tr", { class: "total-row" }, [
        h("th", { scope: "row", text: "Total" }),
        h("td", { class: "num", text: fmt.ha(b.total) }), h("td", { class: "num", text: fmt.ha(m.total) }),
        h("td", { class: "num", text: b.total > 0 ? "100%" : "—" }), h("td", { class: "num", text: m.total > 0 ? "100%" : "—" }),
        h("td", { class: "num", text: "" }),
      ]));
      tbody.replaceChildren(...rows);
    }

    return { render };
  }

  return Object.freeze({ createStructureChart, shares, STACK_ORDER });
});
