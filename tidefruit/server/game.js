'use strict';
/*
 * The authoritative simulation. Clients send where they are and what they
 * pressed; the server decides what got hit, who died, and what anybody earned.
 *
 * Movement is the one thing the client leads on, so walking feels instant. The
 * server checks every step against a distance budget (speed × time, plus what
 * dashes and knockback grant) and pulls a client back when it overspends.
 */
const crypto = require('crypto');
const TF = require('../shared/tf.js');
const { clamp, dist, angDiff } = TF;

const VIEW_R = 1700;
const T = () => performance.now() / 1000;
const r2 = (n) => Math.round(n * 100) / 100;
const sha = (s) => crypto.createHash('sha256').update(String(s)).digest('hex');
const NAME_RE = /^[A-Za-z0-9_]{3,16}$/;
const STATS = ['melee', 'defense', 'sword', 'gun', 'fruit'];

const CODES = {
  TIDES2X: { desc: '2× XP for 30 minutes', apply: (p) => { p.s.x2Until = Math.max(Date.now(), p.s.x2Until || 0) + 30 * 60 * 1000; } },
  SEAFRUIT: { desc: '$25,000', apply: (p) => { p.s.beli += 25000; } },
  FRESHSTART: { desc: 'a free stat reset', apply: (p, g) => g.resetStats(p) },
  FIRSTSAIL: { desc: 'a random fruit', can: (p) => p.s.fruits.length < TF.FRUIT_INV_CAP || 'Make room in your fruit storage first.',
    apply: (p, g) => g.giveFruit(p, TF.rollFruit().id) },
};

function freshSave(name, team) {
  return {
    v: 1, name, team, tokenHash: '', level: 1, xp: 0,
    stats: { melee: 0, defense: 0, sword: 0, gun: 0, fruit: 0 },
    beli: 0, frags: 0, bounty: 0, fruit: null, fruitAwake: false, fruits: [],
    owned: ['st_brawler', 'sw_drift'], equip: { style: 'st_brawler', sword: 'sw_drift', gun: null },
    slot: 1, mastery: {}, abilities: {}, quest: null, sea: 0, spawn: [0, 0], codes: [],
    gachaAt: 0, x2Until: 0, created: Date.now(), seen: Date.now(), kills: 0, deaths: 0,
  };
}
// Older saves pick up any field added since they were written.
function migrate(s) {
  const f = freshSave(s.name, s.team);
  for (const k of Object.keys(f)) if (s[k] === undefined) s[k] = f[k];
  for (const k of Object.keys(f.stats)) if (typeof s.stats[k] !== 'number') s.stats[k] = 0;
  if (!TF.SEAS[s.sea]) s.sea = 0;
  s.owned = s.owned.filter((id) => TF.ITEMS[id]);
  s.fruits = s.fruits.filter((id) => TF.ITEMS[id]);
  if (s.fruit && !TF.ITEMS[s.fruit]) s.fruit = null;
  if (!s.owned.includes('st_brawler')) s.owned.unshift('st_brawler');
  for (const cat of ['style', 'sword', 'gun']) {
    const it = TF.ITEMS[s.equip[cat]];
    if (!it || it.cat !== cat || !s.owned.includes(it.id)) s.equip[cat] = cat === 'style' ? 'st_brawler' : null;
  }
  return s;
}

// ═══════════════════════════════════════════════════════════════════════════
class Game {
  constructor(store) {
    this.store = store;
    this.players = new Map();
    this.byName = new Map();
    this.nextId = 1;
    this.tickN = 0;
    this.lastT = T();
    this.seas = TF.SEAS.map((def) => new Sea(this, def));
    this.stock = [];
    this.stockUntil = 0;
    this.rollStock();
    this.lb = { level: [], bounty: [] };
    this.lbAt = 0;
  }

  id() { return this.nextId++; }

  // ─── Connections ─────────────────────────────────────────────────────────
  connect(conn) {
    const c = { conn, p: null, n: 0, at: T() };
    conn.on('message', (raw) => {
      const t = T();
      if (t - c.at > 1) { c.at = t; c.n = 0; }
      if (++c.n > 120) { if (c.n > 400) conn.close(1008, 'flood'); return; }
      let m;
      try { m = JSON.parse(raw); } catch (_) { return; }
      if (!m || typeof m.t !== 'string') return;
      if (!c.p) { if (m.t === 'hello') this.hello(c, m); return; }
      try { this.handle(c.p, m); } catch (e) { console.error('handler', m.t, e); }
    });
    conn.on('close', () => { if (c.p) this.leave(c.p); });
  }

  hello(c, m) {
    const name = String(m.name || '').trim();
    const token = String(m.token || '');
    if (!NAME_RE.test(name)) return this.reject(c, 'Names are 3–16 letters, digits or _.');
    if (token.length < 16 || token.length > 128) return this.reject(c, 'Bad session token. Reload the page.');
    const key = name.toLowerCase();
    let save = this.store.get(key);
    if (save) {
      if (save.tokenHash !== sha(token)) return this.reject(c, 'That name belongs to another sailor. Pick a different one.');
      migrate(save);
    } else {
      const team = m.team === 'marine' ? 'marine' : 'pirate';
      save = freshSave(name, team);
      save.tokenHash = sha(token);
      this.store.set(key, save);
    }
    const old = this.byName.get(key);
    if (old) { this.note(old, 'Signed in from somewhere else.', 'bad'); old.conn.close(4000, 'replaced'); this.leave(old); }

    const p = this.makePlayer(c.conn, save);
    c.p = p;
    this.players.set(p.id, p);
    this.byName.set(key, p);
    this.seas[save.sea].players.add(p);
    this.placeAtSpawn(p);
    p.send({
      t: 'welcome', id: p.id, sea: save.sea, x: p.x, y: p.y, pc: p.pc, me: this.meMsg(p, T()),
      stock: this.stock, stockLeft: Math.max(0, (this.stockUntil - Date.now()) / 1000) | 0, lb: this.lb,
    });
    this.broadcastChat(null, `${save.name} set sail${save.created > Date.now() - 5000 ? ' for the first time' : ''}.`, true);
  }

  reject(c, msg) { c.conn.send(JSON.stringify({ t: 'error', msg })); c.conn.close(4001, 'rejected'); }

  makePlayer(conn, s) {
    const p = {
      id: this.id(), conn, s, gone: false,
      x: 0, y: 0, aim: 0, inWater: false, m1Hold: false, m1At: 0,
      hp: 1, maxHp: 1, en: 1, maxEn: 1, dead: false, respawnAt: 0, protUntil: 0,
      cds: {}, buffs: [], shield: 0, shieldUntil: 0, transUntil: 0, dashCdUntil: 0, dashUntil: 0,
      stunUntil: 0, slowUntil: 0, burn: null, lastHurt: 0, lastPvp: 0,
      budget: 0, lastMoveT: T(), pc: 0, lastCorr: 0,
      pvp: false, dirty: true, meAt: 0, chatAt: 0,
    };
    p.send = (obj) => conn.send(typeof obj === 'string' ? obj : JSON.stringify(obj));
    this.recompute(p);
    p.hp = p.maxHp; p.en = p.maxEn;
    return p;
  }

  leave(p) {
    if (p.gone) return;
    p.gone = true;
    p.s.seen = Date.now();
    this.players.delete(p.id);
    const key = p.s.name.toLowerCase();
    if (this.byName.get(key) === p) this.byName.delete(key);
    this.seas[p.s.sea].players.delete(p);
    this.store.markDirty();
  }

  // ─── Message dispatch ────────────────────────────────────────────────────
  handle(p, m) {
    switch (m.t) {
      case 'in': return this.onInput(p, m);
      case 'sk': return this.useSkill(p, String(m.k), +m.ax, +m.ay);
      case 'dash': return this.onDash(p);
      case 'slot': { const s = m.s | 0; if (s >= 0 && s <= 3) { p.s.slot = s; p.dirty = true; } return; }
      case 'stat': return this.addStat(p, String(m.k), m.n | 0);
      case 'equip': return this.equip(p, String(m.id));
      case 'eat': return this.eatFruit(p, m.i | 0);
      case 'drop': return this.dropFruit(p, m.i | 0);
      case 'npc': return this.npcAction(p, m);
      case 'pvp': return this.setPvp(p, !!m.on);
      case 'chat': return this.chat(p, String(m.m || ''));
      case 'code': return this.redeem(p, String(m.c || ''));
      case 'ping': return p.send({ t: 'pong', c: m.c });
    }
  }

  // ─── Derived stats ───────────────────────────────────────────────────────
  recompute(p) {
    const s = p.s;
    p.maxHp = TF.maxHp(s.level, s.stats.defense);
    p.maxEn = TF.maxEn(s.level, s.stats.defense);
    p.hp = Math.min(p.hp, p.maxHp);
    p.en = Math.min(p.en, p.maxEn);
  }

  pointsLeft(p) {
    const st = p.s.stats;
    return TF.pointsTotal(p.s.level) - (st.melee + st.defense + st.sword + st.gun + st.fruit);
  }

  transformed(p, t) { return t < p.transUntil; }

  speedOf(p, t, water) {
    let v = water ? TF.SPEED.boat : TF.SPEED.land;
    for (const b of p.buffs) if (b.spd) v *= b.spd;
    if (this.transformed(p, t)) v *= TF.TRANSFORM.spd;
    return v;
  }

  // The weapon in the active slot, falling back to fists for an empty slot.
  weapon(p) {
    const s = p.s;
    let slot = s.slot;
    if (slot === 3 && !s.fruit) slot = 0;
    if (slot === 2 && !s.equip.gun) slot = 0;
    if (slot === 1 && !s.equip.sword) slot = 0;
    if (slot === 3) {
      const fr = TF.ITEMS[s.fruit];
      const beast = fr.type === 'beast';
      return { kind: 'fruit', id: fr.id, it: fr, base: TF.fruitBase(fr, s.level), stat: s.stats.fruit,
        skills: fr.skills, m1: beast ? TF.M1.beast : TF.M1.fruit, color: fr.color, mastery: s.mastery[fr.id] || 0 };
    }
    const cat = slot === 0 ? 'style' : slot === 1 ? 'sword' : 'gun';
    const it = TF.ITEMS[slot === 0 ? s.equip.style : slot === 1 ? s.equip.sword : s.equip.gun];
    const stat = slot === 0 ? s.stats.melee : slot === 1 ? s.stats.sword : s.stats.gun;
    return { kind: cat, id: it.id, it, base: it.base, stat, skills: it.skills, m1: TF.M1[cat], color: it.color, mastery: s.mastery[it.id] || 0 };
  }

  calcDmg(p, w, t) {
    let d = w.base * TF.statMul(w.stat) * (1 + Math.min(TF.MASTERY_CAP, w.mastery) * 0.0005);
    if (p.s.abilities.aura) d *= 1.1;
    if (w.kind === 'fruit' && p.s.fruitAwake) d *= 1.25;
    if (this.transformed(p, t)) d *= TF.TRANSFORM.dmg;
    for (const b of p.buffs) if (b.dmg) d *= b.dmg;
    return d;
  }

  // ─── Movement ────────────────────────────────────────────────────────────
  onInput(p, m) {
    if (Number.isFinite(m.a)) p.aim = m.a;
    p.m1Hold = !!m.m1;
    if (p.dead || !Number.isFinite(m.x) || !Number.isFinite(m.y)) return;
    if ((m.pc | 0) !== p.pc) return; // sent before our last correction landed
    const t = T();
    const sea = TF.SEAS[p.s.sea];
    const dt = clamp(t - p.lastMoveT, 0, 1);
    p.lastMoveT = t;
    const nx = clamp(m.x, 0, sea.w), ny = clamp(m.y, 0, sea.h);
    const water = p.inWater || TF.islandAt(p.s.sea, nx, ny) < 0;
    const spd = this.speedOf(p, t, water);
    const cap = spd * 0.5 + 120;
    const regen = t < p.stunUntil ? 0 : spd * 1.35 * dt;
    if (p.budget < cap) p.budget = Math.min(cap, p.budget + regen);
    else p.budget -= (p.budget - cap) * Math.min(1, dt * 0.6);
    const d = dist(p.x, p.y, nx, ny);
    if (d <= p.budget) {
      p.budget -= d;
      p.x = nx; p.y = ny;
    } else {
      const k = p.budget / d;
      p.x += (nx - p.x) * k; p.y += (ny - p.y) * k;
      p.budget = 0;
      if (t - p.lastCorr > 0.25) this.correct(p, t);
    }
    p.inWater = TF.islandAt(p.s.sea, p.x, p.y) < 0;
  }

  correct(p, t) {
    p.pc++;
    p.lastCorr = t;
    p.send({ t: 'pos', x: Math.round(p.x), y: Math.round(p.y), pc: p.pc });
  }

  teleport(p, x, y) {
    p.x = x; p.y = y; p.budget = 0;
    p.inWater = TF.islandAt(p.s.sea, x, y) < 0;
    this.correct(p, T());
  }

  onDash(p) {
    const t = T();
    const D = p.s.abilities.flash ? TF.DASH.flash : TF.DASH.base;
    if (p.dead || t < p.dashCdUntil - 0.15 || t < p.stunUntil) return;
    p.dashCdUntil = t + D.cd;
    p.dashUntil = t + TF.DASH.dur;
    p.budget += D.dist + 40;
    p.dirty = true;
  }

  // ─── Combat: basic attacks and skills ────────────────────────────────────
  doM1(p, t) {
    const w = this.weapon(p);
    const m1 = this.transformed(p, t) && w.kind === 'fruit' ? TF.M1.beast : w.m1;
    p.m1At = t + m1.rate;
    const sea = this.seas[p.s.sea];
    const dmg = this.calcDmg(p, w, t) * m1.m;
    if (m1.t === 'melee') {
      const reach = m1.rng * (this.transformed(p, t) ? 1.3 : 1);
      sea.eachTarget('p', p, (tg, isP) => {
        const d = dist(p.x, p.y, tg.x, tg.y);
        const tr = isP ? TF.PLAYER_R : tg.r;
        if (d > reach + tr) return;
        if (d > tr + 10 && Math.abs(angDiff(Math.atan2(tg.y - p.y, tg.x - p.x), p.aim)) > m1.arc / 2) return;
        sea.hit({ side: 'p', owner: p, dmg, wid: w.id, st: null, x: p.x, y: p.y }, tg, isP, 1, p.x, p.y, 70);
      });
      sea.emit({ k: 'm1', o: p.id, a: r2(p.aim), r: reach, c: w.color, w: w.kind }, p.x, p.y);
    } else {
      sea.addProj(p, 'p', p.x, p.y, p.aim, m1.sp, m1.r, m1.rng, dmg, 0, 0, null, w.id, w.color, m1.sh, p.id);
    }
  }

  useSkill(p, key, ax, ay) {
    const t = T();
    if (p.dead || t < p.stunUntil || !TF.SKILL_KEYS.includes(key)) return;
    if (!Number.isFinite(ax) || !Number.isFinite(ay)) return;
    const w = this.weapon(p);
    const sk = w.skills.find((s) => s.k === key);
    if (!sk) return;
    if (w.mastery < TF.SKILL_UNLOCK[key]) return this.note(p, `${sk.n} unlocks at ${TF.SKILL_UNLOCK[key]} mastery.`, 'bad');
    const cdKey = w.id + ':' + key;
    if ((p.cds[cdKey] || 0) > t + 0.1) return;
    const cost = Math.round(p.maxEn * TF.SKILL_ENERGY[key]);
    if (p.en < cost) return this.note(p, 'Not enough energy.', 'bad');
    p.en -= cost;
    let cd = sk.cd || 5;
    if (w.kind === 'fruit' && p.s.fruitAwake) cd *= 0.8;
    p.cds[cdKey] = t + cd;
    p.dirty = true;
    const ang = Math.atan2(ay - p.y, ax - p.x);
    const dmg = this.calcDmg(p, w, t) * (sk.m || 0);
    this.seas[p.s.sea].cast(p, 'p', sk, dmg, ang, ax, ay, w.id, w.color);
  }

  // Damage to a player, from a mob or (in PvP) another player.
  damagePlayer(tp, amount, src, side, st, ox, oy, knockDefault) {
    const t = T();
    if (tp.dead || tp.gone || t < tp.protUntil) return;
    const sea = this.seas[tp.s.sea];
    const fr = tp.s.fruit && TF.ITEMS[tp.s.fruit];
    const elemental = fr && fr.type === 'elemental';
    let d = amount;
    if (side === 'p') {
      d *= TF.PVP_SCALE;
      if (elemental && !src.s.abilities.aura) d *= 0.6;
      src.lastPvp = t; tp.lastPvp = t;
    } else if (elemental && src.mt && !src.mt.boss && !src.mt.seaBeast && Math.random() < 0.25) {
      sea.emit({ k: 'dmg', x: tp.x, y: tp.y - 30, v: 'PHASE', c: 4 }, tp.x, tp.y);
      return;
    }
    if (tp.s.abilities.instinct && Math.random() < 0.12) {
      sea.emit({ k: 'dmg', x: tp.x, y: tp.y - 30, v: 'DODGE', c: 4 }, tp.x, tp.y);
      return;
    }
    if (this.transformed(tp, t)) d *= 1 - TF.TRANSFORM.dr;
    for (const b of tp.buffs) if (b.dr) d *= 1 - b.dr;
    d = Math.max(1, Math.round(d * (0.93 + Math.random() * 0.14)));
    if (tp.shield > 0 && t < tp.shieldUntil) {
      const a = Math.min(tp.shield, d);
      tp.shield -= a; d -= a;
      if (d <= 0) { sea.emit({ k: 'dmg', x: tp.x, y: tp.y - 30, v: 'BLOCK', c: 4 }, tp.x, tp.y); return; }
    }
    tp.hp -= d;
    tp.lastHurt = t;
    tp.dirty = true;
    sea.emit({ k: 'dmg', x: Math.round(tp.x), y: Math.round(tp.y - 30), v: d, c: 2, o: tp.id }, tp.x, tp.y);
    if (st) {
      if (st.burn) tp.burn = { until: t + st.burn, dps: amount * 0.1 * (side === 'p' ? TF.PVP_SCALE : 1), src, side, acc: 0 };
      if (st.slow) tp.slowUntil = Math.max(tp.slowUntil, t + st.slow);
      if (st.stun) tp.stunUntil = Math.max(tp.stunUntil, t + st.stun * (side === 'p' ? 0.6 : 1));
    }
    const knock = (st && st.knock) || knockDefault || 0;
    if (knock && Number.isFinite(ox)) {
      const a = Math.atan2(tp.y - oy, tp.x - ox);
      this.knock(tp, Math.cos(a) * knock, Math.sin(a) * knock);
    }
    if (tp.hp <= 0) this.killPlayer(tp, src, side);
  }

  // Players move themselves, so knockback is a request to the client to slide,
  // plus the movement budget that lets that slide through validation.
  knock(p, kx, ky) {
    p.budget += Math.hypot(kx, ky) * 1.1 + 20;
    p.send({ t: 'kb', x: Math.round(kx), y: Math.round(ky) });
  }

  killPlayer(p, src, side) {
    const t = T();
    const sea = this.seas[p.s.sea];
    p.dead = true; p.hp = 0; p.respawnAt = t + 3.5;
    p.buffs = []; p.transUntil = 0; p.burn = null; p.shield = 0; p.stunUntil = 0; p.slowUntil = 0;
    p.s.deaths++;
    p.dirty = true;
    sea.emit({ k: 'die', x: Math.round(p.x), y: Math.round(p.y), r: 26, c: '#ffffff' }, p.x, p.y);
    let by = src && (src.s ? src.s.name : src.mt ? src.mt.name : '');
    if (side === 'p' && src && src.s) {
      const gain = Math.max(250, Math.round(p.s.bounty * 0.1), p.s.level * 25);
      src.s.bounty += gain;
      src.s.kills++;
      p.s.bounty = Math.max(0, p.s.bounty - Math.round(gain * 0.5));
      src.dirty = true;
      const word = src.s.team === 'marine' ? 'honor' : 'bounty';
      this.note(src, `You defeated ${p.s.name}. +$${gain.toLocaleString()} ${word}.`, 'good');
      sea.broadcastChat(`⚔ ${src.s.name} defeated ${p.s.name}`, true);
    }
    p.send({ t: 'dead', by: by || 'the sea', in: 3.5 });
  }

  respawn(p, t) {
    p.dead = false;
    this.recompute(p);
    p.hp = p.maxHp; p.en = p.maxEn;
    p.protUntil = t + 3;
    this.placeAtSpawn(p);
    p.dirty = true;
  }

  placeAtSpawn(p) {
    const s = p.s;
    const seaDef = TF.SEAS[s.sea];
    const isle = s.spawn && s.spawn[0] === s.sea && seaDef.islands[s.spawn[1]] ? s.spawn[1] : 0;
    const isl = seaDef.islands[isle];
    let x = isl.x, y = isl.y;
    if (!isl.hub) { const q = TF.NPCS[isl.npcs[0]]; x = q.x + (isl.x - q.x) * 0.25; y = q.y + (isl.y - q.y) * 0.25; }
    const a = Math.random() * Math.PI * 2;
    this.teleport(p, Math.round(x + Math.cos(a) * 50), Math.round(y + Math.sin(a) * 50));
  }

  // ─── Rewards ─────────────────────────────────────────────────────────────
  giveXp(p, amount) {
    const s = p.s;
    if ((s.x2Until || 0) > Date.now()) amount *= 2;
    if (s.level >= TF.MAX_LEVEL) return;
    s.xp += Math.round(amount);
    const before = s.level;
    while (s.level < TF.MAX_LEVEL && s.xp >= TF.xpNext(s.level)) { s.xp -= TF.xpNext(s.level); s.level++; }
    if (s.level >= TF.MAX_LEVEL) s.xp = 0;
    if (s.level !== before) {
      this.recompute(p);
      p.hp = p.maxHp; p.en = p.maxEn;
      const sea = this.seas[s.sea];
      sea.emit({ k: 'lvl', o: p.id, lv: s.level }, p.x, p.y);
      for (const mark of [700, 1500, 2300]) {
        if (before < mark && s.level >= mark) {
          const nxt = TF.SEAS.findIndex((x) => x.minLevel === mark);
          this.note(p, `Level ${mark}! The ${TF.SEAS[nxt].name} is open — talk to a Ferry Captain.`, 'good');
        }
      }
      if (Math.floor(before / 500) !== Math.floor(s.level / 500) || s.level === TF.MAX_LEVEL) {
        this.broadcastChat(null, s.level === TF.MAX_LEVEL ? `👑 ${s.name} reached the max level, ${TF.MAX_LEVEL}!` : `${s.name} reached level ${s.level}!`, true);
      }
    }
    p.dirty = true;
  }

  addMastery(p, wid, amt) {
    if (!wid || !(amt > 0)) return;
    const m = p.s.mastery;
    const before = m[wid] || 0;
    if (before >= TF.MASTERY_CAP) return;
    m[wid] = Math.min(TF.MASTERY_CAP, Math.round((before + amt) * 100) / 100);
    for (const k of TF.SKILL_KEYS) {
      const need = TF.SKILL_UNLOCK[k];
      if (before < need && m[wid] >= need) {
        const it = TF.ITEMS[wid];
        const sk = it && it.skills.find((s) => s.k === k);
        if (sk) this.note(p, `New skill unlocked: [${k.toUpperCase()}] ${sk.n}`, 'good');
      }
    }
    p.dirty = true;
  }

  giveFruit(p, fid, how) {
    const s = p.s;
    if (s.fruits.length >= TF.FRUIT_INV_CAP) { this.note(p, 'Fruit storage is full.', 'bad'); return false; }
    s.fruits.push(fid);
    const fr = TF.ITEMS[fid];
    this.note(p, `You got the ${fr.name}! Open your bag [I] to eat it.`, 'good');
    if (how && (fr.rarity === 'legendary' || fr.rarity === 'mythical')) this.broadcastChat(null, `${s.name} ${how} a ${TF.RARITY[fr.rarity].name} ${fr.name}!`, true);
    p.dirty = true;
    return true;
  }

  // ─── Stats, gear and fruit ──────────────────────────────────────────────
  addStat(p, k, n) {
    if (!STATS.includes(k) || n <= 0) return;
    const add = Math.min(n, this.pointsLeft(p), TF.STAT_CAP - p.s.stats[k]);
    if (add <= 0) return;
    p.s.stats[k] += add;
    this.recompute(p);
    p.dirty = true;
  }

  resetStats(p) {
    for (const k of Object.keys(p.s.stats)) p.s.stats[k] = 0;
    this.recompute(p);
    p.dirty = true;
  }

  equip(p, id) {
    const it = TF.ITEMS[id];
    if (!it || it.cat === 'fruit' || !p.s.owned.includes(id)) return;
    p.s.equip[it.cat] = id;
    p.s.slot = it.cat === 'style' ? 0 : it.cat === 'sword' ? 1 : 2;
    p.dirty = true;
  }

  eatFruit(p, i) {
    const s = p.s;
    const fid = s.fruits[i];
    if (!fid || p.dead) return;
    s.fruits.splice(i, 1);
    const old = s.fruit && TF.ITEMS[s.fruit];
    s.fruit = fid;
    s.fruitAwake = false;
    s.slot = 3;
    p.transUntil = 0;
    for (const k of Object.keys(p.cds)) if (k.startsWith('fr_')) delete p.cds[k];
    const fr = TF.ITEMS[fid];
    this.note(p, `You ate the ${fr.name}${old ? ` — the ${old.name} is gone` : ''}. Press 4 to use it.`, 'good');
    this.seas[s.sea].emit({ k: 'buff', o: p.id, c: fr.color, dur: 1.2 }, p.x, p.y);
    p.dirty = true;
  }

  dropFruit(p, i) {
    const fid = p.s.fruits[i];
    if (!fid || p.dead) return;
    p.s.fruits.splice(i, 1);
    const sea = this.seas[p.s.sea];
    sea.addDrop(fid, p.x + Math.cos(p.aim) * 50, p.y + Math.sin(p.aim) * 50, p.id, 1800);
    p.dirty = true;
  }

  setPvp(p, on) {
    const t = T();
    if (on && p.s.level < TF.PVP_MIN_LEVEL) return this.note(p, `PvP opens at level ${TF.PVP_MIN_LEVEL}.`, 'bad');
    if (!on && t - p.lastPvp < 10) return this.note(p, 'You were just in a fight. Wait a moment.', 'bad');
    p.pvp = on;
    p.dirty = true;
    this.note(p, on ? 'PvP on. Other players with PvP on can attack you outside safe zones.' : 'PvP off.', on ? 'bad' : 'good');
  }

  redeem(p, raw) {
    const code = raw.trim().toUpperCase();
    const c = CODES[code];
    if (!c) return this.note(p, 'That code does not exist.', 'bad');
    if (p.s.codes.includes(code)) return this.note(p, 'You already used that code.', 'bad');
    const ok = c.can ? c.can(p) : true;
    if (ok !== true) return this.note(p, ok, 'bad');
    p.s.codes.push(code);
    c.apply(p, this);
    this.note(p, `Code redeemed: ${c.desc}!`, 'good');
    p.dirty = true;
  }

  // ─── NPCs ────────────────────────────────────────────────────────────────
  npcAction(p, m) {
    const npc = TF.NPCS[m.n | 0];
    const s = p.s;
    if (!npc || npc.sea !== s.sea || p.dead) return;
    if (dist(p.x, p.y, npc.x, npc.y) > 200) return this.note(p, 'Walk closer to talk.', 'bad');
    const isl = TF.SEAS[s.sea].islands[npc.isle];
    const a = String(m.a || '');
    const pay = (beli, frags) => {
      if (s.beli < beli) { this.note(p, `You need $${beli.toLocaleString()}.`, 'bad'); return false; }
      if (frags && s.frags < frags) { this.note(p, `You need ${frags.toLocaleString()} fragments.`, 'bad'); return false; }
      s.beli -= beli; if (frags) s.frags -= frags;
      return true;
    };
    switch (npc.kind) {
      case 'quest': {
        if (a === 'spawn') { s.spawn = [s.sea, npc.isle]; this.note(p, `Spawn point set to ${isl.name}.`, 'good'); break; }
        if (a === 'abandon') { s.quest = null; this.note(p, 'Quest abandoned.'); break; }
        if (a !== 'accept') return;
        const choices = [isl.mobs[0], isl.mobs[1], isl.boss];
        const type = choices[m.i | 0];
        if (type === undefined) return;
        const mt = TF.MOB_TYPES[type];
        if (s.level < mt.level) return this.note(p, `Reach level ${mt.level} first.`, 'bad');
        s.quest = { mob: type, need: mt.boss ? 1 : TF.questCount(s.sea), have: 0 };
        s.spawn = [s.sea, npc.isle];
        this.note(p, `Quest: defeat ${mt.boss ? mt.name : s.quest.need + ' ' + mt.name}. Spawn set here.`, 'good');
        break;
      }
      case 'fruit': {
        const fid = String(m.id);
        if (a !== 'buy' || !this.stock.includes(fid)) return;
        if (s.fruits.length >= TF.FRUIT_INV_CAP) return this.note(p, 'Fruit storage is full.', 'bad');
        if (!pay(TF.ITEMS[fid].price)) return;
        this.giveFruit(p, fid, 'bought');
        break;
      }
      case 'gacha': {
        if (a !== 'roll') return;
        const wait = (s.gachaAt || 0) - Date.now();
        if (wait > 0) return this.note(p, `The Mystic needs ${Math.ceil(wait / 60000)} more minutes.`, 'bad');
        if (s.fruits.length >= TF.FRUIT_INV_CAP) return this.note(p, 'Fruit storage is full.', 'bad');
        if (!pay(TF.gachaCost(s.level))) return;
        s.gachaAt = Date.now() + 20 * 60 * 1000;
        this.giveFruit(p, TF.rollFruit().id, 'rolled');
        break;
      }
      case 'sword': case 'gun': case 'style': {
        const it = TF.ITEMS[String(m.id)];
        if (a !== 'buy' || !it || it.cat !== npc.kind || it.drop || it.sea !== s.sea || s.owned.includes(it.id)) return;
        if (it.minLevel && s.level < it.minLevel) return this.note(p, `Requires level ${it.minLevel}.`, 'bad');
        if (!pay(it.price, it.frags)) return;
        s.owned.push(it.id);
        this.equip(p, it.id);
        this.note(p, `Bought ${it.name}.`, 'good');
        break;
      }
      case 'ability': {
        const ab = TF.ABILITIES.find((x) => x.id === m.id);
        if (a !== 'buy' || !ab || s.abilities[ab.id]) return;
        if (!pay(ab.price)) return;
        s.abilities[ab.id] = true;
        this.note(p, `Learned ${ab.name}.`, 'good');
        break;
      }
      case 'ferry': {
        const to = m.sea | 0;
        if (a !== 'travel' || !TF.SEAS[to] || to === s.sea) return;
        if (s.level < TF.SEAS[to].minLevel) return this.note(p, `The ${TF.SEAS[to].name} needs level ${TF.SEAS[to].minLevel}.`, 'bad');
        this.changeSea(p, to);
        return;
      }
      case 'reset': {
        if (a !== 'reset') return;
        if (!pay(TF.resetCost(s.level))) return;
        this.resetStats(p);
        this.note(p, 'Stats refunded. Spend them again in the Stats menu [K].', 'good');
        break;
      }
      case 'awaken': {
        if (a !== 'awaken' || !s.fruit || s.fruitAwake) return;
        const fr = TF.ITEMS[s.fruit];
        if (!pay(0, TF.RARITY[fr.rarity].awaken)) return;
        s.fruitAwake = true;
        this.note(p, `Your ${fr.name} is awakened: +25% damage, faster cooldowns.`, 'good');
        break;
      }
      default: return;
    }
    p.dirty = true;
  }

  changeSea(p, to) {
    const from = this.seas[p.s.sea];
    from.players.delete(p);
    p.s.sea = to;
    p.s.quest = null;
    p.s.spawn = [to, 0];
    this.seas[to].players.add(p);
    p.transUntil = 0; p.burn = null;
    this.placeAtSpawn(p);
    p.protUntil = T() + 3;
    p.send({ t: 'sea', sea: to, x: p.x, y: p.y, pc: p.pc });
    this.note(p, `Welcome to the ${TF.SEAS[to].name}.`, 'good');
    p.dirty = true;
  }

  rollStock() {
    const pick = new Set();
    let guard = 0;
    while (pick.size < 6 && guard++ < 500) pick.add(TF.rollFruit().id);
    this.stock = [...pick].sort((a, b) => TF.ITEMS[a].price - TF.ITEMS[b].price);
    this.stockUntil = Date.now() + 15 * 60 * 1000;
    this.broadcast({ t: 'stock', ids: this.stock, left: 900 });
  }

  // ─── Chat and notices ────────────────────────────────────────────────────
  chat(p, raw) {
    const t = T();
    const m = raw.replace(/[\u0000-\u001f]/g, '').trim().slice(0, 140);
    if (!m || t - p.chatAt < 0.8) return;
    p.chatAt = t;
    if (m.startsWith('/')) return this.command(p, m);
    this.broadcast({ t: 'chat', n: p.s.name, team: p.s.team, lv: p.s.level, m });
  }

  command(p, m) {
    const [cmd] = m.slice(1).split(/\s+/);
    if (cmd === 'who') {
      const names = [...this.players.values()].map((q) => `${q.s.name} (${q.s.level})`);
      return this.note(p, `${names.length} online: ${names.slice(0, 30).join(', ')}`);
    }
    if (cmd === 'stuck') { this.placeAtSpawn(p); return; }
    this.note(p, 'Commands: /who, /stuck');
  }

  note(p, m, c) { p.send({ t: 'note', m, c: c || '' }); }

  broadcast(obj) {
    const s = JSON.stringify(obj);
    for (const p of this.players.values()) p.send(s);
  }

  broadcastChat(_unused, m, sys) { this.broadcast({ t: 'chat', sys: sys ? 1 : 0, m }); }

  // ─── Private state ───────────────────────────────────────────────────────
  meMsg(p, t) {
    const s = p.s;
    const cds = {};
    for (const [k, v] of Object.entries(p.cds)) if (v > t) cds[k] = r2(v - t);
    let spd = this.transformed(p, t) ? TF.TRANSFORM.spd : 1;
    for (const b of p.buffs) if (b.spd) spd *= b.spd;
    return {
      t: 'me', name: s.name, team: s.team, lv: s.level, xp: s.xp, xn: TF.xpNext(s.level), pts: this.pointsLeft(p),
      st: s.stats, beli: s.beli, frags: s.frags, bounty: s.bounty, fruit: s.fruit, awake: s.fruitAwake,
      fruits: s.fruits, owned: s.owned, equip: s.equip, slot: s.slot, mastery: s.mastery, ab: s.abilities,
      q: s.quest, sea: s.sea, spawn: s.spawn, cds, hp: Math.round(p.hp), mhp: p.maxHp, en: Math.round(p.en), men: p.maxEn,
      pvp: p.pvp, stun: r2(Math.max(0, p.stunUntil - t)), slow: r2(Math.max(0, p.slowUntil - t)),
      spd: r2(spd),
      tr: r2(Math.max(0, p.transUntil - t)), x2: Math.max(0, ((s.x2Until || 0) - Date.now()) / 1000) | 0,
      gacha: Math.max(0, ((s.gachaAt || 0) - Date.now()) / 1000) | 0, dash: r2(Math.max(0, p.dashCdUntil - t)),
      shield: Math.round(p.shieldUntil > t ? p.shield : 0), kills: s.kills, deaths: s.deaths, codes: s.codes.length,
    };
  }

  // ─── Main loop ───────────────────────────────────────────────────────────
  tick() {
    const t = T();
    const dt = Math.min(0.1, t - this.lastT);
    this.lastT = t;
    this.tickN++;
    for (const p of this.players.values()) this.updatePlayer(p, t, dt);
    for (const sea of this.seas) if (sea.players.size || sea.hazards.length) sea.update(t, dt);
    for (const sea of this.seas) sea.flushEvents();
    if (this.tickN % 2 === 0) for (const sea of this.seas) sea.sendSnapshots(t);
    if (Date.now() > this.stockUntil) this.rollStock();
    if (t > this.lbAt) { this.lbAt = t + 5; this.updateLeaderboard(); }
  }

  updatePlayer(p, t, dt) {
    if (p.dead) { if (t >= p.respawnAt) this.respawn(p, t); return; }
    const sea = this.seas[p.s.sea];
    p.en = Math.min(p.maxEn, p.en + p.maxEn * 0.07 * dt);
    let regen = t - p.lastHurt > 6 ? 0.03 : 0;
    if (this.transformed(p, t)) regen += p.s.fruit === 'fr_phoenix' ? 0.04 : TF.TRANSFORM.regen;
    if (regen) p.hp = Math.min(p.maxHp, p.hp + p.maxHp * regen * dt);
    if (p.burn) {
      if (t >= p.burn.until) p.burn = null;
      else {
        p.burn.acc += p.burn.dps * dt;
        if (p.burn.acc >= 1 && t - (p.burn.last || 0) > 0.5) {
          const d = Math.round(p.burn.acc); p.burn.acc = 0; p.burn.last = t;
          const b = p.burn;
          p.hp -= d; p.lastHurt = t;
          sea.emit({ k: 'dmg', x: Math.round(p.x), y: Math.round(p.y - 30), v: d, c: 5, o: p.id }, p.x, p.y);
          if (p.hp <= 0) { this.killPlayer(p, b.src, b.side); return; }
        }
      }
    }
    if (p.buffs.length) p.buffs = p.buffs.filter((b) => b.until > t);
    if (p.m1Hold && t >= p.m1At && t >= p.stunUntil) this.doM1(p, t);
    if (p.dirty && t - p.meAt > 0.1 || t - p.meAt > 1) {
      p.dirty = false; p.meAt = t;
      p.send(this.meMsg(p, t));
    }
  }

  updateLeaderboard() {
    const all = [...this.store.values()];
    const row = (s, v) => [s.name, v, s.team];
    this.lb = {
      level: all.slice().sort((a, b) => b.level - a.level || b.xp - a.xp).slice(0, 10).map((s) => row(s, s.level)),
      bounty: all.filter((s) => s.bounty > 0).sort((a, b) => b.bounty - a.bounty).slice(0, 10).map((s) => row(s, s.bounty)),
      online: this.players.size,
      seas: this.seas.map((s) => s.players.size),
    };
    this.broadcast(Object.assign({ t: 'lb' }, this.lb));
  }

  status() {
    return { online: this.players.size, seas: this.seas.map((s) => ({ name: s.def.name, players: s.players.size })) };
  }
}

// ═══════════════════════════════════════════════════════════════════════════
class Sea {
  constructor(game, def) {
    this.g = game;
    this.def = def;
    this.idx = def.idx;
    this.players = new Set();
    this.mobs = [];
    this.hazards = [];
    this.drops = [];
    this.ev = [];
    const t = T();
    for (const isl of def.islands) {
      for (const sp of isl.spawns) for (let i = 0; i < sp.count; i++) this.addMob(sp.type, sp, isl);
    }
    this.beast = null;
    this.beastAt = t + 120;
    this.fruitAt = t + 90 + Math.random() * 120;
  }

  // ─── Mobs ────────────────────────────────────────────────────────────────
  addMob(type, sp) {
    const mt = TF.MOB_TYPES[type];
    const m = {
      id: this.g.id(), type, mt, sp, x: sp.x, y: sp.y, hx: sp.x, hy: sp.y, r: mt.r,
      hp: mt.hp, maxHp: mt.hp, alive: true, respawnAt: 0, target: null, scanAt: 0,
      atkAt: 0, windUntil: 0, ang: Math.random() * 6.28, kbx: 0, kby: 0,
      stunUntil: 0, slowUntil: 0, burn: null, contrib: new Map(), lastHit: 0,
      wanderAt: 0, wx: sp.x, wy: sp.y, nextSpecial: 0, chargeAt: 0, chargeEnd: 0, chargeAng: 0, chargeHit: null,
    };
    this.scatter(m);
    this.mobs.push(m);
    return m;
  }

  scatter(m) {
    if (m.mt.seaBeast) return;
    const spread = m.mt.boss ? 0 : 150;
    for (let i = 0; i < 20; i++) {
      const a = Math.random() * 6.283, r = Math.random() * spread;
      const x = m.sp.x + Math.cos(a) * r, y = m.sp.y + Math.sin(a) * r;
      if (TF.islandAt(this.idx, x, y) === m.mt.isle && TF.landDepth(this.idx, m.mt.isle, x, y) < 0.9 && !TF.inTown(this.idx, x, y)) {
        m.x = m.hx = x; m.y = m.hy = y; return;
      }
    }
  }

  canStand(m, x, y) {
    if (m.mt.seaBeast) return TF.islandAt(this.idx, x, y) < 0 && x > 50 && y > 50 && x < this.def.w - 50 && y < this.def.h - 50;
    return TF.islandAt(this.idx, x, y) === m.mt.isle && !TF.inTown(this.idx, x, y);
  }

  moveMob(m, dx, dy) {
    const nx = m.x + dx, ny = m.y + dy;
    if (this.canStand(m, nx, ny)) { m.x = nx; m.y = ny; return true; }
    if (this.canStand(m, nx, m.y)) { m.x = nx; return true; }
    if (this.canStand(m, m.x, ny)) { m.y = ny; return true; }
    return false;
  }

  validTarget(p, t) { return p && !p.gone && !p.dead && p.s.sea === this.idx && t >= p.protUntil; }

  // Mobs leave alone anyone standing in a town or right next to an NPC.
  sanctuary(m, p) {
    if (TF.inTown(this.idx, p.x, p.y)) return true;
    if (m.mt.isle < 0) return false;
    for (const id of this.def.islands[m.mt.isle].npcs) {
      const n = TF.NPCS[id];
      if (dist(n.x, n.y, p.x, p.y) < 150) return true;
    }
    return false;
  }

  updateMob(m, t, dt) {
    const mt = m.mt;
    if (!m.alive) { if (m.respawnAt && t >= m.respawnAt) this.respawnMob(m); return; }
    // Burning
    if (m.burn) {
      if (t >= m.burn.until) m.burn = null;
      else if (t - m.burn.last >= 0.5) {
        m.burn.last = t;
        this.damageMob(m, m.burn.dps * 0.5, m.burn.src, m.burn.wid, null, null, null, 0, 5);
        if (!m.alive) return;
      }
    }
    // Knockback slide
    if (m.kbx || m.kby) {
      const f = Math.exp(-10 * dt);
      this.moveMob(m, m.kbx * dt, m.kby * dt);
      m.kbx *= f; m.kby *= f;
      if (Math.abs(m.kbx) + Math.abs(m.kby) < 5) m.kbx = m.kby = 0;
    }
    if (t < m.stunUntil) { m.windUntil = 0; return; }
    const aggro = mt.seaBeast ? 750 : mt.boss ? 320 : 220;
    const leash = mt.seaBeast ? 2200 : mt.boss ? 800 : 560;
    let tp = m.target;
    // A monster provoked from a safe spot may keep its attacker as a target —
    // it still cannot walk in, but a boss's ranged attacks will reach.
    const provoked = tp && m.lastAttacker === tp && t - m.lastHit < 6;
    if (tp && (!this.validTarget(tp, t) || dist(m.hx, m.hy, tp.x, tp.y) > leash || dist(m.x, m.y, tp.x, tp.y) > 1000 || (!provoked && this.sanctuary(m, tp)))) tp = m.target = null;
    if (!tp && t >= m.scanAt) {
      m.scanAt = t + 0.35;
      let best = aggro;
      for (const p of this.players) {
        if (!this.validTarget(p, t) || this.sanctuary(m, p)) continue;
        // Bosses do not pick on players far below them unless provoked.
        if (mt.boss && p.s.level < mt.level - 25) continue;
        const d = dist(m.x, m.y, p.x, p.y);
        if (d < best) { best = d; tp = p; }
      }
      m.target = tp || null;
    }
    const slow = t < m.slowUntil ? 0.5 : 1;

    // A boss charge in progress owns the mob until it ends.
    if (m.chargeEnd && t < m.chargeEnd) {
      if (t >= m.chargeAt) {
        const sp = 1100 * dt;
        this.moveMob(m, Math.cos(m.chargeAng) * sp, Math.sin(m.chargeAng) * sp);
        for (const p of this.players) {
          if (m.chargeHit.has(p) || !this.validTarget(p, t)) continue;
          if (dist(m.x, m.y, p.x, p.y) < m.r + TF.PLAYER_R + 12) {
            m.chargeHit.add(p);
            this.g.damagePlayer(p, mt.dmg * 1.3, m, 'm', { knock: 260 }, m.x, m.y);
          }
        }
      }
      return;
    }
    m.chargeEnd = 0;

    if (tp) {
      const d = dist(m.x, m.y, tp.x, tp.y);
      m.ang = Math.atan2(tp.y - m.y, tp.x - m.x);
      const reach = m.r + TF.PLAYER_R + 14;
      if (m.windUntil) {
        if (t >= m.windUntil) {
          m.windUntil = 0;
          if (d <= reach + 34) this.g.damagePlayer(tp, mt.dmg, m, 'm', null, m.x, m.y, mt.boss ? 90 : 30);
        }
      } else if ((mt.boss || mt.seaBeast) && t >= m.nextSpecial && d < 800) {
        this.special(m, tp, t);
      } else if (d > reach) {
        const sp = mt.speed * slow * dt;
        if (!this.moveMob(m, Math.cos(m.ang) * sp, Math.sin(m.ang) * sp) && !mt.seaBeast && d > aggro * 1.4) m.target = null;
      } else if (t >= m.atkAt) {
        m.windUntil = t + (mt.boss ? 0.45 : 0.35);
        m.atkAt = t + (mt.boss ? 1.0 : 1.2);
      }
    } else {
      m.windUntil = 0;
      const dh = dist(m.x, m.y, m.hx, m.hy);
      if (dh > 200 || (m.returning && dh > 30)) {
        m.returning = true;
        const a = Math.atan2(m.hy - m.y, m.hx - m.x);
        const sp = mt.speed * 1.2 * dt;
        if (!this.moveMob(m, Math.cos(a) * sp, Math.sin(a) * sp)) { m.x = m.hx; m.y = m.hy; }
        m.ang = a;
      } else {
        m.returning = false;
        if (t >= m.wanderAt) {
          m.wanderAt = t + 2 + Math.random() * 4;
          const a = Math.random() * 6.283, r = Math.random() * (mt.boss ? 60 : 110);
          m.wx = m.hx + Math.cos(a) * r; m.wy = m.hy + Math.sin(a) * r;
        }
        const dw = dist(m.x, m.y, m.wx, m.wy);
        if (dw > 8) {
          const a = Math.atan2(m.wy - m.y, m.wx - m.x);
          const sp = mt.speed * 0.35 * dt;
          if (!this.moveMob(m, Math.cos(a) * sp, Math.sin(a) * sp)) { m.wx = m.x; m.wy = m.y; }
          m.ang = a;
        }
      }
      if (t - m.lastHit > 4 && m.hp < m.maxHp) {
        m.hp = Math.min(m.maxHp, m.hp + m.maxHp * 0.25 * dt);
        if (m.hp >= m.maxHp) m.contrib.clear();
      }
    }
  }

  // Boss and sea-beast attacks: every one is telegraphed so it can be dodged.
  special(m, tp, t) {
    const mt = m.mt;
    const kind = mt.attacks[Math.floor(Math.random() * mt.attacks.length)];
    m.nextSpecial = t + (mt.seaBeast ? 2.6 : 3.2) + Math.random() * 1.6;
    const dmg = mt.dmg;
    const col = '#ff3b3b';
    const a = Math.atan2(tp.y - m.y, tp.x - m.x);
    switch (kind) {
      case 'slam':
        this.addBlast(m, 'm', tp.x, tp.y, 150, 0.9, dmg * 1.6, { stun: 0.5 }, null, col, 'crack');
        break;
      case 'nova':
        this.addBlast(m, 'm', m.x, m.y, 220 + m.r, 1.1, dmg * 1.4, { knock: 220 }, null, col, 'ring');
        break;
      case 'volley':
        for (let i = 0; i < 7; i++) this.addProj(m, 'm', m.x, m.y, a + (i / 6 - 0.5) * 1.0, 620, 16, 850, dmg * 0.8, 0, 0, null, null, '#ff6b6b', 'orb');
        break;
      case 'rain':
        for (let i = 0; i < 6; i++) {
          const ra = Math.random() * 6.283, rr = Math.random() * 230;
          this.addBlast(m, 'm', tp.x + Math.cos(ra) * rr, tp.y + Math.sin(ra) * rr, 110, 0.8 + i * 0.15, dmg, null, null, col, 'meteor');
        }
        break;
      case 'beam':
        this.addBeam(m, 'm', a, 760, 90, 3, 0.15, dmg * 0.8, null, null, col, 'light', 0.8);
        break;
      case 'charge':
        m.chargeAng = a; m.chargeAt = t + 0.6; m.chargeEnd = t + 1.05; m.chargeHit = new Set();
        this.emit({ k: 'warn', x: Math.round(m.x), y: Math.round(m.y), a: r2(a), len: 495, w: m.r * 2 + 24, d: 0.6 }, m.x, m.y);
        break;
    }
  }

  respawnMob(m) {
    m.alive = true;
    m.hp = m.maxHp;
    m.target = null; m.burn = null; m.windUntil = 0; m.chargeEnd = 0; m.kbx = m.kby = 0;
    m.contrib.clear();
    this.scatter(m);
    if (m.mt.boss) this.broadcastChat(`${m.mt.name} (Lv. ${m.mt.level}) has appeared on ${this.def.islands[m.mt.isle].name}!`, true);
  }

  damageMob(m, amount, p, wid, st, ox, oy, knockDefault, colorCode) {
    if (!m.alive) return;
    const t = T();
    let d = amount * (0.93 + Math.random() * 0.14);
    const crit = colorCode === undefined && Math.random() < 0.06;
    if (crit) d *= 1.5;
    d = Math.max(1, Math.round(d));
    const dealt = Math.min(d, m.hp);
    m.hp -= d;
    m.lastHit = t;
    if (p && !p.gone) {
      m.lastAttacker = p;
      m.contrib.set(p, (m.contrib.get(p) || 0) + dealt);
      if (!m.target || (!m.mt.boss && Math.random() < 0.25)) m.target = p;
      this.g.addMastery(p, wid, (dealt / m.maxHp) * (2 + m.mt.level / 200));
    }
    this.emit({ k: 'dmg', x: Math.round(m.x), y: Math.round(m.y - m.r), v: d, c: colorCode !== undefined ? colorCode : crit ? 1 : 0 }, m.x, m.y);
    if (st) {
      if (st.burn) m.burn = { until: t + st.burn, dps: amount * 0.12, src: p, wid, last: t };
      if (st.slow) m.slowUntil = Math.max(m.slowUntil, t + st.slow);
      if (st.stun) m.stunUntil = Math.max(m.stunUntil, t + st.stun * (m.mt.boss || m.mt.seaBeast ? 0.25 : 1));
    }
    const knock = ((st && st.knock) || knockDefault || 0) * (m.mt.seaBeast ? 0 : m.mt.boss ? 0.2 : 1);
    if (knock && Number.isFinite(ox)) {
      const a = Math.atan2(m.y - oy, m.x - ox);
      m.kbx += Math.cos(a) * knock * 10; m.kby += Math.sin(a) * knock * 10;
    }
    if (m.hp <= 0) this.killMob(m);
  }

  killMob(m) {
    const t = T();
    const mt = m.mt;
    m.alive = false;
    m.respawnAt = mt.respawn ? t + mt.respawn : 0;
    this.emit({ k: 'die', x: Math.round(m.x), y: Math.round(m.y), r: m.r, c: mt.look.shirt }, m.x, m.y);
    let top = null, topV = 0;
    for (const [p, v] of m.contrib) if (v > topV) { topV = v; top = p; }
    const share = mt.boss || mt.seaBeast ? 0.05 : 0.15;
    for (const [p, v] of m.contrib) {
      if (p.gone || p.s.sea !== this.idx) continue;
      if (p !== top && v < m.maxHp * share) continue;
      this.reward(p, m);
    }
    m.contrib.clear();
    if (mt.boss) this.broadcastChat(`${mt.name} was defeated${top ? ' by ' + top.s.name : ''}!`, true);
    if (mt.seaBeast) {
      this.broadcastChat(`The ${mt.name} sank beneath the waves${top ? ' — slain by ' + top.s.name : ''}!`, true);
      this.mobs.splice(this.mobs.indexOf(m), 1);
      this.beast = null;
      this.beastAt = t + 300 + Math.random() * 180;
    }
  }

  reward(p, m) {
    const mt = m.mt;
    const s = p.s;
    const g = this.g;
    g.giveXp(p, mt.xp);
    s.beli += mt.beli;
    if (mt.frags) s.frags += mt.frags;
    const q = s.quest;
    if (q && q.mob === mt.id) {
      q.have++;
      if (q.have >= q.need) {
        const xp = TF.questXp(mt.level, mt.boss), beli = TF.questBeli(mt.level, mt.boss);
        g.giveXp(p, xp);
        s.beli += beli;
        g.note(p, `Quest complete! +${xp.toLocaleString()} XP, +$${beli.toLocaleString()}. Quest renewed.`, 'good');
        q.have = 0;
      }
    }
    if (mt.drop && !s.owned.includes(mt.drop) && Math.random() < 0.2) {
      s.owned.push(mt.drop);
      const it = TF.ITEMS[mt.drop];
      g.note(p, `${mt.name} dropped the ${it.name}! Equip it from your bag [I].`, 'good');
      this.broadcastChat(`${s.name} obtained the ${it.name}!`, true);
    }
    if ((mt.boss && Math.random() < 0.03) || (mt.seaBeast && Math.random() < 0.1)) g.giveFruit(p, TF.rollFruit().id, 'found');
    p.dirty = true;
  }

  // ─── Hazards: everything that can hit something ──────────────────────────
  eachTarget(side, owner, fn) {
    const t = T();
    if (side === 'p') {
      for (const m of this.mobs) if (m.alive) fn(m, false);
      if (owner && owner.pvp) for (const q of this.players) if (this.canPvp(owner, q, t)) fn(q, true);
    } else {
      for (const q of this.players) if (!q.dead && t >= q.protUntil) fn(q, true);
    }
  }

  canPvp(a, b, t) {
    if (a === b || a.gone || b.gone || a.dead || b.dead || !a.pvp || !b.pvp) return false;
    if (a.s.team === 'marine' && b.s.team === 'marine') return false;
    if (t < b.protUntil) return false;
    if (TF.isSafe(this.idx, a.x, a.y) || TF.isSafe(this.idx, b.x, b.y)) return false;
    return true;
  }

  hit(h, tg, isP, mult, ox, oy, knockDefault) {
    const amount = h.dmg * (mult || 1);
    if (isP) this.g.damagePlayer(tg, amount, h.owner, h.side, h.st, ox, oy, knockDefault);
    else this.damageMob(tg, amount, h.side === 'p' ? h.owner : null, h.wid, h.st, ox, oy, knockDefault);
  }

  cast(owner, side, sk, dmg, ang, ax, ay, wid, color) {
    const t = T();
    const ox = owner.x, oy = owner.y;
    const reach = Math.min(sk.rng || 0, dist(ox, oy, ax, ay));
    const tx = ox + Math.cos(ang) * reach, ty = oy + Math.sin(ang) * reach;
    const sh = sk.sh || 'orb';
    switch (sk.t) {
      case 'proj': {
        const n = sk.cnt || 1;
        for (let i = 0; i < n; i++) {
          const a = ang + (n > 1 ? (i / (n - 1) - 0.5) * (sk.spr || 0) : 0);
          this.addProj(owner, side, ox, oy, a, sk.sp, sk.r, sk.rng, dmg, sk.pierce || 0, sk.boom || 0, sk.st, wid, color, sh);
        }
        break;
      }
      case 'nova':
        this.addBlast(owner, side, ox, oy, sk.r, sk.d || 0.05, dmg, sk.st, wid, color, sh);
        if (sk.heal && owner.s) this.heal(owner, owner.maxHp * sk.heal);
        break;
      case 'blast':
        this.addBlast(owner, side, tx, ty, sk.r, sk.d || 0.3, dmg, sk.st, wid, color, sh);
        break;
      case 'pull': {
        const h = this.addBlast(owner, side, tx, ty, sk.r, 0.25, dmg, sk.st, wid, color, sh);
        h.pull = sk.force;
        break;
      }
      case 'beam':
        this.addBeam(owner, side, ang, sk.len, sk.w, sk.ticks, sk.iv, dmg / sk.ticks, sk.st, wid, color, sh, 0);
        break;
      case 'dash': {
        if (owner.s) { owner.budget += sk.dist + 60; owner.dashUntil = t + sk.dur; }
        const h = this.addHazard({ k: 'aura', side, owner, dmg, st: sk.st, wid, r: sk.r, until: t + sk.dur + 0.12, hits: new Set() });
        h.knock = 80;
        this.emit({ k: 'dash', o: owner.id, a: r2(ang), dist: sk.dist, dur: sk.dur, c: color, sh }, ox, oy);
        break;
      }
      case 'zone': {
        const at = sk.at === 'self' ? [ox, oy] : [tx, ty];
        const ticks = Math.max(1, Math.round(sk.dur / sk.iv));
        this.addHazard({ k: 'zone', side, owner, dmg: dmg / ticks, st: sk.st, wid, x: at[0], y: at[1], r: sk.r, iv: sk.iv, next: t + sk.iv * 0.5, until: t + sk.dur });
        this.emit({ k: 'zone', x: Math.round(at[0]), y: Math.round(at[1]), r: sk.r, dur: sk.dur, c: color, sh }, at[0], at[1]);
        break;
      }
      case 'rain': {
        const per = dmg / (sk.cnt * 0.3);
        for (let i = 0; i < sk.cnt; i++) {
          const a = Math.random() * 6.283, r = Math.sqrt(Math.random()) * sk.area;
          this.addBlast(owner, side, tx + Math.cos(a) * r, ty + Math.sin(a) * r, sk.r, 0.35 + i * sk.iv, per, sk.st, wid, color, sh);
        }
        break;
      }
      case 'tele': {
        const d = Math.min(sk.rng, dist(ox, oy, ax, ay));
        const nx = clamp(ox + Math.cos(ang) * d, 0, this.def.w), ny = clamp(oy + Math.sin(ang) * d, 0, this.def.h);
        if (owner.s) owner.budget += d + 60;
        this.emit({ k: 'tele', x1: Math.round(ox), y1: Math.round(oy), x2: Math.round(nx), y2: Math.round(ny), c: color, o: owner.id }, ox, oy);
        this.addBlast(owner, side, nx, ny, sk.r, 0.12, dmg, sk.st, wid, color, sh);
        break;
      }
      case 'chain': {
        const pts = [[Math.round(ox), Math.round(oy)]];
        const hitSet = new Set();
        let cx = tx, cy = ty, range = 260;
        const h = { side, owner, dmg, st: sk.st, wid };
        for (let j = 0; j <= sk.jumps; j++) {
          let best = null, bestD = range, bestP = false;
          this.eachTarget(side, owner, (tg, isP) => {
            if (hitSet.has(tg)) return;
            const d = dist(cx, cy, tg.x, tg.y);
            if (d < bestD) { bestD = d; best = tg; bestP = isP; }
          });
          if (!best && j === 0) {
            // Nothing near the cursor: take the nearest thing to the caster.
            range = sk.rng;
            cx = ox; cy = oy;
            this.eachTarget(side, owner, (tg, isP) => {
              const d = dist(cx, cy, tg.x, tg.y);
              if (d < bestD) { bestD = d; best = tg; bestP = isP; }
            });
          }
          if (!best) break;
          hitSet.add(best);
          pts.push([Math.round(best.x), Math.round(best.y)]);
          this.hit(h, best, bestP, 1, cx, cy);
          cx = best.x; cy = best.y; range = sk.jr;
        }
        if (pts.length === 1) pts.push([Math.round(tx), Math.round(ty)]);
        this.emit({ k: 'chain', pts, c: color }, ox, oy);
        break;
      }
      case 'buff': {
        if (!owner.s) break;
        if (sk.heal) this.heal(owner, owner.maxHp * sk.heal);
        if (sk.shield) { owner.shield = owner.maxHp * sk.shield; owner.shieldUntil = t + sk.dur; }
        if (sk.spd || sk.dr || sk.dmg) owner.buffs.push({ until: t + sk.dur, spd: sk.spd, dr: sk.dr, dmg: sk.dmg });
        owner.dirty = true;
        this.emit({ k: 'buff', o: owner.id, c: color, dur: sk.dur }, ox, oy);
        break;
      }
      case 'trans': {
        if (!owner.s) break;
        owner.transUntil = t + sk.dur;
        this.heal(owner, owner.maxHp * 0.15);
        owner.dirty = true;
        this.emit({ k: 'trans', o: owner.id, c: color }, ox, oy);
        break;
      }
    }
  }

  heal(p, amount) {
    const a = Math.min(Math.round(amount), Math.round(p.maxHp - p.hp));
    if (a <= 0) return;
    p.hp += a;
    this.emit({ k: 'dmg', x: Math.round(p.x), y: Math.round(p.y - 34), v: a, c: 3 }, p.x, p.y);
  }

  addHazard(h) { h.id = this.g.id(); this.hazards.push(h); return h; }

  addProj(owner, side, x, y, a, sp, r, rng, dmg, pierce, boom, st, wid, color, sh, skipFx) {
    const h = this.addHazard({ k: 'proj', side, owner, dmg, st, wid, x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, r, left: rng, pierce, boom, hits: new Set(), color, sh });
    this.emit({ k: 'proj', id: h.id, x: Math.round(x), y: Math.round(y), a: r2(a), sp, r, rng, c: color, sh, m: side === 'm' ? 1 : 0, o: skipFx || 0 }, x, y);
    return h;
  }

  addBlast(owner, side, x, y, r, delay, dmg, st, wid, color, sh) {
    const h = this.addHazard({ k: 'blast', side, owner, dmg, st, wid, x, y, r, at: T() + delay });
    this.emit({ k: 'blast', x: Math.round(x), y: Math.round(y), r, d: r2(delay), c: color, sh, m: side === 'm' ? 1 : 0 }, x, y);
    return h;
  }

  addBeam(owner, side, a, len, w, n, iv, dmgPer, st, wid, color, sh, delay) {
    const t = T();
    const h = this.addHazard({ k: 'beam', side, owner, dmg: dmgPer, st, wid, a, len, w, n, iv, next: t + (delay || 0.03), x: owner.x, y: owner.y });
    this.emit({ k: 'beam', o: owner.id, ot: owner.s ? 'p' : 'm', x: Math.round(owner.x), y: Math.round(owner.y), a: r2(a), len, w, d: delay || 0, dur: r2(n * iv + 0.1), c: color, sh, m: side === 'm' ? 1 : 0 }, owner.x, owner.y);
    return h;
  }

  explode(h, x, y, r, exclude) {
    this.emit({ k: 'blast', x: Math.round(x), y: Math.round(y), r, d: 0, c: h.color, sh: h.sh, m: h.side === 'm' ? 1 : 0 }, x, y);
    this.eachTarget(h.side, h.owner, (tg, isP) => {
      if (tg === exclude) return;
      if (dist(x, y, tg.x, tg.y) <= r + (isP ? TF.PLAYER_R : tg.r)) this.hit(h, tg, isP, 0.7, x, y, 40);
    });
  }

  updateHazards(t, dt) {
    const keep = [];
    for (const h of this.hazards) if (!this.stepHazard(h, t, dt)) keep.push(h);
    this.hazards = keep;
  }

  // Returns true when the hazard is finished.
  stepHazard(h, t, dt) {
    const ownerGone = h.owner && (h.owner.gone || (h.owner.s ? h.owner.dead || h.owner.s.sea !== this.idx : !h.owner.alive));
    switch (h.k) {
      case 'proj': {
        const steps = Math.max(1, Math.ceil((Math.hypot(h.vx, h.vy) * dt) / Math.max(10, h.r)));
        for (let s = 0; s < steps; s++) {
          h.x += (h.vx * dt) / steps; h.y += (h.vy * dt) / steps;
          h.left -= Math.hypot(h.vx, h.vy) * dt / steps;
          let done = false;
          this.eachTarget(h.side, h.owner, (tg, isP) => {
            if (done || h.hits.has(tg)) return;
            if (dist(h.x, h.y, tg.x, tg.y) > h.r + (isP ? TF.PLAYER_R : tg.r)) return;
            h.hits.add(tg);
            this.hit(h, tg, isP, 1, h.x - h.vx * 0.05, h.y - h.vy * 0.05, 25);
            if (h.boom) this.explode(h, h.x, h.y, h.boom, tg);
            if (h.pierce === 0) done = true;
            else if (h.pierce > 0) h.pierce--;
          });
          if (done) { this.emit({ k: 'pend', id: h.id }, h.x, h.y); return true; }
          if (h.left <= 0) { if (h.boom) this.explode(h, h.x, h.y, h.boom, null); return true; }
        }
        return false;
      }
      case 'blast': {
        if (t < h.at) return false;
        this.eachTarget(h.side, h.owner, (tg, isP) => {
          const d = dist(h.x, h.y, tg.x, tg.y);
          if (d > h.r + (isP ? TF.PLAYER_R : tg.r)) return;
          this.hit(h, tg, isP, 1, h.x, h.y, 30);
          if (h.pull && d > 20) {
            const a = Math.atan2(h.y - tg.y, h.x - tg.x), pull = Math.min(h.pull, d - 10);
            if (isP) this.g.knock(tg, Math.cos(a) * pull, Math.sin(a) * pull);
            else if (!tg.mt.boss && !tg.mt.seaBeast) { tg.kbx += Math.cos(a) * pull * 10; tg.kby += Math.sin(a) * pull * 10; }
          }
        });
        return true;
      }
      case 'beam': {
        if (ownerGone) return true;
        if (t < h.next) return false;
        h.next = t + h.iv;
        h.n--;
        const ox = h.owner.x, oy = h.owner.y;
        const ca = Math.cos(h.a), sa = Math.sin(h.a);
        this.eachTarget(h.side, h.owner, (tg, isP) => {
          const tr = isP ? TF.PLAYER_R : tg.r;
          const dx = tg.x - ox, dy = tg.y - oy;
          const along = dx * ca + dy * sa, perp = -dx * sa + dy * ca;
          if (along < -tr || along > h.len + tr || Math.abs(perp) > h.w / 2 + tr) return;
          this.hit(h, tg, isP, 1, ox, oy, 20);
        });
        return h.n <= 0;
      }
      case 'zone': {
        if (t >= h.until) return true;
        if (t < h.next) return false;
        h.next = t + h.iv;
        this.eachTarget(h.side, h.owner, (tg, isP) => {
          if (dist(h.x, h.y, tg.x, tg.y) <= h.r + (isP ? TF.PLAYER_R : tg.r)) this.hit(h, tg, isP, 1, h.x, h.y, 0);
        });
        return false;
      }
      case 'aura': {
        if (ownerGone || t >= h.until) return true;
        const ox = h.owner.x, oy = h.owner.y;
        this.eachTarget(h.side, h.owner, (tg, isP) => {
          if (h.hits.has(tg)) return;
          if (dist(ox, oy, tg.x, tg.y) > h.r + (isP ? TF.PLAYER_R : tg.r)) return;
          h.hits.add(tg);
          this.hit(h, tg, isP, 1, ox, oy, h.knock);
        });
        return false;
      }
    }
    return true;
  }

  // ─── Drops, world fruit and the sea beast ────────────────────────────────
  addDrop(fid, x, y, ownerId, life) {
    const sea = this.def;
    x = clamp(x, 20, sea.w - 20); y = clamp(y, 20, sea.h - 20);
    this.drops.push({ id: this.g.id(), fid, x: Math.round(x), y: Math.round(y), until: T() + life, owner: ownerId, pickAfter: T() + 1.2 });
  }

  updateWorld(t) {
    // Despawn and pick up fruit lying around.
    if (this.drops.length) {
      this.drops = this.drops.filter((d) => {
        if (t > d.until) return false;
        for (const p of this.players) {
          if (p.dead || (p.id === d.owner && t < d.pickAfter + 1.5) || t < d.pickAfter) continue;
          if (dist(p.x, p.y, d.x, d.y) < 46) {
            if (p.s.fruits.length >= TF.FRUIT_INV_CAP) continue;
            const fr = TF.ITEMS[d.fid];
            this.g.giveFruit(p, d.fid, d.owner ? null : 'found');
            this.emit({ k: 'die', x: d.x, y: d.y, r: 30, c: fr.color }, d.x, d.y);
            return false;
          }
        }
        return true;
      });
    }
    if (t >= this.fruitAt) {
      this.fruitAt = t + 420 + Math.random() * 300;
      if (this.drops.filter((d) => !d.owner).length < 3) {
        const isls = this.def.islands.filter((i) => !i.hub);
        const isl = isls[Math.floor(Math.random() * isls.length)];
        const pt = TF.pointIn(isl, Math.random() * 6.283, 0.2 + Math.random() * 0.6);
        const fr = TF.rollFruit();
        this.addDrop(fr.id, pt.x, pt.y, 0, 900);
        this.broadcastChat(`A ${TF.RARITY[fr.rarity].name.toLowerCase()} fruit has fallen somewhere in the ${this.def.name}…`, true);
      }
    }
    if (!this.beast && t >= this.beastAt && this.players.size) {
      this.beastAt = t + 60;
      for (let i = 0; i < 60; i++) {
        const x = 800 + Math.random() * (this.def.w - 1600), y = 800 + Math.random() * (this.def.h - 1600);
        if (this.def.islands.some((isl) => dist(x, y, isl.x, isl.y) < isl.R + 600)) continue;
        this.beast = this.addMob(this.def.beast, { x, y, count: 1 });
        this.beast.x = this.beast.hx = x; this.beast.y = this.beast.hy = y;
        this.broadcastChat(`⚠ A ${TF.MOB_TYPES[this.def.beast].name} (Lv. ${TF.MOB_TYPES[this.def.beast].level}) surfaced in the open sea!`, true);
        break;
      }
    }
  }

  // ─── Tick ────────────────────────────────────────────────────────────────
  update(t, dt) {
    // Only islands somebody is near get simulated; the rest hold still.
    const active = new Set();
    for (const isl of this.def.islands) {
      for (const p of this.players) if (dist(p.x, p.y, isl.x, isl.y) < isl.R + 1900) { active.add(isl.idx); break; }
    }
    for (const m of this.mobs) {
      if (m.mt.seaBeast || active.has(m.mt.isle)) this.updateMob(m, t, dt);
    }
    // Keep mobs from stacking into one blob.
    for (let i = 0; i < this.mobs.length; i++) {
      const a = this.mobs[i];
      if (!a.alive || !active.has(a.mt.isle)) continue;
      for (let j = i + 1; j < this.mobs.length; j++) {
        const b = this.mobs[j];
        if (!b.alive || b.mt.isle !== a.mt.isle) continue;
        const dx = b.x - a.x, dy = b.y - a.y, min = a.r + b.r;
        const d2 = dx * dx + dy * dy;
        if (d2 >= min * min || d2 === 0) continue;
        const d = Math.sqrt(d2), push = (min - d) / 2;
        const ux = dx / d, uy = dy / d;
        this.moveMob(a, -ux * push, -uy * push);
        this.moveMob(b, ux * push, uy * push);
      }
    }
    this.updateHazards(t, dt);
    this.updateWorld(t);
  }

  // ─── Network out ─────────────────────────────────────────────────────────
  emit(ev, x, y, to) { this.ev.push({ json: JSON.stringify(ev), x, y, to }); }

  broadcastChat(m, sys) {
    const s = JSON.stringify({ t: 'chat', sys: sys ? 1 : 0, m });
    for (const p of this.players) p.send(s);
  }

  flushEvents() {
    if (!this.ev.length) return;
    const R2 = (VIEW_R + 300) * (VIEW_R + 300);
    for (const p of this.players) {
      const parts = [];
      for (const e of this.ev) {
        if (e.to !== undefined) { if (e.to === p.id) parts.push(e.json); continue; }
        const dx = e.x - p.x, dy = e.y - p.y;
        if (dx * dx + dy * dy < R2) parts.push(e.json);
      }
      if (parts.length) p.send('{"t":"e","e":[' + parts.join(',') + ']}');
    }
    this.ev = [];
  }

  sendSnapshots(t) {
    if (!this.players.size) return;
    const R2 = VIEW_R * VIEW_R;
    const pRows = new Map();
    for (const q of this.players) {
      let f = 0;
      if (q.inWater) f |= 1;
      if (q.pvp) f |= 2;
      if (t < q.transUntil) f |= 4;
      if (q.dead) f |= 8;
      if (q.s.abilities.aura) f |= 16;
      if (t < q.stunUntil) f |= 32;
      if (t < q.dashUntil) f |= 64;
      if (q.shield > 0 && t < q.shieldUntil) f |= 128;
      if (t < q.protUntil) f |= 256;
      if (TF.isSafe(this.idx, q.x, q.y)) f |= 512;
      if (q.s.fruitAwake) f |= 1024;
      const w = this.g.weapon(q);
      pRows.set(q, [q.id, Math.round(q.x), Math.round(q.y), r2(q.aim), Math.round(q.hp), q.maxHp, q.s.level, f,
        w.id, q.s.name, q.s.team === 'marine' ? 1 : 0, q.s.bounty, q.s.fruit ? TF.FRUIT_IDX[q.s.fruit] : -1]);
    }
    for (const p of this.players) {
      if (p.conn.congested) continue;
      const ps = [], ms = [], ds = [];
      for (const [q, row] of pRows) {
        const dx = q.x - p.x, dy = q.y - p.y;
        if (q === p || dx * dx + dy * dy < R2) ps.push(row);
      }
      for (const m of this.mobs) {
        if (!m.alive) continue;
        const dx = m.x - p.x, dy = m.y - p.y;
        if (dx * dx + dy * dy > R2 * (m.mt.seaBeast ? 1.6 : 1)) continue;
        let f = 0;
        if (m.windUntil) f |= 1;
        if (t < m.stunUntil) f |= 2;
        if (m.target) f |= 4;
        if (m.chargeEnd && t >= m.chargeAt) f |= 8;
        if (t < m.slowUntil) f |= 16;
        if (m.burn) f |= 32;
        ms.push([m.id, m.type, Math.round(m.x), Math.round(m.y), Math.round(m.hp), f, r2(m.ang)]);
      }
      for (const d of this.drops) {
        const dx = d.x - p.x, dy = d.y - p.y;
        if (dx * dx + dy * dy < R2) ds.push([d.id, TF.FRUIT_IDX[d.fid], d.x, d.y]);
      }
      const bosses = [];
      if (this.g.tickN % 30 === 0) {
        for (const m of this.mobs) if ((m.mt.boss || m.mt.seaBeast) && m.alive) bosses.push([m.type, Math.round(m.x), Math.round(m.y)]);
      }
      const msg = { t: 's', p: ps, m: ms, d: ds, en: Math.round(p.en), hp: Math.round(p.hp) };
      if (this.g.tickN % 30 === 0) msg.b = bosses;
      p.send(msg);
    }
  }
}

module.exports = { Game, CODES };
