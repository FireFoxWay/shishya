<div align="center">

# SHISHYA · शिष्य

**An apprentice that watches you do a job once, writes down what it learned
in words you can edit, and then does that job — on your own Windows laptop,
sandboxed, with the network switched off.**

[![repo](https://img.shields.io/badge/github-FireFoxWay%2Fshishya-1B1B3A?logo=github)](https://github.com/FireFoxWay/shishya)
[![runs](https://img.shields.io/badge/runs-entirely%20offline-2F7A55)](#the-network-claim)
[![model](https://img.shields.io/badge/model-local%20via%20Ollama-3A3A7C)](#the-model)
[![python](https://img.shields.io/badge/python-3.12%20stdlib%20only-C68414?logo=python&logoColor=white)](#run-it)
[![platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4?logo=windows)](#run-it)
[![sandbox](https://img.shields.io/badge/sandbox-WSL2%20%C2%B7%20Ubuntu%2024.04-6E6A63)](#how-it-holds-together)

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

Windows 10 22H2 or Windows 11, with virtualisation enabled in the firmware,
Python 3.10+ from python.org, and [Ollama for Windows](https://ollama.com/download).

```powershell
# once, in an administrator PowerShell: WSL2, OLLAMA_HOST, the firewall rule
powershell -ExecutionPolicy Bypass -File windows\setup.ps1

python doctor.py                                   # what works on this machine, and what does not
python -c "import host.vm as vm; vm.create()"      # first boot: slow — downloads Ubuntu and provisions
python demo.py                                     # everything, ready
```

Then open <http://localhost:8200>.

`vm.create()` rather than `wsl --import` by hand: the boundary is two
templates, `vm/wsl.conf` and `vm/fstab`, carrying `__SHISHYA_ROOT__`, and they
are resolved against *your* checkout and written into the image **before it
has ever booted as itself**. WSL's defaults — every drive mounted at
`/mnt/c`, and `cmd.exe` runnable from inside — are the opposite of a sandbox,
and no step of provisioning ever runs in a guest that has them.

`python demo.py` brings the whole stack up in dependency order and is the
thing to run when something looks wrong. It exists because a dead Xvfb
presents as "input is broken" rather than "there is no display" — every
symptom points at the wrong layer, and guessing which component failed wastes
the time you do not have. `python demo.py check` changes nothing;
`python demo.py rehearse` exercises every claim below, including the ones
specific to WSL: no `/mnt/c`, no interop, no DNS while locked.

**Keep the checkout on a local drive** (not a network share), and let
`.gitattributes` do its job: the shell scripts run inside the sandbox straight
off the mount, and Git for Windows' default CRLF breaks them on line one.
`doctor.py` checks both.

### The terminal

The panel is a browser on localhost, which is awkward when the laptop is in
one country and you are in another. `shishya` is not:

Add the checkout's folder to your user `PATH` once (Settings → System → About
→ Advanced system settings → Environment Variables); `shishya.cmd` is the
launcher. Not `setx PATH "%PATH%;…"`, which copies the system path into
yours and truncates it at 1024 characters.

```powershell
shishya                                    # the loop
shishya board                              # or one thing, and exit
shishya sum %USERPROFILE%\Downloads\sales.xlsx
shishya ask "what did we take last week?"
```

Four things, and the restraint is the design: summarise a document already on
the machine, summarise one you name, read the dashboard as text, and ask it
things. Teaching a procedure and watching the clone work need to be *seen* and
stay in the panel.

Standard library only, because this runs on a machine you have just `ssh`'d
into (Windows' own OpenSSH server works). Colour switches off when it is not a
terminal, so `shishya board > today.txt` gives you plain text, and output is
UTF-8 whatever the console's code page, because every price has a `₹`.

### Things Windows does differently, on purpose

**Text is UTF-8, named every time.** Windows defaults text files to cp1252,
and every price in this system carries a `₹`. Every text read and write in the
repository names `encoding="utf-8"` explicitly, and `doctor.py` walks the AST
and fails if any call has stopped doing so. **Keep it that way.**

**The model has to listen beyond loopback.** The sandbox reaches Windows at
its NAT gateway, not 127.0.0.1, and Ollama answers on 127.0.0.1 alone unless
`OLLAMA_HOST=0.0.0.0`. `setup.ps1` sets it and adds an inbound rule for 11434
**on the WSL adapter only**, so your Wi-Fi does not get a model too. If every
app in the sandbox fails to answer while `ollama run` works fine on Windows,
this is why.

**Secrets are locked by ACL, not chmod.** `0600` is a comment on Windows. The
store at `%USERPROFILE%\.shishya` has its inheritance cut and one grant — you
— and `demo.py check` reads the access list back.

**NAT, not mirrored networking.** The egress lock is written for WSL's NAT
mode. If `%USERPROFILE%\.wslconfig` sets `networkingMode=mirrored`, `doctor.py`
says so.

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
WINDOWS                           │  THE SANDBOX  (WSL2 · Ubuntu 24.04)
                                  │
  control panel  (browser)        │    Xvfb + openbox      1440×900, frozen
  serve.py       stdlib only      │    AT-SPI tree         widget names, not pixels
  Ollama         on the GPU       │    LibreOffice         warm, gtk3, accessible
  shared/        the only way in  │    recorder → executor runs as `clone`, no sudo
                                  │
                     WSL2 utility VM · wsl.conf · fstab
```

Exactly three things cross that line: **the screen out** (`:6080`, through
WSL's localhost forwarding), **the model in** (`:11434` at the NAT gateway),
and **one shared folder** (drvfs). Nothing else — no `/mnt/c`, no running
Windows programs from inside.

### Three things that are load-bearing

**The mount list is the security model.** The clone cannot read `Documents`
because it is not mounted — not because we check a path somewhere. Grant a
folder by adding a line to `vm/fstab`; revoke it by deleting the line.

One honest difference from the Mac build: Lima's mounts were enforced by the
hypervisor. WSL's are enforced by the guest's own `/etc/wsl.conf` and
`/etc/fstab`, so root inside could mount `C:` by hand. The clone is not root
and has no sudo, and `demo.py rehearse` checks both — the claim holds for the
clone, which is who it is about.

**The accessibility tree, not pixels.** The executor resolves "the field
labelled *District*" instead of guessing at a screen region. LibreOffice
exposes its grid cell by cell — `A1`, `B1`, `C1` — so a procedure can name a
cell the way a person would. If a recording comes back empty, run
`python3 vm/tree.py` inside the sandbox: that is the tool for it.

**The display resolution is frozen at 1440×900.** Recorded traces reference
on-screen layout. Changing the resolution after recording starts invalidates
every trace already captured.

### The model

Runs on **Windows** via Ollama, reached from inside at the guest's default
gateway, port 11434 — read from the routing table each time, because WSL's
NAT hands out a new subnet when Windows restarts. Deliberately not inside the
sandbox: a model without the GPU is slow enough to sink a live demonstration.

### The network claim

`vm/egress.sh` drops all outbound traffic from the sandbox except the host's
model, applied inside the guest where the clone has no sudo and cannot lift
it. It is the one place the rules are written; browsing and SSH are modes of
it. Under WSL it also drops WSL's DNS tunnel (`10.255.255.254`, on the
guest's own loopback), which would otherwise let a locked sandbox resolve —
and so signal — any name on the internet.

The indicator in the panel is **measured** on every poll by reading nftables
in the guest — it has three states, because *unknown* is its own answer when
the sandbox is down. It used to be a variable initialised to `true`, which
displayed `LOCKED` while nothing was actually blocked.

**And it survives a reboot.** nftables rules live only in the running kernel,
so until 6 September a sandbox that came back after the laptop slept came back
*open* — found only because the panel asks the guest instead of remembering,
and it said `OPEN`. `shishya-egress.service` re-applies the lock before the
network comes up, so there is no window in which the sandbox is running and
unlocked. That measured indicator is the reason the bug was ever visible; an
interface that reported what it had been told would have hidden it for
months.

### The undo button

Whole-disk snapshots, so a rollback also catches the app that had a document
open and unsaved.

The sandbox's disk is one file, `ext4.vhdx`, under
`%LOCALAPPDATA%\shishya` — deliberately outside the repository, which the
clone can read. A snapshot copies it with the sandbox stopped; a rollback
copies it back, and WSL keeps pointing at the same path.

**Not instant, and not pretending to be.** The Mac build cloned the disk on
APFS copy-on-write in about 4 ms. NTFS has no such thing: this is a real copy
of a few GB, tens of seconds. On a Dev Drive (ReFS) Windows may block-clone it
and it is much faster.

---

## Layout

```
shishya              the terminal — ask, summarise, read the dashboard
shishya.cmd          …and its Windows launcher
doctor.py            what works on THIS machine, and what does not
demo.py              bring everything to a known-good state
serve.py             control panel server + JSON API
windows/setup.ps1    once, as administrator: WSL2, Ollama, the firewall

host/vm.py           wsl.exe wrapper: create, snapshot, rollback, egress lock
host/brain.py        asking the model and reading a file, host-side
host/dashboard.py    the overview screen's data, assembled in one call
host/profile.py      who is using this and what they do for a living
host/hosts.py        saved ssh hosts — never a password, only a key path
host/ledger.py       append-only audit log, including refusals
host/secrets.py      credentials, kept OUTSIDE this repo on purpose
host/synth.py        trace → editable plain-language procedure

vm/wsl.conf          no automount, no interop, systemd on
vm/fstab             the two folders the clone can see — this IS the boundary
vm/egress.sh         the network lock, every mode of it, re-applied at boot
vm/forecast.py       demand forecasting, written from scratch in numpy
vm/provision.sh      builds the machine, once
vm/display.sh        Xvfb, openbox, x11vnc, noVNC — re-runnable
vm/recorder.py       records AT-SPI events, not mouse coordinates
vm/executor.py       performs a learned procedure against live apps
vm/locate.py         find a control by name → a point on screen

vm/shell/books.py    the shop: stock, sales, margin, GST, void, returns
vm/shell/invoice.py  GST tax invoices
vm/shell/money.py    accounts, commitments, what a credit score is made of
vm/shell/            the desktop and its apps

web/                 the control panel — plain ES modules, no build step
```

Stdlib Python and plain ES modules throughout. Nothing that has to resolve a
dependency at a demo table.

---

## Status

**Works, and is checked.** `python demo.py check` runs its assertions in about a
minute — including typing a key into a real window and reading it back, and
asking the *guest* whether the egress lock is on rather than remembering
what it was told.

The sandbox and the clone's desktop; take-the-wheel; snapshot and
rollback; the permission ledger; the egress lock; document Q&A over dropped
files; document generation (`.xlsx` / `.docx` / `.pptx`); **the executor**,
which performs a taught procedure against live LibreOffice and reads each
cell back to check it landed; GST billing, tax invoices, void and returns;
stock audit, scheduled runs, alerts, backups; clerk/head roles with approvals
between them; a Tally XML round trip; a six-screen ERP; and the terminal.

**It trains its own model.** Running someone else's model locally is ordinary
now. `vm/forecast.py` trains a demand forecaster on the shop's own purchase
history, on the shop's own laptop — forward pass, backpropagation, momentum
and initialisation all written out, numpy doing array arithmetic and nothing
else. Measured against the baselines that matter, on a month it never saw:

| On a held-out month | MAE |
|---|---|
| **this model** | **7.469** |
| same as last month | 10.862 |
| recent average | 12.572 |

**31.2% better than the best baseline.** 12,079 products, 17 months, 120,790
training windows, **3.9 seconds** to train. Nothing uploaded. A forecaster
that cannot beat *"next month looks like last month"* is worse than useless,
so `forecast.py check` prints that comparison whether or not it flatters us.

**Not proved yet, which is a different thing.**

- **Nobody outside this project has used it.** Every bill so far was rung up
  by a script. One shopkeeper for one afternoon is worth more than any
  feature still on the list.
- **Tally has never accepted the XML.** It passes every check that can run
  here; that is not the same claim. This is a Windows build now, so it is one
  Tally install away.
- **The WSL port has not been through a full demonstration yet.** Everything
  inside the guest is the code that ran on the Mac; the wrapper around it is
  new. Run `python demo.py rehearse` before trusting it in front of people.
- **Nobody who reads Telugu has read the Telugu answers**, and the English
  and Telugu versions are known to differ in emphasis. Marked *do not
  demonstrate* until they have.
- **Keyboard injection into the sandbox can die on its own.** Mouse fine,
  queries fine, every typed key silently swallowed — which stops the
  executor dead. It happened once while the machine sat idle. `demo.py
  check` types a probe and catches it; `vm/display.sh --all` fixes it.

**Not public, and not yet publishable.** `shared/training/` holds a real
pharmacy's purchase history, and it is in git history rather than only in the
working tree. That comes out with `git filter-repo` before this repository
goes anywhere.
