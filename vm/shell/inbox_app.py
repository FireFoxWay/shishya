#!/usr/bin/env python3
"""
Inbox — files sent in from the machine outside.

Drop a file on the control panel and it lands here. This is the only way in:
the sandbox cannot reach out and take a file off the host, so everything that
arrives was handed over deliberately.

Nothing is opened on arrival. A file that appeared a second ago is exactly the
kind that should not be executed by surprise, so it waits for you to say what
it is for: keep it as work, or teach from it.
"""

import shutil
import subprocess
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk   # noqa: E402

import common   # noqa: E402

INBOX = common.SHARED / "inbox"


class InboxApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Inbox")
        self.set_default_size(620, 460)
        self.connect("destroy", Gtk.main_quit)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        head = Gtk.Label(xalign=0, margin=14)
        head.set_markup("<b>Inbox</b>")
        root.pack_start(head, False, False, 0)

        self.note = Gtk.Label(xalign=0, margin_start=14, margin_end=14)
        self.note.set_opacity(.7)
        root.pack_start(self.note, False, False, 0)

        self.store = Gtk.ListStore(str, str)
        self.view = Gtk.TreeView(model=self.store)
        self.view.get_accessible().set_name("Incoming files")
        for i, title in enumerate(("File", "Size")):
            self.view.append_column(
                Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i))
        scroll = Gtk.ScrolledWindow(margin=14)
        scroll.add(self.view)
        root.pack_start(scroll, True, True, 0)

        feet = Gtk.Box(spacing=8, margin=14)
        for label, handler in (("Open", self.on_open),
                               ("Keep as work", self.on_keep),
                               ("Teach from this", self.on_teach)):
            b = Gtk.Button(label=label)
            b.get_accessible().set_name(label)
            b.connect("clicked", handler)
            feet.pack_end(b, False, False, 0)
        root.pack_start(feet, False, False, 0)

        self.refresh()
        GLib.timeout_add_seconds(2, self.refresh)

    def refresh(self):
        INBOX.mkdir(parents=True, exist_ok=True)
        # .part files are uploads still in flight on the host side.
        files = sorted(p for p in INBOX.iterdir()
                       if p.is_file() and not p.name.startswith(".")
                       and p.suffix != ".part")
        picked = self.selected_name()
        self.store.clear()
        for p in files:
            self.store.append([p.name, human(p.stat().st_size)])
        if picked:
            self.reselect(picked)
        self.note.set_text(
            f"{len(files)} file{'s' if len(files) != 1 else ''} sent from the host"
            if files else "Nothing waiting. Drop a file on the control panel.")
        return True

    def selected_name(self):
        model, it = self.view.get_selection().get_selected()
        return model[it][0] if it else None

    def reselect(self, name):
        for row in self.store:
            if row[0] == name:
                self.view.get_selection().select_iter(row.iter)
                return

    def picked(self):
        name = self.selected_name()
        return INBOX / name if name else None

    def on_open(self, _b):
        p = self.picked()
        if p:
            subprocess.Popen(["xdg-open", str(p)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def on_keep(self, _b):
        self.move_to(common.WORK, "Work")

    def on_teach(self, _b):
        self.move_to(common.TRAINING, "Training Data")

    def move_to(self, target, label):
        p = self.picked()
        if not p:
            return
        target.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(target / p.name))
        self.refresh()
        self.note.set_text(f"{p.name} → {label}")


def human(n):
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


if __name__ == "__main__":
    InboxApp().show_all()
    Gtk.main()
