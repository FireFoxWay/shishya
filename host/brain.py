#!/usr/bin/env python3
"""
Asking the model, and reading a file well enough to ask about it.

Host-side and deliberately direct: the terminal talks to Ollama on this
machine rather than driving the sandbox's chat window through the
accessibility tree. The GUI path exists so the clone can be watched working;
somebody on an ssh connection from four thousand miles away does not want to
watch anything, they want an answer.

Where the sandbox line falls here is worth being explicit about. The sandbox
contains the CLONE — it is what stops an agent reading the laptop. It was
never meant to stop the OWNER reading their own files, and a terminal the
owner opened, over ssh they authenticated, asking about a path they typed, is
the owner reading their own file. Every one of those reads goes in the ledger
all the same.
"""

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLLAMA = "http://localhost:11434"
FALLBACK_MODEL = "gpt-oss:latest"
KEEP_ALIVE = "15m"

# Same file the Models app writes and the sandbox apps read, so the terminal
# answers with the model the owner picked rather than one of its own choosing.
ROLES = ROOT / "shared" / ".models.json"


def model_for(job="answers"):
    try:
        chosen = json.loads(ROLES.read_text(encoding="utf-8")).get(job)
        if chosen:
            return chosen
    except (OSError, ValueError):
        pass
    return FALLBACK_MODEL


def up():
    """Is there a model server to talk to at all."""
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=3):
            return True
    except (urllib.error.URLError, OSError):
        return False


def resident():
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/ps", timeout=3) as r:
            return [m["name"] for m in json.loads(r.read()).get("models") or []]
    except (urllib.error.URLError, OSError, ValueError):
        return []


def stream(prompt, system=None, job="answers", budget=2400, on_token=None,
           on_think=None):
    """Ask, and hand back tokens as they arrive.

    Streaming rather than waiting for the whole answer. A twenty-billion
    parameter model on a laptop takes its time, and in a terminal the
    difference between text appearing and a cursor sitting still is the
    difference between working and hung.

    Two fields come back, not one. gpt-oss reasons before it answers and
    Ollama reports that reasoning as `thinking`, separately from `response` —
    and the reasoning is spent out of the SAME num_predict budget. A summary
    asked for with 900 tokens of room spent all 900 thinking and returned an
    empty string after half a minute, which is the same failure this project
    has already had once, in the chat app, and for the same reason.

    So the budget is generous by default, and the reasoning is handed to
    on_think rather than discarded — a terminal that shows "thinking" while
    the model reasons is telling the truth about what it is doing, and a
    cursor that just sits there is not.
    """
    # "think": "low", NOT "think": False.
    #
    # False looks like the obvious way to ask a reasoning model to stop
    # reasoning, and on gpt-oss it is worse than useless: the model reasons
    # anyway, Ollama reports it in the separate `thinking` field, the whole
    # num_predict budget goes on it, and `response` comes back EMPTY. A
    # summary asked for that way returned nothing after 32 seconds, then
    # nothing again after 196 when the budget was doubled.
    #
    # Measured on the same 1,001-row catalogue:
    #     think omitted   61.0s   497 words of reasoning, 184-word answer
    #     think "low"     15.1s     5 words of reasoning, 237-word answer
    #
    # Four times faster and the better answer, because the reasoning was the
    # expensive part and almost none of it was needed to describe a file.
    body = {
        "model": model_for(job),
        "prompt": prompt,
        "stream": True,
        "think": "low",
        "keep_alive": KEEP_ALIVE,
        # num_ctx has to hold the prompt AND the answer. Three characters per
        # token is pessimistic on purpose: column names and code tokenise
        # worse than prose, and a prompt silently truncated produces a
        # confident answer to a question the model could not see.
        "options": {"temperature": 0.2, "num_predict": budget,
                    "num_ctx": max(8192, min((len(prompt) + len(system or "")) // 3
                                             + budget + 512, 32768))},
    }
    if system:
        body["system"] = system

    def open_stream():
        req = urllib.request.Request(f"{OLLAMA}/api/generate",
                                     json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=600)

    out = []
    try:
        r = open_stream()
    except urllib.error.HTTPError:
        # Not every model understands a reasoning level. Drop it and ask again
        # rather than refusing to answer because of a hint.
        body.pop("think", None)
        r = open_stream()
    with r:
        for line in r:
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
            except ValueError:
                continue
            think = chunk.get("thinking") or ""
            if think and on_think:
                on_think(think)
            piece = chunk.get("response", "")
            if piece:
                out.append(piece)
                if on_token:
                    on_token(piece)
            if chunk.get("done"):
                break

    answer = "".join(out)
    if not answer:
        # It reasoned until it ran out of room. Once more, with more room, and
        # with the reasoning hint REMOVED rather than set to False — False is
        # what caused this failure in the first place, and a retry that
        # repeats the original mistake is not a retry.
        body["options"]["num_predict"] = budget * 2
        body.pop("think", None)
        req = urllib.request.Request(f"{OLLAMA}/api/generate",
                                     json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            for line in r:
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except ValueError:
                    continue
                piece = chunk.get("response", "")
                if piece:
                    out.append(piece)
                    if on_token:
                        on_token(piece)
                if chunk.get("done"):
                    break
        answer = "".join(out)
    return answer


# ─── reading a file well enough to ask about it ─────────────────────────────

def _sheet(path, max_rows=400, max_cols=40):
    """A spreadsheet as text: the shape first, then a sample.

    The shape matters more than the sample and is put first for that reason.
    "17,011 rows, 54 columns" tells the model that counting by eye is
    hopeless, which is what makes it write a program instead of guessing —
    the single most useful thing this project learned about prompting.
    """
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    parts = []
    for name in wb.sheetnames[:8]:
        ws = wb[name]
        rows, cols = ws.max_row or 0, ws.max_column or 0
        parts.append(f"### Sheet {name!r} — {rows} rows x {cols} columns")
        for i, row in enumerate(ws.iter_rows(max_row=min(rows, max_rows),
                                             max_col=min(cols, max_cols),
                                             values_only=True)):
            cells = ["" if v is None else str(v) for v in row]
            if any(cells):
                parts.append(" | ".join(cells))
            if i > max_rows:
                parts.append(f"... {rows - i} more rows")
                break
    wb.close()
    return "\n".join(parts)


def _csv(path, max_rows=400):
    import csv
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        rows = list(csv.reader(fh))
    head = rows[:max_rows]
    body = "\n".join(" | ".join(r) for r in head)
    if len(rows) > max_rows:
        body += f"\n... {len(rows) - max_rows} more rows"
    return f"### {len(rows)} rows x {len(rows[0]) if rows else 0} columns\n{body}"


def _pdf(path):
    p = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    return p.stdout


def extract(path):
    """Text out of a file, or a plain explanation of why not.

    Deliberately narrow about what it claims to handle. A summariser that
    silently produces nothing for a .docx and then answers anyway is worse
    than one that says it cannot read .docx here.
    """
    path = Path(path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"no file at {path}")
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xltx"):
        return _sheet(path)
    if suffix in (".csv", ".tsv"):
        return _csv(path)
    if suffix == ".pdf":
        text = _pdf(path)
        if text.strip():
            return text
        raise ValueError("that PDF has no text layer — it is probably a scan. "
                         "The Inbox app in the sandbox will OCR it.")
    if suffix in (".txt", ".md", ".json", ".log", ".py", ".html", ".xml", ".yaml", ".yml"):
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix in (".docx", ".pptx"):
        raise ValueError(f"{suffix} needs python-docx/python-pptx, which live "
                         f"in the sandbox rather than out here. Drop it in the "
                         f"Inbox and ask the chat app.")
    raise ValueError(f"I do not know how to read {suffix or 'that'} files.")


SUMMARY_SYSTEM = (
    "You summarise a document for somebody who has not read it. Lead with what "
    "it IS in one line, then what it contains, then anything that looks wrong "
    "or surprising. Be specific: name columns, quote figures. Never invent a "
    "number — if a total is not written in the document, say it would have to "
    "be counted rather than producing one. Keep it under 250 words."
)


def summarise(path, on_token=None, on_think=None):
    text = extract(path)
    # 6,000 characters, not 24,000. A summary needs the shape and enough rows
    # to see what a row looks like; the rest is reasoning the model has to do
    # and then throw away. The shape line at the top already says how big the
    # real thing is, which is the part that matters.
    trimmed = text[:6000]
    prompt = (f"Summarise the file below for somebody who has not seen it.\n\n"
              f"File: {Path(path).name}\n"
              f"{'(showing the first 6,000 characters of it)' if len(text) > 6000 else ''}\n\n"
              f"{trimmed}")
    return stream(prompt, SUMMARY_SYSTEM, job="documents", budget=2400,
                  on_token=on_token, on_think=on_think)


CHAT_SYSTEM = (
    "You are Shishya, an assistant running entirely on the owner's own laptop. "
    "Answer plainly and briefly. You are unreliable at arithmetic across many "
    "rows and you know it: if a question needs counting or filtering over a "
    "table, say so and offer to write a program rather than guessing a number. "
    "Never invent a figure, a filename or a citation."
)
