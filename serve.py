#!/usr/bin/env python3
"""
Shishya control panel.

    python3 serve.py            # http://localhost:8200

Serves web/ with caching off (same reason as starforge: module edits should
show up on reload) and exposes a small JSON API over host/vm.py + the ledger.

Deliberately stdlib-only. This runs on a laptop at a demo table with the
network locked down; a dependency that needs to resolve at start-up is a
dependency that can end the demo.
"""

import json
import os
import sys
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "host"))

import ledger            # noqa: E402
import vm                # noqa: E402

WEB = os.path.join(ROOT, "web")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB, **kwargs)

    # ─── API ────────────────────────────────────────────────────────────────

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._api("GET")
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._api("POST")
        self.send_error(404)

    def _api(self, method):
        route = self.path.split("?")[0][len("/api/"):].strip("/")
        try:
            body = {}
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                body = json.loads(self.rfile.read(n) or b"{}")
            self._json(self.route(method, route, body))
        except Exception as e:
            traceback.print_exc()
            self._json({"error": str(e), "type": type(e).__name__}, code=500)

    def route(self, method, route, body):
        # ── read ──
        if route == "status":
            return {"vm": vm.status(), "ledger": ledger.summary(),
                    "snapshots": vm.snapshots() if vm.status()["state"] != "absent" else []}
        if route == "ledger":
            return {"entries": ledger.read(limit=int(body.get("limit", 300)))}

        if method != "POST":
            self.send_error(405)
            return None

        # ── write ── every one of these is logged, including from the CLI
        if route == "vm/create":
            ledger.record(ledger.INFO, "vm.create", vm.NAME, actor="guru")
            return vm.create()
        if route == "vm/start":
            ledger.record(ledger.INFO, "vm.start", vm.NAME, actor="guru")
            return vm.start()
        if route == "vm/stop":
            ledger.record(ledger.INFO, "vm.stop", vm.NAME, actor="guru")
            return vm.stop()
        if route == "vm/snapshot":
            tag = body.get("tag", vm.CLEAN_TAG)
            ledger.record(ledger.INFO, "vm.snapshot", tag, actor="guru")
            return vm.snapshot(tag)
        if route == "vm/rollback":
            tag = body.get("tag", vm.CLEAN_TAG)
            ledger.record(ledger.INFO, "vm.rollback", tag, actor="guru",
                          detail="everything the clone did since this tag is gone")
            return vm.rollback(tag)
        if route == "vm/egress":
            locked = bool(body.get("locked", True))
            ledger.record(ledger.INFO, "net.egress",
                          "locked" if locked else "open", actor="guru")
            return vm.egress(locked)

        self.send_error(404)
        return None

    def _json(self, obj, code=200):
        if obj is None:
            return
        payload = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    # ─── static ─────────────────────────────────────────────────────────────

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        super().end_headers()

    def log_message(self, fmt, *args):
        status = args[1] if len(args) > 1 else ""
        if status not in ("200", "304"):
            super().log_message(fmt, *args)


Handler.extensions_map.update({".js": "text/javascript", ".mjs": "text/javascript"})

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8200
    print(f"Shishya → http://localhost:{port}   (Ctrl-C to stop)")
    ThreadingHTTPServer(("", port), Handler).serve_forever()
