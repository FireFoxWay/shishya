#!/usr/bin/env python3
"""
Shishya — perform a procedure that was learned by demonstration.

    python3 executor.py <trace-dir> --plan     what it would do, no action
    python3 executor.py <trace-dir> --run      actually do it

── What this will and will not attempt ─────────────────────────────────────

A recorded procedure is prose with a loose target attached. The prose carries
the intent — "Type 'Exam Eligible' into the selected cell" — while the target
is frequently generic, "Panel" or "Text Input", because that is genuinely
what AT-SPI reported at the time. So the text is read and the target is only
consulted when it is specific.

Four actions are supported, and they are the four the recorded lessons
actually contain: go to a named cell, type a value, press a named control,
and open an application. Anything else stops the run.

Stopping is the design, not a shortfall. A model this size guessing at an
unrecognised instruction is how an apprentice ends up confidently filing the
wrong thing, and the entire argument for this project is that you can see
what it did. A refusal you can read beats an action you cannot.

Every step verifies before moving on. A step that cannot be confirmed is
retried once and then halts the run with the reason.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import locate   # noqa: E402

try:
    import pyatspi
except ImportError:
    pyatspi = None

SETTLE = 0.6           # what a person's hand costs between actions
VERIFY_TIMEOUT = 6


# ─── reading a step ─────────────────────────────────────────────────────────

CELL = re.compile(r"\bcell\s+([A-Z]{1,3}\d{1,5})\b", re.I)
QUOTED = re.compile(r"['\"‘’“”]([^'\"‘’“”]{1,80})['\"‘’“”]")

TYPING = ("type", "enter", "write", "input", "fill", "put")
PRESSING = ("click", "press", "choose", "select the", "push")
OPENING = ("open", "launch", "start")


def understand(step):
    """Turn one written step into something performable, or None.

    Reads the sentence rather than the target field. The target recorded
    against a spreadsheet step is usually the sheet, not the cell, because
    that is what had focus when the recorder looked.
    """
    text = (step.get("text") or "").strip()
    low = text.lower()
    target = step.get("target") or {}
    named = (target.get("name") or "").strip()

    cell = CELL.search(text) or CELL.search(named)
    quoted = QUOTED.search(text)

    # "Type 'X' into cell I4" — the two together are one action.
    if any(v in low for v in TYPING) and quoted:
        return {"do": "type", "value": quoted.group(1),
                "cell": cell.group(1).upper() if cell else None, "text": text}

    if cell and any(v in low for v in ("navigate", "go to", "move to", "select")):
        return {"do": "goto", "cell": cell.group(1).upper(), "text": text}

    if any(v in low for v in OPENING):
        what = quoted.group(1) if quoted else named
        if what:
            return {"do": "open", "what": what, "text": text}

    if any(v in low for v in PRESSING):
        what = quoted.group(1) if quoted else named
        # A generic target name is not a control worth hunting for.
        if what and what.lower() not in ("panel", "text input", "table", "frame"):
            return {"do": "press", "what": what, "text": text}

    return None


# ─── doing it ───────────────────────────────────────────────────────────────

def sh(*args, timeout=10):
    return subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)


def goto_cell(name):
    """Put the cursor in a named cell.

    Through the Name Box rather than by hunting the accessibility tree for a
    cell: the box is one control that is always present, always in the same
    place, and works the same in every spreadsheet — where a cell may be
    scrolled out of view and have no usable position at all.
    """
    box = locate.find("Name Box", visible_only=True)
    if not box:
        return False, "no Name Box — is a spreadsheet open?"
    hit = box[0]
    sh("xdotool", "mousemove", str(hit["x"]), str(hit["y"]))
    time.sleep(0.2)
    sh("xdotool", "click", "1")
    time.sleep(0.3)
    sh("xdotool", "key", "ctrl+a")
    sh("xdotool", "type", "--delay", "40", name)
    sh("xdotool", "key", "Return")
    time.sleep(SETTLE)
    return True, f"went to {name}"


def type_value(value):
    sh("xdotool", "type", "--delay", "45", value)
    sh("xdotool", "key", "Return")
    time.sleep(SETTLE)
    return True, f"typed {value!r}"


def press_control(name):
    hits = locate.find(name)
    if not hits:
        return False, f"could not find anything called {name!r}"
    ok, message = locate.click(hits[0], name)
    time.sleep(SETTLE)
    return ok, message


def open_app(what):
    known = {
        "calc": "libreoffice --calc", "writer": "libreoffice --writer",
        "files": "python3 /opt/shishya/vm/shell/files_app.py",
        "training data": "python3 /opt/shishya/vm/shell/training_app.py",
    }
    command = known.get(what.lower())
    if not command:
        return False, f"I do not know how to open {what!r}"
    subprocess.Popen(command.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    return True, f"opened {what}"


DO = {"goto": lambda a: goto_cell(a["cell"]),
      "type": lambda a: type_value(a["value"]),
      "press": lambda a: press_control(a["what"]),
      "open": lambda a: open_app(a["what"])}


# ─── verifying ──────────────────────────────────────────────────────────────

def confirm(action):
    """Check the thing that was supposed to happen actually did.

    Only claims to have checked what it really can. A typed value is looked
    for in the accessibility tree; a press is not verifiable in general, and
    saying so is better than a green tick that means nothing.
    """
    if action["do"] == "type":
        wanted = action["value"]
        deadline = time.time() + VERIFY_TIMEOUT
        while time.time() < deadline:
            if wanted and locate.find(wanted[:24]):
                return True, "found it on screen"
            time.sleep(0.5)
        return False, f"{wanted!r} did not appear anywhere"
    return True, "not verifiable, assumed"


# ─── running ────────────────────────────────────────────────────────────────

def load(trace_dir):
    path = Path(trace_dir)
    if path.is_dir():
        path = path / "procedure.json"
    return json.loads(path.read_text())


def plan(proc):
    lines = [f"{proc.get('title', 'untitled')}"]
    for step in proc.get("steps", []):
        action = understand(step)
        mark = "  ok " if action else "  ?? "
        summary = (f"{action['do']} " +
                   (action.get("cell") or action.get("value") or action.get("what") or "")
                   ) if action else "cannot perform this one"
        lines.append(f"{mark}{step.get('n', '?'):>2}. {summary:<28} {step.get('text','')[:60]}")
    doable = sum(1 for s in proc.get("steps", []) if understand(s))
    lines.append(f"\n  {doable} of {len(proc.get('steps', []))} steps are performable")
    return "\n".join(lines)


def run(proc, on_step=None):
    """Perform the procedure, stopping at the first step that cannot be
    confirmed. Returns a list of (n, ok, message)."""
    results = []
    for step in proc.get("steps", []):
        n = step.get("n", len(results) + 1)
        action = understand(step)
        if not action:
            results.append((n, False, "I do not know how to do this one — stopping"))
            break

        ok, message = DO[action["do"]](action)
        if ok:
            ok, verified = confirm(action)
            message = f"{message} — {verified}"
            if not ok:
                # One retry, because a slow application is the usual cause.
                time.sleep(1.2)
                DO[action["do"]](action)
                ok, verified = confirm(action)
                message = f"{message}; retried — {verified}"

        results.append((n, ok, message))
        if on_step:
            on_step(n, ok, message)
        if not ok:
            break
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--run", action="store_true", help="actually do it")
    args = ap.parse_args()

    procedure = load(args.trace)
    if not args.run:
        print(plan(procedure))
        raise SystemExit(0)

    for n, ok, message in run(procedure):
        print(f"  {'ok ' if ok else 'STOP'} {n:>2}. {message}")
