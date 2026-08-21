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
MODEL = "deepseek-r1:8b"          # the fallback when nothing is chosen

# ─── one job, one model ─────────────────────────────────────────────────────
# Different work wants different models, and a school should not have to hold
# twenty gigabytes on disk to answer a question about an attendance policy.
# Each job names a model; the Models app writes this file and the apps read it.
ROLES = SHARED / ".models.json"


def model_for(job):
    """Which model does this job. Falls back rather than failing — a missing
    or malformed file must never stop the app from answering."""
    try:
        import json as _json
        chosen = _json.loads(ROLES.read_text()).get(job)
        if chosen:
            return chosen
    except (OSError, ValueError):
        pass
    return MODEL

ACCENT = "#0078d4"


def set_state(state):
    """What the taskbar pill shows: idle | working | wheel | needs."""
    try:
        SHARED.mkdir(parents=True, exist_ok=True)
        STATE.write_text(state)
    except OSError:
        pass


def ask_job(job, prompt, **kw):
    """ask(), told which job it is for, so the right model answers."""
    return ask(prompt, job=job, **kw)


def ask(prompt, system=None, schema=None, timeout=600, budget=None, job=None):
    body = {
        "model": model_for(job) if job else MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2, "num_ctx": 8192, "num_predict": 2048},
    }
    if system:
        body["system"] = system
    if schema:
        body["format"] = schema
    def once(budget):
        body["options"]["num_predict"] = budget
        req = urllib.request.Request(f"{HOST}/api/generate", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _strip_think(json.loads(r.read())["response"])

    if budget:
        # Code needs more room than prose: the model reasons first, and a
        # script that stops halfway is worse than no script.
        body["options"]["num_predict"] = budget
    try:
        answer = once(body["options"]["num_predict"])
        if not answer:
            # It thought until it ran out of room. Once more, with more room.
            answer = once(body["options"]["num_predict"] * 2)
        return answer or ("I ran out of room working that out. Ask me something "
                          "narrower and I'll get there.")
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"can't reach the model on the host ({e}). If the egress lock is "
            f"on, {HOST} is the one address it should still allow."
        )



def _strip_think(text):
    """Remove the model's reasoning, or report that there was no answer.

    deepseek-r1 emits <think>...</think> even with thinking disabled. If it
    spends its whole token budget reasoning the block is never closed, and
    there is no answer in the reply at all — the earlier version fell back to
    returning the raw text, so the user saw the reasoning presented as the
    answer. Returning empty lets the caller retry with more room instead.
    """
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    if "<think>" in text:
        return ""                     # opened and never closed: truncated
    return text


PLAIN = {".txt", ".md", ".csv", ".tsv", ".json", ".log", ".py", ".xml", ".html"}

# Read Office files with the libraries that understand them rather than by
# shelling out to LibreOffice. `--headless --cat` silently produces nothing
# for spreadsheets, so an .xlsx a person can plainly open came back as
# "LibreOffice could not read this". These libraries are already installed
# for writing documents; using them to read is faster, needs no subprocess,
# and cannot be wedged by a LibreOffice instance that is already running.
NATIVE = {".xlsx": "sheet", ".xlsm": "sheet", ".docx": "doc", ".pptx": "deck"}

# Older and OpenDocument formats still need LibreOffice, converting to a
# format we can read rather than asking it to print to stdout.
CONVERT = {".odt", ".ods", ".odp", ".doc", ".xls", ".ppt", ".rtf"}


def extract(path):
    """Returns (text, how). `how` is shown in the UI so the route a file took
    is visible — and so an empty result explains itself rather than looking
    like the file was ignored."""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in PLAIN:
        return path.read_text(encoding="utf-8", errors="replace"), "read as text"

    if suffix == ".pdf":
        out = _run(["pdftotext", "-layout", str(path), "-"])
        if out.strip():
            return out, "extracted with pdftotext"
        return "", "PDF has no text layer — it is a scan, and OCR is not installed"

    if suffix in NATIVE:
        try:
            reader = {"sheet": _read_sheet, "doc": _read_doc, "deck": _read_deck}
            text = reader[NATIVE[suffix]](path)
            if text.strip():
                return text, f"read {suffix[1:]} directly"
            return "", f"{suffix[1:]} opened but is empty"
        except Exception as e:
            return "", f"could not read {suffix[1:]}: {type(e).__name__}"

    if suffix in CONVERT:
        return _via_libreoffice(path)

    try:
        raw = path.read_bytes()[:200_000]
        if b"\x00" not in raw[:2000]:
            return raw.decode("utf-8", errors="replace"), f"unknown type {suffix}, read as text"
    except OSError:
        pass
    return "", f"can't read {suffix or 'this file'}"


def _read_sheet(path):
    """Every sheet as pipe-separated rows, with the sheet named.

    Pipes rather than commas because real cells contain commas, and a model
    reading `12,500 | 3 | yes` should not have to guess where the columns
    are. Blank trailing cells are dropped so short rows stay short.
    """
    from openpyxl import load_workbook
    # data_only: we want what the sheet shows, not "=SUM(B2:B9)".
    wb = load_workbook(path, data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            while cells and cells[-1] == "":
                cells.pop()
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            out.append(f"## Sheet: {ws.title}\n" + "\n".join(rows))
    wb.close()
    return "\n\n".join(out)


def _read_doc(path):
    from docx import Document
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _read_deck(path):
    from pptx import Presentation
    deck = Presentation(str(path))
    parts = []
    for i, slide in enumerate(deck.slides, 1):
        lines = [f"## Slide {i}"]
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    text = "".join(r.text for r in p.runs).strip()
                    if text:
                        lines.append(text)
        if len(lines) > 1:
            parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _via_libreoffice(path):
    """Convert to something readable in a temp directory. Never --cat: it
    prints nothing for spreadsheets and fails silently."""
    import tempfile
    target = "csv" if path.suffix.lower() in {".ods", ".xls"} else "txt:Text"
    with tempfile.TemporaryDirectory() as tmp:
        _run(["libreoffice", "--headless", "--convert-to", target,
              "--outdir", tmp, str(path)], timeout=150)
        for made in Path(tmp).iterdir():
            body = made.read_text(encoding="utf-8", errors="replace")
            if body.strip():
                return body, f"converted with LibreOffice to {made.suffix[1:]}"
    return "", "LibreOffice could not convert this"


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
