#!/usr/bin/env python3
"""
Shishya — find a control by what it is called. Runs INSIDE the sandbox.

The primitive everything else stands on. A procedure says "the field labelled
District"; this turns that into a point on screen. Get this right and the
executor is mostly bookkeeping; get it wrong and no amount of good synthesis
matters.

    python3 locate.py "Training Data"          # anywhere
    python3 locate.py Ask --app training_app   # narrowed to one app
"""

import argparse
import re
import subprocess
import sys
import time

import pyatspi

# A spreadsheet's cell grid reports its *theoretical* size as its child count:
# LibreOffice Calc says 2,147,483,647, which is INT32_MAX and not a number of
# cells anyone has. Walking `range(childCount)` over AT-SPI runs at roughly
# 1,500 nodes a second, so descending into one takes about sixteen days — the
# search does not fail, it simply never returns, which is far worse.
#
# Nothing findable by name lives inside the grid anyway: cells are reached
# through the Table interface by row and column, not by walking. So a node
# claiming more children than any real interface has is treated as opaque.
HUGE = 100_000

# Roles worth clicking. A label with the right text is usually describing the
# control next to it, not the thing to press.
CLICKABLE = {
    "push button", "toggle button", "check box", "radio button", "menu item",
    "list item", "table cell", "text", "entry", "password text", "combo box",
    "tab", "link", "icon",
}


def find(name, app=None, role=None, visible_only=True):
    """Every match, best first.

    Returns dicts rather than live accessibles because the caller usually
    wants to act, and an accessible held across a click may already be stale
    by the time it is used.
    """
    hits = []
    desktop = pyatspi.Registry.getDesktop(0)
    for application in desktop:
        if application is None:
            continue
        if app and app.lower() not in (application.name or "").lower():
            continue
        _walk(application, application.name, name.lower(), role, visible_only, hits)
    # Exact name first, then shortest — "Save" should beat "Save changes"
    # when the procedure said Save.
    hits.sort(key=lambda h: (not h["exact"], len(h["name"])))
    return hits


# A spreadsheet's accessible table reports INT_MAX children — 2,147,483,647
# for a blank Calc sheet — and walking that is why finding the Name Box with
# a sheet open used to take forever and time out. Anything with more children
# than this is a data grid, not a container of controls, and its cells are
# reached through the Table interface (see executor.confirm), never by walk.
TOO_MANY = 512


def _walk(node, app_name, wanted, role, visible_only, hits, depth=0):
    if node is None or depth > 14:
        return
    try:
        count = node.childCount
        node_name = node.name or ""
        node_role = node.getRoleName()
    except Exception:
        return
    if count > TOO_MANY:
        count = 0

    if node_name and wanted in node_name.lower():
        if (role is None or role == node_role) and node_role in CLICKABLE:
            point = _point(node, visible_only)
            if point:
                hits.append({
                    "name": node_name, "role": node_role, "app": app_name,
                    "x": point[0], "y": point[1], "w": point[2], "h": point[3],
                    "exact": node_name.lower() == wanted,
                })

    if count > HUGE:
        return

    for i in range(count):
        try:
            _walk(node[i], app_name, wanted, role, visible_only, hits, depth + 1)
        except Exception:
            continue


def inside(container, role="panel", index=0, app=None, visible_only=True):
    """A point for a control that has no name of its own.

    Some controls cannot be found by name because they do not have one. Calc's
    Name Box is the case that forced this: LibreOffice exposes it as an
    unnamed panel with no text interface, so `find("Name Box")` matches
    nothing however long it looks. What it does have is a named container and
    a stable position inside it — it is the first panel of the Formula Tool
    Bar — and that is enough to reach it.

    Extents are read fresh on every call rather than remembered, so this
    survives the window being moved, which is the whole reason we are not
    simply hard-coding the coordinates it sits at today.
    """
    holder = []
    desktop = pyatspi.Registry.getDesktop(0)
    for application in desktop:
        if application is None:
            continue
        if app and app.lower() not in (application.name or "").lower():
            continue
        _find_named(application, container.lower(), holder)
        if holder:
            break
    if not holder:
        return None

    matches = []
    node = holder[0]
    try:
        for i in range(min(node.childCount, 200)):
            child = node[i]
            if child is not None and child.getRoleName() == role:
                matches.append(child)
    except Exception:
        return None
    if index >= len(matches):
        return None

    point = _point(matches[index], visible_only)
    if not point:
        return None
    return {"name": f"{container}[{role} {index}]", "role": role,
            "app": (holder[0].getApplication().name or ""), "exact": True,
            "x": point[0], "y": point[1], "w": point[2], "h": point[3]}


CELL_REF = re.compile(r"^([A-Z]{1,3})(\d{1,7})$", re.I)


def cell_text(ref, app="soffice"):
    """What is actually in a named spreadsheet cell, or None.

    The grid cannot be walked — see TOO_MANY above — but it does not need to be.
    The Table interface reaches a cell directly by row and column in about a
    millisecond, on the same node whose child count made walking hopeless.

    This is what makes a typed value verifiable. Searching the tree for the
    text was the alternative, and it answered the wrong question: it could
    only ever say "this appears somewhere on screen", never "it is in I4".
    """
    match = CELL_REF.match((ref or "").strip())
    if not match:
        return None
    column = 0
    for letter in match.group(1).upper():
        column = column * 26 + (ord(letter) - 64)
    column -= 1
    row = int(match.group(2)) - 1

    holder = []
    for application in pyatspi.Registry.getDesktop(0):
        if application is None:
            continue
        if app and app.lower() not in (application.name or "").lower():
            continue
        _find_role(application, "table", holder)
        if holder:
            break
    if not holder:
        return None
    try:
        cell = holder[0].queryTable().getAccessibleAt(row, column)
        text = cell.queryText()
        return text.getText(0, text.characterCount)
    except Exception:
        return None


def grid(app="soffice", tries=4):
    """The spreadsheet's accessible table, or None.

    Retries, because this lookup fails intermittently right after a
    keystroke: LibreOffice rebuilds part of its tree and a walk that starts
    mid-rebuild finds nothing at all. Once cost a lesson its last four steps
    with the sheet plainly on screen and the cursor in the right cell — the
    only thing wrong was that the question had been asked at the wrong
    millisecond. A miss is a retry, never a verdict.
    """
    for attempt in range(tries):
        for application in pyatspi.Registry.getDesktop(0):
            if application is None:
                continue
            try:
                if app and app.lower() not in (application.name or "").lower():
                    continue
            except Exception:
                continue
            holder = []
            _find_role(application, "table", holder)
            if holder:
                return holder[0]
        if attempt < tries - 1:
            time.sleep(0.4)
    return None


def current_cell(app="soffice"):
    """Which cell the cursor is actually in, or None.

    Asked of the grid through the Collection interface rather than found by
    walking: the sheet reports two billion children, and the one with focus
    cannot be reached by looking at them one at a time. Collection lets the
    toolkit answer "which of your descendants has focus" in a single call.

    This is what makes a `goto` verifiable. Before it, going to a cell was
    reported as "not verifiable, assumed" — the executor typed into whatever
    the arrow keys had reached and only found out later, when the value it
    typed failed to read back from the cell it meant.
    """
    sheet = grid(app)
    if sheet is not None:
        try:
            collection = sheet.queryCollection()
            states = pyatspi.StateSet()
            states.add(pyatspi.STATE_FOCUSED)
            rule = collection.createMatchRule(
                states.raw(), collection.MATCH_ALL,
                [], collection.MATCH_ALL,      # attributes: any
                [], collection.MATCH_ALL,      # roles: any
                [], collection.MATCH_ALL,      # interfaces: any
                False)
            found = collection.getMatches(rule, collection.SORT_ORDER_CANONICAL,
                                          1, True)
            if found:
                return found[0].name
        except Exception:
            pass
    return None


def _find_role(node, wanted, out, depth=0):
    """First node of this role. The grid itself is the target here, so this
    stops *at* a huge node rather than refusing to look at it."""
    if out or node is None or depth > 14:
        return
    try:
        count, role = node.childCount, node.getRoleName()
    except Exception:
        return
    if role == wanted:
        out.append(node)
        return
    if count > HUGE:
        return
    for i in range(count):
        try:
            _find_role(node[i], wanted, out, depth + 1)
        except Exception:
            continue


def _find_named(node, wanted, out, depth=0):
    """First node with this exact name. Stops at the first hit rather than
    collecting every one, because the caller wants a container, not a list."""
    if out or node is None or depth > 14:
        return
    try:
        count, name = node.childCount, (node.name or "").lower()
    except Exception:
        return
    if name == wanted:
        out.append(node)
        return
    if count > HUGE:
        return
    for i in range(count):
        try:
            _find_named(node[i], wanted, out, depth + 1)
        except Exception:
            continue


def _point(node, visible_only):
    """Screen rectangle, or None when the control cannot be clicked.

    A control scrolled out of view still reports a rectangle — an off-screen
    or zero-sized one. Clicking that lands somewhere arbitrary, so those are
    dropped rather than returned as a usable target.
    """
    try:
        component = node.queryComponent()
    except NotImplementedError:
        return None
    try:
        x, y, w, h = component.getExtents(pyatspi.DESKTOP_COORDS)
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    if visible_only and (x < 0 or y < 0):
        return None
    return x + w // 2, y + h // 2, w, h


# ─── being on top ───────────────────────────────────────────────────────────
# AT-SPI reports where a control is, not whether you can reach it. A button
# under another window has perfectly good coordinates and clicking them hits
# the window on top instead — silently, landing a click somewhere nobody
# intended. So before clicking we raise the window that owns the control, and
# afterwards we check that the point really belongs to it.

def toplevel_name(hit_app):
    """The window title to raise. Apps name their frame after themselves,
    which is what the window manager matches on."""
    return hit_app.replace(".py", "").replace("_", " ")


def window_at(x, y):
    """Which window owns this point, according to X rather than AT-SPI."""
    try:
        out = subprocess.run(["xdotool", "getmouselocation", "--shell"],
                             capture_output=True, text=True, timeout=4)
        subprocess.run(["xdotool", "mousemove", str(x), str(y)], timeout=4)
        out = subprocess.run(["xdotool", "getmouselocation", "--shell"],
                             capture_output=True, text=True, timeout=4).stdout
        for line in out.splitlines():
            if line.startswith("WINDOW="):
                return line.split("=", 1)[1].strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def raise_owner(hit):
    """Bring the control's own window forward.

    The desktop is deliberately excluded: it is a DESKTOP-type window and the
    window manager keeps it behind everything, by design. Icons on it are only
    clickable when nothing covers them, exactly as on any other desktop.
    """
    if "desktop" in hit["app"].lower():
        return False
    try:
        found = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--name", toplevel_name(hit["app"])],
            capture_output=True, text=True, timeout=5).stdout.split()
        if not found:
            return False
        subprocess.run(["xdotool", "windowactivate", "--sync", found[0]], timeout=5)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def click(hit, name, app=None, role=None):
    """Click a control, having first made sure it is the thing being clicked."""
    raised = raise_owner(hit)
    if raised:
        # Raising can move things, so ask again rather than trusting the
        # coordinates we took before the window came forward.
        again = find(name, app, role)
        if again:
            hit = again[0]

    owner = window_at(hit["x"], hit["y"])
    if owner:
        mine = subprocess.run(["xdotool", "getwindowname", owner],
                              capture_output=True, text=True, timeout=4).stdout.strip()
        expected = toplevel_name(hit["app"]).lower()
        if mine and expected.split()[0] not in mine.lower() and "desktop" not in mine.lower():
            return (False, f"{hit['name']!r} is underneath {mine!r} — "
                           f"close or move that window first")

    subprocess.run(["xdotool", "mousemove", str(hit["x"]), str(hit["y"]),
                    "click", "1"], check=False)
    return (True, f"clicked {hit['name']!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--app")
    ap.add_argument("--role")
    ap.add_argument("--click", action="store_true", help="click the best match")
    args = ap.parse_args()

    hits = find(args.name, args.app, args.role)
    if not hits:
        sys.exit(f"no control matching {args.name!r}")

    for h in hits[:6]:
        mark = "*" if h["exact"] else " "
        print(f"{mark} {h['role']:<14} {h['name'][:34]:<34} {h['app'][:16]:<16} "
              f"@ {h['x']},{h['y']}")

    if args.click:
        ok, message = click(hits[0], args.name, args.app, args.role)
        print(message)
        if not ok:
            sys.exit(2)


if __name__ == "__main__":
    main()
