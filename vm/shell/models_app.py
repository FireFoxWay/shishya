#!/usr/bin/env python3
"""
Models — choose which AI does which job, and hold only what you need.

The idea this app exists for: there is no single model a school should have
to install. Answering a policy question wants something small and quick;
writing code wants something trained on code; neither needs twenty gigabytes
sitting on a staff-room laptop. So each job names its own model, and you
install only the ones you use.

Downloading needs the network, which is normally locked. That is deliberate:
adding a model is a decision someone makes on purpose, not something the
sandbox can do for itself while nobody is looking.
"""

import json
import threading
import urllib.error
import urllib.request

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk   # noqa: E402

import common   # noqa: E402

JOBS = [
    ("answers",   "Answering questions",
     "Reads your documents and answers from them. Wants care, not size."),
    ("code",      "Writing code",
     "Writes the small programs that do the counting. A code-trained model earns its space here."),
    ("documents", "Writing documents",
     "Drafts notes, letters and decks. Follows structure more than it reasons."),
]

# Suggested rather than exhaustive. Sizes are approximate and shown so the
# trade is visible before anything is downloaded.
CATALOGUE = [
    ("qwen2.5:3b",        "1.9 GB", "Small and quick. Good for answering."),
    ("llama3.2:3b",       "2.0 GB", "Small, general purpose."),
    ("qwen2.5-coder:7b",  "4.7 GB", "Trained on code. Best for the Code app."),
    ("deepseek-r1:8b",    "5.2 GB", "Reasons before answering. Slower, more careful."),
    ("gpt-oss:latest",   "13.8 GB", "Large and general. Wants a roomy machine."),
]


class ModelsApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Models")
        self.set_default_size(760, 660)
        self.connect("destroy", Gtk.main_quit)
        self.installed = {}
        self.choice = self.load_choice()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        head = Gtk.Box(spacing=10, margin=14)
        title = Gtk.Label(xalign=0)
        title.set_markup("<b>Models</b>")
        head.pack_start(title, False, False, 0)
        self.total = Gtk.Label(xalign=0)
        self.total.set_opacity(.7)
        head.pack_start(self.total, True, True, 0)
        refresh = Gtk.Button(label="Refresh")
        refresh.get_accessible().set_name("Refresh")
        refresh.connect("clicked", lambda _b: self.reload())
        head.pack_end(refresh, False, False, 0)
        root.pack_start(head, False, False, 0)

        # ── which model does which job ──
        root.pack_start(section("Which model does which job"), False, False, 0)
        self.pickers = {}
        for job, label, why in JOBS:
            row = Gtk.Box(spacing=10, margin_start=14, margin_end=14, margin_bottom=8)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            name = Gtk.Label(label=label, xalign=0)
            hint = Gtk.Label(label=why, xalign=0)
            hint.set_opacity(.6)
            hint.set_line_wrap(True)
            text.pack_start(name, False, False, 0)
            text.pack_start(hint, False, False, 0)
            row.pack_start(text, True, True, 0)

            picker = Gtk.ComboBoxText()
            picker.get_accessible().set_name(f"Model for {label}")
            picker.set_size_request(210, -1)
            picker.connect("changed", self.on_pick, job)
            self.pickers[job] = picker
            row.pack_end(picker, False, False, 0)
            root.pack_start(row, False, False, 0)

        # ── what is installed ──
        root.pack_start(section("Installed on this machine"), False, False, 0)
        self.store = Gtk.ListStore(str, str, str)
        view = Gtk.TreeView(model=self.store)
        view.get_accessible().set_name("Installed models")
        for i, col in enumerate(("Model", "Size", "Used for")):
            view.append_column(Gtk.TreeViewColumn(col, Gtk.CellRendererText(), text=i))
        self.view = view
        scroll = Gtk.ScrolledWindow(margin=14)
        scroll.set_size_request(-1, 150)
        scroll.add(view)
        root.pack_start(scroll, False, False, 0)

        # ── available ──
        root.pack_start(section("Available to add"), False, False, 0)
        self.avail = Gtk.ListStore(str, str, str)
        av = Gtk.TreeView(model=self.avail)
        av.get_accessible().set_name("Available models")
        for i, col in enumerate(("Model", "Size", "What it is for")):
            av.append_column(Gtk.TreeViewColumn(col, Gtk.CellRendererText(), text=i))
        self.av = av
        av_scroll = Gtk.ScrolledWindow(margin_start=14, margin_end=14)
        av_scroll.set_size_request(-1, 130)
        av_scroll.add(av)
        root.pack_start(av_scroll, True, True, 0)

        feet = Gtk.Box(spacing=8, margin=14)
        self.status = Gtk.Label(xalign=0)
        self.status.set_opacity(.7)
        feet.pack_start(self.status, True, True, 0)
        for label, handler in (("Remove", self.on_remove), ("Add selected", self.on_add)):
            b = Gtk.Button(label=label)
            b.get_accessible().set_name(label)
            b.connect("clicked", handler)
            feet.pack_end(b, False, False, 0)
        root.pack_start(feet, False, False, 0)

        self.reload()

    # ── state ───────────────────────────────────────────────────────────────

    def load_choice(self):
        try:
            return json.loads(common.ROLES.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_choice(self):
        common.ROLES.parent.mkdir(parents=True, exist_ok=True)
        common.ROLES.write_text(json.dumps(self.choice, indent=2), encoding="utf-8")

    def reload(self):
        try:
            with urllib.request.urlopen(f"{common.HOST}/api/tags", timeout=10) as r:
                data = json.loads(r.read())
        except urllib.error.URLError as e:
            self.say(f"Can't reach the model service: {e}")
            return

        self.installed = {}
        for m in data.get("models", []):
            self.installed[m["name"]] = m.get("size", 0)

        # A cloud-hosted entry is not a local model, and letting one be picked
        # would quietly break the one promise this whole project makes.
        self.installed = {n: s for n, s in self.installed.items() if "cloud" not in n}

        used = {}
        for job, label, _ in JOBS:
            chosen = self.choice.get(job) or common.MODEL
            used.setdefault(chosen, []).append(label.split()[0].lower())

        self.store.clear()
        for name, size in sorted(self.installed.items()):
            self.store.append([name, f"{size / 1e9:.1f} GB",
                               ", ".join(used.get(name, [])) or "—"])
        total = sum(self.installed.values()) / 1e9
        self.total.set_text(f"{len(self.installed)} installed · {total:.1f} GB on disk")

        self.avail.clear()
        for name, size, why in CATALOGUE:
            if name not in self.installed:
                self.avail.append([name, size, why])

        for job, _, _ in JOBS:
            picker = self.pickers[job]
            picker.handler_block_by_func(self.on_pick)
            picker.remove_all()
            names = sorted(self.installed)
            for n in names:
                picker.append_text(n)
            chosen = self.choice.get(job) or common.MODEL
            if chosen in names:
                picker.set_active(names.index(chosen))
            picker.handler_unblock_by_func(self.on_pick)

        self.say("Each job uses the model chosen above.")

    # ── actions ─────────────────────────────────────────────────────────────

    def on_pick(self, combo, job):
        name = combo.get_active_text()
        if not name:
            return
        self.choice[job] = name
        self.save_choice()
        self.say(f"{job} → {name}")
        self.reload()

    def on_add(self, _b):
        model, it = self.av.get_selection().get_selected()
        if not it:
            return self.say("Pick one from the list below first.")
        name = model[it][0]
        self.say(f"Downloading {name} — this needs the network unlocked.")
        common.set_state("working")
        threading.Thread(target=self._pull, args=(name,), daemon=True).start()

    def _pull(self, name):
        body = json.dumps({"name": name}).encode()
        req = urllib.request.Request(f"{common.HOST}/api/pull", body,
                                     {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3600) as r:
                for line in r:
                    try:
                        step = json.loads(line)
                    except ValueError:
                        continue
                    if "total" in step and step.get("completed"):
                        pct = 100 * step["completed"] / max(1, step["total"])
                        GLib.idle_add(self.say, f"{name}: {pct:.0f}%")
            GLib.idle_add(self.done, f"{name} is ready.")
        except urllib.error.URLError as e:
            GLib.idle_add(self.done,
                          f"Could not download {name} — {e}. If the network is "
                          f"locked, that is why; unlock it, add the model, lock it again.")

    def on_remove(self, _b):
        model, it = self.view.get_selection().get_selected()
        if not it:
            return self.say("Pick an installed model first.")
        name = model[it][0]
        if name in self.choice.values():
            return self.say(f"{name} is doing a job — give that job to another model first.")
        req = urllib.request.Request(f"{common.HOST}/api/delete",
                                     json.dumps({"name": name}).encode(),
                                     {"Content-Type": "application/json"}, method="DELETE")
        try:
            urllib.request.urlopen(req, timeout=60)
            self.done(f"Removed {name}.")
        except urllib.error.URLError as e:
            self.say(f"Could not remove it: {e}")

    def done(self, message):
        self.say(message)
        common.set_state("idle")
        self.reload()
        return False

    def say(self, text):
        self.status.set_text(text)
        return False


def section(title):
    lbl = Gtk.Label(xalign=0, margin_start=14, margin_top=10, margin_bottom=4)
    lbl.set_markup(f"<small><b>{title.upper()}</b></small>")
    lbl.set_opacity(.55)
    return lbl


if __name__ == "__main__":
    ModelsApp().show_all()
    Gtk.main()
