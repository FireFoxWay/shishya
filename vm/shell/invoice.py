#!/usr/bin/env python3
"""
A bill somebody can hand over. Runs INSIDE the sandbox.

There is no printer here and there will not be one in a demonstration, so
"print" means producing the document a printer would put on paper: a tax
invoice, saved as HTML in Work/Bills, which opens and prints from any
browser. A shop that cannot hand the customer a bill is not running.

Laid out as an Indian retail tax invoice: the seller, the bill number and
date, the line items with their rate, and — the part that makes it an
invoice rather than a receipt — the tax broken out by GST rate. A bill with
one blended tax figure is not something an accountant can work from.
"""

import html
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/opt/shishya/vm/shell")
import books      # noqa: E402
import common     # noqa: E402

BILLS = common.WORK / "Bills"

# Edited by the shop. Kept beside the books rather than in code, because the
# one thing every shop changes first is its own name.
SHOP = common.BILLING / "shop.txt"
DEFAULT_SHOP = "YOUR SHOP NAME\nStreet address, City\nGSTIN: not set"


def shop_details():
    try:
        text = SHOP.read_text(encoding="utf-8").strip()
        if text:
            return text
    except OSError:
        pass
    try:
        SHOP.parent.mkdir(parents=True, exist_ok=True)
        SHOP.write_text(DEFAULT_SHOP, encoding="utf-8")
    except OSError:
        pass
    return DEFAULT_SHOP


CSS = """
body{font-family:-apple-system,'Segoe UI',sans-serif;max-width:720px;margin:0 auto;
padding:26px;color:#111}
h1{font-size:19px;margin:0 0 2px;letter-spacing:.04em}
.shop{white-space:pre-line;font-size:12px;color:#555;margin-bottom:14px}
.meta{display:flex;justify-content:space-between;font-size:12px;
border-top:2px solid #111;border-bottom:1px solid #ccc;padding:8px 0;margin-bottom:12px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.08em;
color:#666;border-bottom:1px solid #999;padding:5px 6px}
td{padding:5px 6px;border-bottom:1px solid #eee}
.n{text-align:right;font-variant-numeric:tabular-nums}
tfoot td{border:none;padding-top:7px}
tfoot .grand{font-weight:700;font-size:15px;border-top:2px solid #111}
.tax{margin-top:16px;font-size:11.5px;color:#444}
.void{margin:14px 0;padding:8px 10px;border:2px solid #111;font-weight:700;
letter-spacing:.1em;text-align:center}
.foot{margin-top:22px;font-size:10.5px;color:#777;border-top:1px solid #ccc;padding-top:8px}
@media print{body{padding:0}}
"""


def write(bill, rows, customer=""):
    """One invoice for one bill. Returns the path written."""
    lines = [r for r in rows if r.get("kind") == "sale"]
    if not lines:
        return None
    voided = any(r.get("kind") == "void" for r in rows)
    returns = [r for r in rows if r.get("kind") == "return"]

    subtotal = sum(books.number(r["amount"]) for r in lines)
    tax_total = sum(books.number(r["tax"]) for r in lines)
    by_rate = defaultdict(lambda: [0.0, 0.0])
    for r in lines:
        slot = by_rate[r.get("gst") or books.DEFAULT_GST]
        slot[0] += books.number(r["amount"]) - books.number(r["tax"])
        slot[1] += books.number(r["tax"])

    esc = html.escape
    parts = [f"<!doctype html><meta charset='utf-8'><title>{esc(bill)}</title>",
             f"<style>{CSS}</style>",
             "<h1>TAX INVOICE</h1>",
             f"<div class='shop'>{esc(shop_details())}</div>",
             "<div class='meta'>",
             f"<span>Bill <b>{esc(bill)}</b></span>",
             f"<span>{esc(lines[0].get('at', ''))}</span>",
             f"<span>{esc(customer or lines[0].get('customer') or 'Cash')}</span>",
             "</div>"]

    if voided:
        # Printed on the invoice, not omitted from it. A voided bill that
        # prints as though it were live is how a cancelled sale gets paid twice.
        parts.append("<div class='void'>VOIDED — THIS BILL WAS CANCELLED</div>")

    parts.append("<table><thead><tr><th>Item</th><th class='n'>Qty</th>"
                 "<th class='n'>Rate</th><th class='n'>GST</th>"
                 "<th class='n'>Amount</th></tr></thead><tbody>")
    for r in lines:
        parts.append(
            f"<tr><td>{esc(r['name'])}</td>"
            f"<td class='n'>{books.number(r['qty']):.0f}</td>"
            f"<td class='n'>{books.money(r['price'])}</td>"
            f"<td class='n'>{esc(str(r.get('gst', '')))}%</td>"
            f"<td class='n'>{books.money(r['amount'])}</td></tr>")
    parts.append("</tbody><tfoot>")
    parts.append(f"<tr><td colspan='4' class='n'>Taxable value</td>"
                 f"<td class='n'>{books.money(subtotal - tax_total)}</td></tr>")
    parts.append(f"<tr><td colspan='4' class='n'>GST</td>"
                 f"<td class='n'>{books.money(tax_total)}</td></tr>")
    parts.append(f"<tr class='grand'><td colspan='4' class='n'>Total</td>"
                 f"<td class='n'>₹{books.money(subtotal)}</td></tr>")
    parts.append("</tfoot></table>")

    parts.append("<div class='tax'><b>Tax summary</b><br>")
    for rate in sorted(by_rate, key=lambda x: books.number(x)):
        taxable, tax = by_rate[rate]
        parts.append(f"{rate}% on ₹{books.money(taxable)} = ₹{books.money(tax)}<br>")
    parts.append("</div>")

    if returns:
        parts.append("<div class='tax'><b>Returned against this bill</b><br>")
        for r in returns:
            parts.append(f"{-books.number(r['qty']):.0f} × {esc(r['name'])} "
                         f"(₹{books.money(-books.number(r['amount']))})<br>")
        parts.append("</div>")

    parts.append("<div class='foot'>Prices are inclusive of GST. "
                 "Made by Shishya on this machine — nothing left this computer."
                 "</div>")

    BILLS.mkdir(parents=True, exist_ok=True)
    path = BILLS / f"{bill}.html"
    path.write_text("".join(parts), encoding="utf-8")
    return path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: invoice.py <bill-number>")
    number = sys.argv[1]
    out = write(number, books.bill_rows(number))
    print(out or f"nothing to print for {number}")
