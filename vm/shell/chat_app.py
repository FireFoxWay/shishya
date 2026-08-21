#!/usr/bin/env python3
"""
Shishya — the dashboard you talk to.

Everything else here is a tool you operate: you choose Training Data, you
choose Make a Document. This is the opposite. You say what you want in
your own words and it decides what to do with your material — answer from
it, build a spreadsheet, draft a document, put together a deck, or write
and run a program to work something out.

That decision is the whole point of this app. The doing was already built
and tested; what was missing was something that chooses, which is the
difference between a toolbox and a colleague.

── Why it chooses once per turn ────────────────────────────────────────────

A model this size, left to run a multi-step loop, wanders. It calls a tool,
misreads the result, calls another, and three steps later is confidently
doing the wrong job. So each turn is a single constrained choice — the same
schema-shaped generation that already produces valid spreadsheets — followed
by a known code path. Less clever, far more likely to work in front of
somebody who matters.
"""

import json
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
import make_app        # noqa: E402
from training_app import Library, SYSTEM as ANSWER_SYSTEM   # noqa: E402

RUN_TIMEOUT = 60

DECIDE = {
    "type": "object",
    "properties": {
        "action": {"type": "string",
                   "enum": ["answer", "spreadsheet", "document", "deck", "code", "clarify"]},
        "because": {"type": "string"},
        "brief": {"type": "string"},
    },
    "required": ["action", "because", "brief"],
}

DECIDE_SYSTEM = """You decide what to do with a request about the user's own documents.

Choose exactly one:
  answer      — any question about rules, policy, eligibility, or what a
                particular record says. This is the default for questions.
                Use it even when the question describes a specific case the
                documents do not name — working out what the rules say about
                a case IS answering.
  spreadsheet — they asked for a table or data file (.xlsx)
  document    — they asked for prose: a note, letter, report, brief (.docx)
  deck        — they asked for slides (.pptx)
  code        — the answer is a number that has to be counted, totalled,
                filtered or ranked across many rows. You are unreliable doing
                that by eye, so write a program instead. Looking up one record
                is not this — that is answer.
  clarify     — you genuinely cannot tell what they are asking for. Almost
                never the right choice. If you could make a reasonable
                attempt, make it. Never use clarify merely because the
                documents might not contain the answer; try, and say so if
                they do not.

"because" is one short sentence to the user saying what you are about to do.
"brief" restates the job precisely for whoever carries it out.
Answer as JSON only."""


CODE_SYSTEM = (
    "You write short, complete Python 3 scripts. Output code only — no "
    "explanation, no markdown fences. Python 3 on Linux with pandas, "
    "openpyxl, python-docx and python-pptx available. Build paths with "
    "pathlib — Path.home() / 'shared' / 'training' / '<name>' — never a "
    "string starting with ~. Print the result. Under 40 lines."
)


class ChatApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Shishya")
        self.set_default_size(880, 760)
        self.connect("destroy", Gtk.main_quit)
        self.library = None
        self.busy = False
        self.history = []

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        bar = Gtk.Box(spacing=10, margin=12)
        title = Gtk.Label(xalign=0)
        title.set_markup("<b>Shishya</b>")
        bar.pack_start(title, False, False, 0)
        self.subtitle = Gtk.Label(xalign=0)
        self.subtitle.set_opacity(.65)
        bar.pack_start(self.subtitle, True, True, 0)
        reload_btn = Gtk.Button(label="Reread material")
        reload_btn.get_accessible().set_name("Reread material")
        reload_btn.connect("clicked", lambda _b: self.read_material())
        bar.pack_end(reload_btn, False, False, 0)
        root.pack_start(bar, False, False, 0)

        # ── conversation ──
        self.thread = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                              margin=14)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.thread)
        self.scroll = scroll
        root.pack_start(scroll, True, True, 0)

        # ── say something ──
        row = Gtk.Box(spacing=8, margin=12)
        self.entry = Gtk.Entry(
            placeholder_text="Tell me what you need — in your own words")
        self.entry.get_accessible().set_name("Message")
        self.entry.connect("activate", self.on_send)
        row.pack_start(self.entry, True, True, 0)
        self.send = Gtk.Button(label="Send")
        self.send.get_accessible().set_name("Send")
        self.send.connect("clicked", self.on_send)
        row.pack_end(self.send, False, False, 0)
        root.pack_start(row, False, False, 0)

        self.read_material()
        self.say("shishya",
                 "I've read everything in your Training Data folder. Tell me what "
                 "you need and I'll work out how to make it — an answer, a "
                 "spreadsheet, a document, a deck, or a program if the answer has "
                 "to be counted out of the data.")

    # ── material ────────────────────────────────────────────────────────────

    def read_material(self):
        self.library = Library()
        names = []
        common.TRAINING.mkdir(parents=True, exist_ok=True)
        for p in sorted(common.TRAINING.iterdir()):
            if p.is_file() and not p.name.startswith("."):
                self.library.add(p)
                names.append(p.name)
        self.files = names
        self.subtitle.set_text(
            f"{len(names)} documents · {len(self.library.chunks)} pieces"
            if names else "no material yet — put files in Training Data")

    # ── conversation view ───────────────────────────────────────────────────

    def say(self, who, text, kind=""):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        label = Gtk.Label(xalign=0)
        label.set_markup(f"<small><b>{'You' if who == 'you' else 'Shishya'}</b></small>")
        label.set_opacity(.55)
        box.pack_start(label, False, False, 0)

        body = Gtk.Label(xalign=0, label=text)
        # Named so the panel can read replies back without mistaking the
        # user's own message — every bubble is a label otherwise.
        body.get_accessible().set_name("reply" if who != "you" else "yours")
        body.set_line_wrap(True)
        body.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        body.set_selectable(True)
        body.set_max_width_chars(88)
        if kind == "doing":
            body.set_opacity(.7)
        box.pack_start(body, False, False, 0)

        if who == "you":
            box.set_halign(Gtk.Align.END)
        self.thread.pack_start(box, False, False, 0)
        self.thread.show_all()
        GLib.idle_add(self._to_bottom)
        return body

    def _to_bottom(self):
        adj = self.scroll.get_vadjustment()
        adj.set_value(adj.get_upper())
        return False

    # ── the turn ────────────────────────────────────────────────────────────

    def on_send(self, _w):
        if self.busy:
            return
        text = self.entry.get_text().strip()
        if not text:
            return
        self.entry.set_text("")
        self.say("you", text)
        self.busy = True
        self.send.set_sensitive(False)
        common.set_state("working")
        self.working = self.say("shishya", "Thinking about how to do that…", "doing")
        threading.Thread(target=self.work, args=(text,), daemon=True).start()

    def work(self, request):
        try:
            plan = self.decide(request)
        except Exception as e:
            return GLib.idle_add(self.finish, f"I couldn't work out how to do that: {e}")

        GLib.idle_add(self.update, plan.get("because", "Working on it…"))
        action = plan.get("action", "answer")
        brief = plan.get("brief") or request

        try:
            if action == "clarify":
                reply = brief
            elif action == "code":
                reply = self.by_code(brief)
            elif action in ("spreadsheet", "document", "deck"):
                reply = self.by_document(action, brief)
            else:
                reply = self.by_answer(brief)
        except Exception as e:
            reply = f"That didn't work: {type(e).__name__}: {e}"

        GLib.idle_add(self.finish, reply)

    # ── the obvious cases, decided without asking ───────────────────────────
    # The model is good at reading a request and bad at holding a six-way
    # choice steady. Asked twice whether "can a student with 68% attendance
    # sit the exam" was a question, it said clarify once and spreadsheet
    # once — a question it answers well, routed to a refusal and then to a
    # file. So the shapes that are unambiguous in English are settled in
    # English, and the model is asked only about the rest.

    COUNTING = ("how many", "how much", "count ", "total ", "sum ", "average",
                "how often", "per category", "each category", "breakdown",
                "most ", "least ", "highest", "lowest", "rank", "top ")
    ASKING = ("can ", "could ", "is ", "are ", "does ", "do ", "did ", "should ",
              "what ", "which ", "who ", "when ", "why ", "where ", "how ")
    MAKING = ("make", "build", "create", "draft", "write", "produce", "prepare",
              "give me", "put together")

    def shortcut(self, request):
        """A settled action, or None to let the model choose."""
        q = request.lower().strip()
        wants_file = any(v in q for v in self.MAKING)

        # Counting beats everything: it is the one thing to never do by eye.
        if any(w in q for w in self.COUNTING) and not wants_file:
            return {"action": "code",
                    "because": "That needs counting across the data, so I'll write "
                               "a program to do it exactly.",
                    "brief": request}

        if not wants_file and (q.endswith("?") or q.startswith(self.ASKING)):
            return {"action": "answer",
                    "because": "Let me check your documents.",
                    "brief": request}
        return None

    def decide(self, request):
        settled = self.shortcut(request)
        if settled:
            return settled
        recent = "\n".join(f"- {h}" for h in self.history[-3:])
        prompt = (f"The user's documents are: {', '.join(self.files) or 'none yet'}\n"
                  + (f"Recently:\n{recent}\n" if recent else "")
                  + f"\nRequest: {request}")
        return json.loads(common.ask(prompt, system=DECIDE_SYSTEM,
                                     schema=DECIDE, budget=1024))

    # ── the four ways of doing it ───────────────────────────────────────────

    def by_answer(self, brief):
        found = self.library.search(brief, k=4)
        if not found:
            return "I can't find anything about that in your material."
        passages = "\n\n".join(f"[from {s}]\n{t}" for s, t in found)
        answer = common.ask(f"PASSAGES:\n{passages}\n\nQUESTION: {brief}",
                            system=ANSWER_SYSTEM)
        sources = sorted({s.split(" — ")[0] for s, _ in found})
        self.history.append(f"answered: {brief}")
        return f"{answer.strip()}\n\nRead from: {', '.join(sources)}"

    def by_document(self, action, brief):
        kind = {"spreadsheet": "Spreadsheet", "document": "Document",
                "deck": "Presentation"}[action]
        found = self.library.search(brief, k=10)
        passages = "\n\n".join(f"[from {s}]\n{t}" for s, t in found)
        prompt = (f"{make_app.ASKS[kind]}\n\nWHAT IS NEEDED:\n{brief}\n\n"
                  f"SOURCE MATERIAL — build from these facts and invent no "
                  f"others:\n{passages}\n\nGive it a short filename, no extension.")
        spec = json.loads(common.ask(prompt, schema=make_app.SCHEMAS[kind], budget=4096))
        path = make_app.WRITERS[kind](spec)
        self.history.append(f"made {path.name}")
        return (f"Made {path.name} — it's in your Work folder.\n"
                f"Built from: {', '.join(sorted({s.split(' — ')[0] for s, _ in found}))}")

    def by_code(self, brief):
        """Counting, totalling and filtering go through a program.

        The model is unreliable doing arithmetic across rows by eye — it
        misses rows and occasionally invents a figure. Code that reads the
        file is exact, and the code is on screen to be checked.
        """
        listing = describe_material()
        code = repair_paths(strip_fences(common.ask(
            f"{listing}\n\nWrite a Python script that: {brief}",
            system=CODE_SYSTEM, budget=6144)))
        if not code.strip() or code.lstrip().startswith("I ran out of room"):
            return "I couldn't write a program for that. Try narrowing it down."

        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "job.py"
            script.write_text(code)
            try:
                p = subprocess.run([sys.executable, str(script)],
                                   capture_output=True, text=True,
                                   timeout=RUN_TIMEOUT, cwd=str(Path.home()))
                out = (p.stdout or "").strip()
                err = (p.stderr or "").strip()
            except subprocess.TimeoutExpired:
                out, err = "", f"it was still running after {RUN_TIMEOUT}s"

        self.history.append(f"computed: {brief}")
        if err and not out:
            return (f"I wrote a program and it failed:\n\n{code}\n\n{err}")
        return (f"I worked it out with a program:\n\n{out}\n\n"
                f"— here is what I ran, so you can check it —\n\n{code}")

    # ── finishing ───────────────────────────────────────────────────────────

    def update(self, text):
        self.working.set_text(text)
        return False

    def finish(self, reply):
        self.say("shishya", reply)
        self.busy = False
        self.send.set_sensitive(True)
        common.set_state("idle")
        self.entry.grab_focus()
        return False


def describe_material():
    lines = []
    for p in sorted(common.TRAINING.iterdir())[:8]:
        if not p.is_file() or p.name.startswith("."):
            continue
        entry = f"  {common.TRAINING}/{p.name}"
        if p.suffix.lower() in (".xlsx", ".xlsm"):
            try:
                from openpyxl import load_workbook
                wb = load_workbook(p, read_only=True)
                row = next(wb.worksheets[0].iter_rows(max_row=1, values_only=True))
                entry += f"\n      columns: {', '.join(str(c) for c in row if c)}"
                wb.close()
            except Exception:
                pass
        lines.append(entry)
    return ("These files exist — use these exact paths and column names:\n"
            + "\n".join(lines)) if lines else "There are no files yet."


def repair_paths(code):
    """Point filenames at files that exist.

    Given "01_20Retail_20Inventory.xlsx" the model wrote
    "01_20Retail_Inventory.xlsx" — one fragment dropped. The script then fails
    on a missing file, which reads as the whole tool being broken rather than
    as a typo. Any quoted name ending in a document extension that does not
    exist is matched against the real ones and replaced when there is a clear
    best match.
    """
    import difflib
    import re

    real = [p.name for p in common.TRAINING.iterdir() if p.is_file()]
    real += [p.name for p in common.WORK.iterdir() if p.is_file()] if common.WORK.exists() else []
    if not real:
        return code

    def swap(m):
        quote, name = m.group(1), m.group(2)
        if name in real:
            return m.group(0)
        close = difflib.get_close_matches(name, real, n=1, cutoff=0.6)
        return f"{quote}{close[0]}{quote}" if close else m.group(0)

    return re.sub(r"(['\"])([^'\"/]+\.(?:xlsx|xlsm|csv|docx|pptx|pdf|txt|md))\1",
                  swap, code)


def strip_fences(text):
    import re
    m = re.search(r"```(?:python)?\s*([\s\S]*?)```", text)
    return (m.group(1) if m else text).strip()


if __name__ == "__main__":
    ChatApp().show_all()
    Gtk.main()
