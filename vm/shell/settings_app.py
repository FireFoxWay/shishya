#!/usr/bin/env python3
"""
Settings — make the desktop yours.

Wallpaper, accent colour and icon size, written to a config file the shell
watches. Changes apply live: the desktop re-reads the file rather than being
restarted, because restarting the shell would close whatever the clone was
in the middle of.
"""

import json

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk   # noqa: E402

import common   # noqa: E402

CONFIG = common.SHARED / ".desktop.json"

DEFAULTS = {"wallpaper": "#10151c", "accent": "#0078d4", "icon_size": 96,
            "wallmark": "SHISHYA SANDBOX"}

# Named rather than a raw colour wheel: these read as choices someone made,
# and any of them stays legible behind white icon labels.
WALLPAPERS = [
    ("Galaxy",    "galaxy"),
    ("Matrix",    "matrix"),
    ("Slate",     "#10151c"),
    ("Indigo",    "#141a2e"),
    ("Forest",    "#101c17"),
    ("Plum",      "#1b1220"),
    ("Graphite",  "#161616"),
]
ACCENTS = [
    ("Blue",      "#0078d4"),
    ("Teal",      "#0f8b8d"),
    ("Marigold",  "#c9821a"),
    ("Rose",      "#b4436c"),
    ("Violet",    "#6f5bd1"),
]


def load():
    try:
        return {**DEFAULTS, **json.loads(CONFIG.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)


def save(config):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(config, indent=2), encoding="utf-8")


class SettingsApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Settings")
        self.set_default_size(480, 500)
        self.connect("destroy", Gtk.main_quit)
        self.config = load()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=16)
        self.add(root)

        title = Gtk.Label(xalign=0)
        title.set_markup("<b>Settings</b>")
        root.pack_start(title, False, False, 0)

        root.pack_start(self.swatches("Wallpaper", WALLPAPERS, "wallpaper"), False, False, 0)
        root.pack_start(self.swatches("Accent", ACCENTS, "accent"), False, False, 0)

        root.pack_start(label("Icon size"), False, False, 0)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 64, 140, 4)
        scale.set_value(self.config["icon_size"])
        scale.get_accessible().set_name("Icon size")
        scale.connect("value-changed", self.on_size)
        root.pack_start(scale, False, False, 0)

        root.pack_start(label("Wallpaper text"), False, False, 0)
        entry = Gtk.Entry(text=self.config["wallmark"])
        entry.get_accessible().set_name("Wallpaper text")
        entry.connect("changed", self.on_mark)
        root.pack_start(entry, False, False, 0)

        self.note = Gtk.Label(xalign=0, margin_top=10)
        self.note.set_opacity(.7)
        self.note.set_text("Changes apply to the desktop within a second.")
        root.pack_start(self.note, False, False, 0)

        reset = Gtk.Button(label="Back to defaults")
        reset.get_accessible().set_name("Back to defaults")
        reset.connect("clicked", self.on_reset)
        root.pack_end(reset, False, False, 0)

    def swatches(self, heading, options, key):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(label(heading), False, False, 0)
        row = Gtk.Box(spacing=8)
        for name, colour in options:
            btn = Gtk.Button()
            btn.set_size_request(66, 40)
            btn.set_tooltip_text(name)
            btn.get_accessible().set_name(f"{heading} {name}")
            swatch = Gtk.DrawingArea()
            swatch.connect("draw", self.paint, colour)
            btn.add(swatch)
            btn.connect("clicked", self.on_pick, key, colour)
            row.pack_start(btn, False, False, 0)
        box.pack_start(row, False, False, 0)
        return box

    @staticmethod
    def paint(area, cr, colour):
        # The live wallpaper has no single colour, so its swatch is a tiny
        # rendering of the thing itself rather than a stand-in shade.
        if colour in ("galaxy", "matrix"):
            cache = getattr(SettingsApp, "_previews", None)
            if cache is None:
                cache = SettingsApp._previews = {}
            if colour not in cache:
                if colour == "matrix":
                    import matrix
                    cache[colour] = matrix.Matrix()
                else:
                    import galaxy
                    cache[colour] = galaxy.Galaxy()
            alloc = area.get_allocation()
            cache[colour].draw(cr, alloc.width, alloc.height)
            return
        rgba = Gdk.RGBA()
        rgba.parse(colour)
        cr.set_source_rgb(rgba.red, rgba.green, rgba.blue)
        cr.paint()

    def on_pick(self, _b, key, colour):
        self.config[key] = colour
        self.apply()

    def on_size(self, scale):
        self.config["icon_size"] = int(scale.get_value())
        self.apply()

    def on_mark(self, entry):
        self.config["wallmark"] = entry.get_text()
        self.apply()

    def on_reset(self, _b):
        self.config = dict(DEFAULTS)
        self.apply()
        self.note.set_text("Back to defaults.")

    def apply(self):
        save(self.config)


def label(text):
    lbl = Gtk.Label(xalign=0, margin_top=10)
    lbl.set_markup(f"<small>{text.upper()}</small>")
    lbl.set_opacity(.6)
    return lbl


if __name__ == "__main__":
    SettingsApp().show_all()
    Gtk.main()
