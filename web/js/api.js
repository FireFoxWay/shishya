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

export const api = {
  status:   ()      => call("status"),
  ledger:   ()      => call("ledger"),
  create:   ()      => call("vm/create",   {}),
  start:    ()      => call("vm/start",    {}),
  stop:     ()      => call("vm/stop",     {}),
  snapshot: (tag)   => call("vm/snapshot", { tag }),
  rollback: (tag)   => call("vm/rollback", { tag }),
  egress:   (locked)=> call("vm/egress",   { locked }),
};
