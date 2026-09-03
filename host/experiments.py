#!/usr/bin/env python3
"""
Experiments and datasets — which run, on which data, with which model.

This handbook is full of claims like "8 of 8 on the 17,011-row export" and
"deepseek-r1:8b answered correctly in 59s". Every one of them was true when
it was written and none of them says which file, which model version, or
whether the file has changed since. A result that cannot name its inputs is
an anecdote.

── Datasets ───────────────────────────────────────────────────────────────

A dataset here is a file in the material folder, fingerprinted: name, size,
and a SHA-256 of its contents. The hash is the point. "The pharmacy export"
named two different files over one afternoon — the original and a version
with thirteen more sheets — and nothing in the project noticed. A run
records the fingerprint it actually read, so a figure can always be traced
back to the bytes that produced it.

── Experiments ────────────────────────────────────────────────────────────

One row per run: what was asked, which model answered, which datasets were
in front of it, how long it took, and whether it was right. Enough to answer
"has this got better or worse since Tuesday", which is the only question an
experiment log needs to answer and the one nobody can answer from memory.
"""

import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "var" / "experiments.json"
MATERIAL = ROOT / "shared" / "training"

# Big files are hashed by their first and last megabyte plus their size.
# A full SHA-256 of a 21 MB workbook takes long enough that nobody would run
# the check, and a check nobody runs is worse than a cheaper one they do.
FULLY_UNDER = 4 * 1024 * 1024


def fingerprint(path):
    """Name, size and content hash of one file."""
    path = Path(path)
    if not path.is_file():
        return None
    size = path.stat().st_size
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        if size <= FULLY_UNDER:
            digest.update(f.read())
            how = "sha256"
        else:
            head = f.read(1024 * 1024)
            f.seek(max(0, size - 1024 * 1024))
            digest.update(head + f.read())
            digest.update(str(size).encode())
            how = "sha256 of head+tail+size"
    return {"name": path.name, "bytes": size,
            "hash": digest.hexdigest()[:16], "how": how}


def datasets():
    """Every piece of material the clone can read, fingerprinted."""
    if not MATERIAL.exists():
        return []
    out = []
    for path in sorted(MATERIAL.iterdir()):
        if path.is_file() and not path.name.startswith("."):
            got = fingerprint(path)
            if got:
                out.append(got)
    return out


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


def record(what, model, verdict, seconds=None, detail="", on=None):
    """One run. `on` is the list of dataset names it actually read.

    Fingerprints are resolved here rather than passed in, so a caller cannot
    record a result against a file it did not open.
    """
    known = {d["name"]: d for d in datasets()}
    used = [known[n] for n in (on or []) if n in known]
    row = {"at": time.time(), "what": what, "model": model,
           "verdict": verdict, "seconds": seconds, "detail": detail,
           "on": used}
    rows = _read()
    rows.append(row)
    _write(rows[-500:])          # a log, not an archive
    return row


def runs(what=None, limit=50):
    rows = [r for r in _read() if what is None or r.get("what") == what]
    return sorted(rows, key=lambda r: r.get("at", 0), reverse=True)[:limit]


def changed_since(row):
    """Which of a run's datasets are no longer the file it read.

    This is what makes an old result honest: the number stays, and beside it
    is whether the thing it was measured on still exists in that form.
    """
    known = {d["name"]: d for d in datasets()}
    moved = []
    for d in row.get("on", []):
        now = known.get(d["name"])
        if now is None:
            moved.append(f"{d['name']} is gone")
        elif now["hash"] != d["hash"]:
            moved.append(f"{d['name']} has changed")
    return moved


if __name__ == "__main__":
    import sys
    what = sys.argv[1] if len(sys.argv) > 1 else "datasets"
    if what == "datasets":
        for d in datasets():
            print(f"  {d['hash']}  {d['bytes']:>10,}  {d['name']}")
    else:
        for r in runs():
            stale = changed_since(r)
            print(f"  {time.strftime('%d %b %H:%M', time.localtime(r['at']))}  "
                  f"{r['model']:<18} {r['verdict']:<12} {r['what'][:40]}"
                  + (f"   ⚠ {'; '.join(stale)}" if stale else ""))
