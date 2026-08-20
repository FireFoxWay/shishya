#!/usr/bin/env python3
"""
Shishya — the permission ledger.

Append-only JSONL. Every action the clone takes, every file it opens, every
request it makes, and — the entries that matter most in a demo — every one
that was refused.

Append-only on purpose: an audit log the agent could edit is not an audit
log. Nothing in this module removes or rewrites a line.
"""

import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "var" / "ledger.jsonl"
_lock = threading.Lock()

ALLOW, DENY, INFO = "allow", "deny", "info"


def record(verdict, action, target, *, actor="clone", detail=None, run=None):
    entry = {
        "t": round(time.time(), 3),
        "verdict": verdict,       # allow | deny | info
        "actor": actor,           # clone | guru (you) | system
        "action": action,         # open | write | exec | net | snapshot | ...
        "target": target,
        "detail": detail,
        "run": run,               # which task run this belongs to
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False)
    with _lock:
        # Append with an explicit flush: a crash mid-task must not lose the
        # entries explaining what the clone was doing when it crashed.
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
    return entry


def read(limit=500, since=0.0):
    if not LOG.exists():
        return []
    out = []
    with open(LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue          # never let one bad line hide the rest
            if e.get("t", 0) >= since:
                out.append(e)
    return out[-limit:]


def summary():
    entries = read(limit=100000)
    return {
        "total": len(entries),
        "denied": sum(1 for e in entries if e["verdict"] == DENY),
        "allowed": sum(1 for e in entries if e["verdict"] == ALLOW),
        "since": entries[0]["t"] if entries else None,
    }
