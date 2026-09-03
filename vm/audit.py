#!/usr/bin/env python3
"""
Shishya — the shop's daily audit. Runs INSIDE the sandbox, usually unattended.

    python3 audit.py /home/clone/shared/jobs/<stamp>

What a shopkeeper would want on the counter in the morning: what sold
yesterday and what it earned, which product actually made the money, how the
month is tracking, and what is about to run out. Reads the Billing app's own
books — the shop's data, not an export of it.

Written code, not a generated program, for the reason the margin work taught
twice over: this runs at six in the evening with nobody watching, and a
number nobody checked is worse than no number at all. Every figure here comes
from summing columns that exist. There is no model call in this file.

`profit` is summed, never recomputed. The Billing app writes it per line at
the cost on the day of sale; recomputing from today's catalogue cost is how a
month's margin quietly becomes fiction — see training/inventory-workbook-notes.md.
"""

import csv
import datetime as dt
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/opt/shishya/vm/shell")
import books       # noqa: E402
import common      # noqa: E402

import matplotlib                      # noqa: E402
matplotlib.use("Agg")                  # no display, and none needed
import matplotlib.pyplot as plt        # noqa: E402

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.edgecolor": "#444", "axes.labelcolor": "#222",
    "xtick.color": "#444", "ytick.color": "#444",
    "axes.grid": True, "grid.color": "#e5e5e5", "grid.linewidth": .6,
    "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
    "figure.dpi": 110,
})
INK = "#1f2430"


def put_status(job, **fields):
    fields.setdefault("t", round(time.time(), 1))
    tmp = job / ".status.tmp"
    tmp.write_text(json.dumps(fields, ensure_ascii=False))
    tmp.replace(job / "status.json")


def rows_of(path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def rupees(value):
    return f"₹{value:,.2f}"


# ─── the four questions ─────────────────────────────────────────────────────

def takings(sales, day):
    """Yesterday's line items — or today's, if the audit runs in the evening.
    The day is decided by the caller, never by this function guessing."""
    return [r for r in sales if (r.get("at") or "").startswith(day)]


def by_product(lines):
    money, profit, units = defaultdict(float), defaultdict(float), defaultdict(float)
    for r in lines:
        name = r.get("name") or "?"
        money[name] += number(r.get("amount"))
        profit[name] += number(r.get("profit"))
        units[name] += number(r.get("qty"))
    return money, profit, units


def month_days(sales, month):
    """Takings per day across the month, so a trend can be drawn rather than
    a single total asserted."""
    per = defaultdict(float)
    for r in sales:
        at = r.get("at") or ""
        if at.startswith(month):
            per[at[:10]] += number(r.get("amount"))
    return dict(sorted(per.items()))


def running_out(catalogue):
    """At or below the reorder point, worst first — and out of stock counts
    as worst. Ten lines, ranked, because a list of four hundred is a dump."""
    short = []
    for r in catalogue:
        stock, point = number(r.get("stock")), number(r.get("reorder"))
        if point <= 0 and stock > 0:
            continue
        if stock <= point:
            short.append((stock - point, stock, point, r.get("name") or "?",
                          number(r.get("cost"))))
    short.sort()
    return short


# ─── drawing ────────────────────────────────────────────────────────────────

def save(fig, out, name, charts):
    fig.tight_layout()
    path = out / name
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    charts.append(name)


def chart_day(profit, money, out, charts):
    """What actually earned today. Ranked by profit, not by takings — the
    biggest seller and the biggest earner are rarely the same product, and
    only one of them pays the rent."""
    top = sorted(profit.items(), key=lambda kv: kv[1], reverse=True)[:10]
    if not top:
        return
    names = [n[:26] for n, _ in reversed(top)]
    values = [v for _, v in reversed(top)]
    fig, ax = plt.subplots(figsize=(7, max(2.6, .38 * len(top) + 1)))
    ax.barh(names, values, color=INK)
    ax.set_title("Today's profit by product")
    ax.set_xlabel("gross profit (₹)")
    save(fig, out, "profit-today.png", charts)


def chart_month(days, out, charts):
    if len(days) < 2:
        return
    labels = [d[8:10] for d in days]
    fig, ax = plt.subplots(figsize=(7.4, 3.2))
    ax.plot(labels, list(days.values()), marker="o", markersize=3,
            linewidth=1.6, color=INK)
    ax.set_title("Sales across the month")
    ax.set_xlabel("day")
    ax.set_ylabel("takings (₹)")
    save(fig, out, "month-sales.png", charts)


def chart_short(short, out, charts):
    if not short:
        return
    worst = short[:10]
    names = [n[:26] for _, _, _, n, _ in reversed(worst)]
    stock = [s for _, s, _, _, _ in reversed(worst)]
    point = [p for _, _, p, _, _ in reversed(worst)]
    fig, ax = plt.subplots(figsize=(7, max(2.6, .38 * len(worst) + 1)))
    ax.barh(names, point, color="#c2c7cf", label="reorder point")
    ax.barh(names, stock, color=INK, height=.5, label="on hand")
    ax.set_title("Running out")
    ax.legend(fontsize=8, frameon=False)
    save(fig, out, "running-out.png", charts)


# ─── the page ───────────────────────────────────────────────────────────────

def provenance(job):
    """One line, quoting the host's own record of the machine at the time.

    Not the sandbox's opinion of itself: it cannot check, and a deliverable
    that vouches for its own conditions is worth nothing. Says "not recorded"
    rather than guessing, because an unverified claim of a locked network is
    exactly the failure this is here to prevent.
    """
    try:
        spec = json.loads((job / "job.json").read_text())
    except (OSError, ValueError):
        return "Made on this machine. Network state at the time was not recorded."
    net = spec.get("egress") or {}
    locked = net.get("locked")
    where = ("with the sandbox's network locked — nothing could leave this "
             "computer while this was made" if locked is True else
             "with the sandbox's network OPEN — " + (net.get("detail") or "")
             if locked is False else
             "with the network state unrecorded")
    return (f"Made by Shishya on this machine, {where}. "
            f"Model: {spec.get('model', '?')}.")


def page(title, findings, charts, short, stamp):
    css = ("body{font-family:-apple-system,'Segoe UI',sans-serif;max-width:860px;"
           "margin:0 auto;padding:28px;color:#1a1c1e;background:#fcfcfa}"
           "h1{font-size:24px;border-bottom:2px solid #1a1c1e;padding-bottom:8px}"
           "h2{font-size:15px;margin-top:28px}img{max-width:100%;"
           "border:1px solid #ddd;margin:8px 0}li{margin:5px 0}"
           "table{border-collapse:collapse;font-size:13px;width:100%}"
           "th,td{text-align:left;padding:6px 10px;border-bottom:1px solid #eee}"
           "th{font-size:11px;text-transform:uppercase;color:#71767c}"
           ".dim{color:#71767c;font-size:13px}")
    parts = [f"<!doctype html><meta charset='utf-8'><title>{title}</title>",
             f"<style>{css}</style><h1>{title}</h1>",
             f"<p class='dim'>{time.strftime('%d %b %Y, %H:%M')} — {stamp}</p>",
             "<h2>The figures</h2><ul>"]
    parts += [f"<li>{f}</li>" for f in findings]
    parts.append("</ul>")
    for name in charts:
        parts.append(f"<h2>{name[:-4].replace('-', ' ').title()}</h2>"
                     f"<img alt='{name}' src='{name}'>")
    if short:
        parts.append("<h2>Order these</h2><table><tr><th>Product</th>"
                     "<th>On hand</th><th>Reorder at</th><th>Cost to refill</th></tr>")
        for _, stock, point, name, cost in short[:15]:
            need = max(point * 2 - stock, 0)
            parts.append(f"<tr><td>{name}</td><td>{stock:.0f}</td>"
                         f"<td>{point:.0f}</td><td>{rupees(need * cost)}</td></tr>")
        parts.append("</table>")
    return "".join(parts)


def main(job_dir):
    job = Path(job_dir)
    out = job / "out"
    out.mkdir(parents=True, exist_ok=True)
    common.set_state("working")
    put_status(job, state="working", step="reading the shop's books")

    # Through books, not the raw file: a voided bill writes reversing rows
    # and its takings must net to zero here without the audit knowing the
    # first thing about how a void is spelled.
    sales = books.read_sales()
    catalogue = books.read_catalogue()
    if not catalogue:
        put_status(job, state="failed",
                   step="there is no catalogue yet — open the Billing app once "
                        "to stock the counter")
        common.set_state("idle")
        return

    # Which day this audit is about. An evening run reports today; a run
    # before the shop opens reports the day that just ended. Decided here and
    # printed in the title, so a report is never ambiguous about its own date.
    now = dt.datetime.now()
    subject = now.date() if now.hour >= 12 else now.date() - dt.timedelta(days=1)
    day, month = subject.isoformat(), subject.strftime("%Y-%m")

    put_status(job, state="working", step=f"auditing {day}")
    today = takings(sales, day)
    money, profit, units = by_product(today)
    days = month_days(sales, month)
    short = running_out(catalogue)

    took = sum(money.values())
    earned = sum(profit.values())
    tax_today = sum(number(r.get("tax")) for r in today)
    month_took = sum(days.values())
    stock_value = sum(number(r.get("stock")) * number(r.get("cost")) for r in catalogue)

    findings = []
    if today:
        bills = len({r.get("bill") for r in today})
        findings.append(f"<b>{subject:%d %b}</b>: {rupees(took)} across {bills} "
                        f"bill(s), earning {rupees(earned)} "
                        f"({earned / took * 100:.1f}% margin)." if took else
                        f"<b>{subject:%d %b}</b>: no takings.")
        best = max(profit.items(), key=lambda kv: kv[1], default=None)
        if best and best[1] > 0:
            findings.append(f"Most profitable product of the day: <b>{best[0]}</b>, "
                            f"earning {rupees(best[1])} on {units[best[0]]:.0f} "
                            f"unit(s) — {best[1] / earned * 100:.0f}% of the day's profit.")
        seller = max(money.items(), key=lambda kv: kv[1], default=None)
        if seller and best and seller[0] != best[0]:
            findings.append(f"The biggest <i>seller</i> was a different product: "
                            f"<b>{seller[0]}</b> at {rupees(seller[1])} in takings "
                            f"but only {rupees(profit[seller[0]])} of profit. "
                            f"Volume and earnings are not the same product here.")
    else:
        findings.append(f"<b>{subject:%d %b}</b>: nothing was billed.")

    if tax_today:
        findings.append(f"GST collected today: {rupees(tax_today)} — already "
                        f"inside the takings above, not on top of them.")
    voided_today = {r.get("bill") for r in today if r.get("kind") == "void"}
    if voided_today:
        findings.append(f"{len(voided_today)} bill(s) were voided today; their "
                        f"takings are already netted out of the figure above.")
    findings.append(f"Month to date ({subject:%B}): <b>{rupees(month_took)}</b> "
                    f"across {len(days)} trading day(s).")
    findings.append(f"Stock on hand is worth {rupees(stock_value)} at cost, "
                    f"across {len(catalogue):,} products.")
    if short:
        out_of = sum(1 for _, s, _, _, _ in short if s <= 0)
        findings.append(f"<b>{len(short)}</b> product(s) at or below their reorder "
                        f"point, {out_of} of them out of stock entirely.")

    put_status(job, state="working", step="drawing")
    charts = []
    chart_day(profit, money, out, charts)
    chart_month(days, out, charts)
    chart_short(short, out, charts)

    title = f"Shop audit — {subject:%d %B %Y}"
    (out / "audit.html").write_text(
        page(title, findings, charts, short, provenance(job)))

    import re
    plain = [re.sub(r"<[^>]+>", "", f) for f in findings]
    put_status(job, state="done",
               files=sorted(f.name for f in out.iterdir() if f.is_file()),
               empty=[], said="\n".join(plain),
               step=f"done — audit.html and {len(charts)} chart(s)")
    common.set_state("idle")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: audit.py <job-dir>")
    try:
        main(sys.argv[1])
    except Exception as e:
        try:
            put_status(Path(sys.argv[1]), state="failed",
                       step=f"the audit itself failed: {type(e).__name__}: {e}")
        finally:
            common.set_state("idle")
        raise
