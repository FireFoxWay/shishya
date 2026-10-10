/*
 * Tidefruit HUD and menus. All DOM work lives here; the canvas never knows a
 * panel is open. Panels re-render only when the data they show has changed,
 * so a button does not vanish from under a click.
 */
(function () {
  'use strict';
  const UI = (window.UI = {});
  let S;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const money = (n) => '$' + Math.floor(n).toLocaleString();
  const num = (n) => Math.floor(n).toLocaleString();
  const STAT_INFO = {
    melee: ['Melee', 'Fighting style damage'],
    defense: ['Defense', '+28 HP and +8 energy per point'],
    sword: ['Sword', 'Sword damage'],
    gun: ['Gun', 'Gun damage'],
    fruit: ['Fruit', 'Fruit power damage'],
  };
  const SLOT_NAMES = ['Style', 'Sword', 'Gun', 'Fruit'];
  const SEA_ICONS = ['🌅', '🌹', '⛈', '🌌'];

  let panel = null, panelArg = null, panelSig = '';
  let hudAt = 0, mapAt = 0;
  let skillSig = '', hotSig = '';
  let confirmEat = -1;

  // ─── Setup ────────────────────────────────────────────────────────────────
  UI.init = function (state) {
    S = state;
    let team = 'pirate';
    try {
      $('nameInput').value = localStorage.getItem('tf_name') || '';
      team = localStorage.getItem('tf_team') || 'pirate';
    } catch (_) { /* private mode */ }
    const pickTeam = (tm) => {
      team = tm;
      document.querySelectorAll('.team').forEach((b) => b.classList.toggle('sel', b.dataset.team === tm));
    };
    pickTeam(team);
    document.querySelectorAll('.team').forEach((b) => b.addEventListener('click', () => pickTeam(b.dataset.team)));
    const play = () => {
      const name = $('nameInput').value.trim();
      if (!/^[A-Za-z0-9_]{3,16}$/.test(name)) return UI.loginError('Pick a name of 3–16 letters, digits or _.');
      $('loginErr').textContent = '';
      $('playBtn').disabled = true;
      $('playBtn').textContent = 'Setting sail…';
      Game.play(name, team);
    };
    $('playBtn').addEventListener('click', play);
    $('nameInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') play(); });
    fetch('status').then((r) => r.json()).then((s) => { $('onlineCount').textContent = s.online; }).catch(() => { $('onlineCount').textContent = '?'; });

    document.querySelectorAll('[data-open]').forEach((b) => b.addEventListener('click', () => UI.toggle(b.dataset.open)));
    $('pvpBtn').addEventListener('click', () => Game.send({ t: 'pvp', on: !(S.me && S.me.pvp) }));
    $('panelClose').addEventListener('click', () => UI.close());
    $('panelBody').addEventListener('click', onPanelClick);
    $('hotbar').addEventListener('click', (e) => { const b = e.target.closest('[data-slot]'); if (b) Game.setSlot(+b.dataset.slot); });
    $('skills').addEventListener('click', (e) => { const b = e.target.closest('[data-key]'); if (b) Game.trySkill(b.dataset.key); });
    $('prompt').addEventListener('click', () => Game.interact());
    const ci = $('chatInput');
    ci.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const m = ci.value.trim();
        if (m) Game.send({ t: 'chat', m });
        ci.value = '';
        ci.blur();
        e.preventDefault();
      } else if (e.key === 'Escape') ci.blur();
      e.stopPropagation();
    });
    bindTouch();
  };

  UI.loginError = function (msg) {
    $('loginErr').textContent = msg;
    $('playBtn').disabled = false;
    $('playBtn').textContent = 'Set sail';
  };

  UI.onJoin = function (first) {
    $('login').classList.add('hidden');
    $('hud').classList.remove('hidden');
    if (first && S.me && S.me.lv === 1 && S.me.xp === 0) {
      UI.toast('Welcome aboard! Walk to the Quest Giver (!) and press E to take your first quest.', 'good');
      setTimeout(() => UI.toast('Starter codes: FIRSTSAIL, SEAFRUIT, TIDES2X — redeem them under Codes.', 'good'), 2500);
    } else if (first) UI.toast(`Welcome back, ${S.me.name}.`, 'good');
    if (S.touch) UI.enableTouch();
  };

  UI.typing = () => document.activeElement && (document.activeElement.id === 'chatInput' || document.activeElement.tagName === 'INPUT');
  UI.focusChat = () => $('chatInput').focus();
  UI.blurChat = () => { if (document.activeElement && document.activeElement.tagName === 'INPUT') document.activeElement.blur(); };

  // ─── Toasts, chat, banners ───────────────────────────────────────────────
  UI.toast = function (msg, cls) {
    const box = $('toasts');
    const d = document.createElement('div');
    d.className = 'toast ' + (cls || '');
    d.textContent = msg;
    box.appendChild(d);
    while (box.children.length > 4) box.firstChild.remove();
    setTimeout(() => d.classList.add('out'), 3800);
    setTimeout(() => d.remove(), 4400);
  };

  UI.chat = function (m) {
    const log = $('chatLog');
    const d = document.createElement('div');
    d.className = 'line' + (m.sys ? ' sys' : '');
    if (m.sys) d.textContent = m.m;
    else {
      const who = document.createElement('b');
      who.className = m.team === 'marine' ? 'marine' : 'pirate';
      who.textContent = `[${m.lv}] ${m.n}: `;
      d.appendChild(who);
      d.appendChild(document.createTextNode(m.m));
    }
    log.appendChild(d);
    while (log.children.length > 60) log.firstChild.remove();
    log.scrollTop = log.scrollHeight;
  };

  UI.levelUp = function (lv) {
    const d = $('lvlup');
    d.innerHTML = `<small>LEVEL UP</small>${num(lv)}`;
    d.classList.remove('hidden', 'show');
    void d.offsetWidth;
    d.classList.add('show');
    clearTimeout(UI._lvT);
    UI._lvT = setTimeout(() => d.classList.add('hidden'), 1800);
  };

  UI.seaBanner = function (name) {
    const d = $('banner');
    d.textContent = `~ ${name} ~`;
    d.classList.remove('hidden', 'show');
    void d.offsetWidth;
    d.classList.add('show');
    setTimeout(() => d.classList.add('hidden'), 3200);
  };

  // ─── HUD ──────────────────────────────────────────────────────────────────
  UI.frame = function (S_, dt) {
    const me = S.me;
    if (!me) return;
    const t = S.time;
    $('hpFill').style.width = (100 * Math.max(0, me.hp) / me.mhp).toFixed(1) + '%';
    $('enFill').style.width = (100 * Math.max(0, me.en) / me.men).toFixed(1) + '%';
    $('xpFill').style.width = me.lv >= TF.MAX_LEVEL ? '100%' : (100 * me.xp / me.xn).toFixed(2) + '%';
    updateSkillCooldowns(t);
    if (t - hudAt > 0.1) { hudAt = t; slowHud(); }
    if (t - mapAt > 0.15) { mapAt = t; R.drawMap($('minimap'), S, false); if (panel === 'map') R.drawMap($('bigmap'), S, true); }
  };

  function slowHud() {
    const me = S.me;
    const t = S.time;
    $('hpText').textContent = `${num(Math.max(0, me.hp))} / ${num(me.mhp)}`;
    $('enText').textContent = `${num(Math.max(0, me.en))} / ${num(me.men)}`;
    $('xpText').textContent = me.lv >= TF.MAX_LEVEL ? `Level ${me.lv} · MAX` : `Level ${num(me.lv)} · ${num(me.xp)} / ${num(me.xn)} XP (${(100 * me.xp / me.xn).toFixed(1)}%)`;
    $('beli').textContent = num(me.beli);
    $('frags').textContent = num(me.frags);
    $('bountyLabel').textContent = me.team === 'marine' ? 'Honor' : 'Bounty';
    $('bounty').textContent = num(me.bounty);
    $('lvl').textContent = num(me.lv);
    $('pname').textContent = me.name;
    $('pname').className = me.team;
    const sea = TF.SEAS[S.sea];
    const isle = TF.islandAt(S.sea, S.self.x, S.self.y);
    $('locSea').textContent = `${SEA_ICONS[S.sea]} ${sea.name}`;
    $('locIsle').textContent = isle >= 0 ? sea.islands[isle].name : 'Open Sea';
    $('safeTag').classList.toggle('hidden', !(isle >= 0 && sea.islands[isle].hub));
    $('pvpBtn').textContent = me.pvp ? 'PvP: ON' : 'PvP: Off';
    $('pvpBtn').classList.toggle('on', !!me.pvp);
    $('ptsBadge').textContent = me.pts > 0 ? me.pts : '';
    $('ptsBadge').classList.toggle('hidden', !(me.pts > 0));
    // Buffs
    const buffs = [];
    if (me.x2 > 0) buffs.push(`<span class="buff x2">2× XP ${fmtTime(me.x2)}</span>`);
    if (S.transUntil > t) buffs.push(`<span class="buff tr">Transformed ${Math.ceil(S.transUntil - t)}s</span>`);
    if (me.shield > 0) buffs.push(`<span class="buff sh">Shield ${num(me.shield)}</span>`);
    if (S.stunUntil > t) buffs.push('<span class="buff bad">Stunned</span>');
    if (S.slowUntil > t) buffs.push('<span class="buff bad">Slowed</span>');
    $('buffs').innerHTML = buffs.join('');
    // Hotbar
    const hs = JSON.stringify([me.slot, me.equip, me.fruit, me.awake]);
    if (hs !== hotSig) { hotSig = hs; renderHotbar(); }
    const w = Game.myWeapon();
    const ss = JSON.stringify([w.id, TF.SKILL_KEYS.map((k) => (me.mastery[w.id] || 0) >= TF.SKILL_UNLOCK[k]), S.touch]);
    if (ss !== skillSig) { skillSig = ss; renderSkills(w); }
    // Quest
    const q = me.q;
    const qd = $('quest');
    if (q) {
      const mt = TF.MOB_TYPES[q.mob];
      const isl = mt.isle >= 0 ? TF.SEAS[mt.sea].islands[mt.isle] : null;
      qd.classList.remove('hidden');
      qd.innerHTML = `<h4>Quest</h4><div class="qmain">Defeat ${mt.boss ? '' : q.need + ' '}<b>${esc(mt.name)}</b></div>
        <div class="qbar"><i style="width:${(100 * q.have / q.need).toFixed(0)}%"></i><span>${q.have} / ${q.need}</span></div>
        <div class="qsub">${isl ? esc(isl.name) + ' · ' : ''}+${num(TF.questXp(mt.level, mt.boss))} XP · ${money(TF.questBeli(mt.level, mt.boss))}</div>`;
    } else {
      qd.classList.remove('hidden');
      qd.innerHTML = `<h4>No quest</h4><div class="qsub">${suggestion()}</div>`;
    }
    // Prompt
    const pr = $('prompt');
    if (S.nearNpc >= 0 && !panel) {
      const n = TF.NPCS[S.nearNpc];
      pr.innerHTML = `<kbd>${S.touch ? 'Tap' : 'E'}</kbd> Talk to ${esc(n.name)}`;
      pr.classList.remove('hidden');
    } else pr.classList.add('hidden');
    // Death
    const dd = $('death');
    if (S.dead) {
      dd.classList.remove('hidden');
      $('deathBy').textContent = `Defeated by ${S.deathBy}`;
      $('deathTimer').textContent = `Respawning in ${Math.max(0, S.respawnAt - t).toFixed(1)}s`;
    } else dd.classList.add('hidden');
    // Boss bar
    let boss = null, bd = 1000;
    for (const m of S.mobs.values()) {
      const mt = TF.MOB_TYPES[m.type];
      if (!mt.boss && !mt.seaBeast) continue;
      const d = Math.hypot(m.x - S.self.x, m.y - S.self.y);
      if (d < bd) { bd = d; boss = m; }
    }
    const bb = $('bossbar');
    if (boss) {
      const mt = TF.MOB_TYPES[boss.type];
      bb.classList.remove('hidden');
      $('bossName').textContent = `${mt.name} · Lv. ${num(mt.level)}`;
      $('bossFill').style.width = (100 * boss.hp / mt.hp).toFixed(1) + '%';
      $('bossHp').textContent = `${num(boss.hp)} / ${num(mt.hp)}`;
    } else bb.classList.add('hidden');
    $('tInteract').classList.toggle('hidden', !(S.touch && S.nearNpc >= 0));
    $('ping').textContent = S.ping ? S.ping + ' ms' : '';
    if (panel) refreshPanel(false);
  }

  function suggestion() {
    const me = S.me;
    const sea = TF.SEAS[S.sea];
    let best = null;
    for (const isl of sea.islands) for (const id of isl.mobs) { const mt = TF.MOB_TYPES[id]; if (mt.level <= me.lv) best = { mt, isl }; }
    if (!best) return 'Find a Quest Giver (!) and press E.';
    const nextSea = TF.SEAS[S.sea + 1];
    if (nextSea && me.lv >= nextSea.minLevel) return `You can sail to the ${nextSea.name}! Visit the Ferry Captain.`;
    return `Best for you: ${esc(best.mt.name)} on ${esc(best.isl.name)} — talk to its Quest Giver.`;
  }

  function fmtTime(s) {
    s = Math.max(0, Math.floor(s));
    const m = Math.floor(s / 60);
    return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}:${String(s % 60).padStart(2, '0')}`;
  }

  function itemIcon(it, size) {
    if (!it) return '<span class="ico empty">·</span>';
    if (it.cat === 'fruit') return `<img class="ico" src="${R.fruitIcon(it, size || 48)}" alt="">`;
    const glyph = it.cat === 'sword' ? '🗡' : it.cat === 'gun' ? '🔫' : '👊';
    return `<span class="ico glyph" style="--c:${it.color}">${glyph}</span>`;
  }

  function renderHotbar() {
    const me = S.me;
    const items = [TF.ITEMS[me.equip.style], me.equip.sword && TF.ITEMS[me.equip.sword], me.equip.gun && TF.ITEMS[me.equip.gun], me.fruit && TF.ITEMS[me.fruit]];
    $('hotbar').innerHTML = items.map((it, i) => `
      <button class="slot${me.slot === i ? ' sel' : ''}${it ? '' : ' none'}" data-slot="${i}">
        <kbd>${i + 1}</kbd>${itemIcon(it, 40)}<span>${it ? esc(it.cat === 'fruit' ? it.short : it.name) : SLOT_NAMES[i]}</span>
        ${i === 3 && me.awake ? '<em class="awk">★</em>' : ''}
      </button>`).join('');
  }

  function renderSkills(w) {
    const me = S.me;
    const m = me.mastery[w.id] || 0;
    $('skills').innerHTML = w.skills.map((sk) => {
      const locked = m < TF.SKILL_UNLOCK[sk.k];
      return `<button class="skill${locked ? ' locked' : ''}" data-key="${sk.k}" title="${esc(sk.n + ' — ' + TF.skillDesc(sk))}">
        <kbd>${sk.k.toUpperCase()}</kbd><span>${esc(sk.n)}</span>${locked ? `<small>🔒 ${TF.SKILL_UNLOCK[sk.k]}</small>` : ''}
        <i class="cd" data-cd="${w.id}:${sk.k}"></i><b class="cdt"></b></button>`;
    }).join('') + `<div class="mastery">${esc(w.it.cat === 'fruit' ? w.it.name : w.it.name)} · Mastery ${Math.floor(m)}/${TF.MASTERY_CAP}</div>`;
  }

  function updateSkillCooldowns(t) {
    const w = Game.myWeapon();
    document.querySelectorAll('#skills .skill').forEach((b) => {
      const key = w.id + ':' + b.dataset.key;
      const sk = w.skills.find((s) => s.k === b.dataset.key);
      const end = S.cd[key] || 0;
      const left = end - t;
      const total = (sk && sk.cd) || 5;
      b.querySelector('.cd').style.height = left > 0 ? Math.min(100, (100 * left) / total) + '%' : '0';
      b.querySelector('.cdt').textContent = left > 0 ? left.toFixed(left < 1 ? 1 : 0) : '';
    });
    const ml = $('skills').querySelector('.mastery');
    if (ml) ml.textContent = `${w.it.name} · Mastery ${Math.floor(S.me.mastery[w.id] || 0)}/${TF.MASTERY_CAP}`;
    const dash = $('dashCd');
    const dl = S.dashEnd - t;
    dash.textContent = dl > 0 ? `Dash ${dl.toFixed(1)}s` : 'Dash ready';
    dash.classList.toggle('ready', dl <= 0);
  }

  // ─── Panels ───────────────────────────────────────────────────────────────
  UI.toggle = function (name, arg) {
    if (panel === name && (arg === undefined || arg === panelArg)) return UI.close();
    UI.open(name, arg);
  };
  UI.open = function (name, arg) {
    panel = name;
    panelArg = arg === undefined ? null : arg;
    panelSig = '';
    confirmEat = -1;
    $('panel').classList.remove('hidden');
    $('panel').dataset.kind = name;
    refreshPanel(true);
  };
  UI.close = function () {
    panel = null;
    $('panel').classList.add('hidden');
  };
  UI.openNpc = function (npc) { UI.open('npc', npc.id); };
  UI.refresh = function () { if (panel) refreshPanel(false); };

  function refreshPanel(force) {
    if (!panel || !S.me) return;
    const def = PANELS[panel];
    if (!def) return;
    const sig = JSON.stringify(def.sig ? def.sig() : 0);
    if (!force && sig === panelSig) return;
    panelSig = sig;
    $('panelTitle').textContent = def.title();
    $('panelBody').innerHTML = def.body();
    if (def.after) def.after();
  }

  const meSig = (...keys) => keys.map((k) => S.me[k]);
  const npcOf = () => TF.NPCS[panelArg];

  const PANELS = {
    stats: {
      title: () => 'Stats',
      sig: () => [meSig('st', 'pts', 'lv', 'mhp', 'men')],
      body: () => {
        const me = S.me;
        const rows = Object.entries(STAT_INFO).map(([k, [name, desc]]) => {
          const v = me.st[k];
          return `<div class="statrow"><div class="sname"><b>${name}</b><small>${desc}</small></div>
            <div class="sbar"><i style="width:${(100 * v / TF.STAT_CAP).toFixed(1)}%"></i><span>${num(v)} / ${num(TF.STAT_CAP)}</span></div>
            <div class="sbtns">${[1, 10, 100].map((n) => `<button data-act="stat" data-k="${k}" data-n="${n}" ${me.pts <= 0 || v >= TF.STAT_CAP ? 'disabled' : ''}>+${n}</button>`).join('')}
            <button data-act="stat" data-k="${k}" data-n="99999" ${me.pts <= 0 || v >= TF.STAT_CAP ? 'disabled' : ''}>Max</button></div></div>`;
        }).join('');
        return `<div class="pts">Points to spend: <b>${num(me.pts)}</b> <small>(you earn ${TF.POINTS_PER_LEVEL} per level)</small></div>${rows}
          <div class="derived"><span>Max HP <b>${num(me.mhp)}</b></span><span>Max Energy <b>${num(me.men)}</b></span>
          <span>Damage bonus per point <b>+3.5%</b></span></div>
          <p class="hint">Refund your points at a Stat Trainer in any sea's town.</p>`;
      },
    },

    bag: {
      title: () => 'Bag',
      sig: () => [panelArg, confirmEat, meSig('fruit', 'fruits', 'owned', 'equip', 'awake', 'lv'), Object.values(S.me.mastery).map(Math.floor)],
      body: () => {
        const me = S.me;
        const tab = panelArg || 'fruit';
        let h = `<div class="tabs"><button data-act="tab" data-tab="fruit" class="${tab === 'fruit' ? 'sel' : ''}">Fruits</button><button data-act="tab" data-tab="gear" class="${tab === 'gear' ? 'sel' : ''}">Weapons &amp; Styles</button></div>`;
        if (tab === 'fruit') {
          const fr = me.fruit && TF.ITEMS[me.fruit];
          h += '<h3>Eaten fruit</h3>';
          h += fr ? fruitCard(fr, me.mastery[fr.id] || 0, me.awake) : '<p class="hint">You have not eaten a fruit. Buy one from a Fruit Merchant, roll one at the Fruit Mystic, or find one lying on an island.</p>';
          h += `<h3>Stored fruits <small>${me.fruits.length} / ${TF.FRUIT_INV_CAP}</small></h3>`;
          if (!me.fruits.length) h += '<p class="hint">Nothing stored.</p>';
          h += '<div class="grid">' + me.fruits.map((fid, i) => {
            const f = TF.ITEMS[fid];
            const r = TF.RARITY[f.rarity];
            const conf = confirmEat === i;
            return `<div class="card" style="--r:${r.color}">${itemIcon(f, 56)}<b>${esc(f.name)}</b><small style="color:${r.color}">${r.name} · ${typeName(f.type)}</small>
              <div class="row"><button data-act="eat" data-i="${i}" class="${conf ? 'warn' : 'go'}">${conf ? `Replace ${esc(fr ? fr.short : '')}?` : 'Eat'}</button><button data-act="drop" data-i="${i}">Drop</button></div></div>`;
          }).join('') + '</div><p class="hint">Eating a fruit replaces the one you have — the old one is gone for good. Dropping puts it on the ground for anyone to pick up (trade this way).</p>';
        } else {
          for (const cat of ['style', 'sword', 'gun']) {
            const owned = me.owned.map((id) => TF.ITEMS[id]).filter((it) => it && it.cat === cat);
            h += `<h3>${cat === 'style' ? 'Fighting styles' : cat === 'sword' ? 'Swords' : 'Guns'}</h3>`;
            if (!owned.length) h += `<p class="hint">None yet — buy one from the ${cat === 'gun' ? 'Gunsmith' : cat === 'sword' ? 'Blacksmith' : 'Martial Master'}.</p>`;
            h += owned.map((it) => {
              const eq = me.equip[cat] === it.id;
              return `<div class="item">${itemIcon(it)}<div class="iname"><b>${esc(it.name)}</b><small>Base ${it.base} · Mastery ${Math.floor(me.mastery[it.id] || 0)}</small>
                <small class="sk">${it.skills.map((s) => `<kbd>${s.k.toUpperCase()}</kbd> ${esc(s.n)}`).join(' ')}</small></div>
                ${eq ? '<span class="badge">Equipped</span>' : `<button data-act="equip" data-id="${it.id}">Equip</button>`}</div>`;
            }).join('');
          }
        }
        return h;
      },
    },

    map: {
      title: () => `Map — ${TF.SEAS[S.sea].name}`,
      body: () => `<canvas id="bigmap" width="720" height="720"></canvas>
        <p class="hint">White: your level. Red: too strong for now. Grey: you have out-grown it. Red dots are bosses; orange is a sea beast.</p>`,
      after: () => R.drawMap($('bigmap'), S, true),
    },

    top: {
      title: () => 'Leaderboard',
      sig: () => [S.lb],
      body: () => {
        const lb = S.lb || { level: [], bounty: [] };
        const table = (rows, label, f) => `<table><tr><th>#</th><th>Captain</th><th>${label}</th></tr>${rows.map((r, i) =>
          `<tr class="${r[2]}"><td>${i + 1}</td><td>${r[2] === 'marine' ? '⚓' : '☠'} ${esc(r[0])}</td><td>${f(r[1])}</td></tr>`).join('') || '<tr><td colspan="3">Nobody yet</td></tr>'}</table>`;
        return `<div class="lbwrap"><div><h3>Highest level</h3>${table(lb.level, 'Level', num)}</div><div><h3>Bounty &amp; honor</h3>${table(lb.bounty, 'Bounty', money)}</div></div>
          <p class="hint">${lb.online || 0} online${lb.seas ? ' · ' + lb.seas.map((n, i) => `${TF.SEAS[i].name}: ${n}`).join(' · ') : ''}</p>`;
      },
    },

    codes: {
      title: () => 'Codes',
      body: () => `<p>Redeem a code for rewards. Each works once per captain.</p>
        <div class="row"><input id="codeInput" maxlength="24" placeholder="Enter code"><button data-act="code" class="go">Redeem</button></div>
        <p class="hint">Starter codes: <b>FIRSTSAIL</b> (random fruit), <b>SEAFRUIT</b> ($25,000), <b>TIDES2X</b> (2× XP for 30 minutes), <b>FRESHSTART</b> (free stat reset).</p>`,
      after: () => {
        const i = $('codeInput');
        i.addEventListener('keydown', (e) => { if (e.key === 'Enter') { Game.send({ t: 'code', c: i.value }); i.value = ''; } e.stopPropagation(); });
        setTimeout(() => i.focus(), 30);
      },
    },

    help: {
      title: () => 'How to play',
      body: () => `<div class="help">
        <div><h3>Controls</h3><ul>
        <li><kbd>WASD</kbd> move · <kbd>Mouse</kbd> aim · <kbd>Left click</kbd> attack (hold)</li>
        <li><kbd>Z</kbd> <kbd>X</kbd> <kbd>C</kbd> <kbd>V</kbd> <kbd>F</kbd> skills of the weapon in hand</li>
        <li><kbd>1</kbd>–<kbd>4</kbd> fighting style, sword, gun, fruit</li>
        <li><kbd>Q</kbd>/<kbd>Space</kbd> dash · <kbd>E</kbd> talk · <kbd>Enter</kbd> chat</li>
        <li><kbd>K</kbd> stats · <kbd>I</kbd> bag · <kbd>M</kbd> map · <kbd>Tab</kbd> leaderboard · <kbd>P</kbd> PvP</li>
        <li><kbd>Mouse wheel</kbd> zoom</li></ul></div>
        <div><h3>The grind</h3><ul>
        <li>Take a quest from an island's <b>Quest Giver</b>. Quests renew themselves when done.</li>
        <li>Every level gives ${TF.POINTS_PER_LEVEL} stat points. Put them into what you fight with, and Defense.</li>
        <li>Using a weapon raises its <b>mastery</b>, which unlocks its skills (X at 25, C at 75, V at 150, F at 250).</li>
        <li>Walk into the sea and you sail. Four seas open at levels 1, 700, 1,500 and 2,300. Max level is ${num(TF.MAX_LEVEL)}.</li>
        <li>Fruits come from the Fruit Merchant (stock rotates every 15 minutes), the Fruit Mystic, boss drops, and the wild — one falls somewhere in each sea every few minutes.</li>
        <li><b>Elemental</b> fruits phase through some hits. <b>Beast</b> fruits transform with V.</li>
        <li>From level ${TF.PVP_MIN_LEVEL}, switch PvP on to fight other players outside towns. Pirates earn bounty; Marines earn honor and cannot hurt each other.</li></ul></div></div>`,
    },

    npc: {
      title: () => npcOf().name,
      sig: () => {
        const n = npcOf();
        const base = [panelArg, meSig('beli', 'frags', 'lv', 'owned', 'equip', 'q', 'fruit', 'awake', 'ab', 'fruits', 'st', 'sea')];
        if (n.kind === 'fruit') base.push(S.stock, Math.floor(S.stockAt - S.time));
        if (n.kind === 'gacha') base.push(S.me.gacha);
        return base;
      },
      body: () => NPC_BODY[npcOf().kind](npcOf()),
    },
  };

  function typeName(t) { return t === 'elemental' ? 'Elemental' : t === 'beast' ? 'Beast' : 'Natural'; }

  function fruitCard(fr, mastery, awake) {
    const r = TF.RARITY[fr.rarity];
    return `<div class="fruitcard" style="--r:${r.color}">${itemIcon(fr, 72)}<div>
      <b>${esc(fr.name)}</b> ${awake ? '<span class="badge gold">★ Awakened</span>' : ''}<br>
      <small style="color:${r.color}">${r.name} · ${typeName(fr.type)}</small><small> · Mastery ${Math.floor(mastery)}/${TF.MASTERY_CAP}</small>
      <ul class="sklist">${fr.skills.map((s) => `<li class="${mastery < TF.SKILL_UNLOCK[s.k] ? 'locked' : ''}"><kbd>${s.k.toUpperCase()}</kbd> <b>${esc(s.n)}</b> <small>${esc(TF.skillDesc(s))}${mastery < TF.SKILL_UNLOCK[s.k] ? ' · unlocks at ' + TF.SKILL_UNLOCK[s.k] : ''}</small></li>`).join('')}</ul></div></div>`;
  }

  function shopItem(it, extra) {
    const me = S.me;
    const owned = me.owned.includes(it.id);
    const eq = me.equip[it.cat] === it.id;
    const lvlock = it.minLevel && me.lv < it.minLevel;
    const cost = `${money(it.price)}${it.frags ? ` + ◆${num(it.frags)}` : ''}`;
    return `<div class="item">${itemIcon(it)}<div class="iname"><b>${esc(it.name)}</b><small>Base damage ${it.base}${it.minLevel ? ` · Requires level ${num(it.minLevel)}` : ''}${extra || ''}</small>
      <small class="sk">${it.skills.map((s) => `<kbd>${s.k.toUpperCase()}</kbd> ${esc(s.n)}`).join(' ')}</small></div>
      ${owned ? (eq ? '<span class="badge">Equipped</span>' : `<button data-act="equip" data-id="${it.id}">Equip</button>`)
        : `<button data-act="npc" data-a="buy" data-id="${it.id}" class="go" ${me.beli < it.price || (it.frags && me.frags < it.frags) || lvlock ? 'disabled' : ''}>${cost}</button>`}</div>`;
  }

  const NPC_BODY = {
    quest(n) {
      const me = S.me;
      const isl = TF.SEAS[n.sea].islands[n.isle];
      const choices = [isl.mobs[0], isl.mobs[1], isl.boss];
      let h = `<p class="lead">Welcome to <b>${esc(isl.name)}</b>. Monsters here are level ${num(isl.lv[0])}–${num(isl.lv[1])}.</p>`;
      h += choices.map((id, i) => {
        const mt = TF.MOB_TYPES[id];
        const need = mt.boss ? 1 : TF.questCount(n.sea);
        const ok = me.lv >= mt.level;
        const cur = me.q && me.q.mob === id;
        return `<div class="item quest${mt.boss ? ' boss' : ''}"><div class="iname"><b>${mt.boss ? '👑 ' : ''}Defeat ${mt.boss ? '' : need + ' × '}${esc(mt.name)}</b>
          <small>Lv. ${num(mt.level)} · ${num(mt.hp)} HP${mt.drop ? ` · may drop the ${esc(TF.ITEMS[mt.drop].name)}` : ''}</small>
          <small class="rew">+${num(TF.questXp(mt.level, mt.boss))} XP · ${money(TF.questBeli(mt.level, mt.boss))}</small></div>
          ${cur ? '<span class="badge">Active</span>' : ok ? `<button class="go" data-act="npc" data-a="accept" data-i="${i}">Accept</button>` : `<button disabled>Lv. ${num(mt.level)}</button>`}</div>`;
      }).join('');
      h += `<div class="row">${me.q ? '<button data-act="npc" data-a="abandon">Abandon quest</button>' : ''}<button data-act="npc" data-a="spawn">Set spawn here</button></div>`;
      return h;
    },
    fruit() {
      const me = S.me;
      const left = Math.max(0, S.stockAt - S.time);
      return `<p class="lead">Fresh fruit from every sea. New stock in <b>${fmtTime(left)}</b>.</p><div class="grid">` + S.stock.map((fid) => {
        const f = TF.ITEMS[fid];
        const r = TF.RARITY[f.rarity];
        return `<div class="card" style="--r:${r.color}">${itemIcon(f, 56)}<b>${esc(f.name)}</b><small style="color:${r.color}">${r.name} · ${typeName(f.type)}</small>
          <button class="go" data-act="npc" data-a="buy" data-id="${fid}" ${me.beli < f.price ? 'disabled' : ''}>${money(f.price)}</button></div>`;
      }).join('') + '</div><p class="hint">Bought fruit goes to your bag [I]. Eat it from there.</p>';
    },
    gacha() {
      const me = S.me;
      const cost = TF.gachaCost(me.lv);
      const odds = Object.values(TF.RARITY);
      const total = odds.reduce((a, r) => a + r.w, 0);
      return `<p class="lead">"Cross my palm with Beli and the sea will choose your fruit."</p>
        <div class="odds">${odds.map((r) => `<span style="color:${r.color}">${r.name} ${((100 * r.w) / total).toFixed(0)}%</span>`).join('')}</div>
        <div class="row center"><button class="go big" data-act="npc" data-a="roll" ${me.gacha > 0 || me.beli < cost ? 'disabled' : ''}>${me.gacha > 0 ? 'Back in ' + fmtTime(me.gacha) : 'Roll for ' + money(cost)}</button></div>
        <p class="hint">One roll every 20 minutes. The price grows with your level.</p>`;
    },
    sword(n) { return weaponShop(n, 'sword'); },
    gun(n) { return weaponShop(n, 'gun'); },
    style(n) { return weaponShop(n, 'style'); },
    ability() {
      const me = S.me;
      return '<p class="lead">"Strength is more than a stat sheet."</p>' + TF.ABILITIES.map((a) => `<div class="item"><span class="ico glyph" style="--c:#80deea">✦</span>
        <div class="iname"><b>${a.name}</b><small>${a.desc}</small></div>
        ${me.ab[a.id] ? '<span class="badge">Learned</span>' : `<button class="go" data-act="npc" data-a="buy" data-id="${a.id}" ${me.beli < a.price ? 'disabled' : ''}>${money(a.price)}</button>`}</div>`).join('');
    },
    ferry() {
      const me = S.me;
      return '<p class="lead">"Where to, captain?"</p>' + TF.SEAS.map((s, i) => `<div class="item"><span class="ico glyph" style="--c:${s.water[0]}">${SEA_ICONS[i]}</span>
        <div class="iname"><b>${s.name}</b><small>Levels ${num(s.minLevel)}${TF.SEAS[i + 1] ? '–' + num(TF.SEAS[i + 1].minLevel) : '–' + num(TF.MAX_LEVEL)} · ${s.islands.length} islands</small></div>
        ${i === S.sea ? '<span class="badge">You are here</span>' : me.lv >= s.minLevel ? `<button class="go" data-act="npc" data-a="travel" data-sea="${i}">Sail</button>` : `<button disabled>Lv. ${num(s.minLevel)}</button>`}</div>`).join('');
    },
    reset() {
      const me = S.me;
      const cost = TF.resetCost(me.lv);
      const spent = Object.values(me.st).reduce((a, b) => a + b, 0);
      return `<p class="lead">"Not happy with your build? I can fix that."</p><p>You have ${num(spent)} points spent.</p>
        <div class="row center"><button class="go big" data-act="npc" data-a="reset" ${me.beli < cost || !spent ? 'disabled' : ''}>Refund all for ${money(cost)}</button></div>`;
    },
    awaken() {
      const me = S.me;
      if (!me.fruit) return '<p class="lead">"Come back when you have eaten a fruit."</p>';
      const fr = TF.ITEMS[me.fruit];
      const cost = TF.RARITY[fr.rarity].awaken;
      return `<p class="lead">"Every fruit sleeps. I can wake yours."</p>${fruitCard(fr, me.mastery[fr.id] || 0, me.awake)}
        <p>Awakening gives +25% fruit damage and 20% shorter fruit cooldowns. It is lost if you eat another fruit.</p>
        <div class="row center">${me.awake ? '<span class="badge gold">Already awakened</span>' : `<button class="go big" data-act="npc" data-a="awaken" ${me.frags < cost ? 'disabled' : ''}>Awaken for ◆${num(cost)}</button>`}</div>
        <p class="hint">Fragments (◆) drop from bosses in the second sea and beyond, and from sea beasts.</p>`;
    },
  };

  function weaponShop(n, cat) {
    const list = Object.values(TF.ITEMS).filter((it) => it.cat === cat && it.sea === n.sea);
    const sold = list.filter((it) => !it.drop).sort((a, b) => a.price - b.price);
    const drops = list.filter((it) => it.drop);
    let h = `<p class="lead">${cat === 'style' ? '"Fists are the oldest weapon."' : cat === 'sword' ? '"Every blade here is sharp enough."' : '"Point the dangerous end away from you."'}</p>`;
    h += sold.map((it) => shopItem(it)).join('');
    if (drops.length) {
      h += `<h3>Boss drops in this sea</h3>` + drops.map((it) => {
        const boss = TF.MOB_TYPES.find((m) => m.drop === it.id);
        return `<div class="item dim">${itemIcon(it)}<div class="iname"><b>${esc(it.name)}</b><small>Base ${it.base} · 20% drop from ${esc(boss ? boss.name : '?')}</small></div>${S.me.owned.includes(it.id) ? (S.me.equip[cat] === it.id ? '<span class="badge">Equipped</span>' : `<button data-act="equip" data-id="${it.id}">Equip</button>`) : ''}</div>`;
      }).join('');
    }
    return h;
  }

  function onPanelClick(e) {
    const b = e.target.closest('[data-act]');
    if (!b || b.disabled) return;
    const d = b.dataset;
    switch (d.act) {
      case 'stat': Game.send({ t: 'stat', k: d.k, n: +d.n }); break;
      case 'tab': panelArg = d.tab; refreshPanel(true); break;
      case 'equip': Game.send({ t: 'equip', id: d.id }); break;
      case 'eat': {
        const i = +d.i;
        if (S.me.fruit && confirmEat !== i) { confirmEat = i; refreshPanel(true); return; }
        confirmEat = -1;
        Game.send({ t: 'eat', i });
        break;
      }
      case 'drop': Game.send({ t: 'drop', i: +d.i }); break;
      case 'code': { const i = $('codeInput'); Game.send({ t: 'code', c: i.value }); i.value = ''; break; }
      case 'npc': {
        const msg = { t: 'npc', n: panelArg, a: d.a };
        if (d.i !== undefined) msg.i = +d.i;
        if (d.id !== undefined) msg.id = d.id;
        if (d.sea !== undefined) msg.sea = +d.sea;
        Game.send(msg);
        if (d.a === 'travel') UI.close();
        break;
      }
    }
  }

  // ─── Touch controls ──────────────────────────────────────────────────────
  UI.enableTouch = function () {
    document.body.classList.add('touch');
    $('touch').classList.remove('hidden');
    skillSig = '';
  };

  function bindTouch() {
    const joy = $('joy'), knob = $('joyKnob');
    let jid = null, cx = 0, cy = 0;
    const R0 = 55;
    const move = (tch) => {
      let dx = tch.clientX - cx, dy = tch.clientY - cy;
      const d = Math.hypot(dx, dy);
      if (d > R0) { dx *= R0 / d; dy *= R0 / d; }
      knob.style.transform = `translate(${dx}px, ${dy}px)`;
      S.joy.x = dx / R0; S.joy.y = dy / R0;
      S.joy.active = d > 6;
    };
    joy.addEventListener('touchstart', (e) => {
      const tch = e.changedTouches[0];
      jid = tch.identifier;
      const r = joy.getBoundingClientRect();
      cx = r.left + r.width / 2; cy = r.top + r.height / 2;
      move(tch);
      e.preventDefault();
    }, { passive: false });
    joy.addEventListener('touchmove', (e) => {
      for (const tch of e.changedTouches) if (tch.identifier === jid) move(tch);
      e.preventDefault();
    }, { passive: false });
    const end = (e) => {
      for (const tch of e.changedTouches) if (tch.identifier === jid) {
        jid = null; S.joy.active = false; S.joy.x = S.joy.y = 0; knob.style.transform = '';
      }
    };
    joy.addEventListener('touchend', end);
    joy.addEventListener('touchcancel', end);
    const atk = $('tAttack');
    atk.addEventListener('touchstart', (e) => { S.touchAttack = true; e.preventDefault(); }, { passive: false });
    atk.addEventListener('touchend', () => { S.touchAttack = false; });
    atk.addEventListener('touchcancel', () => { S.touchAttack = false; });
    $('tDash').addEventListener('touchstart', (e) => { Game.tryDash(); e.preventDefault(); }, { passive: false });
    $('tInteract').addEventListener('touchstart', (e) => { Game.interact(); e.preventDefault(); }, { passive: false });
    $('tChat').addEventListener('click', () => UI.focusChat());
  }
})();
