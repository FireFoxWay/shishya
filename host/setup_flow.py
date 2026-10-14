#!/usr/bin/env python3
"""
The setup page's brain: what is ready, what is not, and the one button that
fixes each.

Everything the terminal route asked a person to type — setup.ps1 as
administrator, `shishya create`, installing Ollama — is a step here with a
button, and long steps run in the background with their output kept so the
page can show it live. One job at a time: two of these at once (say, building
the sandbox while WSL is being reconfigured) would only fail in a more
confusing way.

Nothing here invents a new mechanism. The buttons call the same functions the
command line does — vm.create, launch.elevated_setup — so the two routes
cannot drift apart.
"""

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import launch
import vm

_job = {"name": None, "running": False, "ok": None, "lines": [], "at": 0.0}
_lock = threading.Lock()
_provisioned = {"value": None}            # cached: asking boots the sandbox
MARK = vm.STATE / "provisioned.ok"


def _say(line):
    with _lock:
        _job["lines"].append(str(line))
        del _job["lines"][:-400]


def _run_job(name, fn):
    with _lock:
        if _job["running"]:
            raise RuntimeError(f"already busy with: {_job['name']}")
        _job.update(name=name, running=True, ok=None, lines=[], at=time.time())

    def body():
        ok = False
        try:
            ok = fn() is not False
        except Exception as e:                            # noqa: BLE001
            _say(f"failed: {e}")
        finally:
            with _lock:
                _job.update(running=False, ok=ok)
            _say("done." if ok else "stopped — see above.")

    threading.Thread(target=body, daemon=True).start()
    return {"started": name}


# ─── what is true right now ─────────────────────────────────────────────────

def _ps(command, timeout=20):
    try:
        p = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                           capture_output=True, text=True, timeout=timeout,
                           creationflags=vm._NO_WINDOW)
        return p.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


_hv = {"at": 0.0, "value": None}


def _hypervisor():
    """True when a hypervisor is running — which is what WSL 2 needs, and is
    readable without administrator rights. Cached: it only changes across a
    restart, and asking costs a PowerShell start."""
    if os.name != "nt":
        return None
    if time.time() - _hv["at"] > 60:
        out = _ps("(Get-CimInstance Win32_ComputerSystem).HypervisorPresent")
        _hv.update(at=time.time(), value={"True": True, "False": False}.get(out))
    return _hv["value"]


def _ollama_installed():
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"
    return (local / "ollama.exe").exists() or bool(shutil.which("ollama"))


def provisioned(state):
    if state not in ("running", "stopped"):
        return False
    if MARK.exists():
        return True
    if _provisioned["value"] is None and not _job["running"]:
        try:
            _provisioned["value"] = vm._provisioned()
        except Exception:                                 # noqa: BLE001
            return False
        if _provisioned["value"]:
            MARK.write_text("yes", encoding="utf-8")
    return bool(_provisioned["value"])


def state():
    st = vm.status()
    s = st.get("state")
    hv = _hypervisor()
    windows_ok = s not in ("no-wsl", "wsl-busy") and hv is not False
    built = provisioned(s) if windows_ok else False
    steps = [
        {"id": "windows", "title": "Windows is ready for the sandbox",
         "ok": windows_ok,
         "detail": ("WSL 2 and virtualisation are on." if windows_ok else
                    st.get("detail") if s == "wsl-busy" else
                    "WSL is not installed yet." if s == "no-wsl" else
                    "No hypervisor is running. Press Fix, then restart Windows. "
                    "If it is still off after a restart, virtualisation is "
                    "disabled in the BIOS (ASUS: F2 at boot → Advanced → CPU "
                    "Configuration → Intel Virtualization Technology)."),
         "action": None if windows_ok else "Fix (asks for administrator)"},
        {"id": "ollama", "title": "The AI model (Ollama) is installed",
         "ok": _ollama_installed(),
         "detail": ("Running." if launch.model_up() else
                    "Installed. It starts when Shishya does.")
                   if _ollama_installed() else
                   "Not installed. Install downloads about 1 GB.",
         "action": None if _ollama_installed() else "Install Ollama"},
        {"id": "create", "title": "The sandbox is built",
         "ok": built,
         "detail": ("Built." if built else
                    "Takes 20 to 30 minutes, once. Leave this page open."),
         "action": None if built or not windows_ok else
                   ("Finish building" if s in ("running", "stopped") else "Build the sandbox")},
        {"id": "start", "title": "The sandbox is running",
         "ok": s == "running" and built,
         "detail": ("Running." if s == "running" and built else
                    "Stopped." if built else "Waits for the step above."),
         "action": "Start" if built and s != "running" else None},
    ]
    with _lock:
        job = {k: _job[k] for k in ("name", "running", "ok")}
        job["lines"] = list(_job["lines"][-200:])
    return {"steps": steps, "job": job, "ready": all(x["ok"] for x in steps),
            "sandbox": s}


# ─── the buttons ────────────────────────────────────────────────────────────

def _fix_windows():
    _say("Asking Windows for administrator rights — click Yes on the prompt.")
    _say("A blue PowerShell window shows what it changes. It can sit quietly")
    _say("for several minutes while Windows enables features; let it finish.")
    launch.elevated_setup()
    _hv["at"] = 0.0
    _say("If it said RESTART WINDOWS: restart now, then open Shishya.exe again.")


def _install_ollama():
    if not shutil.which("winget"):
        _say("winget is not available. Download Ollama from https://ollama.com/download")
        return False
    _say("Downloading and installing Ollama (about 1 GB) …")
    p = subprocess.Popen(["winget", "install", "--id", "Ollama.Ollama", "-e",
                          "--source", "winget", "--silent",
                          "--accept-package-agreements", "--accept-source-agreements"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=vm._NO_WINDOW)
    last = ""
    for raw in iter(p.stdout.readline, b""):
        line = raw.decode("utf-8", "replace").strip().strip("\r")
        # winget's progress bar arrives as hundreds of redrawn lines.
        if line and line != last and not set(line) <= set("-\\|/ █▒░%0123456789.MBKG"):
            _say(line[:120])
            last = line
    return p.wait() == 0


def _create():
    if launch.create(_say, open_browser=False) != 0:
        return False
    MARK.parent.mkdir(parents=True, exist_ok=True)
    MARK.write_text("yes", encoding="utf-8")
    _provisioned["value"] = True


def _start():
    _say("Starting the sandbox …")
    vm.start()
    _say("Running, network locked.")


def run(step):
    fn = {"windows": _fix_windows, "ollama": _install_ollama,
          "create": _create, "start": _start}.get(step)
    if not fn:
        raise ValueError(f"no such step: {step!r}")
    return _run_job(step, fn)


if __name__ == "__main__":
    print(json.dumps(state(), indent=2))
