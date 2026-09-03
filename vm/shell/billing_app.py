#!/usr/bin/env python3
"""
Billing — the counter. Ring up a sale, hand over a bill, and the books update.

The app that makes everything else real. Findings, Reports and the scheduled
audit used to read files exported from somewhere else; this produces the
shop's own data as it happens.

Two tabs, because two different jobs: the Counter is what somebody uses two
hundred times a day and must stay uncluttered, and Bills is where you go
when something went wrong — a return, a void, a reprint. Putting a Void
button on the counter is how yesterday's takings get cancelled by a slip.

The books themselves live in books.py: GST-inclusive pricing, append-only
sales, and corrections written as new rows rather than edits. Nothing here
parses a CSV.
"""

import subprocess
import sys
import time
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk   # noqa: E402

import approvals  # noqa: E402
import books      # noqa: E402
import common     # noqa: E402
import invoice    # noqa: E402

SEED = common.TRAINING / "01_20Retail_20Inventory.xlsx"


def seed_catalogue():
    """First run: stock the counter from whatever inventory exists.

    A billing app with an empty product list demonstrates a form, not a shop.
    """
    common.BILLING.mkdir(parents=True, exist_ok=True)
    if books.CATALOGUE.exists():
        return
    rows = []
    if SEED.exists():
        try:
            import pandas as pd
            for _, r in pd.read_excel(SEED).iterrows():
                rows.append({
                    "id": str(r.get("Product ID", "")).strip(),
                    "name": str(r.get("Product Name", "")).strip(),
                    "category": str(r.get("Category", "")).strip(),
                    "cost": f"{float(r.get('Unit Cost', 0) or 0):.2f}",
                    "price": f"{float(r.get('Retail Price', 0) or 0):.2f}",
                    "stock": str(int(float(r.get("Closing Stock", 0) or 0))),
                    "reorder": str(int(float(r.get("Reorder Point", 0) or 0))),
                    "gst": books.DEFAULT_GST,
                })
        except Exception:
            rows = []
    books.write_catalogue([r for r in rows if r["id"] and r["name"]])


class BillingApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Billing")
        self.set_default_size(980, 700)
        self.connect("destroy", Gtk.main_quit)

        seed_catalogue()
        self.catalogue = books.read_catalogue()
        self.by_id = {r["id"]: r for r in self.catalogue}
        self.bill = {}            # id -> qty on the current bill
        self.last_bill = None

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        self.status = Gtk.Label(xalign=0, margin_start=14, margin_end=14,
                                margin_top=8)
        self.status.set_opacity(.75)
        self.status.set_line_wrap(True)
        self.status.get_accessible().set_name("Status")

        tabs = Gtk.Notebook(margin=10)
        tabs.append_page(self.counter_page(), Gtk.Label(label="Counter"))
        tabs.append_page(self.bills_page(), Gtk.Label(label="Bills"))
        tabs.connect("switch-page", lambda *_a: self.show_bills())
        root.pack_start(tabs, True, True, 0)
        root.pack_start(self.status, False, False, 0)

        self.show_results()
        self.paint_bill()
        self.greet()

    # ── first run ──

    def greet(self):
        """Say what this is, once, to somebody who has never seen it.

        A counter that opens onto a thousand products and no explanation is
        a counter people ask a colleague about instead of using.
        """
        if books.read_sales():
            self.status.set_text(f"{len(self.catalogue)} products stocked · "
                                 f"you are the {common.role()}")
            return
        self.status.set_markup(
            "<b>Nothing has been billed yet.</b>  Type a product name above, "
            "click it to add it to the bill, then Save the bill. "
            "Prices include GST, the stock count goes down as you sell, and "
            "every bill can be printed or corrected from the Bills tab.")

    # ── counter ──

    def counter_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        bar = Gtk.Box(spacing=8, margin=10)
        self.search = Gtk.Entry(placeholder_text="Type a product name or code")
        self.search.get_accessible().set_name("Product search")
        self.search.connect("changed", lambda _e: self.show_results())
        self.search.connect("activate", self.on_first_result)
        bar.pack_start(self.search, True, True, 0)

        self.customer = Gtk.Entry(placeholder_text="Customer (optional)",
                                  width_chars=18)
        self.customer.get_accessible().set_name("Customer")
        bar.pack_end(self.customer, False, False, 0)
        page.pack_start(bar, False, False, 0)

        split = Gtk.Paned(margin=10)
        self.results = Gtk.ListBox()
        self.results.get_accessible().set_name("Search results")
        left = Gtk.ScrolledWindow()
        left.set_size_request(430, -1)
        left.add(self.results)
        split.pack1(left, False, False)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.lines = Gtk.ListBox()
        self.lines.get_accessible().set_name("Bill")
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.add(self.lines)
        right.pack_start(scroll, True, True, 0)

        self.totals = Gtk.Label(xalign=1, margin=8)
        self.totals.get_accessible().set_name("Total")
        right.pack_start(self.totals, False, False, 0)
        split.pack2(right, True, False)
        page.pack_start(split, True, True, 0)

        feet = Gtk.Box(spacing=8, margin=10)
        for label, handler in (("Clear the bill", self.on_clear),
                               ("Print the last bill", self.on_print),
                               ("Save the bill", self.on_save)):
            b = Gtk.Button(label=label)
            b.get_accessible().set_name(label)
            b.connect("clicked", handler)
            feet.pack_end(b, False, False, 0)
        page.pack_start(feet, False, False, 0)
        return page

    def matches(self):
        want = self.search.get_text().strip().lower()
        if not want:
            return [r for r in self.catalogue
                    if books.number(r["stock"]) <= books.number(r["reorder"])][:40]
        return [r for r in self.catalogue
                if want in r["name"].lower() or want in r["id"].lower()][:60]

    def show_results(self):
        for row in self.results.get_children():
            self.results.remove(row)
        self.found = self.matches()
        for r in self.found:
            stock = books.number(r["stock"])
            row = Gtk.ListBoxRow()
            # A flat button, not a bare row: a GtkListBoxRow publishes no
            # action to the accessibility layer, so nothing could press it
            # and the counter could not be driven or taught.
            note = "OUT OF STOCK" if stock <= 0 else f"{stock:.0f} left"
            hit = Gtk.Button(label=f"{r['name']}   ₹{books.money(r['price'])}"
                                   f"  ·  {note}  ·  GST {r['gst']}%")
            hit.set_relief(Gtk.ReliefStyle.NONE)
            hit.get_child().set_xalign(0)
            hit.get_accessible().set_name(f"{r['name']} {r['id']}")
            hit.connect("clicked", lambda _b, pid=r["id"]: self.add_to_bill(pid))
            row.add(hit)
            self.results.add(row)
        self.results.show_all()

    def on_first_result(self, _entry):
        if self.found:
            self.add_to_bill(self.found[0]["id"])

    # NOT add()/remove(): this is a Gtk.Window and Gtk.Container owns both
    # names. Shadowing add() once left the window with no contents at all.
    def add_to_bill(self, pid):
        item = self.by_id.get(pid)
        if not item:
            return
        stock = books.number(item["stock"])
        if self.bill.get(pid, 0) + 1 > stock:
            self.status.set_text(f"Only {stock:.0f} of {item['name']} left.")
            return
        self.bill[pid] = self.bill.get(pid, 0) + 1
        self.paint_bill()

    def remove_from_bill(self, pid):
        if pid in self.bill:
            self.bill[pid] -= 1
            if self.bill[pid] <= 0:
                del self.bill[pid]
        self.paint_bill()

    def paint_bill(self):
        for row in self.lines.get_children():
            self.lines.remove(row)
        total = tax = 0.0
        for pid, qty in self.bill.items():
            item = self.by_id[pid]
            amount = books.number(item["price"]) * qty
            total += amount
            tax += books.tax_within(item["price"], item["gst"]) * qty
            row = Gtk.ListBoxRow()
            line = Gtk.Box(spacing=8, margin=6)
            text = Gtk.Label(xalign=0, label=f"{qty} × {item['name']}")
            text.set_line_wrap(True)
            line.pack_start(text, True, True, 0)
            line.pack_start(Gtk.Label(xalign=1, label=f"₹{books.money(amount)}"),
                            False, False, 0)
            less = Gtk.Button(label="−")
            less.get_accessible().set_name(f"Remove one {item['name']}")
            less.connect("clicked", lambda _b, p=pid: self.remove_from_bill(p))
            line.pack_end(less, False, False, 0)
            row.add(line)
            self.lines.add(row)
        self.totals.set_markup(
            f"<small>of which GST ₹{books.money(tax)}</small>\n"
            f"<b>Total  ₹{books.money(total)}</b>")
        self.totals.get_accessible().set_name(f"Total {books.money(total)}")
        self.lines.show_all()

    def on_clear(self, _b):
        self.bill = {}
        self.paint_bill()
        self.status.set_text("Bill cleared.")

    def on_save(self, _b):
        if not self.bill:
            self.status.set_text("Nothing on the bill yet.")
            return
        number = books.new_bill_number()
        who = self.customer.get_text().strip()
        if who:
            books.remember_customer(who)
        rows = [books.line(number, "sale", self.by_id[pid], qty, who)
                for pid, qty in self.bill.items()]
        books.record(rows)

        for pid, qty in self.bill.items():
            item = self.by_id[pid]
            item["stock"] = str(int(books.number(item["stock"]) - qty))
        books.write_catalogue(self.catalogue)

        total = sum(books.number(r["amount"]) for r in rows)
        path = invoice.write(number, rows, who)
        self.last_bill = number
        self.bill = {}
        self.customer.set_text("")
        self.paint_bill()
        self.show_results()
        self.status.set_text(f"Saved {number} — ₹{books.money(total)}. "
                             f"Bill written to {path.parent.name}/{path.name}.")

    def on_print(self, _b):
        number = self.last_bill or (books.bills(1)[0]["bill"] if books.bills(1) else None)
        if not number:
            self.status.set_text("Nothing has been billed yet.")
            return
        path = invoice.write(number, books.bill_rows(number))
        if not path:
            self.status.set_text(f"Nothing to print for {number}.")
            return
        subprocess.Popen([sys.executable,
                          str(Path(__file__).parent / "files_app.py"),
                          str(path.parent)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.status.set_text(f"{number} is ready to print — {path.name} in "
                             f"Work/Bills. Open it and print from there.")

    # ── bills ──

    def bills_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.bill_list = Gtk.ListBox()
        self.bill_list.get_accessible().set_name("Recent bills")
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.add(self.bill_list)
        page.pack_start(scroll, True, True, 0)
        return page

    def show_bills(self):
        # Anything the head approved since the last look, performed now.
        for request in self.approved_voids():
            count, message = books.void(request["target"])
            approvals.decide(request["id"], True, note="done") \
                if request.get("state") == approvals.PENDING else None
            self._mark_done(request["id"])
            self.catalogue = books.read_catalogue()
            self.by_id = {r["id"]: r for r in self.catalogue}
            self.status.set_text(f"Head approved: {message}")

        for row in self.bill_list.get_children():
            self.bill_list.remove(row)
        recent = books.bills(30)
        if not recent:
            row = Gtk.ListBoxRow()
            row.add(Gtk.Label(label="No bills yet. Ring one up on the Counter.",
                              margin=14, xalign=0))
            self.bill_list.add(row)
            self.bill_list.show_all()
            return

        for entry in recent:
            row = Gtk.ListBoxRow()
            line = Gtk.Box(spacing=8, margin=6)
            mark = "  ·  VOIDED" if entry["void"] else ""
            text = Gtk.Label(xalign=0, label=(
                f"{entry['bill']}  ·  {entry['at'][:16]}  ·  "
                f"₹{books.money(entry['total'])}"
                f"{'  ·  ' + entry['customer'] if entry['customer'] else ''}{mark}"))
            text.set_line_wrap(True)
            line.pack_start(text, True, True, 0)

            printit = Gtk.Button(label="Print")
            printit.get_accessible().set_name(f"Print {entry['bill']}")
            printit.connect("clicked", lambda _b, n=entry["bill"]: self.print_one(n))
            line.pack_end(printit, False, False, 0)

            back = Gtk.Button(label="Return an item")
            back.get_accessible().set_name(f"Return from {entry['bill']}")
            back.set_sensitive(not entry["void"])
            back.connect("clicked", lambda _b, n=entry["bill"]: self.returns_for(n))
            line.pack_end(back, False, False, 0)

            # Voiding is the head's, not the clerk's: it cancels takings that
            # have already been counted, and it is the one action here that a
            # slip of the hand should not be able to perform.
            # A clerk is not simply refused. Being blocked with no way to ask
            # is how people work around software: a clerk who cannot void a
            # mistaken bill rings up a correcting sale instead, and the books
            # carry two wrong entries rather than one right correction.
            head = common.may("void")
            kill = Gtk.Button(label="Void" if head else "Ask to void")
            kill.get_accessible().set_name(
                f"{'Void' if head else 'Ask to void'} {entry['bill']}")
            kill.set_sensitive(not entry["void"])
            if not head:
                kill.set_tooltip_text("Sends a request to the head")
            kill.connect("clicked", lambda _b, n=entry["bill"], e=entry:
                         self.void_one(n) if head else self.ask_to_void(n, e))
            line.pack_end(kill, False, False, 0)

            row.add(line)
            self.bill_list.add(row)
        self.bill_list.show_all()

    def _mark_done(self, request_id):
        """Note that an approved request has been carried out, so reopening
        the tab does not void the same bill a second time."""
        rows = approvals._read()
        for r in rows:
            if r.get("id") == request_id:
                r["note"] = "done"
        approvals._write(rows)

    def print_one(self, number):
        path = invoice.write(number, books.bill_rows(number))
        self.status.set_text(f"{path.name} written to Work/Bills."
                             if path else f"Nothing to print for {number}.")

    def ask_to_void(self, number, entry):
        """Raise a request and say plainly that nothing has happened yet."""
        waiting = [r for r in approvals.pending()
                   if r.get("what") == "void" and r.get("target") == number]
        if waiting:
            self.status.set_text(f"Already asked — {number} is waiting for the "
                                 f"head to decide.")
            return
        approvals.ask("void", f"Void {number}, ₹{books.money(entry['total'])}"
                              + (f" for {entry['customer']}" if entry["customer"] else ""),
                      target=number)
        self.status.set_text(f"Asked the head to void {number}. "
                             f"The bill still stands until they decide.")
        self.show_bills()

    def approved_voids(self):
        """Requests the head has granted and this app has not yet acted on.

        Approving records a decision; performing it is this app's job. Kept
        apart deliberately — a decision that half-performed an action would
        leave the books in a state nobody asked for.
        """
        done = []
        for r in approvals.recent(50):
            if r.get("what") != "void" or r.get("state") != "approved":
                continue
            if r.get("note") == "done":
                continue
            done.append(r)
        return done

    def void_one(self, number):
        if not common.may("void"):
            self.status.set_text("Only the head can void a bill.")
            return
        count, message = books.void(number)
        self.catalogue = books.read_catalogue()
        self.by_id = {r["id"]: r for r in self.catalogue}
        self.status.set_text(message)
        self.show_bills()
        self.show_results()
        if count:
            invoice.write(number, books.bill_rows(number))

    def returns_for(self, number):
        """One dialog, one item, one quantity. Returns are rare and fiddly;
        a wrong one is a cash refund that never happened."""
        rows = [r for r in books.bill_rows(number) if r.get("kind") == "sale"]
        if not rows:
            self.status.set_text(f"Nothing on {number} to return.")
            return
        dialog = Gtk.Dialog(title=f"Return from {number}", transient_for=self,
                            modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                           "Take it back", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        picker = Gtk.ComboBoxText()
        for r in rows:
            picker.append(r["id"], f"{r['name']} ({books.number(r['qty']):.0f} sold)")
        picker.set_active(0)
        picker.get_accessible().set_name("Item to return")
        box.add(picker)
        qty = Gtk.SpinButton.new_with_range(1, 999, 1)
        qty.get_accessible().set_name("How many")
        box.add(qty)
        box.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            count, message = books.take_back(number, picker.get_active_id(),
                                             qty.get_value_as_int())
            self.catalogue = books.read_catalogue()
            self.by_id = {r["id"]: r for r in self.catalogue}
            self.status.set_text(message)
            self.show_bills()
            self.show_results()
        dialog.destroy()


if __name__ == "__main__":
    BillingApp().show_all()
    Gtk.main()
