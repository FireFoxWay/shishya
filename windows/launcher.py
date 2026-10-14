"""
Shishya.exe — the whole Windows build is this file plus a folder.

    Shishya\\
        Shishya.exe        this, frozen by PyInstaller
        payload\\app\\       the project, as committed
        payload\\runtime\\   Python, Windows' embeddable build — nothing to install

Double-clicking it:

  1. copies the payload to %LOCALAPPDATA%\\shishya\\ when it is new or newer.
     The sandbox mounts the project folder, so the project must live
     somewhere that stays put — not on a Desktop that OneDrive may sync, or a
     folder somebody moves next week. Your work in shared\\ is never
     overwritten; only files that are missing are filled in.
  2. starts the control panel with that Python, no console window, and
     opens the browser — onto the setup page until everything is ready.

Deliberately small and standard library only: the frozen exe carries only
what this file imports, and everything else runs on the full embeddable
Python next to it, where nothing can be missing.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
PAYLOAD = HERE / "payload"
HOME = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "shishya"
NO_WINDOW = 0x08000000
DETACHED = 0x00000008 | 0x00000200          # DETACHED_PROCESS | NEW_PROCESS_GROUP


def message(text, error=True):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Shishya", 0x10 if error else 0x40)
    except Exception:                                     # noqa: BLE001
        print(text)


def version(folder):
    try:
        return (folder / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def stop_running_panel():
    """A panel running from the old copy holds runtime\\pythonw.exe open, and
    Windows will not replace a running program. Stopped before the update."""
    try:
        pid = int((HOME / "app" / "var" / "serve.pid").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True, creationflags=NO_WINDOW)
    time.sleep(1)


def sync_runtime():
    src, dst = PAYLOAD / "runtime", HOME / "runtime"
    if version(src) and version(src) == version(dst):
        return False
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return True


def sync_app():
    """Code is replaced; shared\\ and var\\ are the person's, and are kept."""
    src, dst = PAYLOAD / "app", HOME / "app"
    if version(src) and version(src) == version(dst):
        return False
    dst.mkdir(parents=True, exist_ok=True)
    keep = {"shared", "var"}
    for item in dst.iterdir():
        if item.name in keep:
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    for item in src.iterdir():
        if item.name in keep:
            continue
        target = dst / item.name
        shutil.copytree(item, target) if item.is_dir() else shutil.copy2(item, target)
    # Seed data: filled in where missing, never written over.
    for f in (src / "shared").rglob("*"):
        rel = f.relative_to(src / "shared")
        target = dst / "shared" / rel
        if f.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
    return True


def main():
    if not (PAYLOAD / "app").is_dir() or not (PAYLOAD / "runtime").is_dir():
        message("Shishya.exe needs the 'payload' folder that came beside it.\n\n"
                "Keep the whole Shishya folder together — move the folder, "
                "not just the .exe. To put it on the Start menu or taskbar, "
                "right-click Shishya.exe and pin it.")
        return 1

    HOME.mkdir(parents=True, exist_ok=True)
    newer = (version(PAYLOAD / "app") != version(HOME / "app")
             or version(PAYLOAD / "runtime") != version(HOME / "runtime"))
    if newer:
        stop_running_panel()
    try:
        sync_runtime()
        sync_app()
    except OSError as e:
        message(f"Shishya could not copy its files into {HOME}.\n\n{e}\n\n"
                "Close any open Shishya windows and try again.")
        return 1

    python = HOME / "runtime" / "pythonw.exe"
    script = HOME / "app" / "host" / "launch.py"
    args = [str(python), "-X", "utf8", str(script), "gui"] + (["--restart"] if newer else [])
    try:
        subprocess.Popen(args, cwd=HOME / "app", stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=DETACHED | NO_WINDOW)
    except OSError as e:
        message(f"Shishya could not start.\n\n{e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
