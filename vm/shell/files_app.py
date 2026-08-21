#!/usr/bin/env python3
"""
Files — browse what the clone has.

    python3 files_app.py [folder]

There is no xdg-open in this sandbox, so opening is handled explicitly by
extension. That is a feature rather than a shortfall: the clone should not
have a general "open whatever this is" verb, and every route out of this
window is one we chose. An unknown file type is shown, not launched.
"""

import subprocess
import sys
import time
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk   # noqa: E402

import common   # noqa: E402

PLACES = [
    ("Work",          common.WORK,     "folder-documents"),
    ("Inbox",         common.SHARED / "inbox", "mail-message-new"),
    ("Training Data", common.TRAINING, "emblem-documents"),
    ("Lessons",       common.TRACES,   "folder-templates"),
]

# Spreadsheets go to our own Sheets app — instant, and it never fails to
# appear. Everything else still goes to LibreOffice.
SHEETS = {".xlsx", ".xlsm", ".csv"}
OFFICE = {".docx", ".pptx", ".ods", ".odt", ".odp", ".doc", ".xls", ".ppt"}
TEXTY = {".txt", ".md", ".json", ".log", ".csv", ".tsv", ".xml", ".html", ".py", ".jsonl"}


class FilesApp(Gtk.Window):
    def __init__(self, start=None):
        super().__init__(title="Files")
        self.set_default_size(880, 580)
        self.connect("destroy", Gtk.main_quit)
        self.here = Path(start) if start else common.WORK
        self.history = []

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        # ── path bar ──
        bar = Gtk.Box(spacing=8, margin=10)
        self.back = Gtk.Button(label="Back")
        self.back.get_accessible().set_name("Back")
        self.back.connect("clicked", self.on_back)
        bar.pack_start(self.back, False, False, 0)

        self.where = Gtk.Label(xalign=0)
        self.where.get_accessible().set_name("Location")
        bar.pack_start(self.where, True, True, 0)

        refresh = Gtk.Button(label="Refresh")
        refresh.get_accessible().set_name("Refresh")
        refresh.connect("clicked", lambda _b: self.load())
        bar.pack_end(refresh, False, False, 0)
        root.pack_start(bar, False, False, 0)

        split = Gtk.Box(spacing=0)
        root.pack_start(split, True, True, 0)

        # ── places ──
        places = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin=10)
        places.set_size_request(150, -1)
        for name, path, icon in PLACES:
            btn = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
            btn.get_accessible().set_name(name)
            row = Gtk.Box(spacing=8)
            row.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU),
                           False, False, 0)
            row.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
            btn.add(row)
            btn.connect("clicked", lambda _b, p=path: self.go(p))
            places.pack_start(btn, False, False, 0)
        split.pack_start(places, False, False, 0)

        # ── listing ──
        self.store = Gtk.ListStore(str, str, str, str)   # name, size, changed, fullpath
        self.view = Gtk.TreeView(model=self.store)
        self.view.get_accessible().set_name("Files")
        for i, title in enumerate(("Name", "Size", "Changed")):
            column = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i)
            column.set_resizable(True)
            if i == 0:
                column.set_expand(True)
            self.view.append_column(column)
        # Double-click matches every file manager anyone has used; Enter is
        # there so the whole app is reachable from the keyboard, which is also
        # how the executor will drive it.
        self.view.connect("row-activated", self.on_activate)
        scroll = Gtk.ScrolledWindow(margin=10)
        scroll.add(self.view)
        split.pack_start(scroll, True, True, 0)

        # ── actions ──
        feet = Gtk.Box(spacing=8, margin=10)
        self.note = Gtk.Label(xalign=0)
        self.note.set_opacity(.7)
        feet.pack_start(self.note, True, True, 0)
        for label, handler in (("Open", self.on_open),
                               ("Copy to Work", self.on_copy)):
            b = Gtk.Button(label=label)
            b.get_accessible().set_name(label)
            b.connect("clicked", handler)
            feet.pack_end(b, False, False, 0)
        root.pack_start(feet, False, False, 0)

        self.load()
        GLib.timeout_add_seconds(4, self.load)

    # ── navigation ──

    def go(self, path):
        path = Path(path)
        if path != self.here:
            self.history.append(self.here)
        self.here = path
        self.load()

    def on_back(self, _b):
        if self.history:
            self.here = self.history.pop()
            self.load()

    def load(self):
        self.here.mkdir(parents=True, exist_ok=True)
        picked = self.selected()
        self.store.clear()
        try:
            entries = sorted(self.here.iterdir(),
                             key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as e:
            self.note.set_text(str(e))
            return True

        shown = 0
        for p in entries:
            if p.name.startswith("."):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            self.store.append([
                f"{p.name}/" if p.is_dir() else p.name,
                "" if p.is_dir() else human(st.st_size),
                time.strftime("%d %b %H:%M", time.localtime(st.st_mtime)),
                str(p),
            ])
            shown += 1

        self.where.set_text(str(self.here).replace(str(common.HOME), "~"))
        self.back.set_sensitive(bool(self.history))
        if not shown:
            self.note.set_text("This folder is empty.")
        elif not picked:
            self.note.set_text(f"{shown} item{'s' if shown != 1 else ''}")
        if picked:
            self.reselect(picked)
        return True

    def selected(self):
        model, it = self.view.get_selection().get_selected()
        return model[it][3] if it else None

    def reselect(self, full):
        for row in self.store:
            if row[3] == full:
                self.view.get_selection().select_iter(row.iter)
                return

    # ── opening ──

    def on_activate(self, _view, path, _col):
        self.open(Path(self.store[path][3]))

    def on_open(self, _b):
        picked = self.selected()
        if picked:
            self.open(Path(picked))

    def open(self, path):
        if path.is_dir():
            return self.go(path)

        suffix = path.suffix.lower()
        if suffix in SHEETS:
            self.launch([sys.executable,
                         str(Path(__file__).resolve().parent / "sheet_app.py"),
                         str(path)], path)
        elif suffix in OFFICE:
            self.launch(["libreoffice", str(path)], path)
        elif suffix == ".pdf":
            self.launch(["evince", str(path)], path)
        elif suffix in TEXTY or path.stat().st_size < 400_000:
            Viewer(path).show_all()
            self.note.set_text(f"showing {path.name}")
        else:
            self.note.set_text(f"Nothing here opens {suffix or 'this'} — "
                               f"copy it out if you need it.")

    def launch(self, cmd, path):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.note.set_text(f"opening {path.name}…")
        except FileNotFoundError:
            self.note.set_text(f"{cmd[0]} is not installed in this sandbox")

    def on_copy(self, _b):
        import shutil
        picked = self.selected()
        if not picked:
            return
        source = Path(picked)
        if source.is_dir() or source.parent == common.WORK:
            return
        common.WORK.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, common.WORK / source.name)
        self.note.set_text(f"copied {source.name} to Work")


class Viewer(Gtk.Window):
    """Plain text, read-only. Enough to check what a file says without giving
    the sandbox an editor it has no use for."""

    def __init__(self, path):
        super().__init__(title=path.name)
        self.set_default_size(760, 560)
        text = Gtk.TextView(editable=False, monospace=True, left_margin=10,
                            right_margin=10, top_margin=8)
        text.get_accessible().set_name(path.name)
        try:
            body = path.read_text(encoding="utf-8", errors="replace")[:400_000]
        except OSError as e:
            body = f"Could not read this file: {e}"
        text.get_buffer().set_text(body)
        scroll = Gtk.ScrolledWindow()
        scroll.add(text)
        self.add(scroll)


def human(n):
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


if __name__ == "__main__":
    FilesApp(sys.argv[1] if len(sys.argv) > 1 else None).show_all()
    Gtk.main()
