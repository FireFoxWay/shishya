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


# The chat dashboard is the front door now, so it is tried first; Training
# Data still works for the older, single-purpose flow.
TARGETS = [("chat", "Message", "Send", "Shishya"),
           ("training", "Question", "Ask", "Answer")]


def ask(question):
    for app_hint, box, button, _ in TARGETS:
        field = find(app_hint, "text", box, timeout=4)
        if field is None:
            continue
        set_text(field, question)
        press_button = find(app_hint, "push button", button, timeout=4)
        if press_button is None:
            return f"found the box in {app_hint} but not its {button} button"
        press(press_button)
        return f"asked: {question}"
    return "Nothing is open to ask. Open Shishya from the panel first."


def read_answer(timeout=420):
    """Poll until the reply settles — both apps answer on a thread."""
    if find("chat", "text", "Message", timeout=3) is not None:
        return read_chat(timeout)
    field = find("training", "text", "Answer", timeout=4)
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


def read_chat(timeout=420):
    """The newest thing Shishya said.

    The conversation is a stack of labels rather than one field, so this
    watches the last long one and waits for it to stop changing — the reply
    is written in one go, but the "thinking about how" line precedes it and
    must not be mistaken for the answer.
    """
    deadline = time.time() + timeout
    last, stable = "", 0
    while time.time() < deadline:
        newest = ""
        for app in pyatspi.Registry.getDesktop(0):
            if app is None or "chat" not in (app.name or "").lower():
                continue

            def walk(node, depth=0):
                nonlocal newest
                if depth > 16:
                    return
                try:
                    # Only Shishya's side of the conversation.
                    if node.getRoleName() == "label" and node.name == "reply":
                        try:
                            t = node.queryText()
                            said = t.getText(0, t.characterCount)
                        except Exception:
                            said = ""
                        if said.strip():
                            newest = said
                    for i in range(node.childCount):
                        walk(node[i], depth + 1)
                except Exception:
                    pass
            walk(app)

        working = newest.startswith(("Thinking about", "Let me check", "I'll ", "I will ",
                                     "That needs counting"))
        if newest and newest == last and not working:
            stable += 1
            if stable >= 2:
                return newest
        else:
            stable = 0
        last = newest
        time.sleep(2)
    return last or "(still working)"


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "read"
    if what == "ask":
        print(ask(" ".join(sys.argv[2:])))
    elif what == "read":
        print(read_answer())
    else:
        sys.exit("usage: drive.py ask <question> | drive.py read")
