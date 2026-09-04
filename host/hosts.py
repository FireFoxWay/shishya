#!/usr/bin/env python3
"""
Saved SSH hosts.

What is stored: a name, a user, a hostname, a port, and the path to a key.
What is NOT stored: a password, a passphrase, or a private key. The wireframe
says "keys stored locally" and that is exactly right — the key stays where ssh
already keeps it, and this file records where to look, never what is in it.

A passphrase-protected key is the correct kind to use here. There is nowhere
in this app to type a passphrase and nowhere it would be kept if there were.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "shared" / ".hosts.json"

FIELDS = ("name", "user", "host", "port", "key")

# Anything that looks like a credential is refused rather than dropped
# quietly, so nobody discovers later that it was saved somewhere else.
FORBIDDEN = ("password", "passphrase", "secret", "token", "pin", "otp")


def read():
    try:
        rows = json.loads(STORE.read_text(encoding="utf-8"))
        return [{f: str(r.get(f, "")) for f in FIELDS} for r in rows]
    except (OSError, ValueError):
        return []


def write(rows):
    clean = []
    for r in rows:
        for bad in FORBIDDEN:
            if bad in {str(k).lower() for k in r}:
                raise ValueError(f"{bad} is not stored here — use a key file")
        row = {f: str(r.get(f, "")).strip() for f in FIELDS}
        if not row["host"]:
            continue
        row["port"] = row["port"] or "22"
        row["name"] = row["name"] or f"{row['user'] or 'user'}@{row['host']}"
        clean.append(row)
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STORE)
    return clean


def target(row):
    """The argv ssh needs. Built as a list so nothing a person typed into a
    hostname field is ever interpolated into a shell string."""
    args = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=8"]
    if row.get("key"):
        args += ["-i", row["key"]]
    if row.get("port") and str(row["port"]) != "22":
        args += ["-p", str(row["port"])]
    who = f"{row['user']}@{row['host']}" if row.get("user") else row["host"]
    return args + [who]
