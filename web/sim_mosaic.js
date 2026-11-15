/* CropMix Twin — schematic crop mosaic engine (Crop Editor, stage E2).
 *
 * SCHEMATIC, NOT FIELD LOCATIONS: each hexagonal cell stands for 100 ha of the region's sown area; positions inside
 * the region outline are illustrative only (the project has no geo-referenced field data).
 *
 * Pure functions, no DOM and no water maths. Areas stay the single source of truth (sim_state): the mosaic only
 * displays rounded shares of them, and a brush stroke is converted back into exact area changes (±100 ha per cell)
 * that the page applies through the existing editor state. Works in the browser (window.CropMixMosaic) and in Node.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CropMixMosaic = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const HA_PER_CELL = 100;
  const SQRT3 = Math.sqrt(3);
  const AXIAL_DIRS = Object.freeze([[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]]);
  const NOISE_AMPLITUDE = 0.35;      // how much the smooth noise bends patch borders (relative)
  const key = (q, r) => q + "," + r;

  // ------------------------------------------------------------------------------------------ geometry helpers

  function distanceToRing(x, y, ring) {
    let d = Infinity;
    for (let i = 0; i < ring.length - 1; i++) {
      const [ax, ay] = ring[i];
      const [bx, by] = ring[i + 1];
      const dx = bx - ax, dy = by - ay;
      const len2 = dx * dx + dy * dy;
      const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / len2));
      d = Math.min(d, Math.hypot(x - (ax + t * dx), y - (ay + t * dy)));
    }
    return d;
  }

  /**
   * Hex centres inside `ring`, row by row: each row crosses the outline at a few x positions (even-odd rule), and the
   * centres between pairs of crossings are inside. Same result as a per-point test, ~50× faster.
   */
  function hexCentres(ring, size, ox, oy, box) {
    const out = [];
    const rMin = Math.floor((box.y0 - oy) / (1.5 * size)) - 1;
    const rMax = Math.ceil((box.y1 - oy) / (1.5 * size)) + 1;
    for (let r = rMin; r <= rMax; r++) {
      const y = oy + 1.5 * size * r;
      const xs = [];
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [xi, yi] = ring[i];
        const [xj, yj] = ring[j];
        if ((yi > y) !== (yj > y)) xs.push((xj - xi) * (y - yi) / (yj - yi) + xi);
      }
      xs.sort((a, b) => a - b);
      for (let k = 0; k + 1 < xs.length; k += 2) {
        // even-odd rule (as sim_map.pointInRing): a point is inside when x lies in [xs[k], xs[k+1])
        const qFrom = Math.ceil((xs[k] - ox) / (SQRT3 * size) - r / 2);
        const qTo = Math.ceil((xs[k + 1] - ox) / (SQRT3 * size) - r / 2) - 1;
        for (let q = qFrom; q <= qTo; q++) {
          const x = ox + SQRT3 * size * (q + r / 2);
          if (x >= xs[k] && x < xs[k + 1]) out.push({ q, r, x, y });
        }
      }
    }
    return out;
  }

  /**
   * Pointy-top hexagonal grid with exactly `capacity` cells whose centres lie inside `ring` (projected units).
   * The cell size is found by bisection; the few surplus cells closest to the outline are dropped.
   * Returns { cells: [{id, q, r, x, y}], size, ox, oy, index: Map("q,r" → id), neighbors: id[][] }.
   */
  function buildGrid(ring, capacity) {
    const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
    const box = { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
    const ox = box.x0, oy = box.y0;
    const area = Math.abs(ring.reduce((s, p, i) => (i ? s + ring[i - 1][0] * p[1] - p[0] * ring[i - 1][1] : s), 0)) / 2;
    let lo = Math.sqrt(area / capacity / (1.5 * SQRT3)) * 0.5;       // hex area = 1.5·√3·size²
    let hi = lo * 4;
    // largest size that still gives >= capacity cells; 26 halvings narrow a 4× bracket to ~1e-7 (surplus cells are
    // trimmed below anyway, so more precision would not change the grid)
    for (let i = 0; i < 26; i++) {
      const mid = (lo + hi) / 2;
      if (hexCentres(ring, mid, ox, oy, box).length >= capacity) lo = mid; else hi = mid;
    }
    const size = lo;
    let pts = hexCentres(ring, size, ox, oy, box);
    if (pts.length > capacity) {
      const ranked = pts.map((p, i) => ({ i, d: distanceToRing(p.x, p.y, ring) })).sort((a, b) => a.d - b.d || a.i - b.i);
      const drop = new Set(ranked.slice(0, pts.length - capacity).map((x) => x.i));
      pts = pts.filter((_, i) => !drop.has(i));
    }
    pts.sort((a, b) => a.r - b.r || a.q - b.q);
    const cells = pts.map((p, id) => Object.freeze({ id, q: p.q, r: p.r, x: p.x, y: p.y }));
    const index = new Map(cells.map((c) => [key(c.q, c.r), c.id]));
    const neighbors = cells.map((c) => AXIAL_DIRS.map(([dq, dr]) => index.get(key(c.q + dq, c.r + dr))).filter((n) => n !== undefined));
    return { cells, size, ox, oy, index, neighbors };
  }

  // ------------------------------------------------------------------------------------------ counts

  /**
   * Cells per crop: areas / haPerCell rounded by largest remainder so that the counts add up to the rounded total.
   * Above `capacity`, shares are scaled to the capacity and the excess is reported as `overflow` (cells not shown).
   */
  function cellCounts(areas, crops, haPerCell, capacity) {
    const exact = crops.map((c) => Math.max(0, areas[c]) / haPerCell);
    const sum = exact.reduce((a, b) => a + b, 0);
    const total = Math.round(sum);
    const target = Math.min(total, capacity);
    const scaled = total > capacity && sum > 0 ? exact.map((e) => e * capacity / sum) : exact;
    const floors = scaled.map(Math.floor);
    let extra = target - floors.reduce((a, b) => a + b, 0);
    const order = scaled.map((e, i) => ({ i, rem: e - floors[i] })).sort((a, b) => b.rem - a.rem || a.i - b.i);
    for (let k = 0; k < order.length && extra > 0; k++, extra--) floors[order[k].i] += 1;
    const counts = {};
    crops.forEach((c, i) => { counts[c] = floors[i]; });
    return { counts, total, overflow: Math.max(0, total - capacity) };
  }

  function tallyLayout(layout, crops) {
    const t = Object.fromEntries(crops.map((c) => [c, 0]));
    for (const c of layout) if (c !== null) t[c] += 1;
    return t;
  }

  // ------------------------------------------------------------------------------------------ layout

  /** Smooth, deterministic noise in [-1, 1] (sum of three sine waves); `salt` varies it per crop. */
  function smoothNoise(x, y, scale, salt) {
    const k = (2 * Math.PI) / scale;
    const a = Math.sin(x * k * 1.0 + salt * 1.7) + Math.sin(y * k * 1.3 + salt * 2.9) + Math.sin((x + y) * k * 0.7 + salt * 4.1);
    return a / 3;
  }

  /** Spread-out seed cells, one per crop (largest crops first), by farthest-point sampling. */
  function seedCells(grid, crops, counts) {
    const order = crops.slice().sort((a, b) => (counts[b] || 0) - (counts[a] || 0) || crops.indexOf(a) - crops.indexOf(b));
    const cx = grid.cells.reduce((s, c) => s + c.x, 0) / grid.cells.length;
    const cy = grid.cells.reduce((s, c) => s + c.y, 0) / grid.cells.length;
    // first seed: farthest cell from the centre (an end of the region), then repeatedly the farthest from all seeds
    let first = 0, best = -1;
    for (const c of grid.cells) { const d = Math.hypot(c.x - cx, c.y - cy); if (d > best) { best = d; first = c.id; } }
    const seeds = [first];
    const minDist = grid.cells.map((c) => Math.hypot(c.x - grid.cells[first].x, c.y - grid.cells[first].y));
    while (seeds.length < order.length) {
      let pick = 0, far = -1;
      for (const c of grid.cells) if (minDist[c.id] > far) { far = minDist[c.id]; pick = c.id; }
      seeds.push(pick);
      for (const c of grid.cells) minDist[c.id] = Math.min(minDist[c.id], Math.hypot(c.x - grid.cells[pick].x, c.y - grid.cells[pick].y));
    }
    const out = {};
    order.forEach((crop, i) => { out[crop] = seeds[i]; });
    return out;
  }

  /**
   * Natural-looking layout: crops grow as compact patches from spread-out seeds (smallest first; the largest crop
   * takes the remaining "background"), with smooth noise bending the borders. Deterministic.
   * Returns an array (length = cells) of crop ids; null = unsown.
   */
  function initialLayout(grid, counts, crops) {
    const n = grid.cells.length;
    const layout = new Array(n).fill(null);
    const seeds = seedCells(grid, crops, counts);
    const extent = Math.max(...grid.cells.map((c) => c.x)) - Math.min(...grid.cells.map((c) => c.x));
    const active = crops.filter((c) => (counts[c] || 0) > 0)
      .sort((a, b) => counts[a] - counts[b] || crops.indexOf(a) - crops.indexOf(b));
    const background = active[active.length - 1];
    for (const crop of active) {
      if (crop === background) continue;
      growPatch(grid, layout, crop, counts[crop], seeds[crop], extent, crops.indexOf(crop));
    }
    if (background) {
      let left = counts[background];
      for (let i = 0; i < n && left > 0; i++) if (layout[i] === null) { layout[i] = background; left--; }
    }
    return consolidate(grid, layout, crops, null);
  }

  /** Fragmentation of one crop: 10 per detached fragment + 1 per cell with at most one same-crop neighbour. */
  function fragmentScore(grid, layout, crop) {
    if (crop === null) return 0;
    let weak = 0;
    for (let i = 0; i < layout.length; i++) {
      if (layout[i] !== crop) continue;
      let same = 0;
      for (const nb of grid.neighbors[i]) if (layout[nb] === crop) same++;
      if (same <= 1) weak++;
    }
    return 10 * Math.max(0, components(grid, layout, crop).length - 1) + weak;
  }

  /**
   * Removes stray fragments (visual defect found in the stage 3.5 audit). A detached fragment of crop A (k cells)
   * is handed to the neighbouring crop B that surrounds it most, and A takes back k cells of B on the edge of A's
   * main patch. Every crop keeps its cell count; a move is kept only if A loses a fragment, B gains none and both become less fragmented.
   * `canMove(id)` limits which fragment cells may move (null = all). Deterministic; returns a new layout.
   */
  function consolidate(grid, layout, crops, canMove) {
    const next = layout.slice();
    for (let pass = 0; pass < 12; pass++) {         // one fragment per crop per pass; stops when nothing improves
      let improved = false;
      for (const A of crops) {
        const comps = components(grid, next, A);
        if (comps.length < 2) continue;
        const mainComp = comps.reduce((a, b) => (b.length > a.length ? b : a));
        for (const frag of comps) {
          if (frag === mainComp || (canMove && !frag.every(canMove))) continue;
          if (!frag.every((id) => next[id] === A)) continue;
          const inFrag = new Set(frag);
          const nbCount = new Map();
          for (const id of frag) for (const nb of grid.neighbors[id]) {
            if (!inFrag.has(nb) && next[nb] !== null && next[nb] !== A) nbCount.set(next[nb], (nbCount.get(next[nb]) || 0) + 1);
          }
          if (!nbCount.size) continue;
          // try the neighbouring crops in order of contact; the first one that also borders A's main patch wins
          const partners = [...nbCount.keys()].sort((x, y) => nbCount.get(y) - nbCount.get(x) || crops.indexOf(x) - crops.indexOf(y));
          let done = false;
          for (const B of partners) {
            // k cells of B grown from the edge of A's main patch (most A neighbours first)
            const owned = new Set(components(grid, next, A).reduce((a, b) => (b.length > a.length ? b : a)));
            const picked = [];
            for (let k = 0; k < frag.length; k++) {
              let best = -1, bt = 0;
              for (const id of owned) for (const nb of grid.neighbors[id]) {
                if (next[nb] !== B || owned.has(nb) || inFrag.has(nb)) continue;
                let t = 0;
                for (const m of grid.neighbors[nb]) if (owned.has(m)) t++;
                if (t > bt || (t === bt && nb < best)) { bt = t; best = nb; }
              }
              if (best < 0) break;
              picked.push(best); owned.add(best);
            }
            if (picked.length !== frag.length) continue;
            const nA = comps.length, nB = components(grid, next, B).length;
            const before = fragmentScore(grid, next, A) + fragmentScore(grid, next, B);
            for (const id of frag) next[id] = B;
            for (const id of picked) next[id] = A;
            const okA = components(grid, next, A).length < nA, okB = components(grid, next, B).length <= nB;
            if (okA && okB && fragmentScore(grid, next, A) + fragmentScore(grid, next, B) < before) { done = true; break; }
            for (const id of frag) next[id] = A;
            for (const id of picked) next[id] = B;
          }
          if (done) { improved = true; break; }
        }
      }
      if (!improved) break;
    }
    return next;
  }

  /** Best-first growth of one crop from a seed into free cells, ordered by noisy distance to the seed. */
  function growPatch(grid, layout, crop, count, seed, extent, salt) {
    const s = grid.cells[seed];
    const cost = (id) => {
      const c = grid.cells[id];
      return Math.hypot(c.x - s.x, c.y - s.y) * (1 + NOISE_AMPLITUDE * smoothNoise(c.x, c.y, extent / 3, salt + 1));
    };
    let start = seed;
    if (layout[start] !== null) {                                   // seed taken: nearest free cell instead
      let best = Infinity;
      for (const c of grid.cells) if (layout[c.id] === null) { const d = Math.hypot(c.x - s.x, c.y - s.y); if (d < best) { best = d; start = c.id; } }
    }
    const frontier = new Map([[start, cost(start)]]);
    let placed = 0;
    while (placed < count) {
      if (frontier.size === 0) {                                     // boxed in: continue from the nearest free cell
        let best = Infinity, next = -1;
        for (const c of grid.cells) if (layout[c.id] === null) { const d = cost(c.id); if (d < best) { best = d; next = c.id; } }
        if (next < 0) break;
        frontier.set(next, best);
      }
      let pick = -1, pc = Infinity;
      for (const [id, c] of frontier) if (c < pc || (c === pc && id < pick)) { pc = c; pick = id; }
      frontier.delete(pick);
      if (layout[pick] !== null) continue;
      layout[pick] = crop;
      placed++;
      for (const nb of grid.neighbors[pick]) if (layout[nb] === null && !frontier.has(nb)) frontier.set(nb, cost(nb));
    }
  }

  function centroidOf(grid, layout, crop) {
    let x = 0, y = 0, k = 0;
    for (let i = 0; i < layout.length; i++) if (layout[i] === crop) { x += grid.cells[i].x; y += grid.cells[i].y; k++; }
    return k ? { x: x / k, y: y / k, k } : null;
  }

  /**
   * Smallest change of `layout` that matches `counts`: cells move only for crops whose counts changed.
   * Receivers grow from their patch edge, taking cells from crops with surplus or unsown cells next to them; when no
   * such neighbour exists, cells are passed along a short chain of neighbours so patches stay whole.
   * Remaining surplus (total area decreased) becomes unsown at the patch edges. Returns { layout, changed }.
   */
  function reconcile(grid, layout, counts, crops) {
    const next = layout.slice();
    const have = tallyLayout(next, crops);
    const surplus = {}, deficit = {};
    for (const c of crops) {
      const d = (counts[c] || 0) - have[c];
      if (d > 0) deficit[c] = d; else if (d < 0) surplus[c] = -d;
    }
    const seeds = seedCells(grid, crops, counts);
    const isDonor = (id) => next[id] === null || (surplus[next[id]] || 0) > 0;
    const take = (id, crop) => { const from = next[id]; if (from !== null) surplus[from]--; next[id] = crop; };

    const receivers = crops.filter((c) => deficit[c] > 0);
    let guard = 0;
    while (receivers.some((c) => deficit[c] > 0) && guard++ < 100000) {
      for (const crop of receivers) {
        if (!(deficit[crop] > 0)) continue;
        const cen = centroidOf(grid, next, crop) || grid.cells[seeds[crop]];
        // 1) a donor cell on the patch edge (unsown first, then nearest to the patch centre)
        let pick = -1, best = Infinity;
        for (let i = 0; i < next.length; i++) {
          if (next[i] === crop || !isDonor(i)) continue;
          if (!grid.neighbors[i].some((nb) => next[nb] === crop)) continue;
          const c = grid.cells[i];
          const d = Math.hypot(c.x - cen.x, c.y - cen.y) + (next[i] === null ? 0 : grid.size * 0.5);
          if (d < best) { best = d; pick = i; }
        }
        if (pick >= 0) { take(pick, crop); deficit[crop]--; continue; }
        // 2) no donor touches the patch: pass a cell along the shortest chain of neighbours to the nearest donor
        const path = chainToDonor(grid, next, crop, isDonor);
        if (path) {
          for (let k = path.length - 1; k > 0; k--) {
            if (k === path.length - 1) { const from = next[path[k]]; if (from !== null) surplus[from]--; }
            next[path[k]] = next[path[k - 1]];
          }
          next[path[0]] = crop;
          deficit[crop]--;
          continue;
        }
        // 3) the crop has no cells at all: start a patch at the nearest donor cell to its seed
        const s = grid.cells[seeds[crop]];
        best = Infinity; pick = -1;
        for (let i = 0; i < next.length; i++) if (isDonor(i)) { const c = grid.cells[i]; const d = Math.hypot(c.x - s.x, c.y - s.y); if (d < best) { best = d; pick = i; } }
        if (pick < 0) { deficit[crop] = 0; continue; }
        take(pick, crop); deficit[crop]--;
      }
    }
    // total decreased: remaining surplus becomes unsown, edge cells farthest from their patch centre first
    for (const crop of crops) {
      if (!(surplus[crop] > 0)) continue;
      const cen = centroidOf(grid, next, crop);
      const mine = [];
      for (let i = 0; i < next.length; i++) if (next[i] === crop) {
        const sameNb = grid.neighbors[i].filter((nb) => next[nb] === crop).length;
        mine.push({ i, edge: 6 - sameNb, d: Math.hypot(grid.cells[i].x - cen.x, grid.cells[i].y - cen.y) });
      }
      mine.sort((a, b) => b.edge - a.edge || b.d - a.d || a.i - b.i);
      for (let k = 0; k < surplus[crop] && k < mine.length; k++) next[mine[k].i] = null;
      surplus[crop] = 0;
    }
    // fragments created by this reconcile (e.g. a patch edge cut off by a growing neighbour) are tidied; fragments
    // that already existed in the input — such as cells the user painted on purpose — are never moved
    let anyMoved = false;
    for (let i = 0; i < next.length && !anyMoved; i++) if (next[i] !== layout[i]) anyMoved = true;
    const keep = new Set();
    if (anyMoved) {
      for (const crop of crops) {
        const comps = components(grid, layout, crop);
        if (comps.length < 2) continue;
        const main = comps.reduce((a, b) => (b.length > a.length ? b : a));
        for (const comp of comps) if (comp !== main) for (const id of comp) keep.add(id);
      }
    }
    const tidy = anyMoved ? consolidate(grid, next, crops, (id) => !keep.has(id)) : next;
    const changed = [];
    for (let i = 0; i < tidy.length; i++) if (tidy[i] !== layout[i]) changed.push({ id: i, from: layout[i], to: tidy[i] });
    return { layout: tidy, changed };
  }

  /** BFS from the crop's patch to the nearest donor cell; returns the path [edgeCell, …, donorCell] or null. */
  function chainToDonor(grid, layout, crop, isDonor) {
    const prev = new Map();
    const queue = [];
    for (let i = 0; i < layout.length; i++) {
      if (layout[i] !== crop) continue;
      for (const nb of grid.neighbors[i]) if (layout[nb] !== crop && !prev.has(nb)) { prev.set(nb, -1); queue.push(nb); }
    }
    for (let h = 0; h < queue.length; h++) {
      const id = queue[h];
      if (isDonor(id)) {
        const path = [];
        for (let cur = id; cur !== -1; cur = prev.get(cur)) path.unshift(cur);
        return path;
      }
      for (const nb of grid.neighbors[id]) if (layout[nb] !== crop && !prev.has(nb)) { prev.set(nb, id); queue.push(nb); }
    }
    return null;
  }

  // ------------------------------------------------------------------------------------------ brush

  /** Cell id under a point (projected units), or null outside the grid. */
  function cellAt(grid, x, y) {
    const px = (x - grid.ox) / grid.size, py = (y - grid.oy) / grid.size;
    const qf = (SQRT3 / 3) * px - py / 3, rf = (2 / 3) * py, sf = -qf - rf;
    let q = Math.round(qf), r = Math.round(rf);
    const s = Math.round(sf);
    const dq = Math.abs(q - qf), dr = Math.abs(r - rf), ds = Math.abs(s - sf);
    if (dq > dr && dq > ds) q = -r - s; else if (dr > ds) r = -q - s;
    const id = grid.index.get(key(q, r));
    return id === undefined ? null : id;
  }

  /** Cells within hex distance `radius` of a cell (1, 7, 19, 37 … cells in the interior). */
  function brushCells(grid, id, radius) {
    const c = grid.cells[id];
    const out = [];
    for (let dq = -radius; dq <= radius; dq++) {
      for (let dr = Math.max(-radius, -dq - radius); dr <= Math.min(radius, -dq + radius); dr++) {
        const n = grid.index.get(key(c.q + dq, c.r + dr));
        if (n !== undefined) out.push(n);
      }
    }
    return out;
  }

  /** Paints `ids` with `crop` (null = unsown / eraser). Returns { layout, changed: [{id, from, to}] }. */
  function paint(layout, ids, crop) {
    const next = layout.slice();
    const changed = [];
    for (const id of ids) {
      if (next[id] === crop) continue;
      changed.push({ id, from: next[id], to: crop });
      next[id] = crop;
    }
    return { layout: next, changed };
  }

  /**
   * Converts painted cell changes into exact area changes (ha): each cell moves 100 ha from `from` to `to`.
   * A crop never goes below 0 — it gives what it has, and the receiver gets exactly that, so crop-to-crop strokes
   * keep the total sown area unchanged. Unsown → crop adds 100 ha; crop → unsown (eraser) removes up to 100 ha.
   */
  function strokeAreas(areas, changes, haPerCell) {
    const ha = haPerCell || HA_PER_CELL;
    const out = Object.assign({}, areas);
    for (const ch of changes) {
      const amount = ch.from === null || ch.from === undefined ? ha : Math.min(ha, Math.max(0, out[ch.from]));
      if (ch.from !== null && ch.from !== undefined) out[ch.from] -= amount;
      if (ch.to !== null && ch.to !== undefined) out[ch.to] += amount;
    }
    return out;
  }

  // ------------------------------------------------------------------------------------------ labels

  function components(grid, layout, crop) {
    const seen = new Uint8Array(layout.length);
    const comps = [];
    for (let i = 0; i < layout.length; i++) {
      if (layout[i] !== crop || seen[i]) continue;
      const comp = [i];
      seen[i] = 1;
      for (let h = 0; h < comp.length; h++) {
        for (const nb of grid.neighbors[comp[h]]) if (!seen[nb] && layout[nb] === crop) { seen[nb] = 1; comp.push(nb); }
      }
      comps.push(comp);
    }
    return comps;
  }

  /**
   * One label anchor per crop: the cell deepest inside the crop's largest patch (depth = hex steps to the patch
   * edge; edge cells have depth 1). The renderer shows a label only where the depth leaves enough room.
   */
  function labelAnchors(grid, layout, crops) {
    const out = [];
    for (const crop of crops) {
      const comps = components(grid, layout, crop);
      if (!comps.length) continue;
      const comp = comps.reduce((a, b) => (b.length > a.length ? b : a));
      const inComp = new Set(comp);
      const depth = new Map();
      const queue = [];
      for (const id of comp) {
        const nbs = grid.neighbors[id];
        if (nbs.length < 6 || nbs.some((nb) => !inComp.has(nb))) { depth.set(id, 1); queue.push(id); }
      }
      for (let h = 0; h < queue.length; h++) {
        const id = queue[h];
        for (const nb of grid.neighbors[id]) if (inComp.has(nb) && !depth.has(nb)) { depth.set(nb, depth.get(id) + 1); queue.push(nb); }
      }
      const cx = comp.reduce((s, id) => s + grid.cells[id].x, 0) / comp.length;
      const cy = comp.reduce((s, id) => s + grid.cells[id].y, 0) / comp.length;
      let best = comp[0];
      for (const id of comp) {
        const d = depth.get(id), bd = depth.get(best);
        const dist = Math.hypot(grid.cells[id].x - cx, grid.cells[id].y - cy);
        const bdist = Math.hypot(grid.cells[best].x - cx, grid.cells[best].y - cy);
        if (d > bd || (d === bd && dist < bdist)) best = id;
      }
      out.push({ crop, id: best, x: grid.cells[best].x, y: grid.cells[best].y, depth: depth.get(best), size: comp.length });
    }
    return out;
  }

  /** Net cell changes between two layouts (used to turn a whole brush stroke into one area update). */
  function diffLayouts(before, after) {
    const out = [];
    for (let i = 0; i < before.length; i++) if (before[i] !== after[i]) out.push({ id: i, from: before[i], to: after[i] });
    return out;
  }

  /**
   * Does a label of textWidthPx × textHeightPx fit inside the patch around an anchor of the given depth, when one
   * cell is cellWidthPx wide (flat-to-flat) on screen? Width available ≈ (2·depth − 1) cells, height ≈ 2·depth rows
   * (row pitch 0.75 of the width), with a 10 % margin; rim cells (depth 1) are never labelled.
   */
  function labelFits(anchor, textWidthPx, textHeightPx, cellWidthPx) {
    if (!(anchor.depth >= 2)) return false;
    const width = (2 * anchor.depth - 1) * cellWidthPx * 0.9;
    const height = 2 * anchor.depth * cellWidthPx * 0.75 * 0.9;
    return textWidthPx <= width && textHeightPx <= height;
  }

  return Object.freeze({
    HA_PER_CELL, buildGrid, cellCounts, tallyLayout, initialLayout, reconcile, cellAt, brushCells, paint,
    strokeAreas, components, labelAnchors, diffLayouts, labelFits,
  });
});
