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
    state === "no-lima" ? "lima is not installed" :
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
   demo.sh check proves both on every run. */

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
      "Nothing kept. Anything put here stays on this Mac — the sandbox has no path to it."));
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
