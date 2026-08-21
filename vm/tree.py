#!/usr/bin/env python3
"""
Shishya — dump the accessibility tree. Runs INSIDE the sandbox.

The debugging tool you reach for whenever a recording comes back thin or the
executor cannot find a control. Shows exactly what the agent can see.

    python3 tree.py                 # everything
    python3 tree.py Shishya         # only apps whose name matches
"""

import sys

import pyatspi

SKIP = {"filler", "panel", "section", "redundant object"}


def walk(node, depth=0, limit=12):
    if node is None or depth > limit:
        return
    try:
        role, name = node.getRoleName(), (node.name or "")
        count = node.childCount
    except Exception:
        return                       # controls vanish mid-walk; keep going

    if role not in SKIP or name:
        print(f"{'  ' * depth}{role:<18} {name}")

    for i in range(count):
        try:
            # This pyatspi exposes children by indexing, not getChildAt().
            walk(node[i], depth + 1, limit)
        except Exception:
            continue


if __name__ == "__main__":
    want = sys.argv[1].lower() if len(sys.argv) > 1 else None
    desktop = pyatspi.Registry.getDesktop(0)
    found = False
    for app in desktop:
        if app is None:
            continue
        if want and want not in (app.name or "").lower():
            continue
        found = True
        print(f"\n=== {app.name} ===")
        walk(app)
    if not found:
        print("nothing matched — is the app running, and on the shared bus?")
