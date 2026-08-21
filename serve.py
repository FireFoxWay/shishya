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
import re
import sys
import time
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "host"))

import ledger            # noqa: E402
import vm                # noqa: E402

WEB = os.path.join(ROOT, "web")
INBOX = os.path.join(ROOT, "shared", "inbox")

# Files come in over a loopback socket from a page anyone on this machine can
# open, and land in a directory the sandbox reads. Cap the size so a stray
# drop cannot fill the disk the VM is running on.
MAX_UPLOAD = 64 * 1024 * 1024

# An explicit list, not "whatever file name you send". This endpoint runs a
# program inside the sandbox; it takes a choice from a menu, never a path.
LAUNCHABLE = {
    "training_app.py": "Training Data",
    "files_app.py": "Files",
    "activity_app.py": "Activity",
    "make_app.py": "Make a Document",
    "inbox_app.py": "Inbox",
    "code_app.py": "Code",
    "models_app.py": "Models",
    "system_app.py": "System",
}


def safe_filename(raw):
    """The name arrives in a header the browser filled in from a dropped file.

    Treat it as hostile: strip any directory part, refuse dotfiles and
    traversal, and keep it to characters that cannot mean anything to a
    shell. A dropped file must never be able to choose where it lands.
    """
    name = os.path.basename(raw or "").strip()
    name = re.sub(r"[^A-Za-z0-9._ ()-]", "_", name)
    name = name.lstrip(".") or "dropped-file"
    return name[:120]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB, **kwargs)

    # ─── API ────────────────────────────────────────────────────────────────

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._api("GET")
        return super().do_GET()

    def do_POST(self):
        # Uploads are raw bytes, not JSON, so they bypass the usual API path.
        if self.path.split("?")[0] == "/api/upload":
            return self.upload()
        if self.path.startswith("/api/"):
            return self._api("POST")
        self.send_error(404)

    def upload(self):
        size = int(self.headers.get("Content-Length") or 0)
        if size <= 0 or size > MAX_UPLOAD:
            return self._json({"error": f"file must be 1 byte to {MAX_UPLOAD // 1048576}MB"}, 413)

        name = safe_filename(self.headers.get("X-Filename"))
        os.makedirs(INBOX, exist_ok=True)
        target = os.path.join(INBOX, name)
        if os.path.exists(target):
            stem, ext = os.path.splitext(name)
            name = f"{stem}-{time.strftime('%H%M%S')}{ext}"
            target = os.path.join(INBOX, name)

        # Write to a temp name first and rename into place: the sandbox
        # watches this directory, and a half-written file appearing there
        # would be picked up as complete.
        tmp = target + ".part"
        remaining = size
        with open(tmp, "wb") as out:
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)
        if remaining > 0:
            os.unlink(tmp)
            return self._json({"error": "upload cut short"}, 400)
        os.rename(tmp, target)

        ledger.record(ledger.ALLOW, "file.in", name, actor="guru",
                      detail=f"{size} bytes dropped from the host")
        return self._json({"name": name, "bytes": size})

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
            state = vm.status()
            live = state.get("state") == "running"
            return {
                "vm": state,
                "ledger": ledger.summary(),
                "snapshots": vm.snapshots() if state["state"] != "absent" else [],
                # Measured, never assumed. Unknown when the VM is down, because
                # "locked" would be a claim we cannot support.
                "egress": vm.egress_state() if live else {"locked": None,
                                                          "detail": "sandbox is not running"},
            }
        if route == "launch":
            # Launch an app inside the sandbox from out here.
            #
            # Clicking inside the sandbox goes through noVNC, and that path
            # has failed twice under demo conditions — stale websockify
            # children swallow button releases and every control goes dead
            # while still looking fine. This route does not touch the display
            # at all, so it keeps working when that breaks. It is also the
            # better story: you drive from your side, the clone works on its.
            name = str(body.get("app", ""))
            if name not in LAUNCHABLE:
                return {"error": f"unknown app {name!r}"}
            ledger.record(ledger.INFO, "app.launch", name, actor="guru")
            return vm.launch_app(name)

        if route == "inbox":
            try:
                waiting = sorted(f for f in os.listdir(INBOX)
                                 if not f.startswith(".") and not f.endswith(".part"))
            except OSError:
                waiting = []
            return {"waiting": waiting}
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
        if route == "close":
            name = body.get("app")
            if name and name not in LAUNCHABLE:
                return {"error": f"unknown app {name!r}"}
            ledger.record(ledger.INFO, "app.close", name or "all", actor="guru")
            return vm.close_apps(name)

        if route == "ask":
            text = str(body.get("text", "")).strip()
            if not text:
                return {"error": "nothing to ask"}
            ledger.record(ledger.INFO, "ask", text[:70], actor="guru")
            return vm.drive("ask", text)

        if route == "answer":
            return vm.drive("read")

        if route == "vm/fix-input":
            ledger.record(ledger.INFO, "display.reset", "vnc stack", actor="guru")
            return vm.reset_display()

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
