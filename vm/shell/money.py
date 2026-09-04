#!/usr/bin/env python3
"""
Money — accounts, what is owed, and what a credit score is made of.

Pure Python. No GTK, no VM, no network: it runs on Windows as readily as it
runs in the sandbox, which is deliberate — this is the part a second developer
can pick up without a Lima machine.

Two things this deliberately does NOT do, and will not be extended to do:

  * It never connects to a bank and never asks for a credential. Not because
    it would be hard, but because "an AI on your laptop that holds your net
    banking password" is a sentence that should stop a room. Everything here
    is typed in by the person or read from a statement they exported
    themselves. That is also what makes it demonstrable: there is no live
    account to go wrong in front of an audience.

  * It gives no investment advice and recommends no product. What it does is
    arithmetic on your own numbers, plus the published, general rules of how
    a credit score is put together. "Your utilisation is 74%, and under 30%
    is the usual guidance" is arithmetic and a public fact. "Move your money
    here" is advice, and nothing in this file is qualified to give it.

The store is one CSV per thing, in the same append-only style as the shop's
books, because the same argument applies: a row that was written is a row you
can still read after the program that wrote it is gone.
"""

import csv
import datetime as dt
from pathlib import Path

import common

MONEY = common.SHARED / "money"
ACCOUNTS = MONEY / "accounts.csv"
COMMITMENTS = MONEY / "commitments.csv"
SCORES = MONEY / "scores.csv"

ACCOUNT_COLUMNS = ["id", "name", "kind", "balance", "limit", "note"]
# kind: current | savings | card | loan | cash
COMMITMENT_COLUMNS = ["id", "what", "kind", "amount", "day", "account", "note"]
SCORE_COLUMNS = ["at", "score", "bureau", "note"]
# kind: emi | bill | rent | insurance | subscription | other
# day:  day of the month it falls due, 1-31


def _rows(path, columns):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return [{c: r.get(c, "") for c in columns} for r in csv.DictReader(fh)]


def _write(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})
    tmp.replace(path)                 # whole file, renamed — never half of one


def number(value, default=0.0):
    try:
        return float(str(value).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def accounts():
    return _rows(ACCOUNTS, ACCOUNT_COLUMNS)


def save_accounts(rows):
    _write(ACCOUNTS, ACCOUNT_COLUMNS, rows)


def commitments():
    return _rows(COMMITMENTS, COMMITMENT_COLUMNS)


def save_commitments(rows):
    _write(COMMITMENTS, COMMITMENT_COLUMNS, rows)


# ─── what you are actually holding ──────────────────────────────────────────

def position(rows=None):
    """Cash on one side, what is owed on the other.

    A card balance and a loan balance are debts and count against you; a
    current account counts for you. Storing both as a positive number and
    deciding the sign here means a row is never ambiguous about what it meant.
    """
    rows = accounts() if rows is None else rows
    have = owe = 0.0
    for r in rows:
        amount = number(r.get("balance"))
        if r.get("kind") in ("card", "loan"):
            owe += amount
        else:
            have += amount
    return {"have": round(have, 2), "owe": round(owe, 2),
            "net": round(have - owe, 2)}


def monthly(rows=None):
    """Everything that leaves the account every month, whether you look or not.

    This is the number the sketch calls "all the commitments you have". Most
    people can name three of them and are surprised by the total.
    """
    rows = commitments() if rows is None else rows
    return round(sum(number(r.get("amount")) for r in rows), 2)


def due_soon(within=7, rows=None, today=None):
    """What falls due in the next few days, soonest first.

    Days-of-month, not dates: a rent that falls on the 5th falls on the 5th
    of whatever month it is. Rolling into next month is the case that gets
    forgotten — on the 28th, the 2nd is four days away, not minus twenty-six.
    """
    rows = commitments() if rows is None else rows
    today = today or dt.date.today()
    out = []
    for r in rows:
        day = int(number(r.get("day"), 0))
        if not 1 <= day <= 31:
            continue
        days = day - today.day
        if days < 0:
            # Next month. Ask that month how long it is rather than assuming.
            nxt = (today.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
            length = (nxt.replace(day=28) + dt.timedelta(days=4))
            length = (length - dt.timedelta(days=length.day)).day
            days = (length - today.day) + day
        if days <= within:
            out.append({**r, "in_days": days, "amount": number(r.get("amount"))})
    out.sort(key=lambda r: r["in_days"])
    return out


# ─── the score itself, which we do not compute ──────────────────────────────
# The wireframe puts a number in a gauge — 742, "+12 this month" — and that
# number is worth having on screen. What it must not be is a number this
# program made up.
#
# No formula outside a bureau produces somebody's score, and one invented here
# would be believed precisely because it appeared next to real arithmetic. So
# this is a log rather than a model: you type in what your bureau actually
# told you, and the app keeps the history and does the subtraction. The gauge
# is then true by construction, and "+12 this month" is a fact about two
# readings rather than a claim about your creditworthiness.


def scores():
    rows = _rows(SCORES, SCORE_COLUMNS)
    rows.sort(key=lambda r: r.get("at", ""))
    return rows


def record_score(score, bureau="", note=""):
    """Write down what a bureau told you, dated today."""
    score = int(number(score))
    if not 300 <= score <= 900:
        raise ValueError("a bureau score is between 300 and 900")
    rows = scores()
    rows.append({"at": dt.date.today().isoformat(), "score": str(score),
                 "bureau": bureau, "note": note})
    _write(SCORES, SCORE_COLUMNS, rows)
    return rows[-1]


def score_now():
    """The latest reading and how far it has moved since the one before.

    Returns None when nothing has been recorded — which is the honest state
    for a machine that has never been told, and is drawn as an empty gauge
    rather than as a zero.
    """
    rows = scores()
    if not rows:
        return None
    latest = rows[-1]
    out = {"score": int(number(latest.get("score"))),
           "at": latest.get("at", ""), "bureau": latest.get("bureau", ""),
           "change": None, "since": None}
    if len(rows) > 1:
        prev = rows[-2]
        out["change"] = out["score"] - int(number(prev.get("score")))
        out["since"] = prev.get("at", "")
    return out


# ─── what a credit score is made of ─────────────────────────────────────────
# The weights below are the published, widely-reproduced breakdown used by the
# major bureaus. They are here as a checklist of what to look at, not as a
# model that predicts anybody's score — no formula outside a bureau does, and
# this one does not claim to.

FACTORS = [
    ("payment history",  35, "Whether you have paid on time. The largest single "
                             "piece, and the one a missed payment damages most."),
    ("amounts owed",     30, "How much of your available credit you are using. "
                             "Usually quoted as: keep it under 30%."),
    ("length of history", 15, "How long your accounts have been open. Closing an "
                              "old card shortens this."),
    ("new credit",       10, "Recent applications. Several in a short span reads "
                             "as looking for money."),
    ("credit mix",       10, "A spread of kinds — a card, a loan — rather than "
                             "one of everything."),
]


def utilisation(rows=None):
    """How much of your card limit you are using, as a percentage.

    The one number in this file worth putting on a dashboard: it is the second
    largest factor, it moves month to month, and unlike the others you can
    change it this afternoon by paying a card down.
    """
    rows = accounts() if rows is None else rows
    used = limit = 0.0
    for r in rows:
        if r.get("kind") != "card":
            continue
        used += number(r.get("balance"))
        limit += number(r.get("limit"))
    if limit <= 0:
        return None                        # no cards, so the number is not 0
    return round(used / limit * 100, 1)


def standing(rows=None):
    """Plain observations about your own numbers. Not a score, and not advice.

    Every line is either arithmetic on figures the person typed in, or a
    published general rule. Nothing here recommends a product, and nothing
    here knows anything about the person it could not read off the page.
    """
    rows = accounts() if rows is None else rows
    notes = []
    use = utilisation(rows)
    if use is None:
        notes.append(("info", "No card recorded, so there is no utilisation to "
                              "report. Add one to see it."))
    elif use >= 30:
        notes.append(("watch", f"Card utilisation is {use}%. The usual guidance "
                               f"is to keep it under 30% — this is the fastest "
                               f"of the five factors to move."))
    else:
        notes.append(("ok", f"Card utilisation is {use}%, inside the under-30% "
                            f"guidance."))

    cards = [r for r in rows if r.get("kind") == "card"]
    for r in cards:
        limit = number(r.get("limit"))
        if limit and number(r.get("balance")) / limit >= 0.9:
            notes.append(("watch", f"{r.get('name') or 'A card'} is at 90% or "
                                   f"more of its own limit. A single card near "
                                   f"its ceiling shows even when the total does "
                                   f"not."))

    kinds = {r.get("kind") for r in rows}
    if len(kinds & {"card", "loan"}) < 2:
        notes.append(("info", "Only one kind of credit is recorded. Mix is 10% "
                              "of the picture — worth knowing, not worth "
                              "borrowing for."))

    soon = due_soon(3)
    if soon:
        notes.append(("watch", f"{len(soon)} payment(s) due within three days. "
                               f"Payment history is the largest factor there "
                               f"is, and it is the one that is purely a matter "
                               f"of not forgetting."))
    return notes


if __name__ == "__main__":
    import json
    print(json.dumps({"position": position(), "monthly": monthly(),
                      "utilisation": utilisation(),
                      "due_soon": due_soon(),
                      "standing": standing()}, indent=2, default=str))
