#!/usr/bin/env python3
"""
Shishya — what the shop should know without being asked. Runs INSIDE the sandbox.

    python3 alerts.py /home/clone/shared/jobs/<stamp>

Findings and the audit answer when you go and look. This is the other
direction: it decides there is something you would want to be told, and puts
it where you will see it whether or not you thought to ask.

Written to shared/.alerts.json, which the panel reads on its ordinary poll.
Nothing here pushes, pops up or interrupts — the clone's screen is watched by
somebody who may be mid-sentence in front of an audience, and a notification
that steals attention is a notification that gets switched off.

── The rule that keeps it worth reading ───────────────────────────────────

At most five, ranked by what it costs the shop to ignore, and each one has
to name a thing somebody can do today. Findings learned this the hard way:
its first run reported 8,254 outliers and told the reader nothing at all. An
alert list nobody reads is worse than none, because it looks like coverage.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/shishya/vm/shell")
import books      # noqa: E402
import common     # noqa: E402

ALERTS = common.SHARED / ".alerts.json"
MOST = 5


def put_status(job, **fields):
    fields.setdefault("t", round(time.time(), 1))
    tmp = job / ".status.tmp"
    tmp.write_text(json.dumps(fields, ensure_ascii=False))
    tmp.replace(job / "status.json")


def look():
    """Everything worth saying, most costly first."""
    found = []
    catalogue = books.read_catalogue()
    sales = books.read_sales()
    short = books.running_out(catalogue)

    out_of = [s for s in short if s["stock"] <= 0]
    if out_of:
        # Out of stock is the expensive one: it is not a warning about the
        # future, it is sales not happening now.
        worst = ", ".join(s["name"] for s in out_of[:3])
        found.append({
            "weight": 100 + len(out_of),
            "what": f"{len(out_of)} product(s) are out of stock",
            "do": f"Order {worst}" + (" and others" if len(out_of) > 3 else ""),
        })

    low = [s for s in short if s["stock"] > 0]
    if low:
        cost = sum(max(s["reorder"] * 2 - s["stock"], 0) * s["cost"] for s in low)
        found.append({
            "weight": 50 + min(len(low), 40),
            "what": f"{len(low)} product(s) are at or below their reorder point",
            "do": f"About ₹{books.money(cost)} to refill them all",
        })

    # Nothing sold today, during shop hours, is either a closed day or a
    # counter nobody is using. Both are worth a line; neither is an error.
    today = time.strftime("%Y-%m-%d")
    todays = [r for r in sales if (r.get("at") or "").startswith(today)]
    if not todays and time.localtime().tm_hour >= 12:
        found.append({
            "weight": 40,
            "what": "Nothing has been billed today",
            "do": "If the shop is open, check the counter is being used",
        })

    voided = {r["bill"] for r in sales if r.get("kind") == "void"
              and (r.get("at") or "").startswith(today)}
    if len(voided) >= 3:
        found.append({
            "weight": 60,
            "what": f"{len(voided)} bills were voided today",
            "do": "Worth asking why — voids cancel takings already counted",
        })

    if not books.CUSTOMERS.exists() or not books.read_customers():
        pass          # not worth a line; an empty customer book is normal
    else:
        owing = [c for c in books.read_customers()
                 if books.number(c.get("balance")) > 0]
        if owing:
            total = sum(books.number(c["balance"]) for c in owing)
            found.append({
                "weight": 30,
                "what": f"{len(owing)} customer(s) owe ₹{books.money(total)}",
                "do": "Khata balances outstanding",
            })

    backups = common.WORK / "Backups"
    fresh = sorted(backups.glob("*")) if backups.exists() else []
    if not fresh:
        found.append({
            "weight": 70,
            "what": "The books have never been backed up",
            "do": "Schedule a backup in the Reports app",
        })

    found.sort(key=lambda a: -a["weight"])
    return found[:MOST]


def main(job_dir):
    job = Path(job_dir)
    out = job / "out"
    out.mkdir(parents=True, exist_ok=True)
    common.set_state("working")
    put_status(job, state="working", step="looking for anything worth saying")

    if not books.CATALOGUE.exists():
        put_status(job, state="failed",
                   step="there are no books yet — open the Billing app once")
        common.set_state("idle")
        return

    found = look()
    ALERTS.parent.mkdir(parents=True, exist_ok=True)
    tmp = ALERTS.with_suffix(".tmp")
    tmp.write_text(json.dumps({"at": time.time(), "alerts": found},
                              ensure_ascii=False, indent=2))
    tmp.replace(ALERTS)

    said = ("\n".join(f"• {a['what']} — {a['do']}" for a in found)
            or "Nothing needs attention.")
    (out / "alerts.txt").write_text(said)
    put_status(job, state="done", files=["alerts.txt"], empty=[], said=said,
               step=f"done — {len(found)} thing(s) worth knowing")
    common.set_state("idle")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: alerts.py <job-dir>")
    try:
        main(sys.argv[1])
    except Exception as e:
        try:
            put_status(Path(sys.argv[1]), state="failed",
                       step=f"the alert check itself failed: {type(e).__name__}: {e}")
        finally:
            common.set_state("idle")
        raise
