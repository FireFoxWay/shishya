#!/usr/bin/env python3
"""
Who is using this, and what they do for a living.

The dashboard greets by name and shows a different set of cards depending on
the profession — a shopkeeper opens onto takings and stock, someone managing
their own money opens onto what is owed and what falls due, a developer opens
onto a shell. Same system, same data, different first screen.

That is the whole of the personalisation, and it is deliberately this small.
The alternative — inferring what somebody wants from what they do — means
watching them, and a project whose argument is "nothing leaves this laptop"
should not be building a behavioural profile to decide which chart to draw.
A dropdown is not a limitation here. It is the point.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "shared" / ".profile.json"

# Every card the dashboard knows how to draw. The dashboard asks for these by
# name, so a profession is nothing more than an ordered list of them.
CARDS = {
    "sales":       "Sales",
    "addons":      "Add-ons",
    "metrics":     "Top metrics",
    "stock":       "Running out",
    "credit":      "Credit standing",
    "waiting":     "Waiting on you",
}

# What each card is for, shown on the onboarding screen so somebody choosing a
# profession can see what they are choosing before they choose it.
ABOUT = {
    "sales":   "What you took, day by day",
    "addons":  "Everything that goes out every month — loans, EMIs, "
               "subscriptions, rent",
    "metrics": "Revenue, profit, margin, tax, bills",
    "stock":   "What is at or below its reorder point",
    "credit":  "The five things a credit score is made of, against your own "
               "numbers",
    "waiting": "Anything stopped and waiting on a person",
}

# The professions from the wireframe. The ordering of each list is the order
# the cards appear in, and it matters: the first card is what somebody sees
# before they have decided to look at anything.
PROFESSIONS = {
    "retail owner": ["sales", "metrics", "addons", "stock", "waiting"],
    "manufacturer": ["sales", "stock", "metrics", "addons", "waiting"],
    "freelancer":   ["addons", "sales", "credit", "metrics", "waiting"],
    "salaried":     ["addons", "credit", "metrics", "waiting"],
    "student":      ["addons", "credit", "waiting"],
    "other":        ["metrics", "addons", "waiting"],
}

DEFAULT = {"name": "", "profession": "retail owner", "onboarded": False}


def read():
    try:
        return {**DEFAULT, **json.loads(STORE.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULT)


def write(name=None, profession=None):
    """Set either or both. Refuses a profession it has no cards for, rather
    than saving it and drawing an empty dashboard."""
    now = read()
    if name is not None:
        now["name"] = str(name).strip()[:60]
    if "onboarded" in now and profession is not None:
        now["onboarded"] = True
    if profession is not None:
        profession = str(profession).strip().lower()
        if profession not in PROFESSIONS:
            raise ValueError(f"no such profession {profession!r} — "
                             f"one of {', '.join(sorted(PROFESSIONS))}")
        now["profession"] = profession
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(now, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STORE)
    return now


def cards(profile=None):
    """The cards this person's dashboard shows, in order."""
    profile = profile or read()
    return PROFESSIONS.get(profile.get("profession"), PROFESSIONS["other"])


def greeting(profile=None):
    profile = profile or read()
    name = (profile.get("name") or "").strip()
    return f"Welcome {name}," if name else "Welcome,"
