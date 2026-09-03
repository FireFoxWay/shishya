#!/usr/bin/env python3
"""
Shishya — copy the shop's books somewhere safe. Runs INSIDE the sandbox.

    python3 backup.py /home/clone/shared/jobs/<stamp>

The books are the one thing here that cannot be regenerated. Training
material can be dropped in again, a report can be re-run, the sandbox itself
is one rollback from clean — but a month of takings exists in exactly one
file, and "roll back" would destroy it as thoroughly as any accident.

So: a dated copy into Work/Backups, which is on the mounted share and
therefore already on the Mac, plus a plain-text summary of what was in it. A
backup nobody can read without the software that wrote it is a hostage, not
a backup.

Deliberately not clever. No incremental anything, no compression: at a few
hundred kilobytes a day, a copy you can open in any spreadsheet beats a
format that needs this program back to restore it.
"""

import csv
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/shishya/vm/shell")
import books      # noqa: E402
import common     # noqa: E402

BACKUPS = common.WORK / "Backups"
KEEP = 30          # a month of dailies; older ones are pruned


def put_status(job, **fields):
    fields.setdefault("t", round(time.time(), 1))
    tmp = job / ".status.tmp"
    tmp.write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")
    tmp.replace(job / "status.json")


def summarise(where):
    sales = books.read_sales()
    catalogue = books.read_catalogue()
    takings = sum(books.number(r.get("amount")) for r in sales)
    tax = sum(books.number(r.get("tax")) for r in sales)
    stock = sum(books.number(r.get("stock")) * books.number(r.get("cost"))
                for r in catalogue)
    voided = len({r["bill"] for r in sales if r.get("kind") == "void"})
    text = (f"Shishya books — copied {time.strftime('%d %b %Y, %H:%M')}\n"
            f"{'=' * 52}\n\n"
            f"  products stocked      {len(catalogue):,}\n"
            f"  stock value at cost   ₹{books.money(stock)}\n"
            f"  sale lines recorded   {len(sales):,}\n"
            f"  bills voided          {voided}\n"
            f"  takings, all time     ₹{books.money(takings)}\n"
            f"  of which GST          ₹{books.money(tax)}\n\n"
            f"These are plain CSV. Open catalogue.csv or sales.csv in any\n"
            f"spreadsheet — you do not need Shishya to read them back.\n")
    (where / "what-is-in-here.txt").write_text(text, encoding="utf-8")
    return text


def prune():
    """Keep the last KEEP, oldest first out. Said out loud in the summary so
    a missing backup is never a surprise."""
    if not BACKUPS.exists():
        return 0
    dated = sorted((d for d in BACKUPS.iterdir() if d.is_dir()),
                   key=lambda d: d.name)
    dropped = 0
    for old in dated[:-KEEP]:
        shutil.rmtree(old, ignore_errors=True)
        dropped += 1
    return dropped


def main(job_dir):
    job = Path(job_dir)
    out = job / "out"
    out.mkdir(parents=True, exist_ok=True)
    common.set_state("working")
    put_status(job, state="working", step="copying the books")

    if not books.CATALOGUE.exists():
        put_status(job, state="failed",
                   step="there are no books yet — open the Billing app once")
        common.set_state("idle")
        return

    where = BACKUPS / time.strftime("%Y-%m-%d-%H%M")
    where.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in ("catalogue.csv", "sales.csv", "customers.csv", "shop.txt"):
        source = common.BILLING / name
        if source.exists():
            shutil.copy2(source, where / name)
            copied.append(name)

    summary = summarise(where)
    dropped = prune()

    # A copy of the summary comes back with the job so the panel can show
    # what was saved without anybody opening a folder.
    (out / "backup-summary.txt").write_text(
        summary + (f"\nPruned {dropped} backup(s) older than the last {KEEP}.\n"
                   if dropped else ""), encoding="utf-8")

    put_status(job, state="done",
               files=["backup-summary.txt"], empty=[],
               said=f"{len(copied)} file(s) copied to Work/Backups/{where.name}"
                    + (f"; {dropped} old backup(s) pruned" if dropped else "")
                    + "\n\n" + summary,
               step=f"done — books copied to Work/Backups/{where.name}")
    common.set_state("idle")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: backup.py <job-dir>")
    try:
        main(sys.argv[1])
    except Exception as e:
        try:
            put_status(Path(sys.argv[1]), state="failed",
                       step=f"the backup itself failed: {type(e).__name__}: {e}")
        finally:
            common.set_state("idle")
        raise
