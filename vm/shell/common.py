#!/usr/bin/env python3
"""
Shishya — shared bits for the apps that run on the clone's desktop.

Two jobs: talk to the model on the host, and turn any file the user drops in
into plain text.
"""

import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path.home()
SHARED = HOME / "shared"
WORK = SHARED / "work"
LESSONS = SHARED / "lessons"
TRAINING = SHARED / "training"
TRACES = SHARED / "traces"
STATE = SHARED / ".state"

# The model runs on the host's GPU and is reached across the sandbox
# boundary. Inside the VM it would fall back to emulated CPU and be far too
# slow to demo.
HOST = "http://host.lima.internal:11434"
MODEL = "deepseek-r1:8b"

ACCENT = "#0078d4"


def set_state(state):
    """What the taskbar pill shows: idle | working | wheel | needs."""
    try:
        SHARED.mkdir(parents=True, exist_ok=True)
        STATE.write_text(state)
    except OSError:
        pass


def ask(prompt, system=None, schema=None, timeout=600):
    body = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2, "num_ctx": 8192, "num_predict": 2048},
    }
    if system:
        body["system"] = system
    if schema:
        body["format"] = schema
    req = urllib.request.Request(f"{HOST}/api/generate", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _strip_think(json.loads(r.read())["response"])
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"can't reach the model on the host ({e}). If the egress lock is "
            f"on, {HOST} is the one address it should still allow."
        )



def _strip_think(text):
    """deepseek-r1 emits <think>...</think> even with think disabled, and the
    reasoning is not the answer — showing it to a user reads as the thing
    malfunctioning. An unclosed tag means the reply was truncated mid-thought,
    so there is no answer to salvage."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return re.sub(r"^.*?<think>.*$", "", text, flags=re.S).strip() or text.strip()

# ─── any document → text ────────────────────────────────────────────────────
# "Any type" in practice means: read it if we can, and say so plainly if we
# can't. A file that silently contributes nothing is worse than one that
# reports itself as unreadable.

PLAIN = {".txt", ".md", ".csv", ".tsv", ".json", ".log", ".py", ".xml", ".html"}
OFFICE = {".odt", ".ods", ".odp", ".docx", ".xlsx", ".pptx", ".doc", ".rtf"}


def extract(path):
    """Returns (text, how). `how` is shown in the UI so the user can see the
    route a file took — and spot when a PDF came back empty because it was
    a scan rather than text."""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in PLAIN:
        return path.read_text(encoding="utf-8", errors="replace"), "read as text"

    if suffix == ".pdf":
        out = _run(["pdftotext", "-layout", str(path), "-"])
        if out.strip():
            return out, "extracted with pdftotext"
        return "", "PDF has no text layer — it is probably a scan, and OCR is not installed"

    if suffix in OFFICE:
        out = _run(["libreoffice", "--headless", "--cat", str(path)], timeout=120)
        if out.strip():
            return out, "converted with LibreOffice"
        return "", "LibreOffice could not read this"

    # Unknown extension: if it looks like text, treat it as text.
    try:
        raw = path.read_bytes()[:200_000]
        if b"\x00" not in raw[:2000]:
            return raw.decode("utf-8", errors="replace"), f"unknown type {suffix}, read as text"
    except OSError:
        pass
    return "", f"can't read {suffix or 'this file'}"


def _run(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def chunk(text, size=1400, overlap=180):
    """Overlapping windows so a fact sitting on a boundary is not cut in half."""
    text = " ".join(text.split())
    if len(text) <= size:
        return [text] if text else []
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return out
