#!/usr/bin/env python3
"""
One desktop, not four. Runs INSIDE the sandbox, once.

Openbox ships with four virtual desktops and binds the mouse wheel over the
desktop to switching between them. So a scroll that misses a window — or
lands on the desktop behind one — silently replaces everything on screen with
an empty workspace. It looks like the apps closed.

That is bad on any machine and worse on this one. The clone's screen is
watched through a video stream by someone who cannot tell a workspace switch
from a crash, every recorded lesson references what is on screen, and a
demonstration that appears to lose its windows mid-sentence is not one you
recover from in front of a judge.

There is no use here for more than one desktop. Everything runs full-attention
in a 1440×900 frame that is deliberately frozen (§20), and nothing in the
project has ever wanted a second workspace.

Writes the clone's own rc.xml from the system default, so an openbox upgrade
does not quietly restore four desktops.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

SYSTEM = Path("/etc/xdg/openbox/rc.xml")
MINE = Path.home() / ".config" / "openbox" / "rc.xml"

# Every mouse binding whose whole purpose is to change desktop. Removed as
# well as reducing the count to one: with a single desktop these are already
# no-ops, but a no-op binding is a thing that starts working again the day
# somebody adds a second desktop for an unrelated reason.
WHEEL = re.compile(
    r"[ \t]*<mousebind[^>]*>\s*"
    r"<action name=\"(?:GoTo|SendTo)Desktop\">.*?</action>\s*"
    r"</mousebind>\s*",
    re.DOTALL)


def main():
    if not SYSTEM.exists():
        sys.exit(f"no system openbox config at {SYSTEM}")
    text = SYSTEM.read_text(encoding="utf-8")

    # Only the count inside <desktops>. A bare search for <number> would also
    # match the one in <margins> and elsewhere.
    def one(match):
        return match.group(0).replace("<number>4</number>", "<number>1</number>")
    text, count = re.subn(r"<desktops>.*?</desktops>", one, text, flags=re.DOTALL)
    if count != 1:
        sys.exit("could not find the <desktops> block — openbox config changed shape")

    text, removed = WHEEL.subn("", text)

    MINE.parent.mkdir(parents=True, exist_ok=True)
    if MINE.exists():
        shutil.copy2(MINE, MINE.with_suffix(".xml.bak"))
    MINE.write_text(text, encoding="utf-8")
    print(f"one desktop; removed {removed} desktop-switching mouse binding(s)")
    print(f"wrote {MINE}")

    # And apply it to the session that is already running. The <desktops>
    # block is read at startup and openbox honours a count already set on the
    # root window over its own config — so with Xvfb still up, restarting the
    # window manager alone changes nothing. Writing the file fixes the next
    # cold start; this fixes now, without disturbing a single open window.
    try:
        subprocess.run(["xdotool", "set_num_desktops", "1"],
                       check=True, capture_output=True, timeout=15)
        now = subprocess.run(["xprop", "-root", "_NET_NUMBER_OF_DESKTOPS"],
                             capture_output=True, text=True, timeout=15).stdout.strip()
        print(f"live session: {now}")
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        print(f"could not change the running session ({type(e).__name__}) — "
              f"it will take effect on the next display restart")


if __name__ == "__main__":
    main()
