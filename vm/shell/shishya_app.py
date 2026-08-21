#!/usr/bin/env python3
"""
Shishya — teach a lesson, read what was learned, run it.

The window a judge spends the most time looking at, so the procedure is the
whole left-hand side and everything else is a button. The point being made
is: this is what it learned, in words, and you may change them.
"""

import json
import subprocess
import sys
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk   # noqa: E402

import common   # noqa: E402

RECORDER = Path("/opt/shishya/vm/recorder.py")


class ShishyaApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Shishya")
        self.set_default_size(880, 620)
        self.connect("destroy", Gtk.main_quit)
        self.recording = None

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        # ── teach ──
        bar = Gtk.Box(spacing=8, margin=14)
        self.what = Gtk.Entry(placeholder_text="What are you about to teach me?")
        self.what.get_accessible().set_name("Lesson name")
        bar.pack_start(self.what, True, True, 0)

        self.teach = Gtk.Button(label="Teach me")
        self.teach.get_accessible().set_name("Teach me")
        self.teach.connect("clicked", self.on_teach)
        bar.pack_end(self.teach, False, False, 0)
        root.pack_start(bar, False, False, 0)

        self.status = Gtk.Label(xalign=0, margin_start=14, margin_end=14)
        self.status.set_opacity(.7)
        self.status.set_text("Name the job, press Teach me, then do it once.")
        root.pack_start(self.status, False, False, 0)

        # ── lessons / procedure ──
        split = Gtk.Paned(margin=14)
        root.pack_start(split, True, True, 0)

        self.lessons = Gtk.ListBox()
        self.lessons.get_accessible().set_name("Lessons")
        self.lessons.connect("row-selected", self.on_pick)
        left = Gtk.ScrolledWindow()
        left.set_size_request(230, -1)
        left.add(self.lessons)
        split.pack1(left, False, False)

        self.text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD, left_margin=12,
                                 right_margin=12, top_margin=10)
        self.text.get_accessible().set_name("Procedure")
        right = Gtk.ScrolledWindow()
        right.add(self.text)
        split.pack2(right, True, False)

        # ── act ──
        feet = Gtk.Box(spacing=8, margin=14)
        for label, handler in (("Save changes", self.on_save), ("Run it", self.on_run)):
            b = Gtk.Button(label=label)
            b.get_accessible().set_name(label)
            b.connect("clicked", handler)
            feet.pack_end(b, False, False, 0)
        root.pack_start(feet, False, False, 0)

        self.reload()

    # ── recording ──

    def on_teach(self, _b):
        if self.recording:
            subprocess.run([sys.executable, str(RECORDER), "stop"],
                           capture_output=True)
            self.recording = None
            self.teach.set_label("Teach me")
            self.status.set_text("Got it. Working out what you did…")
            common.set_state("working")
            threading.Thread(target=self.synthesise, daemon=True).start()
            return

        name = self.what.get_text().strip() or "untitled"
        self.recording = subprocess.Popen(
            [sys.executable, str(RECORDER), "start", name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.teach.set_label("I'm done")
        self.status.set_text("Watching. Do the job once, then press I'm done.")
        common.set_state("working")

    def synthesise(self):
        """Synthesis runs on the host, where the model is. The sandbox asks
        for it rather than doing it, which keeps the one model process on the
        GPU instead of a second one on emulated CPU in here."""
        latest = newest(common.TRACES)
        if not latest:
            return GLib.idle_add(self.after, "Nothing was recorded — check that "
                                             "the app you used exposes an accessibility tree.")
        try:
            out = subprocess.run(
                ["python3", "/opt/shishya/host/synth.py", str(latest)],
                capture_output=True, text=True, timeout=900)
            msg = "Learned it." if out.returncode == 0 else out.stderr.strip()
        except subprocess.SubprocessError as e:
            msg = f"Could not work it out: {e}"
        GLib.idle_add(self.after, msg)

    def after(self, message):
        self.status.set_text(message)
        common.set_state("idle")
        self.reload()
        return False

    # ── lessons ──

    def reload(self):
        for row in self.lessons.get_children():
            self.lessons.remove(row)
        self.found = []
        common.TRACES.mkdir(parents=True, exist_ok=True)
        for proc_file in sorted(common.TRACES.glob("*/procedure.json"), reverse=True):
            try:
                proc = json.loads(proc_file.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            self.found.append((proc_file, proc))
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=proc.get("title", proc_file.parent.name),
                              xalign=0, margin=10)
            label.set_line_wrap(True)
            row.add(label)
            self.lessons.add(row)
        self.lessons.show_all()

    def on_pick(self, _box, row):
        if row is None:
            return
        path, proc = self.found[row.get_index()]
        self.text.get_buffer().set_text(render(proc))

    def on_save(self, _b):
        row = self.lessons.get_selected_row()
        if row is None:
            return
        path, proc = self.found[row.get_index()]
        buf = self.text.get_buffer()
        edited = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        # Steps are re-read from the text, so an edit here really is the
        # procedure — not a note attached to one.
        proc["steps"] = [{"n": i, "text": line.strip(), "target": {}, "verify": ""}
                         for i, line in enumerate(
                             (l for l in edited.splitlines() if l.strip()), 1)]
        proc["edited_by_hand"] = True
        path.write_text(json.dumps(proc, indent=2, ensure_ascii=False))
        self.status.set_text("Saved. That is what I will do.")

    def on_run(self, _b):
        self.status.set_text("The executor is week 4 — not built yet.")


def render(proc):
    lines = []
    for p in proc.get("parameters", []):
        lines.append(f"# {{{p['name']}}} = {p.get('example','')}")
    if lines:
        lines.append("")
    for s in proc.get("steps", []):
        lines.append(f"{s['n']}. {s['text']}")
    for w in proc.get("warnings", []):
        lines.append(f"\n! {w}")
    return "\n".join(lines)


def newest(root):
    runs = [d for d in root.glob("*") if (d / "trace.jsonl").exists()]
    return max(runs, key=lambda d: d.stat().st_mtime) if runs else None


if __name__ == "__main__":
    ShishyaApp().show_all()
    Gtk.main()
