/* Procedural aerial landscape for the hero background.
 * Purely illustrative: a stylised irrigated river valley in an arid steppe
 * (meandering river with sandbars and an oxbow lake, riparian woodland, canals that
 * branch from the river, field strips laid out along each canal, flooded rice basins,
 * windbreaks, saline fallow and desert). It is NOT a map and NOT model output.
 * No external assets; works offline. Pauses when hidden; static under reduced motion. */
(function () {
  "use strict";
  var canvas = document.getElementById("terrain");
  if (!canvas || !canvas.getContext) return;
  var ctx = canvas.getContext("2d");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- seeded random + value noise ----------
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  var R = mulberry32(73104);
  function rand(a, b) { return a + (b - a) * R(); }
  function pick(a) { return a[Math.floor(R() * a.length)]; }

  var PERM = new Uint16Array(512), VAL = new Float32Array(256);
  (function () {
    var p = [], i, j, t;
    for (i = 0; i < 256; i++) p.push(i);
    for (i = 255; i > 0; i--) { j = Math.floor(R() * (i + 1)); t = p[i]; p[i] = p[j]; p[j] = t; }
    for (i = 0; i < 512; i++) PERM[i] = p[i & 255];
    for (i = 0; i < 256; i++) VAL[i] = R();
  })();
  function vnoise(x, y) {
    var xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
    xi &= 255; yi &= 255;
    var u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
    var a = VAL[PERM[PERM[xi] + yi]], b = VAL[PERM[PERM[xi + 1] + yi]];
    var c = VAL[PERM[PERM[xi] + yi + 1]], d = VAL[PERM[PERM[xi + 1] + yi + 1]];
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
  }
  function fbm(x, y, oct) {
    var s = 0, amp = 0.5, f = 1, n = 0;
    for (var i = 0; i < (oct || 4); i++) { s += amp * vnoise(x * f, y * f); n += amp; amp *= 0.5; f *= 2.03; }
    return s / n;
  }
  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function smooth(a, b, x) { var t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); }
  function mix(c1, c2, t) { return [c1[0] + (c2[0] - c1[0]) * t, c1[1] + (c2[1] - c1[1]) * t, c1[2] + (c2[2] - c1[2]) * t]; }
  function lerpP(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]; }

  // ---------- polyline helper ----------
  function Poly(pts) {
    var cum = [0];
    for (var i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
    return {
      pts: pts, cum: cum, len: cum[cum.length - 1],
      at: function (s) {
        s = clamp(s, 0, this.len);
        var lo = 0, hi = cum.length - 1;
        while (hi - lo > 1) { var m = (lo + hi) >> 1; if (cum[m] < s) lo = m; else hi = m; }
        var seg = cum[hi] - cum[lo] || 1, t = (s - cum[lo]) / seg, a = pts[lo], b = pts[hi];
        var tx = (b[0] - a[0]) / seg, ty = (b[1] - a[1]) / seg;
        return { x: a[0] + (b[0] - a[0]) * t, y: a[1] + (b[1] - a[1]) * t, tx: tx, ty: ty, nx: -ty, ny: tx };
      }
    };
  }

  // ---------- world ----------
  var WW = 2600, WH = 1700;
  var world = document.createElement("canvas");
  world.width = WW; world.height = WH;
  var w = world.getContext("2d");

  // River centreline (Catmull-Rom through meandering control points)
  function catmull(p0, p1, p2, p3, t) {
    var t2 = t * t, t3 = t2 * t;
    return [
      0.5 * (2 * p1[0] + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
      0.5 * (2 * p1[1] + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
    ];
  }
  function spline(ctrl, per) {
    var out = [];
    for (var i = 0; i < ctrl.length - 1; i++) {
      var p0 = ctrl[Math.max(0, i - 1)], p1 = ctrl[i], p2 = ctrl[i + 1], p3 = ctrl[Math.min(ctrl.length - 1, i + 2)];
      for (var s = 0; s < per; s++) out.push(catmull(p0, p1, p2, p3, s / per));
    }
    out.push(ctrl[ctrl.length - 1]);
    return out;
  }
  var ctrl = [];
  for (var i = 0; i <= 12; i++) {
    var t = i / 12;
    ctrl.push([-260 + t * (WW + 520), 300 + t * 1080 + Math.sin(t * 10.5 + 0.6) * 165 + Math.sin(t * 23 + 2) * 38 + rand(-25, 25)]);
  }
  var river = Poly(spline(ctrl, 26));
  function riverWidth(s) { return 17 + 15 * fbm(s * 0.0045, 3.7, 3); } // half-width, 17–32 world px
  var RW_MAX = 34;

  // Coarse distance-to-river field (bilinear), used for terrain and placement
  var DC = 16, DGX = Math.ceil(WW / DC) + 2, DGY = Math.ceil(WH / DC) + 2, dgrid = new Float32Array(DGX * DGY);
  (function () {
    var P = river.pts;
    for (var gy = 0; gy < DGY; gy++) for (var gx = 0; gx < DGX; gx++) {
      var x = gx * DC, y = gy * DC, best = 1e12;
      for (var k = 0; k < P.length; k += 2) { var dx = P[k][0] - x, dy = P[k][1] - y, d = dx * dx + dy * dy; if (d < best) best = d; }
      dgrid[gy * DGX + gx] = Math.sqrt(best);
    }
  })();
  function dist(x, y) {
    var fx = clamp(x / DC, 0, DGX - 1.001), fy = clamp(y / DC, 0, DGY - 1.001);
    var x0 = Math.floor(fx), y0 = Math.floor(fy), tx = fx - x0, ty = fy - y0, i0 = y0 * DGX + x0;
    var a = dgrid[i0], b = dgrid[i0 + 1], c = dgrid[i0 + DGX], d = dgrid[i0 + DGX + 1];
    return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty;
  }

  // ---------- 1. Base terrain: steppe, desert, floodplain, salt flats, hillshade ----------
  (function () {
    var S = 4, LW = Math.ceil(WW / S), LH = Math.ceil(WH / S);
    var hgt = new Float32Array((LW + 2) * (LH + 2));
    for (var y = 0; y < LH + 2; y++) for (var x = 0; x < LW + 2; x++)
      hgt[y * (LW + 2) + x] = fbm(x * S * 0.0012, y * S * 0.0012, 5);
    var small = document.createElement("canvas"); small.width = LW; small.height = LH;
    var sctx = small.getContext("2d"), img = sctx.createImageData(LW, LH), D = img.data;
    var desert = [76, 80, 80], desertHi = [96, 100, 98], steppe = [56, 66, 62], flood = [32, 50, 48], salt = [118, 128, 134];
    for (y = 0; y < LH; y++) for (x = 0; x < LW; x++) {
      var wx = x * S, wy = y * S, d = dist(wx, wy);
      var h = hgt[(y + 1) * (LW + 2) + x + 1];
      var veg = fbm(wx * 0.0022 + 31, wy * 0.0022 - 12, 4);
      var c = mix(desert, desertHi, smooth(0.3, 0.75, h));
      c = mix(c, steppe, smooth(0.42, 0.7, veg) * 0.85);
      c = mix(c, flood, smooth(700, 160, d) * 0.9);
      var sl = fbm(wx * 0.0032 + 47, wy * 0.0032 - 7, 4);
      var crust = 0.75 + 0.25 * vnoise(wx * 0.03, wy * 0.03);  // broken, crusty salt rather than smooth patches
      c = mix(c, salt, smooth(0.62, 0.76, sl) * smooth(260, 460, d) * 0.42 * crust);
      // wind ripples fade in gradually towards the desert edge (no hard contour)
      var r = Math.sin(wx * 0.045 + wy * 0.018 + fbm(wx * 0.004, wy * 0.004, 2) * 14);
      c = mix(c, desertHi, (r * 0.5 + 0.5) * 0.10 * smooth(820, 1150, d));
      // hillshade, light from the upper right
      var gxv = hgt[(y + 1) * (LW + 2) + x + 2] - hgt[(y + 1) * (LW + 2) + x];
      var gyv = hgt[y * (LW + 2) + x + 1] - hgt[(y + 2) * (LW + 2) + x + 1];
      var shade = clamp(1 + (gxv * 0.7 + gyv * 0.7) * 9, 0.72, 1.22);
      var grain = 0.96 + vnoise(wx * 0.08, wy * 0.08) * 0.08;
      var o = (y * LW + x) * 4;
      D[o] = c[0] * shade * grain; D[o + 1] = c[1] * shade * grain; D[o + 2] = c[2] * shade * grain; D[o + 3] = 255;
    }
    sctx.putImageData(img, 0, 0);
    w.imageSmoothingEnabled = true; w.imageSmoothingQuality = "high";
    w.drawImage(small, 0, 0, LW * S, LH * S);
  })();

  // ---------- 2. Canals: main canals branch from the river, then turn to run along it ----------
  var OC = 10, OGX = Math.ceil(WW / OC), OGY = Math.ceil(WH / OC), occ = new Uint8Array(OGX * OGY);
  function occAt(x, y) { var gx = Math.floor(x / OC), gy = Math.floor(y / OC); return gx < 0 || gy < 0 || gx >= OGX || gy >= OGY ? 1 : occ[gy * OGX + gx]; }
  function occMark(x, y) { var gx = Math.floor(x / OC), gy = Math.floor(y / OC); if (gx >= 0 && gy >= 0 && gx < OGX && gy < OGY) occ[gy * OGX + gx] = 1; }

  var canals = [];
  function growCanal(x, y, ang, steps, stepLen, turnTo, level, minDist) {
    var pts = [[x, y]], a = ang;
    for (var k = 0; k < steps; k++) {
      var travelled = k * stepLen;
      if (turnTo !== null && travelled > 110) {
        var diff = Math.atan2(Math.sin(turnTo - a), Math.cos(turnTo - a));
        a += diff * 0.05;
      }
      a += (fbm(x * 0.004 + level * 9, y * 0.004, 2) - 0.5) * 0.09;
      x += Math.cos(a) * stepLen; y += Math.sin(a) * stepLen;
      if (x < -60 || y < -60 || x > WW + 60 || y > WH + 60) break;
      if (k > 6 && dist(x, y) < minDist) break;
      if (k > 4 && level > 0 && occAt(x, y)) break;
      pts.push([x, y]);
    }
    return pts.length > 6 ? Poly(pts) : null;
  }
  for (var k = 0; k < 9; k++) {
    var s0 = river.len * (0.07 + k * 0.105 + rand(-0.02, 0.02));
    var p = river.at(s0), side = k % 2 ? 1 : -1, rw = riverWidth(s0);
    var outA = Math.atan2(p.ny * side, p.nx * side);
    var along = Math.atan2(p.ty, p.tx) + (R() < 0.5 ? 0 : Math.PI);
    var main = growCanal(p.x + p.nx * side * (rw + 3), p.y + p.ny * side * (rw + 3), outA, Math.floor(rand(48, 78)), 14, along, 0, RW_MAX + 60);
    if (!main) continue;
    main.level = 0; canals.push(main);
    for (var m = 0; m < main.pts.length; m++) { occMark(main.pts[m][0], main.pts[m][1]); }
    // secondary canals branch towards the side away from the river
    for (var sb = rand(120, 200); sb < main.len - 60; sb += rand(150, 260)) {
      var q = main.at(sb);
      var sgn = dist(q.x + q.nx * 40, q.y + q.ny * 40) > dist(q.x - q.nx * 40, q.y - q.ny * 40) ? 1 : -1;
      var sec = growCanal(q.x + q.nx * sgn * 6, q.y + q.ny * sgn * 6, Math.atan2(q.ny * sgn, q.nx * sgn), Math.floor(rand(10, 24)), 13, null, 1, RW_MAX + 60);
      if (!sec) continue;
      sec.level = 1; canals.push(sec);
      for (m = 0; m < sec.pts.length; m++) occMark(sec.pts[m][0], sec.pts[m][1]);
    }
  }

  // ---------- 3. Fields laid out along each canal (irregular strips, no global grid) ----------
  function inQuad(px, py, q) {
    var inside = false;
    for (var i = 0, j = 3; i < 4; j = i++) {
      var xi = q[i][0], yi = q[i][1], xj = q[j][0], yj = q[j][1];
      if ((yi > py) !== (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  function bilin(q, u, v) { return lerpP(lerpP(q[0], q[1], u), lerpP(q[3], q[2], u), v); }
  var fields = [];
  function tryField(q, canal) {
    // reject strongly wedge-shaped plots (inner side of tight canal bends)
    var near = Math.hypot(q[1][0] - q[0][0], q[1][1] - q[0][1]), farE = Math.hypot(q[2][0] - q[3][0], q[2][1] - q[3][1]);
    if (farE < near * 0.55 || farE > near * 1.9) return false;
    for (var i = 0; i < 4; i++) {
      if (q[i][0] < -80 || q[i][1] < -80 || q[i][0] > WW + 80 || q[i][1] > WH + 80) return false;
      if (dist(q[i][0], q[i][1]) < RW_MAX + 34) return false;
    }
    var probes = [[0.5, 0.5], [0.25, 0.3], [0.75, 0.3], [0.25, 0.75], [0.75, 0.75]];
    for (i = 0; i < probes.length; i++) { var pp = bilin(q, probes[i][0], probes[i][1]); if (occAt(pp[0], pp[1])) return false; }
    var minx = Math.min(q[0][0], q[1][0], q[2][0], q[3][0]), maxx = Math.max(q[0][0], q[1][0], q[2][0], q[3][0]);
    var miny = Math.min(q[0][1], q[1][1], q[2][1], q[3][1]), maxy = Math.max(q[0][1], q[1][1], q[2][1], q[3][1]);
    for (var y = Math.floor(miny / OC) * OC + OC / 2; y < maxy; y += OC)
      for (var x = Math.floor(minx / OC) * OC + OC / 2; x < maxx; x += OC) if (inQuad(x, y, q)) occMark(x, y);
    fields.push({ q: q, canal: canal });
    return true;
  }
  canals.forEach(function (c) {
    [-1, 1].forEach(function (sd) {
      var s = rand(8, 30), off = c.level === 0 ? 11 : 7;
      while (s < c.len - 30) {
        var fw = rand(42, 110), s1 = Math.min(s + fw, c.len - 4);
        if (R() < 0.07) { s = s1 + rand(10, 30); continue; } // gap: track, farmstead, uncultivated patch
        var a = c.at(s), b = c.at(s1);
        var d1 = rand(85, 205) * (c.level === 0 ? 1 : 0.85), d2 = d1 * rand(0.82, 1.18);
        var q = [
          [a.x + a.nx * sd * off, a.y + a.ny * sd * off],
          [b.x + b.nx * sd * off, b.y + b.ny * sd * off],
          [b.x + b.nx * sd * (off + d2) + rand(-7, 7), b.y + b.ny * sd * (off + d2) + rand(-7, 7)],
          [a.x + a.nx * sd * (off + d1) + rand(-7, 7), a.y + a.ny * sd * (off + d1) + rand(-7, 7)]
        ];
        tryField(q, c);
        s = s1 + rand(5, 11); // field road
      }
    });
  });

  // ---------- 4. Draw river corridor (banks, oxbow, side channel) ----------
  function ribbon(poly, halfW, s0, s1, step) {
    var L = [], Rr = [];
    for (var s = s0; s <= s1; s += step) {
      var p = poly.at(s), hw = halfW(s);
      L.push([p.x + p.nx * hw, p.y + p.ny * hw]); Rr.push([p.x - p.nx * hw, p.y - p.ny * hw]);
    }
    var path = new Path2D(); path.moveTo(L[0][0], L[0][1]);
    for (var i = 1; i < L.length; i++) path.lineTo(L[i][0], L[i][1]);
    for (i = Rr.length - 1; i >= 0; i--) path.lineTo(Rr[i][0], Rr[i][1]);
    path.closePath();
    return path;
  }
  // soft muddy banks (several translucent passes = feathered edge)
  [2.6, 2.1, 1.7].forEach(function (k, i) {
    w.fillStyle = ["rgba(40,52,52,.35)", "rgba(58,68,66,.45)", "rgba(84,92,88,.55)"][i];
    w.fill(ribbon(river, function (s) { return riverWidth(s) * k + 6; }, 0, river.len, 8));
  });
  // oxbow lake on one outer bend
  (function () {
    var s = river.len * 0.36, p = river.at(s), side = 1;
    var cx = p.x + p.nx * side * 150, cy = p.y + p.ny * side * 150;
    w.save(); w.translate(cx, cy); w.rotate(Math.atan2(p.ty, p.tx));
    w.strokeStyle = "rgba(40,60,58,.7)"; w.lineWidth = 26; w.lineCap = "round";
    w.beginPath(); w.ellipse(0, 0, 120, 60, 0, Math.PI * 0.15, Math.PI * 1.1); w.stroke();
    var g = w.createLinearGradient(-120, -60, 120, 60); g.addColorStop(0, "#123A72"); g.addColorStop(1, "#0A2652");
    w.strokeStyle = g; w.lineWidth = 13;
    w.beginPath(); w.ellipse(0, 0, 120, 60, 0, Math.PI * 0.18, Math.PI * 1.07); w.stroke();
    w.restore();
  })();

  // ---------- 5. Fields ----------
  var FC = {
    alfalfa: ["#2C5A43", "#2F6146", "#28533D", "#356849"],
    wheat:   ["#6E6C49", "#7B7652", "#676645", "#857D57"],
    melon:   ["#4A6240", "#52693F", "#456039"],
    cotton:  ["#5E6A57", "#68735E"],
    fallow:  ["#545C59", "#5E6562", "#68716D"]
  };
  var paddyPath = new Path2D();
  function quadPath(q) { var p = new Path2D(); p.moveTo(q[0][0], q[0][1]); for (var i = 1; i < 4; i++) p.lineTo(q[i][0], q[i][1]); p.closePath(); return p; }
  function wavyLine(a, b, amp, seed) {
    var p = new Path2D(), n = 8; p.moveTo(a[0], a[1]);
    var dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1, nx = -dy / L, ny = dx / L;
    for (var i = 1; i <= n; i++) {
      var t = i / n, o = (vnoise(seed + t * 3, seed * 0.7) - 0.5) * amp * (i === n ? 0 : 1);
      p.lineTo(a[0] + dx * t + nx * o, a[1] + dy * t + ny * o);
    }
    return p;
  }

  fields.forEach(function (f, idx) {
    var q = f.q, c = bilin(q, 0.5, 0.5), d = dist(c[0], c[1]), roll = R(), type;
    var richness = fbm(c[0] * 0.002 + 5, c[1] * 0.002, 3);
    if (d < 480) type = roll < 0.44 ? "paddy" : roll < 0.68 ? "alfalfa" : roll < 0.8 ? "melon" : roll < 0.92 ? "wheat" : "fallow";
    else if (d < 950) type = roll < 0.22 ? "paddy" : roll < 0.48 ? "alfalfa" : roll < 0.7 ? "wheat" : roll < 0.83 ? "melon" : roll < 0.9 ? "cotton" : "fallow";
    else type = roll < 0.3 ? "wheat" : roll < 0.48 ? "alfalfa" : roll < 0.6 ? "melon" : "fallow";
    if (richness < 0.26 && type !== "paddy") type = "fallow";
    f.type = type;
    var path = quadPath(q);

    // field shadow on the ground (low sun from upper right)
    w.save(); w.translate(-2.5, 3); w.fillStyle = "rgba(0,8,20,.28)"; w.fill(path); w.restore();

    if (type === "paddy") {
      var k = Math.floor(rand(2, 5)), cuts = [0];
      for (var i = 1; i < k; i++) cuts.push(i / k + rand(-0.06, 0.06));
      cuts.push(1);
      for (i = 0; i < k; i++) {
        var A = bilin(q, 0, cuts[i]), B = bilin(q, 1, cuts[i]), C = bilin(q, 1, cuts[i + 1]), D = bilin(q, 0, cuts[i + 1]);
        var cell = [A, B, C, D], cp = quadPath(cell);
        // water: muted sky reflection, slightly lighter towards the sun
        var g = w.createLinearGradient(A[0], A[1], C[0], C[1]);
        var depth = R();
        g.addColorStop(0, depth < 0.5 ? "#2C5578" : "#264C70");
        g.addColorStop(0.55, "#1C3E60");
        g.addColorStop(1, "#14304C");
        w.fillStyle = g; w.fill(cp);
        // rice canopy: from open water (just flooded) to dense green (established crop)
        var canopy = Math.pow(R(), 0.8);
        w.fillStyle = "rgba(66,112,84," + (0.12 + canopy * 0.6).toFixed(2) + ")"; w.fill(cp);
        // rows of seedlings
        w.save(); w.clip(cp); w.strokeStyle = "rgba(150,210,170,.10)"; w.lineWidth = 1;
        for (var r = 0.06; r < 1; r += 0.07) { var P0 = lerpP(A, D, r), P1 = lerpP(B, C, r); w.beginPath(); w.moveTo(P0[0], P0[1]); w.lineTo(P1[0], P1[1]); w.stroke(); }
        // sparkles of light on the water
        for (var sp = 0; sp < 6; sp++) { var pt = bilin(cell, R(), R()); w.fillStyle = "rgba(200,225,255," + rand(0.05, 0.18).toFixed(2) + ")"; w.fillRect(pt[0], pt[1], 1.6, 1.6); }
        w.restore();
        paddyPath.addPath(cp);
        // inner bund between basins
        if (i > 0) {
          var bl = wavyLine(A, B, 5, idx * 1.7 + i);
          w.strokeStyle = "#3E5944"; w.lineWidth = 2.6; w.stroke(bl);
          w.strokeStyle = "rgba(190,215,195,.16)"; w.lineWidth = 0.9; w.stroke(bl);
        }
      }
      w.strokeStyle = "#3A5240"; w.lineWidth = 3; w.stroke(path);
      w.strokeStyle = "rgba(190,215,195,.14)"; w.lineWidth = 1; w.stroke(path);
    } else {
      var base = pick(FC[type]);
      w.save(); w.clip(path);
      w.fillStyle = base; w.fill(path);
      // light across the field
      var lg = w.createLinearGradient(q[0][0], q[0][1], q[2][0], q[2][1]);
      lg.addColorStop(0, "rgba(255,255,255,.06)"); lg.addColorStop(1, "rgba(0,0,0,.12)");
      w.fillStyle = lg; w.fill(path);
      // patchy soil moisture / growth
      for (var bl2 = 0; bl2 < 3; bl2++) {
        var cp2 = bilin(q, R(), R()), rr = rand(25, 70), rg = w.createRadialGradient(cp2[0], cp2[1], 0, cp2[0], cp2[1], rr);
        rg.addColorStop(0, R() < 0.5 ? "rgba(0,0,0,.10)" : "rgba(255,255,255,.06)"); rg.addColorStop(1, "rgba(0,0,0,0)");
        w.fillStyle = rg; w.fillRect(cp2[0] - rr, cp2[1] - rr, rr * 2, rr * 2);
      }
      // crop rows / furrows parallel to the canal
      var spacing = type === "melon" ? 0.09 : type === "fallow" ? 0.12 : type === "cotton" ? 0.05 : 0.035;
      w.strokeStyle = type === "fallow" ? "rgba(210,220,220,.10)" : "rgba(8,20,18,.16)"; w.lineWidth = type === "melon" ? 2.2 : 1.1;
      for (var rr2 = spacing / 2; rr2 < 1; rr2 += spacing) {
        var a0 = lerpP(q[0], q[3], rr2), a1 = lerpP(q[1], q[2], rr2);
        w.beginPath(); w.moveTo(a0[0], a0[1]); w.lineTo(a1[0], a1[1]); w.stroke();
      }
      if (type === "fallow" && R() < 0.6) { // patchy salt crust: soft, irregular, low contrast
        for (var sc = 0; sc < 7; sc++) {
          var sp2 = bilin(q, R(), R()), sr = rand(8, 26), sg = w.createRadialGradient(sp2[0], sp2[1], 0, sp2[0], sp2[1], sr);
          sg.addColorStop(0, "rgba(205,215,218," + rand(0.06, 0.12).toFixed(2) + ")"); sg.addColorStop(1, "rgba(205,215,218,0)");
          w.fillStyle = sg; w.fillRect(sp2[0] - sr, sp2[1] - sr, sr * 2, sr * 2);
        }
      }
      w.restore();
      w.strokeStyle = "rgba(14,24,24,.45)"; w.lineWidth = 1.4; w.stroke(path);
    }
    // feeder outlet from the canal into the field
    var o0 = bilin(q, 0.5, 0), o1 = bilin(q, 0.5, -0.02);
    w.strokeStyle = "rgba(60,130,230,.75)"; w.lineWidth = 1.6;
    w.beginPath(); w.moveTo(o1[0], o1[1]); w.lineTo(o0[0], o0[1]); w.stroke();
  });

  // ---------- 6. Canals on top of fields ----------
  function strokePoly(poly, width, style) {
    w.strokeStyle = style; w.lineWidth = width; w.lineJoin = "round"; w.lineCap = "round";
    w.beginPath(); w.moveTo(poly.pts[0][0], poly.pts[0][1]);
    for (var i = 1; i < poly.pts.length; i++) w.lineTo(poly.pts[i][0], poly.pts[i][1]);
    w.stroke();
  }
  canals.forEach(function (c) {
    var main = c.level === 0;
    w.save(); w.translate(-2, 3); strokePoly(c, main ? 11 : 6, "rgba(0,8,20,.35)"); w.restore();
    strokePoly(c, main ? 10 : 5.5, main ? "#475449" : "#3E4C43");
    strokePoly(c, main ? 4.6 : 2.2, main ? "#1E5BC2" : "#1A4FA6");
    if (main) strokePoly(c, 1.1, "rgba(170,205,255,.45)");
  });
  // windbreak tree rows along some main canals (with cast shadows)
  canals.forEach(function (c) {
    if (c.level !== 0 || R() < 0.45) return;
    var sd = R() < 0.5 ? 1 : -1;
    for (var s = 0; s < c.len; s += rand(5, 8)) {
      if (vnoise(s * 0.02, c.len) < 0.3) continue;
      var p = c.at(s), x = p.x + p.nx * sd * 8, y = p.y + p.ny * sd * 8, r = rand(2.2, 3.8);
      w.fillStyle = "rgba(0,8,20,.4)"; w.beginPath(); w.arc(x - 3, y + 4, r * 1.1, 0, 6.283); w.fill();
      w.fillStyle = pick(["#24503E", "#2A5A44", "#1F4637"]); w.beginPath(); w.arc(x, y, r, 0, 6.283); w.fill();
      w.fillStyle = "rgba(170,210,180,.18)"; w.beginPath(); w.arc(x + r * 0.3, y - r * 0.3, r * 0.45, 0, 6.283); w.fill();
    }
  });

  // ---------- 7. Riparian woodland (tugai) along the banks ----------
  for (var tg = 0; tg < 2600; tg++) {
    var s = R() * river.len, p2 = river.at(s), sd2 = R() < 0.5 ? 1 : -1, hw = riverWidth(s);
    var off = hw + 4 + Math.pow(R(), 1.8) * 120;
    if (fbm(s * 0.006, sd2 * 3, 2) < 0.42 && off > hw + 40) continue;
    var x = p2.x + p2.nx * sd2 * off + rand(-6, 6), y = p2.y + p2.ny * sd2 * off + rand(-6, 6);
    if (occAt(x, y)) continue;
    var r2 = rand(2.5, 7);
    w.fillStyle = "rgba(0,8,20,.35)"; w.beginPath(); w.arc(x - 2.5, y + 3.5, r2, 0, 6.283); w.fill();
    w.fillStyle = pick(["#1F4A3B", "#24533F", "#1B4135", "#2B5B45", "#2E5240"]); w.beginPath(); w.arc(x, y, r2, 0, 6.283); w.fill();
    w.fillStyle = "rgba(180,215,190,.12)"; w.beginPath(); w.arc(x + r2 * 0.3, y - r2 * 0.35, r2 * 0.5, 0, 6.283); w.fill();
  }

  // ---------- 8. River water: side channel, main channel, sandbars, highlights ----------
  // side channel (anabranch) with an island
  (function () {
    var s0 = river.len * 0.62, s1 = river.len * 0.72, pts = [];
    for (var s = s0; s <= s1; s += 10) {
      var p = river.at(s), t = (s - s0) / (s1 - s0), o = Math.sin(t * Math.PI) * 70 + riverWidth(s) * Math.sin(t * Math.PI);
      pts.push([p.x - p.nx * o, p.y - p.ny * o]);
    }
    var side = Poly(pts);
    w.fillStyle = "rgba(84,92,88,.55)"; w.fill(ribbon(side, function () { return 14; }, 0, side.len, 6));
    w.fillStyle = "#123C78"; w.fill(ribbon(side, function (s) { return 6 + 3 * Math.sin(s * 0.02); }, 0, side.len, 6));
  })();
  var riverWater = ribbon(river, riverWidth, 0, river.len, 6);
  var wg = w.createLinearGradient(0, 0, WW, WH);
  wg.addColorStop(0, "#123E7E"); wg.addColorStop(0.5, "#0F3670"); wg.addColorStop(1, "#0B2C60");
  w.fillStyle = wg; w.fill(riverWater);
  // deeper thalweg
  w.fillStyle = "rgba(4,18,52,.45)"; w.fill(ribbon(river, function (s) { return riverWidth(s) * 0.45; }, 0, river.len, 6));
  // silty edges
  w.strokeStyle = "rgba(90,140,190,.35)"; w.lineWidth = 2.5; w.stroke(riverWater);
  // sandbars on inner bends
  for (var sb2 = 40; sb2 < river.len - 40; sb2 += rand(110, 220)) {
    var a2 = river.at(sb2 - 20), b2 = river.at(sb2 + 20);
    var curv = a2.tx * b2.ty - a2.ty * b2.tx; // sign = bend direction
    if (Math.abs(curv) < 0.02) continue;
    // point bar attached to the inner bank, half under water
    var pc = river.at(sb2), sideIn = curv > 0 ? 1 : -1, hw2 = riverWidth(sb2);
    w.save(); w.clip(riverWater);
    w.translate(pc.x + pc.nx * sideIn * hw2 * 0.95, pc.y + pc.ny * sideIn * hw2 * 0.95); w.rotate(Math.atan2(pc.ty, pc.tx));
    var bl3 = rand(40, 75), bg = w.createRadialGradient(0, 0, 2, 0, 0, bl3);
    bg.addColorStop(0, "rgba(150,148,128,.55)"); bg.addColorStop(0.6, "rgba(120,124,110,.25)"); bg.addColorStop(1, "rgba(110,118,108,0)");
    w.fillStyle = bg; w.beginPath(); w.ellipse(0, 0, bl3, hw2 * 0.55, 0, 0, 6.283); w.fill();
    w.restore();
  }
  // sky reflection along the water surface
  w.save(); w.clip(riverWater);
  var refl = w.createLinearGradient(WW, 0, 0, WH);
  refl.addColorStop(0, "rgba(120,180,255,.28)"); refl.addColorStop(0.45, "rgba(120,180,255,.05)"); refl.addColorStop(1, "rgba(120,180,255,.12)");
  w.globalCompositeOperation = "screen"; w.fillStyle = refl; w.fillRect(0, 0, WW, WH);
  w.restore();

  // ---------- 9. Light and grade ----------
  w.globalCompositeOperation = "soft-light";
  var sun = w.createRadialGradient(WW * 0.86, -150, 50, WW * 0.86, -150, 1900);
  sun.addColorStop(0, "rgba(255,245,230,.55)"); sun.addColorStop(1, "rgba(255,245,230,0)");
  w.fillStyle = sun; w.fillRect(0, 0, WW, WH);
  w.globalCompositeOperation = "multiply";
  w.fillStyle = "rgba(14,40,96,.30)"; w.fillRect(0, 0, WW, WH);         // cool blue grade
  var far = w.createLinearGradient(0, 0, 0, WH * 0.55);                   // distance haze (top = far after tilt)
  far.addColorStop(0, "rgba(10,40,110,.55)"); far.addColorStop(1, "rgba(10,40,110,0)");
  w.globalCompositeOperation = "screen"; w.fillStyle = far; w.fillRect(0, 0, WW, WH);
  w.globalCompositeOperation = "source-over";

  // ---------- particles ----------
  var riverDrops = [], canalDrops = [];
  for (i = 0; i < 90; i++) riverDrops.push({ s: R() * river.len, off: rand(-0.7, 0.7), sp: rand(0.3, 0.7), len: rand(1.5, 4.5), a: rand(0.12, 0.4), ph: rand(0, 6.28) });
  canals.forEach(function (c) {
    var count = c.level === 0 ? 6 : 1;
    for (var j = 0; j < count; j++) canalDrops.push({ c: c, s: R() * c.len, sp: rand(0.6, 1.4) * (c.level === 0 ? 1 : 0.7), r: c.level === 0 ? rand(1.3, 2.2) : rand(0.8, 1.2) });
  });

  // ---------- render loop ----------
  var cw = 0, ch = 0, running = true, heroVisible = true, start = performance.now();
  var target = { x: 0, y: 0 }, mouse = { x: 0, y: 0 };
  function resize() {
    var rect = canvas.getBoundingClientRect();
    var cap = window.innerWidth < 760 ? 1400 : 2600;
    var dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    var scaleDown = Math.min(1, cap / Math.max(1, rect.width * dpr));
    cw = Math.max(1, Math.round(rect.width * dpr * scaleDown));
    ch = Math.max(1, Math.round(rect.height * dpr * scaleDown));
    canvas.width = cw; canvas.height = ch;
  }

  function frame(now) {
    var t = (now - start) / 1000;
    mouse.x += (target.x - mouse.x) * 0.04; mouse.y += (target.y - mouse.y) * 0.04;
    var scale = Math.max(cw / WW, ch / WH) * 1.12;
    var driftX = reduceMotion ? 0 : Math.sin(t * 0.035) * 60;
    var driftY = reduceMotion ? 0 : Math.cos(t * 0.028) * 40;
    var ox = (cw - WW * scale) / 2 + (driftX + mouse.x * 40) * scale;
    var oy = (ch - WH * scale) / 2 + (driftY + mouse.y * 30) * scale;

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = "#061522"; ctx.fillRect(0, 0, cw, ch);
    ctx.setTransform(scale, 0, 0, scale, ox, oy);
    ctx.drawImage(world, 0, 0);

    // sky reflection drifting across flooded paddies
    ctx.save(); ctx.clip(paddyPath);
    var sweep = ((t * 55) % (WW + WH * 1.2)) - WH * 0.6;
    var g = ctx.createLinearGradient(sweep, 0, sweep + 560, 560);
    g.addColorStop(0, "rgba(120,180,255,0)"); g.addColorStop(0.5, "rgba(170,210,255,.20)"); g.addColorStop(1, "rgba(120,180,255,0)");
    ctx.globalCompositeOperation = "screen"; ctx.fillStyle = g; ctx.fillRect(0, 0, WW, WH);
    ctx.restore();

    // sun glints on the river, drifting downstream
    ctx.globalCompositeOperation = "screen"; ctx.lineCap = "round";
    riverDrops.forEach(function (d) {
      if (!reduceMotion) d.s = (d.s + d.sp) % river.len;
      var p = river.at(d.s), hw = riverWidth(d.s), x = p.x + p.nx * d.off * hw, y = p.y + p.ny * d.off * hw;
      var flick = Math.max(0, Math.sin(t * 1.7 + d.ph));
      ctx.strokeStyle = "rgba(190,220,255," + (d.a * flick).toFixed(3) + ")"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + p.tx * d.len, y + p.ty * d.len); ctx.stroke();
    });
    // water moving through the canals
    canalDrops.forEach(function (d) {
      if (!reduceMotion) d.s = (d.s + d.sp) % d.c.len;
      var p = d.c.at(d.s), glow = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, d.r * 5);
      glow.addColorStop(0, "rgba(150,200,255,.9)"); glow.addColorStop(1, "rgba(0,125,255,0)");
      ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(p.x, p.y, d.r * 5, 0, 6.283); ctx.fill();
    });
    ctx.globalCompositeOperation = "source-over";

    if (running && !reduceMotion) requestAnimationFrame(frame);
  }

  function play() { if (!running && heroVisible && !document.hidden && !reduceMotion) { running = true; requestAnimationFrame(frame); } }
  function pause() { running = false; }

  resize();
  requestAnimationFrame(frame);
  window.addEventListener("resize", function () { resize(); if (reduceMotion || !running) requestAnimationFrame(frame); });
  window.addEventListener("pointermove", function (e) {
    target.x = (e.clientX / window.innerWidth - 0.5) * -1;
    target.y = (e.clientY / window.innerHeight - 0.5) * -1;
  }, { passive: true });
  document.addEventListener("visibilitychange", function () { if (document.hidden) pause(); else play(); });
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) {
      // animate only while at least 5 % of the hero is on screen (a sliver at the top edge counts as hidden)
      entries.forEach(function (en) { heroVisible = en.intersectionRatio >= 0.05; if (heroVisible) play(); else pause(); });
    }, { threshold: [0, 0.05] }).observe(document.querySelector(".hero"));
  }
})();
