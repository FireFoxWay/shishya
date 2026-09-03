/* ============================================================================
   SHISHYA — control panel ↔ host bridge
   ========================================================================== */

async function call(route, body) {
  const res = await fetch(`/api/${route}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (data.error) throw new Error(data.error);
  return data;
}

/* Raw bytes rather than FormData: the host server is stdlib-only and parsing
   multipart by hand is a lot of surface for no gain when one file per request
   does the job. The name rides in a header. */
async function upload(file) {
  const res = await fetch("/api/upload", {
    method: "POST",
    headers: { "X-Filename": encodeURIComponent(file.name), "Content-Type": "application/octet-stream" },
    body: file,
  });
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (data.error) throw new Error(data.error);
  return data;
}

export const api = {
  upload,
  inbox:    ()      => call("inbox"),
  launch:   (app)   => call("launch", { app }),
  fixInput: ()      => call("vm/fix-input", {}),
  close:    (app)   => call("close", app ? { app } : {}),
  sources:  ()      => call("sources", {}),
  browsing: (on)    => call("vm/browsing", { on }),
  shell:    (cmd)   => call("shell", { cmd }),
  ask:      (text)  => call("ask", { text }),
  answer:   ()      => call("answer", {}),
  job:      (brief)  => call("job", { brief }),
  report:   (brief)  => call("report", { brief }),
  tally:    ()       => call("tally", {}),
  audit:    ()       => call("audit", {}),
  backup:   ()       => call("backup", {}),
  checkAlerts: ()    => call("alerts/check", {}),
  alerts:   ()       => call("alerts"),
  setRole:  (role)   => call("role", { role }),
  approvals: ()      => call("approvals"),
  tasks:    ()       => call("tasks"),
  addTask:  (what)   => call("task/add", { what }),
  taskState:(id, state) => call("task/state", { id, state }),
  tasksFromAlerts: () => call("tasks/from-alerts", {}),
  history:  ()       => call("history"),
  saveHistory: (why) => call("history/save", { why }),
  secrets:  ()       => call("secrets"),
  setSecret: (name, value) => call("secret/set", { name, value }),
  forgetSecret: (name)     => call("secret/forget", { name }),
  decide:   (id, approved, note) => call("approve", { id, approved, note }),
  takeList: (where, at) => call("take/list", { where, at }),
  takeUrl:  (where, path) =>
    `/api/take?where=${encodeURIComponent(where)}&path=${encodeURIComponent(path)}`,
  schedules: ()      => call("schedules"),
  jobProgress: ()    => call("job/progress"),
  jobFileUrl: (job, name) =>
    `/api/job/file?job=${encodeURIComponent(job)}&name=${encodeURIComponent(name)}`,
  lessons:  ()       => call("lessons"),
  lessonPlan: (lesson) => call("lesson/plan", { lesson }),
  lessonRun:  (lesson) => call("lesson/run",  { lesson }),
  lessonStop: ()       => call("lesson/stop", {}),
  lessonAnswer: (n, text, skip) => call("lesson/answer", { n, text, skip }),
  progress: ()      => call("lesson/progress"),
  status:   ()      => call("status"),
  ledger:   ()      => call("ledger"),
  create:   ()      => call("vm/create",   {}),
  start:    ()      => call("vm/start",    {}),
  stop:     ()      => call("vm/stop",     {}),
  snapshot: (tag)   => call("vm/snapshot", { tag }),
  rollback: (tag)   => call("vm/rollback", { tag }),
  egress:   (locked)=> call("vm/egress",   { locked }),
};
