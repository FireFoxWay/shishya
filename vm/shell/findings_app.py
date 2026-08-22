#!/usr/bin/env python3
"""
Findings — what is wrong with your data, without being asked.

Everything else here is reactive: you ask, it answers. This is the opposite.
It reads whatever spreadsheets you have given it and goes looking for the
things nobody thought to ask about — the same way the duplicate supplier
turned up, which is still the most useful thing this project has produced
and which nobody requested.

── Why each check is a generated program ───────────────────────────────────

The model is unreliable at arithmetic across rows and exact at writing code
that does the arithmetic. So a check is a short, bounded brief — "find near
duplicate values in text columns" — turned into a program, run, and reported
with the program attached. Every finding is therefore checkable by the person
being told about it, which is the whole difference between a tool you can
adopt and one you have to trust.

Bounded rather than open-ended for the same reason the chat decides once per
turn: a model this size asked to "analyse this data" wanders. Asked six
specific questions, it answers six specific questions.
"""

import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango   # noqa: E402

import common          # noqa: E402
from chat_app import describe_material, repair, usable, CODE_SYSTEM   # noqa: E402

RUN_TIMEOUT = 90

# Each check is a title, a brief, and why a human should care. The briefs are
# written to be answerable by a program rather than by judgement.
PROTOCOL = (
    "\n\nFirst line of output must be exactly 'FINDINGS: n' where n is how "
    "many problems were found — 0 if none. Then the details, one per line, "
    "each readable by someone who has never seen the file: name the column "
    "and the values in plain text, not as Python tuples or dict reprs."
)

CHECKS = [
    ("Duplicate names wearing different capitals",
     "For each text column with fewer than 2000 distinct values, find values "
     "that are identical when lowercased and stripped but differ as written. "
     "Print the column, the variants, and how many rows each variant has. "
     "Only report columns that actually have such collisions. " + PROTOCOL,
     "The same supplier, customer or product counted twice splits every total "
     "that involves it."),

    ("Columns that are almost entirely empty",
     "For every column, count how many rows are empty, None, zero, 'N/A' or "
     "blank. Print any column where that is above 80% of rows, with the "
     "percentage, sorted worst first. " + PROTOCOL,
     "A column nobody fills is either a broken process or a field that should "
     "be removed."),

    ("Numbers far outside the normal range",
     "For each numeric column with more than 20 non-zero values, compute the "
     "median and the interquartile range, and report values more than 6 "
     "interquartile ranges from the median. Print at most 3 examples per "
     "column with an identifying label from the first text column. " + PROTOCOL,
     "One misplaced decimal point in a price or a quantity distorts every "
     "figure computed from it."),

    ("Rows that duplicate an identifier",
     "Find columns whose name suggests an identifier (contains 'id', 'code', "
     "'sku', 'no' or 'number') and report any value appearing in more than "
     "one row, with the count. At most 10 examples. " + PROTOCOL,
     "An identifier that repeats means two records that should be one, or a "
     "merge that went wrong."),

    ("Things that stopped moving",
     "If the sheet has columns whose headers are dates, treat them as a time "
     "series per row. Report rows that had activity in the earlier half of "
     "the period and none at all in the most recent quarter. Print at most 10 "
     "with a label from the first text column. " + PROTOCOL,
     "Stock that sold and then stopped is money sitting on a shelf."),

    ("Money tied up in things that never moved",
     "If the sheet has a quantity-on-hand column and a price or cost column, "
     "compute quantity times price for rows whose activity columns are all "
     "zero, and print the total and the ten largest with a label. " + PROTOCOL,
     "The single number that tells you how much working capital is asleep."),
]


class FindingsApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Findings")
        self.set_default_size(880, 720)
        self.connect("destroy", Gtk.main_quit)
        self.running = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        bar = Gtk.Box(spacing=10, margin=14)
        title = Gtk.Label(xalign=0)
        title.set_markup("<b>Findings</b>")
        bar.pack_start(title, False, False, 0)
        self.status = Gtk.Label(xalign=0)
        self.status.set_opacity(.68)
        self.status.set_text("Looks through your spreadsheets for things nobody asked about.")
        bar.pack_start(self.status, True, True, 0)
        self.go = Gtk.Button(label="Look through my data")
        self.go.get_accessible().set_name("Look through my data")
        self.go.connect("clicked", self.on_go)
        bar.pack_end(self.go, False, False, 0)
        root.pack_start(bar, False, False, 0)

        self.progress = Gtk.ProgressBar()
        self.progress.set_margin_start(14)
        self.progress.set_margin_end(14)
        self.progress.set_show_text(True)
        root.pack_start(self.progress, False, False, 0)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=14)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.body)
        self.scroll = scroll
        root.pack_start(scroll, True, True, 0)

    # ── running the checks ──────────────────────────────────────────────────

    def on_go(self, _b):
        if self.running:
            return
        self.running = True
        self.go.set_sensitive(False)
        for child in self.body.get_children():
            self.body.remove(child)
        common.set_state("working")
        threading.Thread(target=self.work, daemon=True).start()

    def work(self):
        listing = describe_material()
        found = 0
        for i, (title, brief, why) in enumerate(CHECKS, 1):
            GLib.idle_add(self.progress.set_fraction, (i - 1) / len(CHECKS))
            GLib.idle_add(self.progress.set_text, f"{i} of {len(CHECKS)} — {title}")
            GLib.idle_add(self.status.set_text, f"Checking: {title.lower()}")

            try:
                code = repair(common.ask(
                    f"{listing}\n\nWrite a Python script that: {brief}",
                    system=CODE_SYSTEM, budget=5120, job="code"))
                out, err = ("", "no code") if not usable(code) else run(code)
            except Exception as e:
                code, out, err = "", "", f"{type(e).__name__}: {e}"

            verdict = read_verdict(out)
            if verdict == "nothing":
                GLib.idle_add(self.add_clear, title)
            elif out:
                found += 1
                GLib.idle_add(self.add_finding, title, why, out, code)
            else:
                GLib.idle_add(self.add_failed, title, err)

        GLib.idle_add(self.finish, found)

    def finish(self, found):
        self.progress.set_fraction(1.0)
        self.progress.set_text("done")
        self.status.set_text(
            f"{found} thing{'s' if found != 1 else ''} worth a look."
            if found else "Nothing stood out. That is a good result.")
        self.go.set_sensitive(True)
        self.running = False
        common.set_state("idle")
        return False

    # ── rendering ───────────────────────────────────────────────────────────

    def card(self, accent):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        line = Gtk.Box()
        stripe = Gtk.DrawingArea()
        stripe.set_size_request(3, -1)
        stripe.connect("draw", lambda _a, cr: (cr.set_source_rgb(*accent), cr.paint()))
        line.pack_start(stripe, False, False, 0)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5,
                        margin_start=12, margin_top=2, margin_bottom=2)
        line.pack_start(inner, True, True, 0)
        box.pack_start(line, False, False, 0)
        self.body.pack_start(box, False, False, 0)
        return inner

    def add_finding(self, title, why, out, code):
        inner = self.card((0.83, 0.33, 0.13))
        head = Gtk.Label(xalign=0)
        head.set_markup(f"<b>{esc(title)}</b>")
        inner.pack_start(head, False, False, 0)

        reason = Gtk.Label(label=why, xalign=0)
        reason.set_line_wrap(True); reason.set_max_width_chars(88); reason.set_opacity(.68)
        inner.pack_start(reason, False, False, 0)

        result = Gtk.Label(label=out.strip()[:2500], xalign=0, selectable=True)
        result.set_line_wrap(True)
        result.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        result.set_max_width_chars(94)
        result.modify_font(Pango.FontDescription("Monospace 9"))
        inner.pack_start(result, False, False, 0)

        # The program is folded away but present. A finding you cannot check is
        # just an assertion, and this is the difference.
        show = Gtk.Expander(label="Show the program that found this")
        show.get_accessible().set_name("Show the program")
        prog = Gtk.Label(label=code.strip(), xalign=0, selectable=True)
        prog.set_line_wrap(True)
        prog.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        prog.set_max_width_chars(96)
        prog.modify_font(Pango.FontDescription("Monospace 9"))
        prog.set_opacity(.75)
        show.add(prog)
        inner.pack_start(show, False, False, 0)

        self.body.show_all()
        return False

    def add_clear(self, title):
        inner = self.card((0.17, 0.54, 0.24))
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(f"{esc(title)} — <span alpha='60%'>nothing found</span>")
        inner.pack_start(lbl, False, False, 0)
        self.body.show_all()
        return False

    def add_failed(self, title, err):
        inner = self.card((0.45, 0.45, 0.48))
        lbl = Gtk.Label(xalign=0)
        last = (err or "").strip().splitlines()
        lbl.set_markup(f"{esc(title)} — <span alpha='55%'>could not check: "
                       f"{esc(last[-1][:90] if last else 'no output')}</span>")
        lbl.set_line_wrap(True); lbl.set_max_width_chars(92)
        inner.pack_start(lbl, False, False, 0)
        self.body.show_all()
        return False


# ── helpers ─────────────────────────────────────────────────────────────────

def run(code):
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "check.py"
        script.write_text(code)
        try:
            p = subprocess.run([sys.executable, str(script)],
                               capture_output=True, text=True,
                               timeout=RUN_TIMEOUT, cwd=str(Path.home()))
            return (p.stdout or "").strip(), (p.stderr or "").strip()
        except subprocess.TimeoutExpired:
            return "", f"still running after {RUN_TIMEOUT}s"


def read_verdict(out):
    """How many problems a check found, read from its own first line.

    Inferring this from prose failed immediately: a check that printed "none
    found" once per column produced a wall of nothing that was reported as a
    finding. The script is now asked to say the number itself.
    """
    text = (out or "").strip()
    if not text:
        return "failed"
    first = text.splitlines()[0].strip().lower()
    if first.startswith("findings:"):
        try:
            return "found" if int(first.split(":", 1)[1].strip().split()[0]) > 0 else "nothing"
        except (ValueError, IndexError):
            pass
    # Older wording, and a fallback for a script that ignored the instruction.
    if first in ("none found", "not applicable", "none"):
        return "nothing"
    return "found"


def esc(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


if __name__ == "__main__":
    FindingsApp().show_all()
    Gtk.main()
