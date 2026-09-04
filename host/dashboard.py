#!/usr/bin/env python3
"""
The overview screen's data, assembled once.

One call rather than eight. The panel already polls ten endpoints every three
seconds and that cost was worth cutting, not repeating — a dashboard that
fired a request per card would have put the count at eighteen.

Only the cards this person's profession actually shows are computed. A
developer's dashboard does not read the shop's books, so it does not pay for
reading them.

Everything here is read-only and derived. Nothing in this file writes.
"""

import csv
import datetime as dt
from collections import defaultdict
from pathlib import Path

import profile          # noqa: E402  — host/ is on sys.path, see serve.py

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "shared"
SALES = SHARED / "billing" / "sales.csv"
CATALOGUE = SHARED / "billing" / "catalogue.csv"


def _num(v, default=0.0):
    try:
        return float(str(v).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def _sales_rows():
    if not SALES.exists():
        return []
    with open(SALES, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _sandbox(name):
    """Import a module written to run INSIDE the sandbox, with its paths
    corrected for out here.

    common.py computes SHARED as ~/shared, which is right in the VM — the
    clone's home is /home/clone and the mount lands there. On the Mac it
    resolves to the calling user's home, which is a different directory that
    may well exist and be empty. Nothing raises; the books simply come back
    with no rows, and a dashboard reports a shop with no stock problems
    because it read the wrong folder.

    So the paths are pinned to this repository's shared/ after import, which
    is the same directory the VM has mounted.
    """
    import sys
    shell = str(ROOT / "vm" / "shell")
    if shell not in sys.path:
        sys.path.insert(0, shell)
    import importlib
    common = importlib.import_module("common")
    common.SHARED = SHARED
    common.BILLING = SHARED / "billing"
    common.CATALOGUE = CATALOGUE
    common.SALES = SALES
    mod = importlib.import_module(name)
    for attr, value in (("SHARED", SHARED), ("BILLING", SHARED / "billing"),
                        ("CATALOGUE", CATALOGUE), ("SALES", SALES),
                        ("MONEY", SHARED / "money"),
                        ("ACCOUNTS", SHARED / "money" / "accounts.csv"),
                        ("COMMITMENTS", SHARED / "money" / "commitments.csv")):
        if hasattr(mod, attr):
            setattr(mod, attr, value)
    return mod


# ─── the cards ──────────────────────────────────────────────────────────────

def card_sales(days=14):
    """Takings per day for the last fortnight — the line in the sketch.

    Days with no trade are included as zero. A chart that silently skips them
    draws a flat line through a closed shop and reads as steady business.
    """
    rows = _sales_rows()
    today = dt.date.today()
    span = [today - dt.timedelta(days=n) for n in range(days - 1, -1, -1)]
    per = defaultdict(float)
    for r in rows:
        at = (r.get("at") or "")[:10]
        try:
            day = dt.date.fromisoformat(at)
        except ValueError:
            continue
        per[day] += _num(r.get("amount"))
    points = [{"day": d.isoformat(), "label": d.strftime("%-d %b"),
               "amount": round(per.get(d, 0.0), 2)} for d in span]
    total = round(sum(p["amount"] for p in points), 2)
    return {"points": points, "total": total, "days": days,
             "today": round(per.get(today, 0.0), 2)}


def card_addons():
    """Add-ons — everything that goes out every month.

    Loans, EMIs, subscriptions, rent. The wireframe calls this the add-ons
    card and notes that it is "all the commitments you have", which is the
    right way round: an add-on is something that attached itself to your
    month and now leaves every month whether you look at it or not.

    Most people can name three of theirs. The total is the number worth
    drawing, and it is almost always larger than the guess.
    """
    money = _sandbox("money")
    rows = money.commitments()
    per = defaultdict(float)
    for r in rows:
        per[(r.get("kind") or "other").strip() or "other"] += money.number(r.get("amount"))
    ranked = sorted(per.items(), key=lambda kv: -kv[1])
    return {
        "slices": [{"name": k, "amount": round(v, 2)} for k, v in ranked],
        "total": money.monthly(rows),
        "count": len(rows),
        "due": money.due_soon(7, rows),
        "position": money.position(),
    }


def card_metrics():
    """The numbers worth a glance, with margin computed rather than guessed.

    Margin is on the sale, not on the cost — profit over revenue. Getting
    that the wrong way round flatters the number by exactly the amount that
    would make it wrong to quote.
    """
    rows = _sales_rows()
    revenue = sum(_num(r.get("amount")) for r in rows)
    profit = sum(_num(r.get("profit")) for r in rows)
    tax = sum(_num(r.get("tax")) for r in rows)
    bills = {r.get("bill") for r in rows if r.get("bill")}
    out = [
        {"label": "Revenue",      "value": round(revenue, 2), "money": True},
        {"label": "Profit",       "value": round(profit, 2),  "money": True},
        {"label": "Margin",       "value": round(profit / revenue * 100, 1)
                                            if revenue else 0.0, "suffix": "%"},
        {"label": "GST collected", "value": round(tax, 2),    "money": True},
        {"label": "Bills",        "value": len(bills)},
    ]
    return {"rows": out}


def card_stock(limit=8):
    """What is running out. books.py owns this question; this asks it."""
    try:
        short = _sandbox("books").running_out()
    except Exception as e:                                   # noqa: BLE001
        return {"rows": [], "error": f"{type(e).__name__}: {e}"}
    return {"rows": short[:limit], "count": len(short)}


def card_commitments():
    """"Shows all the commitments you have" — the arrow in the sketch."""
    try:
        money = _sandbox("money")
        return {"monthly": money.monthly(),
                "position": money.position(),
                "due": money.due_soon(7)}
    except Exception as e:                                   # noqa: BLE001
        return {"monthly": 0, "position": {}, "due": [], "error": str(e)}


def card_credit():
    try:
        money = _sandbox("money")
        return {"utilisation": money.utilisation(),
                "score": money.score_now(),
                "standing": [{"level": l, "text": t} for l, t in money.standing()],
                "factors": [{"name": n, "weight": w, "what": d}
                            for n, w, d in money.FACTORS]}
    except Exception as e:                                   # noqa: BLE001
        return {"utilisation": None, "score": None, "standing": [],
                "factors": [], "error": str(e)}


def card_waiting():
    """Anything that has stopped and is waiting on a person."""
    import tasks
    out = {"tasks": 0, "approvals": 0}
    try:
        out["tasks"] = tasks.summary().get("open", 0)
    except Exception:                                        # noqa: BLE001
        pass
    try:
        import vm as _vm
        out["approvals"] = len(_vm.pending_approvals())
    except Exception:                                        # noqa: BLE001
        pass
    return out


def card_shell():
    """The developer card is the shell itself; it carries no data of its own."""
    return {"hint": "Type a command. It runs inside the sandbox, as the clone, "
                    "which has no sudo and no network."}


BUILDERS = {
    "sales": card_sales, "addons": card_addons, "metrics": card_metrics,
    "stock": card_stock, "commitments": card_commitments,
    "credit": card_credit, "waiting": card_waiting, "shell": card_shell,
}


def everything():
    who = profile.read()
    wanted = profile.cards(who)
    out = {}
    for name in wanted:
        builder = BUILDERS.get(name)
        if not builder:
            continue
        try:
            out[name] = builder()
        except Exception as e:                               # noqa: BLE001
            # One card that cannot be drawn must not take the dashboard with
            # it. It says so in its own space and the rest still paints.
            out[name] = {"error": f"{type(e).__name__}: {e}"}
    return {"profile": who, "greeting": profile.greeting(who),
            "cards": wanted, "titles": profile.CARDS,
            "about": profile.ABOUT, "data": out,
            "professions": sorted(profile.PROFESSIONS)}
