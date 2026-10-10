/*
 * Tidefruit renderer: everything drawn on the canvas. World space is the
 * server's coordinate system; the camera maps it to the screen. Characters are
 * drawn top-down at three-quarter view, feet at their (x, y).
 */
(function () {
  'use strict';
  const R = (window.R = {});
  const TAU = Math.PI * 2;
  let cv, ctx, W = 0, H = 0, DPR = 1;

  R.init = function (canvas) {
    cv = canvas;
    ctx = canvas.getContext('2d');
    R.resize();
  };
  R.resize = function () {
    DPR = Math.min(2, window.devicePixelRatio || 1);
    W = window.innerWidth; H = window.innerHeight;
    cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
    cv.style.width = W + 'px'; cv.style.height = H + 'px';
  };
  R.size = () => ({ W, H });

  // ─── Colour helpers ───────────────────────────────────────────────────────
  const shadeCache = new Map();
  function rgb(hex) {
    const c = parseInt(hex.slice(1), 16);
    return [c >> 16, (c >> 8) & 255, c & 255];
  }
  function shade(hex, amt) {
    const key = hex + amt;
    let v = shadeCache.get(key);
    if (v) return v;
    let [r, g, b] = rgb(hex);
    if (amt < 0) { r *= 1 + amt; g *= 1 + amt; b *= 1 + amt; }
    else { r += (255 - r) * amt; g += (255 - g) * amt; b += (255 - b) * amt; }
    v = `rgb(${r | 0},${g | 0},${b | 0})`;
    shadeCache.set(key, v);
    return v;
  }
  function rgba(hex, a) { const [r, g, b] = rgb(hex); return `rgba(${r},${g},${b},${a})`; }
  R.shade = shade; R.rgba = rgba;

  function rr(c, x, y, w, h, r) {
    c.beginPath();
    c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath();
  }
  function ellipse(c, x, y, rx, ry, fill) { c.beginPath(); c.ellipse(x, y, rx, ry, 0, 0, TAU); c.fillStyle = fill; c.fill(); }
  function circle(c, x, y, r, fill) { c.beginPath(); c.arc(x, y, r, 0, TAU); c.fillStyle = fill; c.fill(); }

  // ─── Islands ──────────────────────────────────────────────────────────────
  const pathCache = new Map();
  function islPath(isl, k) {
    const key = isl.sea + ':' + isl.idx + ':' + k;
    let p = pathCache.get(key);
    if (p) return p;
    p = new Path2D();
    const N = isl.radii.length;
    for (let i = 0; i <= N; i++) {
      const th = (i / N) * TAU, r = isl.radii[i % N] * k;
      const x = isl.x + Math.cos(th) * r, y = isl.y + Math.sin(th) * r;
      if (i === 0) p.moveTo(x, y); else p.lineTo(x, y);
    }
    p.closePath();
    pathCache.set(key, p);
    return p;
  }
  const decorCache = new Map();
  function decorOf(isl) {
    const key = isl.sea + ':' + isl.idx;
    let d = decorCache.get(key);
    if (!d) { d = TF.decorFor(isl); decorCache.set(key, d); }
    return d;
  }
  const blotCache = new Map();
  function blotsOf(isl) {
    const key = isl.sea + ':' + isl.idx;
    let b = blotCache.get(key);
    if (b) return b;
    const rnd = TF.mulberry32(TF.hashStr(isl.name + ':blots'));
    b = [];
    for (let i = 0; i < 18; i++) {
      const p = TF.pointIn(isl, rnd() * TAU, Math.sqrt(rnd()) * 0.75);
      b.push({ x: p.x, y: p.y, rx: 40 + rnd() * 110, ry: 30 + rnd() * 70, a: rnd() * TAU });
    }
    blotCache.set(key, b);
    return b;
  }

  let wavePat = null;
  function wavePattern() {
    if (wavePat) return wavePat;
    const oc = document.createElement('canvas');
    oc.width = oc.height = 256;
    const c = oc.getContext('2d');
    c.strokeStyle = 'rgba(255,255,255,0.10)';
    c.lineWidth = 2;
    const rnd = TF.mulberry32(7);
    for (let i = 0; i < 22; i++) {
      const x = rnd() * 256, y = rnd() * 256, w = 18 + rnd() * 26;
      c.beginPath();
      c.moveTo(x, y);
      c.quadraticCurveTo(x + w / 4, y - 5, x + w / 2, y);
      c.quadraticCurveTo(x + (3 * w) / 4, y + 5, x + w, y);
      c.stroke();
    }
    wavePat = ctx.createPattern(oc, 'repeat');
    return wavePat;
  }

  function drawWater(sea, cam, t, vb) {
    ctx.fillStyle = sea.water[0];
    ctx.fillRect(vb.x0 - 10, vb.y0 - 10, vb.x1 - vb.x0 + 20, vb.y1 - vb.y0 + 20);
    const pat = wavePattern();
    if (pat.setTransform) pat.setTransform(new DOMMatrix().translateSelf((t * 14) % 256, Math.sin(t * 0.5) * 8));
    ctx.fillStyle = pat;
    ctx.fillRect(vb.x0 - 10, vb.y0 - 10, vb.x1 - vb.x0 + 20, vb.y1 - vb.y0 + 20);
    // The edge of the world: deep water fading to black.
    const fog = (x0, y0, x1, y1) => {
      const g = ctx.createLinearGradient(x0, y0, x1, y1);
      g.addColorStop(0, 'rgba(0,8,22,0)');
      g.addColorStop(1, 'rgba(0,8,22,0.85)');
      return g;
    };
    const F = 420, PAD = 2000;
    ctx.fillStyle = fog(F, 0, -F, 0); if (vb.x0 < F) ctx.fillRect(vb.x0 - 10, vb.y0 - 10, F - vb.x0 + 10, vb.y1 - vb.y0 + 20);
    ctx.fillStyle = fog(0, F, 0, -F); if (vb.y0 < F) ctx.fillRect(vb.x0 - 10, vb.y0 - 10, vb.x1 - vb.x0 + 20, F - vb.y0 + 10);
    ctx.fillStyle = fog(sea.w - F, 0, sea.w + F, 0); if (vb.x1 > sea.w - F) ctx.fillRect(sea.w - F, vb.y0 - 10, vb.x1 - sea.w + F + PAD, vb.y1 - vb.y0 + 20);
    ctx.fillStyle = fog(0, sea.h - F, 0, sea.h + F); if (vb.y1 > sea.h - F) ctx.fillRect(vb.x0 - 10, sea.h - F, vb.x1 - vb.x0 + 20, vb.y1 - sea.h + F + PAD);
  }

  function drawIslandGround(sea, isl, t) {
    const bio = TF.BIOMES[isl.biome];
    ctx.save();
    // Shallows and foam.
    ctx.fillStyle = rgba(sea.foam, 0.16);
    ctx.fill(islPath(isl, 1.2));
    ctx.fillStyle = rgba(sea.foam, 0.22 + Math.sin(t * 1.5 + isl.idx) * 0.05);
    ctx.fill(islPath(isl, 1.09));
    ctx.strokeStyle = rgba('#ffffff', 0.45);
    ctx.lineWidth = 4;
    ctx.setLineDash([22, 16]);
    ctx.lineDashOffset = -t * 10;
    ctx.stroke(islPath(isl, 1.035));
    ctx.setLineDash([]);
    ctx.fillStyle = bio.sand;
    ctx.fill(islPath(isl, 1.0));
    ctx.fillStyle = bio.ground;
    const inner = islPath(isl, 0.88);
    ctx.fill(inner);
    ctx.clip(inner);
    ctx.fillStyle = bio.ground2;
    for (const b of blotsOf(isl)) { ctx.beginPath(); ctx.ellipse(b.x, b.y, b.rx, b.ry, b.a, 0, TAU); ctx.fill(); }
    ctx.restore();
    ctx.strokeStyle = shade(bio.ground, -0.18);
    ctx.lineWidth = 3;
    ctx.stroke(inner);
    if (isl.hub) {
      // Town plaza.
      ctx.fillStyle = '#d9cfbd';
      circle(ctx, isl.x, isl.y, isl.R * 0.24, '#d9cfbd');
      ctx.strokeStyle = '#b7aa93';
      ctx.lineWidth = 3;
      for (let i = 1; i <= 3; i++) { ctx.beginPath(); ctx.arc(isl.x, isl.y, isl.R * 0.08 * i, 0, TAU); ctx.stroke(); }
      for (let i = 0; i < 8; i++) {
        const a = (i / 8) * TAU;
        ctx.beginPath();
        ctx.moveTo(isl.x + Math.cos(a) * isl.R * 0.08, isl.y + Math.sin(a) * isl.R * 0.08);
        ctx.lineTo(isl.x + Math.cos(a) * isl.R * 0.24, isl.y + Math.sin(a) * isl.R * 0.24);
        ctx.stroke();
      }
      // A fountain.
      circle(ctx, isl.x, isl.y, 38, '#9fb4c7');
      circle(ctx, isl.x, isl.y, 30, '#4fc3f7');
      circle(ctx, isl.x, isl.y - 4 + Math.sin(t * 4) * 2, 9, '#e1f5fe');
    }
    // Flat decor lives on the ground layer.
    for (const d of decorOf(isl)) if (FLAT[d.k]) drawDecor(d, bio, t);
  }

  // ─── Decor ────────────────────────────────────────────────────────────────
  const FLAT = { lava: 1, flower: 1, shell: 1, reed: 1, bones: 1 };
  function drawDecor(d, bio, t) {
    const c = ctx, x = d.x, y = d.y, s = d.s;
    switch (d.k) {
      case 'palm': {
        ellipse(c, x, y, 22 * s, 8 * s, 'rgba(0,0,0,0.18)');
        c.strokeStyle = '#8d6e4a'; c.lineWidth = 7 * s; c.lineCap = 'round';
        c.beginPath(); c.moveTo(x, y); c.quadraticCurveTo(x + 10 * s, y - 30 * s, x + 4 * s, y - 62 * s); c.stroke();
        const tx = x + 4 * s, ty = y - 62 * s, sway = Math.sin(t * 1.3 + d.v * 9) * 0.08;
        for (let i = 0; i < 6; i++) {
          const a = (i / 6) * TAU + sway + d.v;
          c.save(); c.translate(tx, ty); c.rotate(a);
          c.fillStyle = i % 2 ? '#2e8b3e' : '#3fa34d';
          c.beginPath(); c.ellipse(20 * s, 0, 22 * s, 7 * s, 0, 0, TAU); c.fill();
          c.restore();
        }
        circle(c, tx, ty, 6 * s, '#6d4c2f');
        break;
      }
      case 'tree': case 'bush': {
        const big = d.k === 'tree';
        ellipse(c, x, y, (big ? 34 : 22) * s, (big ? 11 : 8) * s, 'rgba(0,0,0,0.18)');
        if (big) { c.fillStyle = '#6d4c2f'; c.fillRect(x - 5 * s, y - 26 * s, 10 * s, 26 * s); }
        const cy = y - (big ? 44 : 12) * s, r = (big ? 30 : 17) * s;
        const g1 = bio.ground === '#f8bbd0' ? '#ec407a' : shade(bio.ground, -0.35), g2 = shade(bio.ground, -0.15);
        circle(c, x - r * 0.5, cy + r * 0.2, r * 0.75, g1);
        circle(c, x + r * 0.5, cy + r * 0.2, r * 0.75, g1);
        circle(c, x, cy - r * 0.2, r * 0.85, g2);
        circle(c, x - r * 0.25, cy - r * 0.45, r * 0.35, shade(bio.ground, 0.15));
        break;
      }
      case 'pine': {
        ellipse(c, x, y, 24 * s, 8 * s, 'rgba(0,0,0,0.18)');
        c.fillStyle = '#5d4037'; c.fillRect(x - 4 * s, y - 14 * s, 8 * s, 14 * s);
        const snowy = isSnow(bio);
        for (let i = 0; i < 3; i++) {
          const w = (30 - i * 7) * s, by = y - (12 + i * 16) * s;
          c.fillStyle = i % 2 ? '#2e7d4f' : '#2a6e45';
          c.beginPath(); c.moveTo(x - w, by); c.lineTo(x + w, by); c.lineTo(x, by - 30 * s); c.closePath(); c.fill();
          if (snowy) { c.fillStyle = '#ffffff'; c.beginPath(); c.moveTo(x - w * 0.35, by - 19 * s); c.lineTo(x + w * 0.35, by - 19 * s); c.lineTo(x, by - 30 * s); c.closePath(); c.fill(); }
        }
        break;
      }
      case 'rock': {
        ellipse(c, x, y, 22 * s, 7 * s, 'rgba(0,0,0,0.2)');
        c.fillStyle = '#8a8f96';
        c.beginPath(); c.moveTo(x - 20 * s, y); c.lineTo(x - 14 * s, y - 16 * s); c.lineTo(x + 2 * s, y - 22 * s); c.lineTo(x + 18 * s, y - 10 * s); c.lineTo(x + 20 * s, y); c.closePath(); c.fill();
        c.fillStyle = '#a9aeb5';
        c.beginPath(); c.moveTo(x - 12 * s, y - 14 * s); c.lineTo(x + 2 * s, y - 20 * s); c.lineTo(x + 6 * s, y - 10 * s); c.closePath(); c.fill();
        break;
      }
      case 'cactus': {
        ellipse(c, x, y, 14 * s, 5 * s, 'rgba(0,0,0,0.2)');
        c.fillStyle = '#4c9a52';
        rr(c, x - 6 * s, y - 40 * s, 12 * s, 40 * s, 6 * s); c.fill();
        rr(c, x - 18 * s, y - 30 * s, 8 * s, 18 * s, 4 * s); c.fill();
        rr(c, x + 10 * s, y - 34 * s, 8 * s, 16 * s, 4 * s); c.fill();
        c.fillRect(x - 12 * s, y - 16 * s, 8 * s, 5 * s); c.fillRect(x + 4 * s, y - 22 * s, 8 * s, 5 * s);
        break;
      }
      case 'hut': {
        ellipse(c, x, y + 2, 40 * s, 12 * s, 'rgba(0,0,0,0.2)');
        c.fillStyle = '#c8a26b'; c.fillRect(x - 30 * s, y - 34 * s, 60 * s, 34 * s);
        c.fillStyle = '#6d4c2f'; c.fillRect(x - 8 * s, y - 20 * s, 16 * s, 20 * s);
        c.fillStyle = '#a1662f';
        c.beginPath(); c.moveTo(x - 38 * s, y - 32 * s); c.lineTo(x, y - 62 * s); c.lineTo(x + 38 * s, y - 32 * s); c.closePath(); c.fill();
        c.strokeStyle = '#7a4a20'; c.lineWidth = 2; c.stroke();
        break;
      }
      case 'crate': case 'barrel': {
        ellipse(c, x, y, 18 * s, 6 * s, 'rgba(0,0,0,0.2)');
        if (d.k === 'crate') {
          c.fillStyle = '#a0703d'; c.fillRect(x - 15 * s, y - 28 * s, 30 * s, 28 * s);
          c.strokeStyle = '#6d4824'; c.lineWidth = 3 * s; c.strokeRect(x - 15 * s, y - 28 * s, 30 * s, 28 * s);
          c.beginPath(); c.moveTo(x - 15 * s, y - 28 * s); c.lineTo(x + 15 * s, y); c.stroke();
        } else {
          c.fillStyle = '#8d5a2b'; rr(c, x - 13 * s, y - 30 * s, 26 * s, 30 * s, 8 * s); c.fill();
          c.fillStyle = '#5d3a1a'; c.fillRect(x - 13 * s, y - 24 * s, 26 * s, 3 * s); c.fillRect(x - 13 * s, y - 9 * s, 26 * s, 3 * s);
        }
        break;
      }
      case 'pillar': {
        ellipse(c, x, y, 18 * s, 6 * s, 'rgba(0,0,0,0.2)');
        const col = isDark(bio) ? '#6e6a85' : '#e8e2d2';
        c.fillStyle = col; c.fillRect(x - 10 * s, y - 60 * s, 20 * s, 60 * s);
        c.fillStyle = shade(col.length === 7 ? col : '#e8e2d2', -0.12); c.fillRect(x - 14 * s, y - 64 * s, 28 * s, 8 * s); c.fillRect(x - 14 * s, y - 6 * s, 28 * s, 6 * s);
        c.fillStyle = 'rgba(0,0,0,0.08)'; c.fillRect(x + 2 * s, y - 56 * s, 4 * s, 50 * s);
        break;
      }
      case 'ruin': case 'wall': {
        ellipse(c, x, y, 34 * s, 8 * s, 'rgba(0,0,0,0.2)');
        c.fillStyle = d.k === 'wall' ? '#6f757c' : '#b3a98f';
        c.beginPath(); c.moveTo(x - 30 * s, y); c.lineTo(x - 30 * s, y - 34 * s); c.lineTo(x - 14 * s, y - 40 * s); c.lineTo(x - 4 * s, y - 26 * s); c.lineTo(x + 10 * s, y - 32 * s); c.lineTo(x + 30 * s, y - 18 * s); c.lineTo(x + 30 * s, y); c.closePath(); c.fill();
        c.strokeStyle = 'rgba(0,0,0,0.18)'; c.lineWidth = 2;
        for (let i = 1; i < 4; i++) { c.beginPath(); c.moveTo(x - 30 * s, y - i * 9 * s); c.lineTo(x + 30 * s, y - i * 9 * s); c.stroke(); }
        break;
      }
      case 'tomb': {
        ellipse(c, x, y, 16 * s, 5 * s, 'rgba(0,0,0,0.25)');
        c.fillStyle = '#8e939a'; rr(c, x - 12 * s, y - 30 * s, 24 * s, 30 * s, 10 * s); c.fill();
        c.fillStyle = '#6c7178'; c.fillRect(x - 2 * s, y - 24 * s, 4 * s, 14 * s); c.fillRect(x - 7 * s, y - 20 * s, 14 * s, 4 * s);
        break;
      }
      case 'crystal': {
        const col = cryColor(bio, d.v);
        ellipse(c, x, y, 18 * s, 6 * s, 'rgba(0,0,0,0.2)');
        c.save(); c.globalCompositeOperation = 'lighter'; circle(c, x, y - 18 * s, 26 * s, rgba(col, 0.12 + Math.sin(t * 2 + d.v * 6) * 0.05)); c.restore();
        for (const [ox, h, w] of [[-8, 34, 9], [6, 46, 11], [16, 26, 7]]) {
          c.fillStyle = col;
          c.beginPath(); c.moveTo(x + (ox - w) * s, y); c.lineTo(x + ox * s, y - h * s); c.lineTo(x + (ox + w) * s, y); c.closePath(); c.fill();
          c.fillStyle = 'rgba(255,255,255,0.35)';
          c.beginPath(); c.moveTo(x + (ox - w * 0.2) * s, y - 4 * s); c.lineTo(x + ox * s, y - h * s); c.lineTo(x + (ox + w * 0.5) * s, y - 4 * s); c.closePath(); c.fill();
        }
        break;
      }
      case 'coral': {
        c.strokeStyle = d.v > 0.5 ? '#ff7a9c' : '#ff9f68'; c.lineWidth = 5 * s; c.lineCap = 'round';
        for (let i = -2; i <= 2; i++) { c.beginPath(); c.moveTo(x, y); c.quadraticCurveTo(x + i * 8 * s, y - 14 * s, x + i * 12 * s, y - (22 + Math.abs(i) * -3) * s); c.stroke(); }
        break;
      }
      case 'shell': circle(c, x, y, 6 * s, '#fff3e0'); c.strokeStyle = '#ffab91'; c.lineWidth = 1.5; c.beginPath(); c.arc(x, y, 3 * s, 0, 5); c.stroke(); break;
      case 'mush': {
        ellipse(c, x, y, 14 * s, 5 * s, 'rgba(0,0,0,0.2)');
        c.fillStyle = '#f5f0e6'; c.fillRect(x - 4 * s, y - 14 * s, 8 * s, 14 * s);
        const cap = isl_mushColor(bio);
        c.fillStyle = cap; c.beginPath(); c.ellipse(x, y - 14 * s, 15 * s, 10 * s, 0, Math.PI, 0); c.fill();
        circle(c, x - 5 * s, y - 18 * s, 2.5 * s, '#fff'); circle(c, x + 6 * s, y - 16 * s, 2 * s, '#fff');
        break;
      }
      case 'flower': {
        const cols = ['#ff5c8a', '#ffd54f', '#ffffff', '#ba68c8', '#ff8a65'];
        for (let i = 0; i < 5; i++) {
          const a = d.v * 20 + i * 1.3, px = x + Math.cos(a) * 14 * s, py = y + Math.sin(a) * 9 * s;
          circle(c, px, py, 4 * s, cols[(i + Math.floor(d.v * 5)) % 5]);
          circle(c, px, py, 1.5 * s, '#fff59d');
        }
        break;
      }
      case 'lamp': case 'torch': {
        ellipse(c, x, y, 9 * s, 3 * s, 'rgba(0,0,0,0.25)');
        c.fillStyle = d.k === 'lamp' ? '#37474f' : '#6d4c2f'; c.fillRect(x - 2.5 * s, y - 40 * s, 5 * s, 40 * s);
        const fl = d.k === 'lamp' ? '#ffe082' : '#ff9100';
        c.save(); c.globalCompositeOperation = 'lighter';
        circle(c, x, y - 44 * s, (18 + Math.sin(t * 9 + d.v * 30) * 2) * s, rgba(fl, 0.25));
        c.restore();
        circle(c, x, y - 44 * s, 6 * s, fl);
        break;
      }
      case 'lava': {
        c.save(); c.globalCompositeOperation = 'lighter';
        ellipse(c, x, y, 40 * s, 16 * s, rgba('#ff6d00', 0.35 + Math.sin(t * 2 + d.v * 9) * 0.1));
        c.restore();
        ellipse(c, x, y, 30 * s, 11 * s, '#ff5722');
        ellipse(c, x - 6 * s, y - 2 * s, 12 * s, 4 * s, '#ffab40');
        break;
      }
      case 'deadtree': {
        ellipse(c, x, y, 18 * s, 6 * s, 'rgba(0,0,0,0.2)');
        c.strokeStyle = '#4e3d34'; c.lineWidth = 6 * s; c.lineCap = 'round';
        c.beginPath(); c.moveTo(x, y); c.lineTo(x, y - 44 * s); c.stroke();
        c.lineWidth = 3.5 * s;
        c.beginPath(); c.moveTo(x, y - 26 * s); c.lineTo(x - 16 * s, y - 42 * s); c.moveTo(x, y - 34 * s); c.lineTo(x + 14 * s, y - 50 * s); c.moveTo(x, y - 44 * s); c.lineTo(x - 6 * s, y - 58 * s); c.stroke();
        break;
      }
      case 'cloud': {
        c.globalAlpha = 0.85;
        circle(c, x - 18 * s, y - 10 * s, 16 * s, '#ffffff'); circle(c, x, y - 18 * s, 20 * s, '#ffffff'); circle(c, x + 20 * s, y - 10 * s, 15 * s, '#f3f7ff');
        c.globalAlpha = 1;
        break;
      }
      case 'candy': {
        ellipse(c, x, y, 10 * s, 4 * s, 'rgba(0,0,0,0.2)');
        c.fillStyle = '#ffffff'; c.fillRect(x - 2 * s, y - 34 * s, 4 * s, 34 * s);
        circle(c, x, y - 40 * s, 13 * s, d.v > 0.5 ? '#ff80ab' : '#80deea');
        c.strokeStyle = '#ffffff'; c.lineWidth = 3 * s; c.beginPath(); c.arc(x, y - 40 * s, 7 * s, 0, 4.5); c.stroke();
        break;
      }
      case 'snowman': {
        ellipse(c, x, y, 16 * s, 5 * s, 'rgba(0,0,0,0.15)');
        circle(c, x, y - 12 * s, 14 * s, '#ffffff'); circle(c, x, y - 32 * s, 10 * s, '#f5f9fc');
        circle(c, x - 3 * s, y - 34 * s, 1.5 * s, '#263238'); circle(c, x + 3 * s, y - 34 * s, 1.5 * s, '#263238');
        c.fillStyle = '#ff7043'; c.fillRect(x, y - 32 * s, 7 * s, 2.5 * s);
        break;
      }
      case 'cannon': {
        ellipse(c, x, y, 22 * s, 7 * s, 'rgba(0,0,0,0.2)');
        c.fillStyle = '#6d4c2f'; c.fillRect(x - 14 * s, y - 12 * s, 28 * s, 12 * s);
        c.fillStyle = '#37474f'; rr(c, x - 6 * s, y - 24 * s, 34 * s, 13 * s, 6 * s); c.fill();
        circle(c, x - 8 * s, y - 4 * s, 6 * s, '#4e342e'); circle(c, x + 8 * s, y - 4 * s, 6 * s, '#4e342e');
        break;
      }
      case 'flag': case 'mast': {
        const tall = d.k === 'mast' ? 90 : 60;
        ellipse(c, x, y, 10 * s, 3 * s, 'rgba(0,0,0,0.2)');
        c.fillStyle = '#5d4037'; c.fillRect(x - 2.5 * s, y - tall * s, 5 * s, tall * s);
        const wave = Math.sin(t * 4 + d.v * 10) * 4 * s;
        c.fillStyle = d.k === 'mast' ? '#efe6d2' : '#1565c0';
        c.beginPath(); c.moveTo(x + 2 * s, y - tall * s); c.quadraticCurveTo(x + 22 * s, y - (tall - 8) * s + wave, x + 40 * s, y - (tall - 4) * s); c.lineTo(x + 40 * s, y - (tall - 30) * s); c.quadraticCurveTo(x + 22 * s, y - (tall - 34) * s - wave, x + 2 * s, y - (tall - 30) * s); c.closePath(); c.fill();
        if (d.k === 'flag') { circle(c, x + 21 * s, y - (tall - 17) * s, 5 * s, '#ffffff'); }
        break;
      }
      case 'reed': {
        c.strokeStyle = '#7c8f3c'; c.lineWidth = 2;
        for (let i = -3; i <= 3; i++) { c.beginPath(); c.moveTo(x + i * 3 * s, y); c.lineTo(x + i * 5 * s + Math.sin(t * 2 + i) * 2, y - (16 + (i & 1) * 6) * s); c.stroke(); }
        break;
      }
      case 'bones': {
        c.strokeStyle = '#efe9dc'; c.lineWidth = 4 * s; c.lineCap = 'round';
        for (let i = 0; i < 4; i++) { c.beginPath(); c.arc(x + i * 10 * s - 15 * s, y, 12 * s, Math.PI * 1.1, Math.PI * 1.9); c.stroke(); }
        c.beginPath(); c.moveTo(x - 24 * s, y); c.lineTo(x + 24 * s, y); c.stroke();
        break;
      }
    }
  }
  function isSnow(bio) { return bio.ground === '#f3f7fb' || bio.ground === '#bfe3f2'; }
  function isDark(bio) { return ['#3d3a4c', '#1d1533', '#2c355a', '#2a2a2e', '#3d4a8c'].includes(bio.ground); }
  function cryColor(bio, v) {
    if (bio.ground === '#bfe3f2') return '#b3e5fc';
    if (bio.ground === '#4c3a34' || bio.ground === '#2a2a2e') return '#ff7043';
    if (bio.ground === '#6d5a8a' || bio.ground === '#1d1533') return '#b388ff';
    if (bio.ground === '#3d4a8c') return '#fff59d';
    return v > 0.5 ? '#ea80fc' : '#80d8ff';
  }
  function isl_mushColor(bio) { return bio.ground === '#f8bbd0' ? '#ff80ab' : bio.ground === '#6d5a8a' ? '#9c27b0' : '#e53935'; }

  // ─── Characters ───────────────────────────────────────────────────────────
  const HATS = {
    1: (c, hc) => { c.fillStyle = hc; rr(c, -11, -50, 22, 7, 3); c.fill(); c.fillRect(8, -48, 7, 4); },
    2: (c, hc, f) => { c.fillStyle = hc; rr(c, -11, -53, 22, 9, 4); c.fill(); c.fillRect(f > 0 ? 4 : -16, -46, 12, 3); },
    3: (c, hc) => { c.fillStyle = hc; rr(c, -12, -54, 24, 12, 6); c.fill(); c.fillStyle = 'rgba(0,0,0,0.35)'; c.fillRect(-10, -44, 20, 3); },
    4: (c, hc) => { c.fillStyle = hc; c.beginPath(); c.moveTo(-17, -47); c.quadraticCurveTo(0, -60, 17, -47); c.lineTo(10, -53); c.lineTo(0, -64); c.lineTo(-10, -53); c.closePath(); c.fill(); circle(c, 0, -55, 3, '#fff'); },
    5: (c, hc) => { c.fillStyle = hc; c.beginPath(); c.moveTo(-10, -48); c.lineTo(-10, -58); c.lineTo(-5, -53); c.lineTo(0, -61); c.lineTo(5, -53); c.lineTo(10, -58); c.lineTo(10, -48); c.closePath(); c.fill(); circle(c, 0, -55, 2, '#e53935'); },
    6: (c, hc) => { c.fillStyle = hc; c.beginPath(); c.moveTo(-9, -48); c.quadraticCurveTo(-18, -54, -14, -64); c.quadraticCurveTo(-11, -55, -4, -50); c.moveTo(9, -48); c.quadraticCurveTo(18, -54, 14, -64); c.quadraticCurveTo(11, -55, 4, -50); c.fill(); },
    7: (c, hc) => { c.fillStyle = hc; c.beginPath(); c.moveTo(-13, -30); c.lineTo(-13, -46); c.quadraticCurveTo(0, -64, 13, -46); c.lineTo(13, -30); c.lineTo(9, -30); c.lineTo(9, -44); c.lineTo(-9, -44); c.lineTo(-9, -30); c.closePath(); c.fill(); },
    8: (c, hc, f, t) => { c.strokeStyle = hc; c.lineWidth = 3; c.beginPath(); c.ellipse(0, -60 + Math.sin(t * 3) * 1.5, 11, 4, 0, 0, TAU); c.stroke(); },
    9: (c, hc) => { c.fillStyle = hc; c.fillRect(-14, -50, 28, 4); c.fillRect(-9, -66, 18, 17); c.fillStyle = '#c62828'; c.fillRect(-9, -54, 18, 3); },
  };

  // o: { size, ang, t, moving, flash, weapon: {kind, color}, alpha, boat, aura, trans, transColor, fruitKey }
  function drawCharacter(x, y, L, o) {
    const c = ctx;
    const s = o.size || 1;
    const t = o.t;
    const face = Math.cos(o.ang) < 0 ? -1 : 1;
    const moving = o.moving;
    const step = moving ? Math.sin(t * 13) : 0;
    const bob = moving ? Math.abs(Math.sin(t * 13)) * -2 : Math.sin(t * 2.2) * 0.7;
    c.save();
    c.translate(x, y);
    if (o.alpha !== undefined) c.globalAlpha = o.alpha;
    // Ground shadow / boss aura
    if (o.aura) {
      c.save(); c.globalCompositeOperation = 'lighter';
      const g = c.createRadialGradient(0, 0, 4, 0, 0, 34 * s);
      g.addColorStop(0, rgba(o.aura, 0.5)); g.addColorStop(1, rgba(o.aura, 0));
      c.fillStyle = g; c.beginPath(); c.ellipse(0, 0, 40 * s, 16 * s, 0, 0, TAU); c.fill();
      c.restore();
    }
    if (o.boat) drawBoat(c, s, o.boatAng, t);
    else ellipse(c, 0, 0, 16 * s, 6 * s, 'rgba(0,0,0,0.25)');
    c.scale(s, s);
    if (o.trans) drawTransformBack(c, o, t, face);
    const form = L.form;
    if (form === 'b') { drawBeast(c, L, o, t, face, step); c.restore(); return; }
    const floaty = form === 's';
    if (floaty) c.translate(0, -6 + Math.sin(t * 3) * 3);
    const skin = L.skin, shirt = L.shirt, pants = L.pants;
    const heavy = form === 'g' || form === 'a';
    // Legs
    if (!o.boat && !floaty) {
      c.fillStyle = shade(pants, -0.15);
      rr(c, -9, -13 + step * 2, 7, 13 - step * 2, 3); c.fill();
      rr(c, 2, -13 - step * 2, 7, 13 + step * 2, 3); c.fill();
    } else if (floaty) {
      c.fillStyle = rgba(shirt, 0.7);
      c.beginPath(); c.moveTo(-11, -14); c.quadraticCurveTo(-6 + Math.sin(t * 6) * 4, 4, 0, 6); c.quadraticCurveTo(6 + Math.sin(t * 6 + 1) * 4, 4, 11, -14); c.closePath(); c.fill();
    }
    // Back arm
    const armSwing = moving ? step * 5 : 0;
    c.fillStyle = shade(skin, -0.15);
    rr(c, -face * 14 - 3, -28 + armSwing * 0.5 + bob, 6, 14, 3); c.fill();
    // Torso
    const tw = heavy ? 28 : 22, th = heavy ? 22 : 19;
    c.fillStyle = shirt;
    rr(c, -tw / 2, -12 - th + bob, tw, th, 5); c.fill();
    c.fillStyle = shade(shirt, -0.2);
    c.fillRect(-tw / 2 + 2, -16 + bob, tw - 4, 3);
    if (form === 'g') { c.fillStyle = shade(shirt, 0.25); c.fillRect(-8, -28 + bob, 6, 6); c.fillRect(3, -22 + bob, 5, 5); }
    // Head
    const hy = -12 - th - 16 + bob;
    if (form === 'a') {
      circle(c, 0, hy + 8, 12, skin);
      ellipse(c, face * 3, hy + 11, 7, 5.5, shade(skin, 0.35));
    } else if (form === 'g') {
      c.fillStyle = skin; rr(c, -11, hy, 22, 17, 3); c.fill();
    } else {
      c.fillStyle = skin; rr(c, -10, hy, 20, 18, 6); c.fill();
      if (form === 'f') { c.fillStyle = shade(skin, -0.25); c.beginPath(); c.moveTo(-3, hy + 1); c.lineTo(0, hy - 9); c.lineTo(5, hy + 1); c.fill(); }
    }
    // Eyes look where the character aims.
    const ex = Math.cos(o.ang) * 3, ey = Math.sin(o.ang) * 2;
    const eyeCol = form === 'g' || form === 's' ? (o.eyeGlow || '#ffeb3b') : '#1b1b1b';
    if (form === 'g' || form === 's') { c.save(); c.globalCompositeOperation = 'lighter'; circle(c, -4 + ex, hy + 8 + ey, 4, rgba(eyeCol, 0.4)); circle(c, 4 + ex, hy + 8 + ey, 4, rgba(eyeCol, 0.4)); c.restore(); }
    c.fillStyle = eyeCol;
    c.fillRect(-5 + ex, hy + 6 + ey, 3, 4);
    c.fillRect(3 + ex, hy + 6 + ey, 3, 4);
    if (L.hat && HATS[L.hat]) { c.save(); c.translate(0, bob); HATS[L.hat](c, L.hatColor || '#333', face, t); c.restore(); }
    // Front arm + weapon
    c.save();
    c.translate(face * 12, -24 + bob);
    const wa = o.weapon && o.weapon.kind !== 'style' ? o.ang : face > 0 ? 0.4 : Math.PI - 0.4;
    c.rotate(wa + (o.swing || 0));
    drawWeapon(c, o.weapon, t, o);
    c.fillStyle = skin;
    rr(c, -3, -3, 12, 6, 3); c.fill();
    c.restore();
    if (o.flash) { c.globalCompositeOperation = 'lighter'; c.globalAlpha = o.flash; c.fillStyle = '#ffffff'; c.fillRect(-16, hy - 4, 32, -hy + 4); }
    c.restore();
  }
  R.drawCharacter = drawCharacter;

  function drawWeapon(c, w, t) {
    if (!w) return;
    if (w.kind === 'sword') {
      c.fillStyle = '#5d4037'; c.fillRect(6, -2, 8, 4);
      c.fillStyle = '#9e9e9e'; c.fillRect(13, -6, 3, 12);
      c.fillStyle = w.color || '#cfd8dc';
      c.beginPath(); c.moveTo(16, -3); c.lineTo(48, -2); c.lineTo(54, 0); c.lineTo(48, 2); c.lineTo(16, 3); c.closePath(); c.fill();
      c.fillStyle = 'rgba(255,255,255,0.55)'; c.fillRect(17, -2, 30, 1.2);
    } else if (w.kind === 'gun') {
      c.fillStyle = shade(w.color || '#6d4c41', -0.2); rr(c, 4, -3, 12, 8, 2); c.fill();
      c.fillStyle = '#37474f'; c.fillRect(10, -4, 26, 5);
      c.fillStyle = w.color || '#6d4c41'; c.fillRect(8, -5, 8, 3);
    } else if (w.kind === 'fruit') {
      c.save(); c.globalCompositeOperation = 'lighter';
      circle(c, 12, 0, 9 + Math.sin(t * 8) * 1.5, rgba(w.color, 0.45));
      circle(c, 12, 0, 4, rgba('#ffffff', 0.7));
      c.restore();
    }
  }

  function drawBoat(c, s, ang, t) {
    c.save();
    c.rotate((ang || 0));
    ellipse(c, 0, 4, 40 * s, 15 * s, 'rgba(0,0,0,0.2)');
    c.fillStyle = '#7b4f2c';
    c.beginPath(); c.moveTo(-34 * s, -12 * s); c.lineTo(26 * s, -12 * s); c.quadraticCurveTo(44 * s, 0, 26 * s, 12 * s); c.lineTo(-34 * s, 12 * s); c.quadraticCurveTo(-40 * s, 0, -34 * s, -12 * s); c.fill();
    c.fillStyle = '#b07a48';
    c.beginPath(); c.moveTo(-28 * s, -7 * s); c.lineTo(22 * s, -7 * s); c.quadraticCurveTo(34 * s, 0, 22 * s, 7 * s); c.lineTo(-28 * s, 7 * s); c.closePath(); c.fill();
    c.strokeStyle = '#5d3a1a'; c.lineWidth = 2;
    for (let i = -18; i < 20; i += 10) { c.beginPath(); c.moveTo(i * s, -7 * s); c.lineTo(i * s, 7 * s); c.stroke(); }
    c.restore();
  }

  function drawBeast(c, L, o, t, face, step) {
    const body = L.shirt, dark = L.pants, skin = L.skin;
    c.save();
    c.scale(face, 1);
    // legs
    c.fillStyle = shade(dark, -0.1);
    for (const lx of [-14, -6, 8, 15]) { rr(c, lx, -12 + (lx % 2 ? step : -step) * 2, 6, 12, 3); c.fill(); }
    // tail
    c.strokeStyle = body; c.lineWidth = 5; c.lineCap = 'round';
    c.beginPath(); c.moveTo(-18, -20); c.quadraticCurveTo(-30, -26 + Math.sin(t * 6) * 4, -34, -36); c.stroke();
    // body
    c.fillStyle = body; c.beginPath(); c.ellipse(0, -20, 22, 12, 0, 0, TAU); c.fill();
    c.fillStyle = shade(body, 0.2); c.beginPath(); c.ellipse(2, -16, 14, 5, 0, 0, TAU); c.fill();
    // head
    c.fillStyle = skin; c.beginPath(); c.ellipse(22, -30, 11, 9, 0.2, 0, TAU); c.fill();
    c.beginPath(); c.moveTo(16, -36); c.lineTo(18, -46); c.lineTo(23, -38); c.fill();
    c.fillStyle = shade(skin, -0.2); c.beginPath(); c.ellipse(31, -28, 6, 4, 0.2, 0, TAU); c.fill();
    c.fillStyle = '#ffeb3b'; c.fillRect(22, -33, 3, 3);
    if (L.hat === 6) { c.fillStyle = L.hatColor; c.beginPath(); c.moveTo(14, -36); c.lineTo(10, -50); c.lineTo(19, -38); c.fill(); }
    c.restore();
    if (o.flash) { c.globalCompositeOperation = 'lighter'; c.globalAlpha = o.flash; ellipse(c, 0, -22, 30, 16, '#ffffff'); }
  }

  // Beast-fruit transformations grow wings or tails behind the body.
  function drawTransformBack(c, o, t, face) {
    const col = o.transColor || '#ffffff';
    const k = o.fruitKey;
    c.save(); c.globalCompositeOperation = 'lighter';
    circle(c, 0, -26, 34, rgba(col, 0.18 + Math.sin(t * 6) * 0.05));
    c.restore();
    if (k === 'phoenix' || k === 'falcon' || k === 'dragon') {
      const flap = Math.sin(t * 9) * 0.35;
      for (const side of [-1, 1]) {
        c.save(); c.translate(side * 6, -30); c.rotate(side * (0.5 + flap)); c.scale(side, 1);
        c.fillStyle = k === 'dragon' ? shade(col, -0.3) : rgba(col, 0.85);
        c.beginPath(); c.moveTo(0, 0); c.quadraticCurveTo(26, -30, 46, -14); c.lineTo(34, -6); c.lineTo(40, 4); c.lineTo(24, 2); c.lineTo(26, 12); c.closePath(); c.fill();
        c.restore();
      }
    } else if (k === 'leopard' || k === 'kitsune') {
      const n = k === 'kitsune' ? 5 : 1;
      for (let i = 0; i < n; i++) {
        const a = -face * (0.6 + (i - (n - 1) / 2) * 0.35) + Math.sin(t * 4 + i) * 0.1;
        c.save(); c.translate(-face * 6, -16); c.rotate(a);
        c.fillStyle = k === 'kitsune' ? rgba(col, 0.8) : '#ffca28';
        c.beginPath(); c.ellipse(0, -18, 6, 18, 0, 0, TAU); c.fill();
        if (k === 'kitsune') circle(c, 0, -32, 4, '#ffffff');
        c.restore();
      }
    } else if (k === 'venom') {
      for (let i = 0; i < 3; i++) {
        const a = -0.9 + i * 0.9 + Math.sin(t * 3 + i) * 0.15;
        c.save(); c.translate(0, -26); c.rotate(a);
        c.fillStyle = rgba('#7e57c2', 0.9); c.beginPath(); c.ellipse(0, -26, 7, 18, 0, 0, TAU); c.fill();
        circle(c, 0, -42, 7, '#76ff03');
        c.restore();
      }
    }
  }

  // Sea serpents: a chain of segments swimming in a sine.
  function drawSerpent(x, y, L, size, ang, t, flash) {
    const c = ctx;
    const n = 9, seg = 16 * size;
    const pts = [];
    for (let i = 0; i < n; i++) {
      const back = i * seg * 0.9;
      const wob = Math.sin(t * 3 - i * 0.7) * seg * 0.6;
      pts.push([x - Math.cos(ang) * back - Math.sin(ang) * wob, y - Math.sin(ang) * back + Math.cos(ang) * wob]);
    }
    c.save();
    c.fillStyle = 'rgba(0,0,0,0.25)';
    for (let i = n - 1; i >= 0; i--) { c.beginPath(); c.ellipse(pts[i][0], pts[i][1] + 10, seg * (1 - i / (n * 1.4)), seg * 0.45, 0, 0, TAU); c.fill(); }
    for (let i = n - 1; i >= 0; i--) {
      const r = seg * (1 - i / (n * 1.4));
      circle(c, pts[i][0], pts[i][1] - r * 0.4, r, i % 2 ? L.shirt : shade(L.shirt, 0.12));
      circle(c, pts[i][0], pts[i][1] - r * 0.8, r * 0.35, L.hatColor || L.skin);
    }
    const hx = pts[0][0] + Math.cos(ang) * seg * 0.6, hy = pts[0][1] + Math.sin(ang) * seg * 0.6 - seg * 0.5;
    circle(c, hx, hy, seg * 1.15, L.skin);
    circle(c, hx + Math.cos(ang) * seg * 0.5 - seg * 0.35, hy - seg * 0.3, seg * 0.22, '#ffeb3b');
    circle(c, hx + Math.cos(ang) * seg * 0.5 + seg * 0.35, hy - seg * 0.3, seg * 0.22, '#ffeb3b');
    if (flash) { c.globalCompositeOperation = 'lighter'; c.globalAlpha = flash; circle(c, hx, hy, seg * 1.2, '#ffffff'); }
    c.restore();
  }

  // ─── Fruit icon ───────────────────────────────────────────────────────────
  const iconCache = new Map();
  R.fruitIcon = function (fr, size) {
    const key = fr.id + ':' + size;
    if (iconCache.has(key)) return iconCache.get(key);
    const oc = document.createElement('canvas');
    oc.width = oc.height = size;
    const c = oc.getContext('2d');
    const s = size / 64;
    c.scale(s, s);
    const g = c.createRadialGradient(24, 26, 4, 32, 36, 28);
    g.addColorStop(0, shade(fr.color, 0.45)); g.addColorStop(1, shade(fr.color, -0.15));
    c.fillStyle = g; c.beginPath(); c.arc(32, 36, 24, 0, TAU); c.fill();
    c.strokeStyle = fr.color2 === '#ffffff' || fr.color2 === '#000000' ? shade(fr.color, -0.4) : fr.color2;
    c.lineWidth = 3.2; c.lineCap = 'round';
    for (const [cx, cy, r] of [[24, 30, 7], [40, 32, 6], [30, 46, 7], [44, 46, 5], [18, 44, 4]]) {
      c.beginPath(); c.arc(cx, cy, r, 0.4, TAU * 0.85); c.stroke();
    }
    c.fillStyle = '#5d4037'; c.fillRect(30, 6, 4, 10);
    c.fillStyle = '#43a047'; c.beginPath(); c.ellipse(41, 10, 9, 4, -0.4, 0, TAU); c.fill();
    c.fillStyle = 'rgba(255,255,255,0.45)'; c.beginPath(); c.ellipse(22, 24, 6, 3.5, -0.6, 0, TAU); c.fill();
    const url = oc.toDataURL();
    iconCache.set(key, url);
    return url;
  };

  // ─── Particles ────────────────────────────────────────────────────────────
  const parts = [];
  function particle(x, y, vx, vy, life, size, color, add, grav) {
    if (parts.length > 1800) parts.shift();
    parts.push({ x, y, vx, vy, life, max: life, size, color, add: add !== false, g: grav || 0 });
  }
  R.particle = particle;
  function burst(x, y, n, color, speed, size, life, grav) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * TAU, v = speed * (0.3 + Math.random() * 0.7);
      particle(x, y, Math.cos(a) * v, Math.sin(a) * v, life * (0.6 + Math.random() * 0.6), size * (0.6 + Math.random() * 0.8), color, true, grav);
    }
  }
  R.burst = burst;
  function drawParticles(dt) {
    const c = ctx;
    for (let i = parts.length - 1; i >= 0; i--) {
      const p = parts[i];
      p.life -= dt;
      if (p.life <= 0) { parts.splice(i, 1); continue; }
      p.x += p.vx * dt; p.y += p.vy * dt; p.vy += p.g * dt;
      p.vx *= 1 - dt * 2; p.vy *= 1 - dt * 2;
      const k = p.life / p.max;
      c.globalCompositeOperation = p.add ? 'lighter' : 'source-over';
      c.globalAlpha = Math.min(1, k * 1.5);
      circle(c, p.x, p.y, p.size * (0.4 + k * 0.6), p.color);
    }
    c.globalAlpha = 1;
    c.globalCompositeOperation = 'source-over';
  }

  // ─── Effects ──────────────────────────────────────────────────────────────
  function drawProjShape(p, t) {
    const c = ctx;
    const a = Math.atan2(p.vy, p.vx);
    const col = p.c || '#ffffff';
    c.save();
    c.translate(p.x, p.y);
    c.globalCompositeOperation = 'lighter';
    const glow = c.createRadialGradient(0, 0, 0, 0, 0, p.r * 2.2);
    glow.addColorStop(0, rgba(col, 0.6)); glow.addColorStop(1, rgba(col, 0));
    c.fillStyle = glow; c.beginPath(); c.arc(0, 0, p.r * 2.2, 0, TAU); c.fill();
    c.globalCompositeOperation = 'source-over';
    c.rotate(a);
    switch (p.sh) {
      case 'bullet': c.fillStyle = '#fff8e1'; rr(c, -p.r * 2.4, -p.r * 0.45, p.r * 3, p.r * 0.9, p.r * 0.45); c.fill(); break;
      case 'spear': case 'feather':
        c.fillStyle = p.sh === 'feather' ? col : '#ffffff';
        c.beginPath(); c.moveTo(p.r * 1.8, 0); c.lineTo(-p.r * 1.6, -p.r * 0.5); c.lineTo(-p.r * 1.2, 0); c.lineTo(-p.r * 1.6, p.r * 0.5); c.closePath(); c.fill();
        c.fillStyle = rgba(col, 0.8); c.fillRect(-p.r * 2.8, -p.r * 0.15, p.r * 1.6, p.r * 0.3);
        break;
      case 'crescent': case 'wave':
        c.strokeStyle = p.sh === 'wave' ? rgba(col, 0.9) : '#ffffff'; c.lineWidth = Math.max(3, p.r * 0.35); c.lineCap = 'round';
        c.beginPath(); c.arc(-p.r * 0.6, 0, p.r * 1.1, -1.1, 1.1); c.stroke();
        c.strokeStyle = rgba(col, 0.9); c.lineWidth = Math.max(2, p.r * 0.2);
        c.beginPath(); c.arc(-p.r * 0.9, 0, p.r * 1.1, -1.0, 1.0); c.stroke();
        break;
      case 'fist': {
        c.fillStyle = col; rr(c, -p.r * 0.8, -p.r * 0.8, p.r * 1.6, p.r * 1.6, p.r * 0.5); c.fill();
        c.strokeStyle = shade(col.length === 7 ? col : '#ffffff', -0.35); c.lineWidth = Math.max(1.5, p.r * 0.12);
        for (let i = -1; i <= 1; i++) { c.beginPath(); c.moveTo(p.r * 0.2, i * p.r * 0.45); c.lineTo(p.r * 0.8, i * p.r * 0.45); c.stroke(); }
        break;
      }
      case 'saw': case 'cube': {
        c.rotate(t * 14);
        c.fillStyle = col;
        if (p.sh === 'cube') { c.strokeStyle = '#ffffff'; c.lineWidth = 3; c.strokeRect(-p.r * 0.8, -p.r * 0.8, p.r * 1.6, p.r * 1.6); c.globalAlpha = 0.5; c.fillRect(-p.r * 0.8, -p.r * 0.8, p.r * 1.6, p.r * 1.6); c.globalAlpha = 1; }
        else { c.beginPath(); for (let i = 0; i < 16; i++) { const rr2 = i % 2 ? p.r * 0.6 : p.r; c.lineTo(Math.cos((i / 16) * TAU) * rr2, Math.sin((i / 16) * TAU) * rr2); } c.closePath(); c.fill(); circle(c, 0, 0, p.r * 0.25, '#5d4037'); }
        break;
      }
      case 'bomb': circle(c, 0, 0, p.r, '#263238'); circle(c, -p.r * 0.3, -p.r * 0.3, p.r * 0.3, 'rgba(255,255,255,0.4)'); circle(c, p.r * 0.8, -p.r * 0.8, p.r * 0.3, Math.sin(t * 30) > 0 ? '#ffeb3b' : '#ff5722'); break;
      case 'note': c.rotate(-a); c.fillStyle = col; c.font = `bold ${p.r * 2}px sans-serif`; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText('♪', 0, 0); break;
      case 'skull': c.rotate(-a); circle(c, 0, 0, p.r, rgba(col, 0.85)); c.fillStyle = '#1a1033'; c.fillRect(-p.r * 0.45, -p.r * 0.25, p.r * 0.3, p.r * 0.35); c.fillRect(p.r * 0.15, -p.r * 0.25, p.r * 0.3, p.r * 0.35); break;
      case 'bat': { const f = Math.sin(t * 25) * 0.5; c.fillStyle = '#1a1033'; c.beginPath(); c.moveTo(0, 0); c.lineTo(-p.r, -p.r * (1 + f)); c.lineTo(-p.r * 0.4, 0); c.lineTo(-p.r, p.r * (1 + f)); c.closePath(); c.fill(); circle(c, 0, 0, p.r * 0.4, '#311b92'); break; }
      case 'drop': c.fillStyle = col; c.beginPath(); c.moveTo(p.r * 1.4, 0); c.quadraticCurveTo(0, -p.r, -p.r * 0.8, 0); c.quadraticCurveTo(0, p.r, p.r * 1.4, 0); c.fill(); break;
      case 'ring': c.strokeStyle = col; c.lineWidth = Math.max(3, p.r * 0.3); c.beginPath(); c.arc(0, 0, p.r * 0.8, 0, TAU); c.stroke(); circle(c, 0, 0, p.r * 0.35, rgba('#ffffff', 0.6)); break;
      case 'cloud': c.globalAlpha = 0.8; circle(c, -p.r * 0.4, 0, p.r * 0.8, col); circle(c, p.r * 0.4, -p.r * 0.2, p.r * 0.7, '#eceff1'); circle(c, 0, p.r * 0.35, p.r * 0.6, col); c.globalAlpha = 1; break;
      case 'meteor': circle(c, 0, 0, p.r, shade(col.length === 7 ? col : '#ff5722', -0.3)); circle(c, p.r * 0.2, -p.r * 0.2, p.r * 0.55, col); break;
      default: circle(c, 0, 0, p.r, col); circle(c, 0, 0, p.r * 0.5, 'rgba(255,255,255,0.85)');
    }
    c.restore();
  }

  // The world pass: everything from the water up to the damage numbers.
  R.drawWorld = function (S, dt) {
    const t = S.time;
    const sea = TF.SEAS[S.sea];
    const cam = S.cam;
    const z = cam.zoom;
    const shakeX = cam.shake ? (Math.random() - 0.5) * cam.shake : 0, shakeY = cam.shake ? (Math.random() - 0.5) * cam.shake : 0;
    ctx.setTransform(DPR * z, 0, 0, DPR * z, DPR * (W / 2 - (cam.x + shakeX) * z), DPR * (H / 2 - (cam.y + shakeY) * z));
    const vb = { x0: cam.x - W / 2 / z, y0: cam.y - H / 2 / z, x1: cam.x + W / 2 / z, y1: cam.y + H / 2 / z };
    const inView = (x, y, m) => x > vb.x0 - m && x < vb.x1 + m && y > vb.y0 - m && y < vb.y1 + m;
    drawWater(sea, cam, t, vb);

    const visIsl = sea.islands.filter((isl) => inView(isl.x, isl.y, isl.R * 1.3));
    for (const isl of visIsl) drawIslandGround(sea, isl, t);

    // Ground-level effects: zones, telegraphs, fruit on the ground.
    for (const f of S.fx) if (f.k === 'zone') drawZone(f, t);
    for (const f of S.fx) if ((f.k === 'blast' && t < f.t0 + f.d) || f.k === 'warn' || (f.k === 'beam' && f.m && t < f.t0 + f.d)) drawTelegraph(f, t, S);
    for (const d of S.drops.values()) drawDrop(d, t);

    // Y-sorted pass: decor, NPCs, mobs, players.
    const list = [];
    for (const isl of visIsl) for (const d of decorOf(isl)) if (!FLAT[d.k] && inView(d.x, d.y, 80)) list.push({ y: d.y, k: 0, d, bio: TF.BIOMES[isl.biome] });
    for (const n of TF.NPCS) if (n.sea === S.sea && inView(n.x, n.y, 80)) list.push({ y: n.y, k: 1, n });
    for (const m of S.mobs.values()) if (inView(m.x, m.y, 200)) list.push({ y: m.y, k: 2, m });
    for (const p of S.players.values()) if (inView(p.x, p.y, 120)) list.push({ y: p.y, k: 3, p });
    list.sort((a, b) => a.y - b.y);
    const overlays = [];
    for (const e of list) {
      if (e.k === 0) drawDecor(e.d, e.bio, t);
      else if (e.k === 1) { drawNpc(e.n, t, S); overlays.push(e); }
      else if (e.k === 2) { drawMob(e.m, t); overlays.push(e); }
      else { drawPlayer(e.p, t, S); overlays.push(e); }
    }

    // Projectiles and effects above everything.
    for (const p of S.projs.values()) drawProjShape(p, t);
    for (const f of S.fx) {
      if (f.k === 'blast' && t >= f.t0 + f.d) drawExplosion(f, t);
      else if (f.k === 'beam' && t >= f.t0 + f.d) drawBeam(f, t, S);
      else if (f.k === 'chain') drawChain(f, t);
      else if (f.k === 'm1') drawSwing(f, t, S);
      else if (f.k === 'ring') drawRing(f, t);
    }
    drawParticles(dt);
    for (const e of overlays) {
      if (e.k === 1) drawNpcLabel(e.n, S);
      else if (e.k === 2) drawMobLabel(e.m);
      else drawPlayerLabel(e.p, S);
    }
    drawTexts(S, t);
    // Night falls slowly and lifts again; lamps and torches keep glowing.
    const night = Math.max(0, Math.sin((t / 600) * TAU)) * 0.28;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    if (night > 0.01) { ctx.fillStyle = `rgba(10,15,45,${night})`; ctx.fillRect(0, 0, W, H); }
    if (S.hurtFlash > 0) {
      const g = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.3, W / 2, H / 2, Math.max(W, H) * 0.7);
      g.addColorStop(0, 'rgba(255,0,0,0)'); g.addColorStop(1, `rgba(255,0,0,${S.hurtFlash * 0.45})`);
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    }
  };

  R.screenToWorld = function (S, sx, sy) {
    const z = S.cam.zoom;
    return { x: S.cam.x + (sx - W / 2) / z, y: S.cam.y + (sy - H / 2) / z };
  };

  // ─── Entity drawing ───────────────────────────────────────────────────────
  const NPC_LOOK = {
    quest: { form: 'h', shirt: '#1e88e5', pants: '#5d4037', hat: 2, hatColor: '#fdd835', skin: '#f1c27d' },
    fruit: { form: 'h', shirt: '#ff7043', pants: '#4e342e', hat: 9, hatColor: '#4e342e', skin: '#e0ac69' },
    gacha: { form: 'h', shirt: '#7e57c2', pants: '#311b92', hat: 7, hatColor: '#4527a0', skin: '#f1c27d' },
    sword: { form: 'h', shirt: '#607d8b', pants: '#37474f', hat: 1, hatColor: '#263238', skin: '#c68642' },
    gun: { form: 'h', shirt: '#8d6e63', pants: '#3e2723', hat: 4, hatColor: '#3e2723', skin: '#e0ac69' },
    style: { form: 'h', shirt: '#ef5350', pants: '#212121', hat: 1, hatColor: '#ffffff', skin: '#8d5524' },
    ability: { form: 'h', shirt: '#26c6da', pants: '#006064', hat: 8, hatColor: '#80deea', skin: '#f1c27d' },
    ferry: { form: 'h', shirt: '#ffffff', pants: '#0d47a1', hat: 4, hatColor: '#0d47a1', skin: '#e0ac69' },
    reset: { form: 'h', shirt: '#9ccc65', pants: '#33691e', hat: 2, hatColor: '#33691e', skin: '#f1c27d' },
    awaken: { form: 'h', shirt: '#ffe082', pants: '#ff6f00', hat: 8, hatColor: '#ffd54f', skin: '#fff3e0' },
  };
  function drawNpc(n, t, S) {
    const near = S.nearNpc === n.id;
    drawCharacter(n.x, n.y, NPC_LOOK[n.kind], { size: 1.05, ang: Math.PI / 2 + Math.sin(t * 0.7 + n.id) * 0.5, t: t + n.id, moving: false, aura: near ? '#ffffff' : null });
  }
  function drawNpcLabel(n, S) {
    const k = TF.NPC_KINDS[n.kind];
    const y = n.y - 78 + Math.sin(S.time * 3 + n.id) * 3;
    ctx.save();
    ctx.beginPath(); ctx.arc(n.x, y, 13, 0, TAU);
    ctx.fillStyle = k.color; ctx.fill();
    ctx.lineWidth = 3; ctx.strokeStyle = '#1a1a2e'; ctx.stroke();
    ctx.fillStyle = '#1a1a2e'; ctx.font = 'bold 15px system-ui, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(k.icon, n.x, y + 1);
    label(n.name, n.x, n.y - 58, 12, '#ffffff');
    ctx.restore();
  }

  function drawMob(m, t) {
    const mt = TF.MOB_TYPES[m.type];
    const flash = m.flash > 0 ? m.flash : 0;
    const wind = m.f & 1;
    if (mt.seaBeast) { drawSerpent(m.x, m.y, mt.look, mt.size / 3.2 * 1.6, m.ang, t, flash); return; }
    const sz = mt.size * (wind ? 1.06 : 1);
    drawCharacter(m.x, m.y, mt.look, {
      size: sz, ang: m.ang, t: t + m.id * 0.37, moving: m.moving, flash,
      aura: mt.boss ? '#ff1744' : wind ? '#ff8a80' : null, eyeGlow: mt.look.hatColor || '#ffeb3b',
      weapon: { kind: mt.look.form === 'h' ? 'sword' : 'style', color: '#b0bec5' }, swing: wind ? -0.8 : 0,
    });
    if (m.f & 32 && Math.random() < 0.3) particle(m.x + (Math.random() - 0.5) * 20, m.y - 30 * sz, 0, -40, 0.5, 5, '#ff7043');
    if (m.f & 16 && Math.random() < 0.2) particle(m.x + (Math.random() - 0.5) * 24, m.y - 20 * sz, 0, -20, 0.6, 4, '#81d4fa');
    if (m.f & 2) { ctx.save(); ctx.globalCompositeOperation = 'lighter'; for (let i = 0; i < 3; i++) { const a = t * 6 + i * 2.1; circle(ctx, m.x + Math.cos(a) * 14, m.y - 56 * sz + Math.sin(a) * 4, 3, '#ffeb3b'); } ctx.restore(); }
  }
  function drawMobLabel(m) {
    const mt = TF.MOB_TYPES[m.type];
    const top = m.y - (mt.seaBeast ? 90 : 62 * mt.size) - 6;
    label(`${mt.name} [Lv. ${mt.level}]`, m.x, top - 10, mt.boss || mt.seaBeast ? 14 : 11, mt.boss || mt.seaBeast ? '#ff8a80' : '#ffffff');
    if (m.hp < mt.hp) bar(m.x, top, mt.boss || mt.seaBeast ? 90 : 52, 6, m.hp / mt.hp, '#e53935');
  }

  function playerLook(p) {
    const h = TF.hashStr(p.name);
    const skins = ['#f1c27d', '#e0ac69', '#c68642', '#8d5524', '#ffdbac'];
    const skin = skins[h % skins.length];
    if (p.team === 1) return { form: 'h', shirt: '#f5f7fa', pants: ['#1565c0', '#0d47a1', '#1976d2'][(h >>> 3) % 3], hat: 2, hatColor: '#1565c0', skin };
    return { form: 'h', shirt: ['#c62828', '#b71c1c', '#d84315', '#6a1b9a'][(h >>> 3) % 4], pants: '#3e2723', hat: (h >>> 5) % 3 === 0 ? 4 : 1, hatColor: ['#212121', '#c62828', '#ffd54f'][(h >>> 7) % 3], skin };
  }
  function drawPlayer(p, t, S) {
    if (p.f & 8) return;
    const L = playerLook(p);
    const w = TF.ITEMS[p.w];
    const trans = !!(p.f & 4);
    const fr = p.fruit >= 0 ? TF.FRUITS[p.fruit] : null;
    const boat = !!(p.f & 1);
    const swing = p.swingT && t - p.swingT < 0.18 ? Math.sin(((t - p.swingT) / 0.18) * Math.PI) * -1.4 : 0;
    drawCharacter(p.x, p.y, L, {
      size: trans ? TF.TRANSFORM.size : 1, ang: p.aim, t: t + p.id, moving: p.moving, boat, boatAng: p.moveAng || 0,
      weapon: w ? { kind: w.cat, color: w.cat === 'fruit' ? w.color : w.color } : null, flash: p.flash > 0 ? p.flash : 0,
      alpha: p.f & 256 ? 0.55 + Math.sin(t * 20) * 0.2 : undefined, trans, transColor: fr && fr.color, fruitKey: fr && fr.key,
      aura: trans && fr ? fr.color : p.f & 1024 && w && w.cat === 'fruit' ? fr.color : null, swing,
    });
    if (p.f & 128) { ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.strokeStyle = 'rgba(128,222,234,0.7)'; ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(p.x, p.y - 26, 36, 0, TAU); ctx.stroke(); ctx.restore(); }
    if (p.f & 32) { ctx.save(); ctx.globalCompositeOperation = 'lighter'; for (let i = 0; i < 3; i++) { const a = t * 6 + i * 2.1; circle(ctx, p.x + Math.cos(a) * 14, p.y - 60 + Math.sin(a) * 4, 3, '#ffeb3b'); } ctx.restore(); }
    if (boat && p.moving && Math.random() < 0.6) particle(p.x - Math.cos(p.moveAng) * 36 + (Math.random() - 0.5) * 10, p.y - Math.sin(p.moveAng) * 36, -Math.cos(p.moveAng) * 30, -Math.sin(p.moveAng) * 30, 0.7, 5, 'rgba(255,255,255,0.8)', false);
    if (trans && fr && Math.random() < 0.4) particle(p.x + (Math.random() - 0.5) * 30, p.y - 30 - Math.random() * 30, 0, -40, 0.6, 4, fr.color);
  }
  function drawPlayerLabel(p, S) {
    if (p.f & 8) return;
    const me = p.id === S.id;
    const trans = p.f & 4;
    const top = p.y - (trans ? 80 : 64);
    const col = p.team === 1 ? '#90caf9' : '#ff8a80';
    label(`${p.name} [${p.lv}]`, p.x, top - 10, 12, me ? '#ffe082' : col);
    if (p.bounty > 0) label(`${p.team === 1 ? '⚓' : '☠'} $${fmtShort(p.bounty)}`, p.x, top - 25, 10, '#ffd54f');
    if (!me) bar(p.x, top, 46, 5, p.hp / p.mhp, p.f & 2 ? '#e53935' : '#43a047');
    if (p.f & 2 && !(p.f & 512)) label('PvP', p.x + 40, top - 10, 10, '#ff5252');
  }

  function drawDrop(d, t) {
    const fr = TF.FRUITS[d.fi];
    if (!fr) return;
    const by = Math.sin(t * 3 + d.id) * 5;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    circle(ctx, d.x, d.y - 16 + by, 34, rgba(fr.color, 0.25 + Math.sin(t * 4) * 0.08));
    ctx.restore();
    ellipse(ctx, d.x, d.y, 16, 5, 'rgba(0,0,0,0.25)');
    const img = dropImg(fr);
    if (img.complete) ctx.drawImage(img, d.x - 20, d.y - 40 + by, 40, 40);
    if (Math.random() < 0.15) particle(d.x + (Math.random() - 0.5) * 30, d.y - 20, 0, -30, 0.8, 3, '#ffffff');
    label(fr.name, d.x, d.y - 48 + by, 11, TF.RARITY[fr.rarity].color);
  }
  const dropImgs = new Map();
  function dropImg(fr) {
    let img = dropImgs.get(fr.id);
    if (!img) { img = new Image(); img.src = R.fruitIcon(fr, 64); dropImgs.set(fr.id, img); }
    return img;
  }

  function label(text, x, y, size, color) {
    ctx.font = `800 ${size}px system-ui, "Segoe UI", sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.lineWidth = 3.5;
    ctx.strokeStyle = 'rgba(0,0,0,0.75)';
    ctx.strokeText(text, x, y);
    ctx.fillStyle = color;
    ctx.fillText(text, x, y);
  }
  function bar(x, y, w, h, k, col) {
    k = Math.max(0, Math.min(1, k));
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    rr(ctx, x - w / 2 - 1.5, y - h / 2 - 1.5, w + 3, h + 3, 3); ctx.fill();
    ctx.fillStyle = col;
    if (k > 0) { rr(ctx, x - w / 2, y - h / 2, w * k, h, 2); ctx.fill(); }
  }
  function fmtShort(n) {
    if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e4) return (n / 1e3).toFixed(0) + 'K';
    return String(n);
  }
  R.fmtShort = fmtShort;

  // ─── Skill effects ────────────────────────────────────────────────────────
  function drawTelegraph(f, t, S) {
    const c = ctx;
    if (f.k === 'warn') {
      const k = Math.min(1, (t - f.t0) / f.d);
      c.save(); c.translate(f.x, f.y); c.rotate(f.a);
      c.fillStyle = `rgba(255,40,40,${0.12 + k * 0.2})`; c.fillRect(0, -f.w / 2, f.len, f.w);
      c.fillStyle = 'rgba(255,40,40,0.35)'; c.fillRect(0, -f.w / 2, f.len * k, f.w);
      c.restore();
      return;
    }
    if (f.k === 'beam') {
      const o = anchor(f, S);
      c.save(); c.translate(o.x, o.y); c.rotate(f.a);
      c.fillStyle = 'rgba(255,40,40,0.18)'; c.fillRect(0, -f.w / 2, f.len, f.w);
      c.strokeStyle = 'rgba(255,60,60,0.6)'; c.lineWidth = 2; c.strokeRect(0, -f.w / 2, f.len, f.w);
      c.restore();
      return;
    }
    const k = Math.min(1, (t - f.t0) / Math.max(0.01, f.d));
    const col = f.m ? '#ff2a2a' : f.c;
    c.beginPath(); c.arc(f.x, f.y, f.r, 0, TAU);
    c.fillStyle = rgba(col, f.m ? 0.12 : 0.08); c.fill();
    c.lineWidth = f.m ? 3 : 2; c.strokeStyle = rgba(col, f.m ? 0.7 : 0.45); c.stroke();
    c.beginPath(); c.arc(f.x, f.y, f.r * k, 0, TAU);
    c.fillStyle = rgba(col, f.m ? 0.25 : 0.15); c.fill();
    if (f.sh === 'meteor' && f.d > 0.3) {
      const h = (1 - k) * 420;
      c.save(); c.globalCompositeOperation = 'lighter';
      circle(c, f.x + h * 0.4, f.y - h, Math.max(10, f.r * 0.3), rgba(f.m ? '#ff5722' : f.c, 0.9));
      circle(c, f.x + h * 0.4, f.y - h, Math.max(5, f.r * 0.15), '#fff3e0');
      c.restore();
      if (Math.random() < 0.6) particle(f.x + h * 0.4, f.y - h, (Math.random() - 0.5) * 40, -60, 0.4, 7, '#ff7043');
    }
  }

  function drawExplosion(f, t) {
    const c = ctx;
    const age = t - f.t0 - f.d;
    const life = 0.42;
    if (age > life) return;
    const k = age / life;
    const col = f.m ? '#ff5252' : f.c;
    c.save();
    c.globalCompositeOperation = 'lighter';
    const g = c.createRadialGradient(f.x, f.y, 0, f.x, f.y, f.r * (0.6 + k * 0.5));
    g.addColorStop(0, rgba('#ffffff', 0.6 * (1 - k))); g.addColorStop(0.4, rgba(col, 0.55 * (1 - k))); g.addColorStop(1, rgba(col, 0));
    c.fillStyle = g; c.beginPath(); c.arc(f.x, f.y, f.r * (0.6 + k * 0.5), 0, TAU); c.fill();
    c.strokeStyle = rgba(col, 0.9 * (1 - k)); c.lineWidth = 6 * (1 - k) + 1;
    c.beginPath(); c.arc(f.x, f.y, f.r * (0.4 + k * 0.7), 0, TAU); c.stroke();
    if (f.sh === 'crack') {
      c.strokeStyle = rgba('#ffffff', 0.8 * (1 - k)); c.lineWidth = 3;
      for (let i = 0; i < 7; i++) {
        const a = (i / 7) * TAU + f.seed;
        c.beginPath(); c.moveTo(f.x, f.y);
        c.lineTo(f.x + Math.cos(a + 0.2) * f.r * 0.5, f.y + Math.sin(a + 0.2) * f.r * 0.5);
        c.lineTo(f.x + Math.cos(a) * f.r, f.y + Math.sin(a) * f.r);
        c.stroke();
      }
    }
    if (f.sh === 'bolt' && age < 0.15) {
      c.strokeStyle = '#ffffff'; c.lineWidth = 5;
      c.beginPath(); c.moveTo(f.x, f.y);
      let yy = f.y;
      for (let i = 0; i < 6; i++) { yy -= 70; c.lineTo(f.x + (Math.random() - 0.5) * 50, yy); }
      c.stroke();
    }
    c.restore();
  }

  function anchor(f, S) {
    const e = f.ot === 'm' ? S.mobs.get(f.o) : S.players.get(f.o);
    return e ? { x: e.x, y: e.y - (f.ot === 'm' ? 20 : 26) } : { x: f.x, y: f.y };
  }

  function drawBeam(f, t, S) {
    const age = t - f.t0 - f.d;
    if (age > f.dur) return;
    const k = age / f.dur;
    const o = anchor(f, S);
    const c = ctx;
    const col = f.m ? '#ff5252' : f.c;
    c.save();
    c.translate(o.x, o.y);
    c.rotate(f.a);
    c.globalCompositeOperation = 'lighter';
    const fade = k > 0.75 ? (1 - k) * 4 : 1;
    if (f.sh === 'fist' || f.sh === 'claw' || f.sh === 'slash') {
      const n = 6;
      for (let i = 0; i < n; i++) {
        const along = ((i / n + age * 3) % 1) * f.len;
        const off = Math.sin(i * 7.3 + age * 30) * f.w * 0.35;
        if (f.sh === 'fist') { circle(c, along, off, f.w * 0.22, rgba(col, 0.75 * fade)); circle(c, along, off, f.w * 0.1, rgba('#ffffff', 0.6 * fade)); }
        else { c.strokeStyle = rgba(i % 2 ? '#ffffff' : col, 0.85 * fade); c.lineWidth = 4; c.beginPath(); c.arc(along, off, f.w * 0.3, -1.2, 1.2); c.stroke(); }
      }
    } else {
      const flick = 0.85 + Math.random() * 0.15;
      const g = c.createLinearGradient(0, -f.w / 2, 0, f.w / 2);
      g.addColorStop(0, rgba(col, 0)); g.addColorStop(0.5, rgba(col, 0.75 * fade * flick)); g.addColorStop(1, rgba(col, 0));
      c.fillStyle = g; c.fillRect(0, -f.w / 2, f.len, f.w);
      c.fillStyle = rgba('#ffffff', 0.7 * fade); c.fillRect(0, -f.w * 0.1, f.len, f.w * 0.2);
      if (f.sh === 'crack' || f.sh === 'bolt') {
        c.strokeStyle = rgba('#ffffff', 0.9 * fade); c.lineWidth = 3;
        c.beginPath(); c.moveTo(0, 0);
        for (let x = 30; x < f.len; x += 30) c.lineTo(x, (Math.random() - 0.5) * f.w * 0.6);
        c.stroke();
      }
    }
    c.restore();
    if (Math.random() < 0.7) {
      const along = Math.random() * f.len;
      particle(o.x + Math.cos(f.a) * along, o.y + Math.sin(f.a) * along, (Math.random() - 0.5) * 60, (Math.random() - 0.5) * 60, 0.4, 5, col);
    }
  }

  function drawZone(f, t) {
    const c = ctx;
    const age = t - f.t0;
    if (age > f.dur) return;
    const k = age / f.dur;
    const fadeIn = Math.min(1, age * 5), fadeOut = k > 0.85 ? (1 - k) / 0.15 : 1;
    const a = fadeIn * fadeOut;
    c.save();
    c.globalCompositeOperation = f.sh === 'void' ? 'source-over' : 'lighter';
    const g = c.createRadialGradient(f.x, f.y, f.r * 0.2, f.x, f.y, f.r);
    const col = f.c;
    g.addColorStop(0, rgba(col, 0.35 * a)); g.addColorStop(1, rgba(col, 0.12 * a));
    c.fillStyle = g; c.beginPath(); c.arc(f.x, f.y, f.r, 0, TAU); c.fill();
    c.strokeStyle = rgba(col, 0.6 * a); c.lineWidth = 3;
    c.setLineDash([14, 10]); c.lineDashOffset = -t * 40;
    c.beginPath(); c.arc(f.x, f.y, f.r, 0, TAU); c.stroke();
    c.setLineDash([]);
    if (f.sh === 'void') {
      c.strokeStyle = rgba('#000000', 0.5 * a); c.lineWidth = 5;
      for (let i = 0; i < 3; i++) { c.beginPath(); c.arc(f.x, f.y, f.r * (0.3 + i * 0.2), t * (2 + i) , t * (2 + i) + 2.5); c.stroke(); }
    }
    c.restore();
    if (Math.random() < 0.8) {
      const pa = Math.random() * TAU, pr = Math.sqrt(Math.random()) * f.r;
      particle(f.x + Math.cos(pa) * pr, f.y + Math.sin(pa) * pr, 0, -30 - Math.random() * 30, 0.8, 4 + Math.random() * 4, col);
    }
  }

  function drawChain(f, t) {
    const age = t - f.t0;
    if (age > 0.35) return;
    const c = ctx;
    c.save(); c.globalCompositeOperation = 'lighter';
    for (const [w, col] of [[8, rgba(f.c, 0.35 * (1 - age / 0.35))], [3, rgba('#ffffff', 0.95 * (1 - age / 0.35))]]) {
      c.strokeStyle = col; c.lineWidth = w; c.lineJoin = 'round';
      c.beginPath();
      for (let i = 0; i < f.pts.length - 1; i++) {
        const [x1, y1] = f.pts[i], [x2, y2] = f.pts[i + 1];
        if (i === 0) c.moveTo(x1, y1 - 20);
        for (let s = 1; s <= 5; s++) {
          const k = s / 5;
          c.lineTo(x1 + (x2 - x1) * k + (s < 5 ? (Math.random() - 0.5) * 30 : 0), y1 + (y2 - y1) * k - 20 + (s < 5 ? (Math.random() - 0.5) * 30 : 0));
        }
      }
      c.stroke();
    }
    c.restore();
  }

  function drawSwing(f, t, S) {
    const age = t - f.t0;
    if (age > 0.18) return;
    const e = S.players.get(f.o);
    if (!e) return;
    const k = age / 0.18;
    const c = ctx;
    c.save();
    c.translate(e.x, e.y - 22);
    c.globalCompositeOperation = 'lighter';
    const arc = f.w === 'sword' ? 1.1 : 0.8;
    c.strokeStyle = rgba(f.w === 'sword' ? '#ffffff' : f.c || '#ffffff', 0.8 * (1 - k));
    c.lineWidth = f.w === 'sword' ? 6 : 10;
    c.lineCap = 'round';
    c.beginPath();
    c.arc(0, 0, f.r * 0.85, f.a - arc + k * arc * 0.6, f.a + arc * (k * 1.4 - 0.4));
    c.stroke();
    if (f.w !== 'sword') circle(c, Math.cos(f.a) * f.r * 0.8, Math.sin(f.a) * f.r * 0.8, 14 * (1 - k), rgba(f.c || '#ffffff', 0.6));
    c.restore();
  }

  function drawRing(f, t) {
    const age = t - f.t0;
    if (age > f.dur) return;
    const k = age / f.dur;
    ctx.save(); ctx.globalCompositeOperation = 'lighter';
    ctx.strokeStyle = rgba(f.c, 1 - k); ctx.lineWidth = 6 * (1 - k) + 1;
    ctx.beginPath(); ctx.arc(f.x, f.y, f.r0 + (f.r1 - f.r0) * k, 0, TAU); ctx.stroke();
    ctx.restore();
  }

  function drawTexts(S, t) {
    const c = ctx;
    for (const d of S.texts) {
      const age = t - d.t0;
      const k = age / d.life;
      if (k >= 1) continue;
      const pop = age < 0.12 ? 1 + (1 - age / 0.12) * 0.6 : 1;
      c.globalAlpha = k > 0.7 ? (1 - k) / 0.3 : 1;
      label(d.text, d.x + d.dx * age, d.y - 30 * age - (d.big ? 10 : 0), Math.round(d.size * pop), d.color);
    }
    c.globalAlpha = 1;
  }

  // ─── Minimap ──────────────────────────────────────────────────────────────
  R.drawMap = function (canvas, S, big) {
    const c = canvas.getContext('2d');
    const sea = TF.SEAS[S.sea];
    const w = canvas.width, h = canvas.height;
    const k = Math.min(w / sea.w, h / sea.h);
    c.clearRect(0, 0, w, h);
    c.fillStyle = sea.water[1];
    c.fillRect(0, 0, w, h);
    c.fillStyle = rgba(sea.water[0], 0.7);
    c.fillRect(0, 0, sea.w * k, sea.h * k);
    for (const isl of sea.islands) {
      const bio = TF.BIOMES[isl.biome];
      c.beginPath();
      const N = isl.radii.length;
      for (let i = 0; i <= N; i += 2) {
        const th = (i / N) * TAU, r = isl.radii[i % N];
        const x = (isl.x + Math.cos(th) * r) * k, y = (isl.y + Math.sin(th) * r) * k;
        if (i === 0) c.moveTo(x, y); else c.lineTo(x, y);
      }
      c.closePath();
      c.fillStyle = bio.sand; c.fill();
      c.fillStyle = bio.ground; c.beginPath(); c.arc(isl.x * k, isl.y * k, isl.R * 0.82 * k, 0, TAU); c.fill();
      if (big) {
        const lv = S.me ? S.me.lv : 1;
        const col = lv >= isl.lv[0] ? (lv > isl.lv[1] + 150 ? '#b0bec5' : '#ffffff') : '#ff8a80';
        c.font = `800 ${Math.max(11, w / 60)}px system-ui, sans-serif`;
        c.textAlign = 'center';
        c.lineWidth = 3; c.strokeStyle = 'rgba(0,0,0,0.8)';
        c.strokeText(isl.name, isl.x * k, isl.y * k - 6); c.fillStyle = col; c.fillText(isl.name, isl.x * k, isl.y * k - 6);
        const sub = isl.hub ? `Town · Lv. ${isl.lv[0]}–${isl.lv[1]}` : `Lv. ${isl.lv[0]}–${isl.lv[1]}`;
        c.font = `700 ${Math.max(10, w / 75)}px system-ui, sans-serif`;
        c.strokeText(sub, isl.x * k, isl.y * k + 10); c.fillStyle = '#ffe082'; c.fillText(sub, isl.x * k, isl.y * k + 10);
      }
    }
    // Quest target
    if (S.me && S.me.q) {
      const mt = TF.MOB_TYPES[S.me.q.mob];
      const isl = mt.isle >= 0 && mt.sea === S.sea ? sea.islands[mt.isle] : null;
      if (isl) { c.strokeStyle = '#ffd54f'; c.lineWidth = 2; c.setLineDash([4, 3]); c.beginPath(); c.arc(isl.x * k, isl.y * k, isl.R * 1.25 * k, 0, TAU); c.stroke(); c.setLineDash([]); }
    }
    for (const b of S.bosses) {
      const mt = TF.MOB_TYPES[b[0]];
      c.fillStyle = mt.seaBeast ? '#ff9100' : '#ff1744';
      c.beginPath(); c.arc(b[1] * k, b[2] * k, big ? 6 : 3.5, 0, TAU); c.fill();
      c.strokeStyle = '#000'; c.lineWidth = 1; c.stroke();
    }
    for (const p of S.players.values()) {
      if (p.id === S.id) continue;
      c.fillStyle = p.team === 1 ? '#90caf9' : '#ff8a80';
      c.fillRect(p.x * k - 2, p.y * k - 2, 4, 4);
    }
    const me = S.self;
    if (me) {
      c.save(); c.translate(me.x * k, me.y * k); c.rotate(S.aim);
      c.fillStyle = '#ffe082'; c.strokeStyle = '#000'; c.lineWidth = 1.5;
      const s = big ? 9 : 6;
      c.beginPath(); c.moveTo(s, 0); c.lineTo(-s * 0.7, -s * 0.7); c.lineTo(-s * 0.3, 0); c.lineTo(-s * 0.7, s * 0.7); c.closePath(); c.fill(); c.stroke();
      c.restore();
    }
  };
})();
