/* ============================================================================
   SHISHYA — control panel

   Week 1 scope: prove the pipeline. Boot the sandbox, see the clone's screen
   in this page, click into it, snapshot and roll back. No agent yet.
   ========================================================================== */

import { api } from "./api.js";

const $ = id => document.getElementById(id);
const VERDICT_CLASS = { allow: "ok", deny: "no", info: "" };

let netLocked = null;
let lastStatus = null;     // so the rollback prompt can name the snapshot      // unknown until the sandbox is asked
let wheel = true;           // interactive from the start

/* ─── logging ────────────────────────────────────────────────────────────── */

function log(msg, kind = "") {
  const line = document.createElement("div");
  line.className = `logLine ${kind}`;
  line.textContent = `${new Date().toLocaleTimeString()}  ${msg}`;
  $("log").prepend(line);
  while ($("log").childElementCount > 60) $("log").lastElementChild.remove();
}

/* Any control that talks to the VM is slow (snapshots take a while) and must
   not be double-fired — a second rollback mid-rollback corrupts the disk. */
async function guard(btn, label, fn) {
  const was = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Working…";
  try {
    const out = await fn();
    log(`${label} ✓`, "ok");
    return out;
  } catch (e) {
    log(`${label} ✗ ${e.message}`, "no");
  } finally {
    btn.disabled = false;
    btn.textContent = was;
    /* ─── terminal ───────────────────────────────────────────────────────────── */
/* Reaches into the sandbox and nowhere else. There is no pty behind it, so
   each command is its own shell — no interactive programs, and cd does not
   carry over. It is for looking at things. */

const history = [];
let histAt = 0;

async function runCommand() {
  const cmd = $("termIn").value.trim();
  if (!cmd) return;
  history.push(cmd);
  histAt = history.length;
  $("termIn").value = "";
  echo(cmd, "cmd");
  try {
    const r = await api.shell(cmd);
    if (r.out) echo(r.out);
    if (r.err) echo(r.err, "bad");
    if (!r.out && !r.err) echo(`(exit ${r.code})`, "cmd");
  } catch (e) {
    echo(e.message, "bad");
  }
}

function echo(text, kind) {
  const line = document.createElement("span");
  if (kind) line.className = kind;
  line.textContent = text + "\n";
  const out = $("termOut");
  out.append(line);
  out.scrollTop = out.scrollHeight;
}

$("btnRun").onclick = runCommand;
$("termIn").addEventListener("keydown", e => {
  if (e.key === "Enter") return runCommand();
  // Up and down walk what you already typed, as any shell does.
  if (e.key === "ArrowUp" && histAt > 0) {
    histAt--; $("termIn").value = history[histAt] ?? ""; e.preventDefault();
  }
  if (e.key === "ArrowDown") {
    histAt = Math.min(histAt + 1, history.length);
    $("termIn").value = history[histAt] ?? ""; e.preventDefault();
  }
});

/* ─── appearance ─────────────────────────────────────────────────────────── */
/* Three states. Auto is the absence of the attribute, which is exactly what
   the stylesheet already keys on — the media query only applies when nothing
   has been stamped on the root. */

const THEMES = ["auto", "light", "dark"];

function applyTheme(name) {
  if (name === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", name);
  $("btnTheme").textContent = name;
  try { localStorage.setItem("shishya.theme", name); } catch { /* private mode */ }
}

applyTheme((() => {
  try { return THEMES.includes(localStorage.getItem("shishya.theme"))
    ? localStorage.getItem("shishya.theme") : "auto"; } catch { return "auto"; }
})());

$("btnTheme").onclick = () => {
  const now = $("btnTheme").textContent.trim().toLowerCase();
  applyTheme(THEMES[(THEMES.indexOf(now) + 1) % THEMES.length]);
};

refresh();
  }
}

/* ─── painting ───────────────────────────────────────────────────────────── */

function paintLedger(entries) {
  const el = $("ledger");
  el.textContent = "";
  for (const e of entries.slice().reverse()) {
    const row = document.createElement("div");
    row.className = `entry ${VERDICT_CLASS[e.verdict] ?? ""}`;
    row.innerHTML =
      `<span class="v">${e.verdict}</span>` +
      `<span class="a">${e.action}</span>` +
      `<span class="t"></span>`;
    // textContent, not innerHTML — targets are filenames the clone chose, and
    // a document named like a <script> tag should never execute in this panel.
    row.querySelector(".t").textContent = e.target ?? "";
    if (e.detail) row.title = e.detail;
    el.append(row);
  }
}

function paintStatus(s) {
  lastStatus = s;
  /* Egress comes from the sandbox's own firewall, not from a variable we set
     when we last pressed the button. An indicator that reports a state it
     never checked is worse than no indicator on a panel whose whole promise
     is that you can verify what happened. */
  const b = s.browsing ?? {};
  browsing = b.browsing;
  const bp = $("browseState");
  if (bp) {
    bp.textContent = b.browsing === true ? "Allowed" : b.browsing === false ? "Blocked" : "—";
    bp.className = b.browsing === true ? "open" : "locked";
    bp.title = b.detail ?? "";
  }
  $("btnBrowse").textContent = b.browsing === true ? "Stop browsing" : "Allow browsing";

  const e = s.egress ?? {};
  netLocked = e.locked;
  const pill = $("netState");
  pill.textContent = e.locked === true ? "Locked"
                   : e.locked === false ? "Open" : "Unknown";
  pill.className = e.locked === true ? "locked" : e.locked === false ? "open" : "no";
  pill.title = e.detail ?? "";
  $("btnNet").textContent = e.locked === true ? "Unlock network" : "Lock network";

  const state = s.vm?.state ?? "unknown";
  $("vmState").textContent = state.charAt(0).toUpperCase() + state.slice(1);
  $("vmState").className = state === "running" ? "ok" : "no";
  $("denyCount").textContent = s.ledger?.denied ?? 0;
  $("denyCount").className = (s.ledger?.denied ?? 0) > 0 ? "no" : "";

  const live = state === "running";
  $("screenMsg").style.display = live ? "none" : "grid";
  $("screenMsg").textContent = live ? "" : `sandbox ${state}`;

  // Three states, not two: unknown is its own answer when the sandbox is down.
  const eg = s.egress ?? {};
  netLocked = eg.locked;
  const label = netLocked === true ? "Locked" : netLocked === false ? "Open" : "Unknown";
  $("netState").textContent = label;
  $("netState").className = netLocked === true ? "locked" : netLocked === false ? "open" : "";
  $("netState").title = eg.detail ?? "";
  $("btnNet").textContent = netLocked === true ? "Unlock network" : "Lock network";
}

async function refresh() {
  try {
    const [s, l, box] = await Promise.all([api.status(), api.ledger(), api.inbox()]);
    paintStatus(s);
    paintLedger(l.entries);
    const n = box.waiting.length;
    $("inboxCount").textContent = n ? `${n} waiting` : "empty";
  } catch (e) {
    $("vmState").textContent = "HOST DOWN";
    $("vmState").className = "no";
  }
}

/* ─── take the wheel ─────────────────────────────────────────────────────── */
/* The VNC session is shared, so handing over control is only a matter of
   dropping view_only — the clone keeps its session either way. */

/* The button used to be labelled with the action rather than the state:
   while you were in control it read "Hand it back", which reads as an
   instruction to press it. Pressing it then switched your input off, and the
   sandbox appeared frozen. It now states what is true right now, and says
   underneath what pressing it would do. */
function setWheel(on) {
  wheel = on;
  const f = $("vnc");
  const url = new URL(f.src);
  url.searchParams.set("view_only", on ? "0" : "1");
  url.searchParams.set("reconnect", "1");
  f.src = url.toString();
  const b = $("btnWheel");
  b.classList.toggle("on", on);
  b.classList.toggle("off", !on);
  b.textContent = on ? "You have control" : "○ WATCHING ONLY — CLICK TO CONTROL";
  b.title = on ? "Click to stop sending your clicks to the sandbox"
               : "Click to send your clicks and typing to the sandbox";
  log(on ? "you have control of the sandbox" : "your input is no longer being sent");
}

/* ─── wiring ─────────────────────────────────────────────────────────────── */

$("btnCreate").onclick = e => guard(e.target, "first boot", api.create);
$("btnStart").onclick  = e => guard(e.target, "start",      api.start);
$("btnStop").onclick   = e => guard(e.target, "stop",       api.stop);
$("btnSnap").onclick   = e => guard(e.target, "snapshot",   () => api.snapshot("clean"));

$("btnRoll").onclick = e => {
  /* Say what you are rolling back TO. A snapshot taken before the sandbox was
     built does not undo the clone's work — it wipes the machine, which is
     exactly what happened once. The date makes that visible before you commit. */
  const taken = lastStatus?.snapshot_taken;
  const when = taken ? `taken ${taken}` : "no snapshot has been marked";
  if (!confirm(`Roll the sandbox back to the clean mark (${when})?\n\n` +
               `Everything the clone has done since then is discarded.\n\n` +
               `If that mark is older than the apps, this wipes them too.`)) return;
  guard(e.target, "rollback", () => api.rollback("clean"));
};

$("btnNet").onclick = e => guard(e.target, "egress",
  /* Ask for the opposite of what the sandbox actually reports. When the state
     is unknown, locking is the safe direction to move in. */
  () => api.egress(netLocked !== true));

/* ─── sending files to the clone ─────────────────────────────────────────── */

const drop = $("drop"), picker = $("picker");

drop.onclick = () => picker.click();
picker.onchange = () => { send([...picker.files]); picker.value = ""; };

/* Listen on the window, not just the box: people aim at the panel, and a
   drop that lands two pixels outside would otherwise navigate the browser
   away to the file itself. */
for (const ev of ["dragenter", "dragover"]) {
  window.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); });
}
for (const ev of ["dragleave", "drop"]) {
  window.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); });
}
window.addEventListener("drop", e => send([...(e.dataTransfer?.files ?? [])]));

async function send(files) {
  if (!files.length) return;
  drop.classList.add("busy");
  let done = 0;
  for (const file of files) {
    try {
      const out = await api.upload(file);
      log(`sent ${out.name} (${Math.round(out.bytes / 1024)}kB)`, "ok");
      done++;
    } catch (e) {
      log(`${file.name} ✗ ${e.message}`, "no");
    }
  }
  drop.classList.remove("busy");
  if (done) /* ─── terminal ───────────────────────────────────────────────────────────── */
/* Reaches into the sandbox and nowhere else. There is no pty behind it, so
   each command is its own shell — no interactive programs, and cd does not
   carry over. It is for looking at things. */

const history = [];
let histAt = 0;

async function runCommand() {
  const cmd = $("termIn").value.trim();
  if (!cmd) return;
  history.push(cmd);
  histAt = history.length;
  $("termIn").value = "";
  echo(cmd, "cmd");
  try {
    const r = await api.shell(cmd);
    if (r.out) echo(r.out);
    if (r.err) echo(r.err, "bad");
    if (!r.out && !r.err) echo(`(exit ${r.code})`, "cmd");
  } catch (e) {
    echo(e.message, "bad");
  }
}

function echo(text, kind) {
  const line = document.createElement("span");
  if (kind) line.className = kind;
  line.textContent = text + "\n";
  const out = $("termOut");
  out.append(line);
  out.scrollTop = out.scrollHeight;
}

$("btnRun").onclick = runCommand;
$("termIn").addEventListener("keydown", e => {
  if (e.key === "Enter") return runCommand();
  // Up and down walk what you already typed, as any shell does.
  if (e.key === "ArrowUp" && histAt > 0) {
    histAt--; $("termIn").value = history[histAt] ?? ""; e.preventDefault();
  }
  if (e.key === "ArrowDown") {
    histAt = Math.min(histAt + 1, history.length);
    $("termIn").value = history[histAt] ?? ""; e.preventDefault();
  }
});

/* ─── appearance ─────────────────────────────────────────────────────────── */
/* Three states. Auto is the absence of the attribute, which is exactly what
   the stylesheet already keys on — the media query only applies when nothing
   has been stamped on the root. */

const THEMES = ["auto", "light", "dark"];

function applyTheme(name) {
  if (name === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", name);
  $("btnTheme").textContent = name;
  try { localStorage.setItem("shishya.theme", name); } catch { /* private mode */ }
}

applyTheme((() => {
  try { return THEMES.includes(localStorage.getItem("shishya.theme"))
    ? localStorage.getItem("shishya.theme") : "auto"; } catch { return "auto"; }
})());

$("btnTheme").onclick = () => {
  const now = $("btnTheme").textContent.trim().toLowerCase();
  applyTheme(THEMES[(THEMES.indexOf(now) + 1) % THEMES.length]);
};

refresh();
}

/* Launching from out here never touches the display, so it still works on
   the evenings when clicking inside the sandbox does not. */
for (const btn of document.querySelectorAll("#apps [data-app]")) {
  btn.onclick = () => guard(btn, `open ${btn.textContent.toLowerCase()}`,
                            () => api.launch(btn.dataset.app));
}

/* ─── asking, and closing, without the display ───────────────────────────── */

async function askClone() {
  const text = $("askBox").value.trim();
  if (!text) return;
  const out = $("answer");
  out.className = "answer waiting";
  out.textContent = "Asking… the first answer of the evening is the slowest.";
  try {
    await api.ask(text);
    // The app answers on its own thread, so poll rather than assume.
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 3000));
      const got = await api.answer();
      const text_ = (got.result || "").trim();
      if (text_ && !/^\(no answer/.test(text_)) {
        out.className = "answer";
        out.textContent = text_;
        return;
      }
    }
    out.textContent = "Still working. Look at the clone's screen — it may already be there.";
  } catch (e) {
    out.className = "answer";
    out.textContent = `Couldn't ask: ${e.message}`;
  }
}

$("btnAsk").onclick = askClone;
$("askBox").addEventListener("keydown", e => { if (e.key === "Enter") askClone(); });

$("btnSources").onclick = e => guard(e.target, "use as sources", async () => {
  const out = await api.sources();
  log(out.added.length
        ? `now reading: ${out.added.join(", ")}`
        : "nothing waiting in the inbox", out.added.length ? "ok" : "");
  return out;
});

$("btnCloseAll").onclick = e =>
  guard(e.target, "close apps", () => api.close());

/* Browsing is a mode, not a setting: it shows in the header beside EGRESS so
   nobody can be unsure whether the sandbox can currently reach the web. */
let browsing = null;

$("btnBrowse").onclick = e => guard(e.target, "browsing", async () => {
  const out = await api.browsing(browsing !== true);
  if (!out.browsing && out.detail) log(out.detail, "no");
  return out;
});

$("btnFix").onclick = e => guard(e.target, "rebuild display", async () => {
  const out = await api.fixInput();
  log(`display rebuilt — ${out.note}`, "ok");
  // The iframe is holding the connection that just went away.
  $("vnc").src = $("vnc").src;
  return out;
});

$("btnWheel").onclick = () => setWheel(!wheel);
$("btnReload").onclick = () => { $("vnc").src = $("vnc").src; log("reconnecting to clone display"); };

/* ─── terminal ───────────────────────────────────────────────────────────── */
/* Reaches into the sandbox and nowhere else. There is no pty behind it, so
   each command is its own shell — no interactive programs, and cd does not
   carry over. It is for looking at things. */

const history = [];
let histAt = 0;

async function runCommand() {
  const cmd = $("termIn").value.trim();
  if (!cmd) return;
  history.push(cmd);
  histAt = history.length;
  $("termIn").value = "";
  echo(cmd, "cmd");
  try {
    const r = await api.shell(cmd);
    if (r.out) echo(r.out);
    if (r.err) echo(r.err, "bad");
    if (!r.out && !r.err) echo(`(exit ${r.code})`, "cmd");
  } catch (e) {
    echo(e.message, "bad");
  }
}

function echo(text, kind) {
  const line = document.createElement("span");
  if (kind) line.className = kind;
  line.textContent = text + "\n";
  const out = $("termOut");
  out.append(line);
  out.scrollTop = out.scrollHeight;
}

$("btnRun").onclick = runCommand;
$("termIn").addEventListener("keydown", e => {
  if (e.key === "Enter") return runCommand();
  // Up and down walk what you already typed, as any shell does.
  if (e.key === "ArrowUp" && histAt > 0) {
    histAt--; $("termIn").value = history[histAt] ?? ""; e.preventDefault();
  }
  if (e.key === "ArrowDown") {
    histAt = Math.min(histAt + 1, history.length);
    $("termIn").value = history[histAt] ?? ""; e.preventDefault();
  }
});

/* ─── appearance ─────────────────────────────────────────────────────────── */
/* Three states. Auto is the absence of the attribute, which is exactly what
   the stylesheet already keys on — the media query only applies when nothing
   has been stamped on the root. */

const THEMES = ["auto", "light", "dark"];

function applyTheme(name) {
  if (name === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", name);
  $("btnTheme").textContent = name;
  try { localStorage.setItem("shishya.theme", name); } catch { /* private mode */ }
}

applyTheme((() => {
  try { return THEMES.includes(localStorage.getItem("shishya.theme"))
    ? localStorage.getItem("shishya.theme") : "auto"; } catch { return "auto"; }
})());

$("btnTheme").onclick = () => {
  const now = $("btnTheme").textContent.trim().toLowerCase();
  applyTheme(THEMES[(THEMES.indexOf(now) + 1) % THEMES.length]);
};

refresh();
setInterval(refresh, 3000);
log("control panel up — you have the wheel");
