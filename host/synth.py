#!/usr/bin/env python3
"""
Shishya — procedure synthesis. Runs on the HOST, against the local model.

Takes a trace (what you did, once) and produces a procedure: a numbered list
of steps in plain language that a person can read and correct, each carrying
enough structure for the executor to actually perform it.

    python3 host/synth.py shared/traces/20260820-223000

This is the part that makes the project not-RPA. A macro recorder stores your
demonstration verbatim and replays it. We throw the verbatim version away and
keep an *account* of it — generalised, parameterised, and legible.
"""

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLLAMA = "http://localhost:11434"

# deepseek-r1 rather than the larger gpt-oss: gpt-oss speaks OpenAI's harmony
# format, which does not compose with ollama's schema-constrained generation —
# it returns an empty response every time. deepseek also leaves far more RAM
# free next to the VM's 8GB, and synthesises in about 18 seconds.
DEFAULT_MODEL = "deepseek-r1:8b"

# We ask the model for 3-10 steps; fewer means it stopped early, not that
# the task was simple.
MIN_STEPS = 3
MAX_TRIES = 4


class SynthError(RuntimeError):
    pass


def assert_local(model):
    """A model tagged -cloud runs on someone else's computer.

    The entire pitch is that the applicant's data never leaves this laptop.
    Silently reaching for a hosted model would make that claim false while
    every demo still appeared to work, so this refuses rather than warns.
    """
    if "cloud" in model.lower():
        raise SynthError(
            f"{model} is a hosted model — the whole point is that nothing "
            f"leaves this machine. Use a local model."
        )


# The shape we require back. Handing ollama a schema rather than the word
# "json" is what makes this reliable: the good local models are reasoning
# models, and left unconstrained they narrate their thinking and get cut off
# before the JSON ever arrives. A schema constrains generation itself, so the
# model cannot produce anything but a valid procedure.
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "parameters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "example": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "example", "description"],
            },
        },
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "text": {"type": "string"},
                    "target": {
                        "type": "object",
                        "properties": {"role": {"type": "string"}, "name": {"type": "string"}},
                        "required": ["role", "name"],
                    },
                    "verify": {"type": "string"},
                },
                "required": ["n", "text", "target", "verify"],
            },
        },
    },
    "required": ["title", "parameters", "steps"],
}


def ask(prompt, model=DEFAULT_MODEL, temperature=0.2):
    assert_local(model)
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": SCHEMA,
        # deepseek-r1 is a reasoning model: left alone it spends its token
        # budget thinking, and because the schema forces syntactically valid
        # JSON it then closes the object early — yielding a procedure with
        # one step instead of seven. The reasoning buys us nothing here; the
        # trace has already done the hard part.
        "think": False,
        # Low temperature: we want the same demonstration to yield the same
        # procedure. A teacher who explains it differently every time is
        # not a teacher you can correct.
        "options": {"temperature": temperature, "num_ctx": 8192,
                    "num_predict": 4096},
    }).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/generate", body,
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read())["response"]
    except urllib.error.URLError as e:
        raise SynthError(f"local model unreachable at {OLLAMA} — is ollama running? ({e})")


# ─── trace → something a model can read ─────────────────────────────────────

def load(trace_dir):
    p = Path(trace_dir) / "trace.jsonl"
    if not p.exists():
        raise SynthError(f"no trace at {p}")
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def summarise(rows):
    """Flatten the trace into numbered observations.

    Raw AT-SPI is far too verbose to hand to a model whole — one text-insert
    event per keystroke buries the shape of the task. We collapse runs of
    typing into a single 'typed X into Y' and drop the rest.
    """
    meta = next((r for r in rows if r.get("kind") == "meta" and "label" in r), {})
    steps = [r for r in rows if r.get("kind") == "step"]

    lines, buf, buf_target = [], [], None

    def flush():
        nonlocal buf, buf_target
        if buf:
            lines.append(f'typed "{"".join(buf)}" into {buf_target}')
            buf, buf_target = [], None

    for s in steps:
        t = s.get("target") or {}
        where = f'{t.get("role","?")} "{t.get("name","")}"'.strip()
        app = s.get("app") or "?"

        if s["event"] == "object:text-changed:insert" and isinstance(s.get("detail"), str):
            if buf_target and buf_target != f"{where} in {app}":
                flush()
            buf_target = f"{where} in {app}"
            buf.append(s["detail"])
            continue

        flush()
        verb = {
            "object:state-changed:focused": "moved to",
            "object:value-changed": "changed the value of",
            "object:selection-changed": "selected in",
            "window:activate": "switched to",
        }.get(s["event"], s["event"])
        lines.append(f"{verb} {where} in {app}")

    flush()
    return meta.get("label", "untitled"), lines


# ─── the prompt ─────────────────────────────────────────────────────────────

PROMPT = """You are watching a recording of a person doing a task once on a computer.
Below is what they did, in order, described in terms of the on-screen controls they used.

TASK LABEL: {label}

OBSERVATIONS:
{obs}

Write the procedure they were following, so that someone else could repeat it
on different data tomorrow.

Rules:
- Write each step the way a person would explain it to a new colleague. Say
  what they are accomplishing, not which widget was clicked.
- Collapse fiddling into intent. Several clicks that add up to "find the
  applicant's row" are ONE step.
- Anything specific to this run — a name, a number, a filename, a date — is a
  parameter, not a constant. Refer to it as {{parameter_name}} in the step text.
- Add a "verify" to each step: how you would know it worked.
- Between 3 and 10 steps. If you have more, you are describing clicks
  rather than the job.
- Do NOT invent actions. If the person only moved to a control and typed
  nothing, they were READING it — most likely checking it against something.
  Say that. Never write "edit" or "update" for a control nothing was typed
  into. A step that did not happen is worse than a step left out.
- Write the way a colleague talks, not the way a manual reads. "Find the
  applicant's row" — not "the user should navigate to the row such that".

Return ONLY JSON of this shape:
{{
  "title": "short name for the task",
  "parameters": [
    {{"name": "applicant_name", "example": "value seen in this recording",
      "description": "what this is"}}
  ],
  "steps": [
    {{"n": 1,
      "text": "what to do, referring to parameters as {{applicant_name}}",
      "target": {{"role": "the kind of control", "name": "its label"}},
      "verify": "how you know this step worked"}}
  ]
}}"""


def synthesise(trace_dir, model=DEFAULT_MODEL):
    label, obs = summarise(load(trace_dir))
    if not obs:
        raise SynthError(
            "the trace has no steps — if the recording looked fine, AT-SPI was "
            "probably not exposing the app. Run `recorder.py probe` in the sandbox."
        )

    prompt = PROMPT.format(
        label=label,
        obs="\n".join(f"{i+1}. {o}" for i, o in enumerate(obs)),
    )

    # The model intermittently returns a one-step procedure for a ten-step
    # recording — it stops early and the schema closes the object for it,
    # so the result is valid JSON and obvious nonsense. We asked for at least
    # three steps, so treat fewer as a failed generation and ask again rather
    # than handing the user a procedure that plainly is not the task.
    # Temperature climbs a little each try to break it out of the same rut.
    best = None
    for attempt in range(MAX_TRIES):
        proc, _ = validate(parse(ask(prompt, model, 0.2 + 0.2 * attempt)), obs)
        n = len(proc.get("steps", []))
        if best is None or n > len(best.get("steps", [])):
            best = proc
        if n >= MIN_STEPS:
            break
    else:
        best.setdefault("warnings", []).append(
            f"the model never produced {MIN_STEPS} steps in {MAX_TRIES} tries — "
            f"this procedure is probably incomplete, check it against what you did"
        )
    proc = best
    proc["source_trace"] = str(trace_dir)
    proc["model"] = model

    out = Path(trace_dir) / "procedure.json"
    out.write_text(json.dumps(proc, indent=2, ensure_ascii=False), encoding="utf-8")
    return proc


# ─── don't trust the model ──────────────────────────────────────────────────
# An 8B model reliably gets the shape of a task right and unreliably gets the
# details right. Rather than pretend better prompting fixes that, we check its
# output against the trace it was derived from. Anything the trace cannot
# support is dropped or flagged — the procedure the human reads should never
# contain a step nobody performed.

def validate(proc, obs):
    """Returns (procedure, warnings). Never raises: a flawed procedure the
    user can see and correct beats an exception they cannot."""
    warnings = []
    haystack = " ".join(obs).lower()

    # A parameter whose example never appears in the recording was imagined.
    kept_params = []
    for p in proc.get("parameters", []):
        example = str(p.get("example", "")).strip()
        if example and example.lower() not in haystack:
            warnings.append(
                f"dropped parameter {{{p['name']}}} — its example "
                f"{example!r} never appears in the recording"
            )
            continue
        kept_params.append(p)
    proc["parameters"] = kept_params

    # Near-duplicate steps: the model restating one action as two.
    kept_steps, seen = [], []
    for step in proc.get("steps", []):
        key = _norm(step.get("text", ""))
        if any(_similar(key, s) for s in seen):
            warnings.append(f"dropped duplicate step: {step.get('text','')[:60]}")
            continue
        seen.append(key)
        kept_steps.append(step)

    for i, step in enumerate(kept_steps, 1):
        step["n"] = i
    proc["steps"] = kept_steps

    # Any {placeholder} left in the text with no parameter behind it.
    names = {p["name"] for p in kept_params}
    for step in kept_steps:
        for ref in re.findall(r"\{(\w+)\}", step.get("text", "")):
            if ref not in names:
                warnings.append(f"step {step['n']} refers to {{{ref}}}, which is not a parameter")

    proc["warnings"] = warnings
    return proc, warnings


def _norm(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).split()


def _similar(a, b, threshold=0.8):
    """Word overlap. Crude on purpose — we are catching a model repeating
    itself in near-identical words, not paraphrase detection."""
    if not a or not b:
        return False
    sa, sb = set(a), set(b)
    return len(sa & sb) / max(len(sa), len(sb)) >= threshold


def parse(raw):
    """Models wrap JSON in prose and fences even when told not to."""
    for attempt in (raw, re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M)):
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise SynthError(f"model did not return usable JSON:\n{raw[:400]}")


def render(proc):
    """The screen the judge reads. Plain text on purpose."""
    out = [proc.get("title", "Untitled"), "=" * len(proc.get("title", "Untitled")), ""]
    if proc.get("parameters"):
        out.append("Changes each time:")
        for p in proc["parameters"]:
            out.append(f"  {{{p['name']}}} — {p.get('description','')}  (this run: {p.get('example','')})")
        out.append("")
    for s in proc.get("steps", []):
        out.append(f"{s['n']}. {s['text']}")
        if s.get("verify"):
            out.append(f"     ✓ {s['verify']}")
    if proc.get("warnings"):
        out.append("")
        out.append("Checked against the recording:")
        for w in proc["warnings"]:
            out.append(f"  ! {w}")
    return "\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: synth.py <trace-dir> [model]")
    model = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODEL
    try:
        print(render(synthesise(sys.argv[1], model)))
    except SynthError as e:
        sys.exit(f"synth: {e}")
