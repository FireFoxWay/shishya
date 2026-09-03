#!/usr/bin/env python3
"""
Bring existing books up to the current schema. Runs INSIDE the sandbox, once.

Adds the columns GST, returns, voids and customers need, to files written
before those existed. Every original file is copied aside first: these are a
shop's takings, and a migration that goes wrong must be answerable with "the
old one is right there" rather than an apology.

Idempotent. Running it twice changes nothing the second time.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, "/opt/shishya/vm/shell")
import books   # noqa: E402


def keep_a_copy(path):
    if path.exists():
        spare = path.with_suffix(path.suffix + ".before-gst")
        if not spare.exists():
            shutil.copy2(path, spare)
            print(f"  kept {spare.name}")


def main():
    if not books.CATALOGUE.exists():
        print("no books yet — nothing to migrate")
        return

    keep_a_copy(books.CATALOGUE)
    keep_a_copy(books.SALES)

    catalogue = books._rows(books.CATALOGUE)
    added = 0
    for row in catalogue:
        if not row.get("gst"):
            row["gst"] = books.DEFAULT_GST
            added += 1
    books.write_catalogue(catalogue)
    print(f"catalogue: {len(catalogue)} products, {added} given the default "
          f"{books.DEFAULT_GST}% rate")

    sales = books._rows(books.SALES)
    for row in sales:
        row.setdefault("kind", "sale")
        row["kind"] = row.get("kind") or "sale"
        row.setdefault("customer", "")
        row.setdefault("gst", books.DEFAULT_GST)
        if not row.get("gst"):
            row["gst"] = books.DEFAULT_GST
        # Tax is computed from what was actually charged, not invented: the
        # price on the row is the price the customer paid, and the GST inside
        # it is arithmetic, not a guess about a past transaction.
        if not row.get("tax"):
            row["tax"] = f"{books.tax_within(row.get('price'), row['gst']) * books.number(row.get('qty')):.2f}"
    if sales:
        books._write(books.SALES, books.SALES_COLUMNS, sales)
    print(f"sales: {len(sales)} line(s) carried over, totals unchanged")

    if not books.CUSTOMERS.exists():
        books.write_customers([])
        print("customers: started empty")


if __name__ == "__main__":
    main()
