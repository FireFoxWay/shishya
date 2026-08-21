#!/usr/bin/env python3
"""
Silence LibreOffice's welcome dialogs. Runs INSIDE the sandbox, once.

A first-run banner and a Tip of the Day sitting over the spreadsheet is a bad
look in front of an audience, and worse for the clone: both are modal, so a
recorded lesson would capture someone dismissing dialogs rather than doing the
job, and a replayed lesson would stall against a dialog that only appears the
first time.

The settings live in the user profile as registry items, so this edits the
profile rather than passing flags — flags would have to be remembered at every
launch, including the ones the clone makes for itself.
"""

import re
import sys
from pathlib import Path

PROFILE = Path.home() / ".config" / "libreoffice" / "4" / "user"
XCU = PROFILE / "registrymodifications.xcu"

QUIET = [
    ("org.openoffice.Office.Common/Misc", "FirstRun", "false"),
    ("org.openoffice.Office.Common/Misc", "ShowTipOfTheDay", "false"),
    ("org.openoffice.Office.Common/Help", "ShowTip", "false"),
    ("org.openoffice.Setup/Product", "ooSetupVersionAboutBox", "24.2"),
    # Recovery is worse than useless here. The sandbox gets torn down and
    # rolled back constantly, so LibreOffice sees a crash every time and
    # opens a recovery dialog in front of whatever was meant to be on screen.
    ("org.openoffice.Office.Recovery/AutoSave", "Enabled", "false"),
    ("org.openoffice.Office.Recovery/RecoveryInfo", "Enabled", "false"),
]

ITEM = ('<item oor:path="/{path}"><prop oor:name="{name}" oor:op="fuse">'
        '<value>{value}</value></prop></item>')


def clear_recovery():
    """Drop any pending recovery session.

    Killing soffice — which we do on every reset — leaves crash state behind,
    and the next launch offers to recover instead of opening the file it was
    asked for.
    """
    for name in ("recovery", "backup"):
        target = PROFILE / name
        if target.is_dir():
            for child in target.iterdir():
                try:
                    child.unlink()
                except OSError:
                    pass


def main():
    clear_recovery()
    if not XCU.exists():
        sys.exit(f"no profile at {XCU} — start LibreOffice once first")
    text = XCU.read_text(encoding="utf-8")

    added = 0
    for path, name, value in QUIET:
        # Already set (to anything) — leave it alone rather than fighting the
        # user's own preference.
        if re.search(rf'oor:path="/{re.escape(path)}"[^>]*>\s*<prop oor:name="{name}"', text):
            continue
        text = text.replace("</oor:items>",
                            ITEM.format(path=path, name=name, value=value) + "</oor:items>")
        added += 1

    XCU.write_text(text, encoding="utf-8")
    print(f"  quieted {added} setting(s)")


if __name__ == "__main__":
    main()
