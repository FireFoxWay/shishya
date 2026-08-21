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
import subprocess
import sys

import pyatspi

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


def _walk(node, app_name, wanted, role, visible_only, hits, depth=0):
    if node is None or depth > 14:
        return
    try:
        count = node.childCount
        node_name = node.name or ""
        node_role = node.getRoleName()
    except Exception:
        return

    if node_name and wanted in node_name.lower():
        if (role is None or role == node_role) and node_role in CLICKABLE:
            point = _point(node, visible_only)
            if point:
                hits.append({
                    "name": node_name, "role": node_role, "app": app_name,
                    "x": point[0], "y": point[1], "w": point[2], "h": point[3],
                    "exact": node_name.lower() == wanted,
                })

    for i in range(count):
        try:
            _walk(node[i], app_name, wanted, role, visible_only, hits, depth + 1)
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
