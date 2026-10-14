#!/usr/bin/env python3
"""
Bring Shishya up and open it — the one command.

    shishya run          panel, model, sandbox, browser, in that order
    shishya stop         the sandbox and the panel, not the model

Everything here was already done somewhere: demo.py restarted the panel and
started Ollama, the panel's Start button started the sandbox. What was missing
was one thing a person types that does all of it and ends with the page open,
so that is all this is. Each step checks before it acts, so running it twice
opens the page twice and changes nothing else.

Order matters. The panel comes first because it is the thing that reports on
everything else — if the sandbox then fails to start, the page is already
there saying so, instead of a terminal full of text nobody is reading.
"""

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "host"))

import vm             # noqa: E402

PORT = int(os.environ.get("SHISHYA_PORT", "8200"))
PANEL = f"http://localhost:{PORT}"
MODEL = "http://localhost:11434"
PIDFILE = ROOT / "var" / "serve.pid"      # written by serve.py itself


def _up(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError):
        return False


def _wait(url, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if _up(url, timeout=2):
            return True
        time.sleep(1)
    return False


def panel_up():
    # /api/ping, not /api/status: status asks WSL, and a WSL that is slow to
    # answer — common right after it is installed — made a perfectly healthy
    # panel look dead, and Shishya.exe said it could not start.
    return _up(f"{PANEL}/api/ping")


def _kill(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, creationflags=vm._NO_WINDOW)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def _port_holder():
    """The process listening on the panel's port, if it is a Shishya panel.

    A panel started some other way — `shishya run` from a git checkout, an
    older Shishya.exe — has its pid file somewhere else, holds the port, and
    the new panel cannot bind it. Only a serve.py is ever stopped this way:
    whatever else is on the port is somebody else's, and is reported instead.
    """
    if os.name != "nt":
        return None
    ps = (f"$c = Get-NetTCPConnection -LocalPort {PORT} -State Listen -ErrorAction SilentlyContinue | "
          "Select-Object -First 1; if ($c) { $p = Get-CimInstance Win32_Process "
          "-Filter \"ProcessId=$($c.OwningProcess)\"; \"$($c.OwningProcess)|$($p.CommandLine)\" }")
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=20,
                             creationflags=vm._NO_WINDOW).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    pid, _, cmd = out.partition("|")
    return (int(pid), cmd) if pid.isdigit() else None


def stop_panel():
    stopped = False
    try:
        _kill(int(PIDFILE.read_text(encoding="utf-8").strip()))
        stopped = True
    except (OSError, ValueError):
        pass
    PIDFILE.unlink(missing_ok=True)
    holder = _port_holder()
    if holder and "serve.py" in holder[1]:
        _kill(holder[0])
        stopped = True
    if stopped:
        time.sleep(1)
    return stopped


def start_panel(restart=False):
    """serve.py, detached, logging to var/serve.log. True once it answers."""
    if panel_up() and not restart:
        return True
    stop_panel()
    (ROOT / "var").mkdir(exist_ok=True)
    # pythonw on Windows where there is one: no console window left open for
    # a server nobody needs to look at. The log is where its output goes.
    exe = Path(sys.executable)
    quiet = exe.with_name("pythonw.exe")
    python = str(quiet if os.name == "nt" and quiet.exists() else exe)
    with open(ROOT / "var" / "serve.log", "ab") as log:
        # -X utf8 and PYTHONUTF8 as well as serve.py's own fix: everything the
        # panel starts in turn inherits them.
        subprocess.Popen([python, "-X", "utf8", str(ROOT / "serve.py"), str(PORT)],
                         cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"),
                         stdin=subprocess.DEVNULL, stdout=log,
                         stderr=subprocess.STDOUT,
                         creationflags=vm._DETACHED | vm._NO_WINDOW,
                         start_new_session=os.name != "nt")
    if _wait(f"{PANEL}/api/ping", 45):
        return True
    holder = _port_holder()
    if holder:
        with open(ROOT / "var" / "serve.log", "a", encoding="utf-8") as log:
            log.write(f"\nport {PORT} is held by another program: pid {holder[0]} "
                      f"{holder[1]}\n")
    return False


def model_up():
    return _up(f"{MODEL}/api/tags")


def start_model():
    """Ollama is an app, and apps quit. Started the way its installer does."""
    if model_up():
        return True
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"
    for exe in (local / "ollama app.exe", local / "ollama.exe"):
        if exe.exists():
            vm._spawn([str(exe)] + (["serve"] if exe.name == "ollama.exe" else []))
            return _wait(f"{MODEL}/api/tags", 60)
    return False


def sandbox_reaches_model():
    """Asked from inside, through the lock, the way the apps will ask."""
    try:
        p = vm._run(vm.as_clone(
            "cd /opt/shishya/vm/shell && python3 -c \"import common, "
            "urllib.request as u; u.urlopen(common.HOST + '/api/tags', "
            "timeout=5); print('yes')\""), timeout=40)
        return p.stdout.strip().endswith("yes")
    except (subprocess.SubprocessError, OSError):
        return False


def elevated_setup():
    """windows\\setup.ps1 as administrator — one UAC prompt, and waited for."""
    if os.name != "nt":
        return False
    script = ROOT / "windows" / "setup.ps1"
    p = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList "
         f"'-NoProfile','-ExecutionPolicy','Bypass','-File','\"{script}\"'"],
        creationflags=vm._NO_WINDOW)
    return p.returncode == 0


def run(say=print, open_browser=True):
    """The whole thing. Returns 0 when the page opened onto a working panel."""
    say("Starting the control panel …")
    if not start_panel():
        say(f"  the panel did not start — see {ROOT / 'var' / 'serve.log'}")
        return 1
    say(f"  {PANEL}")

    say("Starting the model …")
    say("  Ollama is answering" if start_model() else
        "  Ollama is not running and could not be started — install it from "
        "https://ollama.com/download; the apps answer through it")

    st = vm.status()
    state = st.get("state")
    if state == "wsl-busy":
        say(st["detail"])
    elif state == "no-wsl":
        say("The sandbox needs WSL — run windows\\setup.ps1 as administrator, once.")
    elif state == "absent":
        say("There is no sandbox yet. Create it once (slow — it downloads Ubuntu):")
        say("  shishya create")
    elif state != "running":
        say("Starting the sandbox … (up to a minute)")
        try:
            vm.start()
            say("  running, network locked")
        except (vm.VMError, subprocess.SubprocessError, OSError) as e:
            say(f"  it did not start: {e}")
    else:
        say("The sandbox is already running")

    if open_browser:
        webbrowser.open(PANEL)
    say(f"Open: {PANEL}")
    return 0


def create(say=print, open_browser=True):
    """First-time sandbox build, then everything else."""
    st = vm.status()
    state = st.get("state")
    if state == "no-wsl":
        say("WSL is not installed — run windows\\setup.ps1 as administrator, "
            "restart Windows, then try again.")
        return 1
    if state == "wsl-busy":
        say(st["detail"])
        return 1
    # Absent, or left half-built by an earlier attempt: both are finished here.
    if state == "absent" or not vm._provisioned():
        say("Creating the sandbox. This downloads Ubuntu and installs the desktop")
        say("inside it — expect 15 to 30 minutes, once. Leave this window open.")
        try:
            vm.create(say)
        except (vm.VMError, subprocess.SubprocessError, OSError) as e:
            say(f"  failed: {e}")
            say("  Run `shishya create` again to carry on from where it stopped.")
            return 1
        # The firewall rule is scoped to WSL's network adapter, which does not
        # exist until a WSL 2 distribution has booted — so on a fresh machine
        # setup.ps1 could not add it the first time. Now it can.
        if start_model() and not sandbox_reaches_model():
            say("  the sandbox cannot reach the model yet — finishing the firewall")
            say("  rule (one administrator prompt) …")
            elevated_setup()
            say("  the model is reachable from the sandbox" if sandbox_reaches_model()
                else "  still unreachable — restart Ollama from the tray, then "
                     "python demo.py check")
        say("  done. Taking the clean snapshot the undo button returns to …")
        vm.snapshot(vm.CLEAN_TAG)
    return run(say, open_browser=open_browser)


def stop(say=print):
    if vm.status().get("state") == "running":
        say("Stopping the sandbox …")
        vm.stop()
    if stop_panel():
        say("Stopped the control panel")
    say("Stopped. Ollama is left running; quit it from the tray if you want.")
    return 0


def gui(restart=False):
    """What Shishya.exe runs. No terminal: everything is on a page.

    The panel first, then the browser — onto the setup page until the sandbox
    is built, onto the panel after. A built sandbox that is stopped is started
    here, after the page is already open and saying so.
    """
    if not start_panel(restart=restart):
        # The end of the log, in the box itself: a screenshot of this should
        # be enough to say what went wrong, without opening any file.
        try:
            tail = (ROOT / "var" / "serve.log").read_text(
                encoding="utf-8", errors="replace").strip().splitlines()[-12:]
        except OSError:
            tail = ["(the log is empty — the panel never started)"]
        _message("Shishya could not start its control panel.\n\n"
                 + "\n".join(line[:160] for line in tail)
                 + f"\n\nFull log: {ROOT / 'var' / 'serve.log'}")
        return 1
    start_model()
    import setup_flow
    st = setup_flow.state()
    page = "/" if st["ready"] else "/setup.html"
    webbrowser.open(PANEL + page)
    # Built but stopped: start it, with the page open and polling.
    steps = {x["id"]: x for x in st["steps"]}
    if steps["create"]["ok"] and not steps["start"]["ok"]:
        try:
            vm.start()
        except Exception:                                 # noqa: BLE001
            pass                  # the setup page shows the Start button
    return 0


def _message(text):
    """A Windows message box — the only way to say something without a
    console window."""
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Shishya", 0x10)
    else:
        print(text)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "run"
    if what == "gui":
        sys.exit(gui(restart="--restart" in sys.argv))
    sys.exit({"run": run, "create": create, "stop": stop}.get(what, run)())
