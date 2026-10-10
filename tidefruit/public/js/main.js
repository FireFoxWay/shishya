/*
 * Tidefruit client: connection, input, prediction and the frame loop.
 *
 * The local player moves immediately on input and reports where it is; the
 * server answers with corrections only when it disagrees. Everyone else is
 * drawn where the server last said, eased toward each new snapshot.
 */
(function () {
  'use strict';
  const TAU = Math.PI * 2;
  const clamp = TF.clamp;

  const S = (window.S = {
    ws: null, joined: false, id: 0, sea: 0, me: null, pc: 0,
    self: { x: 1200, y: 1300, kx: 0, ky: 0, dashUntil: 0, dvx: 0, dvy: 0, moving: false, moveAng: 0 },
    aim: 0, players: new Map(), mobs: new Map(), drops: new Map(), projs: new Map(), fx: [], texts: [],
    bosses: [], stock: [], stockAt: 0, lb: null,
    cam: { x: 1200, y: 1300, zoom: 1, shake: 0, user: 1 },
    time: 0, keys: {}, mouse: { x: 0, y: 0, down: false }, cd: {}, cdSent: {}, dashEnd: 0, dashSent: 0,
    m1Next: 0, stunUntil: 0, slowUntil: 0, transUntil: 0,
    dead: false, respawnAt: 0, deathBy: '', nearNpc: -1, hurtFlash: 0,
    touch: false, joy: { x: 0, y: 0, active: false }, touchAttack: false, sendAt: 0, ping: 0,
    name: '', token: '', team: 'pirate', reconnect: 0,
  });

  // ─── Connection ───────────────────────────────────────────────────────────
  function connect() {
    const url = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
    const ws = (S.ws = new WebSocket(url));
    ws.onopen = () => ws.send(JSON.stringify({ t: 'hello', name: S.name, token: S.token, team: S.team }));
    ws.onmessage = (ev) => {
      let m;
      try { m = JSON.parse(ev.data); } catch (_) { return; }
      onMessage(m);
    };
    ws.onclose = () => {
      if (S.ws !== ws) return;
      if (S.joined) {
        UI.toast('Connection lost — reconnecting…', 'bad');
        S.reconnect++;
        setTimeout(connect, Math.min(8000, 1000 * S.reconnect));
      } else UI.loginError(S.loginErr || 'Could not reach the server.');
    };
  }
  function send(o) { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(o)); }

  function onMessage(m) {
    switch (m.t) {
      case 'welcome': {
        S.id = m.id; S.pc = m.pc; S.reconnect = 0;
        setSea(m.sea, m.x, m.y);
        S.stock = m.stock; S.stockAt = S.time + m.stockLeft; S.lb = m.lb;
        onMe(m.me);
        const first = !S.joined;
        S.joined = true;
        S.dead = false;
        UI.onJoin(first);
        return;
      }
      case 'error': S.loginErr = m.msg; UI.loginError(m.msg); return;
    }
    if (!S.joined) return;
    switch (m.t) {
      case 'me': onMe(m); break;
      case 's': onSnap(m); break;
      case 'e': for (const e of m.e) onEvent(e); break;
      case 'pos':
        S.self.x = m.x; S.self.y = m.y; S.pc = m.pc;
        S.self.kx = S.self.ky = 0; S.self.dashUntil = 0;
        break;
      case 'sea':
        S.pc = m.pc;
        setSea(m.sea, m.x, m.y);
        UI.seaBanner(TF.SEAS[m.sea].name);
        break;
      case 'kb': S.self.kx += m.x * 8; S.self.ky += m.y * 8; break;
      case 'dead':
        S.dead = true; S.deathBy = m.by; S.respawnAt = S.time + m.in;
        S.self.kx = S.self.ky = 0;
        break;
      case 'note': UI.toast(m.m, m.c); break;
      case 'chat': UI.chat(m); break;
      case 'stock': S.stock = m.ids; S.stockAt = S.time + m.left; UI.refresh(); break;
      case 'lb': S.lb = m; UI.refresh(); break;
      case 'pong': S.ping = Math.round(performance.now() - m.c); break;
    }
  }

  function setSea(sea, x, y) {
    S.sea = sea;
    S.self.x = x; S.self.y = y; S.self.kx = S.self.ky = 0; S.self.dashUntil = 0;
    S.cam.x = x; S.cam.y = y;
    S.players.clear(); S.mobs.clear(); S.drops.clear(); S.projs.clear();
    S.fx = []; S.texts = []; S.bosses = [];
  }

  function onMe(m) {
    const t = S.time;
    const next = {};
    for (const [k, v] of Object.entries(m.cds || {})) next[k] = t + v;
    // A skill we just pressed may not have reached the server yet.
    for (const [k, end] of Object.entries(S.cd)) if (!(k in next) && end > t && t - (S.cdSent[k] || -9) < 0.5) next[k] = end;
    S.cd = next;
    if (t - S.dashSent > 0.5) S.dashEnd = t + m.dash;
    S.stunUntil = t + m.stun;
    S.slowUntil = t + m.slow;
    S.transUntil = t + m.tr;
    const prevLv = S.me ? S.me.lv : m.lv;
    S.me = m;
    if (m.lv > prevLv) UI.levelUp(m.lv);
    UI.refresh();
  }

  function onSnap(m) {
    const seen = new Set();
    for (const r of m.p) {
      const id = r[0];
      seen.add(id);
      let p = S.players.get(id);
      if (!p) { p = { id, x: r[1], y: r[2], flash: 0, moveAng: 0 }; S.players.set(id, p); }
      if (p.hp !== undefined && r[4] < p.hp) p.flash = 0.7;
      p.tx = r[1]; p.ty = r[2]; p.taim = r[3]; p.hp = r[4]; p.mhp = r[5]; p.lv = r[6]; p.f = r[7];
      p.w = r[8]; p.name = r[9]; p.team = r[10]; p.bounty = r[11]; p.fruit = r[12];
      if (id === S.id && S.dead && !(p.f & 8)) S.dead = false;
    }
    for (const id of S.players.keys()) if (!seen.has(id)) S.players.delete(id);
    seen.clear();
    for (const r of m.m) {
      const id = r[0];
      seen.add(id);
      let mb = S.mobs.get(id);
      if (!mb) { mb = { id, type: r[1], x: r[2], y: r[3], hp: r[4], flash: 0, ang: r[6] }; S.mobs.set(id, mb); }
      if (r[4] < mb.hp) mb.flash = 0.8;
      mb.tx = r[2]; mb.ty = r[3]; mb.hp = r[4]; mb.f = r[5]; mb.tang = r[6];
    }
    for (const id of S.mobs.keys()) if (!seen.has(id)) S.mobs.delete(id);
    S.drops.clear();
    for (const d of m.d) S.drops.set(d[0], { id: d[0], fi: d[1], x: d[2], y: d[3] });
    if (m.b) S.bosses = m.b;
    if (S.me) { S.me.hp = m.hp; S.me.en = m.en; }
  }

  // ─── Effects from the server ─────────────────────────────────────────────
  const DMG_STYLE = {
    0: ['#ffffff', 16], 1: ['#ffd54f', 23], 3: ['#69f0ae', 17], 4: ['#80d8ff', 15], 5: ['#ffab40', 13],
  };
  function text(txt, x, y, color, size, life, big) {
    if (S.texts.length > 120) S.texts.shift();
    S.texts.push({ text: txt, x, y, color, size, t0: S.time, life: life || 0.9, dx: (Math.random() - 0.5) * 40, big });
  }
  function near(x, y, r) { return Math.hypot(x - S.self.x, y - S.self.y) < r; }

  function onEvent(e) {
    const t = S.time;
    switch (e.k) {
      case 'proj':
        S.projs.set(e.id, { x: e.x, y: e.y, vx: Math.cos(e.a) * e.sp, vy: Math.sin(e.a) * e.sp, left: e.rng, r: e.r, c: e.c, sh: e.sh, m: e.m });
        if (e.o) { const p = S.players.get(e.o); if (p) p.swingT = t; }
        break;
      case 'pend': {
        const p = S.projs.get(e.id);
        if (p) { R.burst(p.x, p.y, 8, p.c, 180, 5, 0.35); S.projs.delete(e.id); }
        break;
      }
      case 'blast': S.fx.push(Object.assign({}, e, { t0: t, seed: Math.random() * 6 })); break;
      case 'beam': case 'zone': case 'warn': S.fx.push(Object.assign({}, e, { t0: t })); break;
      case 'dash': S.fx.push({ k: 'dashfx', o: e.o, c: e.c, t0: t, dur: e.dur + 0.1 }); break;
      case 'chain':
        S.fx.push({ k: 'chain', pts: e.pts, c: e.c, t0: t });
        for (const [x, y] of e.pts.slice(1)) R.burst(x, y - 20, 10, e.c, 200, 5, 0.3);
        break;
      case 'tele':
        S.fx.push({ k: 'ring', x: e.x1, y: e.y1 - 20, r0: 10, r1: 70, dur: 0.35, c: e.c, t0: t });
        S.fx.push({ k: 'ring', x: e.x2, y: e.y2 - 20, r0: 70, r1: 10, dur: 0.35, c: e.c, t0: t });
        R.burst(e.x1, e.y1 - 20, 14, e.c, 220, 6, 0.4);
        if (e.o !== S.id) { const p = S.players.get(e.o); if (p) { p.x = p.tx = e.x2; p.y = p.ty = e.y2; } }
        break;
      case 'buff': {
        const p = S.players.get(e.o);
        if (p) { S.fx.push({ k: 'ring', x: p.x, y: p.y - 24, r0: 20, r1: 90, dur: 0.5, c: e.c, t0: t }); R.burst(p.x, p.y - 24, 20, e.c, 200, 6, 0.6); }
        break;
      }
      case 'trans': {
        const p = S.players.get(e.o);
        if (p) {
          S.fx.push({ k: 'ring', x: p.x, y: p.y - 24, r0: 20, r1: 160, dur: 0.6, c: e.c, t0: t });
          R.burst(p.x, p.y - 24, 50, e.c, 360, 8, 0.8);
          if (e.o === S.id) S.cam.shake = 14;
        }
        break;
      }
      case 'm1': {
        if (e.o === S.id) break;
        S.fx.push(Object.assign({}, e, { t0: t }));
        const p = S.players.get(e.o);
        if (p) p.swingT = t;
        break;
      }
      case 'dmg': {
        if (e.c === 2) {
          const mine = e.o === S.id;
          text(String(e.v), e.x, e.y, mine ? '#ff5252' : '#ff8a80', mine ? 19 : 15);
          if (mine) { S.hurtFlash = Math.min(1, S.hurtFlash + 0.35); S.cam.shake = Math.max(S.cam.shake, 5); }
        } else {
          const [col, size] = DMG_STYLE[e.c] || DMG_STYLE[0];
          const v = typeof e.v === 'number' ? (e.c === 3 ? '+' : '') + fmtNum(e.v) : e.v;
          text(v, e.x, e.y, col, size, e.c === 1 ? 1.1 : 0.9, e.c === 1);
        }
        break;
      }
      case 'die': R.burst(e.x, e.y - 20, Math.min(50, 14 + e.r), e.c, 260, 7, 0.7); R.burst(e.x, e.y - 20, 10, '#ffffff', 160, 4, 0.5); break;
      case 'lvl': {
        const p = S.players.get(e.o);
        const x = p ? p.x : e.x, y = p ? p.y : e.y;
        if (p) {
          S.fx.push({ k: 'ring', x, y: y - 24, r0: 20, r1: 140, dur: 0.7, c: '#ffd54f', t0: t });
          R.burst(x, y - 24, 40, '#ffd54f', 300, 7, 0.9);
          text('LEVEL UP!', x, y - 80, '#ffd54f', 20, 1.4);
        }
        break;
      }
    }
  }
  function fmtNum(n) { return n >= 100000 ? R.fmtShort(n) : n.toLocaleString(); }

  function updateFx(dt) {
    const t = S.time;
    for (const [id, p] of S.projs) {
      const sp = Math.hypot(p.vx, p.vy);
      p.x += p.vx * dt; p.y += p.vy * dt; p.left -= sp * dt;
      if (Math.random() < 0.6) R.particle(p.x, p.y, -p.vx * 0.05 + (Math.random() - 0.5) * 30, -p.vy * 0.05 + (Math.random() - 0.5) * 30, 0.3, Math.max(3, p.r * 0.5), p.m ? '#ff5252' : p.c);
      if (p.left <= 0) S.projs.delete(id);
    }
    const keep = [];
    for (const f of S.fx) {
      const age = t - f.t0;
      let alive;
      switch (f.k) {
        case 'blast':
          if (!f.boomed && age >= f.d) {
            f.boomed = true;
            R.burst(f.x, f.y, Math.round(clamp(f.r / 5, 8, 45)), f.m ? '#ff5252' : f.c, f.r * 2.4, 6, 0.5);
            if (near(f.x, f.y, 700)) S.cam.shake = Math.max(S.cam.shake, Math.min(16, f.r / 14));
          }
          alive = age < f.d + 0.5; break;
        case 'beam': alive = age < f.d + f.dur; break;
        case 'zone': alive = age < f.dur; break;
        case 'warn': alive = age < f.d; break;
        case 'chain': alive = age < 0.4; break;
        case 'm1': alive = age < 0.2; break;
        case 'ring': alive = age < f.dur; break;
        case 'dashfx': {
          const p = S.players.get(f.o) || S.mobs.get(f.o);
          if (p) for (let i = 0; i < 3; i++) R.particle(p.x + (Math.random() - 0.5) * 24, p.y - 20 + (Math.random() - 0.5) * 30, 0, 0, 0.35, 8, f.c);
          alive = age < f.dur; break;
        }
        default: alive = false;
      }
      if (alive) keep.push(f);
    }
    S.fx = keep;
    S.texts = S.texts.filter((d) => t - d.t0 < d.life);
    S.hurtFlash = Math.max(0, S.hurtFlash - dt * 1.5);
  }

  // ─── The local player ────────────────────────────────────────────────────
  function myWeapon() {
    const me = S.me;
    let slot = me.slot;
    if (slot === 3 && !me.fruit) slot = 0;
    if (slot === 2 && !me.equip.gun) slot = 0;
    if (slot === 1 && !me.equip.sword) slot = 0;
    if (slot === 3) {
      const fr = TF.ITEMS[me.fruit];
      const beast = fr.type === 'beast' || S.transUntil > S.time;
      return { kind: 'fruit', slot, id: fr.id, it: fr, skills: fr.skills, m1: beast ? TF.M1.beast : TF.M1.fruit, color: fr.color };
    }
    const cat = ['style', 'sword', 'gun'][slot];
    const it = TF.ITEMS[me.equip[cat]];
    return { kind: cat, slot, id: it.id, it, skills: it.skills, m1: TF.M1[cat], color: it.color };
  }
  S.myWeapon = myWeapon;

  function moveInput() {
    let mx = 0, my = 0;
    if (!UI.typing()) {
      const k = S.keys;
      if (k.KeyW || k.ArrowUp) my -= 1;
      if (k.KeyS || k.ArrowDown) my += 1;
      if (k.KeyA || k.ArrowLeft) mx -= 1;
      if (k.KeyD || k.ArrowRight) mx += 1;
    }
    if (S.joy.active) { mx = S.joy.x; my = S.joy.y; }
    const len = Math.hypot(mx, my);
    if (len > 1) { mx /= len; my /= len; }
    return [mx, my];
  }

  function updateSelf(dt) {
    const sf = S.self;
    const me = S.me;
    if (!me || S.dead) { sf.moving = false; return; }
    const t = S.time;
    const sea = TF.SEAS[S.sea];
    const [mx, my] = moveInput();
    const water = TF.islandAt(S.sea, sf.x, sf.y) < 0;
    let spd = (water ? TF.SPEED.boat : TF.SPEED.land) * (me.spd || 1);
    if (S.slowUntil > t) spd *= 0.55;
    let vx = 0, vy = 0;
    if (t < sf.dashUntil) { vx = sf.dvx; vy = sf.dvy; }
    else if (S.stunUntil <= t) { vx = mx * spd; vy = my * spd; }
    vx += sf.kx; vy += sf.ky;
    const f = Math.exp(-10 * dt);
    sf.kx *= f; sf.ky *= f;
    if (Math.abs(sf.kx) + Math.abs(sf.ky) < 4) sf.kx = sf.ky = 0;
    sf.x = clamp(sf.x + vx * dt, 0, sea.w);
    sf.y = clamp(sf.y + vy * dt, 0, sea.h);
    sf.moving = Math.hypot(vx, vy) > 25;
    if (sf.moving) sf.moveAng = Math.atan2(vy, vx);
    // Aim: the mouse on desktop; on touch, the nearest enemy or where we walk.
    if (S.touch) {
      const tg = autoTarget(700);
      if (tg) S.aim = Math.atan2(tg.y - sf.y, tg.x - sf.x);
      else if (mx || my) S.aim = Math.atan2(my, mx);
    } else {
      const w = R.screenToWorld(S, S.mouse.x, S.mouse.y);
      S.aim = Math.atan2(w.y - (sf.y - 24), w.x - sf.x);
    }
    // Basic attack, predicted locally for melee.
    const attacking = S.mouse.down || S.touchAttack;
    if (attacking && t >= S.m1Next && S.stunUntil <= t) {
      const w = myWeapon();
      const m1 = w.m1;
      S.m1Next = t + m1.rate;
      const p = S.players.get(S.id);
      if (p) p.swingT = t;
      if (m1.t === 'melee') S.fx.push({ k: 'm1', o: S.id, a: S.aim, r: m1.rng * (S.transUntil > t ? 1.3 : 1), c: w.color, w: w.kind, t0: t });
    }
  }

  function autoTarget(range) {
    let best = null, bd = range;
    for (const m of S.mobs.values()) {
      const d = Math.hypot(m.x - S.self.x, m.y - S.self.y);
      if (d < bd) { bd = d; best = m; }
    }
    const me = S.me;
    if (me && me.pvp) {
      for (const p of S.players.values()) {
        if (p.id === S.id || !(p.f & 2) || p.f & 512 || p.f & 8 || (me.team === 'marine' && p.team === 1)) continue;
        const d = Math.hypot(p.x - S.self.x, p.y - S.self.y);
        if (d < bd) { bd = d; best = p; }
      }
    }
    return best;
  }

  function aimPoint() {
    if (S.touch) {
      const tg = autoTarget(800);
      if (tg) return { x: tg.x, y: tg.y };
      return { x: S.self.x + Math.cos(S.aim) * 300, y: S.self.y + Math.sin(S.aim) * 300 };
    }
    return R.screenToWorld(S, S.mouse.x, S.mouse.y);
  }

  function trySkill(k) {
    const me = S.me;
    if (!me || S.dead || S.stunUntil > S.time) return;
    const w = myWeapon();
    const sk = w.skills.find((s) => s.k === k);
    if (!sk) return;
    const mastery = me.mastery[w.id] || 0;
    if (mastery < TF.SKILL_UNLOCK[k]) { UI.toast(`${sk.n} unlocks at mastery ${TF.SKILL_UNLOCK[k]}.`, 'bad'); return; }
    const key = w.id + ':' + k;
    if ((S.cd[key] || 0) > S.time + 0.1) return;
    const cost = Math.round(me.men * TF.SKILL_ENERGY[k]);
    if (me.en < cost) { UI.toast('Not enough energy.', 'bad'); return; }
    const ap = aimPoint();
    const ang = Math.atan2(ap.y - S.self.y, ap.x - S.self.x);
    send({ t: 'sk', k, ax: Math.round(ap.x), ay: Math.round(ap.y) });
    let cd = sk.cd || 5;
    if (w.kind === 'fruit' && me.awake) cd *= 0.8;
    S.cd[key] = S.time + cd;
    S.cdSent[key] = S.time;
    me.en -= cost;
    const sf = S.self;
    if (sk.t === 'dash') {
      sf.dashUntil = S.time + sk.dur;
      sf.dvx = (Math.cos(ang) * sk.dist) / sk.dur;
      sf.dvy = (Math.sin(ang) * sk.dist) / sk.dur;
    } else if (sk.t === 'tele') {
      const d = Math.min(sk.rng, Math.hypot(ap.x - sf.x, ap.y - sf.y));
      const sea = TF.SEAS[S.sea];
      sf.x = clamp(sf.x + Math.cos(ang) * d, 0, sea.w);
      sf.y = clamp(sf.y + Math.sin(ang) * d, 0, sea.h);
    }
  }

  function tryDash() {
    const me = S.me;
    if (!me || S.dead || S.stunUntil > S.time || S.time < S.dashEnd) return;
    const D = me.ab.flash ? TF.DASH.flash : TF.DASH.base;
    const [mx, my] = moveInput();
    const a = mx || my ? Math.atan2(my, mx) : S.aim;
    const sf = S.self;
    sf.dashUntil = S.time + TF.DASH.dur;
    sf.dvx = (Math.cos(a) * D.dist) / TF.DASH.dur;
    sf.dvy = (Math.sin(a) * D.dist) / TF.DASH.dur;
    S.dashEnd = S.time + D.cd;
    S.dashSent = S.time;
    send({ t: 'dash' });
    S.fx.push({ k: 'dashfx', o: S.id, c: '#ffffff', t0: S.time, dur: 0.25 });
  }

  function setSlot(s) {
    if (!S.me) return;
    S.me.slot = s;
    send({ t: 'slot', s });
    UI.refresh();
  }

  function interact() {
    if (S.nearNpc >= 0) UI.openNpc(TF.NPCS[S.nearNpc]);
  }

  // ─── Per-frame updates ───────────────────────────────────────────────────
  function updateEntities(dt) {
    const k = 1 - Math.exp(-dt * 14);
    for (const p of S.players.values()) {
      p.flash = Math.max(0, (p.flash || 0) - dt * 4);
      if (p.id === S.id) {
        p.x = S.self.x; p.y = S.self.y; p.aim = S.aim; p.moving = S.self.moving; p.moveAng = S.self.moveAng;
        continue;
      }
      const dx = p.tx - p.x, dy = p.ty - p.y, d = Math.hypot(dx, dy);
      if (d > 600) { p.x = p.tx; p.y = p.ty; } else { p.x += dx * k; p.y += dy * k; }
      p.moving = d > 4;
      if (d > 4) p.moveAng = Math.atan2(dy, dx);
      p.aim = p.taim;
    }
    for (const m of S.mobs.values()) {
      m.flash = Math.max(0, m.flash - dt * 4);
      const dx = m.tx - m.x, dy = m.ty - m.y, d = Math.hypot(dx, dy);
      if (d > 600) { m.x = m.tx; m.y = m.ty; } else { m.x += dx * k; m.y += dy * k; }
      m.moving = d > 2;
      m.ang = m.tang;
    }
    // The nearest NPC within reach.
    let best = -1, bd = 120;
    for (const n of TF.NPCS) {
      if (n.sea !== S.sea) continue;
      const d = Math.hypot(n.x - S.self.x, n.y - S.self.y);
      if (d < bd) { bd = d; best = n.id; }
    }
    S.nearNpc = best;
  }

  function updateCamera(dt) {
    const { W, H } = R.size();
    const base = clamp(Math.min(W, H) / (S.touch ? 680 : 900), 0.42, 1.5);
    S.cam.zoom = base * S.cam.user;
    const k = 1 - Math.exp(-dt * 10);
    S.cam.x += (S.self.x - S.cam.x) * k;
    S.cam.y += (S.self.y - 30 - S.cam.y) * k;
    S.cam.shake = Math.max(0, S.cam.shake - dt * 40);
  }

  function sendInput() {
    if (S.time - S.sendAt < 1 / 30) return;
    S.sendAt = S.time;
    send({ t: 'in', x: Math.round(S.self.x * 10) / 10, y: Math.round(S.self.y * 10) / 10, a: Math.round(S.aim * 100) / 100, m1: !!(S.mouse.down || S.touchAttack) && !S.dead, pc: S.pc });
  }

  // On the login screen the camera drifts over the first sea.
  function idleCamera() {
    const t = S.time * 0.04;
    S.cam.x = 3200 + Math.cos(t) * 2200;
    S.cam.y = 3000 + Math.sin(t * 1.3) * 1800;
    S.self.x = S.cam.x; S.self.y = S.cam.y;
    const { W, H } = R.size();
    S.cam.zoom = clamp(Math.min(W, H) / 1100, 0.35, 1.2);
  }

  let last = performance.now();
  let pingAt = 0;
  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    S.time += dt;
    if (S.joined) {
      updateSelf(dt);
      updateEntities(dt);
      updateCamera(dt);
      sendInput();
      if (S.time > pingAt) { pingAt = S.time + 2; send({ t: 'ping', c: performance.now() }); }
    } else idleCamera();
    updateFx(dt);
    R.drawWorld(S, dt);
    if (S.joined) UI.frame(S, dt);
    requestAnimationFrame(frame);
  }

  // ─── Input wiring ────────────────────────────────────────────────────────
  function bindInput(canvas) {
    window.addEventListener('keydown', (e) => {
      if (UI.typing()) {
        if (e.code === 'Escape') UI.blurChat();
        return;
      }
      if (!S.joined) return;
      S.keys[e.code] = true;
      const map = { KeyZ: 'z', KeyX: 'x', KeyC: 'c', KeyV: 'v', KeyF: 'f' };
      if (map[e.code] && !e.repeat) { trySkill(map[e.code]); e.preventDefault(); return; }
      switch (e.code) {
        case 'Digit1': case 'Digit2': case 'Digit3': case 'Digit4': setSlot(+e.code.slice(5) - 1); break;
        case 'KeyQ': case 'Space': if (!e.repeat) tryDash(); e.preventDefault(); break;
        case 'KeyE': if (!e.repeat) interact(); break;
        case 'KeyK': UI.toggle('stats'); break;
        case 'KeyI': case 'KeyB': UI.toggle('bag'); break;
        case 'KeyM': UI.toggle('map'); break;
        case 'Tab': UI.toggle('top'); e.preventDefault(); break;
        case 'KeyH': UI.toggle('help'); break;
        case 'KeyP': send({ t: 'pvp', on: !(S.me && S.me.pvp) }); break;
        case 'Enter': UI.focusChat(); e.preventDefault(); break;
        case 'Escape': UI.close(); break;
      }
    });
    window.addEventListener('keyup', (e) => { S.keys[e.code] = false; });
    window.addEventListener('blur', () => { S.keys = {}; S.mouse.down = false; });
    canvas.addEventListener('mousemove', (e) => { S.mouse.x = e.clientX; S.mouse.y = e.clientY; });
    canvas.addEventListener('mousedown', (e) => { if (e.button === 0) { S.mouse.down = true; UI.blurChat(); } });
    window.addEventListener('mouseup', (e) => { if (e.button === 0) S.mouse.down = false; });
    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    canvas.addEventListener('wheel', (e) => {
      S.cam.user = clamp(S.cam.user * (e.deltaY > 0 ? 0.92 : 1.08), 0.6, 1.6);
      e.preventDefault();
    }, { passive: false });
    window.addEventListener('resize', () => R.resize());
    window.addEventListener('touchstart', () => { if (!S.touch) { S.touch = true; UI.enableTouch(); } }, { passive: true });
  }

  // ─── Boot ────────────────────────────────────────────────────────────────
  function token() {
    let t = null;
    try { t = localStorage.getItem('tf_token'); } catch (_) { /* private mode */ }
    if (!t || t.length < 16) {
      const b = new Uint8Array(16);
      crypto.getRandomValues(b);
      t = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
      try { localStorage.setItem('tf_token', t); } catch (_) { /* private mode */ }
    }
    return t;
  }

  window.Game = {
    send, trySkill, tryDash, setSlot, interact, myWeapon,
    play(name, team) {
      S.name = name; S.team = team; S.token = token(); S.loginErr = '';
      try { localStorage.setItem('tf_name', name); localStorage.setItem('tf_team', team); } catch (_) { /* private mode */ }
      if (S.ws) { S.ws.onclose = null; S.ws.close(); }
      connect();
    },
  };

  window.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('game');
    R.init(canvas);
    UI.init(S);
    bindInput(canvas);
    requestAnimationFrame(frame);
  });
})();
