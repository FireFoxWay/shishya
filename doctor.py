#!/usr/bin/env python3
"""
Shishya — what works on this machine, and what does not.

    python3 doctor.py          (python doctor.py on Windows)

demo.sh is the equivalent for the machine that runs the sandbox, and it is
bash, macOS-shaped, and assumes a VM. This is the version that runs anywhere,
in the standard library only, and its job is to tell somebody who has just
cloned the repository which half of it they can work on today.

The answer is honest rather than encouraging. The sandbox is Lima, which is
macOS and Linux; on Windows it does not run and no amount of wishing changes
that. What DOES run on Windows is the part where most of the work is: the
shop's books, GST invoicing, the Tally export, the task and experiment
records, the secret store, and the control panel's whole front end.
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

# ─── the half that needs a Mac or Linux ─────────────────────────────────────
head("The sandbox")
lima = shutil.which("limactl")
check("limactl", bool(lima), lima or "not installed", fatal=False)
if not lima:
    if platform.system() == "Windows":
        print("         Lima does not run on Windows. The sandbox — the virtual")
        print("         display, the GTK apps, the recorder, the executor, the")
        print("         egress lock — needs macOS or Linux. Under WSL2 you get a")
        print("         Linux userspace, but nested virtualisation is not")
        print("         something to rely on; see the handbook, §21.")
    else:
        print("         Install it: brew install lima")

try:
    with socket.create_connection(("127.0.0.1", 11434), timeout=2):
        check("a local model is reachable on :11434", True, fatal=False)
except OSError:
    check("a local model is reachable on :11434", False,
          "start Ollama — the apps answer through it", fatal=False)

# ─── what the sandbox would mount ───────────────────────────────────────────
head("The security boundary")
cfg = (ROOT / "vm" / "lima.yaml").read_text(encoding="utf-8")
check("lima.yaml is a template, not one laptop's paths",
      "__SHISHYA_ROOT__" in cfg,
      "resolved against this checkout when the VM is created")
if "/Users/" in cfg:
    check("no absolute home path is baked into the boundary", False,
          "someone's home directory is still written out in full")

print()
if fails:
    print(f"{len(fails)} problem(s): " + ", ".join(fails))
    sys.exit(1)
print("Everything checkable from here is fine.")
