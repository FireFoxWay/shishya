#!/usr/bin/env python3
"""
Version history for the things the clone changes.

The repository has git and forty-two commits of source. What has never had
any history is the material: the shop's books, the lessons it has been
taught, the shape of the catalogue. Those change every day, by software, and
until now the only record of yesterday's version was a nightly backup.

── Why a second repository, not the project's ─────────────────────────────

Because they answer different questions. The project's history is "what did
we build"; this is "what did the shop do". Mixing a day of till receipts
into the source history makes both harder to read, and `git log` on the code
would become unusable within a week.

So: a git repository of its own, inside shared/, holding the books, the
schedule, the roles and the learned procedures. Traces are excluded — they
are screenshots and event dumps, large and specific to one machine.

── Why local, and what a push would cost ──────────────────────────────────

The whole claim of this project is that nothing leaves the laptop unless
somebody says so. `git push` is egress. So history is kept locally and
always; sending it anywhere is a separate, deliberate act — head only,
requiring browsing mode, and written to the ledger like every other crossing.
That is the same shape as the browser permission, and for the same reason.
"""

import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "shared"

# What is worth a history. Everything here is small, textual, and changes
# because a person or the clone did something.
TRACKED = ["billing", "approvals.json", ".schedules.json", ".role",
           ".alerts.json", "traces/*/procedure.json"]

IGNORE = """# The clone's own working files. Large, regenerable, or both.
work/
inbox/
training/
traces/*
!traces/*/
!traces/*/procedure.json
*.tmp
*.part
*.before-gst
"""


class HistoryError(RuntimeError):
    pass


def _git(*args, check=True):
    p = subprocess.run(["git", "-C", str(SHARED), *args],
                       capture_output=True, text=True, timeout=60)
    if check and p.returncode != 0:
        raise HistoryError((p.stderr or p.stdout).strip()[:300])
    return p.stdout.strip()


def started():
    return (SHARED / ".git").exists()


def start():
    """Begin keeping history. Safe to call twice."""
    if started():
        return {"already": True}
    SHARED.mkdir(parents=True, exist_ok=True)
    _git("init", "-q")
    # Identity is set on the repository, not globally: this machine's git
    # config belongs to the person, and a tool should not edit it.
    _git("config", "user.name", "Shishya")
    _git("config", "user.email", "shishya@localhost")
    (SHARED / ".gitignore").write_text(IGNORE, encoding="utf-8")
    return save("history started")


def save(why="", by="system"):
    """Commit whatever changed. Returns what was recorded, or says nothing was.

    Called after anything that alters the books, and safe to call when
    nothing has changed — a version history that only records when somebody
    remembers to ask is not a history.
    """
    if not started():
        return {"error": "history has not been started"}
    _git("add", "-A")
    if not _git("status", "--porcelain"):
        return {"changed": False, "why": why}
    message = f"{why or 'change'}\n\nrecorded by {by} at {time.strftime('%d %b %Y %H:%M:%S')}"
    _git("commit", "-q", "-m", message)
    return {"changed": True, "why": why, "at": _git("rev-parse", "--short", "HEAD")}


def log(limit=25):
    """What has happened to the material, newest first."""
    if not started():
        return []
    raw = _git("log", f"-{limit}", "--pretty=format:%h\x1f%at\x1f%s\x1f%an", check=False)
    out = []
    for line in raw.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            out.append({"at": parts[0], "when": float(parts[1]),
                        "why": parts[2], "by": parts[3]})
    return out


def review(commit):
    """What one change actually changed. This is the review half: a history
    nobody can read a diff out of is a backup with extra steps."""
    if not started():
        raise HistoryError("history has not been started")
    if not commit.isalnum() or len(commit) > 40:
        raise HistoryError("that is not a commit")
    stat = _git("show", "--stat", "--pretty=format:%s%n", commit, check=False)
    patch = _git("show", "--pretty=format:", "--unified=1", commit, check=False)
    return {"at": commit, "summary": stat[:4000], "patch": patch[:20000]}


def status():
    if not started():
        return {"started": False, "pending": 0}
    dirty = [l for l in _git("status", "--porcelain", check=False).splitlines() if l]
    return {"started": True, "pending": len(dirty),
            "commits": len(log(200)), "changed": dirty[:12]}
