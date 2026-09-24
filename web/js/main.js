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
    refresh();
  }
}

/* ─── painting ───────────────────────────────────────────────────────────── */

function paintLedger(entries) {
  const el = $("ledger");
  el.textContent = "";
  const head = document.createElement("div");
  head.className = "entry head";
  head.innerHTML = "<span>time</span><span>verdict</span><span>action</span><span>target</span>";
  el.append(head);
  for (const e of entries.slice().reverse()) {
    const row = document.createElement("div");
    row.className = `entry ${VERDICT_CLASS[e.verdict] ?? ""}`;
    /* The time axis is what turns a list into a record. Seconds matter:
       three entries in one minute is a story, and HH:MM alone hides it. */
    const when = e.t ? new Date(e.t * 1000).toTimeString().slice(0, 8) : "";
    row.innerHTML =
      `<span class="tm">${when}</span>` +
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
  $("vmState").textContent =
    state === "unknown" ? "Checking" : state.charAt(0).toUpperCase() + state.slice(1);
  $("vmState").className = state === "running" ? "ok" : "no";
  $("denyCount").textContent = s.ledger?.denied ?? 0;
  $("denyCount").className = (s.ledger?.denied ?? 0) > 0 ? "no" : "";

  /* Say what is true, including "I do not know yet". The panel claimed the
     sandbox was not running while it was running perfectly — the page had
     simply loaded before the first poll returned. On a panel whose whole
     purpose is to report honestly, a confident wrong answer is the worst
     kind. */
  const live = state === "running";
  $("screenMsg").style.display = live ? "none" : "grid";
  $("screenMsg").textContent =
    live ? "" :
    state === "unknown" ? "connecting to the sandbox" :
    state === "no-wsl" ? "WSL is not installed — run windows\\setup.ps1" :
    state === "absent" ? "no sandbox yet — in PowerShell, run: shishya create" :
    state === "wsl-busy" ? "WSL is not answering — wsl --update, wsl --shutdown, or restart Windows" :
    `sandbox ${state}`;

}

async function refresh() {
  try {
    const [s, l, box, lessons] = await Promise.all(
      [api.status(), api.ledger(), api.inbox(), api.lessons()]);
    paintStatus(s);
    paintLedger(l.entries);
    paintLessons(lessons.lessons);
    paintSchedules();
    api.alerts().then(paintAlerts).catch(() => {});
    paintAsks();
    paintTasks();
    paintVault();
    if (!$("takeList").dataset.ready) {
      $("takeList").dataset.ready = "1";
      paintTake("work", "");
    }
    const n = box.waiting.length;
    $("inboxCount").textContent = n ? `${n} waiting` : "empty";
    // Only when it is the visible half of the pane. Assembling the dashboard
    // reads the books and the catalogue, and doing that every three seconds
    // for a view nobody has open is the same mistake the wallpaper was.
    if (!$("board").hidden) paintBoard();
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
  if (done) refresh();
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

/* ─── to do ──────────────────────────────────────────────────────────────── */
/* Alerts say what is wrong now and vanish when it stops being true. That is
   right for "you are out of stock" and wrong for "order more" — which stays
   true until somebody does it. This is where the work goes. */

async function paintTasks() {
  const box = $("tasks");
  let out;
  try { out = await api.tasks(); } catch { return; }
  $("taskCount").textContent = out.counts.open
    ? `${out.counts.open} open` : "nothing open";
  box.className = "answer";
  box.textContent = "";
  if (!out.tasks.length) {
    box.textContent = "Nothing on the list. Alerts can raise their own.";
    return;
  }
  for (const t of out.tasks) {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:8px;align-items:baseline;margin-top:4px";
    const tick = document.createElement("button");
    tick.className = "tool ghost";
    tick.textContent = "Done";
    tick.onclick = async () => {
      try { await api.taskState(t.id, "done"); } catch (e) { log(e.message, "no"); }
      paintTasks();
    };
    const what = document.createElement("span");
    what.style.flex = "1";
    what.textContent = t.what;             // textContent: raised from shop data
    if (t.why) what.title = t.why;
    const from = document.createElement("span");
    from.style.opacity = ".55";
    from.textContent = t.source;
    row.append(tick, what, from);
    box.append(row);
  }
}

async function addTask() {
  const what = $("taskBox").value.trim();
  if (!what) return;
  $("taskBox").value = "";
  try { await api.addTask(what); log("task added", "ok"); }
  catch (e) { log(`task ✗ ${e.message}`, "no"); }
  paintTasks();
}

$("taskBox").addEventListener("keydown", e => { if (e.key === "Enter") addTask(); });
$("btnTaskAlerts").onclick = e => guard(e.target, "tasks from alerts", async () => {
  const out = await api.tasksFromAlerts();
  log(out.raised ? `${out.raised} task(s) raised from alerts`
                 : "alerts raised nothing new", "ok");
  paintTasks();
  return out;
});

/* ─── secrets ────────────────────────────────────────────────────────────── */
/* The panel shows that a secret exists and how long it is. There is no route
   that returns a value — not hidden in the page, not fetched on demand. The
   store sits outside every mount, so the sandbox cannot read it either, and
   demo.py check proves both on every run. */

async function paintVault() {
  const box = $("vaultList");
  let out;
  try { out = await api.secrets(); } catch { return; }
  $("vaultWhere").textContent = out.private ? "private to you" : "PERMISSIONS WRONG";
  box.className = "answer";
  box.textContent = "";

  if (out.leaked?.length) {
    const bad = document.createElement("div");
    bad.textContent = `A secret's value appears in shared/: ${out.leaked.join(", ")}`;
    box.append(bad);
  }
  if (!out.secrets.length) {
    box.append(document.createTextNode(
      "Nothing kept. Anything put here stays on this computer — the sandbox has no path to it."));
    return;
  }
  for (const sec of out.secrets) {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:8px;align-items:baseline;margin-top:3px";
    const name = document.createElement("span");
    name.textContent = sec.name;            // the name is not the secret
    const len = document.createElement("span");
    len.style.opacity = ".6";
    len.textContent = `${sec.length} characters`;
    const drop = document.createElement("button");
    drop.className = "tool ghost";
    drop.textContent = "Forget";
    drop.onclick = async () => {
      try { await api.forgetSecret(sec.name); log(`forgot ${sec.name}`, "no"); }
      catch (e) { log(`forget ✗ ${e.message}`, "no"); }
      paintVault(); refresh();
    };
    row.append(name, len, drop);
    box.append(row);
  }
}

$("btnSecret").onclick = async () => {
  const name = $("secretName").value.trim();
  const value = $("secretValue").value;
  if (!name || !value) return;
  try {
    await api.setSecret(name, value);
    log(`kept ${name}`, "ok");
    $("secretName").value = "";
    $("secretValue").value = "";   // cleared at once; never left on a screen
  } catch (e) { log(`secret ✗ ${e.message}`, "no"); }
  paintVault();
};

/* ─── what is waiting for a person ───────────────────────────────────────── */
/* A clerk asks, the head decides here. Approving records the decision; the
   app that asked performs the action and marks it done. Kept apart on
   purpose — a decision that half-performed something would leave the books
   in a state nobody asked for. */

async function paintAsks() {
  const box = $("asks");
  let out;
  try { out = await api.approvals(); } catch { return; }
  const waiting = out.pending ?? [];
  $("askCount").textContent = waiting.length
    ? `${waiting.length} waiting` : "nothing waiting";
  box.className = "answer";
  box.textContent = "";

  if (!waiting.length) {
    box.textContent = out.role === "head"
      ? "Nothing is waiting for a decision."
      : "Requests you raise appear here for the head.";
    return;
  }
  for (const r of waiting) {
    const row = document.createElement("div");
    row.style.marginBottom = "8px";
    const what = document.createElement("div");
    // textContent: the detail names a bill and a customer the clone chose.
    what.textContent = r.detail || `${r.what} ${r.target ?? ""}`;
    const when = document.createElement("div");
    when.style.opacity = ".65";
    when.textContent = `asked by the ${r.by} · ${new Date(r.at * 1000).toLocaleTimeString()}`;
    row.append(what, when);

    if (out.role === "head") {
      const buttons = document.createElement("div");
      buttons.style.cssText = "display:flex;gap:6px;margin-top:5px";
      for (const [label, yes, cls] of [["Approve", true, "tool"],
                                       ["Refuse", false, "tool ghost"]]) {
        const b = document.createElement("button");
        b.className = cls;
        b.textContent = label;
        b.onclick = async () => {
          b.disabled = true;
          try {
            await api.decide(r.id, yes, "");
            log(`${yes ? "approved" : "refused"} ${r.what} ${r.target ?? ""}`,
                yes ? "ok" : "no");
          } catch (e) { log(`decision ✗ ${e.message}`, "no"); }
          paintAsks();
          refresh();
        };
        buttons.append(b);
      }
      row.append(buttons);
    } else {
      const note = document.createElement("div");
      note.style.opacity = ".65";
      note.textContent = "waiting for the head";
      row.append(note);
    }
    box.append(row);
  }
}

/* ─── taking things back off the clone ───────────────────────────────────── */
/* Dropping a file on the panel puts it in; this takes it out. A folder at a
   time, with a download for each file — the browser then saves it wherever
   the person actually keeps things, which is the part the shared mount
   cannot do for them. Every file taken is logged as file.out. */

let takeWhere = "work";

async function paintTake(where = takeWhere, at = "") {
  takeWhere = where;
  const box = $("takeList");
  try {
    const out = await api.takeList(where, at);
    $("takeWhere").textContent = out.what;
    box.className = "answer";
    box.textContent = "";

    if (out.up !== null && out.up !== undefined) {
      const up = document.createElement("a");
      up.href = "#";
      up.textContent = "↑ up";
      up.onclick = e => { e.preventDefault(); paintTake(where, out.up === "." ? "" : out.up); };
      box.append(up, document.createElement("br"));
    }
    if (!out.items.length) {
      box.append(document.createTextNode("Nothing here yet."));
      return;
    }
    for (const item of out.items) {
      const row = document.createElement("div");
      row.style.marginTop = "3px";
      if (item.dir) {
        const a = document.createElement("a");
        a.href = "#";
        a.textContent = `▸ ${item.name}`;   // textContent: the clone named it
        a.onclick = e => { e.preventDefault(); paintTake(where, item.path); };
        row.append(a);
      } else {
        const a = document.createElement("a");
        a.href = api.takeUrl(where, item.path);
        a.setAttribute("download", item.name);
        a.textContent = `↓ ${item.name}`;
        row.append(a);
        const size = document.createElement("span");
        size.style.opacity = ".6";
        size.textContent = `  ${Math.max(1, Math.round(item.bytes / 1024))} kB · ${item.at}`;
        row.append(size);
      }
      box.append(row);
    }
  } catch (e) {
    box.className = "answer";
    box.textContent = `Couldn't read that: ${e.message}`;
  }
}

for (const btn of document.querySelectorAll("[data-take]")) {
  btn.onclick = () => paintTake(btn.dataset.take, "");
}

/* ─── jobs ───────────────────────────────────────────────────────────────── */
/* Files in, one line of intent, files out. The worker writes its state into
   the job folder and this only reads it — same rule as the egress pill:
   report what is measured, never what was asked for. */

let jobPoll = null;

function paintJob(p) {
  const out = $("jobOut");
  out.className = "answer" + (p.state === "working" || p.state === "starting" ? " waiting" : "");
  out.textContent = "";

  const head = document.createElement("div");
  head.textContent = `${p.step ?? p.state}` + (p.brief ? ` — ${p.brief}` : "");
  out.append(head);

  if (p.said) {
    const said = document.createElement("div");
    said.style.marginTop = "8px";
    said.textContent = p.said;
    out.append(said);
  }
  for (const name of p.produced ?? []) {
    const row = document.createElement("div");
    row.style.marginTop = "6px";
    const a = document.createElement("a");
    a.href = api.jobFileUrl(p.job, name);
    a.textContent = `↓ ${name}`;      // textContent: the clone named this file
    row.append(a);
    out.append(row);
  }
  if (p.error) {
    const err = document.createElement("div");
    err.style.marginTop = "8px";
    err.textContent = p.error;
    out.append(err);
  }
}

function watchJob() {
  clearInterval(jobPoll);
  jobPoll = setInterval(async () => {
    let p;
    try { p = await api.jobProgress(); } catch { return; }
    paintJob(p);
    if (p.state === "done" || p.state === "failed") {
      clearInterval(jobPoll);
      jobPoll = null;
      log(p.state === "done" ? `job done — ${(p.files ?? []).length} file(s)`
                             : `job failed — ${p.step}`,
          p.state === "done" ? "ok" : "no");
      refresh();          // the ledger now has the finish in it
    }
  }, 2500);
}

async function giveJob() {
  const brief = $("jobBox").value.trim();
  if (!brief) return;
  $("jobBox").value = "";
  const out = $("jobOut");
  out.className = "answer waiting";
  out.textContent = "Handing the files over…";
  try {
    const started = await api.job(brief);
    log(`job started — ${started.files.length} file(s) handed over`, "ok");
    watchJob();
  } catch (e) {
    out.className = "answer";
    out.textContent = `Couldn't start it: ${e.message}`;
  }
}

$("btnJob").onclick = giveJob;

$("btnReport").onclick = async e => {
  const out = $("jobOut");
  out.className = "answer waiting";
  out.textContent = "Handing the files over for a report…";
  try {
    const started = await api.report($("jobBox").value.trim());
    log(`report started — ${started.files.length} file(s) handed over`, "ok");
    watchJob();
  } catch (err) {
    out.className = "answer";
    out.textContent = `Couldn't start it: ${err.message}`;
  }
};
$("jobBox").addEventListener("keydown", e => { if (e.key === "Enter") giveJob(); });

/* ─── who is at the counter ──────────────────────────────────────────────── */
/* The head sees everything; the clerk sees the ordinary work. Enforced in
   the panel and again in the Billing app, and it is deliberately NOT called
   a permission: the sandbox is the boundary, this is about not offering a
   control that could only ever be a mistake at a till. */

const HEAD_ONLY = ["btnRoll", "btnNet", "btnBrowse", "btnSnap", "btnStop",
                   "btnCreate", "btnRun", "termIn", "btnPlan", "btnRunLesson",
                   "btnStopLesson"];
let role = "clerk";

function paintRole(who) {
  role = who || "clerk";
  $("roleNote").textContent = `working as ${role}`;
  $("btnRole").textContent = role === "head" ? "Hand over to a clerk"
                                             : "Take over as head";
  for (const id of HEAD_ONLY) {
    const el = $(id);
    if (!el) continue;
    el.disabled = role !== "head";
    el.title = role === "head" ? "" : "The head does this, not the counter";
  }
}

$("btnRole").onclick = e => guard(e.target, "role", async () => {
  const out = await api.setRole(role === "head" ? "clerk" : "head");
  paintRole(out.role);
  log(`working as ${out.role}`, "ok");
  return out;
});

/* ─── what needs attention ───────────────────────────────────────────────── */
/* Reaches you rather than waiting to be asked — but never interrupts. The
   clone's screen may be in front of an audience mid-sentence, and a popup
   that steals attention is one that gets switched off. */

function paintAlerts(payload) {
  const found = payload?.alerts ?? [];
  const box = $("alerts");
  box.className = "answer";
  box.textContent = "";
  $("alertAge").textContent = payload?.at
    ? `checked ${new Date(payload.at * 1000).toLocaleTimeString()}`
    : "not checked yet";
  if (!found.length) {
    box.textContent = payload?.at ? "Nothing needs attention."
                                  : "Nothing checked yet — schedule an alert check in Reports.";
    return;
  }
  for (const a of found) {
    const row = document.createElement("div");
    row.style.marginBottom = "6px";
    const what = document.createElement("div");
    what.textContent = a.what;              // textContent: the shop's own data
    const doing = document.createElement("div");
    doing.style.opacity = ".7";
    doing.textContent = a.do;
    row.append(what, doing);
    box.append(row);
  }
}

$("btnBackup").onclick = async () => {
  const out = $("jobOut");
  out.className = "answer waiting";
  out.textContent = "Copying the books…";
  try {
    await api.backup();
    log("books backup started", "ok");
    watchJob();
  } catch (err) {
    out.className = "answer";
    out.textContent = `Couldn't start it: ${err.message}`;
  }
};

$("btnAudit").onclick = async () => {
  const out = $("jobOut");
  out.className = "answer waiting";
  out.textContent = "Auditing the shop's books…";
  try {
    await api.audit();
    log("shop audit started", "ok");
    watchJob();
  } catch (err) {
    out.className = "answer";
    out.textContent = `Couldn't start it: ${err.message}`;
  }
};

/* What will happen without anybody here. The panel is where you check that
   a schedule is real — the Reports app sets it, this proves it took. */
async function paintSchedules() {
  try {
    const { schedules, role: who } = await api.schedules();
    if (who && who !== role) paintRole(who);
    const live = (schedules ?? []).filter(s => s.enabled !== false);
    $("schedNote").textContent = live.length
      ? "Runs by itself: " + live.map(s =>
          `${s.label} every ${s.days === "weekdays" ? "weekday" : "day"} at ${s.at}`
        ).join(" · ")
      : "Nothing is scheduled — set it in the Reports app.";
  } catch { /* the panel says nothing rather than something wrong */ }
}

$("btnTally").onclick = async () => {
  const out = $("jobOut");
  out.className = "answer waiting";
  out.textContent = "Handing the files over for Tally vouchers…";
  try {
    const started = await api.tally();
    log(`tally started — ${started.files.length} file(s) handed over`, "ok");
    watchJob();
  } catch (err) {
    out.className = "answer";
    out.textContent = `Couldn't start it: ${err.message}`;
  }
};

/* ─── lessons ────────────────────────────────────────────────────────────── */
/* The panel decides, the sandbox performs. Same reason as every other control
   on this side: the path never touches the display, so it keeps working on the
   evenings when clicking inside the clone does not.

   Plan before Run, always. The executor performs what it recognises and
   refuses the rest, and eight of seventeen is a number a judge should read
   before anything types into a real spreadsheet, not after. */

let lessonSig = "";      // rebuild the picker only when the list really changes
let lessonPoll = null;

function paintLessons(lessons) {
  $("lessonNote").textContent = lessons.length ? `${lessons.length} learned`
                                               : "none learned yet";
  $("btnPlan").disabled = $("btnRunLesson").disabled = !lessons.length;

  const sig = lessons.map(l => `${l.id}:${l.steps}:${l.taught}`).join("|");
  if (sig === lessonSig) return;   // never rebuild the list under a selection
  lessonSig = sig;

  const pick = $("lessonPick");
  const chosen = pick.value;
  pick.textContent = "";
  for (const l of lessons) {
    const o = document.createElement("option");
    o.value = l.id;
    /* textContent, like the ledger's targets: a lesson is titled by a model
       reading the clone's screen, and that is not our text to trust. */
    o.textContent = `${l.title} — ${l.steps} steps · ${l.taught}` +
                    (l.edited ? " · edited" : "");
    pick.append(o);
  }
  if (chosen && lessons.some(l => l.id === chosen)) pick.value = chosen;
}

/* `mark` is "did", "skip" or "cannot". Three weights, not two: on a real
   recording most steps are skipped noise, and inverting nine of seventeen
   rows makes a healthy run look like a disaster. Inversion is the strongest
   signal this palette has, so it is kept for the step that stopped the work. */
function stepRow(n, mark, summary, why) {
  const row = document.createElement("div");
  row.className = `step ${mark}`;
  const num = document.createElement("span");
  num.className = "n";
  num.textContent = n;
  const what = document.createElement("span");
  what.className = "s";
  what.textContent = summary;
  if (why) row.title = why;
  row.append(num, what);
  return row;
}

function paintLesson(head, rows) {
  const out = $("lessonOut");
  out.className = "answer plan";
  out.textContent = "";
  const h = document.createElement("div");
  h.className = "planHead";
  h.textContent = head;
  out.append(h, ...rows);
}

function describe(s) {
  if (!s.can) return "will not attempt this one";
  const cell = s.do === "type" && s.cell ? ` → ${s.cell}` : "";
  return `${s.do} ${s.what ?? ""}${cell}`;
}

$("btnPlan").onclick = e => guard(e.target, "plan lesson", async () => {
  const plan = await api.lessonPlan($("lessonPick").value);
  paintLesson(`${plan.title} · ${plan.doable} of ${plan.total} steps performable`,
              plan.steps.map(s => stepRow(s.n, s.can ? "did" : "cannot",
                                          describe(s), s.text)));
  return plan;
});

$("btnRunLesson").onclick = async () => {
  const id = $("lessonPick").value;
  if (!id) return;
  /* Name what it will do to what. This types into whatever is open on the
     clone's desktop, and the one destructive control on this panel already
     taught us that a button which does not say what it touches is a button
     somebody presses once and regrets. */
  const label = $("lessonPick").selectedOptions[0]?.textContent ?? id;
  if (!confirm(`Let the clone perform this lesson?\n\n${label}\n\n` +
               `It types into whatever is open on the clone's screen — open the ` +
               `spreadsheet first.\n\nStop halts it mid-procedure. Roll back ` +
               `undoes the lot.`)) return;
  try {
    const out = await api.lessonRun(id);
    log(`running ${out.plan?.title ?? id} — ${out.plan?.doable}/${out.plan?.total} performable`, "ok");
    watchLesson();
  } catch (e) {
    log(`run ✗ ${e.message}`, "no");
  }
};

$("btnStopLesson").onclick = e => guard(e.target, "stop lesson", async () => {
  const out = await api.lessonStop();
  log(out.detail, out.stopped ? "no" : "");
  return out;
});

const OUTCOME = { skipped: "skip", halted: "cannot", error: "cannot",
                  ask: "cannot", taught: "did" };

let progressSig = "";

function paintProgress(p) {
  /* Repaint only when the run moved. The poll fires every 1500ms and a
     rebuild replaces the answer box — taking the person's half-typed
     instruction with it. */
  const sig = `${p.state}:${p.events.length}`;
  if (sig === progressSig) return;
  progressSig = sig;
  const start = p.events.find(e => e.kind === "start");
  const done = p.events.filter(e => e.kind === "step" && e.ok).length;
  const skipped = p.events.filter(e => e.kind === "skipped").length;
  const total = start?.total ?? p.events.length;
  /* Say both numbers. "8 of 17" alone reads as nine failures; the nine are
     recorder noise it declined to guess at, and that is not the same news. */
  paintLesson(`${p.state === "running" ? "Running" : "Finished"} · ${p.title} · ` +
              `${done} of ${total} performed, ${skipped} skipped`,
              p.events.filter(e => e.kind !== "start" && e.kind !== "done")
                      .map(e => stepRow(e.n ?? "!",
                                        OUTCOME[e.kind] ?? (e.ok ? "did" : "cannot"),
                                        e.message ?? "", e.text)));

  /* The apprentice's question. The newest event being an unanswered ask,
     while the run still lives, means the clone is standing there waiting —
     the answer box goes where the eye already is, under the step list. */
  const last = p.events[p.events.length - 1];
  if (p.state === "running" && last?.kind === "ask") {
    const out = $("lessonOut");
    const q = document.createElement("div");
    q.style.marginTop = "10px";
    q.textContent = `It is asking about step ${last.n}: ${last.text}`;
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:6px;margin-top:6px";
    const box = document.createElement("input");
    box.placeholder = "Say it in words it knows — type 'X' into cell Y";
    box.style.cssText = "flex:1;font:inherit;background:transparent;" +
                        "border:0;border-bottom:1px solid currentColor;color:inherit";
    const tell = document.createElement("button");
    tell.textContent = "Tell it";
    tell.className = "tool";
    tell.onclick = async () => {
      if (!box.value.trim()) return;
      try { await api.lessonAnswer(last.n, box.value.trim(), false); }
      catch (e) { log(`answer ✗ ${e.message}`, "no"); }
    };
    const skip = document.createElement("button");
    skip.textContent = "Skip it";
    skip.className = "tool ghost";
    skip.onclick = async () => {
      try { await api.lessonAnswer(last.n, "", true); }
      catch (e) { log(`skip ✗ ${e.message}`, "no"); }
    };
    box.addEventListener("keydown", e => { if (e.key === "Enter") tell.onclick(); });
    row.append(box, tell, skip);
    out.append(q, row);
    box.focus();
  }
}

/* Faster than the status poll: this is the one thing on the panel you might
   need to stop, and each step is a second or two. */
function watchLesson() {
  clearInterval(lessonPoll);
  lessonPoll = setInterval(async () => {
    let p;
    try { p = await api.progress(); } catch { return; }
    paintProgress(p);
    if (p.state !== "running") {
      clearInterval(lessonPoll);
      lessonPoll = null;
      refresh();          // the ledger now has every step in it
    }
  }, 1500);
}

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

/* ─── the poll ───────────────────────────────────────────────────────────── */
/* Every tick is ten HTTP calls out here and an ssh session into the sandbox
   at the other end, and it runs for as long as this page is open. On a
   window nobody is looking at that is mostly cost: the sandbox spends cores
   answering questions about itself instead of drawing the screen somebody
   may be watching in another window.

   Slower when hidden, not stopped. Stopping was the first version of this and
   it was wrong: "hidden" is also true of a panel on a second monitor behind
   another window, and a panel that quietly freezes on numbers from ten
   minutes ago is worse than one that costs something. It keeps telling the
   truth, just less often — and the moment you look at it again it refreshes
   before the next tick, so coming back never shows you a stale reading. */
const POLL_WATCHED = 3000;
const POLL_HIDDEN = 30000;
let poll = null;
let pollEvery = 0;

function polling(every) {
  if (every === pollEvery) return;
  pollEvery = every;
  if (poll !== null) clearInterval(poll);
  poll = setInterval(refresh, every);
}

document.addEventListener("visibilitychange", () => {
  const seen = document.visibilityState === "visible";
  polling(seen ? POLL_WATCHED : POLL_HIDDEN);
  if (seen) refresh();          // never greet you with the last stale reading
});

refresh();
polling(document.visibilityState === "visible" ? POLL_WATCHED : POLL_HIDDEN);

/* A reload must not lose the run — it lives on the host, not in this page.
   Paint whatever the last run was, finished or not, and only start polling
   again if it is still going. Reloading the panel after a procedure ended
   used to leave an empty pane, which reads as "nothing ever happened". */
api.progress().then(p => {
  if (!p.events?.length) return;
  paintProgress(p);
  if (p.state === "running") watchLesson();
}).catch(() => {});
api.jobProgress().then(p => {
  if (p.state === "none") return;
  paintJob(p);
  if (p.state === "working" || p.state === "starting") watchJob();
}).catch(() => {});
log("control panel up — you have the wheel");

/* ─── the dashboard ────────────────────────────────────────────────────────
   The overview screen. Everything on it already existed and was scattered
   across Billing, Reports, Alerts and this panel's own right-hand column;
   what was missing was somewhere to see it at once.

   Which cards appear is decided by the profession on the host, not here — a
   shopkeeper opens onto takings and stock, someone managing their own money
   opens onto what is owed. Drawing is generic; the choosing is not this
   file's business.

   Charts are inline SVG. A library would be the only build step in the
   project and the only dependency that has to resolve at a demo table, to
   draw one line and one ring. */

const money = n => "₹" + Number(n || 0).toLocaleString("en-IN",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

function card(title, big) {
  const c = el("div", "card");
  const h = el("h2");
  h.append(el("span", null, title));
  if (big !== undefined) h.append(el("b", null, big));
  c.append(h);
  return c;
}

/* A line, its area, and a dot on the last point. Written against the box the
   card actually gives it rather than a fixed size, so it stays a chart when
   the pane is narrow instead of overflowing it. */
function sparkline(points) {
  const W = 320, H = 92, pad = 6;
  const vals = points.map(p => p.amount);
  const top = Math.max(...vals, 1);
  const x = i => pad + (i * (W - pad * 2)) / Math.max(points.length - 1, 1);
  const y = v => H - pad - (v / top) * (H - pad * 2);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.amount).toFixed(1)}`).join("");

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "spark");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "none");
  const add = (name, attrs) => {
    const n = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    svg.append(n);
    return n;
  };
  add("path", { class: "area", d: `${line}L${x(points.length - 1)},${H - pad}L${x(0)},${H - pad}Z` });
  add("line", { class: "base", x1: pad, y1: H - pad, x2: W - pad, y2: H - pad });
  add("path", { class: "line", d: line });
  const last = points[points.length - 1];
  if (last) add("circle", { class: "dot", cx: x(points.length - 1), cy: y(last.amount), r: 2.6 });
  return svg;
}

/* A ring rather than a pie: the slices are drawn as dashes around one circle,
   which needs no arc maths and cannot produce a malformed path when a slice
   rounds to zero. Shade rather than colour, for the same reason as the CSS. */
function donut(slices, total) {
  const R = 46, C = 2 * Math.PI * R;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "ring");
  svg.setAttribute("viewBox", "0 0 120 120");
  let at = 0;
  slices.forEach((s, i) => {
    const frac = total ? s.amount / total : 0;
    const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    c.setAttribute("cx", 60); c.setAttribute("cy", 60); c.setAttribute("r", R);
    c.setAttribute("stroke", "var(--ink)");
    c.setAttribute("stroke-opacity", (1 - i * 0.13).toFixed(2));
    c.setAttribute("stroke-dasharray", `${(frac * C).toFixed(2)} ${C.toFixed(2)}`);
    c.setAttribute("stroke-dashoffset", (-at * C).toFixed(2));
    c.setAttribute("transform", "rotate(-90 60 60)");
    svg.append(c);
    at += frac;
  });
  return svg;
}

const DRAW = {
  sales(d) {
    const c = card(`Sales · last ${d.days} days`, money(d.total));
    c.classList.add("wide");
    if (!d.points?.length) { c.append(el("p", "none", "No sales recorded yet.")); return c; }
    c.append(sparkline(d.points));
    const f = el("div", "fig");
    f.append(el("span", null, "Today"), el("b", null, money(d.today)));
    c.append(f);
    return c;
  },

  /* "Add-ons card = all the commitments you have (loans, EMIs,
     subscriptions)." Most people can name three of theirs; the total is
     what is worth drawing, and it is nearly always bigger than the guess. */
  addons(d) {
    const c = card("Add-ons · every month", money(d.total));
    if (!d.slices?.length) {
      c.append(el("p", "none", "Nothing recorded. Add loans, EMIs and " +
                               "subscriptions in Banking."));
      return c;
    }
    const wrap = el("div", "donut");
    wrap.append(donut(d.slices, d.total));
    const keys = el("div", "keys");
    d.slices.forEach((s, i) => {
      const k = el("div", "key");
      const swatch = el("i");
      swatch.style.opacity = (1 - i * 0.13).toFixed(2);
      k.append(swatch, el("span", null, s.name), el("b", null, money(s.amount)));
      keys.append(k);
    });
    wrap.append(keys);
    c.append(wrap);
    (d.due || []).forEach(r => {
      const f = el("div", "fig warn");
      f.append(el("span", null, `${r.what} · in ${r.in_days}d`),
               el("b", null, money(r.amount)));
      c.append(f);
    });
    return c;
  },

  metrics(d) {
    const c = card("Top metrics");
    (d.rows || []).forEach(r => {
      const f = el("div", "fig");
      const v = r.money ? money(r.value) : `${r.value}${r.suffix || ""}`;
      f.append(el("span", null, r.label), el("b", null, v));
      c.append(f);
    });
    return c;
  },

  stock(d) {
    const c = card("Running out", d.count ?? 0);
    if (!d.rows?.length) { c.append(el("p", "none", "Nothing below its reorder point.")); return c; }
    d.rows.forEach(r => {
      const f = el("div", "fig warn");
      f.append(el("span", null, r.name), el("b", null, `${r.stock} / ${r.reorder}`));
      c.append(f);
    });
    return c;
  },

  /* "Shows all the commitments you have" — the arrow in the sketch. Most
     people can name three and are surprised by the total, which is the
     entire reason this card is worth drawing. */
  commitments(d) {
    const c = card("Commitments · every month", money(d.monthly));
    const p = d.position || {};
    [["Have", p.have], ["Owe", p.owe], ["Net", p.net]].forEach(([label, v]) => {
      if (v === undefined) return;
      const f = el("div", "fig");
      f.append(el("span", null, label), el("b", null, money(v)));
      c.append(f);
    });
    if (d.due?.length) {
      c.append(el("p", "note", "Due within the week"));
      d.due.forEach(r => {
        const f = el("div", "fig warn");
        f.append(el("span", null, `${r.what} · in ${r.in_days}d`),
                 el("b", null, money(r.amount)));
        c.append(f);
      });
    } else {
      c.append(el("p", "none", "Nothing due in the next seven days."));
    }
    return c;
  },

  credit(d) {
    const c = card("Credit standing",
                   d.utilisation === null || d.utilisation === undefined
                     ? "—" : `${d.utilisation}%`);
    if (!d.standing?.length) { c.append(el("p", "none", "Add an account to see this.")); return c; }
    d.standing.forEach(n => c.append(el("p", `note ${n.level}`, n.text)));
    c.append(el("p", "note", "What it is made of:"));
    (d.factors || []).forEach(f => {
      const row = el("div", "fig");
      row.append(el("span", null, f.name), el("b", null, `${f.weight}%`));
      c.append(row);
    });
    return c;
  },

  waiting(d) {
    const c = card("Waiting on you", (d.tasks || 0) + (d.approvals || 0));
    [["To do", d.tasks], ["Approvals", d.approvals]].forEach(([label, v]) => {
      const f = el("div", "fig");
      f.append(el("span", null, label), el("b", null, v ?? 0));
      c.append(f);
    });
    return c;
  },

  shell(d) {
    const c = card("Shell");
    c.append(el("p", "note", d.hint || ""));
    return c;
  },
};

async function paintBoard() {
  let d;
  try { d = await api.dashboard(); }
  catch (e) { $("cards").replaceChildren(el("p", "none", `Dashboard unavailable — ${e.message}`)); return; }

  $("hello").textContent = d.greeting;

  const pick = $("profession");
  if (pick.options.length !== d.professions.length) {
    pick.replaceChildren(...d.professions.map(p => new Option(p, p)));
  }
  pick.value = d.profile.profession;

  const box = $("cards");
  box.replaceChildren();
  for (const name of d.cards) {
    const data = d.data[name] || {};
    const draw = DRAW[name];
    if (!draw) continue;
    if (data.error) {
      // One card that cannot be drawn must not take the dashboard with it.
      const c = card(d.titles[name] || name);
      c.append(el("p", "none", data.error));
      box.append(c);
      continue;
    }
    try { box.append(draw(data)); }
    catch (e) { const c = card(name); c.append(el("p", "none", e.message)); box.append(c); }
  }
}

$("profession").onchange = async e => {
  await api.setProfile({ profession: e.target.value });
  log(`dashboard is now a ${e.target.value}'s`);
  paintBoard();
};

/* ─── the rail ─────────────────────────────────────────────────────────────
   Six screens, one showing. The VNC iframe keeps its connection while hidden
   and so does everything else here — tearing a screen down and rebuilding it
   on every press would mean the shell losing its scrollback and the SSH pane
   losing which host was selected, every time somebody glanced at the numbers. */

const SCREENS = [
  ["s-board", "01", "Dashboard", paintBoard],
  ["s-shell", "02", "Terminal",  null],
  ["s-ssh",   "03", "SSH",       paintHosts],
  ["s-bank",  "04", "Banking",   paintBank],
  ["s-csma",  "05", "CSMA",      paintCsma],
  ["s-you",   "06", "You",       paintYou],
];
let screenNow = "s-board";

function buildRail() {
  const rail = $("rail");
  rail.replaceChildren();
  SCREENS.forEach(([id, num, label], i) => {
    if (i === SCREENS.length - 1) rail.append(el("div", "spacer"));
    const b = el("button", null, num);
    b.title = label;
    b.setAttribute("aria-label", label);
    b.onclick = () => showScreen(id);
    b.dataset.for = id;
    rail.append(b);
  });
}

/* Buttons carry their target in a data attribute rather than being found by
   position — the rail has a spacer in it, so counting children reached the
   wrong screen. */
function railButton(id) {
  return $("rail").querySelector(`button[data-for="${id}"]`);
}

function showScreen(id) {
  screenNow = id;
  for (const [sid, , , paint] of SCREENS) {
    const on = sid === id;
    $(sid).hidden = !on;
    if (on && paint) paint();
  }
  for (const b of $("rail").querySelectorAll("button[data-for]"))
    b.classList.toggle("on", b.dataset.for === id);
}

/* Two views of the pane: the clone's screen, and the apps. */
function showBoard(on) {
  $("board").hidden = !on;
  document.querySelector(".screen").hidden = on;
  $("tabBoard").classList.toggle("on", on);
  $("tabScreen").classList.toggle("on", !on);
  $("btnWheel").hidden = on;
  $("btnReload").hidden = on;
  if (on) showScreen(screenNow);
}

$("tabBoard").onclick = () => showBoard(true);
$("tabScreen").onclick = () => showBoard(false);

/* ─── 02 · shell ───────────────────────────────────────────────────────────
   The host end has no pty, so this is not a terminal and does not pretend to
   be one: no interactive programs, and no `cd` that survives to the next
   command. Saying so in the pane beats letting somebody discover it by
   typing `cd` and watching nothing happen. */

const HINTS = ["ls ~/shared/work", "df -h", "free -m", "ps -eo pcpu,comm --sort=-pcpu | head",
               "cat ~/shared/billing/shop.txt", "uptime"];

function termLine(box, text, cls) {
  const n = el(cls || "span", null, text + "\n");
  box.append(n);
  box.scrollTop = box.scrollHeight;
}

async function runShell(cmd) {
  const box = $("shellOut");
  termLine(box, "$ " + cmd, "b");
  try {
    const r = await api.shell(cmd);
    if (r.out) termLine(box, r.out);
    if (r.err) termLine(box, r.err, "i");
    if (!r.out && !r.err) termLine(box, `(no output, exit ${r.code})`, "i");
  } catch (e) { termLine(box, e.message, "i"); }
}

$("shellForm").onsubmit = e => {
  e.preventDefault();
  const cmd = $("shellIn").value.trim();
  if (!cmd) return;
  $("shellIn").value = "";
  runShell(cmd);
};

(function seedShell() {
  const box = $("shellOut");
  termLine(box, "Runs inside the sandbox as the clone — no sudo, no network.", "i");
  termLine(box, "No pty, so no interactive programs and no cd that survives.", "i");
  const hints = $("shellHints");
  HINTS.forEach(h => {
    const b = el("button", null, h);
    b.onclick = () => runShell(h);
    hints.append(b);
  });
})();

/* ─── 03 · ssh ─────────────────────────────────────────────────────────────
   The sandbox has no network. Reaching a host means opening port 22 in the
   egress lock, which is a deliberate decision and is logged as one — so the
   button says Allow rather than Connect, and says what it is allowing. */

let hostRows = [], hostPick = null, sshAllowed = false;

async function paintHosts() {
  let d;
  try { d = await api.hosts(); } catch (e) { return; }
  hostRows = d.hosts || [];
  sshAllowed = !!d.ssh;
  $("sshState").textContent = d.detail || "";
  $("btnSshMode").textContent = sshAllowed ? "Block again" : "Allow";
  $("btnSshMode").classList.toggle("on", sshAllowed);

  const list = $("hostList");
  list.replaceChildren();
  if (!hostRows.length) list.append(el("p", "none", "No hosts saved."));
  hostRows.forEach(h => {
    const b = el("button", "host");
    b.append(el("span", null, h.name));
    b.append(el("small", null, `${h.user ? h.user + "@" : ""}${h.host}:${h.port}`));
    b.classList.toggle("on", hostPick === h.name);
    b.onclick = () => { hostPick = h.name; paintHosts(); };
    list.append(b);
  });
}

$("btnSshMode").onclick = async () => {
  const want = !sshAllowed;
  if (want && !confirm(
      "Allow the sandbox to open SSH connections?\n\n" +
      "It will then be able to reach a machine you own, and through it " +
      "whatever that machine can reach. This is recorded in the ledger.")) return;
  try {
    const out = await api.sshMode(want);
    log(out.detail, out.ssh ? "no" : "ok");
    paintHosts();
  } catch (e) { log(e.message, "no"); }
};

$("hostForm").onsubmit = async e => {
  e.preventDefault();
  const f = new FormData(e.target);
  const row = Object.fromEntries([...f.entries()].map(([k, v]) => [k, String(v).trim()]));
  if (!row.host) return;
  try {
    await api.saveHosts([...hostRows, row]);
    e.target.reset();
    paintHosts();
  } catch (err) { log(err.message, "no"); }
};

$("sshForm").onsubmit = async e => {
  e.preventDefault();
  const cmd = $("sshIn").value.trim();
  const box = $("sshOut");
  if (!cmd) return;
  if (!hostPick) { termLine(box, "Pick a host on the left first.", "i"); return; }
  $("sshIn").value = "";
  termLine(box, `${hostPick} $ ${cmd}`, "b");
  try {
    const r = await api.sshRun(hostPick, cmd);
    if (r.out) termLine(box, r.out);
    if (r.err) termLine(box, r.err, "i");
  } catch (err) { termLine(box, err.message, "i"); }
};

/* ─── 04 · banking ─────────────────────────────────────────────────────────
   Accounts you entered. There is no "link account" here and there will not
   be: linking means holding a banking credential, and the sandbox has no
   network to use one over even if it were wise to keep one. */

async function paintBank() {
  const box = $("bankBody");
  let d;
  try { d = (await api.money()).addons || {}; }
  catch (e) { box.replaceChildren(el("p", "none", e.message)); return; }
  box.replaceChildren();

  const cards = el("div", "cards");
  const p = d.position || {};
  const summary = card("Position", money(p.net));
  [["Have", p.have], ["Owe", p.owe]].forEach(([l, v]) => {
    const f = el("div", "fig");
    f.append(el("span", null, l), el("b", null, money(v)));
    summary.append(f);
  });
  cards.append(summary);

  const out = card("Commitments this month", money(d.total));
  (d.slices || []).forEach(sl => {
    const f = el("div", "fig");
    f.append(el("span", null, sl.name), el("b", null, money(sl.amount)));
    out.append(f);
  });
  if (!d.slices?.length) out.append(el("p", "none", "Nothing recorded yet."));
  out.append(el("p", "note", "Feeds the Add-ons card on the dashboard."));
  cards.append(out);
  box.append(cards);

  box.append(el("p", "note",
    "Accounts and commitments are edited in the Banking app inside the " +
    "sandbox. This app has no connection to any bank and no field that would " +
    "take a password, a PIN or an OTP — the sandbox has no network to send " +
    "one over."));
}

/* ─── 05 · CSMA ────────────────────────────────────────────────────────────
   The gauge shows the score your bureau told you, on the day it told you,
   and the change since the reading before. It is not computed here. No
   formula outside a bureau produces somebody's score, and one invented here
   would be believed precisely because it sat next to real arithmetic. */

function gauge(score) {
  const R = 62, C = Math.PI * R;                 // half a circle
  const frac = Math.max(0, Math.min(1, (score - 300) / 600));
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "gauge");
  svg.setAttribute("viewBox", "0 0 160 92");
  const arc = (cls, len) => {
    const n = document.createElementNS("http://www.w3.org/2000/svg", "path");
    n.setAttribute("class", cls);
    n.setAttribute("d", `M18,80 A${R},${R} 0 0 1 142,80`);
    n.setAttribute("stroke-linecap", "round");
    if (len !== undefined) n.setAttribute("stroke-dasharray", `${len} ${C}`);
    svg.append(n);
  };
  arc("track");
  arc("fill", (frac * C).toFixed(1));
  return svg;
}

async function paintCsma() {
  const box = $("csmaBody");
  let d;
  try { d = (await api.money()).credit || {}; }
  catch (e) { box.replaceChildren(el("p", "none", e.message)); return; }
  box.replaceChildren();

  const cards = el("div", "cards");
  const left = card("Your recorded score");
  const sc = d.score;
  if (sc) {
    left.append(gauge(sc.score));
    const box2 = el("div", "score");
    box2.append(el("b", null, sc.score));
    const delta = sc.change === null || sc.change === undefined ? ""
      : `${sc.change >= 0 ? "+" : ""}${sc.change} since ${sc.since}`;
    box2.append(el("span", null, `${sc.bureau || "bureau"} · ${sc.at}${delta ? " · " + delta : ""}`));
    left.append(box2);
  } else {
    left.append(el("p", "none", "Nothing recorded yet. Enter the score your " +
                                 "bureau gave you and this will track it."));
  }
  const form = el("form", "entry");
  const input = el("input");
  input.placeholder = "score from your bureau, 300–900";
  input.inputMode = "numeric";
  form.append(el("span", "prompt", "#"), input);
  form.onsubmit = async e => {
    e.preventDefault();
    try { await api.recordScore(input.value, "bureau"); input.value = ""; paintCsma(); }
    catch (err) { log(err.message, "no"); }
  };
  left.append(form);
  left.append(el("p", "note",
    "Not computed here, and not a prediction. Only a bureau produces your " +
    "score, from data this machine has never seen."));
  cards.append(left);

  const factors = card("Factors",
    d.utilisation === null || d.utilisation === undefined ? "—" : `${d.utilisation}%`);
  (d.factors || []).forEach(f => {
    const r = el("div", "fig");
    r.append(el("span", null, f.name), el("b", null, `${f.weight}%`));
    factors.append(r);
  });
  cards.append(factors);

  const next = card("Next actions");
  if (!d.standing?.length) next.append(el("p", "none", "Add your accounts first."));
  (d.standing || []).forEach(n => {
    const row = el("div", "todo");
    row.append(el("span", null, n.level === "watch" ? "!" : "·"), el("span", null, n.text));
    next.append(row);
  });
  next.append(el("p", "note",
    "Observations on figures you entered, plus the published breakdown of " +
    "what a score is made of. Not financial advice — that needs somebody " +
    "licensed to give it."));
  cards.append(next);

  box.append(cards);
}

/* ─── 06 · you ─────────────────────────────────────────────────────────── */

async function paintYou() {
  const box = $("youBody");
  let d;
  try { d = await api.dashboard(); } catch (e) { return; }
  box.replaceChildren();

  const pick = el("div", "pick");
  d.professions.forEach(name => {
    const b = el("button", null, name);
    b.classList.toggle("on", name === d.profile.profession);
    b.onclick = async () => {
      await api.setProfile({ profession: name });
      log(`dashboard is now a ${name}'s`);
      paintYou();
    };
    pick.append(b);
  });
  box.append(pick);

  const got = card("You'll get");
  (d.cards || []).forEach(name => {
    const f = el("div", "fig");
    f.append(el("span", null, d.titles[name] || name),
             el("b", null, (d.about || {})[name] ? "" : ""));
    const note = el("p", "note", (d.about || {})[name] || "");
    got.append(f);
    if (note.textContent) got.append(note);
  });
  box.append(got);

  const named = card("Your name");
  const form = el("form", "entry");
  const input = el("input");
  input.placeholder = "what the dashboard should call you";
  input.value = d.profile.name || "";
  form.append(el("span", "prompt", "@"), input);
  form.onsubmit = async e => {
    e.preventDefault();
    await api.setProfile({ name: input.value });
    paintYou();
  };
  named.append(form);
  box.append(named);
}

buildRail();
// Establish the initial state explicitly rather than relying on the markup's
// attributes surviving the stylesheet.
showBoard(false);
