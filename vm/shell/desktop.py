#!/usr/bin/env python3
"""
Shishya — the clone's desktop. Runs INSIDE the sandbox.

A deliberately familiar shell: icons on a wallpaper, a taskbar along the
bottom, power in the far corner. Nobody should need the metaphor explained.

Why a shell at all, rather than a bare window manager: the desktop is what a
judge looks at for six minutes. A bare openbox root window reads as "a Linux
box"; this reads as "a computer someone works at", which is the whole claim.

It is GTK rather than a drawn canvas for a reason that matters more than
looks — GTK publishes itself to AT-SPI, so the recorder can see this shell's
own buttons and icons the same way it sees any other app. A desktop drawn on
a canvas would be invisible to the thing that has to learn from it.

    python3 desktop.py
"""

import json
import subprocess
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk   # noqa: E402

HOME = Path.home()
SHARED = HOME / "shared"
WORK = SHARED / "work"
LESSONS = SHARED / "lessons"
TRAINING = SHARED / "training"

TASKBAR_H = 48
APPS = Path(__file__).resolve().parent


# ─── look ───────────────────────────────────────────────────────────────────
# Flat, cool-grey, one blue accent. Restrained on purpose: this is the
# backdrop the actual work happens on, and every extra colour here is one
# more thing competing with the app the clone is driving.

CSS = b"""
.wall-title     { color: #6f7d8c; font-size: 11px; letter-spacing: 2px; }

.icon-btn       { background: transparent; border: 1px solid transparent;
                  border-radius: 4px; padding: 10px 6px; }
.icon-btn:hover { background: rgba(255,255,255,.07);
                  border-color: rgba(255,255,255,.14); }
.icon-btn:focus { background: rgba(255,255,255,.18); }
.icon-label     { color: #e6ebf1; font-size: 12px; }

.taskbar        { background-color: #0b0f14; border-top: 1px solid #1e2833; }

.power          { background: transparent; border: none; border-radius: 0;
                  padding: 0 20px; color: #c3ccd6; }
/* Red only on hover: a permanently red power button reads as an alarm. */
.power:hover    { background-color: #c42b1c; color: #ffffff; }

.task           { background: rgba(255,255,255,.05); border: none;
                  border-radius: 0;
                  padding: 0 14px; color: #dbe3ea; font-size: 12px; }
.task:hover     { background: rgba(255,255,255,.10); }

.clock          { color: #c3ccd6; font-size: 12px; padding: 0 16px; }

.pill           { border-radius: 3px; padding: 3px 10px; font-size: 10px; }
.pill-idle      { background: #1e2833; color: #8b98a5; }
.pill-working   { color: #ffffff; }
.pill-wheel     { background: #2f7a55; color: #ffffff; }
/* Amber, not red: needing a person is normal, not a failure. */
.pill-needs     { background: #b3720a; color: #ffffff; }
"""


CONFIG = SHARED / ".desktop.json"
LOOK = {"wallpaper": "#10151c", "accent": "#0078d4", "icon_size": 96,
        "wallmark": "SHISHYA SANDBOX"}


def read_look():
    try:
        return {**LOOK, **json.loads(CONFIG.read_text())}
    except (OSError, json.JSONDecodeError):
        return dict(LOOK)


def screen_size():
    """Deprecated Gdk.Screen sizing still works and is one call; the
    monitor-geometry replacement needs three and this display never changes
    resolution — it is pinned at 1440x900 so recorded traces stay valid."""
    d = Gdk.Display.get_default()
    geo = d.get_monitor(0).get_geometry()
    return geo.width, geo.height


def style():
    p = Gtk.CssProvider()
    p.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    return p


# A second provider, above the first, holding only what Settings controls.
# Reloading this one repaints the desktop without touching the base sheet and
# without restarting the shell — which would close whatever the clone had open.
THEME = Gtk.CssProvider()


def apply_look(look):
    THEME.load_from_data(f"""
        .desktop      {{ background-color: {look['wallpaper']}; }}
        .task         {{ border-bottom: 2px solid {look['accent']}; }}
        .pill-working {{ background: {look['accent']}; }}
        .icon-btn:focus {{ background: {look['accent']}; }}
    """.encode())


# ─── what sits on the desktop ───────────────────────────────────────────────
# Each entry is (label, icon, what it opens). "Lessons" is the one worth
# noticing: every procedure the clone has been taught shows up there as a
# file. Skills you can point at are much easier to believe than skills
# described in a status panel.

ICONS = [
    ("Work",             "folder-documents",  lambda: files(WORK)),
    ("Inbox",            "mail-message-new",  lambda: app("inbox_app.py")),
    ("Shishya",          "system-run",        lambda: app("shishya_app.py")),
    ("Training Data",    "emblem-documents",  lambda: app("training_app.py")),
    ("Make a Document",  "x-office-document", lambda: app("make_app.py")),
    ("Lessons",          "folder-templates",  lambda: files(LESSONS)),
    ("Activity",         "text-x-generic",    lambda: app("activity_app.py")),
    ("Settings",         "preferences-system", lambda: app("settings_app.py")),
]


def files(path):
    path.mkdir(parents=True, exist_ok=True)
    # No file manager is installed and we do not want a heavy one pulled in
    # just for this; xdg-open falls back sensibly and keeps the dependency
    # surface small.
    subprocess.Popen(["xdg-open", str(path)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def app(name):
    target = APPS / name
    if not target.exists():
        return notice(f"{name} isn't built yet")
    subprocess.Popen([sys.executable, str(target)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def notice(message):
    d = Gtk.MessageDialog(transient_for=None, modal=True,
                          message_type=Gtk.MessageType.INFO,
                          buttons=Gtk.ButtonsType.OK, text=message)
    d.run()
    d.destroy()


class Desktop(Gtk.Window):
    def __init__(self):
        super().__init__(title="Desktop")
        self.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
        self.get_style_context().add_class("desktop")
        # fullscreen() is ignored for DESKTOP-type windows — the WM treats them
        # as the root backdrop and leaves sizing alone, so the window ends up
        # shrink-wrapped around the icons. Size and place it by hand instead.
        self.set_decorated(False)
        self.set_resizable(False)
        self.move(0, 0)
        self.set_default_size(*screen_size())
        self.connect("destroy", Gtk.main_quit)

        # Built before the icon loop, which fills it.
        self.boxes = []

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)

        outer.set_margin_bottom(TASKBAR_H)

        grid = Gtk.FlowBox(
            valign=Gtk.Align.START, halign=Gtk.Align.START,
            selection_mode=Gtk.SelectionMode.NONE,
            min_children_per_line=1, max_children_per_line=1,
            row_spacing=6, margin=22,
        )
        for label, icon, action in ICONS:
            grid.add(self._icon(label, icon, action))
        outer.pack_start(grid, True, True, 0)

        self.tag = Gtk.Label(halign=Gtk.Align.END, margin=18)
        self.tag.get_style_context().add_class("wall-title")
        outer.pack_end(self.tag, False, False, 0)

    def relabel(self, look):
        self.tag.set_text(look["wallmark"])
        for box in self.boxes:
            box.set_size_request(look["icon_size"], -1)

    def _icon(self, label, icon_name, action):
        btn = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        btn.get_style_context().add_class("icon-btn")
        # The accessible name is what the recorder will write into a trace,
        # so it has to read like the thing itself — "Training Data", not
        # "button23".
        btn.get_accessible().set_name(label)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_size_request(96, -1)
        self.boxes.append(box)
        box.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DIALOG),
                       False, False, 0)
        text = Gtk.Label(label=label)
        text.get_style_context().add_class("icon-label")
        text.set_line_wrap(True)
        text.set_justify(Gtk.Justification.CENTER)
        text.set_max_width_chars(12)
        box.pack_start(text, False, False, 0)

        btn.add(box)
        # Single click, not double: the clone drives this through synthetic
        # events, and one click is one less thing to get the timing wrong on.
        btn.connect("clicked", lambda _b: action())
        return btn


class Taskbar(Gtk.Window):
    def __init__(self):
        super().__init__(title="Taskbar")
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.get_style_context().add_class("taskbar")
        self.set_keep_above(True)
        self.set_decorated(False)
        self.set_accept_focus(False)

        w, h = screen_size()
        self.set_default_size(w, TASKBAR_H)
        self.move(0, h - TASKBAR_H)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(bar)

        # ── far left: power ──
        power = Gtk.Button()
        power.get_style_context().add_class("power")
        power.set_relief(Gtk.ReliefStyle.NONE)
        power.get_accessible().set_name("Shut down")
        power.set_tooltip_text("Shut down the sandbox")
        power.add(Gtk.Image.new_from_icon_name("system-shutdown-symbolic",
                                               Gtk.IconSize.LARGE_TOOLBAR))
        power.connect("clicked", self.on_power)
        bar.pack_start(power, False, False, 0)

        self.tasks = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                             margin_start=10)
        bar.pack_start(self.tasks, True, True, 0)

        # ── far right: what is happening, and the time ──
        self.pill = Gtk.Label(label="IDLE")
        self.pill.get_style_context().add_class("pill")
        self.pill.get_style_context().add_class("pill-idle")
        self.pill.set_margin_end(10)
        bar.pack_end(self.pill, False, False, 0)

        self.clock = Gtk.Label()
        self.clock.get_style_context().add_class("clock")
        bar.pack_end(self.clock, False, False, 0)

        self.tick()
        GLib.timeout_add_seconds(1, self.tick)
        GLib.timeout_add_seconds(2, self.refresh_tasks)

    def tick(self):
        self.clock.set_text(GLib.DateTime.new_now_local().format("%H:%M  %a %d %b"))
        return True

    # The state file is written by the agent on the other side. A file rather
    # than a socket so that a crashed agent leaves the taskbar showing the
    # last true state instead of hanging.
    STATE = SHARED / ".state"
    PILLS = {
        "working": ("CLONE WORKING", "pill-working"),
        "wheel":   ("YOU HAVE THE WHEEL", "pill-wheel"),
        "needs":   ("NEEDS YOU", "pill-needs"),
        "idle":    ("IDLE", "pill-idle"),
    }

    def refresh_tasks(self):
        state = "idle"
        try:
            state = self.STATE.read_text().strip() or "idle"
        except OSError:
            pass
        text, css = self.PILLS.get(state, self.PILLS["idle"])
        self.pill.set_text(text)
        ctx = self.pill.get_style_context()
        for _, c in self.PILLS.values():
            ctx.remove_class(c)
        ctx.add_class(css)

        for child in self.tasks.get_children():
            self.tasks.remove(child)
        for wid, title in open_windows():
            b = Gtk.Button(label=ellipsis(title, 24))
            b.get_style_context().add_class("task")
            b.get_accessible().set_name(title)
            b.connect("clicked", lambda _b, w=wid: raise_window(w))
            self.tasks.pack_start(b, False, False, 0)
        self.tasks.show_all()
        return True

    def on_power(self, _btn):
        d = Gtk.MessageDialog(
            transient_for=None, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Shut down the sandbox?")
        d.format_secondary_text(
            "Anything the clone has not saved to Work will be lost.")
        answer = d.run()
        d.destroy()
        if answer == Gtk.ResponseType.OK:
            # The clone has no sudo, by design. Shutdown is a request it makes
            # of the host, not something it can do to itself — the host owns
            # the sandbox's lifecycle.
            (SHARED / ".shutdown-requested").write_text("1")


# ─── window list ────────────────────────────────────────────────────────────

def open_windows():
    """Ask X directly rather than tracking windows ourselves — apps started
    outside this shell (by the executor, say) must appear too."""
    try:
        out = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "."],
                             capture_output=True, text=True, timeout=4).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    seen = []
    for wid in out.split():
        try:
            name = subprocess.run(["xdotool", "getwindowname", wid],
                                  capture_output=True, text=True, timeout=2).stdout.strip()
        except subprocess.SubprocessError:
            continue
        if name and name not in ("Desktop", "Taskbar") and name not in [t for _, t in seen]:
            seen.append((wid, name))
    return seen[:8]


def raise_window(wid):
    subprocess.Popen(["xdotool", "windowactivate", wid],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ellipsis(text, n):
    return text if len(text) <= n else text[: n - 1] + "…"


def main():
    for d in (WORK, LESSONS, TRAINING):
        d.mkdir(parents=True, exist_ok=True)
    provider = style()
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), THEME, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

    desktop = Desktop()
    desktop.show_all()
    Taskbar().show_all()

    # Poll rather than watch the file: an inotify watch dies when the file is
    # replaced by a rename, which is exactly how Settings writes it.
    state = {}

    def follow():
        look = read_look()
        if look != state.get("look"):
            state["look"] = look
            apply_look(look)
            desktop.relabel(look)
        return True

    follow()
    GLib.timeout_add_seconds(1, follow)
    Gtk.main()


if __name__ == "__main__":
    main()
