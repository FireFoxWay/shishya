/* ============================================================================
   SHISHYA — control panel

   Week 1 scope: prove the pipeline. Boot the sandbox, see the clone's screen
   in this page, click into it, snapshot and roll back. No agent yet.
   ========================================================================== */

import { api } from "./api.js";

const $ = id => document.getElementById(id);
const VERDICT_CLASS = { allow: "ok", deny: "no", info: "" };

let netLocked = true;
let wheel = false;          // are we driving, or just watching?

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
  const state = s.vm?.state ?? "unknown";
  $("vmState").textContent = state.toUpperCase();
  $("vmState").className = state === "running" ? "ok" : "no";
  $("denyCount").textContent = s.ledger?.denied ?? 0;
  $("denyCount").className = (s.ledger?.denied ?? 0) > 0 ? "no" : "";

  const live = state === "running";
  $("screenMsg").style.display = live ? "none" : "grid";
  $("screenMsg").textContent = live ? "" : `sandbox ${state}`;
}

async function refresh() {
  try {
    const [s, l] = await Promise.all([api.status(), api.ledger()]);
    paintStatus(s);
    paintLedger(l.entries);
  } catch (e) {
    $("vmState").textContent = "HOST DOWN";
    $("vmState").className = "no";
  }
}

/* ─── take the wheel ─────────────────────────────────────────────────────── */
/* The VNC session is shared, so handing over control is only a matter of
   dropping view_only — the clone keeps its session either way. */

function setWheel(on) {
  wheel = on;
  const f = $("vnc");
  const url = new URL(f.src);
  url.searchParams.set("view_only", on ? "0" : "1");
  f.src = url.toString();
  $("btnWheel").classList.toggle("on", on);
  $("btnWheel").textContent = on ? "HAND IT BACK" : "TAKE THE WHEEL";
  log(on ? "you have the wheel" : "wheel returned to the clone");
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

$("btnNet").onclick = e => guard(e.target, "egress", async () => {
  const out = await api.egress(!netLocked ? true : false);
  netLocked = out.locked;
  $("netState").textContent = netLocked ? "LOCKED" : "OPEN";
  $("netState").className = netLocked ? "locked" : "open";
  $("btnNet").textContent = netLocked ? "UNLOCK NET" : "LOCK NET";
  return out;
});

$("btnWheel").onclick = () => setWheel(!wheel);
$("btnReload").onclick = () => { $("vnc").src = $("vnc").src; log("reconnecting to clone display"); };

refresh();
setInterval(refresh, 3000);
log("control panel up — week 1: prove the pipeline");
