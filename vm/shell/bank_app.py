#!/usr/bin/env python3
"""
Banking — your accounts and what goes out of them every month.

Runs inside the sandbox, like every other app here, and reads and writes
shared/money/ through money.py.

── What this is not, and will not become ───────────────────────────────────

It does not connect to a bank. It never asks for a customer ID, a password,
an OTP or a UPI PIN, and there is no field here that would accept one. Every
figure is one you typed in yourself or exported from your own statement.

That is a deliberate design decision, not a missing feature. The argument
this whole project makes is that the machine keeps what is on it; an app that
holds live banking credentials would be the one place where being wrong costs
somebody their savings rather than an afternoon. The sandbox has no network,
so a credential typed here could not reach a bank anyway — which would make
the field a lie as well as a hazard.

What it is for: seeing the total. Most people can name three standing
payments and are genuinely surprised by the sum of all of them, and that
number is the one worth putting on a screen.
"""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk   # noqa: E402

import common          # noqa: E402
import money           # noqa: E402

KINDS = ["current", "savings", "card", "loan", "cash"]
DUES = ["emi", "bill", "rent", "insurance", "subscription", "other"]


def rupees(n):
    return f"₹{float(n or 0):,.2f}"


class Editor(Gtk.Box):
    """A table you can add rows to and delete rows from, saved as a whole.

    Whole-file writes, like books.py: a partial write of somebody's accounts
    is worse than no write, and a rename is the only operation the filesystem
    will promise not to tear.
    """

    def __init__(self, columns, kinds, load, save, on_change):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.columns, self.kinds = columns, kinds
        self.load, self.save, self.on_change = load, save, on_change

        self.store = Gtk.ListStore(*([str] * len(columns)))
        self.view = Gtk.TreeView(model=self.store)
        self.view.get_accessible().set_name("rows")
        for i, col in enumerate(columns):
            cell = Gtk.CellRendererText(editable=True)
            cell.connect("edited", self.on_edit, i)
            self.view.append_column(Gtk.TreeViewColumn(col.title(), cell, text=i))

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.view)
        self.pack_start(scroll, True, True, 0)

        bar = Gtk.Box(spacing=8)
        for label, fn in (("Add a row", self.on_add), ("Delete the selected row", self.on_del)):
            b = Gtk.Button(label=label)
            b.get_accessible().set_name(label)
            b.connect("clicked", fn)
            bar.pack_start(b, False, False, 0)
        self.pack_start(bar, False, False, 0)
        self.reload()

    def reload(self):
        self.store.clear()
        for r in self.load():
            self.store.append([str(r.get(c, "")) for c in self.columns])

    def rows(self):
        return [{c: row[i] for i, c in enumerate(self.columns)} for row in self.store]

    def commit(self):
        self.save(self.rows())
        self.on_change()

    def on_edit(self, _cell, path, text, column):
        self.store[path][column] = text
        self.commit()

    def on_add(self, _b):
        blank = [""] * len(self.columns)
        blank[0] = f"R{len(self.store) + 1}"
        if "kind" in self.columns:
            blank[self.columns.index("kind")] = self.kinds[0]
        self.store.append(blank)
        self.commit()

    def on_del(self, _b):
        model, it = self.view.get_selection().get_selected()
        if it:
            model.remove(it)
            self.commit()


class BankApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Banking")
        self.set_default_size(900, 640)
        self.connect("destroy", Gtk.main_quit)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=14)
        self.add(root)

        head = Gtk.Label(xalign=0)
        head.set_markup("<b>Banking</b>")
        root.pack_start(head, False, False, 0)

        self.summary = Gtk.Label(xalign=0)
        self.summary.set_opacity(.72)
        root.pack_start(self.summary, False, False, 0)

        note = Gtk.Label(xalign=0, wrap=True)
        note.set_opacity(.6)
        note.set_text("Figures you enter yourself. This app has no connection to "
                      "any bank and no field that will take a password, a PIN or "
                      "an OTP — the sandbox has no network to send one over.")
        root.pack_start(note, False, False, 0)

        tabs = Gtk.Notebook()
        root.pack_start(tabs, True, True, 0)

        self.accounts = Editor(money.ACCOUNT_COLUMNS, KINDS,
                               money.accounts, money.save_accounts, self.refresh)
        tabs.append_page(self.accounts, Gtk.Label(label="Accounts"))

        self.dues = Editor(money.COMMITMENT_COLUMNS, DUES,
                           money.commitments, money.save_commitments, self.refresh)
        tabs.append_page(self.dues, Gtk.Label(label="Every month"))

        self.refresh()

    def refresh(self):
        p = money.position()
        use = money.utilisation()
        soon = money.due_soon(7)
        bits = [f"Have {rupees(p['have'])}", f"owe {rupees(p['owe'])}",
                f"net {rupees(p['net'])}",
                f"{rupees(money.monthly())} goes out every month"]
        if use is not None:
            bits.append(f"cards at {use}% of their limit")
        if soon:
            bits.append(f"{len(soon)} due within the week")
        self.summary.set_text(" · ".join(bits))


if __name__ == "__main__":
    common.SHARED.mkdir(parents=True, exist_ok=True)
    BankApp().show_all()
    Gtk.main()
