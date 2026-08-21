#!/usr/bin/env python3
"""
Activity — the permission ledger, seen from inside the sandbox.

Everything the clone did, and everything it was refused. Refusals are the
rows that matter, so they are coloured and they sort to the top of attention
rather than scrolling away among the routine ones.
"""

import json
import time
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk   # noqa: E402

import common   # noqa: E402

# The host writes the ledger; the sandbox only ever reads it. An audit log the
# audited party can edit is not an audit log.
LEDGER = Path("/opt/shishya/var/ledger.jsonl")


class ActivityApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Activity")
        self.set_default_size(760, 520)
        self.connect("destroy", Gtk.main_quit)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        self.summary = Gtk.Label(xalign=0, margin=14)
        root.pack_start(self.summary, False, False, 0)

        self.store = Gtk.ListStore(str, str, str, str, str)   # time verdict action target colour
        view = Gtk.TreeView(model=self.store)
        view.get_accessible().set_name("Activity")
        for i, title in enumerate(("Time", "", "Action", "Target")):
            r = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(title, r, text=i, foreground=4)
            view.append_column(col)
        scroll = Gtk.ScrolledWindow(margin=14)
        scroll.add(view)
        root.pack_start(scroll, True, True, 0)

        self.refresh()
        GLib.timeout_add_seconds(3, self.refresh)

    def refresh(self):
        self.store.clear()
        allowed = denied = 0
        for entry in read(LEDGER):
            verdict = entry.get("verdict", "info")
            if verdict == "deny":
                denied += 1
                colour = "#f87171"
            elif verdict == "allow":
                allowed += 1
                colour = "#4ade80"
            else:
                colour = "#9aa4ae"
            self.store.append([
                time.strftime("%H:%M:%S", time.localtime(entry.get("t", 0))),
                verdict.upper(),
                entry.get("action", ""),
                str(entry.get("target", "")),
                colour,
            ])
        self.summary.set_markup(
            f"<b>{denied}</b> refused    <b>{allowed}</b> allowed    "
            f"<b>{len(self.store)}</b> entries in total")
        return True


def read(path, limit=400):
    if not path.exists():
        return []
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out[-limit:]


if __name__ == "__main__":
    ActivityApp().show_all()
    Gtk.main()
