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

.start          { background: transparent; border: none; border-radius: 0;
                  padding: 0 18px; color: #e6ebf1; font-size: 12px; }
.start:hover    { background: rgba(255,255,255,.10); }

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
        .desktop      {{ background-color: {look['wallpaper'] if look['wallpaper'].startswith('#') else '#04060d'}; }}
        .task         {{ border-bottom: 2px solid {look['accent']}; }}
        .pill-working {{ background: {look['accent']}; }}
        .icon-btn:focus {{ background: {look['accent']}; }}
    """.encode())


# ─── what sits on the desktop ───────────────────────────────────────────────
# Each entry is (label, icon, what it opens). "Lessons" is the one worth
# noticing: every procedure the clone has been taught shows up there as a
# file. Skills you can point at are much easier to believe than skills
# described in a status panel.

# ─── what the launcher offers ───────────────────────────────────────────────
# Ordered by how the work actually flows — a file arrives, you read it, you
# teach from it, you produce something — rather than alphabetically or by how
# proud we are of each app.

MENU = [
    ("Files",             "system-file-manager",  lambda: app("files_app.py")),
    ("Inbox",             "mail-message-new",     lambda: app("inbox_app.py")),
    (None, None, None),
    ("Training Data",     "emblem-documents",     lambda: app("training_app.py")),
    ("Shishya",           "system-run",           lambda: app("shishya_app.py")),
    (None, None, None),
    ("Make a Document",   "x-office-document",    lambda: app("make_app.py")),
    ("Code",              "text-x-script",        lambda: app("code_app.py")),
    ("Sheets",            "x-office-spreadsheet", lambda: app("sheet_app.py")),
    ("LibreOffice Calc",  "x-office-spreadsheet", lambda: office("--calc")),
    ("LibreOffice Writer", "x-office-document",   lambda: office("--writer")),
    (None, None, None),
    ("Work folder",       "folder-documents",     lambda: files(WORK)),
    ("Lessons",           "folder-templates",     lambda: files(LESSONS)),
    ("Activity",          "text-x-generic",       lambda: app("activity_app.py")),
    ("Models",            "applications-science", lambda: app("models_app.py")),
    ("Settings",          "preferences-system",   lambda: app("settings_app.py")),
]


def office(mode):
    """The real LibreOffice, not a viewer.

    The clone has to learn by watching a person work, and then do that work
    itself — which only holds if both use the same application. A lookalike
    would make every recorded lesson untransferable.
    """
    subprocess.Popen(["libreoffice", mode],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def files(path):
    """Open our own Files app at that folder.

    This used to call xdg-open, which is not installed here — so Work and
    Lessons silently did nothing when clicked. Nothing logged it, because
    Popen of a missing binary fails in the child, not in us.
    """
    path.mkdir(parents=True, exist_ok=True)
    app("files_app.py", str(path))


def app(name, *args):
    target = APPS / name
    if not target.exists():
        return notice(f"{name} isn't built yet")
    # Errors go to a log rather than /dev/null: an app that dies on startup
    # should leave a trace somewhere, not just fail to appear.
    log = open(f"/tmp/{name}.log", "a")
    subprocess.Popen([sys.executable, str(target), *args], stdout=log, stderr=log)


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

        # The wallpaper is a drawing surface with the icons floating over it,
        # so a live background costs nothing when it is switched off — the
        # overlay simply has an empty child underneath.
        self.stack = Gtk.Overlay()
        self.add(self.stack)

        self.canvas = Gtk.DrawingArea()
        self.canvas.connect("draw", self.on_draw)
        self.stack.add(self.canvas)

        self.galaxy = None
        self.ticker = None

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.stack.add_overlay(outer)
        outer.set_margin_bottom(TASKBAR_H)

        # Nothing on the desktop. Everything lives behind the launcher, so the
        # clone's screen stays legible while it works — which is the screen
        # someone is watching for the whole demonstration.
        self.tag = Gtk.Label(halign=Gtk.Align.END, valign=Gtk.Align.END, margin=18)
        self.tag.get_style_context().add_class("wall-title")
        outer.pack_end(self.tag, False, False, 0)
        self.boxes = []

    def on_draw(self, _area, cr):
        if self.galaxy is None:
            return False
        alloc = self.canvas.get_allocation()
        self.galaxy.draw(cr, alloc.width, alloc.height)
        return True

    def set_live(self, on):
        """Start or stop the animated wallpaper.

        Stopped means stopped: the timer is removed rather than left running
        against a hidden surface. The clone is doing real work on four cores
        and the desktop must not take a slice of it for a background nobody
        is looking at.
        """
        if on and self.galaxy is None:
            import galaxy
            self.galaxy = galaxy.Galaxy()
            self.ticker = GLib.timeout_add(int(1000 / galaxy.FPS), self._tick)
        elif not on and self.galaxy is not None:
            if self.ticker:
                GLib.source_remove(self.ticker)
            self.ticker = None
            self.galaxy = None
            self.canvas.queue_draw()

    def _tick(self):
        if self.galaxy is None:
            return False
        self.galaxy.step()
        self.canvas.queue_draw()
        return True

    def set_busy(self, busy):
        """Stop animating while the model is working.

        The sandbox has four cores and the model wants all of them. Drawing
        4,200 points fourteen times a second is affordable when nothing else
        is happening and rude when an answer is being waited on, so the timer
        is removed for the duration.

        The galaxy object is kept — rebuilding it means regenerating every
        point, and the picture would visibly flicker each time somebody asked
        a question. Frozen mid-turn it just looks still.
        """
        if self.galaxy is None:
            return
        if busy and self.ticker is not None:
            GLib.source_remove(self.ticker)
            self.ticker = None
        elif not busy and self.ticker is None:
            import galaxy
            self.ticker = GLib.timeout_add(int(1000 / galaxy.FPS), self._tick)

    def relabel(self, look):
        self.set_live(look.get("wallpaper") == "galaxy")
        self.tag.set_text(look["wallmark"])


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

        # ── far left: the launcher ──
        # Everything opens from here. Shut down sits at the bottom of the same
        # menu rather than being the corner button itself: the corner is where
        # a hand goes without looking, and that should not be the control that
        # ends the session.
        self.start = Gtk.Button()
        self.start.get_style_context().add_class("start")
        self.start.set_relief(Gtk.ReliefStyle.NONE)
        self.start.get_accessible().set_name("Apps")
        self.start.set_tooltip_text("Apps")
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Image.new_from_icon_name("view-grid-symbolic",
                                                    Gtk.IconSize.LARGE_TOOLBAR),
                       False, False, 0)
        row.pack_start(Gtk.Label(label="Apps"), False, False, 0)
        self.start.add(row)
        self.start.connect("clicked", self.on_start)
        bar.pack_start(self.start, False, False, 0)

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

    def on_start(self, button):
        menu = Gtk.Menu()
        menu.get_accessible().set_name("Apps")

        for label, icon, action in MENU:
            if label is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            item = Gtk.MenuItem()
            item.get_accessible().set_name(label)
            row = Gtk.Box(spacing=10)
            row.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU),
                           False, False, 0)
            row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            item.add(row)
            item.connect("activate", lambda _i, fn=action: fn())
            menu.append(item)

        menu.append(Gtk.SeparatorMenuItem())
        power = Gtk.MenuItem()
        power.get_accessible().set_name("Shut down")
        prow = Gtk.Box(spacing=10)
        prow.pack_start(Gtk.Image.new_from_icon_name("system-shutdown-symbolic",
                                                     Gtk.IconSize.MENU), False, False, 0)
        prow.pack_start(Gtk.Label(label="Shut down", xalign=0), True, True, 0)
        power.add(prow)
        power.connect("activate", self.on_power)
        menu.append(power)

        menu.show_all()

        # Positioned by hand. popup_at_widget anchors against the parent
        # window, and the taskbar is a DOCK — the menu opened somewhere
        # off-screen and the whole launcher looked dead, when in fact it had
        # worked every time.
        def place(_menu, *_args):
            _, height = menu.get_preferred_height()
            return 0, screen_size()[1] - TASKBAR_H - height, True

        menu.popup(None, None, place, None, 0, Gtk.get_current_event_time())

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

        # Same file the taskbar pill reads, so there is one source of truth
        # for "the model is working" rather than two that can disagree.
        try:
            busy = (SHARED / ".state").read_text().strip() == "working"
        except OSError:
            busy = False
        if busy != state.get("busy"):
            state["busy"] = busy
            desktop.set_busy(busy)
        return True

    follow()
    GLib.timeout_add_seconds(1, follow)
    Gtk.main()


if __name__ == "__main__":
    main()
