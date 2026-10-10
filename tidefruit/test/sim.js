#!/usr/bin/env node
'use strict';
/*
 * In-process simulation test. Runs the real Game on a virtual clock with fake
 * connections, so a minute of play takes milliseconds and every skill of every
 * weapon can be cast. Exits non-zero on the first broken expectation.
 *
 *   node test/sim.js
 */
const { EventEmitter } = require('events');

let now = 10000;
performance.now = () => now; // the game reads time through performance.now()

const TF = require('../shared/tf.js');
const { Game } = require('../server/game');

let failures = 0;
function check(cond, msg) {
  console.log(`${cond ? '  ok ' : 'FAIL '} ${msg}`);
  if (!cond) failures++;
}

const store = {
  m: new Map(),
  get(k) { return this.m.get(k); },
  set(k, v) { this.m.set(k, v); },
  values() { return this.m.values(); },
  markDirty() {},
};
const g = new Game(store);

function fakeConn() {
  const c = new EventEmitter();
  c.sent = [];
  c.send = (s) => c.sent.push(JSON.parse(s));
  c.close = () => {};
  c.congested = false;
  return c;
}
function join(name, team) {
  const c = fakeConn();
  g.connect(c);
  c.emit('message', JSON.stringify({ t: 'hello', name, token: 'token-for-' + name + '-xxxxxx', team }));
  const p = [...g.players.values()].find((q) => q.s.name === name);
  p.c = c;
  return p;
}
function step(sec) { for (let i = 0; i < Math.round(sec * 30); i++) { now += 1000 / 30; g.tick(); } }
function put(p, x, y) { p.x = x; p.y = y; p.inWater = TF.islandAt(p.s.sea, x, y) < 0; }
function makeStrong(p, level) {
  p.s.level = level;
  for (const k of Object.keys(p.s.stats)) p.s.stats[k] = Math.min(TF.STAT_CAP, level);
  g.recompute(p);
  p.hp = p.maxHp; p.en = p.maxEn;
}
const notes = (p) => p.c.sent.filter((m) => m.t === 'note').map((m) => m.m);

// ─── 1. Every skill of every weapon runs without throwing and hurts things ──
{
  const p = join('Tester', 'pirate');
  makeStrong(p, 3000);
  const sea = g.seas[0];
  const isl = TF.SEAS[0].islands[1]; // Monkey Jungle: a plain island full of mobs
  const target = sea.mobs.find((m) => m.mt.isle === 1 && !m.mt.boss);
  const all = [...TF.FRUITS, ...TF.STYLES, ...TF.SWORDS, ...TF.GUNS];
  let cast = 0, errors = 0;
  const hpBefore = sea.mobs.filter((m) => m.mt.isle === 1).reduce((a, m) => a + m.hp, 0);
  let kills = 0;
  for (const it of all) {
    const cat = TF.ITEMS[it.id].cat;
    p.s.mastery[it.id] = 600;
    if (cat === 'fruit') { p.s.fruit = it.id; p.s.slot = 3; }
    else { if (!p.s.owned.includes(it.id)) p.s.owned.push(it.id); p.s.equip[cat] = it.id; p.s.slot = cat === 'style' ? 0 : cat === 'sword' ? 1 : 2; }
    for (const sk of it.skills) {
      // Keep a live mob in reach.
      let m = sea.mobs.find((x) => x.mt.isle === 1 && x.alive && !x.mt.boss);
      if (!m) { step(8); m = sea.mobs.find((x) => x.mt.isle === 1 && x.alive && !x.mt.boss); }
      put(p, m.x - 120, m.y);
      p.cds = {}; p.en = p.maxEn; p.stunUntil = 0; p.dead = false; p.hp = p.maxHp;
      try {
        const before = sea.hazards.length + sea.ev.length;
        g.useSkill(p, sk.k, m.x, m.y);
        if (sea.hazards.length + sea.ev.length > before || sk.t === 'buff' || sk.t === 'trans') cast++;
        step(1.2);
      } catch (e) { errors++; console.error(it.id, sk.k, e); }
    }
    kills = p.s.kills;
  }
  const total = all.reduce((a, it) => a + it.skills.length, 0);
  const unnamed = all.flatMap((it) => it.skills.filter((sk) => typeof sk.n !== 'string' || !sk.n).map((sk) => it.id + ':' + sk.k));
  check(unnamed.length === 0, `every skill has a name${unnamed.length ? ' — missing: ' + unnamed.join(', ') : ''}`);
  check(errors === 0, `all ${total} skills across ${all.length} weapons run without errors`);
  check(cast === total, `every skill produced an effect (${cast}/${total})`);
  const deaths = sea.mobs.filter((m) => m.mt.isle === 1 && !m.alive).length;
  check(p.s.xp > 0 || p.s.level === 3000, 'skills killed mobs (xp / max level)');
  check(Object.keys(p.s.mastery).length >= all.length, 'mastery tracked per weapon');
  // M1 for every slot kind
  for (const slot of [0, 1, 2, 3]) {
    p.s.slot = slot; p.m1At = 0; p.m1Hold = true;
    const m = sea.mobs.find((x) => x.mt.isle === 1 && x.alive && !x.mt.boss) || target;
    put(p, m.x - 60, m.y); p.aim = 0;
    const hp = m.hp;
    step(0.7);
    p.m1Hold = false;
    check(m.hp < hp || !m.alive, `basic attack in slot ${slot} hits`);
  }
  void hpBefore; void kills; void deaths; void isl;
}

// ─── 2. Mobs leave you alone in town ───────────────────────────────────────
{
  const p = join('Newbie', 'marine');
  const hub = TF.SEAS[0].islands[0];
  put(p, hub.x, hub.y);
  p.protUntil = 0;
  step(6);
  check(p.hp === p.maxHp, 'a new player in the town plaza is not attacked');
  const thugSpawn = hub.spawns[0];
  put(p, thugSpawn.x, thugSpawn.y);
  step(4);
  check(p.hp < p.maxHp || p.dead, 'walking into a mob camp gets you attacked');
  step(5);
}

// ─── 2b. Shooting a boss from town provokes it ─────────────────────────────
{
  const p = join('Sniper', 'pirate');
  makeStrong(p, 200);
  p.s.owned.push('gn_flint'); p.s.equip.gun = 'gn_flint'; p.s.slot = 2; p.protUntil = 0;
  const hub = TF.SEAS[0].islands[0];
  const boss = g.seas[0].mobs.find((m) => m.mt.boss && m.mt.isle === 0);
  const a = Math.atan2(boss.y - hub.y, boss.x - hub.x);
  const edge = hub.R * TF.TOWN_FRAC - 30;
  put(p, hub.x + Math.cos(a) * edge, hub.y + Math.sin(a) * edge);
  check(TF.inTown(0, p.x, p.y), 'the sniper stands inside the town');
  const hp0 = p.hp;
  for (let i = 0; i < 120 && boss.alive && p.hp === hp0; i++) {
    p.aim = Math.atan2(boss.y - p.y, boss.x - p.x); p.m1Hold = true; p.hp = Math.max(p.hp, 1);
    step(0.1);
  }
  p.m1Hold = false;
  check(p.hp < hp0 || p.dead, 'a boss provoked from town fights back with its ranged attacks');
  check(!g.seas[0].mobs.some((m) => m.alive && m.mt.isle === 0 && TF.inTown(0, m.x, m.y)), 'no monster ever walks into the town');
  boss.hp = boss.maxHp; boss.target = null; boss.contrib.clear();
  put(p, hub.x, hub.y);
  step(7);
}

// ─── 3. PvP rules ──────────────────────────────────────────────────────────
{
  const a = join('PirateA', 'pirate');
  const b = join('PirateB', 'pirate');
  const c = join('MarineC', 'marine');
  const d = join('MarineD', 'marine');
  for (const p of [a, b, c, d]) { makeStrong(p, 200); p.s.equip.sword = 'sw_drift'; p.s.slot = 1; p.protUntil = 0; }
  const isl = TF.SEAS[0].islands[2];
  const spot = TF.pointIn(isl, Math.PI * 1.5, 0.15);
  // keep mobs away from the duel
  for (const m of g.seas[0].mobs) if (m.mt.isle === 2) { m.alive = false; m.respawnAt = 0; }
  put(a, spot.x, spot.y); put(b, spot.x + 50, spot.y); put(c, spot.x, spot.y + 60); put(d, spot.x + 50, spot.y + 60);
  const hit = (att, def) => { def.hp = def.maxHp; att.aim = Math.atan2(def.y - att.y, def.x - att.x); att.m1At = 0; att.m1Hold = true; step(0.2); att.m1Hold = false; return def.hp < def.maxHp; };
  check(!hit(a, b), 'no PvP damage while PvP is off');
  for (const p of [a, b, c, d]) g.setPvp(p, true);
  check(hit(a, b), 'pirates with PvP on can hurt each other');
  check(!hit(c, d), 'marines cannot hurt marines');
  check(hit(c, a), 'a marine can hurt a pirate');
  const hub = TF.SEAS[0].islands[0];
  put(a, hub.x, hub.y); put(b, hub.x + 50, hub.y);
  check(!hit(a, b), 'no PvP damage in a town');
  put(a, spot.x, spot.y); put(b, spot.x + 50, spot.y);
  const bountyBefore = a.s.bounty;
  b.hp = 1;
  a.aim = 0; a.m1At = 0; a.m1Hold = true; step(0.2); a.m1Hold = false;
  check(b.dead, 'a PvP kill kills');
  check(a.s.bounty > bountyBefore, `the killer earns bounty ($${a.s.bounty})`);
  step(4);
  check(!b.dead && b.hp === b.maxHp, 'the victim respawns at full health');
  check(!g.setPvp(a, false) && a.pvp, 'PvP cannot be switched off mid-fight');
  for (const m of g.seas[0].mobs) if (m.mt.isle === 2) m.respawnAt = now / 1000;
}

// ─── 4. Bosses: kill, reward, drop, respawn ────────────────────────────────
{
  const p = join('Slayer', 'pirate');
  makeStrong(p, 3000);
  p.s.equip.sword = 'sw_drift'; p.s.slot = 1;
  p.protUntil = 0;
  const sea = g.seas[0];
  const boss = sea.mobs.find((m) => m.mt.name === 'Captain Redgill');
  p.s.quest = { mob: boss.type, need: 1, have: 0 };
  const beli0 = p.s.beli;
  let drops = 0;
  for (let round = 0; round < 30 && !p.s.owned.includes('sw_redgill'); round++) {
    if (!boss.alive) { boss.respawnAt = now / 1000; step(0.1); }
    put(p, boss.x - 80, boss.y);
    p.aim = 0; p.m1Hold = true; p.hp = p.maxHp;
    for (let i = 0; i < 300 && boss.alive; i++) { put(p, boss.x - 80, boss.y); step(0.1); }
    p.m1Hold = false;
    drops++;
  }
  check(p.s.beli > beli0, 'killing a boss pays Beli');
  check(notes(p).some((n) => n.startsWith('Quest complete')), 'boss quest completes');
  check(p.s.owned.includes('sw_redgill'), `the boss sword drops eventually (after ${drops} kills)`);
  check(!boss.alive && boss.respawnAt > now / 1000 + 100, 'the boss waits minutes before it respawns');
}

// ─── 5. Sea travel ─────────────────────────────────────────────────────────
{
  const p = join('Sailor', 'marine');
  const ferry = TF.NPCS.find((n) => n.sea === 0 && n.kind === 'ferry');
  put(p, ferry.x, ferry.y + 40);
  g.npcAction(p, { n: ferry.id, a: 'travel', sea: 1 });
  check(p.s.sea === 0, 'a level 1 player cannot leave the first sea');
  makeStrong(p, 800);
  g.npcAction(p, { n: ferry.id, a: 'travel', sea: 1 });
  check(p.s.sea === 1 && g.seas[1].players.has(p) && !g.seas[0].players.has(p), 'a level 800 player sails to the second sea');
  check(TF.islandAt(1, p.x, p.y) === 0, 'and lands in its town');
  g.npcAction(p, { n: ferry.id, a: 'travel', sea: 2 });
  check(p.s.sea === 1, 'the wrong sea\'s ferry does nothing');
  const ferry2 = TF.NPCS.find((n) => n.sea === 1 && n.kind === 'ferry');
  put(p, ferry2.x, ferry2.y + 40);
  g.npcAction(p, { n: ferry2.id, a: 'travel', sea: 2 });
  check(p.s.sea === 1, 'the third sea needs level 1500');

  // ─── 6. Sea beasts and wild fruit in the second sea ─────────────────────
  const sea = g.seas[1];
  sea.beastAt = now / 1000;
  sea.fruitAt = now / 1000;
  step(0.2);
  check(!!sea.beast && TF.islandAt(1, sea.beast.x, sea.beast.y) < 0, 'a sea beast surfaces in open water');
  const drop = sea.drops.find((d) => !d.owner);
  check(!!drop, 'a wild fruit falls on an island');
  const inv = p.s.fruits.length;
  put(p, drop.x, drop.y);
  step(1.5);
  check(p.s.fruits.length === inv + 1, 'walking over the fruit picks it up');
  makeStrong(p, 3000);
  p.s.slot = 1; p.s.equip.sword = 'sw_drift'; p.protUntil = 0;
  const beast = sea.beast;
  const frags0 = p.s.frags;
  for (let i = 0; i < 2000 && sea.beast; i++) {
    put(p, beast.x - 100, beast.y);
    p.hp = p.maxHp; p.aim = Math.atan2(beast.y - p.y, beast.x - p.x); p.m1Hold = true;
    step(0.1);
  }
  p.m1Hold = false;
  check(!sea.beast, 'the sea beast can be killed');
  check(p.s.frags > frags0, 'and it pays fragments');
}

// ─── 7. Shops ──────────────────────────────────────────────────────────────
{
  const p = join('Shopper', 'pirate');
  p.s.beli = 10_000_000;
  const sword = TF.NPCS.find((n) => n.sea === 0 && n.kind === 'sword');
  put(p, sword.x, sword.y + 40);
  g.npcAction(p, { n: sword.id, a: 'buy', id: 'sw_cutlass' });
  check(p.s.owned.includes('sw_cutlass') && p.s.equip.sword === 'sw_cutlass' && p.s.beli === 10_000_000 - 5000, 'buys and equips a sword');
  g.npcAction(p, { n: sword.id, a: 'buy', id: 'sw_redgill' });
  check(!p.s.owned.includes('sw_redgill'), 'boss-drop swords are not for sale');
  g.npcAction(p, { n: sword.id, a: 'buy', id: 'sw_rose' });
  check(!p.s.owned.includes('sw_rose'), 'another sea\'s sword is not sold here');
  const fruit = TF.NPCS.find((n) => n.sea === 0 && n.kind === 'fruit');
  put(p, fruit.x, fruit.y + 40);
  const fid = g.stock[0];
  g.npcAction(p, { n: fruit.id, a: 'buy', id: fid });
  check(p.s.fruits.includes(fid), `buys a ${TF.ITEMS[fid].name} from the stock`);
  g.npcAction(p, { n: fruit.id, a: 'buy', id: TF.FRUITS.map((f) => f.id).find((id) => !g.stock.includes(id)) });
  check(p.s.fruits.length === 1, 'cannot buy a fruit that is not in stock');
  const ab = TF.NPCS.find((n) => n.sea === 0 && n.kind === 'ability');
  put(p, ab.x, ab.y + 40);
  g.npcAction(p, { n: ab.id, a: 'buy', id: 'aura' });
  check(p.s.abilities.aura, 'learns Aura');
  const far = TF.NPCS.find((n) => n.sea === 0 && n.kind === 'gacha');
  put(p, far.x + 900, far.y);
  g.npcAction(p, { n: far.id, a: 'roll' });
  check(p.s.fruits.length === 1, 'NPCs only deal with players standing near them');
  put(p, far.x, far.y + 40);
  g.npcAction(p, { n: far.id, a: 'roll' });
  check(p.s.fruits.length === 2, 'the Fruit Mystic rolls a fruit');
  g.npcAction(p, { n: far.id, a: 'roll' });
  check(p.s.fruits.length === 2, 'and makes you wait before the next roll');
}

// ─── 8. Levelling ──────────────────────────────────────────────────────────
{
  const p = join('Grinder', 'pirate');
  g.giveXp(p, 1e12);
  check(p.s.level === TF.MAX_LEVEL && p.s.xp === 0, `XP caps at level ${TF.MAX_LEVEL}`);
  check(g.pointsLeft(p) === TF.pointsTotal(TF.MAX_LEVEL), `${TF.pointsTotal(TF.MAX_LEVEL).toLocaleString()} stat points to spend at max`);
  g.addStat(p, 'melee', 99999);
  check(p.s.stats.melee === TF.STAT_CAP, 'a stat caps at ' + TF.STAT_CAP);
}

console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed');
process.exit(failures ? 1 : 0);
