#!/usr/bin/env python3
"""
Shishya — the recorder. Runs INSIDE the sandbox.

Watches you do a job once and writes a trace. The trace is the input to
procedure synthesis, so what we capture here decides what can be learned.

    python3 recorder.py start "verify an applicant"
    python3 recorder.py stop

── Why this records semantics, not mouse coordinates ───────────────────────

The obvious recorder logs "click at (412, 890)". That is what every macro
tool does and it is why they all shatter — move the window, resize the
column, use a different applicant, and the coordinate means nothing.

We listen to AT-SPI instead, so a step is recorded as

    focused  [entry]  "District"  in  window "Applicant Registry"

Coordinates are kept, but only as a hint for the executor when the
accessibility tree comes back empty. The tree is the truth; pixels are the
fallback. Everything downstream depends on that order.
"""

import json
import os
import signal
import sys
import time
from pathlib import Path

TRACES = Path("/home/clone/shared/traces")
PIDFILE = Path("/tmp/shishya-recorder.pid")

# Events worth a step. Deliberately short: a trace with every mouse-move in it
# buries the five decisions that actually define the task.
EVENTS = [
    "object:state-changed:focused",   # the cursor moved to a new control
    "object:text-changed:insert",     # something was typed
    "object:value-changed",           # a slider, spinner, checkbox
    "object:selection-changed",       # a list or dropdown choice
    "window:activate",                # attention moved to another app
]


def source_name(acc):
    try:
        return acc.name or ""
    except Exception:
        return ""


def role_of(acc):
    try:
        return acc.getRoleName()
    except Exception:
        return ""


def describe(acc):
    """One accessible → the fields a procedure needs to name it again later."""
    if acc is None:
        return None
    try:
        return {
            "name": acc.name or "",
            "role": acc.getRoleName(),
            # The path from the app root. This is how the executor re-finds
            # the control on a later run when the name alone is ambiguous.
            "path": ancestry(acc),
            "text": text_of(acc),
        }
    except Exception:
        # A control can vanish between the event firing and us reading it.
        # A hole in one step is survivable; a crashed recorder loses the job.
        return None


def ancestry(acc, limit=8):
    out = []
    node = acc
    while node is not None and len(out) < limit:
        try:
            out.append({"role": node.getRoleName(), "name": node.name or ""})
            node = node.parent
        except Exception:
            break
    return list(reversed(out))


def text_of(acc):
    try:
        import pyatspi
        t = acc.queryText()
        return t.getText(0, t.characterCount)[:400]
    except Exception:
        return None


class Recorder:
    def __init__(self, label):
        self.run = time.strftime("%Y%m%d-%H%M%S")
        self.dir = TRACES / self.run
        (self.dir / "steps").mkdir(parents=True, exist_ok=True)
        self.trace = open(self.dir / "trace.jsonl", "a", encoding="utf-8")
        self.n = 0
        self.last = None          # for collapsing repeated events
        self.buffer = ""          # keystrokes not yet committed
        self.typing_at = None     # where this typing began
        self.last_focus = None    # most recent focused control
        self.typed_at = 0.0       # when the last keystroke arrived
        self.write({"kind": "meta", "label": label, "run": self.run,
                    "started": time.time(), "screen": "1440x900"})

    def write(self, obj):
        self.trace.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.trace.flush()
        os.fsync(self.trace.fileno())

    def shot(self):
        """A screenshot per step — evidence for the synthesiser, and the only
        thing that can explain a step whose tree data came back empty."""
        p = self.dir / "steps" / f"{self.n:04d}.png"
        os.system(f"scrot -o -q 60 {p} 2>/dev/null")
        return p.name if p.exists() else None

    def on_event(self, e):
        try:
            # focus events fire on losing focus too; only the gain is a step
            if e.type == "object:state-changed:focused" and not e.detail1:
                return
            if self.is_noise(e):
                return
            # Moving away ends whatever was being typed. But the first
            # keystroke in a spreadsheet cell opens an editor, which fires its
            # own focus event — flushing on that split every value after its
            # first character. Anything within a moment of a keystroke is the
            # editor opening, not the person moving on.
            if (e.type == "object:state-changed:focused" and self.buffer
                    and time.time() - self.typed_at > 1.2):
                self.flush()
            if e.type == "object:state-changed:focused":
                self.last_focus = describe(e.source) or self.last_focus
            self.n += 1
            self.write({
                "kind": "step",
                "i": self.n,
                "t": round(time.time(), 3),
                "event": e.type,
                "target": describe(e.source),
                "app": getattr(e.host_application, "name", None),
                "detail": e.any_data if isinstance(e.any_data, (str, int, float)) else None,
                "shot": self.shot(),
            })
        except Exception as exc:
            self.write({"kind": "error", "i": self.n, "detail": repr(exc)})

    # ── what is not a step ──────────────────────────────────────────────────
    # AT-SPI reports every change to the interface, not every action by the
    # person. A clock relabelling itself once a second, a status line updating
    # after a save, a progress count ticking up — all arrive as
    # text-changed:insert and are indistinguishable, event-wise, from typing.
    #
    # The distinction that holds: a person can only type into something
    # editable. Labels are written to by the program, never by the user, so a
    # text change on one is the interface talking to itself.

    CHROME = {"Taskbar"}          # our own shell furniture, never the task

    # Applications whose text widgets do not advertise themselves as editable
    # even while you are typing into them. LibreOffice's cell editor is the
    # one that matters here: the editable test alone threw away every value
    # entered into a spreadsheet, which is most of what a clerk actually does.
    LOOSE_TEXT = ("soffice", "libreoffice")

    def is_noise(self, e):
        try:
            source = e.source
            if source is None:
                return True

            app = (getattr(e.host_application, "name", "") or "").lower()

            if e.type == "object:text-changed:insert":
                editable = source.getState().contains(pyatspi.STATE_EDITABLE)
                if not editable and not any(a in app for a in self.LOOSE_TEXT):
                    return True

            # Anything inside the taskbar is us, not the job being taught.
            node, depth = source, 0
            while node is not None and depth < 8:
                if (node.name or "") in self.CHROME:
                    return True
                node = node.parent
                depth += 1

            # Spreadsheets emit a selection change for every cursor movement,
            # so a single keystroke arrives as a burst of identical events on
            # the same grid. Only the first of a run says anything.
            fingerprint = (e.type, source_name(source), role_of(source))
            if fingerprint == self.last and e.type != "object:text-changed:insert":
                return True
            self.last = fingerprint
        except Exception:
            return True               # unreadable source is not a usable step
        return False

    # ── what was typed ──────────────────────────────────────────────────────
    # LibreOffice emits no text-changed event for cell entry — the value a
    # clerk types into a spreadsheet, which is most of the job, simply never
    # reaches AT-SPI. So we watch the keyboard as well and keep the text
    # ourselves, flushing it as one step when the entry is committed.
    #
    # Held rather than logged per keystroke on purpose: a trace of eleven
    # single-character events says far less than one step reading
    # typed "No - below 65%" into Cell I4.

    COMMIT = {"Return", "KP_Enter", "Tab", "ISO_Left_Tab", "Escape"}

    # X reports these by name rather than as the character they produce, so a
    # plain printable-character test drops them. Space is the one that matters:
    # without it every recorded value came out as one run-on word.
    NAMED = {"space": " ", "minus": "-", "period": ".", "comma": ",",
             "slash": "/", "percent": "%", "underscore": "_", "plus": "+",
             "equal": "=", "colon": ":", "semicolon": ";", "apostrophe": "'",
             "parenleft": "(", "parenright": ")", "at": "@", "numbersign": "#",
             "ampersand": "&", "asterisk": "*", "exclam": "!", "question": "?"}

    def on_key(self, event):
        try:
            name = event.event_string or ""
            if name in self.COMMIT:
                self.flush(committed=name != "Escape")
            elif name == "BackSpace":
                self.buffer = self.buffer[:-1]
            else:
                char = self.NAMED.get(name, name if len(name) == 1 and name.isprintable() else None)
                if char is None:
                    return False
                self.buffer += char
                self.typed_at = time.time()
                if not self.typing_at:
                    self.typing_at = self.last_focus
        except Exception:
            pass
        return False              # never swallow the keystroke

    def flush(self, committed=True):
        text, where = self.buffer, self.typing_at
        self.buffer, self.typing_at = "", None
        if not text:
            return
        self.n += 1
        self.write({
            "kind": "step",
            "i": self.n,
            "t": round(time.time(), 3),
            "event": "typed" if committed else "typed-then-cancelled",
            "target": where,
            "detail": text,
            "shot": self.shot(),
        })

    def close(self):
        self.write({"kind": "meta", "ended": time.time(), "steps": self.n})
        self.trace.close()
        print(f"{self.n} steps → {self.dir}")


def start(label):
    try:
        import pyatspi
    except ImportError:
        sys.exit("pyatspi missing — this runs inside the sandbox, not on the host")

    rec = Recorder(label)
    PIDFILE.write_text(str(os.getpid()))

    for ev in EVENTS:
        pyatspi.Registry.registerEventListener(rec.on_event, ev)

    # preemptive=False: we are observing, not intercepting. A recorder that
    # can swallow keystrokes would change the very thing it is recording.
    # This binding rejects a None mask, so every modifier combination has to
    # be named. Without shift in the list, capital letters go unrecorded.
    modifiers = [0, 1 << pyatspi.MODIFIER_SHIFT, 1 << pyatspi.MODIFIER_SHIFTLOCK]
    pyatspi.Registry.registerKeystrokeListener(
        rec.on_key, mask=modifiers, kind=(pyatspi.KEY_PRESSED_EVENT,),
        synchronous=False, preemptive=False)

    def bye(*_):
        rec.flush()
        pyatspi.Registry.deregisterEventListener(rec.on_event, *EVENTS)
        rec.close()
        PIDFILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)

    print(f"recording {rec.run} — Ctrl-C or `recorder.py stop` when done")
    pyatspi.Registry.start()


def stop():
    if not PIDFILE.exists():
        sys.exit("not recording")
    os.kill(int(PIDFILE.read_text()), signal.SIGTERM)


def probe():
    """Is the accessibility tree actually alive? The first thing to check when
    a recording comes back empty — usually GTK_MODULES didn't survive."""
    try:
        import pyatspi
    except ImportError:
        sys.exit("pyatspi missing — run this inside the sandbox")
    desktop = pyatspi.Registry.getDesktop(0)
    apps = [a.name for a in desktop if a is not None]
    print(f"{len(apps)} apps visible to AT-SPI: {apps}")
    if not apps:
        print("EMPTY — check GTK_MODULES=gail:atk-bridge in shishya-wm.service")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if cmd == "start":
        start(sys.argv[2] if len(sys.argv) > 2 else "untitled")
    elif cmd == "stop":
        stop()
    else:
        probe()
