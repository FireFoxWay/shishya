#!/usr/bin/env python3
"""Render the submission to HTML, then to PDF through headless Chrome.

Chrome rather than reportlab: the whole complaint about the first version was
that it looked typeset by a machine, and real control over rhythm, weight and
white space is much easier to get out of CSS than out of a canvas API.
"""
import html as H
import re
import fields as F

def para(text):
    """Blank-line-separated blocks into <p>, with the line wrapping in the
    source thrown away — it is there for editing, not for the reader."""
    blocks = [re.sub(r"\s+", " ", b).strip() for b in text.strip().split("\n\n")]
    return "\n".join(f"<p>{H.escape(b)}</p>" for b in blocks if b)

def count(text):
    return len(text.split())

evidence = "\n".join(
    f'''<div class="ev">
          <div class="ev-n">{H.escape(n)}</div>
          <div class="ev-l">{H.escape(l)}</div>
          <div class="ev-w">{H.escape(w)}</div>
        </div>''' for n, l, w in F.EVIDENCE)

beneficiaries = "\n".join(
    f'''<div class="ben">
          <div class="ben-who">{H.escape(who)}</div>
          <div class="ben-what">{H.escape(what)}</div>
        </div>''' for who, what in F.BENEFICIARY_LIST)

team = " · ".join(H.escape(t) for t in F.TEAM)

DOC = f"""<!doctype html>
<meta charset="utf-8">
<title>Shishya — Innovation Contest Submission</title>
<style>
  @page {{ size: A4; margin: 15mm 15mm 14mm; }}

  /* One family, one accent, and space doing the work that rules and boxes
     were doing in the first version. */
  :root {{
    --ink:   #14161a;
    --ink-2: #3d434c;
    --ink-3: #767d88;
    --line:  #dfe2e6;
    --accent:#8a5a2b;
    --wash:  #f7f5f2;
  }}
  * {{ box-sizing: border-box; }}
  html {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  body {{
    margin: 0;
    font: 9.8pt/1.54 "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
    color: var(--ink-2);
  }}
  h1, h2, h3, .lbl, .ev-n, .ev-l, .meta, .chip {{
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  }}

  /* ── masthead ─────────────────────────────────────────────────────── */
  .top {{ display: flex; justify-content: space-between; align-items: baseline;
         border-bottom: 1.5px solid var(--ink); padding-bottom: 4mm; }}
  h1 {{ margin: 0; font-size: 27pt; font-weight: 700; letter-spacing: -.022em;
       color: var(--ink); line-height: 1; }}
  .sub {{ margin: 2.5mm 0 0; font-size: 10.5pt; font-style: italic;
         color: var(--ink-3); max-width: 118mm; line-height: 1.4; }}
  .school {{ font-size: 8pt; letter-spacing: .13em; text-transform: uppercase;
            color: var(--ink-3); text-align: right; line-height: 1.7; }}
  .school b {{ color: var(--ink); font-weight: 600; }}

  /* ── the two dropdown answers, stated up front ────────────────────── */
  .chips {{ display: flex; gap: 4mm; margin: 4mm 0 5.5mm; }}
  .chip {{ flex: 1; border: 1px solid var(--line); background: var(--wash);
          padding: 3mm 4mm; border-radius: 1.2mm; }}
  .chip span {{ display: block; font-size: 7pt; letter-spacing: .13em;
               text-transform: uppercase; color: var(--ink-3); margin-bottom: 1.2mm; }}
  .chip b {{ font-size: 9pt; font-weight: 600; color: var(--ink); line-height: 1.35; }}

  /* ── a field of the form ──────────────────────────────────────────── */
  /* Sections may break across pages; the pieces inside them may not.
     `break-inside: avoid` on the whole section meant a long one that started
     near the foot of page two was moved to page three entire, leaving a hand's
     width of blank paper and a third sheet carrying almost nothing. Keeping a
     heading with what follows it, and never splitting a single statistic or a
     table row, gets the same tidiness without the wasted page. */
  section {{ margin-bottom: 5.2mm; }}
  .lbl {{ break-after: avoid; }}
  .ev, .ben, .pull, .chip {{ break-inside: avoid; }}
  p {{ orphans: 2; widows: 2; }}
  .lbl {{ display: flex; align-items: baseline; gap: 3mm;
         border-bottom: 1px solid var(--line); padding-bottom: 1.6mm;
         margin-bottom: 3mm; }}
  .lbl h2 {{ margin: 0; font-size: 9pt; font-weight: 700; letter-spacing: .1em;
            text-transform: uppercase; color: var(--ink); }}
  .lbl .n {{ font-size: 8pt; font-weight: 700; color: var(--accent);
            font-variant-numeric: tabular-nums; }}
  .lbl .cap {{ margin-left: auto; font-size: 7.5pt; color: var(--ink-3);
              font-variant-numeric: tabular-nums; }}
  p {{ margin: 0 0 2.2mm; text-align: justify; hyphens: auto; }}
  p:last-child {{ margin-bottom: 0; }}

  /* The one sentence a reader keeps if they keep nothing else. */
  .pull {{ border-left: 2.5px solid var(--accent); padding: 1mm 0 1mm 4mm;
          margin: 3.2mm 0; font-size: 11pt; line-height: 1.45; color: var(--ink);
          font-style: italic; }}

  /* ── evidence ─────────────────────────────────────────────────────── */
  .grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 3.5mm; }}
  .ev {{ border-top: 1.5px solid var(--ink); padding-top: 2mm; }}
  .ev-n {{ font-size: 17pt; font-weight: 700; color: var(--ink);
          letter-spacing: -.02em; line-height: 1; font-variant-numeric: tabular-nums; }}
  .ev-l {{ font-size: 7.5pt; letter-spacing: .07em; text-transform: uppercase;
          color: var(--accent); margin: 1.2mm 0 1.6mm; font-weight: 600; }}
  .ev-w {{ font-size: 8.2pt; line-height: 1.45; color: var(--ink-3); }}

  /* ── beneficiaries ────────────────────────────────────────────────── */
  .ben {{ display: grid; grid-template-columns: 52mm 1fr; gap: 4mm;
         padding: 1.6mm 0; border-bottom: 1px solid var(--line); }}
  .ben:last-of-type {{ border-bottom: 0; }}
  .ben-who {{ font-weight: 600; color: var(--ink); font-size: 9.2pt; }}
  .ben-what {{ font-size: 9.2pt; }}
  .tail {{ margin-top: 3mm; font-style: italic; color: var(--ink-3); }}

  footer {{ margin-top: 6mm; border-top: 1px solid var(--line); padding-top: 3mm;
           display: flex; justify-content: space-between;
           font-size: 7.5pt; letter-spacing: .06em; color: var(--ink-3);
           font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; }}
</style>

<div class="top">
  <div>
    <h1>{H.escape(F.TITLE)}</h1>
    <p class="sub">{H.escape(F.SUBTITLE)}</p>
  </div>
  <div class="school"><b>{H.escape(F.SCHOOL)}</b><br>Innovation Contest<br>Proof of Concept</div>
</div>

<div class="chips">
  <div class="chip"><span>Theme</span><b>{H.escape(F.THEME)}</b></div>
  <div class="chip"><span>Nature of solution</span><b>{H.escape(F.NATURE)}</b></div>
</div>

<section>
  <div class="lbl"><span class="n">01</span><h2>Describe the problem identified</h2>
    <span class="cap">{count(F.PROBLEM)} / 250 words</span></div>
  {para(F.PROBLEM)}
</section>

<section>
  <div class="lbl"><span class="n">02</span><h2>Novelty &mdash; uniqueness</h2>
    <span class="cap">{count(F.NOVELTY)} / 150 words</span></div>
  {para(F.NOVELTY)}
</section>

<section>
  <div class="lbl"><span class="n">03</span><h2>Describe the solution</h2>
    <span class="cap">{count(F.SOLUTION)} / 250 words</span></div>
  {para(F.SOLUTION)}
  <div class="pull">Show it once. Read what it wrote down. Correct it if it is
    wrong. Then watch it do the job &mdash; on a machine with the network
    switched off.</div>
</section>

<section>
  <div class="lbl"><span class="n">04</span><h2>Target beneficiaries</h2></div>
  {para(F.BENEFICIARIES)}
  <div style="margin-top:3mm">{beneficiaries}</div>
  <p class="tail">{H.escape(F.BENEFICIARY_TAIL)}</p>
</section>

<section>
  <div class="lbl"><span class="n">05</span><h2>What already works, measured</h2></div>
  <div class="grid">{evidence}</div>
</section>

<footer>
  <span>{team}</span>
  <span>Built and measured on one laptop &middot; September 2026</span>
</footer>
"""

open("submission.html", "w", encoding="utf-8").write(DOC)
print(f"html written · {len(DOC):,} bytes")
