#!/usr/bin/env python3
"""
Tasks — what the shop still has to do, and who asked for it.

Alerts say what is wrong right now and vanish when it stops being true. That
is the right behaviour for "you are out of stock" and the wrong behaviour for
"order more from Patwari" — which stays true until somebody does it, and
which nobody should have to keep in their head between two visits to the
panel.

So this is the deliberately dull thing: a list, with a state, an owner and a
note. It exists because Findings and the audit produce work, and work with
nowhere to go is work that gets forgotten.

── Where a task comes from ────────────────────────────────────────────────

Three places, and knowing which matters when you are deciding whether to
trust it: a person typed it, an alert raised it, or a finding produced it.
An automatically raised task is not created twice — the same alert firing
every evening for a week is one task, not seven.
"""

import json
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "shared" / "tasks.json"

OPEN, DONE, DROPPED = "open", "done", "dropped"


def _read():
    try:
        found = json.loads(STORE.read_text(encoding="utf-8"))
        return found if isinstance(found, list) else []
    except (OSError, ValueError):
        return []


def _write(rows):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STORE)


def add(what, why="", source="person", key=""):
    """Add a task. `key` makes it idempotent for anything automatic.

    An alert that fires every evening must not leave seven identical tasks by
    the end of the week — so a raised task carries the key of the thing that
    raised it, and raising it again while it is still open changes nothing.
    """
    what = (what or "").strip()
    if not what:
        return None
    rows = _read()
    if key:
        for r in rows:
            if r.get("key") == key and r.get("state") == OPEN:
                return r          # already on the list, still not done
    task = {"id": uuid.uuid4().hex[:10], "at": time.time(), "what": what,
            "why": why, "source": source, "key": key, "state": OPEN,
            "done_at": None}
    rows.append(task)
    _write(rows)
    return task


def listing(state=OPEN, limit=50):
    rows = [r for r in _read() if state is None or r.get("state") == state]
    return sorted(rows, key=lambda r: r.get("at", 0), reverse=True)[:limit]


def set_state(task_id, state):
    if state not in (OPEN, DONE, DROPPED):
        return None
    rows = _read()
    for r in rows:
        if r.get("id") == task_id:
            r["state"] = state
            r["done_at"] = time.time() if state != OPEN else None
            _write(rows)
            return r
    return None


def from_alerts(alerts):
    """Turn today's alerts into tasks, once each.

    The alert is the symptom and the task is the work: "149 products below
    reorder" stops being true the moment somebody orders, but "order them"
    stays on the list until it is done.
    """
    made = []
    for a in alerts or []:
        what = a.get("do") or a.get("what")
        if not what:
            continue
        task = add(what, why=a.get("what", ""), source="alert",
                   key=a.get("what", "")[:80])
        if task and task.get("at", 0) > time.time() - 5:
            made.append(task)
    return made


def counts():
    rows = _read()
    return {"open": sum(1 for r in rows if r.get("state") == OPEN),
            "done": sum(1 for r in rows if r.get("state") == DONE)}
