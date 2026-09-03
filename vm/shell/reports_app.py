#!/usr/bin/env python3
"""
Reports — hand over performance files, get back charts and findings.

The principal's app. A school's term register goes in; what comes out is the
average per class, the trend across the months, the best and worst — as
pictures on screen, and as report.html plus a PNG per chart in the Work
folder, ready to be sent to anyone.

The engine is vm/reporter.py, shared with the panel's Make-a-report button:
one report generator, two front doors. The shape of the report is written
code and the model makes exactly one bounded decision per table — which
column names the groups, which hold the marks — because a report a principal
signs cannot be improvised (the reporter's docstring carries the full
argument).
"""

import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk   # noqa: E402

import common   # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import reporter   # noqa: E402  — tables_from, by_model, by_heuristic, chart_table, html_report

CHARTABLE = {".xlsx", ".xlsm", ".csv", ".tsv", ".docx"}
REPORTS = common.WORK / "Reports"

# Told beforehand, here, because this is the window someone is already in when
# they think "and I want this every evening". The panel's scheduler re-reads
# the same file within the minute; nothing has to be restarted.
SCHEDULES = common.SHARED / ".schedules.json"
AT = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

WHAT = [("audit.py",    "Shop audit — takings, profit of the day, month, stock"),
        ("alerts.py",   "Alert check — what needs attention, without asking"),
        ("backup.py",   "Books backup — a dated copy of the shop's books"),
        ("reporter.py", "Report from the files in Work and Inbox")]


class ReportsApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Reports")
        self.set_default_size(940, 660)
        self.connect("destroy", Gtk.main_quit)
        self.busy = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        # ── name it, make it ──
        bar = Gtk.Box(spacing=8, margin=14)
        self.title_box = Gtk.Entry(placeholder_text="What is this report called?")
        self.title_box.get_accessible().set_name("Report title")
        bar.pack_start(self.title_box, True, True, 0)
        self.go = Gtk.Button(label="Make the report")
        self.go.get_accessible().set_name("Make the report")
        self.go.connect("clicked", self.on_go)
        bar.pack_end(self.go, False, False, 0)
        root.pack_start(bar, False, False, 0)

        self.status = Gtk.Label(xalign=0, margin_start=14, margin_end=14)
        self.status.set_opacity(.7)
        self.status.get_accessible().set_name("Status")
        root.pack_start(self.status, False, False, 0)

        # ── files left, report right ──
        split = Gtk.Paned(margin=14)
        root.pack_start(split, True, True, 0)

        self.checks = {}
        files_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left = Gtk.ScrolledWindow()
        left.set_size_request(280, -1)
        left.add(files_box)
        split.pack1(left, False, False)
        self.files_box = files_box

        shown = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                        margin=10)
        right = Gtk.ScrolledWindow()
        right.add(shown)
        split.pack2(right, True, False)
        self.shown = shown

        # ── tell it to happen by itself ──
        when = Gtk.Box(spacing=8, margin_start=14, margin_end=14, margin_bottom=10)
        when.pack_start(Gtk.Label(label="Every"), False, False, 0)

        self.days = Gtk.ComboBoxText()
        for value, label in (("daily", "day"), ("weekdays", "weekday")):
            self.days.append(value, label)
        self.days.set_active_id("daily")
        self.days.get_accessible().set_name("Which days")
        when.pack_start(self.days, False, False, 0)

        when.pack_start(Gtk.Label(label="at"), False, False, 0)
        self.at = Gtk.Entry(text="18:00", width_chars=6)
        self.at.get_accessible().set_name("Time of day")
        when.pack_start(self.at, False, False, 0)

        self.what = Gtk.ComboBoxText()
        for runner, label in WHAT:
            self.what.append(runner, label)
        self.what.set_active_id("audit.py")
        self.what.get_accessible().set_name("What to run")
        when.pack_start(self.what, True, True, 0)

        for label, handler in (("Turn it off", self.on_unschedule),
                               ("Schedule it", self.on_schedule)):
            b = Gtk.Button(label=label)
            b.get_accessible().set_name(label)
            b.connect("clicked", handler)
            when.pack_end(b, False, False, 0)
        root.pack_start(when, False, False, 0)

        self.scheduled = Gtk.Label(xalign=0, margin_start=14, margin_end=14,
                                   margin_bottom=12)
        self.scheduled.set_opacity(.7)
        self.scheduled.get_accessible().set_name("Scheduled")
        root.pack_start(self.scheduled, False, False, 0)

        self.reload_files()
        self.show_schedules()
        self.status.set_text("Tick the files, name the report, press Make the report.")

    # ── scheduling ──

    def read_schedules(self):
        try:
            found = json.loads(SCHEDULES.read_text())
            return found if isinstance(found, list) else []
        except (OSError, ValueError):
            return []          # no schedule is a valid state, not an error

    def write_schedules(self, items):
        tmp = SCHEDULES.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False))
        tmp.replace(SCHEDULES)          # whole file, renamed — never half a schedule

    def show_schedules(self):
        items = [i for i in self.read_schedules() if i.get("enabled", True)]
        if not items:
            self.scheduled.set_text("Nothing is scheduled — it runs only when "
                                    "you press Make the report.")
            return
        self.scheduled.set_text("Scheduled:  " + "   ·   ".join(
            f"{i.get('label')} every "
            f"{'weekday' if i.get('days') == 'weekdays' else 'day'} at {i.get('at')}"
            for i in items))

    def on_schedule(self, _b):
        at = self.at.get_text().strip()
        if not AT.match(at):
            self.status.set_text("Give the time as HH:MM on a 24-hour clock — 18:00.")
            return
        runner = self.what.get_active_id()
        label = dict(WHAT)[runner].split("—")[0].strip()
        items = [i for i in self.read_schedules() if i.get("runner") != runner]
        items.append({"runner": runner, "label": label, "at": at,
                      "days": self.days.get_active_id(), "enabled": True,
                      "last": ""})
        self.write_schedules(items)
        self.show_schedules()
        # Say what will happen, not "saved". A schedule nobody can picture is
        # a schedule nobody trusts, and this one runs with nobody watching.
        every = "weekday" if self.days.get_active_id() == "weekdays" else "day"
        self.status.set_text(f"{label} will run by itself at {at}, every {every}. "
                             f"The results appear in the panel, and the files "
                             f"land in the job's folder.")

    def on_unschedule(self, _b):
        runner = self.what.get_active_id()
        items = [i for i in self.read_schedules() if i.get("runner") != runner]
        self.write_schedules(items)
        self.show_schedules()
        self.status.set_text("Turned off. It will only run when you ask.")

    # ── files ──

    def reload_files(self):
        for child in self.files_box.get_children():
            self.files_box.remove(child)
        self.checks = {}
        # Work and Inbox ticked by default — those are the files someone put
        # here to be worked on. Training is reference material, so it is
        # offered but off: charting the pharmacy export because a marks sheet
        # was wanted would be a surprise, and surprises are for Findings.
        for folder, ticked in ((common.WORK, True), (common.SHARED / "inbox", True),
                               (common.TRAINING, False)):
            files = sorted(p for p in folder.glob("*") if p.is_file()
                           and p.suffix.lower() in CHARTABLE
                           and not p.name.startswith("."))
            if not files:
                continue
            head = Gtk.Label(xalign=0, margin_top=8, margin_start=6)
            head.set_markup(f"<small><b>{folder.name.upper()}</b></small>")
            self.files_box.pack_start(head, False, False, 0)
            for p in files:
                check = Gtk.CheckButton(label=p.name)
                check.set_active(ticked)
                check.get_accessible().set_name(p.name)
                self.files_box.pack_start(check, False, False, 0)
                self.checks[p] = check
        self.files_box.show_all()

    # ── making ──

    def on_go(self, _b):
        if self.busy:
            return
        picked = [p for p, c in self.checks.items() if c.get_active()]
        if not picked:
            self.status.set_text("Nothing is ticked — pick at least one file.")
            return
        self.busy = True
        self.go.set_sensitive(False)
        for child in self.shown.get_children():
            self.shown.remove(child)
        common.set_state("working")
        title = self.title_box.get_text().strip() or "Report"
        threading.Thread(target=self.make, args=(picked, title),
                         daemon=True).start()

    def make(self, picked, title):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = REPORTS / stamp
        out.mkdir(parents=True, exist_ok=True)
        sections, findings, skipped = [], [], []
        for path in picked:
            GLib.idle_add(self.say, f"Reading {path.name}…")
            try:
                tables = reporter.tables_from(path)
            except Exception as e:
                skipped.append(f"{path.name} ({type(e).__name__})")
                continue
            if not tables:
                skipped.append(path.name)
                continue
            for name, frame in tables:
                GLib.idle_add(self.say, f"Charting {name}…")
                roles = reporter.by_model(name, frame) or reporter.by_heuristic(frame)
                charts = []
                try:
                    reporter.chart_table(name, frame, roles, out, charts, findings)
                except Exception:
                    pass          # one bad table must not sink the report
                if charts:
                    sections.append((name, charts))
                else:
                    skipped.append(name)

        if not sections:
            GLib.idle_add(self.done, None, [],
                          "Nothing chartable in those files — I need a table "
                          "with numbers in it.")
            return
        (out / "report.html").write_text(
            reporter.html_report(title, sections, findings, skipped,
                                 "Made by Shishya on this machine, from the "
                                 "Reports app."))
        pngs = sorted(out.glob("*.png"))
        GLib.idle_add(self.done, out, findings + [f"(not charted: {s})" for s in skipped],
                      f"Done — report.html and {len(pngs)} chart(s) in "
                      f"Work/Reports/{out.name}.", pngs)

    # ── showing ──

    def say(self, text):
        self.status.set_text(text)
        return False

    def done(self, out, findings, message, pngs=()):
        self.status.set_text(message)
        self.busy = False
        self.go.set_sensitive(True)
        common.set_state("idle")

        if findings:
            text = Gtk.Label(xalign=0, margin_bottom=4)
            text.set_line_wrap(True)
            text.set_text("\n".join(f"• {f}" for f in findings[:10]))
            text.get_accessible().set_name("Findings")
            self.shown.pack_start(text, False, False, 0)
        for png in pngs:
            try:
                pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(png), 600, -1, True)
            except Exception:
                continue
            self.shown.pack_start(Gtk.Image.new_from_pixbuf(pix), False, False, 0)
        if out is not None:
            open_btn = Gtk.Button(label="Open the folder")
            open_btn.get_accessible().set_name("Open the folder")
            open_btn.connect("clicked", lambda _b: subprocess.Popen(
                [sys.executable, str(Path(__file__).parent / "files_app.py"), str(out)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            self.shown.pack_start(open_btn, False, False, 0)
        self.shown.show_all()
        return False


if __name__ == "__main__":
    ReportsApp().show_all()
    Gtk.main()
