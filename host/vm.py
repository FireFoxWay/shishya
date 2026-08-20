#!/usr/bin/env python3
"""
Shishya — host-side control of the clone's sandbox.

Thin wrapper over `limactl`. Everything the control panel can do to the VM
goes through here so that every state change lands in the ledger, including
the ones that happen from the command line.
"""

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "vm" / "lima.yaml"
NAME = "shishya"

# The tag we roll back to. Taken once, immediately after provisioning, before
# the clone has ever run — so "undo" always means "the way it was".
CLEAN_TAG = "clean"


class VMError(RuntimeError):
    pass


def _lima(*args, timeout=180, check=True):
    cmd = ["limactl", *args]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise VMError(f"{' '.join(cmd)}\n{p.stderr.strip() or p.stdout.strip()}")
    return p.stdout.strip()


def status():
    """Everything the control panel needs to paint its header, in one call."""
    try:
        raw = _lima("list", "--json", check=False)
    except FileNotFoundError:
        return {"state": "no-lima", "detail": "limactl not installed"}

    for line in raw.splitlines():
        if not line.strip():
            continue
        vm = json.loads(line)
        if vm.get("name") == NAME:
            return {
                "state": vm.get("status", "Unknown").lower(),
                "cpus": vm.get("cpus"),
                "memory": vm.get("memory"),
                "dir": vm.get("dir"),
            }
    return {"state": "absent"}


def create():
    """First boot. Slow — pulls the Ubuntu cloud image, then provisions."""
    if status()["state"] != "absent":
        raise VMError(f"VM {NAME!r} already exists")
    _lima("start", "--tty=false", f"--name={NAME}", str(CONFIG), timeout=1800)
    return status()


def start():
    _lima("start", "--tty=false", NAME, timeout=600)
    return status()


def stop():
    _lima("stop", NAME, timeout=300)
    return status()


def shell(script, user="clone", timeout=120):
    """Run something inside the VM as the clone (never as root)."""
    p = subprocess.run(
        ["limactl", "shell", NAME, "--", "sudo", "-u", user, "bash", "-lc", script],
        capture_output=True, text=True, timeout=timeout,
    )
    return {"code": p.returncode, "out": p.stdout, "err": p.stderr}


# ─── The undo button ────────────────────────────────────────────────────────
# Whole-VM snapshots, so rollback covers the filesystem, running apps and any
# half-finished state together. A file-level undo would miss the app that has
# the document open and unsaved.

def snapshot(tag=CLEAN_TAG):
    _lima("snapshot", "create", NAME, "--tag", tag, timeout=600)
    return {"tag": tag, "at": time.time()}


def rollback(tag=CLEAN_TAG):
    _lima("snapshot", "apply", NAME, "--tag", tag, timeout=600)
    return {"tag": tag, "at": time.time()}


def snapshots():
    try:
        out = _lima("snapshot", "list", NAME, check=False)
    except (FileNotFoundError, VMError, subprocess.TimeoutExpired):
        return []
    return [l.split()[0] for l in out.splitlines()[1:] if l.strip()]


# ─── The network kill switch ────────────────────────────────────────────────
# The demo claim is "nothing left this laptop". We make that true rather than
# promising it: drop all egress except the host's Ollama. Applied inside the
# guest, so the clone cannot lift it — it has no sudo.

# Lima's vz NAT puts the host at .2 on the guest's subnet. Verified with
# `limactl shell shishya -- ip route | awk '/default/{print $3}'` on first boot.
HOST_IP = "192.168.5.2"
OLLAMA_PORT = 11434


def egress(locked: bool):
    if locked:
        script = f"""
          nft flush ruleset
          nft add table inet shishya
          nft add chain inet shishya out '{{ type filter hook output priority 0; policy drop; }}'
          nft add rule inet shishya out ct state established,related accept
          nft add rule inet shishya out oifname lo accept
          nft add rule inet shishya out ip daddr {HOST_IP} tcp dport {OLLAMA_PORT} accept
        """
    else:
        script = "nft flush ruleset"
    p = subprocess.run(
        ["limactl", "shell", NAME, "--", "sudo", "bash", "-lc", script],
        capture_output=True, text=True, timeout=60,
    )
    if p.returncode != 0:
        raise VMError(p.stderr.strip())
    return {"locked": locked}


if __name__ == "__main__":
    import sys
    fn = sys.argv[1] if len(sys.argv) > 1 else "status"
    print(json.dumps(globals()[fn](*sys.argv[2:]), indent=2, default=str))
