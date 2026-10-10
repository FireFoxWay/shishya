#!/usr/bin/env node
'use strict';
/*
 * End-to-end smoke test: boots the real server on a spare port with a
 * throwaway save file, then drives it with WebSocket bots the way a browser
 * would. Exits non-zero on the first broken expectation.
 *
 *   node test/smoke.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const TF = require('../shared/tf.js');

const PORT = 39000 + Math.floor(Math.random() * 1000);
const SAVE = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'tidefruit-')), 'saves.json');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
function check(cond, msg) {
  console.log(`${cond ? '  ok ' : 'FAIL '} ${msg}`);
  if (!cond) failures++;
}

class Bot {
  constructor(name, team, token) {
    this.name = name;
    this.team = team;
    this.token = token || 'tok-' + name + '-0123456789abcdef';
    this.msgs = [];
    this.notes = [];
    this.events = [];
    this.snap = null;
    this.me = null;
    this.pc = 0;
  }
  connect() {
    return new Promise((resolve, reject) => {
      const ws = (this.ws = new WebSocket(`ws://127.0.0.1:${PORT}/ws`));
      ws.onopen = () => ws.send(JSON.stringify({ t: 'hello', name: this.name, token: this.token, team: this.team }));
      ws.onerror = (e) => reject(e);
      ws.onmessage = (ev) => {
        const m = JSON.parse(ev.data);
        this.msgs.push(m);
        if (m.t === 'welcome') { this.id = m.id; this.x = m.x; this.y = m.y; this.pc = m.pc; this.me = m.me; resolve(m); }
        if (m.t === 'error') resolve(m);
        if (m.t === 'me') this.me = m;
        if (m.t === 's') this.snap = m;
        if (m.t === 'note') this.notes.push(m.m);
        if (m.t === 'e') this.events.push(...m.e);
        if (m.t === 'pos' || m.t === 'sea') { this.x = m.x; this.y = m.y; this.pc = m.pc; }
      };
    });
  }
  send(o) { this.ws.send(JSON.stringify(o)); }
  input(m1, aim) { this.send({ t: 'in', x: this.x, y: this.y, a: aim || 0, m1: !!m1, pc: this.pc }); }
  // Walk at an honest pace toward (tx, ty), stopping `stop` short of it.
  async walkTo(tx, ty, stop = 0, m1 = false) {
    for (let i = 0; i < 400; i++) {
      const d = Math.hypot(tx - this.x, ty - this.y);
      if (d <= stop + 2) break;
      const step = Math.min(d - stop, 230 * 0.05);
      this.x += ((tx - this.x) / d) * step;
      this.y += ((ty - this.y) / d) * step;
      this.input(m1, Math.atan2(ty - this.y, tx - this.x));
      await sleep(50);
    }
  }
  close() { this.ws.close(); }
}

async function main() {
  const srv = spawn(process.execPath, [path.join(__dirname, '..', 'server.js')], {
    env: Object.assign({}, process.env, { PORT: String(PORT), SAVE_FILE: SAVE, HOST: '127.0.0.1' }),
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let srvErr = '';
  srv.stderr.on('data', (d) => { srvErr += d; process.stderr.write(d); });
  for (let i = 0; i < 50; i++) {
    try { const r = await fetch(`http://127.0.0.1:${PORT}/status`); if (r.ok) break; } catch (_) { /* booting */ }
    await sleep(100);
  }
  try {
    // ─ static files
    const idx = await fetch(`http://127.0.0.1:${PORT}/`);
    check(idx.status === 200, 'serves the client page');
    const shared = await fetch(`http://127.0.0.1:${PORT}/shared/tf.js`);
    check(shared.status === 200, 'serves the shared rules');
    const leak = await fetch(`http://127.0.0.1:${PORT}/shared/../server.js`);
    check(leak.status === 404, 'does not serve files outside public/ and shared/');
    const leak2 = await fetch(`http://127.0.0.1:${PORT}/%2e%2e/data/saves.json`);
    check(leak2.status === 404, 'does not serve encoded traversal');

    // ─ join
    const a = new Bot('SmokeA', 'pirate');
    const w = await a.connect();
    check(w.t === 'welcome' && w.me.lv === 1 && w.sea === 0, 'new player joins at level 1 in the first sea');
    check(TF.islandAt(0, a.x, a.y) === 0, 'spawns on the starter island');

    // ─ name ownership
    const imposter = new Bot('SmokeA', 'marine', 'a-different-token-123456');
    const r = await imposter.connect();
    check(r.t === 'error', 'a name cannot be taken with a different token');

    // ─ teleport protection
    const before = { x: a.x, y: a.y };
    a.send({ t: 'in', x: a.x + 2000, y: a.y, a: 0, m1: false, pc: a.pc });
    await sleep(300);
    check(a.msgs.some((m) => m.t === 'pos') && Math.abs(a.x - before.x) < 400, 'a teleport hack is pulled back');

    // ─ quest
    const hub = TF.SEAS[0].islands[0];
    const qnpc = TF.NPCS.find((n) => n.sea === 0 && n.isle === 0 && n.kind === 'quest');
    await a.walkTo(qnpc.x, qnpc.y, 60);
    a.send({ t: 'npc', n: qnpc.id, a: 'accept', i: 0 });
    await sleep(300);
    check(a.me.q && a.me.q.mob === hub.mobs[0], 'accepts the Beach Thug quest');
    a.send({ t: 'npc', n: qnpc.id, a: 'accept', i: 2 });
    await sleep(250);
    check(a.me.q.mob === hub.mobs[0], 'cannot take the boss quest under its level');

    // ─ fight
    const spawnPt = hub.spawns[0];
    await a.walkTo(spawnPt.x, spawnPt.y, 120);
    const xp0 = a.me.xp, lv0 = a.me.lv;
    let kills = 0;
    const deadline = Date.now() + 25000;
    while (Date.now() < deadline && a.me.lv < 3) {
      const mobs = (a.snap && a.snap.m || []).filter((m) => m[1] === hub.mobs[0]);
      if (!mobs.length) { await sleep(100); continue; }
      mobs.sort((p, q) => Math.hypot(p[2] - a.x, p[3] - a.y) - Math.hypot(q[2] - a.x, q[3] - a.y));
      const t = mobs[0];
      const d = Math.hypot(t[2] - a.x, t[3] - a.y);
      const aim = Math.atan2(t[3] - a.y, t[2] - a.x);
      if (d > 70) await a.walkTo(t[2], t[3], 60, true);
      else { a.input(true, aim); await sleep(50); }
      // Use Z whenever the sword's first skill is unlocked.
      if ((a.me.mastery.sw_drift || 0) >= 1 && !(a.me.cds['sw_drift:z'] > 0)) a.send({ t: 'sk', k: 'z', ax: t[2], ay: t[3] });
      kills = a.events.filter((e) => e.k === 'die').length;
    }
    a.input(false);
    check(kills > 0, `kills mobs (${kills} deaths seen)`);
    check(a.me.lv > lv0 || a.me.xp > xp0, `earns XP (level ${a.me.lv}, xp ${a.me.xp})`);
    check(a.me.beli > 0, `earns Beli ($${a.me.beli})`);
    check((a.me.mastery.sw_drift || 0) > 0, `gains sword mastery (${a.me.mastery.sw_drift})`);
    check(a.notes.some((n) => n.startsWith('Quest complete')), 'completes the quest and it renews');
    check(a.events.some((e) => e.k === 'dash' && e.o === a.id), 'casts a sword skill');

    // ─ stats
    const pts = a.me.pts;
    a.send({ t: 'stat', k: 'sword', n: 1 });
    a.send({ t: 'stat', k: 'defense', n: 999 });
    await sleep(250);
    check(a.me.st.sword === 1 && a.me.pts === 0 && a.me.st.defense === pts - 1, 'spends stat points and no more than it has');

    // ─ codes and fruit
    a.send({ t: 'code', c: 'firstsail' });
    await sleep(250);
    check(a.me.fruits.length === 1, 'FIRSTSAIL grants a fruit');
    a.send({ t: 'code', c: 'FIRSTSAIL' });
    await sleep(250);
    check(a.me.fruits.length === 1 && a.notes.some((n) => n.includes('already used')), 'a code works only once');
    const fid = a.me.fruits[0];
    a.send({ t: 'eat', i: 0 });
    await sleep(250);
    check(a.me.fruit === fid && a.me.slot === 3 && a.me.fruits.length === 0, `eats the ${TF.ITEMS[fid].name}`);
    a.input(true, 0);
    await sleep(600);
    a.input(false, 0);
    await sleep(100);
    check(a.events.some((e) => (e.k === 'proj' || e.k === 'm1')), 'fruit basic attack fires');

    // ─ gates
    a.send({ t: 'pvp', on: true });
    await sleep(200);
    check(a.notes.some((n) => n.includes('PvP opens')), 'PvP is closed under level 20');
    const ferry = TF.NPCS.find((n) => n.sea === 0 && n.kind === 'ferry');
    await a.walkTo(ferry.x, ferry.y, 60);
    a.send({ t: 'npc', n: ferry.id, a: 'travel', sea: 1 });
    await sleep(250);
    check(a.me.sea === 0 && a.notes.some((n) => n.includes('needs level 700')), 'the second sea is locked under 700');

    // ─ a second player sees the first
    const b = new Bot('SmokeB', 'marine');
    await b.connect();
    await sleep(400);
    check(b.snap && b.snap.p.some((row) => row[9] === 'SmokeA'), 'players see each other');
    a.send({ t: 'chat', m: 'ahoy' });
    await sleep(250);
    check(b.msgs.some((m) => m.t === 'chat' && m.m === 'ahoy' && m.n === 'SmokeA'), 'chat reaches other players');

    // ─ persistence
    const lvBefore = a.me.lv;
    a.close();
    b.close();
    await sleep(300);
    srv.kill('SIGTERM');
    await new Promise((r) => srv.on('exit', r));
    const saved = JSON.parse(fs.readFileSync(SAVE, 'utf8'));
    check(saved.players.smokea && saved.players.smokea.level === lvBefore && saved.players.smokea.fruit === fid, 'saves progress on shutdown');
    check(!JSON.stringify(saved).includes('tok-SmokeA'), 'stores only a hash of the session token');
  } catch (e) {
    console.error(e);
    failures++;
  } finally {
    srv.kill('SIGKILL');
  }
  if (srvErr.includes('[tick]') || srvErr.includes('handler')) { console.log('FAIL  server logged errors'); failures++; }
  console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed');
  process.exit(failures ? 1 : 0);
}

main();
