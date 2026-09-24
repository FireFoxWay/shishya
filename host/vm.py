#!/usr/bin/env python3
"""
Shishya — host-side control of the clone's sandbox, on Windows.

The sandbox is a WSL2 distribution of its own, called `shishya`, and this is
a thin wrapper over `wsl.exe`. Everything the control panel can do to it goes
through here so that every state change lands in the ledger, including the
ones that happen from the command line.

It used to be Lima on a Mac. What carried over unchanged is everything inside
the guest — the same Ubuntu 24.04, the same systemd units, the same display
stack, recorder and executor. What changed is the wrapper around it, and the
three things Lima gave for free that WSL has to be told:

  the boundary   WSL mounts every Windows drive at /mnt/c and lets the guest
                 run Windows programs. Both are switched off in vm/wsl.conf,
                 and the only two folders the clone can see are named in
                 vm/fstab — the same two lima.yaml used to name.
  the host       there is no host.lima.internal. The model is reached at the
                 guest's default gateway, which WSL's NAT points at Windows.
  staying up     a WSL distribution stops a few seconds after its last
                 wsl.exe session ends, systemd or not. start() leaves one
                 session holding it open, and stop() is what ends it.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "shishya"
WSL = "wsl.exe"

# The templates for the boundary. Both carry __SHISHYA_ROOT__, filled in with
# this checkout's own path when the sandbox is created.
WSL_CONF = ROOT / "vm" / "wsl.conf"
FSTAB = ROOT / "vm" / "fstab"

# The clone's uid is fixed because the shared folder is mounted with it, and
# /etc/fstab is read at boot — before the account exists on the first one.
CLONE_UID = 1500

# Where the sandbox's disk lives. Deliberately NOT under the repository: the
# whole checkout is mounted into the guest at /opt/shishya, and a disk image
# of the sandbox — snapshots included — is not something the clone should be
# able to read, even of itself.
STATE = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "shishya"
DISK_DIR = STATE / "disk"
DISK = DISK_DIR / "ext4.vhdx"
SNAPS = STATE / "snapshots"

# Canonical's WSL image of the same release the Mac build ran. The checksum
# is fetched beside it and checked: this file becomes a whole machine.
IMAGES = "https://cloud-images.ubuntu.com/wsl/releases/24.04/current/"

# The tag we roll back to. Taken once, immediately after provisioning, before
# the clone has ever run — so "undo" always means "the way it was".
CLEAN_TAG = "clean"

# No console window flashing up for every poll. Zero off Windows, where none
# of this runs anyway but the module still has to import (doctor, tests).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DETACHED = (getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


class VMError(RuntimeError):
    pass


def _env():
    # wsl.exe writes its own messages in UTF-16 unless told otherwise, and
    # `wsl -l` read as UTF-8 comes back with a NUL between every letter.
    return dict(os.environ, WSL_UTF8="1")


def _run(cmd, timeout=180, input=None):
    """One wsl.exe call. UTF-8 named, never the locale's: the guest prints
    rupee signs, and Windows' default is cp1252."""
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, input=input,
                          env=_env(), creationflags=_NO_WINDOW)


def _wsl(*args, timeout=180, check=True):
    cmd = [WSL, *args]
    p = _run(cmd, timeout=timeout)
    if check and p.returncode != 0:
        raise VMError(f"{' '.join(cmd)}\n{p.stderr.strip() or p.stdout.strip()}")
    return p.stdout.strip()


def guest(*argv, user="root"):
    """The command line that runs argv inside the sandbox.

    --exec, not the default shell: without it wsl.exe hands the arguments to
    a Linux shell that parses them a second time, and a script that was
    quoted correctly once is not quoted correctly twice.
    """
    return [WSL, "-d", NAME, "-u", user, "--cd", "/", "--exec", *argv]


def as_clone(script):
    """A login shell as the clone, with the desktop's environment loaded."""
    return guest("sudo", "-u", "clone", "bash", "-lc",
                 f"set -a; . /etc/shishya.env; set +a; {script}")


def _spawn(cmd):
    """Start something that must outlive this call, and this process."""
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env=_env(), creationflags=_DETACHED | _NO_WINDOW,
                            start_new_session=os.name != "nt")


def status():
    """Everything the control panel needs to paint its header, in one call."""
    try:
        p = _run([WSL, "--list", "--verbose"], timeout=30)
    except FileNotFoundError:
        return {"state": "no-wsl", "detail": "WSL is not installed"}

    # "  NAME      STATE     VERSION" then one row per distribution, the
    # default one marked with a star. No distributions at all is a non-zero
    # exit with a sentence instead of a table, which parses to "absent".
    for line in p.stdout.replace("\x00", "").splitlines()[1:]:
        cols = line.replace("*", " ").split()
        if len(cols) >= 3 and cols[0] == NAME:
            return {"state": cols[1].lower(), "wsl": cols[2],
                    "dir": str(DISK_DIR)}
    return {"state": "absent"}


def _require_running():
    # wsl.exe starts a stopped distribution to run a command in it, and one
    # started that way has no session holding it up and no egress re-check —
    # it boots, answers, and stops again ten seconds later. So a stopped
    # sandbox is refused here, the way `limactl shell` used to refuse.
    if status().get("state") != "running":
        raise VMError("the sandbox is not running — press Start first")


def _in_guest(cmd, timeout=120, input=None):
    _require_running()
    return _run(cmd, timeout=timeout, input=input)


def _put(path, text):
    """Write one file inside the sandbox, as root.

    Bytes, not text: a text-mode pipe on Windows turns every \\n into \\r\\n,
    and a wsl.conf or fstab with carriage returns in it is read wrongly
    rather than rejected.
    """
    p = subprocess.run(guest("sh", "-c", f"cat > {path}"),
                       input=text.replace("\r\n", "\n").encode("utf-8"),
                       capture_output=True, timeout=60, env=_env(),
                       creationflags=_NO_WINDOW)
    if p.returncode != 0:
        raise VMError(f"could not write {path}: "
                      f"{p.stderr.decode('utf-8', 'replace').strip()}")


def _drvfs(path):
    """A Windows path as /etc/fstab wants it: forward slashes, and a space
    written as \\040, because a space is the field separator."""
    text = Path(path).as_posix()
    if text.startswith("//"):
        raise VMError("the checkout is on a network share; put it on a local "
                      "drive — drvfs cannot mount a UNC path from fstab")
    return text.replace(" ", "\\040")


def resolved_boundary():
    """vm/wsl.conf and vm/fstab with this checkout's own path filled in.

    The mount list IS the security boundary, and on the Mac it used to name
    one developer's home directory in full — correct for exactly one laptop.
    Both files are templates; the resolved copies are written to var/ so the
    boundary this machine actually got can be read back, and are what gets
    installed into the guest.
    """
    out = ROOT / "var"
    out.mkdir(parents=True, exist_ok=True)
    root = _drvfs(ROOT)
    resolved = {}
    for src, name in ((WSL_CONF, "wsl.conf"), (FSTAB, "fstab")):
        text = (src.read_text(encoding="utf-8")
                .replace("__SHISHYA_ROOT__", root)
                .replace("__CLONE_UID__", str(CLONE_UID)))
        (out / name).write_text(text, encoding="utf-8")
        resolved[name] = text
    return resolved


def _image(say=print):
    """The Ubuntu rootfs, downloaded once and checked against its SHA256SUMS."""
    arch = {"amd64": "amd64", "x86_64": "amd64",
            "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
    if not arch:
        raise VMError(f"no Ubuntu WSL image for {platform.machine()}")
    name = f"ubuntu-noble-wsl-{arch}-wsl.rootfs.tar.gz"
    local = STATE / name
    STATE.mkdir(parents=True, exist_ok=True)

    with urllib.request.urlopen(IMAGES + "SHA256SUMS", timeout=60) as r:
        sums = r.read().decode("utf-8")
    want = next((ln.split()[0] for ln in sums.splitlines()
                 if ln.strip().endswith(name)), None)
    if not want:
        raise VMError(f"{name} is not listed in {IMAGES}SHA256SUMS")

    def digest():
        h = hashlib.sha256()
        with open(local, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()

    if local.exists() and digest() == want:
        say("  Ubuntu image already downloaded")
        return local

    part = local.with_suffix(".part")
    with urllib.request.urlopen(IMAGES + name, timeout=60) as r, \
            open(part, "wb") as fh:
        total = int(r.headers.get("Content-Length") or 0)
        got, shown = 0, -1
        while True:
            block = r.read(1 << 20)
            if not block:
                break
            fh.write(block)
            got += len(block)
            # A line every 10%, not a bar: this also goes to the panel's log
            # and to terminals that cannot redraw a line.
            pct = got * 100 // total if total else -1
            if pct >= 0 and pct // 10 != shown:
                shown = pct // 10
                say(f"  downloading Ubuntu … {pct}% of {total / 1e6:.0f} MB")
    part.replace(local)
    if digest() != want:
        local.unlink(missing_ok=True)
        raise VMError(f"{name} does not match its published checksum")
    return local


def _provisioned():
    return _run(guest("test", "-f", "/var/lib/shishya-provisioned"),
                timeout=60).returncode == 0


def create(say=print):
    """First boot. Slow — downloads Ubuntu, then provisions the desktop.

    The order is the point. The boundary (wsl.conf, fstab) is written into
    the image before it has ever booted as itself, and the distribution is
    restarted before anything of ours runs in it — so no provisioning step
    ever executes in a guest that can see C:\\ or start a Windows program.

    Resumable. A first build is twenty minutes of downloading, and a dropped
    connection halfway used to leave a sandbox that existed, was not
    provisioned, and could not be created again. Run it again and it picks up
    after the import.
    """
    state = status()["state"]
    if state == "no-wsl":
        raise VMError("WSL is not installed — run windows\\setup.ps1 once, "
                      "as administrator")

    if state == "absent":
        say("Step 1 of 4: the Ubuntu image")
        image = _image(say)
        boundary = resolved_boundary()
        say("Step 2 of 4: importing it into WSL, and closing off C:\\ …")
        DISK_DIR.mkdir(parents=True, exist_ok=True)
        _wsl("--import", NAME, str(DISK_DIR), str(image), "--version", "2",
             timeout=1800)
        _put("/etc/wsl.conf", boundary["wsl.conf"])
        _put("/etc/fstab", boundary["fstab"])
        _run(guest("mkdir", "-p", "/opt/shishya", "/home/clone/shared"), timeout=60)
        _wsl("--terminate", NAME, check=False)
    else:
        if _provisioned():
            raise VMError(f"sandbox {NAME!r} already exists and is built — "
                          "use `shishya run`")
        say("The sandbox exists but was never finished — carrying on from there.")

    say("Step 3 of 4: first boot")
    start(relock=False)

    # The project folder has to be visible inside, or there is nothing to
    # provision with. Checked here so a mount problem is named as one.
    if _run(guest("test", "-f", "/opt/shishya/vm/provision.sh"),
            timeout=60).returncode != 0:
        why = _run(guest("bash", "-lc", "mount -a 2>&1; cat /etc/fstab | grep -v '^#'"),
                   timeout=60)
        raise VMError("the project folder is not mounted inside the sandbox.\n"
                      + (why.stdout + why.stderr).strip()[-800:])

    p = _run(guest("bash", "-lc",
                   f"id clone >/dev/null 2>&1 || useradd -m -u {CLONE_UID} "
                   f"-s /bin/bash clone"), timeout=60)
    if p.returncode != 0:
        raise VMError(f"could not create the clone's account: {p.stderr.strip()}")

    # Provisioning mounts nothing and reaches nothing the boundary does not
    # allow; it only needs the network, for apt. The lock goes on at the end.
    # Streamed to var/provision.log, with its latest line repeated here every
    # half minute: fifteen silent minutes look exactly like a hang.
    say("Step 4 of 4: installing the desktop inside (15 to 25 minutes) …")
    log_path = ROOT / "var" / "provision.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(
            guest("bash", "-lc",
                  "[ -f /var/lib/shishya-provisioned ] || "
                  "{ bash /opt/shishya/vm/provision.sh && "
                  "touch /var/lib/shishya-provisioned; }"),
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            env=_env(), creationflags=_NO_WINDOW)
        started, last = time.time(), ""
        while proc.poll() is None:
            time.sleep(30)
            try:
                tail = log_path.read_bytes()[-4000:].decode("utf-8", "replace")
                line = next((ln.strip() for ln in reversed(tail.splitlines())
                             if ln.strip() and not ln.startswith("+")), "")
            except OSError:
                line = ""
            if line and line != last:
                last = line
                say(f"  [{int(time.time() - started) // 60} min] {line[:100]}")
    if proc.returncode != 0:
        tail = log_path.read_bytes()[-1500:].decode("utf-8", "replace")
        raise VMError(f"provisioning failed — the full log is {log_path}\n{tail}")
    egress(True)
    return status()


def _keepalive():
    """Hold the distribution up.

    Checked before it is started, so pressing Start twice does not leave two
    of them. pgrep is exec'd directly rather than through a shell, because a
    shell's own command line would contain the pattern and match itself.
    """
    p = _run(guest("pgrep", "-f", "shishya-keepalive"), timeout=60)
    if p.returncode == 0:
        return
    _spawn(guest("bash", "-c", "exec -a shishya-keepalive sleep infinity"))


def start(relock=True):
    state = status()["state"]
    if state in ("absent", "no-wsl"):
        raise VMError("there is no sandbox yet — create it first")
    fresh = state != "running"
    _keepalive()
    # Booted is not ready: the display, the desktop and the egress unit are
    # systemd's, and a panel that reports "running" before they are up shows
    # a black screen and calls it a sandbox.
    try:
        _run(guest("systemctl", "is-system-running", "--wait"), timeout=180)
    except subprocess.TimeoutExpired:
        pass          # "degraded" or slow; the panel's own checks say which
    if fresh and relock:
        # egress.sh ran at boot; run it again now that the network is
        # certainly up, so the host's exception names the right gateway.
        egress(True)
    return status()


def stop():
    # Ends every session into the distribution, the keep-alive included.
    _wsl("--terminate", NAME, timeout=120)
    for _ in range(30):
        if status().get("state") != "running":
            break
        time.sleep(1)
    _forget_rules()
    return status()


def shell(script, user="clone", timeout=120):
    """Run something inside the VM as the clone (never as root)."""
    p = _in_guest(guest("sudo", "-u", user, "bash", "-lc", script), timeout=timeout)
    return {"code": p.returncode, "out": p.stdout, "err": p.stderr}


def launch_app(name):
    """Start one of the sandbox's apps, as the clone, on its display.

    setsid and a closed stdin matter: without them the process stays attached
    to this wsl.exe session and dies with it, or holds the pipe open and hangs
    the caller. Both have bitten us.
    """
    _require_running()
    _spawn(as_clone("cd /opt/shishya/vm/shell && "
                    f"setsid python3 {name} </dev/null >/tmp/{name}.log 2>&1 & disown"))
    return {"launched": name}


SHARED = Path(__file__).resolve().parent.parent / "shared"


def use_as_sources():
    """Move everything waiting in the inbox into the material folder.

    Dropping a file on the panel puts it in the inbox, which is deliberately
    a holding area — nothing there is read until somebody says so. This is
    that decision, made from outside the sandbox so it works when clicking
    inside it does not. The chat notices the folder changed and reads them.
    """
    inbox, training = SHARED / "inbox", SHARED / "training"
    training.mkdir(parents=True, exist_ok=True)
    moved = []
    if inbox.exists():
        for p in sorted(inbox.iterdir()):
            if p.is_file() and not p.name.startswith(".") and p.suffix != ".part":
                p.replace(training / p.name)
                moved.append(p.name)
    return {"added": moved}


def close_apps(name=None):
    """Close one app, or all of them, from outside the sandbox.

    Closing a window normally means clicking its X, which needs the display
    input path — the one thing that keeps failing. This does not touch the
    display at all.
    """
    target = name if name else "_app.py"
    _in_guest(guest("pkill", "-f", target), timeout=60)
    time.sleep(1)
    left = _run(guest("bash", "-lc", "pgrep -u clone -f '_app.py' | wc -l"),
                timeout=30).stdout.strip()
    return {"closed": target, "still_open": left}


def drive(action, text=""):
    """Type into the sandbox's apps through the accessibility layer.

    Same reason as close_apps: this reaches the widgets directly rather than
    going through the pointer, so it works on the evenings when clicking
    inside the sandbox does not.
    """
    args = ["ask", text] if action == "ask" else ["read"]
    import shlex
    p = _in_guest(as_clone("cd /opt/shishya/vm && timeout 300 python3 drive.py "
                           + " ".join(shlex.quote(a) for a in args)),
                  timeout=320)
    return {"result": (p.stdout or p.stderr).strip()}


def run_command(command, timeout=45):
    """Run a shell command inside the sandbox, as the clone.

    The panel controls the OS; the OS controls what lives inside it. So this
    reaches into the sandbox and nowhere else — never Windows. It runs as
    `clone`, which has no sudo, inside a VM whose network is off and whose
    disk is one rollback from clean. A mistyped command here costs you the
    sandbox at worst, and the sandbox is designed to be thrown away.

    Not a real terminal: no pty, no persistent shell, so no interactive
    programs and no cd that survives to the next command. It is for looking
    at things, which is what it is actually wanted for.
    """
    p = _in_guest(guest("sudo", "-u", "clone", "bash", "-lc",
                        f"cd /home/clone 2>/dev/null; {command}"),
                  timeout=timeout)
    out = (p.stdout or "").rstrip()
    err = (p.stderr or "").rstrip()
    return {"code": p.returncode, "out": out[-8000:], "err": err[-4000:]}


# ─── Lessons ────────────────────────────────────────────────────────────────
# A procedure learned by demonstration, performed on request. The executor
# lives inside the sandbox because that is where the display and the
# accessibility bus are; everything out here is plumbing and a stop button.

TRACES = SHARED / "traces"
GUEST_TRACES = "/home/clone/shared/traces"

# The id names a directory that is interpolated into a shell command running
# inside the sandbox. Checked against a character class *and* against the
# filesystem, for the same reason the app launcher takes a choice from a menu
# rather than a path: this endpoint runs a program on someone else's machine.
LESSON_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_running = None      # the executor process, so a run can be stopped


def lessons():
    """Every procedure that has been learned, newest first.

    Read from the host's own copy of shared/ rather than asked of the guest.
    It is the same directory through virtiofs, and the panel should still be
    able to list what it knows when the sandbox is down.
    """
    out = []
    # By when it was taught, not by name. The directories are usually
    # timestamps and sort correctly by accident, but one called "test-synth"
    # sorted to the top of a list that claims to be newest first.
    found = sorted(TRACES.glob("*/procedure.json"),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    for path in found:
        try:
            proc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue          # never let one unreadable lesson hide the rest
        out.append({
            "id": path.parent.name,
            "title": proc.get("title") or path.parent.name,
            "steps": len(proc.get("steps", [])),
            "edited": bool(proc.get("edited_by_hand")),
            "taught": time.strftime("%d %b %H:%M", time.localtime(path.stat().st_mtime)),
        })
    return out


def _lesson_dir(lesson_id):
    if not LESSON_ID.match(lesson_id or ""):
        raise VMError(f"not a lesson id: {lesson_id!r}")
    if not (TRACES / lesson_id / "procedure.json").exists():
        raise VMError(f"no lesson called {lesson_id!r}")
    return f"{GUEST_TRACES}/{lesson_id}"


def _executor(lesson_id, *flags):
    _require_running()
    return as_clone("cd /opt/shishya/vm && "
                    f"python3 executor.py {_lesson_dir(lesson_id)} {' '.join(flags)}")


def _as_json(line):
    """One event, or None. A login shell prints things; this is not the place
    to find that out, so anything that is not an object is simply not one."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        return json.loads(line)
    except ValueError:
        return None


def lesson_plan(lesson_id):
    """What it would do, without doing any of it. Cheap — no display work,
    just the procedure read back through the same code that performs it."""
    p = _run(_executor(lesson_id, "--json"), timeout=90)
    for line in reversed((p.stdout or "").splitlines()):
        event = _as_json(line)
        if event:
            return event
    raise VMError((p.stderr or p.stdout).strip()[-400:] or
                  "the executor produced no plan")


def lesson_run(lesson_id, on_event, ask=True):
    """Perform a lesson, reporting each step as it lands.

    Streamed rather than collected. A seventeen-step procedure takes minutes,
    and a panel that shows nothing until it finishes is a panel you cannot
    stop in time — which matters more here than anywhere else on this
    machine, because this is the one control that types into real files.
    """
    global _running
    noise = []
    flags = ["--run", "--json"] + (["--ask"] if ask else [])
    proc = subprocess.Popen(_executor(lesson_id, *flags),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            bufsize=1, env=_env(), creationflags=_NO_WINDOW)
    _running = proc
    try:
        for line in proc.stdout:
            event = _as_json(line)
            if event:
                on_event(event)
            elif line.strip():
                # Whatever the executor said that was not an event — a
                # traceback from inside the sandbox, usually. Kept so a run
                # that dies can say why instead of just stopping.
                noise.append(line.rstrip())
                del noise[:-12]
        code = proc.wait(timeout=30)
    finally:
        _running = None

    # -15 is the Stop button below. That is not a failure worth reporting.
    if code not in (0, -15):
        on_event({"kind": "error", "ok": False,
                  "message": "\n".join(noise) or f"the executor exited {code}"})
    return code


def lesson_stop():
    """Halt a run in progress.

    Two kills, because one is not enough: the local end, and the executor
    inside the sandbox. Terminating wsl.exe ends the Windows end of the
    session, and whether that reaches the process on the far side is not something to
    discover while the clone is typing into somebody's spreadsheet.
    """
    proc = _running
    was_running = proc is not None and proc.poll() is None
    if proc is not None:
        proc.terminate()
    if status().get("state") == "running":
        _run(guest("pkill", "-f", "executor.py"), timeout=60)
    return {"stopped": was_running,
            "detail": "stopped" if was_running else "nothing was running"}


# ─── The schedule ───────────────────────────────────────────────────────────
# Runs that happen without anybody pressing anything. Written by the Reports
# app inside the sandbox, read by the panel out here — the shared mount is the
# one channel between them, and a JSON file both can read beats inventing a
# protocol for four fields.

SCHEDULES = SHARED / ".schedules.json"
ROLE = SHARED / ".role"
ALERTS = SHARED / ".alerts.json"


def role():
    """clerk or head. Clerk when unset — the safer assumption of the two."""
    try:
        found = ROLE.read_text(encoding="utf-8").strip().lower()
        return found if found in ("clerk", "head") else "clerk"
    except OSError:
        return "clerk"


def set_role(who):
    who = (who or "").strip().lower()
    if who not in ("clerk", "head"):
        raise VMError(f"no such role: {who!r}")
    SHARED.mkdir(parents=True, exist_ok=True)
    ROLE.write_text(who, encoding="utf-8")
    return {"role": who}


# ─── Approvals ──────────────────────────────────────────────────────────────
# The clerk asks, the head decides. Read here the same way the schedule is:
# the shared mount is the channel, and the file is the protocol.

APPROVALS = SHARED / "approvals.json"
PENDING = "pending"


def read_approvals():
    try:
        found = json.loads(APPROVALS.read_text(encoding="utf-8"))
        return found if isinstance(found, list) else []
    except (OSError, ValueError):
        return []


def _write_approvals(rows):
    SHARED.mkdir(parents=True, exist_ok=True)
    tmp = APPROVALS.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(APPROVALS)


def pending_approvals():
    """Open requests, oldest first — somebody is waiting at a counter."""
    now = time.time()
    live = [r for r in read_approvals()
            if r.get("state") == PENDING and now - r.get("at", 0) < 24 * 3600]
    return sorted(live, key=lambda r: r.get("at", 0))


def decide_approval(request_id, approved, note=""):
    """Record the head's decision. Returns the request, or None if it is not
    open — deciding twice would perform the action twice, and the second
    time would look exactly as legitimate as the first."""
    rows = read_approvals()
    for r in rows:
        if r.get("id") != request_id:
            continue
        if r.get("state") != PENDING:
            return None
        r["state"] = "approved" if approved else "refused"
        r["decided_at"] = time.time()
        r["note"] = note
        _write_approvals(rows)
        return r
    return None


def alerts():
    """What the shop should know, as last written by the alert check."""
    try:
        return json.loads(ALERTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"alerts": [], "at": None}


def _model_for(job):
    """Which model the sandbox would use for this job — read from the same
    file the apps read, so a report names the model that actually answered."""
    try:
        return json.loads((SHARED / ".models.json").read_text(encoding="utf-8")).get(job, "?")
    except (OSError, ValueError):
        return "?"


def read_schedules():
    try:
        found = json.loads(SCHEDULES.read_text(encoding="utf-8"))
        return found if isinstance(found, list) else []
    except (OSError, ValueError):
        return []          # no schedule is a valid state, not an error


def write_schedules(items):
    SHARED.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULES.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SCHEDULES)          # whole file, renamed — never half a schedule


def due(item, now=None):
    """Is this schedule due, and has today's run not already happened?

    Compared against the wall clock rather than counted from the last run, so
    a laptop that was asleep at six does not fire four times when it wakes —
    it fires once, late, which is what a person would expect.
    """
    if not item.get("enabled", True):
        return False
    now = now or time.localtime()
    if item.get("days") == "weekdays" and now.tm_wday >= 5:
        return False
    today = time.strftime("%Y-%m-%d", now)
    if item.get("last") == today:
        return False
    try:
        hour, minute = (int(part) for part in str(item.get("at", "")).split(":"))
    except ValueError:
        return False
    return (now.tm_hour, now.tm_min) >= (hour, minute)


# ─── Jobs ───────────────────────────────────────────────────────────────────
# The work-order flow: files dropped on the panel, one line saying what to do
# with them, and the deliverable comes back as files. Same shape as lessons —
# the host does plumbing, the sandbox does the work, and state is read from a
# file rather than remembered from the last time we asked.

JOBS = SHARED / "jobs"
GUEST_JOBS = "/home/clone/shared/jobs"
JOB_ID = re.compile(r"^[0-9]{8}-[0-9]{6}$")


def start_job(brief, runner="worker.py", take_inbox=True):
    """Move whatever is waiting in the inbox into a fresh job and start a
    runner on it. Files first, then job.json, then the runner — the order
    matters, because the runner starts by reading job.json and the inputs
    must already be in place when it looks.

    Two runners share this plumbing: worker.py does what the brief says and
    the deliverable is whatever it produces; reporter.py ignores free text
    and builds the fixed-shape report — averages, trends, ends — because a
    report's shape is not the model's to improvise."""
    assert runner in ("worker.py", "reporter.py", "tally.py", "audit.py",
                      "backup.py", "alerts.py")
    # Refuse up front when the sandbox is down. Without this the files were
    # moved, the worker was launched into a stopped VM, and the panel showed
    # "handing the files over" forever — a confident wrong answer, the kind
    # this panel exists to never give.
    if status().get("state") != "running":
        raise VMError("the sandbox is not running — press Start first")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    job = JOBS / stamp
    (job / "in").mkdir(parents=True)
    (job / "out").mkdir()

    # A scheduled run takes nothing. It reads the shop's own books, and
    # emptying the inbox at six in the evening would steal the files somebody
    # staged that afternoon for a job they had not started yet.
    inbox = SHARED / "inbox"
    handed = []
    if take_inbox and inbox.exists():
        for f in sorted(inbox.iterdir()):
            if f.is_file() and not f.name.startswith(".") and f.suffix != ".part":
                f.replace(job / "in" / f.name)
                handed.append(f.name)

    # Provenance, recorded by the side that can actually check it. The clone
    # has no sudo and cannot ask nftables anything, so a report claiming "the
    # network was locked" would be the sandbox vouching for itself. This is
    # the host's statement, written before the work starts, and the runner
    # only quotes it. Today's egress bug is exactly why it exists: the panel
    # read LOCKED for two hours while the web was open, and no deliverable
    # made in that window recorded which it was.
    try:
        net = egress_state()
    except Exception:
        net = {"locked": None, "detail": "could not be checked"}
    (job / "job.json").write_text(json.dumps(
        {"brief": brief, "files": handed, "at": time.time(),
         "egress": net, "model": _model_for("code")}, ensure_ascii=False), encoding="utf-8")

    # Same launch shape as launch_app: setsid, stdin closed, disowned —
    # the worker must outlive this wsl.exe session.
    _spawn(as_clone("cd /opt/shishya/vm && "
                    f"setsid python3 {runner} {GUEST_JOBS}/{stamp} "
                    f"</dev/null >/tmp/worker-{stamp}.log 2>&1 & disown"))
    return {"job": stamp, "files": handed}


def job_state(job_id=None):
    """The newest job (or a named one), read from its own status file.

    Read host-side over the shared mount — no shell into the sandbox, so the
    panel's poll stays cheap and keeps answering even mid-job."""
    if job_id is None:
        runs = sorted(JOBS.glob("*/job.json")) if JOBS.exists() else []
        if not runs:
            return {"state": "none"}
        job = max((r.parent for r in runs), key=lambda d: d.name)
    else:
        if not JOB_ID.match(job_id or ""):
            raise VMError(f"not a job id: {job_id!r}")
        job = JOBS / job_id
        if not job.exists():
            raise VMError(f"no job called {job_id!r}")

    out = {"job": job.name, "state": "starting", "step": "handing the files over"}
    try:
        out.update(json.loads((job / "job.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    try:
        out.update(json.loads((job / "status.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass          # the worker has not written yet — "starting" stands
    try:
        out["produced"] = sorted(
            f.name for f in (job / "out").iterdir()
            if f.is_file() and not f.name.startswith("."))
    except OSError:
        out["produced"] = []
    return out


def job_file(job_id, name):
    """Absolute path of one produced file, or raise. The two checks mirror
    the launch list: an id that matches the pattern AND exists, a bare
    filename that is really inside out/ — this endpoint hands bytes to a
    browser and must never be steerable to any other file on this computer."""
    if not JOB_ID.match(job_id or ""):
        raise VMError(f"not a job id: {job_id!r}")
    safe = Path(name or "").name
    path = (JOBS / job_id / "out" / safe).resolve()
    if not str(path).startswith(str((JOBS / job_id / "out").resolve())) \
            or not path.is_file():
        raise VMError(f"no such file {safe!r} in job {job_id}")
    return path


# ─── Taking things back off the clone ───────────────────────────────────────
# Files go in by being dropped on the panel; this is the way out. Everything
# the clone makes already lives on Windows — shared/ is a drvfs mount, so
# a report it wrote this morning is physically on this disk — but it is
# buried in the project folder, and "it is already there, in a path you have
# never opened" is not a feature anybody can use.
#
# So the panel browses what the clone produced and hands a copy to the
# browser, which saves it wherever the person keeps their files.
#
# Only what the clone was given to work with. The mount list is the security
# model in the other direction and it is the security model in this one too:
# a browser asking for a path is asking a program running on Windows, and
# that program will only ever look inside shared/.

TAKEABLE = {
    "work":    (SHARED / "work",     "what the clone has made"),
    "billing": (SHARED / "billing",  "the shop's books"),
    "traces":  (SHARED / "traces",   "recorded lessons"),
    "inbox":   (SHARED / "inbox",    "waiting to be read"),
}

# Never handed out, whatever is asked for. A half-written file read as
# complete is the upload bug in reverse, and the .before-gst copies are a
# migration's safety net rather than something to circulate.
HIDDEN = (".part", ".tmp")


def _inside(root, relative):
    """Resolve a browser-supplied path inside one root, or raise.

    resolve() then a prefix test, because "../" is only the obvious attempt:
    a symlink inside shared/ pointing at C:\\Users would pass
    any string check and fail this one.
    """
    root = root.resolve()
    target = (root / (relative or "")).resolve()
    if target != root and root not in target.parents:
        raise VMError("that path is not inside the folder")
    return target


def take_list(where="work", relative=""):
    """One folder of what the clone has produced, folders first."""
    if where not in TAKEABLE:
        raise VMError(f"cannot browse {where!r}")
    root, what = TAKEABLE[where]
    target = _inside(root, relative)
    if not target.is_dir():
        raise VMError("that is not a folder")

    folders, files = [], []
    for item in sorted(target.iterdir(), key=lambda i: i.name.lower()):
        if item.name.startswith("."):
            continue
        rel = str(item.relative_to(root))
        if item.is_dir():
            folders.append({"name": item.name, "path": rel, "dir": True})
        elif not item.name.endswith(HIDDEN):
            stat = item.stat()
            files.append({"name": item.name, "path": rel, "dir": False,
                          "bytes": stat.st_size,
                          "at": time.strftime("%d %b %H:%M",
                                              time.localtime(stat.st_mtime))})
    return {"where": where, "what": what, "at": relative,
            "up": str(Path(relative).parent) if relative not in ("", ".") else None,
            "items": folders + files}


def take_file(where, relative):
    """Absolute path of one file to hand back, or raise."""
    if where not in TAKEABLE:
        raise VMError(f"cannot take from {where!r}")
    root, _ = TAKEABLE[where]
    target = _inside(root, relative)
    if not target.is_file() or target.name.startswith(".") \
            or target.name.endswith(HIDDEN):
        raise VMError("no such file")
    return target


def reset_display():
    """Rebuild the path between your eyes and the sandbox.

    Two demo-day failures came through here: stale websockify children
    swallowing button releases, so every control in the sandbox went dead
    while still looking fine — windows still raised, tooltips still showed,
    and nothing worked. It looks like a frozen app and is not one.

    This now re-runs vm/display.sh rather than just bouncing the two services,
    which means it also *applies* the display configuration rather than
    restarting whatever the machine happened to be provisioned with. The
    services were defined inline in provision.sh, and provision.sh runs once
    per machine — so changing one flag on x11vnc used to mean rebuilding the
    VM. Now this button carries the change.

    Without --all, so the X server and the window manager are left alone: the
    clone's open apps and documents survive. Only the video path is rebuilt.
    """
    p = _in_guest(guest("bash", "/opt/shishya/vm/display.sh"), timeout=180)
    if p.returncode != 0:
        # Fall back to the old behaviour rather than leaving the screen down:
        # a machine provisioned before display.sh existed has no such file,
        # and "your screen is broken and so is the fix" is the worst outcome.
        for step in (["systemctl", "stop", "shishya-novnc", "shishya-vnc"],
                     ["pkill", "-9", "-f", "websockify"],
                     ["pkill", "-9", "-x", "x11vnc"],
                     ["systemctl", "start", "shishya-vnc"],
                     ["systemctl", "start", "shishya-novnc"]):
            _run(guest(*step), timeout=60)
            time.sleep(1)

    check = _run(guest("bash", "-lc",
                       'echo "$(pgrep -c x11vnc) $(pgrep -cf \'websockify --web\')"'),
                 timeout=30).stdout.split()
    return {"x11vnc": check[0] if check else "?",
            "websockify": check[1] if len(check) > 1 else "?",
            "tuned": p.returncode == 0,
            "note": "reload the page, then press TAKE THE WHEEL"}


# ─── The undo button ────────────────────────────────────────────────────────
# The sandbox's whole disk is one file, ext4.vhdx, in a folder we chose when
# the distribution was imported. A snapshot is a copy of that file taken while
# the distribution is stopped; a rollback copies it back over the live one.
# WSL keeps pointing at the same path, so nothing needs re-registering.
#
# Not `wsl --export`: that writes a tar of the filesystem and rolling back
# from it means unregistering and re-importing — a new distribution in all
# but name, with the chance of losing the old one halfway through.
#
# Not instant either, and it is worth saying so rather than letting the old
# "4 milliseconds" line survive the port. The Mac cloned the disk on APFS,
# copy-on-write. NTFS has no such thing; this is a real copy of however much
# of the disk is in use — a few GB after provisioning, tens of seconds. On a
# Dev Drive (ReFS) Windows may block-clone it and it is much faster.
#
# The VM is stopped around both operations. Copying a running disk would give
# a crash-consistent image — survivable, but "your undo button sometimes
# replays a dirty filesystem" is not a sentence you want to say to a judge.

SNAP_TAG = re.compile(r"^[A-Za-z0-9._-]{1,40}$")


def _snap(tag):
    # The tag arrives from the panel and names a file; same rule as a lesson.
    if not SNAP_TAG.match(tag or "") or tag.startswith("."):
        raise VMError(f"not a snapshot tag: {tag!r}")
    return SNAPS / f"{tag}.vhdx"


def _clone(src, dst):
    """Copy the disk, to a .part first so a half-copied disk is never taken
    for a whole one. Retried briefly: WSL can hold the file for a moment
    after the distribution reports stopped."""
    part = dst.with_name(dst.name + ".part")
    for attempt in range(20):
        try:
            shutil.copyfile(src, part)
            break
        except PermissionError:
            if attempt == 19:
                raise VMError(f"{src} is still in use — is the sandbox stopped?")
            time.sleep(1)
    part.replace(dst)


def snapshot(tag=CLEAN_TAG):
    target = _snap(tag)
    if not DISK.exists():
        raise VMError(f"no sandbox disk at {DISK} — create the sandbox first")
    was_running = status().get("state") == "running"
    if was_running:
        stop()
    SNAPS.mkdir(parents=True, exist_ok=True)
    try:
        _clone(DISK, target)
    finally:
        if was_running:
            start()
            _relock_if_needed()
    return {"tag": tag, "at": time.time(), "bytes": target.stat().st_size}


def _relock_if_needed():
    """Re-apply the egress lock after anything that restarts the VM.

    nftables rules live in memory, so a stop/start silently drops them. The
    indicator then correctly reports OPEN — which is honest, and is exactly
    the wrong thing to discover mid-demonstration. Anything that cycles the
    VM re-applies the lock itself.
    """
    try:
        if not egress_state().get("locked"):
            egress(True)
    except Exception:
        pass


def rollback(tag=CLEAN_TAG):
    src = _snap(tag)
    if not src.exists():
        raise VMError(f"no snapshot tagged {tag!r} — mark one clean first")
    was_running = status().get("state") == "running"
    if was_running:
        stop()
    try:
        _clone(src, DISK)
    finally:
        if was_running:
            start()
            _relock_if_needed()
    return {"tag": tag, "at": time.time(), "snapshot_taken": _snapshot_age(tag)}


def _snapshot_age(tag=CLEAN_TAG):
    """When the snapshot was taken, so a rollback is not a leap in the dark."""
    path = _snap(tag)
    if not path.exists():
        return None
    return time.strftime("%d %b %H:%M", time.localtime(path.stat().st_mtime))


def snapshots():
    if not SNAPS.exists():
        return []
    return sorted(p.stem for p in SNAPS.glob("*.vhdx"))


# ─── The network kill switch ────────────────────────────────────────────────
# The demo claim is "nothing left this laptop". We make that true rather than
# promising it: drop all egress except the host's Ollama. Applied inside the
# guest, so the clone cannot lift it — it has no sudo.

# The rules themselves live in one place, vm/egress.sh, and every state is a
# mode of it: locked, web, ssh. They used to be written out here three times
# with a fixed host address, and in egress.sh a fourth, "kept in step" by a
# comment. Under WSL the host's address is the guest's default gateway and
# changes when Windows restarts, so it is looked up by the script at the
# moment the rules are applied, never remembered.
OLLAMA_PORT = 11434
EGRESS = "/opt/shishya/vm/egress.sh"


def _apply(mode):
    p = _in_guest(guest("bash", EGRESS, mode), timeout=60)
    _forget_rules()
    if p.returncode != 0:
        raise VMError(p.stderr.strip() or p.stdout.strip())


# One read of the firewall, cached for a moment.
#
# The control panel asks for status every three seconds, and status used to
# call egress_state() and browsing_state() back to back — two guest
# invocations, each a session into the guest running the same `sudo nft
# list table` and parsing the same output for different words. Measured at
# 0.23s apiece, that is half a second of ssh-and-sudo inside the sandbox
# every three seconds, for as long as the panel is open, competing for the
# same four cores as the screen the panel is showing you.
#
# Now it is read once and both answers come off the one read. The short cache
# is not about the cost of the call — it is about a burst of it: a page
# refresh fires status, browsing and egress within the same tick.
#
# TTL is deliberately short, and every path that CHANGES the rules clears it
# by hand. This is the indicator whose lying was the worst bug this project
# has had; it may be a second stale, never wrong.
_RULES = {"at": 0.0, "text": None, "ok": False}
_RULES_TTL = 2.0


def _rules(fresh=False):
    """The guest's nftables table, as text. (ok, text)."""
    now = time.time()
    if not fresh and _RULES["text"] is not None and now - _RULES["at"] < _RULES_TTL:
        return _RULES["ok"], _RULES["text"]
    p = _run(guest("nft", "list", "table", "inet", "shishya"), timeout=30)
    _RULES.update(at=now, text=p.stdout, ok=p.returncode == 0)
    return _RULES["ok"], _RULES["text"]


def _forget_rules():
    """Call after anything that changes the firewall, so the next read is real."""
    _RULES.update(at=0.0, text=None, ok=False)


def egress_state(fresh=False):
    """What the lock actually is, right now — asked of the guest, not
    remembered from the last time we set it.

    The panel used to display LOCKED because a variable said so. On a project
    whose entire claim is that you can verify what happened, an indicator
    reporting a state it never checked is the worst possible bug: it is the
    one thing a judge might actually test.
    """
    ok, text = _rules(fresh)
    if not ok:
        # No such table means no rules, which means nothing is being blocked.
        return {"locked": False, "detail": "no egress rules are loaded"}

    dropping = "policy drop" in text
    # Browsing mode is ALSO policy drop — with the web punched through it.
    # Testing only for the policy was the bug: the panel read LOCKED for two
    # hours while the sandbox could reach github, because both states share
    # that line. Locked has to mean what it says: the model, and nothing else.
    web = "dport { 80, 443 }" in text or "dport 80" in text
    if not dropping:
        return {"locked": False, "detail": "rules present but not dropping"}
    if web:
        return {"locked": False,
                "detail": "browsing is on — the web is reachable from the sandbox"}
    return {"locked": True,
            "detail": "all outbound traffic dropped except the host's model"}


def browsing(on: bool):
    """Open the network for the web, and nothing else.

    A browser needs DNS and 80/443. It does not need the sandbox to be able
    to reach everything, which is what the plain unlock does. This is a third
    state between locked and open: the clone can fetch a page and still
    cannot be told to talk to an arbitrary host on an arbitrary port.

    Deliberately a mode you switch on rather than a permanent exception. The
    claim was never "this can never reach the internet" — it is "it cannot
    unless you say so, and when you do it is in the log."
    """
    if not on:
        return egress(True)
    _apply("web")
    return browsing_state(fresh=True)


def set_browsing(on: bool):
    """Grant or revoke browsing, and tell the sandbox which it is.

    Refuses when Windows itself has no network: a browser that opens onto
    connection errors looks broken, and the honest message is that there is
    nothing to reach.
    """
    if on and not host_online():
        return {"browsing": False,
                "detail": "this computer is not on a network — there is nothing to browse"}
    result = browsing(on)
    flag = SHARED / ".browsing"
    try:
        SHARED.mkdir(parents=True, exist_ok=True)
        flag.write_text("on" if on and result.get("browsing") else "off", encoding="utf-8")
    except OSError:
        pass
    return result


def ssh_out(on: bool):
    """Let the sandbox open SSH connections, and nothing else new.

    A third state alongside browsing, for the same reason: the claim was never
    "this can never reach the network", it is "it cannot unless you say so,
    and when you do it is in the log". Browsing opens 80 and 443. This opens
    22. Neither opens the other.

    Worth being plain about the cost. With this on, the sandbox can reach a
    machine you own and, through it, whatever that machine can reach. That is
    what SSH is for and it is also the whole of the risk — so it is a switch
    somebody throws deliberately, per session, with the ledger recording it.
    """
    if not on:
        return egress(True)
    _apply("ssh")
    return ssh_state(fresh=True)


def ssh_state(fresh=False):
    """Measured from the guest, like every other claim about the lock."""
    ok, text = _rules(fresh)
    if not ok:
        return {"ssh": False, "detail": "no rules loaded — the sandbox is wide open"}
    out = "dport 22" in text
    return {"ssh": out,
            "detail": "the sandbox can open SSH connections" if out
                      else "SSH out of the sandbox is blocked"}


def ssh_run(row, command, timeout=45):
    """Run one command on a saved host, from inside the sandbox.

    From inside deliberately. Doing it on Windows would be simpler and would
    also mean the panel reaching onto your real network from outside the box
    that is supposed to contain everything, which is the one thing this
    project argues against.

    Not a terminal: no pty, so no interactive programs, no password prompt
    (BatchMode is on), and no `cd` that survives to the next command. The same
    shape as run_command, and honest about it for the same reason.
    """
    import shlex

    import hosts
    if not ssh_state()["ssh"]:
        return {"code": -1, "out": "",
                "err": "SSH out of the sandbox is switched off. Turn it on "
                       "first — it is a deliberate hole in the egress lock, "
                       "and switching it on is recorded in the ledger."}
    remote = " ".join(shlex.quote(a) for a in hosts.target(row))
    p = _in_guest(guest("sudo", "-u", "clone", "bash", "-lc",
                        f"{remote} {shlex.quote(command)}"),
                  timeout=timeout)
    return {"code": p.returncode,
            "out": (p.stdout or "").rstrip()[-8000:],
            "err": (p.stderr or "").rstrip()[-4000:]}


def browsing_state(fresh=False):
    """Measured, like everything else about the lock — off the same one read
    of the table that egress_state() uses, rather than a second session
    asking the identical question."""
    ok, text = _rules(fresh)
    if not ok:
        return {"browsing": False, "detail": "no rules loaded — the sandbox is wide open"}
    web = "dport { 80, 443 }" in text or "dport 80" in text
    return {"browsing": web,
            "detail": "the web is reachable" if web else "the web is blocked"}


def host_online():
    """Is this machine on a network at all? The browser is useless otherwise,
    and saying so plainly beats a page of connection errors.

    Asked with a socket rather than `route -n get default`, which is BSD and
    answered only on macOS — on Linux or Windows that call raised or returned
    nothing, and browsing was refused on a machine that was perfectly online.
    Opening a UDP socket toward a public address assigns a local route without
    sending a packet, which is the same question in a portable form.
    """
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(2)
            sock.connect(("1.1.1.1", 53))
            return True
    except OSError:
        return False


def egress(locked: bool):
    if locked:
        _apply("locked")
    else:
        p = _in_guest(guest("nft", "flush", "ruleset"), timeout=60)
        _forget_rules()
        if p.returncode != 0:
            raise VMError(p.stderr.strip())
    # Report what the guest now says, not what we asked for — and force the
    # read, because we have just made whatever is cached wrong.
    return egress_state(fresh=True)


if __name__ == "__main__":
    fn = sys.argv[1] if len(sys.argv) > 1 else "status"
    print(json.dumps(globals()[fn](*sys.argv[2:]), indent=2, default=str))
