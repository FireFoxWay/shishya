#!/usr/bin/env python3
"""
Secrets — kept where the sandbox cannot see them.

The security model of this project is the mount list: the clone cannot read
~/Documents because it is not mounted, not because code checks a path. This
applies that rule to credentials, and the location is the whole design.

── Why not var/ ───────────────────────────────────────────────────────────

Because the sandbox can read it. `vm/lima.yaml` mounts the entire repository
at /opt/shishya, so a secret in var/ is a secret the clone can `cat` — tested,
not assumed: a canary written to var/secret-canary.txt read back from inside
the sandbox on the first try. Anything under the repo is inside the boundary.

So the store lives at ~/.shishya/secrets.json, outside the repository and
outside every mount, with the directory and file readable only by the person
who owns them.

── What this is and is not ────────────────────────────────────────────────

It is NOT encrypted, and nothing here will claim it is. Encryption needs a
key, a key needs either a passphrase typed every time — which would break
every scheduled run — or a key stored beside the thing it protects, which
protects nothing. Saying "encrypted at rest" while doing the latter is the
kind of claim this project exists to avoid making.

What it is: a file the sandbox cannot reach, with 0600 permissions, whose
values never enter a prompt, never enter the ledger, and never cross into
shared/. The ledger records that a secret named `tally.password` was set,
never what it was set to.
"""

import json
import os
import stat
from pathlib import Path

# Deliberately outside the repository. Everything under the project directory
# is mounted into the sandbox read-only, so "in the repo" and "reachable by
# the clone" are the same statement.
HOME = Path.home() / ".shishya"
STORE = HOME / "secrets.json"


class SecretError(RuntimeError):
    pass


def _load():
    try:
        found = json.loads(STORE.read_text())
        return found if isinstance(found, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(values):
    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    # Written with the restrictive mode from the start rather than chmod'ed
    # afterwards: between creating a world-readable file and fixing it there
    # is a window, and windows are what get exploited.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(values, f, indent=2, ensure_ascii=False)
    tmp.replace(STORE)
    os.chmod(STORE, 0o600)
    os.chmod(HOME, 0o700)


def names():
    """Every secret's name and length — never a value.

    The length is there so somebody can tell an empty setting from a set one
    without the API ever having to hand the value back.
    """
    return sorted(({"name": k, "length": len(v or "")}
                   for k, v in _load().items()),
                  key=lambda s: s["name"])


def get(name):
    """The value. Host-side callers only; there is no route that returns this."""
    return _load().get(name)


def put(name, value):
    name = (name or "").strip()
    if not name:
        raise SecretError("a secret needs a name")
    if len(name) > 64 or not all(c.isalnum() or c in "._-" for c in name):
        raise SecretError("names are letters, numbers, dot, dash, underscore")
    values = _load()
    values[name] = value or ""
    _save(values)
    return {"name": name, "length": len(value or "")}


def forget(name):
    values = _load()
    if name not in values:
        raise SecretError(f"no secret named {name!r}")
    del values[name]
    _save(values)
    return {"forgotten": name}


def permissions_ok():
    """Whether the store is as private as it claims to be."""
    if not STORE.exists():
        return True, "no secrets are stored"
    mode = stat.S_IMODE(STORE.stat().st_mode)
    if mode & 0o077:
        return False, f"secrets.json is mode {oct(mode)} — readable by others"
    return True, f"secrets.json is mode {oct(mode)}"


def leaked_into(root):
    """Any secret value that has found its way into a folder the sandbox can
    read. This is the check that matters: the store being private is worth
    nothing if a value was copied into shared/ by a well-meaning script.

    Compares against values, not names — a name in a config file is fine and
    expected; the value being there is the failure.
    """
    values = [v for v in _load().values() if v and len(v) >= 6]
    if not values:
        return []
    found = []
    root = Path(root)
    for path in root.rglob("*"):
        if not path.is_file() or path.stat().st_size > 4_000_000:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for value in values:
            if value in text:
                found.append(str(path.relative_to(root)))
                break
    return found


if __name__ == "__main__":
    import sys
    what = sys.argv[1] if len(sys.argv) > 1 else "list"
    if what == "list":
        print(json.dumps(names(), indent=2))
    elif what == "check":
        ok, detail = permissions_ok()
        print(("ok  " if ok else "BAD ") + detail)
        leaks = leaked_into(Path(__file__).resolve().parent.parent / "shared")
        print(f"leaked into shared/: {leaks or 'nothing'}")
    else:
        sys.exit("usage: secrets.py list|check")
