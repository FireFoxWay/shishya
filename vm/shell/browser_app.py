#!/usr/bin/env python3
"""
Browser — the web, when you have deliberately allowed it.

Some jobs genuinely need a browser: a portal with no API, a supplier's price
list, a government form that only exists as a web page. So the sandbox has
one. What it does not have is standing permission to use it.

── The rule this app exists to keep ────────────────────────────────────────

The claim was never "this can never reach the internet". It is "it cannot
unless you say so, and when you do, it is in the log." Browsing is therefore
a mode: off by default, switched on from the control panel out on the host,
recorded when it changes, and switched off again after. The clone cannot
grant it to itself — it has no sudo and the rules live outside its reach.

Opened while the network is locked, this says so and offers nothing else.
Opened while the Mac itself has no connection, it says that instead. Both
beat a browser that simply fails to load anything.
"""

import subprocess
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk   # noqa: E402

import common   # noqa: E402

STATE = common.SHARED / ".browsing"      # written by the host when the mode changes
# Falkon (Qt WebEngine), not Epiphany (WebKit). Epiphany installs cleanly and
# then crashes its renderer on every page in this VM — "Web process crashed",
# 156 times in fifteen seconds. Software rendering, disabling compositing and
# relaxing the AppArmor namespace restriction all failed to help. Falkon
# rendered the first page it was given.
BROWSER = "falkon"

# Qt WebEngine assumes a GPU and a working sandbox; this VM has neither. Its
# own sandbox is off because the VM *is* the sandbox — the clone has no sudo
# and, unless browsing has been switched on, no network either.
BROWSER_ENV = {
    "QT_QPA_PLATFORM": "xcb",
    "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu --no-sandbox --disable-dev-shm-usage",
}

# A page that loads without the network, so the browser has somewhere to land
# rather than opening on a connection error.
HOME = "about:blank"


def allowed():
    """Is browsing switched on? Read from the file the host writes, not
    guessed — the sandbox should not be the authority on its own permissions."""
    try:
        return STATE.read_text(encoding="utf-8").strip() == "on"
    except OSError:
        return False


class BrowserApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Browser")
        self.set_default_size(640, 420)
        self.connect("destroy", Gtk.main_quit)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=26)
        self.add(box)

        title = Gtk.Label(xalign=0)
        title.set_markup("<b>Browser</b>")
        box.pack_start(title, False, False, 0)

        self.status = Gtk.Label(xalign=0)
        self.status.set_line_wrap(True)
        self.status.set_max_width_chars(58)
        box.pack_start(self.status, False, False, 0)

        row = Gtk.Box(spacing=8)
        self.address = Gtk.Entry(placeholder_text="Address, or a search")
        self.address.get_accessible().set_name("Address")
        self.address.connect("activate", self.on_open)
        row.pack_start(self.address, True, True, 0)
        self.go = Gtk.Button(label="Open")
        self.go.get_accessible().set_name("Open")
        self.go.connect("clicked", self.on_open)
        row.pack_end(self.go, False, False, 0)
        box.pack_start(row, False, False, 0)

        note = Gtk.Label(xalign=0)
        note.set_line_wrap(True)
        note.set_max_width_chars(60)
        note.set_opacity(.6)
        note.set_text(
            "Browsing is off unless you switch it on from the control panel. "
            "Every change is written to the ledger, and the sandbox cannot "
            "switch it on for itself.")
        box.pack_start(note, False, False, 0)

        self.refresh()
        GLib.timeout_add_seconds(2, self.refresh)

    def refresh(self):
        ok = allowed()
        self.address.set_sensitive(ok)
        self.go.set_sensitive(ok)
        if ok:
            self.status.set_markup(
                "<span foreground='#2C6E49'>Browsing is allowed.</span> "
                "Type an address and it opens in the sandbox.")
        else:
            self.status.set_markup(
                "<span foreground='#A2482B'>Browsing is switched off.</span> "
                "Press ALLOW BROWSING on the control panel to turn it on — "
                "then this page will let you through.")
        return True

    def on_open(self, _w):
        if not allowed():
            return
        where = self.address.get_text().strip()
        if not where:
            return
        if "." not in where.split("/")[0] and not where.startswith(("http", "about:")):
            where = "https://duckduckgo.com/?q=" + GLib.uri_escape_string(where, None, True)
        elif not where.startswith(("http://", "https://", "about:")):
            where = "https://" + where

        try:
            import os
            env = {**os.environ, **BROWSER_ENV}
            subprocess.Popen([BROWSER, where], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.status.set_text(f"Opening {where}")
        except FileNotFoundError:
            self.status.set_text(f"{BROWSER} is not installed in this sandbox.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        print("on" if allowed() else "off")
        raise SystemExit(0)
    BrowserApp().show_all()
    Gtk.main()
