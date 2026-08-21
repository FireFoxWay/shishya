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
  ask:      (text)  => call("ask", { text }),
  answer:   ()      => call("answer", {}),
  status:   ()      => call("status"),
  ledger:   ()      => call("ledger"),
  create:   ()      => call("vm/create",   {}),
  start:    ()      => call("vm/start",    {}),
  stop:     ()      => call("vm/stop",     {}),
  snapshot: (tag)   => call("vm/snapshot", { tag }),
  rollback: (tag)   => call("vm/rollback", { tag }),
  egress:   (locked)=> call("vm/egress",   { locked }),
};
