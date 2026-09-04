#!/usr/bin/env python3
"""
CSMA — the credit score maintaining assistant.

Reads the accounts you entered in Banking and tells you what your own numbers
say about the five things a credit score is made of.

── The line this app does not cross ────────────────────────────────────────

It does not predict your score. No formula outside a bureau can, and one that
produced a number here would be believed — which is precisely why it does not
produce one. What it shows is the published breakdown of what goes into a
score, and arithmetic on figures you typed in yourself.

It recommends no product and gives no investment advice. "Your utilisation is
54.9%, and the usual guidance is under 30%" is a division and a public fact.
"Take this loan", "move your savings here", "buy this" are advice, and nothing
in this file is qualified to give it. If you want that, the right answer is a
person who is licensed to, and the app says so rather than improvising.

It is called a maintaining assistant rather than an improving one on purpose.
Maintaining is what the five factors actually reward: paying on time, every
time, and not letting a balance drift up. That is unglamorous and it is the
whole of it.
"""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk   # noqa: E402

import common          # noqa: E402
import money           # noqa: E402

DISCLAIMER = (
    "This is not a credit score and not a prediction of one. Only a bureau "
    "computes your score, from data this machine has never seen. Everything "
    "below is arithmetic on the figures you entered, plus the published "
    "breakdown of what a score is made of. It is not financial advice."
)


class CreditApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Credit Assistant")
        self.set_default_size(760, 700)
        self.connect("destroy", Gtk.main_quit)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=16)
        self.add(root)

        head = Gtk.Label(xalign=0)
        head.set_markup("<b>Credit assistant</b>")
        root.pack_start(head, False, False, 0)

        self.headline = Gtk.Label(xalign=0)
        root.pack_start(self.headline, False, False, 0)

        # Said once, at the top, in the app's own voice rather than in small
        # print at the bottom that nobody reads.
        small = Gtk.Label(xalign=0, wrap=True)
        small.set_opacity(.62)
        small.set_text(DISCLAIMER)
        root.pack_start(small, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        root.pack_start(scroll, True, True, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        scroll.add(self.body)

        again = Gtk.Button(label="Read my accounts again")
        again.get_accessible().set_name("Read my accounts again")
        again.connect("clicked", lambda _b: self.refresh())
        root.pack_start(again, False, False, 0)

        self.refresh()

    def section(self, title):
        lab = Gtk.Label(xalign=0)
        lab.set_markup(f"<b>{title}</b>")
        self.body.pack_start(lab, False, False, 0)

    def line(self, text, dim=False):
        lab = Gtk.Label(xalign=0, wrap=True)
        lab.set_text(text)
        if dim:
            lab.set_opacity(.7)
        self.body.pack_start(lab, False, False, 0)
        return lab

    def refresh(self):
        for child in self.body.get_children():
            self.body.remove(child)

        use = money.utilisation()
        self.headline.set_markup(
            "Card utilisation: <b>—</b>  (no card recorded)" if use is None
            else f"Card utilisation: <b>{use}%</b>  ·  the usual guidance is under 30%")

        notes = money.standing()
        self.section("What your own numbers say")
        if not notes:
            self.line("Nothing to report. Add your accounts in Banking first.", dim=True)
        for level, text in notes:
            self.line(("!  " if level == "watch" else "·  ") + text)

        self.section("What a score is made of")
        for name, weight, what in money.FACTORS:
            self.line(f"{weight}%   {name} — {what}")

        soon = money.due_soon(14)
        self.section("Falling due in the next fortnight")
        if not soon:
            self.line("Nothing. Payment history is the largest single factor, "
                      "so an empty list here is the good outcome.", dim=True)
        for r in soon:
            when = "today" if r["in_days"] == 0 else f"in {r['in_days']} day(s)"
            self.line(f"·  {r['what']} — ₹{r['amount']:,.2f}, {when}")

        self.section("What this app will not do")
        self.line("Connect to a bank, or ask for a password, a PIN or an OTP. "
                  "There is no field here that would take one, and the sandbox "
                  "has no network to send one over.", dim=True)
        self.line("Tell you what to buy, borrow or invest in. That needs "
                  "somebody licensed to give it, and this is not that.", dim=True)
        self.body.show_all()


if __name__ == "__main__":
    common.SHARED.mkdir(parents=True, exist_ok=True)
    CreditApp().show_all()
    Gtk.main()
