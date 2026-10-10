/*
 * Tidefruit — shared rules and content.
 *
 * Loaded by the server with require() and by the browser with a plain
 * <script> tag (it becomes window.TF). Everything both sides must agree on
 * lives here: the formulas, the fruit and weapon tables, the four seas and
 * their islands, and the island geometry that decides land from water.
 * Nothing in this file may touch the DOM or Node's APIs.
 */
(function (root, factory) {
  const TF = factory();
  if (typeof module === 'object' && module.exports) module.exports = TF;
  else root.TF = TF;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const MAX_LEVEL = 3000;
  const STAT_CAP = 3000;
  const POINTS_PER_LEVEL = 3;
  const TAU = Math.PI * 2;

  // ─── Small deterministic helpers ──────────────────────────────────────────
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function hashStr(s) {
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
  const dist = (ax, ay, bx, by) => Math.hypot(ax - bx, ay - by);
  function angDiff(a, b) { let d = (a - b) % TAU; if (d > Math.PI) d -= TAU; if (d < -Math.PI) d += TAU; return d; }

  // ─── Progression formulas ─────────────────────────────────────────────────
  // A level-L mob gives a tenth of a level-L player's next level. A quest pays
  // most of a level on top. Out-level an island and its mobs stop being worth
  // it: that is the push to the next one.
  const xpNext = (L) => Math.floor(40 + 8 * Math.pow(L, 1.45));
  const mobHp = (L) => Math.round(6 * (10 + L / 100) * (1 + 0.035 * Math.min(1.6 * L, STAT_CAP)) * (1 + L / 3000));
  const mobDmg = (L) => Math.round(5 + 1.25 * L);
  const mobXp = (L) => Math.floor(xpNext(L) / 10);
  const mobBeli = (L) => Math.round(6 + L * 0.9);
  const questXp = (L, boss) => Math.floor(xpNext(L) * (boss ? 2.5 : 0.9));
  const questBeli = (L, boss) => Math.round((80 + L * 18) * (boss ? 3 : 1));
  const questCount = (sea) => 5 + sea;
  const maxHp = (L, def) => Math.round(120 + 14 * L + 28 * def);
  const maxEn = (L, def) => Math.round(100 + 3 * L + 8 * def);
  const statMul = (s) => 1 + 0.035 * s;
  const pointsTotal = (L) => POINTS_PER_LEVEL * L;
  const gachaCost = (L) => Math.round(8000 + L * 450);
  const resetCost = (L) => Math.round(1000 + L * 220);

  const RARITY = {
    common:    { name: 'Common',    color: '#c3ccd6', w: 50, mul: 1.00, awaken: 1500 },
    uncommon:  { name: 'Uncommon',  color: '#4fc3f7', w: 28, mul: 1.12, awaken: 2500 },
    rare:      { name: 'Rare',      color: '#c77dff', w: 14, mul: 1.25, awaken: 4000 },
    legendary: { name: 'Legendary', color: '#ff5fb7', w: 6,  mul: 1.40, awaken: 7000 },
    mythical:  { name: 'Mythical',  color: '#ff4d4d', w: 2,  mul: 1.60, awaken: 12000 },
  };
  const fruitBase = (fr, L) => RARITY[fr.rarity].mul * (9 + L / 90);

  // Mastery unlocks, energy cost (fraction of max energy) and default cooldowns.
  const SKILL_KEYS = ['z', 'x', 'c', 'v', 'f'];
  const SKILL_UNLOCK = { z: 1, x: 25, c: 75, v: 150, f: 250 };
  const SKILL_ENERGY = { z: 0.07, x: 0.09, c: 0.11, v: 0.16, f: 0.09 };
  const MASTERY_CAP = 600;

  // Basic attack (left click) per slot.
  const M1 = {
    style: { t: 'melee', rng: 82, arc: 1.8, rate: 0.32, m: 1.0 },
    sword: { t: 'melee', rng: 112, arc: 2.2, rate: 0.42, m: 1.15 },
    gun:   { t: 'proj', sp: 1500, r: 9, rng: 680, rate: 0.55, m: 1.0, sh: 'bullet' },
    fruit: { t: 'proj', sp: 980, r: 15, rng: 440, rate: 0.48, m: 0.9, sh: 'orb' },
    beast: { t: 'melee', rng: 104, arc: 2.0, rate: 0.36, m: 1.05 },
  };

  const SPEED = { land: 285, boat: 440, mob: 165, boss: 140, beast: 230 };
  const PLAYER_R = 20;
  const DASH = { base: { dist: 230, cd: 1.4 }, flash: { dist: 340, cd: 0.9 }, dur: 0.16 };
  const TRANSFORM = { dmg: 1.3, spd: 1.2, dr: 0.2, regen: 0.02, size: 1.35 };
  const PVP_SCALE = 0.7;
  const PVP_MIN_LEVEL = 20;
  const FRUIT_INV_CAP = 12;

  // ─── Fruits ───────────────────────────────────────────────────────────────
  // Skill types are a small vocabulary the server knows how to run and the
  // client knows how to draw: proj, nova, blast, beam, dash, zone, rain, pull,
  // tele, chain, buff, trans. `m` is the damage multiplier — per hit for the
  // single-hit types, the whole volley for beam/zone (split across ticks).
  const S = (k, n, t, o) => Object.assign({ k, n, t }, o);
  const FRUITS = [];
  function F(id, name, rarity, type, color, color2, price, skills) {
    FRUITS.push({ id: 'fr_' + id, key: id, name: name + ' Fruit', short: name, rarity, type, color, color2, price, skills });
  }

  F('spin', 'Spin', 'common', 'natural', '#d7ccc8', '#8d6e63', 8000, [
    S('z', 'Spin Saw', 'proj', { m: 2.0, cd: 4, sp: 850, r: 26, rng: 600, pierce: 1, sh: 'saw' }),
    S('x', 'Cyclone', 'nova', { m: 2.6, cd: 6, r: 150, st: { knock: 90 }, sh: 'ring' }),
    S('c', 'Grinder Dash', 'dash', { m: 2.8, cd: 8, dist: 320, r: 60, dur: 0.25, sh: 'saw' }),
    S('v', 'Saw Storm', 'rain', { m: 3.6, cd: 13, cnt: 8, r: 85, area: 220, rng: 520, iv: 0.08, sh: 'saw' }),
    S('f', 'Spin Glide', 'buff', { cd: 16, dur: 6, spd: 1.4 }),
  ]);
  F('bomb', 'Bomb', 'common', 'natural', '#ff8a50', '#5d4037', 10000, [
    S('z', 'Bomb Toss', 'blast', { m: 2.3, cd: 4, r: 110, rng: 520, d: 0.45, sh: 'bomb' }),
    S('x', 'Cluster Bombs', 'proj', { m: 1.6, cd: 6, sp: 700, r: 16, rng: 450, cnt: 3, spr: 0.6, boom: 90, sh: 'bomb' }),
    S('c', 'Self Destruct', 'nova', { m: 3.8, cd: 10, r: 210, d: 0.2, st: { knock: 130 }, sh: 'bomb' }),
    S('v', 'Bomb Rain', 'rain', { m: 2.6, cd: 14, cnt: 10, r: 100, area: 260, rng: 550, iv: 0.1, sh: 'bomb' }),
    S('f', 'Blast Jump', 'dash', { m: 1.5, cd: 8, dist: 380, r: 70, dur: 0.2, sh: 'bomb' }),
  ]);
  F('spring', 'Spring', 'common', 'natural', '#c5e1a5', '#558b2f', 12000, [
    S('z', 'Spring Snipe', 'proj', { m: 2.2, cd: 4, sp: 1300, r: 20, rng: 700, sh: 'fist' }),
    S('x', 'Coil Stomp', 'blast', { m: 2.8, cd: 6, r: 140, rng: 300, d: 0.3, st: { stun: 0.5 } }),
    S('c', 'Bounce Rush', 'dash', { m: 3.0, cd: 8, dist: 420, r: 60, dur: 0.22 }),
    S('v', 'Spring Cannon', 'proj', { m: 4.6, cd: 12, sp: 1100, r: 40, rng: 800, boom: 140, sh: 'fist' }),
    S('f', 'Rebound', 'buff', { cd: 15, dur: 5, spd: 1.5 }),
  ]);
  F('smoke', 'Smoke', 'common', 'elemental', '#cfd8dc', '#78909c', 15000, [
    S('z', 'Smoke Puff', 'proj', { m: 2.0, cd: 4, sp: 800, r: 30, rng: 550, st: { slow: 1.5 }, sh: 'cloud' }),
    S('x', 'Smoke Screen', 'zone', { m: 3.0, cd: 8, r: 170, dur: 4, iv: 0.5, at: 'self', st: { slow: 1 }, sh: 'cloud' }),
    S('c', 'White Launcher', 'dash', { m: 2.6, cd: 7, dist: 400, r: 60, dur: 0.25, sh: 'cloud' }),
    S('v', 'Smoke Cyclone', 'nova', { m: 4.2, cd: 13, r: 220, d: 0.3, st: { knock: 110 }, sh: 'cloud' }),
    S('f', 'Haze Form', 'buff', { cd: 16, dur: 6, dr: 0.3 }),
  ]);
  F('spike', 'Spike', 'common', 'natural', '#eceff1', '#607d8b', 18000, [
    S('z', 'Spike Shot', 'proj', { m: 1.5, cd: 4, sp: 1000, r: 16, rng: 600, cnt: 3, spr: 0.35, sh: 'spear' }),
    S('x', 'Spike Field', 'zone', { m: 3.0, cd: 7, r: 140, dur: 3, iv: 0.5, at: 'aim', rng: 450, sh: 'spikes' }),
    S('c', 'Hedgehog', 'nova', { m: 3.4, cd: 9, r: 160, sh: 'spikes' }),
    S('v', 'Spike Barrage', 'rain', { m: 2.6, cd: 13, cnt: 9, r: 90, area: 240, rng: 550, iv: 0.08, sh: 'spear' }),
    S('f', 'Spike Charge', 'dash', { m: 2.4, cd: 8, dist: 330, r: 60, dur: 0.2 }),
  ]);
  F('flame', 'Flame', 'uncommon', 'elemental', '#ff6d00', '#ffd54f', 120000, [
    S('z', 'Fire Bullets', 'proj', { m: 1.1, cd: 4, sp: 1000, r: 18, rng: 650, cnt: 5, spr: 0.5, st: { burn: 2 }, sh: 'flame' }),
    S('x', 'Fire Column', 'blast', { m: 3.2, cd: 7, r: 120, rng: 450, d: 0.4, st: { burn: 3 }, sh: 'flame' }),
    S('c', 'Flame Fist', 'proj', { m: 4.0, cd: 9, sp: 900, r: 46, rng: 750, pierce: -1, st: { burn: 3 }, sh: 'fist' }),
    S('v', 'Great Blaze', 'zone', { m: 5.0, cd: 14, r: 240, dur: 4, iv: 0.4, at: 'aim', rng: 500, st: { burn: 2 }, sh: 'flame' }),
    S('f', 'Flame Rocket', 'dash', { m: 2.0, cd: 8, dist: 450, r: 60, dur: 0.25, st: { burn: 2 }, sh: 'flame' }),
  ]);
  F('frost', 'Frost', 'uncommon', 'elemental', '#81d4fa', '#e1f5fe', 150000, [
    S('z', 'Ice Spears', 'proj', { m: 1.4, cd: 4, sp: 1100, r: 16, rng: 650, cnt: 3, spr: 0.25, st: { slow: 1.5 }, sh: 'spear' }),
    S('x', 'Frost Burst', 'nova', { m: 2.8, cd: 7, r: 170, st: { stun: 0.9 }, sh: 'ice' }),
    S('c', 'Glacier Path', 'beam', { m: 3.6, cd: 9, len: 520, w: 70, ticks: 4, iv: 0.12, st: { slow: 2 }, sh: 'ice' }),
    S('v', 'Ice Age', 'zone', { m: 4.8, cd: 14, r: 260, dur: 4, iv: 0.5, at: 'self', st: { slow: 1.2 }, sh: 'ice' }),
    S('f', 'Ice Skate', 'dash', { m: 1.6, cd: 7, dist: 480, r: 50, dur: 0.3, sh: 'ice' }),
  ]);
  F('sand', 'Sand', 'uncommon', 'elemental', '#ffcc80', '#bf8f4f', 180000, [
    S('z', 'Sand Blades', 'proj', { m: 1.6, cd: 4, sp: 900, r: 22, rng: 600, cnt: 2, spr: 0.2, sh: 'crescent' }),
    S('x', 'Quicksand', 'zone', { m: 3.0, cd: 7, r: 180, dur: 4, iv: 0.5, at: 'aim', rng: 450, st: { slow: 1.2 }, sh: 'sand' }),
    S('c', 'Desert Tornado', 'pull', { m: 3.4, cd: 9, r: 200, rng: 450, force: 220, sh: 'sand' }),
    S('v', 'Sand Coffin', 'rain', { m: 3.0, cd: 14, cnt: 7, r: 110, area: 240, rng: 550, iv: 0.12, st: { stun: 0.4 }, sh: 'sand' }),
    S('f', 'Dune Glide', 'dash', { m: 1.6, cd: 7, dist: 420, r: 60, dur: 0.25, sh: 'sand' }),
  ]);
  F('dark', 'Dark', 'uncommon', 'elemental', '#8e63d6', '#1a0a2e', 220000, [
    S('z', 'Dark Orb', 'proj', { m: 2.4, cd: 4, sp: 800, r: 30, rng: 600, boom: 90, sh: 'orb' }),
    S('x', 'Black Hole', 'pull', { m: 3.4, cd: 8, r: 230, rng: 450, force: 260, st: { slow: 1.5 }, sh: 'void' }),
    S('c', 'Void Lunge', 'dash', { m: 3.0, cd: 8, dist: 360, r: 70, dur: 0.22, sh: 'void' }),
    S('v', 'Abyssal Gate', 'zone', { m: 5.2, cd: 14, r: 230, dur: 4, iv: 0.4, at: 'aim', rng: 500, st: { slow: 1 }, sh: 'void' }),
    S('f', 'Darkness Pulse', 'nova', { m: 2.6, cd: 9, r: 200, st: { stun: 0.6 }, sh: 'void' }),
  ]);
  F('falcon', 'Falcon', 'uncommon', 'beast', '#a1887f', '#fff176', 250000, [
    S('z', 'Talon Dive', 'dash', { m: 2.6, cd: 5, dist: 380, r: 60, dur: 0.22, sh: 'feather' }),
    S('x', 'Feather Storm', 'proj', { m: 1.0, cd: 6, sp: 1000, r: 14, rng: 650, cnt: 7, spr: 0.9, sh: 'feather' }),
    S('c', 'Sky Strike', 'blast', { m: 3.8, cd: 9, r: 150, rng: 500, d: 0.5, sh: 'feather' }),
    S('v', 'Falcon Form', 'trans', { cd: 30, dur: 20 }),
    S('f', 'Gale Wings', 'nova', { m: 2.4, cd: 9, r: 180, st: { knock: 150 }, sh: 'feather' }),
  ]);
  F('light', 'Light', 'rare', 'elemental', '#fff59d', '#ffffff', 650000, [
    S('z', 'Light Arrows', 'proj', { m: 1.2, cd: 4, sp: 2000, r: 12, rng: 900, cnt: 4, spr: 0.2, sh: 'spear' }),
    S('x', 'Light Beam', 'beam', { m: 3.8, cd: 7, len: 800, w: 46, ticks: 5, iv: 0.08, sh: 'light' }),
    S('c', 'Flash', 'tele', { m: 2.4, cd: 8, rng: 600, r: 140, sh: 'light' }),
    S('v', 'Sky Spears', 'rain', { m: 3.0, cd: 13, cnt: 12, r: 80, area: 260, rng: 650, iv: 0.06, sh: 'spear' }),
    S('f', 'Radiance', 'nova', { m: 2.8, cd: 9, r: 200, st: { stun: 0.5 }, sh: 'light' }),
  ]);
  F('rubber', 'Rubber', 'rare', 'natural', '#ef5350', '#ffcdd2', 750000, [
    S('z', 'Rubber Pistol', 'beam', { m: 2.4, cd: 4, len: 420, w: 44, ticks: 1, iv: 0.05, sh: 'fist' }),
    S('x', 'Gatling', 'beam', { m: 3.6, cd: 7, len: 380, w: 90, ticks: 8, iv: 0.07, sh: 'fist' }),
    S('c', 'Bazooka', 'proj', { m: 3.6, cd: 9, sp: 1200, r: 50, rng: 450, pierce: -1, st: { knock: 200 }, sh: 'fist' }),
    S('v', 'Gear Boost', 'trans', { cd: 35, dur: 20 }),
    S('f', 'Rocket', 'dash', { m: 1.8, cd: 7, dist: 520, r: 60, dur: 0.28 }),
  ]);
  F('barrier', 'Barrier', 'rare', 'natural', '#80deea', '#ffffff', 800000, [
    S('z', 'Barrier Shard', 'proj', { m: 2.2, cd: 4, sp: 1000, r: 26, rng: 650, pierce: 2, sh: 'cube' }),
    S('x', 'Barrier Prison', 'blast', { m: 2.4, cd: 8, r: 150, rng: 500, d: 0.25, st: { stun: 1.4 }, sh: 'cube' }),
    S('c', 'Barrier Ram', 'dash', { m: 3.0, cd: 8, dist: 380, r: 80, dur: 0.22, st: { knock: 150 }, sh: 'cube' }),
    S('v', 'Fortress', 'buff', { cd: 25, dur: 6, shield: 0.35 }),
    S('f', 'Barrier Burst', 'nova', { m: 3.6, cd: 10, r: 200, st: { knock: 160 }, sh: 'cube' }),
  ]);
  F('ghost', 'Ghost', 'rare', 'natural', '#b39ddb', '#e8eaf6', 900000, [
    S('z', 'Spirit Bolts', 'proj', { m: 1.3, cd: 4, sp: 850, r: 22, rng: 650, cnt: 4, spr: 0.6, sh: 'skull' }),
    S('x', 'Haunting', 'zone', { m: 3.4, cd: 8, r: 180, dur: 4, iv: 0.5, at: 'aim', rng: 450, st: { slow: 1 }, sh: 'skull' }),
    S('c', 'Soul Drain', 'nova', { m: 3.0, cd: 10, r: 180, heal: 0.12, sh: 'skull' }),
    S('v', 'Phantom Legion', 'rain', { m: 3.2, cd: 14, cnt: 9, r: 100, area: 260, rng: 550, iv: 0.1, sh: 'skull' }),
    S('f', 'Ethereal', 'buff', { cd: 20, dur: 5, dr: 0.5, spd: 1.2 }),
  ]);
  F('magma', 'Magma', 'rare', 'elemental', '#ff3d00', '#4e1d0a', 950000, [
    S('z', 'Magma Fist', 'proj', { m: 2.6, cd: 5, sp: 850, r: 34, rng: 650, boom: 100, st: { burn: 3 }, sh: 'fist' }),
    S('x', 'Meteor Shower', 'rain', { m: 2.6, cd: 9, cnt: 6, r: 120, area: 220, rng: 550, iv: 0.15, st: { burn: 2 }, sh: 'meteor' }),
    S('c', 'Magma Pool', 'zone', { m: 4.4, cd: 10, r: 200, dur: 5, iv: 0.5, at: 'aim', rng: 450, st: { burn: 2 }, sh: 'lava' }),
    S('v', 'Volcanic Eruption', 'blast', { m: 6.0, cd: 15, r: 240, rng: 500, d: 0.8, st: { burn: 4, knock: 150 }, sh: 'lava' }),
    S('f', 'Lava Surge', 'dash', { m: 2.2, cd: 8, dist: 400, r: 70, dur: 0.25, st: { burn: 2 }, sh: 'lava' }),
  ]);
  F('quake', 'Quake', 'legendary', 'natural', '#f5f5f5', '#90caf9', 1800000, [
    S('z', 'Quake Punch', 'beam', { m: 2.6, cd: 5, len: 380, w: 120, ticks: 1, iv: 0.05, st: { knock: 220 }, sh: 'crack' }),
    S('x', 'Tremor', 'nova', { m: 3.2, cd: 7, r: 240, st: { knock: 200, stun: 0.4 }, sh: 'crack' }),
    S('c', 'Fault Line', 'beam', { m: 4.0, cd: 9, len: 700, w: 90, ticks: 3, iv: 0.15, st: { stun: 0.5 }, sh: 'crack' }),
    S('v', 'Seaquake', 'nova', { m: 6.0, cd: 15, r: 340, d: 0.5, st: { knock: 300 }, sh: 'crack' }),
    S('f', 'Shock Leap', 'dash', { m: 2.0, cd: 8, dist: 400, r: 80, dur: 0.22, sh: 'crack' }),
  ]);
  F('thunder', 'Thunder', 'legendary', 'elemental', '#ffee58', '#40c4ff', 2100000, [
    S('z', 'Lightning Chain', 'chain', { m: 2.4, cd: 4, rng: 650, jumps: 4, jr: 260, sh: 'bolt' }),
    S('x', 'Thunder Strike', 'rain', { m: 2.8, cd: 8, cnt: 6, r: 100, area: 230, rng: 600, iv: 0.1, st: { stun: 0.3 }, sh: 'bolt' }),
    S('c', 'Bolt Step', 'tele', { m: 2.6, cd: 8, rng: 550, r: 150, st: { stun: 0.5 }, sh: 'bolt' }),
    S('v', "Heaven's Judgement", 'beam', { m: 6.0, cd: 15, len: 900, w: 110, ticks: 5, iv: 0.1, sh: 'bolt' }),
    S('f', 'Static Field', 'nova', { m: 2.4, cd: 10, r: 220, st: { stun: 1.0 }, sh: 'bolt' }),
  ]);
  F('phoenix', 'Phoenix', 'legendary', 'beast', '#29b6f6', '#ffeb3b', 2300000, [
    S('z', 'Blue Flames', 'proj', { m: 1.3, cd: 4, sp: 950, r: 20, rng: 650, cnt: 4, spr: 0.5, st: { burn: 2 }, sh: 'flame' }),
    S('x', 'Phoenix Dive', 'dash', { m: 3.0, cd: 7, dist: 420, r: 80, dur: 0.25, sh: 'flame' }),
    S('c', 'Rebirth Flame', 'buff', { cd: 22, dur: 4, heal: 0.35 }),
    S('v', 'Phoenix Form', 'trans', { cd: 35, dur: 20 }),
    S('f', 'Blue Inferno', 'nova', { m: 3.6, cd: 10, r: 230, st: { burn: 3 }, sh: 'flame' }),
  ]);
  F('portal', 'Portal', 'legendary', 'natural', '#ce93d8', '#4a148c', 1900000, [
    S('z', 'Rift Shot', 'proj', { m: 2.4, cd: 4, sp: 1100, r: 26, rng: 750, pierce: -1, sh: 'ring' }),
    S('x', 'Gate Crush', 'pull', { m: 3.2, cd: 8, r: 200, rng: 500, force: 280, sh: 'ring' }),
    S('c', 'Portal Step', 'tele', { m: 2.0, cd: 6, rng: 800, r: 120, sh: 'ring' }),
    S('v', 'Dimension Collapse', 'blast', { m: 6.0, cd: 15, r: 260, rng: 550, d: 0.7, sh: 'ring' }),
    S('f', 'Mirror World', 'zone', { m: 3.6, cd: 12, r: 200, dur: 4, iv: 0.4, at: 'self', st: { slow: 1 }, sh: 'ring' }),
  ]);
  F('sound', 'Sound', 'legendary', 'natural', '#f48fb1', '#fce4ec', 1700000, [
    S('z', 'Sound Waves', 'proj', { m: 2.0, cd: 4, sp: 900, r: 40, rng: 650, pierce: -1, sh: 'note' }),
    S('x', 'Tempo Burst', 'nova', { m: 3.0, cd: 7, r: 220, st: { stun: 0.6 }, sh: 'note' }),
    S('c', 'Bass Drop', 'blast', { m: 3.8, cd: 9, r: 170, rng: 500, d: 0.5, st: { knock: 150 }, sh: 'note' }),
    S('v', 'Symphony', 'rain', { m: 3.2, cd: 14, cnt: 10, r: 100, area: 260, rng: 600, iv: 0.1, sh: 'note' }),
    S('f', 'Allegro', 'buff', { cd: 18, dur: 8, spd: 1.35, dmg: 1.15 }),
  ]);
  F('gravity', 'Gravity', 'mythical', 'natural', '#9575cd', '#311b92', 3200000, [
    S('z', 'Gravity Push', 'proj', { m: 2.6, cd: 5, sp: 800, r: 50, rng: 650, pierce: -1, st: { knock: 240 }, sh: 'orb' }),
    S('x', 'Singularity', 'pull', { m: 3.6, cd: 8, r: 260, rng: 500, force: 300, st: { slow: 1.5 }, sh: 'void' }),
    S('c', 'Meteor Fall', 'blast', { m: 5.0, cd: 10, r: 200, rng: 600, d: 0.9, st: { stun: 0.8 }, sh: 'meteor' }),
    S('v', 'Asteroid Crash', 'rain', { m: 4.0, cd: 16, cnt: 8, r: 150, area: 300, rng: 650, iv: 0.15, sh: 'meteor' }),
    S('f', 'Shooting Star', 'dash', { m: 2.6, cd: 8, dist: 480, r: 80, dur: 0.25, sh: 'void' }),
  ]);
  F('dough', 'Dough', 'mythical', 'natural', '#ffe0b2', '#8d6e63', 2800000, [
    S('z', 'Dough Fist', 'proj', { m: 2.4, cd: 4, sp: 1200, r: 34, rng: 700, pierce: 2, sh: 'fist' }),
    S('x', 'Rolling Pin', 'beam', { m: 4.0, cd: 7, len: 500, w: 110, ticks: 8, iv: 0.06, sh: 'fist' }),
    S('c', 'Sticky Trap', 'zone', { m: 3.2, cd: 9, r: 180, dur: 4, iv: 0.5, at: 'aim', rng: 500, st: { slow: 2 }, sh: 'dough' }),
    S('v', 'Mochi Barrage', 'rain', { m: 3.6, cd: 15, cnt: 12, r: 110, area: 280, rng: 650, iv: 0.07, sh: 'fist' }),
    S('f', 'Donut Dash', 'dash', { m: 2.4, cd: 7, dist: 460, r: 70, dur: 0.24, sh: 'dough' }),
  ]);
  F('shadow', 'Shadow', 'mythical', 'natural', '#7e57c2', '#000000', 2900000, [
    S('z', 'Shadow Bats', 'proj', { m: 1.2, cd: 4, sp: 950, r: 18, rng: 650, cnt: 6, spr: 0.7, sh: 'bat' }),
    S('x', 'Umbral Grasp', 'pull', { m: 3.4, cd: 8, r: 220, rng: 500, force: 260, st: { stun: 0.6 }, sh: 'void' }),
    S('c', 'Nightmare Lair', 'zone', { m: 4.8, cd: 11, r: 230, dur: 5, iv: 0.5, at: 'aim', rng: 500, st: { slow: 1 }, sh: 'void' }),
    S('v', 'Eclipse', 'nova', { m: 6.2, cd: 15, r: 320, d: 0.6, st: { stun: 0.6 }, sh: 'void' }),
    S('f', 'Shade Step', 'tele', { m: 2.0, cd: 6, rng: 600, r: 120, sh: 'void' }),
  ]);
  F('venom', 'Venom', 'mythical', 'elemental', '#76ff03', '#4a148c', 3500000, [
    S('z', 'Venom Spit', 'proj', { m: 1.6, cd: 4, sp: 900, r: 22, rng: 650, cnt: 3, spr: 0.3, st: { burn: 3 }, sh: 'drop' }),
    S('x', 'Toxic Fog', 'zone', { m: 4.0, cd: 8, r: 210, dur: 5, iv: 0.5, at: 'self', st: { slow: 1 }, sh: 'venom' }),
    S('c', 'Serpent Strike', 'dash', { m: 3.0, cd: 8, dist: 420, r: 70, dur: 0.24, st: { burn: 3 }, sh: 'venom' }),
    S('v', 'Hydra Form', 'trans', { cd: 40, dur: 22 }),
    S('f', 'Venom Rain', 'rain', { m: 3.0, cd: 12, cnt: 10, r: 100, area: 260, rng: 600, iv: 0.08, st: { burn: 2 }, sh: 'drop' }),
  ]);
  F('leopard', 'Leopard', 'mythical', 'beast', '#ffca28', '#5d4037', 4500000, [
    S('z', 'Pounce', 'dash', { m: 2.8, cd: 4, dist: 380, r: 70, dur: 0.18, sh: 'claw' }),
    S('x', 'Thousand Claws', 'beam', { m: 3.8, cd: 7, len: 200, w: 150, ticks: 8, iv: 0.06, sh: 'claw' }),
    S('c', 'Body Flicker', 'tele', { m: 2.6, cd: 7, rng: 550, r: 130, sh: 'claw' }),
    S('v', 'Leopard Form', 'trans', { cd: 35, dur: 20 }),
    S('f', 'Spiral Pounce', 'nova', { m: 3.6, cd: 9, r: 200, st: { knock: 160 }, sh: 'claw' }),
  ]);
  F('dragon', 'Dragon', 'mythical', 'beast', '#e53935', '#ffb300', 5000000, [
    S('z', 'Dragon Breath', 'beam', { m: 4.0, cd: 5, len: 520, w: 110, ticks: 8, iv: 0.08, st: { burn: 2 }, sh: 'flame' }),
    S('x', 'Draconic Claw', 'dash', { m: 3.4, cd: 7, dist: 420, r: 90, dur: 0.25, st: { knock: 150 }, sh: 'claw' }),
    S('c', 'Fireball Barrage', 'proj', { m: 2.0, cd: 9, sp: 900, r: 30, rng: 700, cnt: 5, spr: 0.6, boom: 90, st: { burn: 2 }, sh: 'meteor' }),
    S('v', 'Dragon Form', 'trans', { cd: 40, dur: 22 }),
    S('f', 'Wyrm Meteor', 'rain', { m: 3.6, cd: 12, cnt: 7, r: 140, area: 280, rng: 650, iv: 0.12, st: { burn: 3 }, sh: 'meteor' }),
  ]);
  F('kitsune', 'Kitsune', 'mythical', 'beast', '#4fc3f7', '#e1f5fe', 5500000, [
    S('z', 'Foxfire', 'proj', { m: 1.4, cd: 4, sp: 850, r: 22, rng: 700, cnt: 5, spr: 0.8, st: { burn: 2 }, sh: 'flame' }),
    S('x', 'Spirit Rush', 'dash', { m: 3.0, cd: 7, dist: 460, r: 80, dur: 0.24, sh: 'flame' }),
    S('c', 'Fox Lanterns', 'rain', { m: 3.0, cd: 10, cnt: 9, r: 110, area: 260, rng: 600, iv: 0.08, sh: 'flame' }),
    S('v', 'Kitsune Form', 'trans', { cd: 40, dur: 22 }),
    S('f', 'Nine Tails', 'nova', { m: 4.2, cd: 11, r: 260, st: { knock: 180, burn: 2 }, sh: 'flame' }),
  ]);

  // ─── Fighting styles, swords, guns ────────────────────────────────────────
  const STYLES = [
    { id: 'st_brawler', name: 'Brawler', base: 9, price: 0, sea: 0, color: '#ffccbc', skills: [
      S('z', 'Haymaker', 'dash', { m: 2.2, cd: 4, dist: 200, r: 60, dur: 0.15, st: { knock: 120 }, sh: 'fist' }),
      S('x', 'Ground Pound', 'nova', { m: 2.8, cd: 7, r: 130, st: { stun: 0.5 }, sh: 'crack' }),
      S('c', 'Flurry', 'beam', { m: 3.2, cd: 9, len: 140, w: 100, ticks: 6, iv: 0.07, sh: 'fist' }),
    ] },
    { id: 'st_iron', name: 'Iron Fist', base: 14, price: 150000, sea: 0, color: '#b0bec5', skills: [
      S('z', 'Iron Jab', 'beam', { m: 2.4, cd: 4, len: 180, w: 70, ticks: 1, iv: 0.05, st: { knock: 160 }, sh: 'fist' }),
      S('x', 'Steel Spin', 'nova', { m: 3.0, cd: 7, r: 150, st: { knock: 120 }, sh: 'ring' }),
      S('c', 'Anvil Drop', 'blast', { m: 3.8, cd: 9, r: 140, rng: 300, d: 0.4, st: { stun: 0.8 }, sh: 'crack' }),
    ] },
    { id: 'st_storm', name: 'Storm Step', base: 20, price: 900000, sea: 1, color: '#fff176', skills: [
      S('z', 'Volt Kick', 'dash', { m: 2.6, cd: 4, dist: 320, r: 60, dur: 0.16, st: { stun: 0.3 }, sh: 'bolt' }),
      S('x', 'Thunder Clap', 'nova', { m: 3.0, cd: 7, r: 180, st: { stun: 0.6 }, sh: 'bolt' }),
      S('c', 'Lightning Rush', 'chain', { m: 3.4, cd: 9, rng: 500, jumps: 5, jr: 260, sh: 'bolt' }),
    ] },
    { id: 'st_tide', name: 'Tide Palm', base: 24, price: 1500000, sea: 1, color: '#4dd0e1', skills: [
      S('z', 'Wave Palm', 'proj', { m: 2.6, cd: 4, sp: 900, r: 40, rng: 500, pierce: -1, st: { knock: 150 }, sh: 'wave' }),
      S('x', 'Whirlpool', 'pull', { m: 3.0, cd: 7, r: 200, rng: 350, force: 240, sh: 'wave' }),
      S('c', 'Tsunami Strike', 'beam', { m: 4.2, cd: 9, len: 500, w: 140, ticks: 3, iv: 0.12, st: { knock: 120 }, sh: 'wave' }),
    ] },
    { id: 'st_dragon', name: 'Dragon Claw', base: 30, price: 2500000, frags: 1500, sea: 2, color: '#ff7043', skills: [
      S('z', 'Dragon Talon', 'dash', { m: 2.8, cd: 4, dist: 340, r: 70, dur: 0.18, st: { burn: 2 }, sh: 'claw' }),
      S('x', 'Flame Vortex', 'nova', { m: 3.4, cd: 7, r: 200, st: { burn: 3, knock: 120 }, sh: 'flame' }),
      S('c', 'Dragon Roar', 'beam', { m: 4.6, cd: 9, len: 550, w: 130, ticks: 5, iv: 0.08, st: { burn: 2 }, sh: 'flame' }),
    ] },
    { id: 'st_godhand', name: 'Godhand', base: 40, price: 5000000, frags: 5000, minLevel: 2500, sea: 3, color: '#ffe082', skills: [
      S('z', 'Divine Jab', 'beam', { m: 3.0, cd: 4, len: 260, w: 80, ticks: 1, iv: 0.05, st: { knock: 200 }, sh: 'light' }),
      S('x', 'Heaven Crash', 'blast', { m: 4.0, cd: 7, r: 200, rng: 400, d: 0.4, st: { stun: 0.7 }, sh: 'light' }),
      S('c', 'Fist of Creation', 'proj', { m: 5.2, cd: 9, sp: 1000, r: 70, rng: 800, pierce: -1, boom: 180, sh: 'fist' }),
    ] },
  ];

  const SWORD_SKILLS = {
    dashslash: { t: 'dash', n: 'Dash Slash', m: 2.4, cd: 5, dist: 260, r: 60, dur: 0.18, sh: 'slash' },
    spin: { t: 'nova', n: 'Whirlwind', m: 2.8, cd: 7, r: 140, st: { knock: 60 }, sh: 'slash' },
    wave: { t: 'proj', n: 'Air Slash', m: 2.6, cd: 6, sp: 950, r: 34, rng: 650, pierce: -1, sh: 'crescent' },
    multi: { t: 'beam', n: 'Thousand Cuts', m: 3.6, cd: 8, len: 150, w: 120, ticks: 6, iv: 0.08, sh: 'slash' },
    pierce: { t: 'dash', n: 'Piercing Lunge', m: 3.2, cd: 7, dist: 380, r: 50, dur: 0.22, sh: 'slash' },
    quake: { t: 'blast', n: 'Earth Splitter', m: 3.4, cd: 8, r: 150, rng: 260, d: 0.35, st: { stun: 0.6 }, sh: 'crack' },
    triple: { t: 'proj', n: 'Triple Arc', m: 2.2, cd: 7, sp: 900, r: 28, rng: 600, cnt: 3, spr: 0.5, sh: 'crescent' },
  };
  const GUN_SKILLS = {
    burst: { t: 'proj', n: 'Burst Fire', m: 1.0, cd: 4, sp: 1500, r: 10, rng: 800, cnt: 4, spr: 0.2, sh: 'bullet' },
    snipe: { t: 'proj', n: 'Deadeye', m: 3.2, cd: 7, sp: 2400, r: 12, rng: 1200, pierce: -1, sh: 'bullet' },
    grenade: { t: 'blast', n: 'Grenade', m: 2.8, cd: 6, r: 140, rng: 600, d: 0.6, sh: 'bomb' },
    barrage: { t: 'rain', n: 'Barrage', m: 1.8, cd: 9, cnt: 8, r: 90, area: 220, rng: 650, iv: 0.08, sh: 'bullet' },
    cannon: { t: 'proj', n: 'Cannonball', m: 3.6, cd: 8, sp: 900, r: 26, rng: 800, boom: 130, sh: 'meteor' },
  };
  function weaponSkills(tbl, z, x, st) {
    return [Object.assign({ k: 'z' }, tbl[z], st ? { st: Object.assign({}, tbl[z].st, st) } : {}),
            Object.assign({ k: 'x' }, tbl[x], st ? { st: Object.assign({}, tbl[x].st, st) } : {})];
  }
  const SWORDS = [];
  function SW(id, name, base, price, sea, color, z, x, st, drop) {
    SWORDS.push({ id: 'sw_' + id, name, base, price, sea, color, skills: weaponSkills(SWORD_SKILLS, z, x, st), drop: !!drop });
  }
  SW('drift', 'Driftwood Blade', 10, 0, 0, '#bcaaa4', 'dashslash', 'spin');
  SW('cutlass', 'Cutlass', 12, 5000, 0, '#cfd8dc', 'dashslash', 'wave');
  SW('twin', 'Twin Katanas', 14, 60000, 0, '#eceff1', 'multi', 'dashslash');
  SW('cleaver', 'Iron Cleaver', 16, 250000, 0, '#90a4ae', 'quake', 'spin');
  SW('redgill', "Redgill's Saber", 15, 0, 0, '#e57373', 'wave', 'spin', null, true);
  SW('frost', 'Frostbite Tachi', 18, 0, 0, '#81d4fa', 'pierce', 'wave', { slow: 1 }, true);
  SW('warden', "Warden's Chainblade", 20, 0, 0, '#78909c', 'triple', 'quake', null, true);
  SW('tide', 'Tidecutter', 22, 0, 0, '#4dd0e1', 'wave', 'multi', null, true);
  SW('rose', 'Rosethorn Rapier', 24, 1000000, 1, '#f06292', 'pierce', 'multi');
  SW('lantern', 'Lantern Scythe', 26, 0, 1, '#ffb74d', 'spin', 'triple', { burn: 2 }, true);
  SW('pyre', 'Pyre Glaive', 28, 0, 1, '#ff7043', 'quake', 'wave', { burn: 2 }, true);
  SW('drowned', 'Drowned Cutlass', 29, 2000000, 1, '#26a69a', 'dashslash', 'triple');
  SW('storm', 'Stormsplitter', 32, 3000000, 2, '#ffee58', 'pierce', 'quake', { stun: 0.2 });
  SW('reaper', 'Soulreaper Scythe', 35, 0, 2, '#9575cd', 'spin', 'multi', null, true);
  SW('sun', 'Sunblade', 37, 0, 2, '#ffd54f', 'wave', 'triple', { burn: 2 }, true);
  SW('void', 'Void Katana', 40, 6000000, 3, '#7c4dff', 'pierce', 'multi');
  SW('fang', 'Leviathan Fang', 43, 0, 3, '#00bfa5', 'triple', 'quake', null, true);
  SW('trident', "Sovereign's Trident", 47, 0, 3, '#40c4ff', 'pierce', 'wave', { stun: 0.2 }, true);

  const GUNS = [];
  function GN(id, name, base, price, sea, color, z, x, st, drop) {
    GUNS.push({ id: 'gn_' + id, name, base, price, sea, color, skills: weaponSkills(GUN_SKILLS, z, x, st), drop: !!drop });
  }
  GN('flint', 'Flintlock', 9, 3000, 0, '#8d6e63', 'burst', 'snipe');
  GN('musket', 'Musket', 12, 40000, 0, '#6d4c41', 'snipe', 'grenade');
  GN('repeater', 'Repeater Pistol', 15, 200000, 0, '#546e7a', 'burst', 'barrage');
  GN('harpoon', 'Harpoon Gun', 19, 0, 0, '#26c6da', 'snipe', 'cannon', null, true);
  GN('blunder', 'Ember Blunderbuss', 23, 1200000, 1, '#ff7043', 'burst', 'cannon', { burn: 2 });
  GN('frostbore', 'Frostbore Rifle', 26, 0, 1, '#81d4fa', 'snipe', 'grenade', { slow: 1 }, true);
  GN('storm', 'Storm Rifle', 31, 2800000, 2, '#ffee58', 'snipe', 'barrage', { stun: 0.2 });
  GN('candy', 'Candy Cannon', 34, 0, 2, '#f48fb1', 'cannon', 'barrage', null, true);
  GN('abyss', 'Abyss Cannon', 39, 5500000, 3, '#5c6bc0', 'cannon', 'grenade');
  GN('comet', 'Comet Launcher', 44, 0, 3, '#b388ff', 'barrage', 'cannon', null, true);

  const ABILITIES = [
    { id: 'aura', name: 'Aura', price: 25000, desc: '+10% damage. Hits elemental fruit users at full force.' },
    { id: 'flash', name: 'Flash Step', price: 100000, desc: 'Dash (Q) goes further and recharges faster.' },
    { id: 'instinct', name: 'Instinct', price: 750000, desc: '12% chance to dodge any incoming hit.' },
  ];

  // ─── Seas, islands, mobs and bosses ──────────────────────────────────────
  // Look: [form, shirt, pants, hat, hatColor, skin]. Forms: h human, a ape,
  // g golem, s spirit, f fishman, b beast. Hats: 0 none, 1 bandana, 2 cap,
  // 3 helmet, 4 tricorn, 5 crown, 6 horns, 7 hood, 8 halo, 9 top hat.
  const SEA_DEFS = [
    {
      name: 'Dawn Sea', minLevel: 1, water: ['#2a8fd6', '#1f6fb3'], foam: '#bfefff', w: 9000, h: 9000,
      beast: ['Reef Eel', 360, ['f', '#2e7d32', '#1b5e20', 0, '', '#66bb6a']],
      islands: [
        ['Driftwood Isle', 'meadow', 1200, 1300, 640, true,
          [['Beach Thug', 1, ['h', '#e57373', '#5d4037', 1, '#c62828', '#f1c27d']], ['Crab Raider', 8, ['h', '#ff8a65', '#4e342e', 2, '#d84315', '#e0ac69']]],
          ['Big Barnacle', 15, ['h', '#8d6e63', '#3e2723', 4, '#212121', '#e0ac69', 1.5], ['slam', 'charge']]],
        ['Monkey Jungle', 'jungle', 3300, 1100, 560, false,
          [['Jungle Monkey', 20, ['a', '#8d6e63', '#6d4c41', 0, '', '#a1887f']], ['Silverback', 35, ['a', '#616161', '#424242', 0, '', '#9e9e9e', 1.2]]],
          ['Ape King', 55, ['a', '#5d4037', '#3e2723', 5, '#ffd54f', '#8d6e63', 1.6], ['slam', 'charge']]],
        ['Saltpine Cove', 'cove', 5600, 1400, 560, false,
          [['Cove Pirate', 65, ['h', '#37474f', '#263238', 1, '#b71c1c', '#e0ac69']], ['Cutlass Brute', 90, ['h', '#4e342e', '#212121', 4, '#212121', '#c68642', 1.2]]],
          ['Captain Redgill', 115, ['h', '#b71c1c', '#212121', 4, '#3e2723', '#c68642', 1.6], ['slam', 'volley', 'charge'], 'sw_redgill']],
        ['Sunscorch Desert', 'desert', 7700, 2200, 650, false,
          [['Dune Bandit', 125, ['h', '#ffe0b2', '#a1887f', 7, '#d7ccc8', '#c68642']], ['Desert Officer', 160, ['h', '#ffcc80', '#6d4c41', 2, '#8d6e63', '#c68642']]],
          ['Sandstorm Sultan', 195, ['h', '#ffd54f', '#bf360c', 5, '#ffca28', '#a1665e', 1.6], ['nova', 'volley', 'rain']]],
        ['Frostpeak', 'snow', 7400, 4600, 620, false,
          [['Snow Bandit', 205, ['h', '#90caf9', '#37474f', 7, '#e3f2fd', '#f1c27d']], ['Ice Golem', 245, ['g', '#b3e5fc', '#81d4fa', 0, '', '#e1f5fe', 1.3]]],
          ['Yeti Lord', 290, ['a', '#eceff1', '#cfd8dc', 6, '#90a4ae', '#ffffff', 1.8], ['slam', 'nova', 'charge'], 'sw_frost']],
        ['Marine Bastion', 'fort', 5200, 3600, 560, false,
          [['Marine Cadet', 300, ['h', '#eceff1', '#1565c0', 2, '#1565c0', '#f1c27d']], ['Marine Lieutenant', 335, ['h', '#ffffff', '#0d47a1', 2, '#0d47a1', '#e0ac69']]],
          ['Vice Admiral Hask', 375, ['h', '#ffffff', '#0d47a1', 9, '#eceff1', '#e0ac69', 1.6], ['volley', 'charge', 'slam'], 'gn_harpoon']],
        ['Cloudspire', 'sky', 2900, 3600, 520, false,
          [['Sky Raider', 385, ['h', '#fff9c4', '#90a4ae', 3, '#ffd54f', '#f1c27d']], ['Wind Monk', 425, ['h', '#ffcc80', '#ff8a65', 0, '', '#e0ac69']]],
          ['Thunder Priest', 465, ['h', '#fff176', '#5c6bc0', 6, '#ffeb3b', '#e0ac69', 1.6], ['rain', 'nova', 'beam']]],
        ['Iron Gaol', 'prison', 1300, 5200, 560, false,
          [['Prisoner', 475, ['h', '#ffa726', '#ffa726', 0, '', '#c68642']], ['Gaol Warden', 515, ['h', '#455a64', '#263238', 3, '#37474f', '#e0ac69']]],
          ['The Chain Warden', 555, ['h', '#37474f', '#212121', 3, '#212121', '#8d5524', 1.7], ['charge', 'slam', 'volley'], 'sw_warden']],
        ['Colosseum Ruins', 'arena', 3600, 6300, 600, false,
          [['Gladiator', 565, ['h', '#ff8a65', '#5d4037', 3, '#bdbdbd', '#c68642']], ['Arena Champion', 605, ['h', '#ffd54f', '#6d4c41', 3, '#ffca28', '#8d5524', 1.2]]],
          ['Gladiator King', 640, ['h', '#ffca28', '#b71c1c', 5, '#ffd54f', '#8d5524', 1.8], ['charge', 'nova', 'slam']]],
        ['Coral Depths', 'coral', 6400, 7200, 620, false,
          [['Reef Warrior', 650, ['f', '#26c6da', '#00838f', 0, '', '#4dd0e1']], ['Reef Commando', 675, ['f', '#00897b', '#004d40', 1, '#ff7043', '#26a69a', 1.2]]],
          ['Tide Tyrant', 700, ['f', '#00695c', '#004d40', 5, '#ffd54f', '#26a69a', 1.9], ['nova', 'volley', 'beam', 'rain'], 'sw_tide']],
      ],
    },
    {
      name: 'Crimson Sea', minLevel: 700, water: ['#7a2d4a', '#4f1530'], foam: '#ffb3c7', w: 9000, h: 9000,
      beast: ['Crimson Serpent', 1200, ['f', '#c62828', '#7f0000', 6, '#ffcdd2', '#e53935']],
      islands: [
        ['Harbor of Embers', 'ember', 1300, 1300, 660, true,
          [['Dock Rat', 705, ['h', '#8d6e63', '#3e2723', 1, '#ff7043', '#c68642']], ['Ember Smuggler', 730, ['h', '#ff7043', '#3e2723', 9, '#212121', '#e0ac69']]],
          ['Harbormaster Kade', 775, ['h', '#bf360c', '#212121', 4, '#212121', '#c68642', 1.6], ['charge', 'volley']]],
        ['Rosethorn Kingdom', 'flower', 3700, 1200, 600, false,
          [['Thorn Guard', 785, ['h', '#66bb6a', '#2e7d32', 3, '#81c784', '#f1c27d']], ['Rose Knight', 830, ['h', '#f06292', '#880e4f', 3, '#f8bbd0', '#f1c27d', 1.2]]],
          ['Queen Briar', 870, ['h', '#ec407a', '#880e4f', 5, '#ffd54f', '#f1c27d', 1.7], ['rain', 'nova', 'volley']]],
        ['Green Zone', 'swamp', 6200, 1300, 580, false,
          [['Bog Lurker', 880, ['f', '#558b2f', '#33691e', 0, '', '#7cb342']], ['Swamp Witch', 925, ['h', '#4a148c', '#1b5e20', 7, '#311b92', '#aed581']]],
          ['Mire Hydra', 970, ['b', '#33691e', '#1b5e20', 6, '#c5e1a5', '#558b2f', 2.0], ['volley', 'rain', 'nova'], 'sw_lantern']],
        ['Graveyard Isle', 'grave', 7700, 3400, 560, false,
          [['Restless Ghoul', 980, ['s', '#90a4ae', '#546e7a', 0, '', '#b0bec5']], ['Grave Digger', 1025, ['h', '#5d4037', '#3e2723', 9, '#212121', '#bcaaa4']]],
          ['Lord of Lanterns', 1070, ['s', '#ffb74d', '#4e342e', 9, '#212121', '#ffe0b2', 1.8], ['rain', 'volley', 'beam']]],
        ['Snow Mountain', 'snow', 5400, 3500, 620, false,
          [['Frost Reaver', 1080, ['h', '#4fc3f7', '#01579b', 6, '#e1f5fe', '#e1f5fe']], ['Winter Wolf', 1125, ['b', '#eceff1', '#b0bec5', 0, '', '#eceff1', 1.1]]],
          ['Glacier Colossus', 1170, ['g', '#81d4fa', '#4fc3f7', 6, '#e1f5fe', '#b3e5fc', 2.1], ['slam', 'nova', 'charge'], 'gn_frostbore']],
        ['Hot and Cold', 'volcano', 2900, 3700, 620, false,
          [['Lava Imp', 1180, ['s', '#ff7043', '#bf360c', 6, '#212121', '#ff8a65']], ['Magma Brute', 1225, ['g', '#5d4037', '#3e2723', 0, '', '#ff5722', 1.3]]],
          ['Pyre Warlord', 1270, ['h', '#d84315', '#212121', 6, '#ff6d00', '#8d5524', 1.8], ['rain', 'nova', 'charge'], 'sw_pyre']],
        ['Cursed Ship', 'ship', 1300, 5600, 540, false,
          [['Cursed Deckhand', 1280, ['s', '#4db6ac', '#004d40', 1, '#263238', '#b2dfdb']], ['Cursed Captain', 1325, ['s', '#26a69a', '#004d40', 4, '#212121', '#b2dfdb', 1.2]]],
          ['Admiral of the Drowned', 1370, ['s', '#00897b', '#263238', 4, '#ffd54f', '#80cbc4', 1.8], ['volley', 'beam', 'charge']]],
        ['Ice Castle', 'ice', 3900, 6400, 600, false,
          [['Frozen Sentinel', 1380, ['g', '#b3e5fc', '#4fc3f7', 3, '#e1f5fe', '#e1f5fe']], ['Ice Knight', 1415, ['h', '#e1f5fe', '#0277bd', 3, '#b3e5fc', '#e1f5fe', 1.2]]],
          ['Crystal Empress', 1450, ['h', '#b3e5fc', '#0288d1', 5, '#e1f5fe', '#e1f5fe', 1.7], ['nova', 'rain', 'beam']]],
        ['Forgotten Island', 'ruins', 6700, 6500, 620, false,
          [['Lost Corsair', 1455, ['h', '#6d4c41', '#3e2723', 4, '#4e342e', '#c68642']], ['Ruin Seeker', 1480, ['h', '#8d6e63', '#4e342e', 7, '#5d4037', '#e0ac69']]],
          ['The Forgotten', 1500, ['s', '#9e9e9e', '#424242', 8, '#ffd54f', '#e0e0e0', 1.9], ['beam', 'nova', 'rain', 'charge']]],
      ],
    },
    {
      name: 'Tempest Sea', minLevel: 1500, water: ['#2a6b74', '#163f4a'], foam: '#c8fff4', w: 9000, h: 9000,
      beast: ['Storm Serpent', 2000, ['f', '#ffee58', '#f9a825', 6, '#40c4ff', '#fff59d']],
      islands: [
        ['Port of Storms', 'storm', 1400, 1400, 660, true,
          [['Storm Pirate', 1505, ['h', '#546e7a', '#263238', 1, '#ffee58', '#e0ac69']], ['Gale Corsair', 1540, ['h', '#78909c', '#37474f', 4, '#263238', '#c68642']]],
          ['Stormcaller Vex', 1580, ['h', '#ffee58', '#263238', 6, '#40c4ff', '#e0ac69', 1.6], ['rain', 'charge']]],
        ['Hydra Fields', 'hydra', 4000, 1300, 620, false,
          [['Hydra Cultist', 1590, ['h', '#7b1fa2', '#311b92', 7, '#4a148c', '#d1c4e9']], ['Serpent Guard', 1630, ['f', '#6a1b9a', '#4a148c', 3, '#ce93d8', '#ab47bc', 1.2]]],
          ['Three-Headed Ruin', 1670, ['b', '#4a148c', '#311b92', 6, '#e1bee7', '#7b1fa2', 2.1], ['volley', 'rain', 'nova']]],
        ['Great Tree', 'bigtree', 6900, 1700, 680, false,
          [['Bark Marine', 1680, ['h', '#ffffff', '#1565c0', 2, '#1565c0', '#e0ac69']], ['Canopy Sniper', 1725, ['h', '#558b2f', '#33691e', 7, '#33691e', '#c68642']]],
          ['Elder Treant', 1770, ['g', '#6d4c41', '#33691e', 6, '#7cb342', '#8d6e63', 2.2], ['slam', 'rain', 'nova']]],
        ['Floating Turtle', 'turtle', 7300, 4600, 700, false,
          [['Shell Raider', 1780, ['f', '#43a047', '#1b5e20', 1, '#ffca28', '#81c784']], ['Jungle Fishman', 1825, ['f', '#00897b', '#004d40', 0, '', '#4db6ac', 1.2]]],
          ['Ancient Tortoise', 1870, ['g', '#558b2f', '#33691e', 0, '', '#8bc34a', 2.3], ['slam', 'nova', 'charge']]],
        ['Haunted Castle', 'haunted', 4500, 4100, 600, false,
          [['Bone Knight', 1880, ['s', '#eceff1', '#424242', 3, '#9e9e9e', '#eeeeee']], ['Wraith Mage', 1925, ['s', '#7e57c2', '#311b92', 7, '#4527a0', '#d1c4e9', 1.1]]],
          ['Soul Reaper', 1970, ['s', '#212121', '#000000', 7, '#212121', '#b39ddb', 1.9], ['charge', 'beam', 'rain'], 'sw_reaper']],
        ['Sweet Archipelago', 'candy', 1700, 4400, 620, false,
          [['Cookie Crafter', 1980, ['h', '#ffcc80', '#8d6e63', 9, '#f48fb1', '#ffe0b2']], ['Candy Rebel', 2025, ['h', '#f48fb1', '#ad1457', 1, '#ffffff', '#ffe0b2', 1.1]]],
          ['Cake Monarch', 2070, ['h', '#f8bbd0', '#ec407a', 5, '#ffd54f', '#ffe0b2', 2.0], ['rain', 'volley', 'nova'], 'gn_candy']],
        ['Tiki Outpost', 'tiki', 2700, 7000, 580, false,
          [['Tiki Warrior', 2080, ['h', '#8d6e63', '#ff7043', 6, '#ffb74d', '#8d5524']], ['Island Shaman', 2125, ['h', '#ffb74d', '#bf360c', 6, '#4caf50', '#8d5524', 1.1]]],
          ['Volcano Idol', 2170, ['g', '#5d4037', '#3e2723', 5, '#ff6d00', '#ff7043', 2.2], ['rain', 'slam', 'beam']]],
        ['Sky Temple', 'temple', 5600, 7100, 650, false,
          [['Temple Guardian', 2180, ['g', '#ffe082', '#ffb300', 3, '#ffd54f', '#fff8e1']], ['Celestial Monk', 2235, ['h', '#fff8e1', '#ffb300', 8, '#ffd54f', '#f1c27d', 1.1]]],
          ['Sun Sovereign', 2295, ['h', '#ffd54f', '#ff6f00', 8, '#ffeb3b', '#fff3e0', 2.0], ['beam', 'rain', 'nova', 'charge'], 'sw_sun']],
      ],
    },
    {
      name: 'Abyssal Sea', minLevel: 2300, water: ['#1a1f4a', '#0b0d26'], foam: '#7fd7ff', w: 9000, h: 9000,
      beast: ['Abyss Leviathan', 2800, ['f', '#283593', '#1a237e', 6, '#00e5ff', '#3949ab']],
      islands: [
        ['Lantern Reef', 'abyss', 1400, 1400, 660, true,
          [['Abyss Diver', 2305, ['f', '#3949ab', '#1a237e', 3, '#80d8ff', '#5c6bc0']], ['Lantern Eel', 2335, ['f', '#00838f', '#004d40', 0, '', '#00e5ff', 1.1]]],
          ['Anglerfish Queen', 2375, ['f', '#1a237e', '#000051', 5, '#00e5ff', '#304ffe', 1.8], ['volley', 'charge']]],
        ['Obsidian Wastes', 'obsidian', 4300, 1300, 620, false,
          [['Obsidian Ghoul', 2385, ['s', '#424242', '#212121', 0, '', '#616161']], ['Ash Revenant', 2425, ['s', '#ff7043', '#212121', 7, '#212121', '#9e9e9e', 1.1]]],
          ['Ashen Behemoth', 2470, ['g', '#212121', '#000000', 6, '#ff3d00', '#424242', 2.3], ['slam', 'nova', 'rain']]],
        ['Crystal Spires', 'crystal', 7300, 1900, 640, false,
          [['Crystal Golem', 2485, ['g', '#e040fb', '#aa00ff', 0, '', '#ea80fc']], ['Prism Mage', 2525, ['h', '#b388ff', '#651fff', 7, '#7c4dff', '#ede7f6', 1.1]]],
          ['Prism Overlord', 2570, ['g', '#ea80fc', '#7c4dff', 5, '#ffffff', '#f3e5f5', 2.2], ['beam', 'rain', 'nova']]],
        ['Void Rift', 'void', 6900, 4800, 620, false,
          [['Void Walker', 2585, ['s', '#311b92', '#000000', 7, '#1a0033', '#7c4dff']], ['Rift Stalker', 2625, ['b', '#4527a0', '#1a0033', 6, '#b388ff', '#651fff', 1.2]]],
          ['Rift Tyrant', 2670, ['s', '#12005e', '#000000', 6, '#d500f9', '#7c4dff', 2.2], ['beam', 'charge', 'rain', 'nova']]],
        ['Leviathan Graveyard', 'bone', 3900, 4200, 660, false,
          [['Bone Leviathan', 2685, ['b', '#eceff1', '#bdbdbd', 6, '#e0e0e0', '#f5f5f5', 1.2]], ['Drowned Admiral', 2725, ['s', '#26a69a', '#004d40', 9, '#212121', '#80cbc4', 1.1]]],
          ['Kraken Herald', 2770, ['f', '#ad1457', '#4a148c', 6, '#f48fb1', '#ec407a', 2.3], ['volley', 'rain', 'charge', 'nova'], 'sw_fang']],
        ['Celestial Atoll', 'celestial', 1600, 5600, 600, false,
          [['Star Sentinel', 2785, ['g', '#e3f2fd', '#90caf9', 8, '#fff59d', '#ffffff']], ['Astral Duelist', 2825, ['h', '#e8eaf6', '#3949ab', 8, '#fff59d', '#e8eaf6', 1.1]]],
          ['Comet Warden', 2870, ['h', '#fff59d', '#283593', 8, '#ffffff', '#e8eaf6', 2.1], ['rain', 'beam', 'volley', 'charge'], 'gn_comet']],
        ['Throne of Tides', 'throne', 5000, 7200, 780, false,
          [['Tide Templar', 2885, ['h', '#00b8d4', '#004d40', 3, '#ffd54f', '#b2ebf2']], ['Abyssal Champion', 2945, ['f', '#00838f', '#002f3f', 5, '#ffd54f', '#26c6da', 1.3]]],
          ['The Abyssal Sovereign', 3000, ['f', '#00e5ff', '#001f3f', 5, '#ffd54f', '#18ffff', 2.6], ['beam', 'rain', 'nova', 'charge', 'volley', 'slam'], 'sw_trident']],
      ],
    },
  ];

  const BIOMES = {
    meadow:   { sand: '#f3dfa2', ground: '#71bf52', ground2: '#5ea845', decor: ['palm', 'bush', 'rock', 'palm', 'flower'] },
    jungle:   { sand: '#e9d79a', ground: '#3f9442', ground2: '#2f7a34', decor: ['tree', 'bush', 'tree', 'palm', 'rock'] },
    cove:     { sand: '#efd9a0', ground: '#6aa95a', ground2: '#5a9550', decor: ['palm', 'barrel', 'crate', 'hut', 'rock'] },
    desert:   { sand: '#f5dc96', ground: '#e8c374', ground2: '#d9ad5e', decor: ['cactus', 'rock', 'ruin', 'cactus'] },
    snow:     { sand: '#dfe8ef', ground: '#f3f7fb', ground2: '#dde8f0', decor: ['pine', 'rock', 'pine', 'snowman'] },
    fort:     { sand: '#e6d6a8', ground: '#a7b0b8', ground2: '#949ea7', decor: ['crate', 'cannon', 'flag', 'crate'] },
    sky:      { sand: '#ffffff', ground: '#e6f0ff', ground2: '#d2e2fb', decor: ['cloud', 'pillar', 'cloud'] },
    prison:   { sand: '#c9c1a3', ground: '#7e848b', ground2: '#6c7279', decor: ['wall', 'crate', 'torch'] },
    arena:    { sand: '#efd9a8', ground: '#d8b98a', ground2: '#c9a677', decor: ['pillar', 'ruin', 'torch'] },
    coral:    { sand: '#fbe3c2', ground: '#ee9aaa', ground2: '#e07f93', decor: ['coral', 'shell', 'coral', 'rock'] },
    ember:    { sand: '#d9b48a', ground: '#8f735c', ground2: '#7b604b', decor: ['crate', 'lamp', 'hut', 'barrel'] },
    flower:   { sand: '#f1dfaa', ground: '#7dc96b', ground2: '#6ab45a', decor: ['flower', 'bush', 'flower', 'tree'] },
    swamp:    { sand: '#b5a874', ground: '#5d7c3c', ground2: '#4b6830', decor: ['mush', 'deadtree', 'reed', 'mush'] },
    grave:    { sand: '#9da59a', ground: '#4c5c54', ground2: '#3e4c45', decor: ['tomb', 'deadtree', 'lamp', 'tomb'] },
    volcano:  { sand: '#8a7a70', ground: '#4c3a34', ground2: '#3d2e29', decor: ['lava', 'rock', 'crystal', 'rock'] },
    ship:     { sand: '#b48a5a', ground: '#8b6a45', ground2: '#7a5b3a', decor: ['mast', 'barrel', 'crate', 'cannon'] },
    ice:      { sand: '#e6f5fb', ground: '#bfe3f2', ground2: '#a8d6ea', decor: ['crystal', 'pine', 'crystal'] },
    ruins:    { sand: '#e0d3a8', ground: '#8f9a7a', ground2: '#7d876a', decor: ['ruin', 'pillar', 'tree', 'rock'] },
    storm:    { sand: '#cdbf96', ground: '#6f8a7a', ground2: '#5f7a6b', decor: ['lamp', 'crate', 'hut', 'barrel'] },
    hydra:    { sand: '#c7b9d6', ground: '#6d5a8a', ground2: '#5c4a78', decor: ['crystal', 'deadtree', 'mush'] },
    bigtree:  { sand: '#d9cc96', ground: '#4f8f3c', ground2: '#3f7a30', decor: ['tree', 'tree', 'bush', 'flower'] },
    turtle:   { sand: '#d8cf98', ground: '#5ea04a', ground2: '#4c8c3c', decor: ['tree', 'palm', 'rock', 'bush'] },
    haunted:  { sand: '#8e8a9a', ground: '#3d3a4c', ground2: '#322f40', decor: ['tomb', 'deadtree', 'torch', 'ruin'] },
    candy:    { sand: '#fff0f5', ground: '#f8bbd0', ground2: '#f3a6c0', decor: ['candy', 'candy', 'mush', 'flower'] },
    tiki:     { sand: '#efd29a', ground: '#7a9a46', ground2: '#69883a', decor: ['torch', 'palm', 'hut', 'rock'] },
    temple:   { sand: '#fff3d6', ground: '#f0e0b0', ground2: '#e4cf98', decor: ['pillar', 'torch', 'ruin'] },
    abyss:    { sand: '#47507a', ground: '#2c355a', ground2: '#242c4c', decor: ['lamp', 'coral', 'crystal'] },
    obsidian: { sand: '#5a5a5a', ground: '#2a2a2e', ground2: '#202024', decor: ['lava', 'crystal', 'rock'] },
    crystal:  { sand: '#e9d7f5', ground: '#a17bc4', ground2: '#8c66b0', decor: ['crystal', 'crystal', 'rock'] },
    void:     { sand: '#3a2f5c', ground: '#1d1533', ground2: '#160f28', decor: ['crystal', 'pillar', 'ruin'] },
    bone:     { sand: '#c9c3b5', ground: '#6d6a62', ground2: '#5b5851', decor: ['bones', 'tomb', 'rock'] },
    celestial:{ sand: '#e8eaf6', ground: '#3d4a8c', ground2: '#323e78', decor: ['crystal', 'pillar', 'lamp'] },
    throne:   { sand: '#b2ebf2', ground: '#2f6f7c', ground2: '#255d69', decor: ['pillar', 'coral', 'lamp', 'ruin'] },
  };

  // NPC kinds — the hub island of each sea carries the full set.
  const NPC_KINDS = {
    quest:   { name: 'Quest Giver', icon: '!', color: '#ffd54f' },
    fruit:   { name: 'Fruit Merchant', icon: '◉', color: '#ff7043' },
    gacha:   { name: 'Fruit Mystic', icon: '?', color: '#ce93d8' },
    sword:   { name: 'Blacksmith', icon: '⚔', color: '#b0bec5' },
    gun:     { name: 'Gunsmith', icon: '➹', color: '#a1887f' },
    style:   { name: 'Martial Master', icon: '✊', color: '#ffab91' },
    ability: { name: 'Aura Sage', icon: '✦', color: '#80deea' },
    ferry:   { name: 'Ferry Captain', icon: '⚓', color: '#4fc3f7' },
    reset:   { name: 'Stat Trainer', icon: '↺', color: '#aed581' },
    awaken:  { name: 'Awakener', icon: '☀', color: '#ffe082' },
  };

  // ─── Build the world ──────────────────────────────────────────────────────
  const SEAS = [];
  const MOB_TYPES = [];
  const NPCS = [];
  const HUB_NPCS = ['quest', 'fruit', 'gacha', 'sword', 'gun', 'style', 'ability', 'ferry', 'reset', 'awaken'];

  function buildShape(isl) {
    const rnd = mulberry32(hashStr(isl.name));
    const harm = [[2, 0.04 + rnd() * 0.06], [3, 0.03 + rnd() * 0.05], [5, 0.02 + rnd() * 0.03], [7, 0.01 + rnd() * 0.02]]
      .map(([k, a]) => [k, a, rnd() * TAU]);
    const N = 96;
    const radii = new Array(N);
    for (let i = 0; i < N; i++) {
      const th = (i / N) * TAU;
      let f = 1;
      for (const [k, a, ph] of harm) f += a * Math.sin(k * th + ph);
      radii[i] = isl.R * f;
    }
    isl.radii = radii;
  }
  function radiusAt(isl, th) {
    const N = isl.radii.length;
    let u = (th / TAU) * N;
    u = ((u % N) + N) % N;
    const i = Math.floor(u), f = u - i;
    return isl.radii[i] * (1 - f) + isl.radii[(i + 1) % N] * f;
  }
  // A point `frac` of the way out from the centre at angle `ang`.
  function pointIn(isl, ang, frac) {
    const r = radiusAt(isl, ang) * frac;
    return { x: Math.round(isl.x + Math.cos(ang) * r), y: Math.round(isl.y + Math.sin(ang) * r) };
  }

  SEA_DEFS.forEach((sd, si) => {
    const sea = { idx: si, name: sd.name, minLevel: sd.minLevel, water: sd.water, foam: sd.foam, w: sd.w, h: sd.h, islands: [], beast: null };
    sd.islands.forEach((row, ii) => {
      const [name, biome, x, y, R, hub, mobs, boss] = row;
      const isl = { idx: ii, sea: si, name, biome, x, y, R, hub, mobs: [], boss: -1, npcs: [], spawns: [] };
      buildShape(isl);
      const lvLo = mobs[0][1], lvHi = boss[1];
      isl.lv = [lvLo, lvHi];
      // Towns keep their shops on the northern half and their monsters on the
      // southern shore, far enough apart that nobody gets mobbed at a counter.
      const mobAngles = hub ? [Math.PI * 0.5 + 0.95, Math.PI * 0.5 - 0.95] : [Math.PI * 1.1, Math.PI * 1.9];
      mobs.forEach(([mname, level, look], mi) => {
        const id = MOB_TYPES.length;
        const c = pointIn(isl, mobAngles[mi], hub ? 0.68 : 0.5);
        MOB_TYPES.push(makeMob(id, mname, level, look, si, ii, false, null, null));
        isl.mobs.push(id);
        isl.spawns.push({ type: id, x: c.x, y: c.y, count: 6 });
      });
      {
        const [bname, level, look, attacks, drop] = boss;
        const id = MOB_TYPES.length;
        const c = pointIn(isl, Math.PI * 0.5, hub ? 0.76 : 0.45);
        MOB_TYPES.push(makeMob(id, bname, level, look, si, ii, true, attacks, drop || null));
        isl.boss = id;
        isl.spawns.push({ type: id, x: c.x, y: c.y, count: 1 });
      }
      // NPCs: the hub gets the full ring of shops around its plaza; every
      // other island gets a quest giver on its northern shore.
      const kinds = hub ? HUB_NPCS.filter((k) => k !== 'awaken' || si > 0) : ['quest'];
      kinds.forEach((kind, ki) => {
        let p;
        if (hub) {
          // A staggered arc over the north of the plaza, so labels never collide.
          const a = Math.PI + 0.22 + (ki / (kinds.length - 1)) * (Math.PI - 0.44);
          p = pointIn(isl, a, ki % 2 ? 0.54 : 0.4);
        } else p = pointIn(isl, Math.PI * 1.5, 0.42);
        const npc = { id: NPCS.length, kind, name: NPC_KINDS[kind].name, sea: si, isle: ii, x: p.x, y: p.y };
        NPCS.push(npc);
        isl.npcs.push(npc.id);
      });
      sea.islands.push(isl);
    });
    {
      const [bname, level, look] = sd.beast;
      const id = MOB_TYPES.length;
      MOB_TYPES.push(makeMob(id, bname, level, look, si, -1, false, ['volley', 'nova', 'charge'], null, true));
      sea.beast = id;
    }
    SEAS.push(sea);
  });

  function makeMob(id, name, level, look, sea, isle, boss, attacks, drop, seaBeast) {
    const [form, shirt, pants, hat, hatColor, skin, size] = look;
    const sz = (size || 1) * (seaBeast ? 3.2 : 1);
    let hp = mobHp(level), dmg = mobDmg(level);
    if (boss) { hp *= 22; dmg = Math.round(dmg * 2.2); }
    if (seaBeast) { hp *= 30; dmg = Math.round(dmg * 2); }
    return {
      id, name, level, sea, isle, boss: !!boss, seaBeast: !!seaBeast,
      look: { form, shirt, pants, hat, hatColor, skin }, size: sz, r: Math.round(20 * sz),
      hp: Math.round(hp), dmg, xp: mobXp(level) * (boss ? 6 : seaBeast ? 10 : 1),
      beli: mobBeli(level) * (boss ? 15 : seaBeast ? 25 : 1),
      frags: boss ? (sea > 0 ? Math.round(40 + level / 12) : 0) : seaBeast ? Math.round(80 + level / 8) : 0,
      speed: seaBeast ? SPEED.beast : boss ? SPEED.boss : SPEED.mob,
      attacks: attacks || [], drop: drop || null,
      respawn: boss ? 150 : seaBeast ? 0 : 7,
    };
  }

  // ─── Geometry queries ─────────────────────────────────────────────────────
  // Island index under (x, y) in a sea, or -1 for open water.
  function islandAt(seaIdx, x, y) {
    const isls = SEAS[seaIdx].islands;
    for (let i = 0; i < isls.length; i++) {
      const isl = isls[i];
      const dx = x - isl.x, dy = y - isl.y;
      const d2 = dx * dx + dy * dy;
      const lim = isl.R * 1.3;
      if (d2 > lim * lim) continue;
      if (Math.sqrt(d2) < radiusAt(isl, Math.atan2(dy, dx))) return i;
    }
    return -1;
  }
  // How deep inside its island a point is: 0 at the centre, 1 on the shore.
  function landDepth(seaIdx, isle, x, y) {
    const isl = SEAS[seaIdx].islands[isle];
    const dx = x - isl.x, dy = y - isl.y;
    return Math.hypot(dx, dy) / radiusAt(isl, Math.atan2(dy, dx));
  }
  // The part of a town island where monsters will not follow anyone.
  const TOWN_FRAC = 0.58;
  function inTown(seaIdx, x, y) {
    const hub = SEAS[seaIdx].islands[0];
    return dist(x, y, hub.x, hub.y) < hub.R * TOWN_FRAC;
  }
  function isSafe(seaIdx, x, y) {
    const i = islandAt(seaIdx, x, y);
    return i >= 0 && SEAS[seaIdx].islands[i].hub;
  }

  // Decorations are cosmetic and only drawn by the client, but generated here
  // so every client sees the same palm in the same place.
  function decorFor(isl) {
    const rnd = mulberry32(hashStr(isl.name + ':decor'));
    const bio = BIOMES[isl.biome];
    const out = [];
    const want = Math.round((isl.R * isl.R) / 7000);
    const keepClear = isl.npcs.map((id) => NPCS[id]).concat(isl.spawns);
    let tries = 0;
    while (out.length < want && tries++ < want * 12) {
      const a = rnd() * TAU, f = Math.sqrt(rnd()) * 0.88;
      const p = pointIn(isl, a, f);
      if (keepClear.some((q) => dist(q.x, q.y, p.x, p.y) < 90)) continue;
      if (isl.hub && dist(p.x, p.y, isl.x, isl.y) < isl.R * 0.25) continue;
      out.push({ x: p.x, y: p.y, k: bio.decor[Math.floor(rnd() * bio.decor.length)], s: 0.8 + rnd() * 0.5, v: rnd() });
    }
    out.sort((a, b) => a.y - b.y);
    return out;
  }

  // ─── Lookups ──────────────────────────────────────────────────────────────
  const ITEMS = {};
  FRUITS.forEach((f) => (ITEMS[f.id] = Object.assign({ cat: 'fruit' }, f)));
  STYLES.forEach((s) => (ITEMS[s.id] = Object.assign({ cat: 'style' }, s)));
  SWORDS.forEach((s) => (ITEMS[s.id] = Object.assign({ cat: 'sword' }, s)));
  GUNS.forEach((g) => (ITEMS[g.id] = Object.assign({ cat: 'gun' }, g)));
  const FRUIT_IDX = {};
  FRUITS.forEach((f, i) => (FRUIT_IDX[f.id] = i));

  function rollFruit(rnd) {
    const r = rnd || Math.random;
    let total = 0;
    for (const f of FRUITS) total += RARITY[f.rarity].w / countRarity(f.rarity);
    let x = r() * total;
    for (const f of FRUITS) { x -= RARITY[f.rarity].w / countRarity(f.rarity); if (x <= 0) return f; }
    return FRUITS[0];
  }
  const _rc = {};
  function countRarity(r) { return _rc[r] || (_rc[r] = FRUITS.filter((f) => f.rarity === r).length); }

  function skillDesc(s) {
    const bits = [];
    const kind = { proj: 'Projectile', nova: 'Burst around you', blast: 'Strike at cursor', beam: 'Beam', dash: 'Dash',
      zone: 'Lingering field', rain: 'Barrage at cursor', pull: 'Pulls enemies in', tele: 'Teleport to cursor',
      chain: 'Chain lightning', buff: 'Self buff', trans: 'Transformation' }[s.t];
    bits.push(kind);
    if (s.m) bits.push('×' + s.m + ' dmg');
    if (s.cnt > 1) bits.push(s.cnt + ' shots');
    if (s.st) {
      if (s.st.burn) bits.push('burns');
      if (s.st.slow) bits.push('slows');
      if (s.st.stun) bits.push('stuns');
      if (s.st.knock) bits.push('knockback');
    }
    if (s.heal) bits.push('heals ' + Math.round(s.heal * 100) + '%');
    if (s.shield) bits.push('shield ' + Math.round(s.shield * 100) + '% HP');
    if (s.dr) bits.push(Math.round(s.dr * 100) + '% less damage');
    if (s.spd) bits.push('+' + Math.round((s.spd - 1) * 100) + '% speed');
    if (s.t === 'trans') bits.push('+30% dmg, +20% speed, tougher');
    bits.push((s.cd || 5) + 's');
    return bits.join(' · ');
  }

  return {
    MAX_LEVEL, STAT_CAP, POINTS_PER_LEVEL, TAU, SKILL_KEYS, SKILL_UNLOCK, SKILL_ENERGY, MASTERY_CAP,
    M1, SPEED, PLAYER_R, DASH, TRANSFORM, PVP_SCALE, PVP_MIN_LEVEL, FRUIT_INV_CAP,
    RARITY, FRUITS, STYLES, SWORDS, GUNS, ABILITIES, ITEMS, FRUIT_IDX, SEAS, MOB_TYPES, NPCS, NPC_KINDS, BIOMES,
    mulberry32, hashStr, clamp, dist, angDiff,
    xpNext, mobHp, mobDmg, mobXp, mobBeli, questXp, questBeli, questCount, maxHp, maxEn, statMul, pointsTotal,
    gachaCost, resetCost, fruitBase,
    radiusAt, pointIn, islandAt, landDepth, isSafe, inTown, TOWN_FRAC, decorFor, rollFruit, skillDesc,
  };
});
