/* ============================================================================
   SHISHYA — control panel

   Week 1 scope: prove the pipeline. Boot the sandbox, see the clone's screen
   in this page, click into it, snapshot and roll back. No agent yet.
   ========================================================================== */

import { api } from "./api.js";

const $ = id => document.getElementById(id);
const VERDICT_CLASS = { allow: "ok", deny: "no", info: "" };

let netLocked = null;      // unknown until the sandbox is asked
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
  btn.textContent = "WORKING…";
  try {
    const out = await fn();
    log(`${label} ✓`, "ok");
    return out;
  } catch (e) {
    log(`${label} ✗ ${e.message}`, "no");
  } finally {
    btn.disabled = false;
    btn.textContent = was;
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
  /* Egress comes from the sandbox's own firewall, not from a variable we set
     when we last pressed the button. An indicator that reports a state it
     never checked is worse than no indicator on a panel whose whole promise
     is that you can verify what happened. */
  const e = s.egress ?? {};
  netLocked = e.locked;
  const pill = $("netState");
  pill.textContent = e.locked === true ? "LOCKED"
                   : e.locked === false ? "OPEN" : "UNKNOWN";
  pill.className = e.locked === true ? "locked" : e.locked === false ? "open" : "no";
  pill.title = e.detail ?? "";
  $("btnNet").textContent = e.locked === true ? "UNLOCK NET" : "LOCK NET";

  const state = s.vm?.state ?? "unknown";
  $("vmState").textContent = state.toUpperCase();
  $("vmState").className = state === "running" ? "ok" : "no";
  $("denyCount").textContent = s.ledger?.denied ?? 0;
  $("denyCount").className = (s.ledger?.denied ?? 0) > 0 ? "no" : "";

  const live = state === "running";
  $("screenMsg").style.display = live ? "none" : "grid";
  $("screenMsg").textContent = live ? "" : `sandbox ${state}`;

  // Three states, not two: unknown is its own answer when the sandbox is down.
  const eg = s.egress ?? {};
  netLocked = eg.locked;
  const label = netLocked === true ? "LOCKED" : netLocked === false ? "OPEN" : "UNKNOWN";
  $("netState").textContent = label;
  $("netState").className = netLocked === true ? "locked" : netLocked === false ? "open" : "";
  $("netState").title = eg.detail ?? "";
  $("btnNet").textContent = netLocked === true ? "UNLOCK NET" : "LOCK NET";
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
   while you were in control it read "HAND IT BACK", which reads as an
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
  b.textContent = on ? "● YOU HAVE CONTROL" : "○ WATCHING ONLY — CLICK TO CONTROL";
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
  if (!confirm("Roll back the sandbox?\n\nEverything the clone has done since the last clean mark is discarded.")) return;
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
  if (done) refresh();
}

$("btnWheel").onclick = () => setWheel(!wheel);
$("btnReload").onclick = () => { $("vnc").src = $("vnc").src; log("reconnecting to clone display"); };

refresh();
setInterval(refresh, 3000);
log("control panel up — you have the wheel");
