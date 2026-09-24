#!/usr/bin/env python3
"""
Shishya — what works on this machine, and what does not.

    python doctor.py

The first thing to run after cloning, and the thing to run when something
looks wrong before guessing which layer broke. Standard library only.

This build targets Windows. The sandbox is a WSL2 distribution of its own,
driven by host/vm.py through wsl.exe; the model is Ollama for Windows; the
panel and the terminal are plain Python. Every one of those can be missing or
misconfigured in a way that presents as something else — a model that is
running but listening where the sandbox cannot reach it looks exactly like a
broken app — so each is checked here by name.
"""

import importlib.util
import json
import locale
import os
import platform
import shutil
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# The report itself is full of dashes and box lines, and a Windows console
# writes in its code page unless told otherwise — the doctor would fall over
# on its own headings before diagnosing anything.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
OK, BAD, MEH = "  [ ok ]", "  [FAIL]", "  [ -- ]"
fails = []


def head(t):
    print(f"\n{t}\n{'─' * len(t)}")


def check(name, good, detail="", fatal=True):
    print(f"{OK if good else (BAD if fatal else MEH)}  {name}"
          + (f"  — {detail}" if detail else ""))
    if not good and fatal:
        fails.append(name)
    return good


# ─── the machine ────────────────────────────────────────────────────────────
head("This machine")
print(f"  {platform.system()} {platform.release()} · {platform.machine()}"
      f" · Python {platform.python_version()}")
check("Python 3.10 or newer", sys.version_info >= (3, 10),
      f"found {platform.python_version()}")

# ─── the one that actually bites on Windows ─────────────────────────────────
# Every price in this system is written with a rupee sign and half the comments
# are in three scripts. Windows' default text encoding is cp1252, which cannot
# represent any of it — and the failure is not a warning, it is a
# UnicodeEncodeError in the middle of saving a bill.
head("Text encoding")
print(f"  locale default: {locale.getpreferredencoding(False)}"
      f" · UTF-8 mode: {'on' if sys.flags.utf8_mode else 'off'}")
sample = "₹1,234.50 · शिष्य · శిష్య · em—dash"
try:
    tmp = Path(tempfile.gettempdir()) / "shishya-encoding-probe.txt"
    tmp.write_text(sample, encoding="utf-8")
    back = tmp.read_text(encoding="utf-8")
    tmp.unlink(missing_ok=True)
    check("rupee signs and Indic scripts survive a round trip", back == sample)
except (OSError, UnicodeError) as e:
    check("rupee signs and Indic scripts survive a round trip", False, str(e))

# Named encodings are the fix, and it is only a fix if nothing was missed.
try:
    import ast
    missing = []
    for p in ROOT.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if not isinstance(n, ast.Call) or any(k.arg == "encoding"
                                                  for k in n.keywords):
                continue
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr in ("read_text", "write_text"):
                missing.append(f"{p.name}:{n.lineno}")
    check("every text read and write names its encoding", not missing,
          f"{len(missing)} do not" if missing else "")
except Exception as e:                                   # noqa: BLE001
    check("every text read and write names its encoding", False, str(e), fatal=False)

# ─── the half that runs anywhere ────────────────────────────────────────────
head("The portable half — this is what you can work on today")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vm" / "shell"))
for mod, what in (("books", "the shop's books: stock, sales, margin, GST, returns"),
                  ("invoice", "GST tax invoices"),
                  ("host.tasks", "the task list"),
                  ("host.experiments", "experiment and dataset records"),
                  ("host.secrets", "the secret store"),
                  ("host.ledger", "the permission ledger")):
    try:
        importlib.import_module(mod)
        check(f"{mod}", True, what)
    except Exception as e:                               # noqa: BLE001
        check(f"{mod}", False, f"{type(e).__name__}: {e}")

# GST is the arithmetic most worth getting wrong quietly, so it is checked
# rather than merely imported. Tax is charged WITHIN the price here, which is
# how a counter in India quotes: 118 at 18% is 18 of tax, not 21.24.
try:
    import books
    got = round(books.tax_within(118.0, 18), 2)
    check("GST is computed within the price, not added to it", got == 18.0,
          f"118 at 18% → {got} (want 18.0)")
except Exception as e:                                   # noqa: BLE001
    check("GST is computed within the price, not added to it", False, str(e))

check("the control panel's front end", (ROOT / "web" / "index.html").is_file(),
      "web/ is plain ES modules and CSS — no build step, edit and reload")

# ─── the sandbox: WSL2 ──────────────────────────────────────────────────────
head("The sandbox (WSL2)")
windows = platform.system() == "Windows"
check("this is Windows", windows,
      "this build drives WSL; on another OS only the portable half above runs",
      fatal=False)

wsl = shutil.which("wsl.exe") or shutil.which("wsl")
if check("wsl.exe", bool(wsl), wsl or "not installed — run windows\\setup.ps1 "
         "as administrator", fatal=windows):
    import subprocess
    env = dict(os.environ, WSL_UTF8="1")
    try:
        ver = subprocess.run([wsl, "--version"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", env=env,
                             timeout=30)
        first = (ver.stdout.replace("\x00", "").strip().splitlines() or [""])[0]
        # The Store build of WSL answers --version; the old inbox one does not,
        # and is too old for systemd — which every service in the sandbox is.
        check("WSL from the Store, with systemd support", ver.returncode == 0,
              first or "too old — run: wsl --update")
    except (OSError, subprocess.SubprocessError) as e:
        check("WSL answers", False, str(e))

    try:
        sys.path.insert(0, str(ROOT / "host"))
        import vm
        state = vm.status().get("state")
        check("the shishya sandbox exists", state not in ("absent", "no-wsl"),
              state if state != "absent" else
              'not yet — python -c "import host.vm as vm; vm.create()"',
              fatal=False)
        if state not in ("absent", "no-wsl"):
            check("its disk is outside the repository", vm.DISK.exists(),
                  str(vm.DISK), fatal=False)
    except Exception as e:                               # noqa: BLE001
        check("host/vm.py can ask WSL", False, f"{type(e).__name__}: {e}")

wslconfig = Path.home() / ".wslconfig"
mirrored = False
if wslconfig.is_file():
    import re
    mirrored = bool(re.search(r"(?im)^\s*networkingMode\s*=\s*mirrored",
                              wslconfig.read_text(encoding="utf-8", errors="replace")))
check("WSL networking is NAT, which the egress lock is written for", not mirrored,
      f"{wslconfig} sets networkingMode=mirrored" if mirrored else "")

# ─── the model ──────────────────────────────────────────────────────────────
head("The model")
try:
    with socket.create_connection(("127.0.0.1", 11434), timeout=2):
        check("Ollama is answering on :11434", True, fatal=False)
except OSError:
    check("Ollama is answering on :11434", False,
          "start Ollama — the apps answer through it", fatal=False)

# The sandbox reaches Windows at its NAT gateway, not at 127.0.0.1, and
# Ollama for Windows listens on 127.0.0.1 alone unless told otherwise. It
# presents as every app in the sandbox failing to answer, while `ollama run`
# on Windows works perfectly.
host_var = os.environ.get("OLLAMA_HOST", "")
check("Ollama listens beyond loopback, so the sandbox can reach it",
      host_var.startswith("0.0.0.0"),
      f"OLLAMA_HOST={host_var or '(unset)'} — windows\\setup.ps1 sets it and "
      "scopes the firewall to WSL", fatal=False)

# ─── what the sandbox would mount ───────────────────────────────────────────
head("The security boundary")
conf = (ROOT / "vm" / "wsl.conf").read_text(encoding="utf-8")
fstab = (ROOT / "vm" / "fstab").read_text(encoding="utf-8")


def _section(text, name):
    """key = value pairs of one [section] of an ini-shaped file."""
    out, inside = {}, False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("["):
            inside = line.lower() == f"[{name}]"
        elif inside and "=" in line:
            k, v = (x.strip().lower() for x in line.split("=", 1))
            out[k] = v
    return out


check("Windows drives are not automounted into the sandbox",
      _section(conf, "automount").get("enabled") == "false",
      "vm/wsl.conf [automount] enabled = false")
check("the sandbox cannot start Windows programs",
      _section(conf, "interop").get("enabled") == "false",
      "vm/wsl.conf [interop] enabled = false")
check("fstab is a template, not one laptop's paths",
      "__SHISHYA_ROOT__" in fstab,
      "resolved against this checkout when the sandbox is created")
mounts = [ln.split()[1] for ln in fstab.splitlines()
          if ln.strip() and not ln.lstrip().startswith("#")]
check("exactly two folders cross the boundary",
      sorted(mounts) == ["/home/clone/shared", "/opt/shishya"],
      ", ".join(mounts))
check("the checkout is on a local drive", not str(ROOT).startswith("\\\\"),
      str(ROOT))

# Git for Windows checks out CRLF unless told not to, and these run inside
# the sandbox under bash. .gitattributes says LF; this proves it took.
crlf = [p.name for p in (ROOT / "vm").glob("*.sh") if b"\r" in p.read_bytes()]
check("the sandbox's shell scripts have Unix line endings", not crlf,
      ", ".join(crlf) + " — git add --renormalize . && git checkout -- vm"
      if crlf else "")

print()
if fails:
    print(f"{len(fails)} problem(s): " + ", ".join(fails))
    sys.exit(1)
print("Everything checkable from here is fine.")
