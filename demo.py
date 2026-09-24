#!/usr/bin/env python3
"""
SHISHYA — get to a known-good demo state, in one command.

    python demo.py            reset everything and open the panel
    python demo.py check      check without changing anything
    python demo.py rehearse   every claim you are about to make, exercised

Run this before you present. It exists because the failure that cost us most
was invisible: stale websockify processes piling up across restarts until
button releases stopped being delivered and every control in the sandbox went
dead while still looking fine.

This was demo.sh, bash, on a Mac. It is Python now because the machine it runs
on is Windows, and every check it makes was already one of two things: a
question asked inside the sandbox, which goes through the same wsl.exe
wrapper the panel uses, or an HTTP request to localhost, which needs no curl.
Standard library only, like the rest of the host side.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "host"))

import launch         # noqa: E402
import vm             # noqa: E402

PANEL = 8200
MODEL = "http://localhost:11434"

# Colour only on a terminal that will draw it. Windows' console needs virtual
# terminal processing switched on, and os.system("") is the stdlib way to get
# it; the output is UTF-8 whatever the console's code page, because every line
# below has a tick or a cross in it.
if os.name == "nt":
    os.system("")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
_TTY = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def say(text):
    print(_c("36", text))


def ok(text):
    print(f"  {_c('32', '✓')} {text}")


def bad(text):
    print(f"  {_c('31', '✗')} {text}")


def inguest(*argv, timeout=60):
    """stdout of argv run inside the sandbox as root, stripped."""
    try:
        return vm._run(vm.guest(*argv), timeout=timeout).stdout.strip()
    except subprocess.TimeoutExpired:
        return ""


def asclone(script, timeout=60):
    try:
        return vm._run(vm.as_clone(script), timeout=timeout).stdout.strip()
    except subprocess.TimeoutExpired:
        return ""


def get(url, timeout=6, data=None):
    """Body of a GET (or a JSON POST), or None if nothing answered."""
    req = urllib.request.Request(url)
    if data is not None:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"),
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError):
        return None


def _int(text, default=0):
    try:
        return int(text.split()[0])
    except (ValueError, IndexError, AttributeError):
        return default


# ── checks ──────────────────────────────────────────────────────────────────

def check():
    fails = 0

    state = vm.status().get("state")
    if state == "running":
        ok("sandbox running")
    else:
        bad(f"sandbox is {state} — start it from the panel, or: "
            "python -c \"import host.vm as vm; vm.start()\"")
        return 1

    for s in ("dbus", "display", "atspi", "wm", "vnc", "novnc", "desktop"):
        if inguest("systemctl", "is-active", f"shishya-{s}") == "active":
            ok(f"shishya-{s}")
        else:
            bad(f"shishya-{s} is not active"); fails = 1

    # The one that actually bit us. More than one x11vnc means input will die
    # in ways that look like anything else.
    vnc = _int(inguest("pgrep", "-c", "x11vnc"))
    if vnc == 1:
        ok("one x11vnc")
    else:
        bad(f"{vnc} x11vnc processes (want 1)"); fails = 1

    # websockify forks a child per connected client, so a plain count is not
    # the signal. The failure it is really looking for is a child with no
    # connection behind it: an orphan left over from a restart, still bound,
    # still accepting, still swallowing button releases.
    web = _int(inguest("pgrep", "-cf", "websockify --web"), 1)
    live = _int(inguest("bash", "-c", 'ss -tn state established "( sport = :6080 )" '
                                      "| tail -n +2 | wc -l"))
    orphans = web - 1 - live
    if orphans <= 0:
        ok(f"websockify: 1 parent, {live} client(s), no orphans")
    else:
        bad(f"{orphans} orphaned websockify child(ren) — input will die in ways "
            "that look like anything else"); fails = 1

    desks = _int(inguest("pgrep", "-u", "clone", "-cf", "desktop.py"))
    if desks == 1:
        ok("one desktop")
    else:
        bad(f"{desks} desktops (want 1)"); fails = 1

    status = get(f"http://localhost:{PANEL}/api/status", timeout=4)
    if status is not None:
        ok(f"control panel on :{PANEL}")
    else:
        bad("control panel is down"); fails = 1

    # Asked of Windows' localhost, which is where the panel's host side looks.
    # Whether the SANDBOX can reach it is a different question — the gateway,
    # OLLAMA_HOST and the firewall rule — and is asked next.
    tags = get(f"{MODEL}/api/tags")
    if tags is not None:
        ok("model reachable")
    else:
        bad("ollama is not running on Windows"); fails = 1

    reach = asclone("cd /opt/shishya/vm/shell && python3 -c \"import common, "
                    "urllib.request as u; u.urlopen(common.HOST + '/api/tags', "
                    "timeout=5); print('yes')\"", timeout=30)
    if reach.endswith("yes"):
        ok("the sandbox reaches the model through the lock")
    else:
        bad("the sandbox cannot reach the model — run windows\\setup.ps1 "
            "(OLLAMA_HOST and the firewall rule), then restart Ollama"); fails = 1

    try:
        locked = json.loads(status or "{}")["egress"]["locked"]
    except (ValueError, KeyError, TypeError):
        locked = None
    if locked is True:
        ok("egress locked (measured)")
    else:
        bad(f"egress is {locked}")

    # ── the screen has to go quiet when nobody is watching ──────────────────
    # The animated wallpaper repaints all 1440x900 several times a second, and
    # every repaint is a full frame for x11vnc to encode and ship. The desktop
    # watches noVNC's own socket and stops drawing when the last viewer goes.
    # Proved by pixels, not by CPU: two screenshots seconds apart must match.
    viewers = _int(inguest("bash", "-c", 'ss -tn state established "( sport = :6080 )" '
                                         "| grep -c 6080"))
    if viewers == 0:
        # Wait out the end of the minute: the taskbar clock reads %H:%M.
        asclone("while [ $(date +%S) -gt 50 ]; do sleep 1; done; "
                "scrot -o /tmp/still-a.png; sleep 3; scrot -o /tmp/still-b.png",
                timeout=30)
        a = inguest("md5sum", "/tmp/still-a.png").split(" ")[0]
        b = inguest("md5sum", "/tmp/still-b.png").split(" ")[0]
        if a and a == b:
            ok("screen is still with no viewer attached")
        else:
            bad("screen is repainting with nobody watching — the wallpaper gate is off")
            fails = 1
    else:
        ok("a viewer is attached — screen expected to be live")

    vnc_cmd = inguest("bash", "-c",
                      'tr "\\0" " " < /proc/$(pgrep -x x11vnc | head -1)/cmdline')
    if "-noxdamage" in vnc_cmd:
        bad("x11vnc is running with -noxdamage — it is polling the whole screen")
        fails = 1
    else:
        ok("x11vnc is using damage tracking")
    if "-nolookup" in vnc_cmd:
        ok("x11vnc does not wait on DNS to accept a viewer")
    else:
        bad("x11vnc will do a reverse DNS lookup per connect"); fails = 1

    # ── the first question must not pay for loading the model ───────────────
    try:
        resident = len(json.loads(get(f"{MODEL}/api/ps") or "{}").get("models") or [])
    except ValueError:
        resident = 0
    if resident >= 1:
        ok("a model is resident — the next question answers straight away")
    else:
        bad("no model resident: the next question pays the load (run shishya-warm)")

    # Typed, not assumed. An Xvfb can come up with XTEST keyboard injection
    # dead — mouse fine, queries fine, every keystroke silently swallowed.
    # The window title is built at runtime so the probe's own command line
    # never contains it; a pkill that matches the probing shell kills the probe.
    # One line, joined with ; and &: it crosses a Windows command line on
    # its way in, and a newline is the one thing not worth trusting to that.
    typed = asclone('T=probe$$; rm -f /tmp/.keycheck; '
                    'setsid xterm -title "$T" -e sh -c "cat > /tmp/.keycheck" '
                    '</dev/null >/dev/null 2>&1 & '
                    'sleep 3; '
                    'W=$(xdotool search --onlyvisible --name "$T" | head -1); '
                    'eval "$(xdotool getwindowgeometry --shell "$W" 2>/dev/null)"; '
                    'xdotool mousemove $((X+80)) $((Y+60)) click 1 2>/dev/null; '
                    'sleep 1; '
                    'xdotool type ping; xdotool key Return; sleep 1; '
                    'pkill -f "xterm -title $T" 2>/dev/null; cat /tmp/.keycheck 2>/dev/null',
                    timeout=40)
    if typed.endswith("ping"):
        ok("keyboard injection reaches apps")
    else:
        bad("typed keys are not arriving — run python demo.py to rebuild the display")
        fails = 1

    # Is what is running the code that is on disk?
    pid = inguest("pgrep", "-u", "clone", "-f", "shell/desktop.py").split("\n")[0]
    if pid:
        elapsed = _int(inguest("ps", "-o", "etimes=", "-p", pid), -1)
        age = _int(inguest("bash", "-lc", "echo $(( $(date +%s) - $(stat -c %Y "
                                          "/opt/shishya/vm/shell/desktop.py) ))"), -1)
        if elapsed >= 0 and age >= 0 and elapsed > age:
            bad("the desktop is older than desktop.py — new apps will not be in the menu")
            fails = 1
        else:
            ok("the desktop is running current code")

    # Same trap on this side: the panel keeps serving whatever it started with.
    # It reports when it started rather than being asked of `ps`, which is
    # not a question Windows can answer.
    started = _panel_started()
    if started is not None:
        if started >= (ROOT / "serve.py").stat().st_mtime:
            ok("the panel is running current code")
        else:
            bad("the panel is older than serve.py — new routes will 404"); fails = 1

    # One desktop, not openbox's four: a stray scroll would switch workspace.
    nd = asclone("xprop -root _NET_NUMBER_OF_DESKTOPS").rsplit(" ", 1)[-1]
    if nd == "1":
        ok("one desktop (a stray scroll cannot blank the screen)")
    else:
        bad(f"{nd} desktops — scrolling will switch workspace mid-demo"); fails = 1

    # Secrets must be where the sandbox cannot read them, and their values
    # must not have been copied into shared/ by some well-meaning script.
    # By path: `import secrets` is the standard library's module too, and
    # whichever was imported first would win.
    import importlib.util
    spec = importlib.util.spec_from_file_location("host_secrets",
                                                  ROOT / "host" / "secrets.py")
    vault = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vault)
    private, detail = vault.permissions_ok()
    leaks = vault.leaked_into(ROOT / "shared")
    if private and not leaks:
        ok("secrets are private and none reached shared/")
    else:
        bad(f"secrets: {detail} | {','.join(leaks) or 'no leaks'}"); fails = 1

    # The model each job actually uses must exist.
    try:
        wanted = json.loads((ROOT / "shared" / ".models.json")
                            .read_text(encoding="utf-8")).get("code", "")
    except (OSError, ValueError):
        wanted = ""
    if wanted and f'"{wanted}"' in (get(f"{MODEL}/api/tags", timeout=4) or ""):
        ok(f"code job model installed ({wanted})")
    else:
        bad(f"model for the code job ({wanted}) is not in ollama"); fails = 1

    return fails


# serve.py writes this itself when it starts listening, so its age is when
# the running panel started — whoever started it.
PIDFILE = ROOT / "var" / "serve.pid"


def _panel_started():
    try:
        return PIDFILE.stat().st_mtime if get(f"http://localhost:{PANEL}/api/status",
                                              timeout=3) else None
    except OSError:
        return None


# ── reset ───────────────────────────────────────────────────────────────────

def reset():
    if vm.status().get("state") != "running":
        say("Starting the sandbox")
        vm.start()

    say("Resetting the display stack")
    # Order matters, and so does killing the strays: systemctl stop leaves
    # websockify children behind, and those are what break input.
    inguest("systemctl", "stop", "shishya-novnc", "shishya-vnc", "shishya-wm",
            "shishya-display")
    inguest("pkill", "-9", "-f", "websockify")
    inguest("pkill", "-9", "-f", "x11vnc")
    time.sleep(2)
    for s in ("display", "atspi", "wm", "vnc", "novnc"):
        inguest("systemctl", "start", f"shishya-{s}")
        time.sleep(2)

    asclone("python3 /opt/shishya/vm/one-desktop.py")

    say("Restarting the desktop")
    inguest("pkill", "-u", "clone", "-f", "_app.py")
    inguest("systemctl", "restart", "shishya-desktop")
    time.sleep(4)

    say("Restarting the control panel")
    if not launch.start_panel(restart=True):
        bad("the panel did not start — see var/serve.log")

    if not launch.model_up():
        say("Starting Ollama")
        if not launch.start_model():
            bad("Ollama is not running and could not be started")

    say("Locking egress")
    get(f"http://localhost:{PANEL}/api/vm/egress", timeout=60, data={"locked": True})

    print()
    say("Checks")
    fails = check()
    print()
    say(f"Panel: http://localhost:{PANEL}")
    say("Reload the page. Drive from the panel; do not click inside the sandbox.")
    return fails


# ── rehearsal ───────────────────────────────────────────────────────────────
# Every claim you are about to make, exercised, before an audience exists.

def rehearse():
    fails = 0

    def claim(what, good, why=""):
        nonlocal fails
        if good:
            ok(what)
        else:
            bad(f"{what} — {why}" if why else what); fails = 1

    say("Rehearsing the claims")

    answer = get(f"{MODEL}/api/generate", timeout=90,
                 data={"model": "gpt-oss:latest", "prompt": "say READY",
                       "stream": False}) or ""
    claim("the model answers at all", "ready" in answer.lower())

    code = asclone('curl -s -o /dev/null -w "%{http_code}" -m 6 https://github.com',
                   timeout=30)
    claim("the sandbox cannot reach the internet", code.endswith("000"),
          f"github answered {code}")

    # The WSL-specific holes, each tested rather than trusted to wsl.conf.
    name = asclone('getent hosts github.com >/dev/null && echo resolved || echo blocked',
                   timeout=30)
    claim("the sandbox cannot resolve names either", name.endswith("blocked"),
          "DNS answers while locked — WSL's DNS tunnel is not being dropped")

    nosudo = vm._run(vm.guest("sudo", "-u", "clone", "sudo", "-n", "true"),
                     timeout=30)
    claim("the clone has no sudo", nosudo.returncode != 0)

    drives = asclone("ls /mnt/c >/dev/null 2>&1 && echo visible || echo hidden",
                     timeout=30)
    claim("Windows' drives are invisible from inside", drives.endswith("hidden"),
          "/mnt/c is mounted — automount is on")

    # Asked of the kernel, not of PATH: with interop on, WSL registers a
    # binfmt handler that runs any Windows executable it is handed.
    interop = asclone("grep -qsx enabled /proc/sys/fs/binfmt_misc/WSLInterop* "
                      "&& echo ran || echo refused", timeout=30)
    claim("the sandbox cannot start Windows programs", interop.endswith("refused"),
          "interop is on")

    claim("the shop's books are readable",
          (ROOT / "shared" / "billing" / "catalogue.csv").stat().st_size > 0)

    plan = get(f"http://localhost:{PANEL}/api/lesson/plan", timeout=90,
               data={"lesson": "20260821-124956"}) or ""
    claim("a lesson can be planned", '"doable"' in plan)

    audit = get(f"http://localhost:{PANEL}/api/audit", timeout=30, data={}) or ""
    claim("the audit runs and finds the shop", '"job"' in audit)

    ledger = ROOT / "var" / "ledger.jsonl"
    claim("the ledger is being written", ledger.exists() and ledger.stat().st_size > 0)

    probe = get(f"http://localhost:{PANEL}/api/job/file?job=../../var&name=ledger.jsonl",
                timeout=10) or ""
    claim("a produced file cannot be used to reach outside shared/",
          "not a job id" in probe)

    print()
    if fails == 0:
        say("Every claim stands. The audit is running now — watch it land in the panel.")
    else:
        bad("Something you were going to claim does not hold. Fix it before the call.")
    return fails


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "reset"
    if what == "check":
        say("Checking")
        sys.exit(check())
    if what == "rehearse":
        sys.exit(check() or (print() or rehearse()))
    sys.exit(reset())
