#!/usr/bin/env python3
"""
Shishya — do a job on the files a person handed over. Runs INSIDE the sandbox.

    python3 worker.py /home/clone/shared/jobs/<stamp>

The work-order flow. The person drops files on the panel, writes one line
saying what should happen to them, and presses Do it. The files land in
jobs/<stamp>/in, this runs, and whatever it produces lands in jobs/<stamp>/out
where the panel lists it for download.

Not chat. Chat answers questions from the training material; a job transforms
the files it was handed and its deliverable is files, not prose. The two are
kept separate because their failure modes are different: a wrong answer is a
paragraph you can read, a wrong file is something someone forwards.

Everything it does is visible from outside: status.json is rewritten at every
step (whole, then renamed — a half-written status must never be read as one),
the generated program is saved beside the outputs, and the run refuses to call
itself done if it produced nothing.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/shishya/vm/shell")
import common      # noqa: E402
import chat_app    # noqa: E402  — sheet_shape, repair, usable: the machinery chat already trusts

RUN_TIMEOUT = 180          # jobs write real workbooks; chat's 60s is too tight
GEN_BUDGET = 6144

WORK_SYSTEM = (
    "You write short, complete Python 3 scripts. Output code only — no "
    "explanation, no markdown fences. Python 3 on Linux with pandas, "
    "openpyxl, python-docx, python-pptx and matplotlib available (call "
    "matplotlib.use('Agg') before pyplot). Build paths with pathlib, using "
    "exactly the input and output paths given in the brief. Every number in "
    "every output MUST come from reading the input files — never invent, "
    "sample, or placeholder data; if the inputs do not contain what the job "
    "needs, print CANNOT: and one line saying what is missing, and write "
    "nothing. Every file you produce must be written into the OUTPUT "
    "directory, and for each file written, print one line: WROTE <filename>. "
    "Print the key figures or a short summary of what was done. Under 60 lines."
)

# A deliverable built on invented numbers is worse than no deliverable — it
# gets forwarded. The system prompt forbids it above; this catches the times
# the model does it anyway and says so in its summary, which it reliably does
# ("Generated placeholder contribution graph ... with dummy data" — a real
# job on 23 Aug 26). Confession in, deliverable out.
INVENTED = ("dummy data", "placeholder", "sample data", "fake data",
            "synthetic data", "random data", "cannot:")


def confessed(stdout):
    low = (stdout or "").lower()
    return next((w for w in INVENTED if w in low), None)


def put_status(job, **fields):
    """The panel reads this file over the shared mount. Written whole and
    renamed into place so a poll can never see half a JSON object."""
    fields.setdefault("t", round(time.time(), 1))
    tmp = job / ".status.tmp"
    tmp.write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")
    tmp.replace(job / "status.json")


def describe_inputs(files):
    """The same briefing chat gives the model, but for the job's own files."""
    lines = []
    for p in files:
        entry = f"  {p}"
        if p.suffix.lower() in (".xlsx", ".xlsm"):
            try:
                shape = chat_app.sheet_shape(p)
                if shape:
                    entry += "\n" + shape
            except Exception:
                pass
        lines.append(entry)
    listing = "INPUT FILES — use these exact paths:\n" + "\n".join(lines) \
        if lines else "There are no input files; produce the output from the brief alone."

    # Written guidance reaches jobs the same way it reaches chat: a file
    # named *-notes.md is material about the material, and a warning about a
    # trap in the data matters most to the program about to transform it.
    # Every notes file that fits — a count cap silently dropped the third.
    notes, spent = [], 0
    for n in sorted(common.TRAINING.glob("*notes.md")):
        try:
            text = n.read_text(encoding="utf-8")[:3500]
        except OSError:
            continue
        if spent + len(text) > 10_500:
            break
        notes.append(f"--- {n.name} ---\n{text}")
        spent += len(text)
    if notes:
        listing += ("\n\nRead these notes first. They describe traps in the "
                    "data and override anything a column name implies:\n"
                    + "\n".join(notes))
    # A job asking about today's takings needs the counter's books, not only
    # the files someone handed over.
    listing += chat_app.describe_billing()
    return listing


def run_program(code, job):
    """Run the generated program with the job directory as its world."""
    script = job / "program.py"          # saved, not temp: the program is
    script.write_text(code, encoding="utf-8")              # part of the deliverable — it is how
    try:                                 # anyone checks the outputs are right
        p = subprocess.run([sys.executable, str(script)],
                           capture_output=True, text=True,
                           timeout=RUN_TIMEOUT, cwd=str(job))
        return (p.stdout or "").strip(), (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return "", f"still running after {RUN_TIMEOUT}s — stopped"


def produced(out_dir):
    """What actually exists, sizes checked. A zero-byte file is a claim,
    not a deliverable, and is reported as the failure it is."""
    files, empty = [], []
    for p in sorted(out_dir.iterdir()):
        if p.is_file() and not p.name.startswith("."):
            (files if p.stat().st_size > 0 else empty).append(p.name)
    return files, empty


def main(job_dir):
    job = Path(job_dir)
    spec = json.loads((job / "job.json").read_text(encoding="utf-8"))
    brief = spec["brief"]
    out = job / "out"
    out.mkdir(exist_ok=True)
    inputs = sorted(p for p in (job / "in").iterdir()
                    if p.is_file() and not p.name.startswith("."))

    common.set_state("working")
    put_status(job, state="working", step="reading the files")
    listing = describe_inputs(inputs)

    prompt = (f"{listing}\n\nOUTPUT directory — write every produced file "
              f"here: {out}\n\nThe job: {brief}")

    put_status(job, state="working", step="working out how to do it")
    code = chat_app.repair(common.ask_job("code", prompt,
                                          system=WORK_SYSTEM, budget=GEN_BUDGET))
    if not chat_app.usable(code):
        put_status(job, state="failed",
                   step="I could not work out a program for that job — "
                        "try saying it more concretely")
        common.set_state("idle")
        return

    put_status(job, state="working", step="doing the job")
    stdout, stderr = run_program(code, job)
    attempts = 1

    files, empty = produced(out)
    if (stderr and not stdout) or (not files and not stdout):
        # One retry with the traceback, exactly as chat does. But a retry is
        # only accepted if it produces MORE than the first attempt did — the
        # margin work taught us a repair can turn a loud crash into confident
        # nonsense, and silent nonsense in a file is the worst deliverable.
        put_status(job, state="working",
                   step="the first attempt failed — reading the error and retrying")
        fixed = chat_app.repair(common.ask_job(
            "code",
            f"{prompt}\n\nThis script failed:\n\n{code}\n\n"
            f"The error:\n{(stderr or 'it produced nothing')[-1500:]}\n\n"
            f"Return the corrected script, complete, and nothing else.",
            system=WORK_SYSTEM, budget=GEN_BUDGET))
        if chat_app.usable(fixed):
            stdout2, stderr2 = run_program(fixed, job)
            files2, empty2 = produced(out)
            attempts = 2
            if len(files2) > len(files) or (stdout2 and not stdout):
                stdout, stderr, files, empty = stdout2, stderr2, files2, empty2

    told = confessed(stdout)
    if told:
        put_status(job, state="failed", attempts=attempts,
                   step=("the program said it used made-up numbers "
                         f"({told!r}) — refused rather than delivered. "
                         "Say which file holds the real figures and try again."),
                   said=stdout[-1500:])
        common.set_state("idle")
        return

    if files or stdout:
        put_status(job, state="done", attempts=attempts,
                   files=files, empty=empty,
                   said=stdout[-3000:],
                   step=(f"done — {len(files)} file(s) produced"
                         if files else "done — it answered but produced no files"))
    else:
        put_status(job, state="failed", attempts=attempts,
                   step="the program did not work",
                   error=(stderr or "it produced nothing")[-1200:])
    common.set_state("idle")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: worker.py <job-dir>")
    try:
        main(sys.argv[1])
    except Exception as e:
        try:
            put_status(Path(sys.argv[1]), state="failed",
                       step=f"the worker itself failed: {type(e).__name__}: {e}")
        finally:
            common.set_state("idle")
        raise
