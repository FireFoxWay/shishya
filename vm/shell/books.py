#!/usr/bin/env python3
"""
The shop's books — one module that knows the schema.

The Billing app writes them, the audit reads them, Tally exports them and a
job may ask anything of them. Four programs agreeing on what a column means
by each parsing the CSV themselves is how a column quietly means two things,
so the parsing lives here and nowhere else.

── What a row means ────────────────────────────────────────────────────────

Sales are append-only, and every correction is a new row rather than an edit.
`kind` says which:

    sale     goods out, money in.  qty positive.
    return   goods back, money out. qty negative, and it names the bill it
             returns against so the two can always be paired.
    void     the whole bill was wrong. One reversing row per original row,
             qty negated, referencing the bill it cancels.

Nothing is ever deleted or rewritten. A day's takings are the sum of the
rows for that day, and that sum is correct whether or not anything was
voided — which is the only property that makes a till roll worth keeping.

── GST ─────────────────────────────────────────────────────────────────────

Indian retail prices are quoted inclusive of GST, so `price` is what the
customer pays and the tax inside it is `price × rate / (100 + rate)`. Storing
it the other way round — price plus tax — makes every shelf label wrong. The
rate is per product, because a shop sells things at 0%, 5%, 12% and 18% on
the same bill and one blended rate on the total is not a legal invoice.
"""

import csv
import re
import time
from pathlib import Path

import common

CATALOGUE = common.CATALOGUE
SALES = common.SALES
CUSTOMERS = common.BILLING / "customers.csv"

CATALOGUE_COLUMNS = ["id", "name", "category", "cost", "price", "stock",
                     "reorder", "gst"]
SALES_COLUMNS = ["at", "bill", "kind", "customer", "id", "name", "category",
                 "qty", "price", "cost", "gst", "tax", "amount", "profit"]
CUSTOMER_COLUMNS = ["name", "phone", "balance"]

# What a shop actually sells at. Staples are exempt, most goods are 18%, and
# a wrong rate on an invoice is a compliance problem rather than a rounding
# one — so it is per product and never guessed at bill time.
GST_RATES = ["0", "5", "12", "18", "28"]
DEFAULT_GST = "18"


def money(value):
    return f"{float(value):,.2f}"


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def tax_within(price, rate):
    """The GST already inside a tax-inclusive price."""
    rate = number(rate)
    return number(price) * rate / (100 + rate) if rate else 0.0


# ─── reading and writing ────────────────────────────────────────────────────

def _rows(path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _write(path, columns, rows):
    """Whole file, renamed into place. The audit reads these while the
    counter is open and must never see half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def _append(path, columns, rows):
    fresh = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, columns, extrasaction="ignore")
        if fresh:
            writer.writeheader()
        writer.writerows(rows)


def read_catalogue():
    rows = _rows(CATALOGUE)
    # Older books predate GST. Fill the default rather than fail: a shop that
    # upgrades mid-week should not lose its catalogue.
    for r in rows:
        r.setdefault("gst", DEFAULT_GST)
        if not r.get("gst"):
            r["gst"] = DEFAULT_GST
    return rows


def write_catalogue(rows):
    _write(CATALOGUE, CATALOGUE_COLUMNS, rows)


def read_sales():
    rows = _rows(SALES)
    for r in rows:
        r.setdefault("kind", "sale")          # everything before kind existed
        if not r.get("kind"):
            r["kind"] = "sale"
        r.setdefault("customer", "")
    return rows


def read_customers():
    return _rows(CUSTOMERS)


def write_customers(rows):
    _write(CUSTOMERS, CUSTOMER_COLUMNS, rows)


# ─── recording ──────────────────────────────────────────────────────────────

def new_bill_number():
    return time.strftime("B%Y%m%d-%H%M%S")


def line(bill, kind, item, qty, customer=""):
    """One row of a bill, priced and taxed at the moment it is recorded.

    Cost and GST are carried on the row deliberately. Both change; a bill is
    what it was on the day, and recomputing a month's margin or its tax from
    today's catalogue is how the figures quietly become fiction.
    """
    price, cost = number(item["price"]), number(item["cost"])
    rate = item.get("gst") or DEFAULT_GST
    return {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "bill": bill, "kind": kind, "customer": customer,
        "id": item["id"], "name": item["name"], "category": item.get("category", ""),
        "qty": qty,
        "price": f"{price:.2f}", "cost": f"{cost:.2f}", "gst": rate,
        "tax": f"{tax_within(price, rate) * qty:.2f}",
        "amount": f"{price * qty:.2f}",
        "profit": f"{(price - cost) * qty:.2f}",
    }


def record(rows):
    _append(SALES, SALES_COLUMNS, rows)


def bill_rows(bill):
    """Every row ever written against one bill number, in order."""
    return [r for r in read_sales() if r.get("bill") == bill]


def is_voided(bill, rows=None):
    return any(r.get("kind") == "void" for r in (rows or bill_rows(bill)))


def bills(limit=40):
    """Recent bills, newest first, with what each is now worth.

    A voided bill still appears — with a total of zero and marked as void.
    Hiding it would make the till roll disagree with itself, and the whole
    point of never deleting a row is that somebody can see what happened.
    """
    seen = {}
    for r in read_sales():
        b = r.get("bill")
        if not b:
            continue
        entry = seen.setdefault(b, {"bill": b, "at": r.get("at", ""),
                                    "customer": r.get("customer", ""),
                                    "total": 0.0, "tax": 0.0, "void": False,
                                    "items": 0})
        entry["total"] += number(r.get("amount"))
        entry["tax"] += number(r.get("tax"))
        if r.get("kind") == "void":
            entry["void"] = True
        elif r.get("kind") == "sale":
            entry["items"] += 1
        if r.get("customer"):
            entry["customer"] = r["customer"]
    out = sorted(seen.values(), key=lambda e: e["at"], reverse=True)
    return out[:limit]


def void(bill):
    """Cancel a bill by reversing it, and put the stock back.

    Returns (rows_written, message). Refuses twice, because a bill voided
    twice would credit the customer twice and the second reversal would look
    exactly as legitimate as the first in the ledger.
    """
    rows = bill_rows(bill)
    if not rows:
        return 0, f"no bill numbered {bill}"
    if is_voided(bill, rows):
        return 0, f"{bill} was already voided"
    sales = [r for r in rows if r.get("kind") == "sale"]
    if not sales:
        return 0, f"{bill} has nothing to void"

    # Only what is still outstanding. Part of this bill may already have come
    # back as a return, and reversing the original quantity on top of that
    # refunds the customer twice and puts more stock on the shelf than ever
    # left it. Caught by voiding a bill that had had one of two returned:
    # the bill settled at minus its own value.
    returned = {}
    for r in rows:
        if r.get("kind") == "return":
            returned[r.get("id")] = returned.get(r.get("id"), 0.0) - number(r.get("qty"))

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    reversal = []
    for r in sales:
        pid = r.get("id")
        outstanding = number(r.get("qty")) - returned.get(pid, 0.0)
        if outstanding <= 0:
            returned[pid] = returned.get(pid, 0.0) - number(r.get("qty"))
            continue          # already fully returned; nothing left to reverse
        returned[pid] = 0.0
        share = outstanding / number(r.get("qty"), 1) if number(r.get("qty")) else 0
        back = dict(r)
        back.update({
            "at": stamp, "kind": "void",
            "qty": -outstanding,
            "tax": f"{-number(r.get('tax')) * share:.2f}",
            "amount": f"{-number(r.get('amount')) * share:.2f}",
            "profit": f"{-number(r.get('profit')) * share:.2f}",
        })
        reversal.append(back)

    if not reversal:
        return 0, f"{bill} has already been fully returned — nothing left to void"
    record(reversal)

    catalogue = read_catalogue()
    by_id = {c["id"]: c for c in catalogue}
    for r in reversal:
        item = by_id.get(r.get("id"))
        if item:
            item["stock"] = str(int(number(item["stock"]) - number(r.get("qty"))))
    write_catalogue(catalogue)
    return len(reversal), f"{bill} voided — {len(reversal)} line(s) reversed, stock returned"


def take_back(bill, product_id, qty):
    """A return: some of a bill comes back. Negative quantity, referencing
    the bill it came from, so the pair can always be found."""
    rows = [r for r in bill_rows(bill)
            if r.get("kind") == "sale" and r.get("id") == product_id]
    if not rows:
        return 0, f"{product_id} was not on {bill}"
    sold = sum(number(r.get("qty")) for r in rows)
    already = sum(-number(r.get("qty")) for r in bill_rows(bill)
                  if r.get("kind") in ("return", "void") and r.get("id") == product_id)
    if qty > sold - already:
        return 0, f"only {sold - already:.0f} of that left to return on {bill}"

    original = rows[0]
    back = dict(original)
    back.update({
        "at": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": "return", "qty": -qty,
        "tax": f"{-tax_within(original['price'], original.get('gst')) * qty:.2f}",
        "amount": f"{-number(original['price']) * qty:.2f}",
        "profit": f"{-(number(original['price']) - number(original['cost'])) * qty:.2f}",
    })
    record([back])

    catalogue = read_catalogue()
    for item in catalogue:
        if item["id"] == product_id:
            item["stock"] = str(int(number(item["stock"]) + qty))
            break
    write_catalogue(catalogue)
    return 1, f"{qty:.0f} × {original['name']} returned against {bill}"


# ─── customers ──────────────────────────────────────────────────────────────

def find_customer(name):
    for c in read_customers():
        if c["name"].strip().lower() == (name or "").strip().lower():
            return c
    return None


def remember_customer(name, phone=""):
    """Add a customer if new, and hand back the record either way."""
    name = re.sub(r"\s+", " ", name or "").strip()
    if not name:
        return None
    rows = read_customers()
    for c in rows:
        if c["name"].strip().lower() == name.lower():
            if phone and not c.get("phone"):
                c["phone"] = phone
                write_customers(rows)
            return c
    fresh = {"name": name, "phone": phone, "balance": "0.00"}
    rows.append(fresh)
    write_customers(rows)
    return fresh


def owe(name, amount):
    """Put an amount on a customer's khata, or take it off. The balance is
    what they owe the shop; a payment is a negative amount."""
    rows = read_customers()
    for c in rows:
        if c["name"].strip().lower() == (name or "").strip().lower():
            c["balance"] = f"{number(c.get('balance')) + amount:.2f}"
            write_customers(rows)
            return number(c["balance"])
    return None


# ─── stock ──────────────────────────────────────────────────────────────────

def running_out(catalogue=None):
    """At or below the reorder point, worst first. Out of stock counts worst."""
    short = []
    for r in (catalogue if catalogue is not None else read_catalogue()):
        stock, point = number(r.get("stock")), number(r.get("reorder"))
        if point <= 0 and stock > 0:
            continue
        if stock <= point:
            short.append({"name": r.get("name", "?"), "id": r.get("id", ""),
                          "stock": stock, "reorder": point,
                          "cost": number(r.get("cost")),
                          "short": stock - point})
    short.sort(key=lambda r: r["short"])
    return short
