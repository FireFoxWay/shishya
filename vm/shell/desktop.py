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


# ─── is anyone actually looking? ────────────────────────────────────────────
# The animated wallpaper repaints the whole 1440x900 screen several times a
# second. That is affordable when someone is watching it and pure waste when
# nobody is — and it is worse than waste over VNC, because every repaint is a
# full-screen frame x11vnc has to encode and ship down the wire. An idle
# sandbox was producing a continuous video stream of a picture nobody had
# open. Measured: 19% of a core in Xvfb plus 13% in this process, forever.
#
# The signal is the noVNC bridge's own socket. websockify listens on 6080 and
# a browser tab connected to it shows up as an ESTABLISHED entry; close the
# tab and the entry goes. Read straight from /proc rather than shelling out to
# `ss`, because this is checked once a second for the life of the machine.
NOVNC_PORT = 6080


def watching():
    """True when a browser has the clone's screen open."""
    want = f":{NOVNC_PORT:04X}"
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table) as fh:
                next(fh, None)                       # header
                for line in fh:
                    col = line.split()
                    # local_address is host:port in hex; 01 is ESTABLISHED.
                    if len(col) > 3 and col[3] == "01" and col[1].endswith(want):
                        return True
        except OSError:
            # No /proc/net/tcp means we cannot tell. Assume someone is there:
            # a wallpaper that stops for no reason is a bug people can see,
            # and one that runs when it needn't is only a cost.
            return True
    return False


# ─── look ───────────────────────────────────────────────────────────────────
# Flat, cool-grey, one blue accent. Restrained on purpose: this is the
# backdrop the actual work happens on, and every extra colour here is one
# more thing competing with the app the clone is driving.

CSS = b"""
/* Swiss-technical, matching the control panel. Two design languages sat side
   by side on one screen while the panel was rebuilt and this was not, which
   looked less like a choice than an oversight.

   No colour, so emphasis is inversion -- the same rule as the panel. The one
   place that hurts is the taskbar pill, which used green and amber to say
   what the clone is doing; those become an inverted block and a dashed
   outline, which carry the same three states without the palette. */

.wall-title     { color: #7c828a; font-size: 9px; letter-spacing: 3px; }

.icon-btn       { background: transparent; border: 1px solid transparent;
                  border-radius: 0; padding: 10px 6px; }
.icon-btn:hover { background: #0b0c0e; }
.icon-btn:focus { background: #0b0c0e; }
.icon-label     { color: #e9ebee; font-size: 11px; letter-spacing: .4px; }

.taskbar        { background-color: #0b0c0e; border-top: 1px solid #2a2e33; }

.start          { background: transparent; border: none; border-radius: 0;
                  padding: 0 20px; color: #e9ebee;
                  font-size: 10px; letter-spacing: 1.6px; }
.start:hover    { background: #e9ebee; color: #0b0c0e; }

.task           { background: transparent; border: none;
                  border-bottom: 2px solid #e9ebee; border-radius: 0;
                  padding: 0 14px; color: #c9ced4;
                  font-size: 10px; letter-spacing: 1.2px; }
.task:hover     { background: #e9ebee; color: #0b0c0e; }

.clock          { color: #9aa0a7; font-size: 10px; letter-spacing: 1.4px;
                  padding: 0 18px; }

/* Three states without colour: outline for idle, solid for working, dashed
   for the two that need a person. */
.pill           { border-radius: 0; padding: 3px 10px;
                  font-size: 9px; letter-spacing: 1.6px;
                  border: 1px solid #e9ebee; color: #e9ebee; }
.pill-idle      { border-color: #4a4f55; color: #8b9199; }
.pill-working   { background: #e9ebee; color: #0b0c0e; }
.pill-wheel     { border-style: dashed; }
.pill-needs     { border-style: dashed; border-width: 2px; }
"""


CONFIG = SHARED / ".desktop.json"
LOOK = {"wallpaper": "#10151c", "accent": "#0078d4", "icon_size": 96,
        "wallmark": "SHISHYA SANDBOX", "fps": 12}


def read_look():
    try:
        return {**LOOK, **json.loads(CONFIG.read_text())}
    except (OSError, json.JSONDecodeError):
        return dict(LOOK)


# The live wallpapers, by the name Settings writes into the config.
LIVE = ("galaxy", "matrix")


def make_wallpaper(name):
    """Build a live wallpaper and report the rate it wants to run at."""
    if name == "matrix":
        import matrix
        return matrix.Matrix(), matrix.FPS
    import galaxy
    return galaxy.Galaxy(), galaxy.FPS


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
    ("Shishya — talk to it", "user-available",  lambda: app("chat_app.py")),
    (None, None, None),
    ("Billing",           "emblem-money",         lambda: app("billing_app.py")),
    ("Files",             "system-file-manager",  lambda: app("files_app.py")),
    ("Inbox",             "mail-message-new",     lambda: app("inbox_app.py")),
    (None, None, None),
    ("Findings",          "dialog-warning",       lambda: app("findings_app.py")),
    ("Reports",           "x-office-presentation", lambda: app("reports_app.py")),
    ("Training Data",     "emblem-documents",     lambda: app("training_app.py")),
    ("Shishya",           "system-run",           lambda: app("shishya_app.py")),
    (None, None, None),
    ("Make a Document",   "x-office-document",    lambda: app("make_app.py")),
    ("Code",              "text-x-script",        lambda: app("code_app.py")),
    ("Sheets",            "x-office-spreadsheet", lambda: app("sheet_app.py")),
    ("LibreOffice Calc",  "x-office-spreadsheet", lambda: office("--calc")),
    ("LibreOffice Writer", "x-office-document",   lambda: office("--writer")),
    (None, None, None),
    # Native Linux work apps, provisioned 23 Aug 26. The Windows staples —
    # Tally Prime, Busy, Marg — cannot run in an arm64 Linux sandbox at all;
    # what stands in: GnuCash for the accounting slot, and jobs that produce
    # the XML Tally imports (see training/tally-import-notes.md).
    ("GnuCash",           "gnucash",              lambda: native("gnucash")),
    ("GIMP",              "gimp",                 lambda: native("gimp")),
    ("Inkscape",          "org.inkscape.Inkscape", lambda: native("inkscape")),
    (None, None, None),
    ("Work folder",       "folder-documents",     lambda: files(WORK)),
    ("Lessons",           "folder-templates",     lambda: files(LESSONS)),
    ("Activity",          "text-x-generic",       lambda: app("activity_app.py")),
    ("Browser",           "web-browser",          lambda: app("browser_app.py")),
    ("Terminal",          "utilities-terminal",   lambda: terminal()),
    ("System",            "utilities-system-monitor", lambda: app("system_app.py")),
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


def native(*cmd):
    """A real installed program, checked for before launching. Popen of a
    missing binary fails in the child, not in us — the Work-folder icon
    taught that lesson — so the absence is said out loud instead."""
    import shutil
    if shutil.which(cmd[0]) is None:
        return notice(f"{cmd[0]} is not installed in this sandbox")
    log = open(f"/tmp/{cmd[0]}.log", "a")
    subprocess.Popen(list(cmd), stdout=log, stderr=log)


def terminal():
    """A shell on the clone's own desktop.

    xterm rather than a written terminal app: it is already installed, it is
    a real pty so interactive programs work, and there is nothing to be
    gained from reimplementing it. Sized and coloured to sit with the rest
    rather than arriving as a white box from 1994.
    """
    log = open("/tmp/terminal.log", "a")
    subprocess.Popen(
        ["xterm", "-fa", "Monospace", "-fs", "11",
         "-bg", "#101318", "-fg", "#dfe4ea", "-cr", "#dfe4ea",
         "-geometry", "96x28", "-title", "Terminal",
         "-sb", "-rightbar"],
        stdout=log, stderr=log)


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
        self.live_name = None
        self.fps = 0                     # 0 means "use the wallpaper's own rate"
        self.rate = 0                    # the rate the wallpaper itself asked for
        self.busy = False                # the model is thinking
        self.seen = True                 # a browser has the screen open

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
        """Choose the wallpaper. `on` is its name — "galaxy", "matrix" — or a
        falsy value for a plain colour.

        Switching between two live ones means tearing the old one down first,
        or the new choice never takes.
        """
        if on and self.live_name != on:
            self.set_live(None)
            self.live_name = on
        elif not on:
            self.live_name = None

        if on and self.galaxy is None:
            self.galaxy, self.rate = make_wallpaper(on)
        elif not on and self.galaxy is not None:
            self.galaxy = None
            self.canvas.queue_draw()
        self._retime()

    # ── when the animation is allowed to run ────────────────────────────────
    # Three separate things can silence it, and they used to fight: whichever
    # one spoke last won, so answering a question with the panel closed left
    # the wallpaper spinning afterwards. They are gates now, not commands —
    # every one of them has to be open before a frame is drawn.
    def _retime(self):
        want = bool(self.galaxy) and not self.busy and self.seen
        if want and self.ticker is None:
            rate = self.fps or self.rate or 12
            self.ticker = GLib.timeout_add(int(1000 / rate), self._tick)
        elif not want and self.ticker is not None:
            GLib.source_remove(self.ticker)
            self.ticker = None

    def _tick(self):
        if self.galaxy is None:
            self.ticker = None
            return False
        self.galaxy.step()
        self.canvas.queue_draw()
        return True

    def set_busy(self, busy):
        """Stop animating while the model is working.

        The sandbox has four cores and the model wants all of them. Drawing
        4,200 points fourteen times a second is affordable when nothing else
        is happening and rude when an answer is being waited on.

        The galaxy object is kept — rebuilding it means regenerating every
        point, and the picture would visibly flicker each time somebody asked
        a question. Frozen mid-turn it just looks still. Getting the frame
        rate back used to mean calling make_wallpaper() purely to read the
        number off it, which built and discarded 5,100 points every time the
        clone finished thinking; the rate is remembered instead.
        """
        self.busy = busy
        self._retime()

    def set_seen(self, seen):
        """Stop animating when nobody has the screen open.

        This is the one that matters most. Every frame is a full-screen
        repaint, and over VNC a full-screen repaint is a full-screen frame to
        encode and send. With no viewer attached the sandbox was generating a
        video stream into a socket that nobody was reading from.
        """
        self.seen = seen
        self._retime()

    def relabel(self, look):
        # A changed frame rate has to tear the timer down and rebuild it;
        # GLib timeouts cannot be re-timed in place.
        wanted = int(look.get("fps", 0) or 0)
        if wanted != self.fps:
            self.fps = wanted
            if self.live_name:
                name = self.live_name
                self.set_live(None)
                self.set_live(name)
        chosen = look.get("wallpaper", "")
        self.set_live(chosen if chosen in LIVE else None)
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

        # What is currently on the taskbar, so it can be left alone when
        # nothing has changed. None rather than [] so the first pass always
        # paints, including the empty case.
        self.shown = None
        self.state = None

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
        if state != self.state:
            self.state = state
            text, css = self.PILLS.get(state, self.PILLS["idle"])
            self.pill.set_text(text)
            ctx = self.pill.get_style_context()
            for _, c in self.PILLS.values():
                ctx.remove_class(c)
            ctx.add_class(css)

        # Rebuild only when the window list has actually changed. It used to
        # tear down and recreate every button every two seconds regardless,
        # which is three things at once: a repaint of the whole taskbar strip
        # — 1440x48 of update for a picture identical to the last one, forever
        # — a churn of the AT-SPI tree the executor grounds on, so a widget
        # reference could go stale between being found and being pressed, and
        # a stream of GTK allocations for no reason. The taskbar is now still
        # unless something opened or closed.
        windows = open_windows()
        if windows != self.shown:
            self.shown = windows
            for child in self.tasks.get_children():
                self.tasks.remove(child)
            for wid, title in windows:
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
    outside this shell (by the executor, say) must appear too.

    One xdotool, not one per window. This used to run `search` and then a
    `getwindowname` for every result — with three windows open that is four
    processes spawned every two seconds, for as long as the machine is up,
    on a box with four cores that is also encoding a video stream. xdotool
    chains commands itself: `search ... getwindowname %@` prints one name per
    match, in match order.

    The chained form can misalign if a window closes between the two halves
    of the command, so the count is checked and the old one-at-a-time walk is
    kept as the fallback. Wrong names in a taskbar are worse than slow ones.
    """
    try:
        ids = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "."],
                             capture_output=True, text=True, timeout=4).stdout.split()
        names = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--name", ".", "getwindowname", "%@"],
            capture_output=True, text=True, timeout=4).stdout.splitlines()
    except (subprocess.SubprocessError, FileNotFoundError):
        return []

    if len(names) != len(ids):
        names = []
        for wid in ids:
            try:
                names.append(subprocess.run(["xdotool", "getwindowname", wid],
                                            capture_output=True, text=True,
                                            timeout=2).stdout.strip())
            except subprocess.SubprocessError:
                names.append("")

    seen = []
    for wid, name in zip(ids, names):
        name = name.strip()
        if name and name not in ("Desktop", "Taskbar") \
                and name not in [t for _, t in seen]:
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

        # Cheap enough to ask every second: two small reads out of /proc, no
        # process spawned. Doing it on a timer rather than on connect/disconnect
        # hooks means it also recovers from a browser that vanished without
        # closing its socket cleanly.
        seen = watching()
        if seen != state.get("seen"):
            state["seen"] = seen
            desktop.set_seen(seen)
        return True

    follow()
    GLib.timeout_add_seconds(1, follow)
    Gtk.main()


if __name__ == "__main__":
    main()
