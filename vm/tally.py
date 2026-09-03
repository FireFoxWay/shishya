#!/usr/bin/env python3
"""
Shishya — turn a purchase register into Tally Prime import XML. Runs INSIDE the sandbox.

    python3 tally.py /home/clone/shared/jobs/<stamp>

One press on the panel: the files waiting in the inbox become supplier
ledgers and purchase vouchers that Gateway of Tally > Import Data accepts.
The accounting bridge — Tally itself is Windows-only and cannot run here,
but nothing about a register needs it to.

Written code, not a generated program. The margin work proved the model
finds a new shortcut for every rule it is given; an accounting file is where
that habit goes to do real damage. So the shape is fixed and the rules from
training/tally-import-notes.md are enforced by construction:

  masters before vouchers · dates YYYYMMDD · debit = ISDEEMEDPOSITIVE Yes
  with a negative amount · every voucher sums to zero, in paise · names
  XML-escaped · supplier spellings deduplicated before ledgers are made

and the file is re-parsed and re-checked before it is called a deliverable.
The one thing this cannot verify is Tally itself accepting it — that needs
a Windows machine with Tally, and the summary says in plain words to try a
TEST company first. Import Data cannot be undone.
"""

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, "/opt/shishya/vm")
sys.path.insert(0, "/opt/shishya/vm/shell")
import common      # noqa: E402
import reporter    # noqa: E402  — tables_from: one reader for every runner


def put_status(job, **fields):
    fields.setdefault("t", round(time.time(), 1))
    tmp = job / ".status.tmp"
    tmp.write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")
    tmp.replace(job / "status.json")


# ─── finding the register in whatever arrived ───────────────────────────────

FAMILY = re.compile(r"^(Purchased From|Purchase Qty|Net Purchase Price)\s+(\d+)$")

SUPPLIERISH = ("supplier", "party", "vendor", "purchased from", "seller",
               "distributor", "company")
AMOUNTISH = ("amount", "value", "total", "net amount", "purchase value")
QTYISH = ("qty", "quantity", "units")
PRICEISH = ("price", "rate", "cost")


def stacked_family(frame):
    """The pharmacy shape: suppliers held wide, 'Purchased From 1..10' with a
    qty and a price each. Stacked into (supplier, amount) rows — the same
    stacking Findings had to be told about, done here without asking."""
    groups = defaultdict(dict)
    for col in frame.columns:
        m = FAMILY.match(str(col).strip())
        if m:
            groups[m.group(2)][m.group(1)] = col
    rows = []
    for cols in groups.values():
        if len(cols) < 3:
            continue
        part = frame[[cols["Purchased From"], cols["Purchase Qty"],
                      cols["Net Purchase Price"]]].copy()
        part.columns = ["supplier", "qty", "price"]
        rows.append(part)
    if not rows:
        return None
    import pandas as pd
    out = pd.concat(rows, ignore_index=True)
    out["qty"] = pd.to_numeric(out["qty"], errors="coerce")
    out["price"] = pd.to_numeric(out["price"], errors="coerce")
    out = out.dropna(subset=["supplier", "qty", "price"])
    out["amount"] = out["qty"] * out["price"]
    return out[["supplier", "amount"]]


def flat_register(frame):
    """A plain register: one supplier column, and either an amount column or
    a qty and a price to multiply."""
    import pandas as pd

    def pick(words):
        for col in frame.columns:
            name = str(col).strip().lower()
            if any(w in name for w in words):
                return col
        return None

    supplier = pick(SUPPLIERISH)
    if supplier is None:
        return None
    amount = pick(AMOUNTISH)
    if amount is not None:
        out = frame[[supplier, amount]].copy()
        out.columns = ["supplier", "amount"]
    else:
        qty, price = pick(QTYISH), pick(PRICEISH)
        if qty is None or price is None:
            return None
        out = frame[[supplier, qty, price]].copy()
        out.columns = ["supplier", "qty", "price"]
        out["qty"] = pd.to_numeric(out["qty"], errors="coerce")
        out["price"] = pd.to_numeric(out["price"], errors="coerce")
        out["amount"] = out["qty"] * out["price"]
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce")
    return out.dropna(subset=["supplier", "amount"])[["supplier", "amount"]]


def canonical(rows):
    """One ledger per real supplier. The same supplier arrives as
    'KK ENTERPRISES' and 'Kk Enterprises'; folded by case and whitespace,
    and the spelling that appears most often is the one Tally gets."""
    spellings = defaultdict(lambda: defaultdict(int))
    paise = defaultdict(int)
    for supplier, amount in rows:
        name = re.sub(r"\s+", " ", str(supplier)).strip()
        if not name or name.lower() in ("n/a", "na", "none", "-", "nan"):
            continue
        key = name.casefold()
        spellings[key][name] += 1
        paise[key] += round(float(amount) * 100)
    out = {}
    for key, count in spellings.items():
        display = max(count, key=count.get)
        if paise[key] > 0:
            out[display] = paise[key]
    return out


# ─── writing what Tally imports ─────────────────────────────────────────────

def voucher_xml(suppliers, date):
    """Masters first, then one purchase voucher per supplier. One file: rule
    1 says ledgers must exist before the vouchers that name them, and a
    single file in this order satisfies that by construction."""
    lines = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
             "<ENVELOPE>",
             " <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>",
             " <BODY><IMPORTDATA>",
             "  <REQUESTDESC><REPORTNAME>All Masters</REPORTNAME></REQUESTDESC>",
             "  <REQUESTDATA>"]

    def ledger(name, parent):
        safe = escape(name, {'"': "&quot;"})
        lines.extend([
            "   <TALLYMESSAGE>",
            f"    <LEDGER NAME=\"{safe}\" ACTION=\"Create\">",
            f"     <NAME>{safe}</NAME>",
            f"     <PARENT>{escape(parent)}</PARENT>",
            "    </LEDGER>",
            "   </TALLYMESSAGE>"])

    ledger("Purchase Account", "Purchase Accounts")
    for name in suppliers:
        ledger(name, "Sundry Creditors")
    lines.append("  </REQUESTDATA>")

    lines.extend([
        "  <REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME></REQUESTDESC>",
        "  <REQUESTDATA>"])
    for name, paise in suppliers.items():
        amount = f"{paise / 100:.2f}"
        safe = escape(name)
        lines.extend([
            "   <TALLYMESSAGE>",
            "    <VOUCHER VCHTYPE=\"Purchase\" ACTION=\"Create\">",
            f"     <DATE>{date}</DATE>",
            "     <VOUCHERTYPENAME>Purchase</VOUCHERTYPENAME>",
            f"     <PARTYLEDGERNAME>{safe}</PARTYLEDGERNAME>",
            "     <ALLLEDGERENTRIES.LIST>",
            f"      <LEDGERNAME>{safe}</LEDGERNAME>",
            "      <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>",
            f"      <AMOUNT>{amount}</AMOUNT>",
            "     </ALLLEDGERENTRIES.LIST>",
            "     <ALLLEDGERENTRIES.LIST>",
            "      <LEDGERNAME>Purchase Account</LEDGERNAME>",
            "      <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>",
            f"      <AMOUNT>-{amount}</AMOUNT>",
            "     </ALLLEDGERENTRIES.LIST>",
            "    </VOUCHER>",
            "   </TALLYMESSAGE>"])
    lines.extend(["  </REQUESTDATA>", " </IMPORTDATA></BODY>", "</ENVELOPE>"])
    return "\n".join(lines)


def check(path):
    """Re-read the file just written and prove the rules held. The XML the
    person forwards to their accountant is the file on disk, so the file on
    disk is what gets checked — never the string it was made from."""
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    ledgers = {l.get("NAME") for l in root.iter("LEDGER")}
    vouchers = list(root.iter("VOUCHER"))
    problems = []
    for v in vouchers:
        party = v.findtext("PARTYLEDGERNAME")
        if party not in ledgers:
            problems.append(f"voucher names {party!r} but no such ledger is created")
        total = sum(round(float(e.findtext("AMOUNT")) * 100)
                    for e in v.iter("ALLLEDGERENTRIES.LIST"))
        if total != 0:
            problems.append(f"voucher for {party!r} sums to {total} paise, not 0")
        if not re.fullmatch(r"\d{8}", v.findtext("DATE") or ""):
            problems.append(f"voucher for {party!r} has a malformed date")
    return len(ledgers) - 1, len(vouchers), problems


def main(job_dir):
    job = Path(job_dir)
    out = job / "out"
    out.mkdir(exist_ok=True)
    inputs = sorted(p for p in (job / "in").iterdir()
                    if p.is_file() and not p.name.startswith("."))
    common.set_state("working")

    rows, read_from = [], []
    for path in inputs:
        put_status(job, state="working", step=f"reading {path.name}")
        try:
            tables = reporter.tables_from(path)
        except Exception:
            continue
        for name, frame in tables:
            register = stacked_family(frame)
            if register is None:
                register = flat_register(frame)
            if register is not None and len(register):
                rows.extend(register.itertuples(index=False, name=None))
                read_from.append(name)

    if not rows:
        put_status(job, state="failed",
                   step="no purchase register found — I need a table with a "
                        "supplier column and amounts (or qty and price)")
        common.set_state("idle")
        return

    put_status(job, state="working", step="building ledgers and vouchers")
    suppliers = canonical(rows)
    xml = voucher_xml(suppliers, time.strftime("%Y%m%d"))
    target = out / "tally-import.xml"
    target.write_text(xml, encoding="utf-8")

    put_status(job, state="working", step="checking the file against the rules")
    n_ledgers, n_vouchers, problems = check(target)
    if problems:
        target.unlink(missing_ok=True)
        put_status(job, state="failed",
                   step="the file failed its own checks and was not delivered",
                   error="\n".join(problems[:8]))
        common.set_state("idle")
        return

    total = sum(suppliers.values()) / 100
    summary = (f"{n_ledgers} supplier ledgers and {n_vouchers} purchase vouchers, "
               f"₹{total:,.2f} in total, read from: {', '.join(read_from)}.\n"
               f"Checked: every voucher balances to zero and names a ledger "
               f"the file creates.\n"
               f"IMPORT INTO A TEST COMPANY FIRST — Gateway of Tally > Import "
               f"Data cannot be undone.")
    (out / "summary.txt").write_text(summary, encoding="utf-8")
    put_status(job, state="done",
               files=["tally-import.xml", "summary.txt"], empty=[],
               said=summary,
               step=f"done — {n_ledgers} ledgers, {n_vouchers} vouchers")
    common.set_state("idle")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: tally.py <job-dir>")
    try:
        main(sys.argv[1])
    except Exception as e:
        try:
            put_status(Path(sys.argv[1]), state="failed",
                       step=f"the converter itself failed: {type(e).__name__}: {e}")
        finally:
            common.set_state("idle")
        raise
