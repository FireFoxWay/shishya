#!/usr/bin/env python3
"""
Shishya — which models can actually do the work. Runs INSIDE the sandbox.

    python3 bench.py                       every local model
    python3 bench.py --models llama2:latest,gpt-oss:latest

The Models screen has always said "one model per job, pick a small one where
a small one will do." That was an argument, not a measurement, and the honest
version of the sovereignty claim depends on it: a school with a ₹60,000
desktop cannot run a 14 GB model, so either a small one works or the pitch
has a hole in it.

So this asks every installed model the same question — one whose answer is
known independently — and reports whether the program it wrote ran, whether
the figure came out right, and what it cost in time and memory. Cloud models
are skipped: a benchmark of what runs on this machine has no business
measuring something that does not.

The question is deliberately the boring one. "Low stock by category" was
verified against the file long before any of this existed (§14), so a wrong
answer here is the model's, not the question's.
"""

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/shishya/vm/shell")
import chat_app    # noqa: E402
import common      # noqa: E402

QUESTION = ("count how many products are low on stock in each category in the "
            "retail inventory, and print the total")

# Verified against the file itself, not against a previous model's answer.
TRUTH = {"total": "149", "categories": 8}

HOST = "http://host.lima.internal:11434"


def installed():
    with urllib.request.urlopen(f"{HOST}/api/tags", timeout=20) as r:
        models = json.loads(r.read())["models"]
    # A cloud model is not a local model, whatever the list says.
    return [(m["name"], m["size"] / 1e9) for m in models
            if "cloud" not in m["name"]]


def loaded_vram():
    try:
        with urllib.request.urlopen(f"{HOST}/api/ps", timeout=10) as r:
            live = json.loads(r.read()).get("models", [])
        return max((m.get("size_vram", 0) for m in live), default=0) / 1e9
    except Exception:
        return 0.0


def judge(output):
    """Right, wrong, or nothing — decided on the figure, not on the prose."""
    if not output:
        return "no output"
    if TRUTH["total"] not in output:
        return "wrong figure"
    # The eight categories matter as much as the total: a model that prints
    # 149 and three categories has not done the grouping it was asked for.
    lines = [l for l in output.splitlines() if l.strip()]
    return "correct" if len(lines) >= TRUTH["categories"] else "partial"


def run_one(model, listing):
    """One model, one question, honestly timed — including the load."""
    was = common.MODEL
    common.MODEL = model               # bench, so the job map is bypassed
    start = time.time()
    try:
        code = chat_app.repair(common.ask(
            f"{listing}\n\nWrite a Python script that: {QUESTION}",
            system=chat_app.CODE_SYSTEM, budget=4096, timeout=900))
    except Exception as e:
        common.MODEL = was
        return {"model": model, "verdict": f"failed: {type(e).__name__}",
                "wrote": 0, "ran": 0, "vram": 0.0}
    wrote = time.time() - start
    vram = loaded_vram()
    common.MODEL = was

    if not chat_app.usable(code):
        return {"model": model, "verdict": "wrote no program",
                "wrote": wrote, "ran": 0, "vram": vram}
    start = time.time()
    out, err = chat_app.run_script(code)
    ran = time.time() - start
    verdict = judge(out) if out else f"crashed: {(err or '').strip().splitlines()[-1][:40] if err else '?'}"
    return {"model": model, "verdict": verdict, "wrote": wrote,
            "ran": ran, "vram": vram, "output": (out or "")[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", help="comma separated; default is everything local")
    args = ap.parse_args()

    local = installed()
    sizes = dict(local)
    names = ([m.strip() for m in args.models.split(",")] if args.models
             else [n for n, _ in local])

    listing = chat_app.describe_material()
    print(f"Question: {QUESTION}")
    print(f"Known answer: {TRUTH['total']} products across {TRUTH['categories']} categories\n")
    print(f"{'MODEL':<24}{'ON DISK':>9}{'IN RAM':>9}{'WROTE':>9}{'RAN':>8}  VERDICT")

    results = []
    for name in names:
        row = run_one(name, listing)
        results.append(row)
        print(f"{name:<24}{sizes.get(name, 0):>8.1f}G{row['vram']:>8.1f}G"
              f"{row['wrote']:>8.0f}s{row['ran']:>7.1f}s  {row['verdict']}", flush=True)

    ok = [r for r in results if r["verdict"] == "correct"]
    if ok:
        cheapest = min(ok, key=lambda r: sizes.get(r["model"], 99))
        print(f"\nSmallest model that got it right: {cheapest['model']} "
              f"({sizes.get(cheapest['model'], 0):.1f} GB on disk, "
              f"{cheapest['vram']:.1f} GB resident) in "
              f"{cheapest['wrote']:.0f}s.")
    else:
        print("\nNothing answered correctly — the question, not the models, "
              "is the first thing to check.")
    Path("/tmp/bench.json").write_text(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
