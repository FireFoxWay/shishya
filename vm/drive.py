#!/usr/bin/env python3
"""
Shishya — drive an app through the accessibility layer. Runs INSIDE the sandbox.

    python3 drive.py ask "how many days notice for a TC?"

Why not just move the mouse and type: the display input path has failed twice
under demo conditions. Stale noVNC connections swallow button releases, and
every control goes dead while windows still raise and tooltips still show —
so it looks fine and does nothing.

AT-SPI is a different path entirely. It sets the text on the widget and fires
the button's own action, so it keeps working when the pointer does not. It is
also how the executor will drive apps, so this is not throwaway.
"""

import sys
import time

import pyatspi


def find(app_hint, role, name_hint=None, timeout=20):
    """First matching control, waiting for the app to finish appearing."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for app in pyatspi.Registry.getDesktop(0):
            if app is None or app_hint not in (app.name or "").lower():
                continue
            hit = _walk(app, role, name_hint)
            if hit is not None:
                return hit
        time.sleep(1)
    return None


def _walk(node, role, name_hint, depth=0):
    if node is None or depth > 14:
        return None
    try:
        if node.getRoleName() == role:
            if name_hint is None or name_hint.lower() in (node.name or "").lower():
                return node
        for i in range(node.childCount):
            found = _walk(node[i], role, name_hint, depth + 1)
            if found is not None:
                return found
    except Exception:
        return None
    return None


def set_text(node, text):
    """Replace a field's contents. deleteText then insertText, because
    insertText alone appends to whatever is already in the box."""
    editable = node.queryEditableText()
    try:
        existing = node.queryText().characterCount
    except Exception:
        existing = 0
    if existing:
        editable.deleteText(0, existing)
    editable.insertText(0, text, len(text))


def press(node):
    node.queryAction().doAction(0)


def ask(question):
    field = find("training", "text", "Question")
    if field is None:
        return "Training Data isn't open, or its question box isn't visible yet"
    set_text(field, question)

    button = find("training", "push button", "Ask")
    if button is None:
        return "found the question box but not the Ask button"
    press(button)
    return f"asked: {question}"


def read_answer(timeout=420):
    """Poll the answer pane until it settles — the app answers on a thread."""
    field = find("training", "text", "Answer")
    if field is None:
        return "no answer pane"
    last, stable = "", 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            t = field.queryText()
            now = t.getText(0, t.characterCount)
        except Exception:
            now = ""
        if now and now == last and now not in ("Reading…", "Building the spreadsheet…"):
            stable += 1
            if stable >= 3:
                return now
        else:
            stable = 0
        last = now
        time.sleep(2)
    return last or "(no answer yet)"


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "read"
    if what == "ask":
        print(ask(" ".join(sys.argv[2:])))
    elif what == "read":
        print(read_answer())
    else:
        sys.exit("usage: drive.py ask <question> | drive.py read")
