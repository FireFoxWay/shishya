<div align="center">

# SHISHYA · शिष्य

**An apprentice that watches you do a job once, writes down what it learned
in words you can edit, and then does that job — on your own laptop, sandboxed,
with the network switched off.**

[![repo](https://img.shields.io/badge/github-FireFoxWay%2Fshishya-1B1B3A?logo=github)](https://github.com/FireFoxWay/shishya)
[![runs](https://img.shields.io/badge/runs-entirely%20offline-2F7A55)](#the-network-claim)
[![model](https://img.shields.io/badge/model-local%20via%20Ollama-3A3A7C)](#the-model)
[![python](https://img.shields.io/badge/python-3.12%20stdlib%20only-C68414?logo=python&logoColor=white)](#run-it)
[![sandbox](https://img.shields.io/badge/sandbox-Lima%20%C2%B7%20Apple%20vz-6E6A63)](#how-it-holds-together)

</div>

---

## What it is

It is not RPA and it is not an autonomous agent.

| | how it works | why it breaks |
|---|---|---|
| **RPA** (UiPath, Automator) | replays recorded coordinates | move a window, resize a column, change a value — it shatters |
| **Autonomous agents** | re-derive the task from scratch each run | unpredictable, unauditable, and confidently wrong |
| **Shishya** | compiles your demonstration into a **plain-language procedure**, then executes it against the live accessibility tree | you can read what it learned, and correct it |

That middle artefact is the whole idea. A lesson comes out looking like this,
and you can edit any line:

```
1. Open the applicant PDF from the intake folder
2. Read the applicant's name, ID number, and district
3. In the registry spreadsheet, find the row matching that ID
4. If the district doesn't match, flag it and stop
5. Otherwise mark the row verified and save
```

Not `click at (412, 890)`. A clerk can read that. So can a judge.

---

## Run it

```bash
python3 doctor.py            # what works on this machine, and what does not
brew install lima            # once
python3 -c "import host.vm as vm; vm.create()"   # first boot: slow
./demo.sh                    # everything, ready
```

Then open <http://localhost:8200>.

`vm.create()` rather than `limactl start … vm/lima.yaml` directly: the mount
list in that file **is** the security boundary, so it is a template carrying
`__SHISHYA_ROOT__` and gets resolved against *your* checkout into `var/`. It
used to name one developer's home directory in full, which meant it described
a boundary that existed on exactly one laptop.

`./demo.sh` brings the whole stack up in dependency order and is the thing to
run when something looks wrong. It exists because a dead Xvfb presents as
"input is broken" rather than "there is no display" — every symptom points at
the wrong layer, and guessing which component failed wastes the time you do
not have. `./demo.sh reset` also rolls the sandbox back to clean.

### On Windows

**The sandbox does not run.** Lima is macOS and Linux; there is no Windows
build, and the virtual display, the GTK apps, the recorder, the executor and
the egress lock all live inside it.

**About half the codebase does run**, and it is the half where most of the
work is. `python doctor.py` says so specifically for your machine:

| Runs on Windows | Needs macOS or Linux |
|---|---|
| `vm/shell/books.py` — stock, sales, margin, GST, void, returns | the Lima VM and everything in it |
| `vm/shell/invoice.py` — GST tax invoices | the GTK desktop apps |
| `vm/tally.py` — the Tally XML round trip | the recorder and the executor |
| `host/{tasks,experiments,secrets,ledger,history}.py` | the egress lock (nftables) |
| `web/` — the whole control-panel front end, no build step | APFS snapshots (macOS only) |
| `serve.py` — the panel starts and reports "limactl not installed" | |

One thing to know before you write a line: **Windows defaults text files to
cp1252, not UTF-8**, and every price in this system carries a `₹`. Saving a
bill on a machine with a cp1252 locale used to raise `UnicodeEncodeError` in
the middle of writing the file. Every text read and write in the repository
now names `encoding="utf-8"` explicitly, and `doctor.py` walks the AST and
fails if any call has stopped doing so. **Keep it that way** — the failure is
silent on a Mac and only shows up on your machine.

If you want the full sandbox, WSL2 with Ubuntu is the path, and it is real
work rather than an afternoon: `host/vm.py` shells out to `limactl` in about
twenty places, and under WSL you would be driving the distro itself instead of
a VM. See §21 of the handbook.

---

## What the clone has

An empty desktop with an **Apps** button in the bottom-left corner.

| | |
|---|---|
| **Files** | browse Work, Inbox, Training Data, Lessons |
| **Inbox** | files sent in from the host — the only way in |
| **Training Data** | drop in any document, then ask about it |
| **Shishya** | teach a lesson, read it, edit it, run it |
| **Make a Document** | describe what you need; get a real `.xlsx`, `.docx` or `.pptx` |
| **Sheets** | open and edit spreadsheets instantly |
| **LibreOffice Calc / Writer** | the real thing, warm-started |
| **Activity** | the permission ledger, seen from inside |
| **Settings** | wallpaper, accent, icon size — applied live |

Shut down is at the bottom of the Apps menu rather than being the corner
button itself. The corner is where a hand goes without looking, and that
should not be the control that ends the session.

---

## How it holds together

```
YOUR MAC                          │  THE SANDBOX
                                  │
  control panel  (browser)        │    Xvfb + openbox      1440×900, frozen
  serve.py       stdlib only      │    AT-SPI tree         widget names, not pixels
  Ollama         on the GPU       │    LibreOffice         warm, gtk3, accessible
  shared/        the only way in  │    recorder → executor runs as `clone`, no sudo
                                  │
                            hypervisor
```

Exactly three things cross that line: **the screen out** (`:6080`), **the
model in** (`:11434`), and **one shared folder** (virtiofs). Nothing else.

### Three things that are load-bearing

**The mount list is the security model.** The clone cannot read `~/Documents`
because it is not mounted — not because we check a path somewhere. Grant a
folder by adding a line to `vm/lima.yaml`; revoke it by deleting the line.

**The accessibility tree, not pixels.** The executor resolves "the field
labelled *District*" instead of guessing at a screen region. LibreOffice
exposes its grid cell by cell — `A1`, `B1`, `C1` — so a procedure can name a
cell the way a person would. If a recording comes back empty, run
`python3 vm/tree.py` inside the sandbox: that is the tool for it.

**The display resolution is frozen at 1440×900.** Recorded traces reference
on-screen layout. Changing the resolution after recording starts invalidates
every trace already captured.

### The model

Runs on the **host** via Ollama, reached from inside at
`host.lima.internal:11434`. Deliberately not inside the VM: a model on
emulated CPU instead of the Apple Silicon GPU is slow enough to sink a live
demonstration.

### The network claim

`host/vm.py:egress(True)` drops all outbound traffic from the sandbox except
the host's model, applied inside the guest where the clone has no sudo and
cannot lift it. Verified: `github.com` blocked, `1.1.1.1` blocked, the model
still answering.

The indicator in the panel is **measured** on every poll by reading nftables
in the guest — it has three states, because *unknown* is its own answer when
the sandbox is down. It used to be a variable initialised to `true`, which
displayed `LOCKED` while nothing was actually blocked.

### The undo button

Whole-VM snapshots, so a rollback also catches the app that had a document
open and unsaved.

Not `limactl snapshot` — that is unimplemented for the `vz` driver, which
stores a raw disk. macOS offers something better: the disk lives on APFS, so
`cp -c` clones it copy-on-write. A 3.2 GB image clones in about **4
milliseconds** and costs no extra space until blocks diverge.

---

## Layout

```
demo.sh              bring everything to a known-good state
serve.py             control panel server + JSON API
host/vm.py           lima wrapper: snapshot, rollback, egress lock
host/ledger.py       append-only audit log, including refusals
host/synth.py        trace → editable plain-language procedure
vm/lima.yaml         the sandbox — its mount list IS the boundary
vm/provision.sh      the clone's desktop: Xvfb, openbox, VNC, AT-SPI
vm/recorder.py       records AT-SPI events, not mouse coordinates
vm/locate.py         find a control by name → a point on screen
vm/tree.py           dump the accessibility tree
vm/shell/            the desktop and its apps
web/                 the control panel — plain ES modules, no build step
```

Stdlib Python and plain ES modules throughout. Nothing that has to resolve a
dependency at a demo table.

---

## Status

**Works.** Sandbox, clone's desktop, take-the-wheel, APFS snapshot and
rollback, permission ledger, egress lock, file transfer from the host,
document Q&A over dropped files, document generation (`.xlsx` / `.docx` /
`.pptx`), spreadsheet editing, LibreOffice as a first-class app, procedure
synthesis from a trace.

**Not built yet.** The **executor** — it learns a procedure and writes it
down, but does not yet perform one. That is the largest remaining piece.

**Known.** The recorder needs its noise filter verified against a real
demonstration; the taskbar clock used to register as typing, which is fixed
but untested end to end.
