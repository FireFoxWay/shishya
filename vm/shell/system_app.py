#!/usr/bin/env python3
"""
System — what the sandbox is using, and what you are giving it.

Two halves. The top is a live reading: cores, memory, disk. The bottom is
the part you can change — how much of the machine the desktop is allowed to
spend on looking nice, which is the only resource decision that takes effect
without restarting anything.

The numbers come from /proc rather than from shelling out to top, so reading
them costs almost nothing. A monitor that noticeably loads the machine it is
monitoring is telling you about itself.
"""

import json
import os
import shutil
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk   # noqa: E402

import common   # noqa: E402

LOOK = common.SHARED / ".desktop.json"
HZ = os.sysconf("SC_CLK_TCK")


def cpu_snapshot():
    """Busy and total jiffies, per core. Usage is a delta between two of
    these — a single reading tells you the average since boot, which is not
    what anybody means by "CPU usage"."""
    out = []
    with open("/proc/stat", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("cpu") or line.startswith("cpu "):
                continue
            parts = [int(x) for x in line.split()[1:]]
            idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
            out.append((sum(parts) - idle, sum(parts)))
    return out


def memory():
    info = {}
    with open("/proc/meminfo", encoding="utf-8") as f:
        for line in f:
            key, _, rest = line.partition(":")
            info[key] = int(rest.split()[0]) * 1024
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", 0)
    return total - available, total


class SystemApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="System")
        self.set_default_size(620, 640)
        self.connect("destroy", Gtk.main_quit)
        self.last = cpu_snapshot()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        head = Gtk.Label(xalign=0, margin=14)
        head.set_markup("<b>System</b>")
        root.pack_start(head, False, False, 0)

        # ── live ──
        root.pack_start(heading("Right now"), False, False, 0)
        self.cores = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                             margin_start=14, margin_end=14)
        root.pack_start(self.cores, False, False, 0)
        self.bars = []

        self.mem = self.meter("Memory")
        root.pack_start(self.mem[0], False, False, 0)
        self.disk = self.meter("Disk")
        root.pack_start(self.disk[0], False, False, 0)

        self.note = Gtk.Label(xalign=0, margin=14)
        self.note.set_opacity(.65)
        self.note.set_line_wrap(True)
        root.pack_start(self.note, False, False, 0)

        # ── what you can change ──
        root.pack_start(heading("What the desktop may spend"), False, False, 0)

        self.live = Gtk.CheckButton(label="Animate the wallpaper")
        self.live.get_accessible().set_name("Animate the wallpaper")
        self.live.set_margin_start(14)
        self.live.connect("toggled", self.on_live)
        root.pack_start(self.live, False, False, 0)

        hint = Gtk.Label(xalign=0, margin_start=36, margin_end=14)
        hint.set_opacity(.6)
        hint.set_line_wrap(True)
        hint.set_text("The live wallpapers cost about 5–7% of one core. They "
                      "already stop on their own while the AI is working; turn "
                      "this off to stop them entirely.")
        root.pack_start(hint, False, False, 0)

        root.pack_start(label_for("Frames per second"), False, False, 0)
        self.fps = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 4, 24, 1)
        self.fps.set_margin_start(14)
        self.fps.set_margin_end(14)
        self.fps.get_accessible().set_name("Frames per second")
        self.fps.connect("value-changed", self.on_fps)
        root.pack_start(self.fps, False, False, 0)

        # ── the sandbox's share of the machine ──
        root.pack_start(heading("The sandbox's share of the machine"), False, False, 0)
        self.share = Gtk.Label(xalign=0, margin_start=14, margin_end=14)
        self.share.set_line_wrap(True)
        root.pack_start(self.share, False, False, 0)

        self.load_look()
        self.refresh()
        GLib.timeout_add_seconds(2, self.refresh)

    def meter(self, name):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                      margin_start=14, margin_end=14, margin_top=10)
        row = Gtk.Box()
        title = Gtk.Label(label=name, xalign=0)
        value = Gtk.Label(xalign=1)
        value.set_opacity(.7)
        row.pack_start(title, True, True, 0)
        row.pack_end(value, False, False, 0)
        bar = Gtk.ProgressBar()
        bar.get_accessible().set_name(name)
        box.pack_start(row, False, False, 0)
        box.pack_start(bar, False, False, 0)
        return box, bar, value

    # ── settings ────────────────────────────────────────────────────────────

    def load_look(self):
        try:
            look = json.loads(LOOK.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            look = {}
        self.look = look
        self.live.set_active(look.get("wallpaper") in ("galaxy", "matrix"))
        self.fps.set_value(look.get("fps", 12))

    def save_look(self):
        LOOK.parent.mkdir(parents=True, exist_ok=True)
        LOOK.write_text(json.dumps(self.look, indent=2), encoding="utf-8")

    def on_live(self, btn):
        if btn.get_active():
            # Restore whatever live wallpaper was last chosen rather than
            # picking one for them.
            self.look["wallpaper"] = self.look.get("last_live", "galaxy")
        else:
            if self.look.get("wallpaper") in ("galaxy", "matrix"):
                self.look["last_live"] = self.look["wallpaper"]
            self.look["wallpaper"] = "#10151c"
        self.save_look()

    def on_fps(self, scale):
        self.look["fps"] = int(scale.get_value())
        self.save_look()

    # ── live readings ───────────────────────────────────────────────────────

    def refresh(self):
        now = cpu_snapshot()
        while len(self.bars) < len(now):
            box, bar, value = self.meter(f"Core {len(self.bars) + 1}")
            self.cores.pack_start(box, False, False, 0)
            self.bars.append((bar, value))
            self.cores.show_all()

        busiest = 0.0
        for i, ((busy, total), (was_busy, was_total)) in enumerate(zip(now, self.last)):
            span = total - was_total
            use = (busy - was_busy) / span if span else 0.0
            use = min(max(use, 0.0), 1.0)
            busiest = max(busiest, use)
            bar, value = self.bars[i]
            bar.set_fraction(use)
            value.set_text(f"{use * 100:.0f}%")
        self.last = now

        used, total = memory()
        self.mem[1].set_fraction(used / total if total else 0)
        self.mem[2].set_text(f"{used / 1e9:.1f} of {total / 1e9:.1f} GB")

        usage = shutil.disk_usage("/")
        self.disk[1].set_fraction(usage.used / usage.total)
        self.disk[2].set_text(f"{usage.used / 1e9:.0f} of {usage.total / 1e9:.0f} GB")

        state = "idle"
        try:
            state = (common.SHARED / ".state").read_text(encoding="utf-8").strip() or "idle"
        except OSError:
            pass
        if state == "working":
            self.note.set_text("The AI is working — the wallpaper has stopped "
                               "animating so the cores go to it.")
        elif busiest > 0.7:
            self.note.set_text("Something is busy. If it is not the AI, check "
                               "what is running.")
        else:
            self.note.set_text("Idle. The model runs on the host's GPU, so it "
                               "does not show up in these cores until a script runs.")

        self.share.set_text(
            f"{len(now)} cores and {total / 1e9:.0f} GB are given to the sandbox. "
            f"Changing that is done on the host, in vm/lima.yaml, and needs the "
            f"sandbox restarted — it is not something the clone can grant itself.")
        return True


def heading(title):
    lbl = Gtk.Label(xalign=0, margin_start=14, margin_top=14, margin_bottom=2)
    lbl.set_markup(f"<small><b>{title.upper()}</b></small>")
    lbl.set_opacity(.55)
    return lbl


def label_for(title):
    lbl = Gtk.Label(xalign=0, margin_start=14, margin_top=8)
    lbl.set_markup(f"<small>{title}</small>")
    lbl.set_opacity(.6)
    return lbl


if __name__ == "__main__":
    SystemApp().show_all()
    Gtk.main()
