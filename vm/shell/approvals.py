#!/usr/bin/env python3
"""
Asking permission, and granting it. Shared by the sandbox apps and the panel.

Roles already say what a clerk may not do. That is half an answer: being
refused with no way to ask is how people work around software rather than
with it — a clerk who cannot void a mistaken bill will simply ring up a
correcting sale, and the books will carry two wrong entries instead of one
right correction.

So a refusal becomes a request. The clerk asks, the head sees it on the
panel, and approving it performs the thing. Nothing is decided by the
software; it only carries the question and records the answer.

── Why the state is a file ────────────────────────────────────────────────

Same reason the schedule is: the app raising the request runs inside the
sandbox and the person deciding is at the panel on the Mac. The shared mount
is the one channel between them, and a JSON file both can read beats
inventing a protocol for six fields.

── What this is not ───────────────────────────────────────────────────────

Not a security boundary. A program inside the sandbox could write straight
to this file, and the sandbox is what stops it mattering. This is for honest
people working a till, and for a record of who asked for what.
"""

import json
import time
import uuid
from pathlib import Path

import common

STORE = common.SHARED / "approvals.json"

PENDING, APPROVED, REFUSED = "pending", "approved", "refused"

# Requests older than this are stale: a void asked for yesterday should not
# be sitting there approvable this morning, when nobody remembers the bill.
STALE_AFTER = 24 * 3600


def _read():
    try:
        found = json.loads(STORE.read_text())
        return found if isinstance(found, list) else []
    except (OSError, ValueError):
        return []


def _write(rows):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    tmp.replace(STORE)          # whole file, renamed — never half a decision


def ask(what, detail, target=""):
    """Raise a request. Returns its id.

    `what` is the action name the role model already knows — "void",
    "rollback" — so the two never drift apart into different vocabularies.
    """
    rows = _read()
    request = {
        "id": uuid.uuid4().hex[:10],
        "at": time.time(),
        "by": common.role(),
        "what": what,
        "target": target,
        "detail": detail,
        "state": PENDING,
        "decided_at": None,
        "note": "",
    }
    rows.append(request)
    _write(rows)
    return request["id"]


def pending():
    """Open requests, oldest first — the one waiting longest is the one
    somebody is standing at a counter waiting for."""
    now = time.time()
    live = [r for r in _read()
            if r.get("state") == PENDING and now - r.get("at", 0) < STALE_AFTER]
    return sorted(live, key=lambda r: r.get("at", 0))


def get(request_id):
    return next((r for r in _read() if r.get("id") == request_id), None)


def decide(request_id, approved, note=""):
    """Record a decision. Returns the request, or None if it is not open.

    Refuses to decide twice: a request approved once and approved again
    would perform its action twice, and the second time would look exactly
    as legitimate as the first.
    """
    rows = _read()
    for r in rows:
        if r.get("id") != request_id:
            continue
        if r.get("state") != PENDING:
            return None
        r["state"] = APPROVED if approved else REFUSED
        r["decided_at"] = time.time()
        r["note"] = note
        _write(rows)
        return r
    return None


def recent(limit=20):
    return sorted(_read(), key=lambda r: r.get("at", 0), reverse=True)[:limit]


def prune(keep=200):
    """Decided requests are history, not a queue. Keep the last few hundred
    so the file stays readable, and never touch anything still pending."""
    rows = _read()
    if len(rows) <= keep:
        return 0
    live = [r for r in rows if r.get("state") == PENDING]
    done = sorted((r for r in rows if r.get("state") != PENDING),
                  key=lambda r: r.get("at", 0))
    dropped = max(0, len(done) - keep)
    _write(live + done[dropped:])
    return dropped
