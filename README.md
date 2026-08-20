# SHISHYA · शिष्य

An apprentice that watches you do a job **once**, writes down what it learned in
words you can read and correct, and then does that job — inside a sandbox, on
your own laptop, with the network switched off.

It is not RPA and it is not an autonomous agent.

- **RPA** (UiPath, Automator) replays coordinates. Move a window and it shatters.
- **Autonomous agents** re-derive the task every run. Unpredictable, unauditable.
- **Shishya** compiles your demonstration into a *plain-language procedure*, then
  executes that procedure against the live accessibility tree. You can read what
  it learned. You can edit what it learned. That is the whole idea.

---

## Run it

```bash
brew install lima                                  # once
limactl start --tty=false --name=shishya vm/lima.yaml   # first boot: slow
python3 serve.py                                   # → http://localhost:8200
```

The control panel shows the clone's screen, the permission ledger, and the
sandbox controls.

---

## Layout

```
vm/lima.yaml      the sandbox — its mount list IS the security boundary
vm/provision.sh   builds the clone's desktop: Xvfb, openbox, x11vnc, AT-SPI
host/vm.py        lima wrapper — snapshot, rollback, egress lock
host/ledger.py    append-only audit log
serve.py          control panel server + JSON API
web/              the panel itself — plain ES modules, no build step
shared/           the only writable window between host and clone
```

---

## Three things that are load-bearing

**The mount list is the security model.** The clone cannot read
`~/Documents` because it is not mounted, not because we check a path
somewhere. Grant a folder by adding a line to `vm/lima.yaml`; revoke it by
deleting the line. Nothing else on the laptop exists as far as the clone is
concerned.

**The accessibility tree, not pixels.** `provision.sh` turns AT-SPI on so the
executor can resolve "the field labelled *District*" instead of guessing at a
screen region. Pixels are the fallback. If the tree comes back empty, check
`GTK_MODULES=gail:atk-bridge` survived in `shishya-wm.service`.

**The display resolution is frozen at 1440×900.** Recorded traces reference
on-screen layout. Changing the resolution after recording starts invalidates
every trace already captured.

---

## The undo button

Snapshots are whole-VM, not file-level — so rolling back also catches the app
that had a document open and unsaved.

```bash
limactl snapshot create shishya --tag clean
limactl snapshot apply  shishya --tag clean
```

## The network claim

`host/vm.py:egress(True)` drops all outbound traffic from the sandbox except
the host's Ollama. Applied inside the guest, where the clone has no sudo and
therefore cannot lift it. The demo claim is "nothing left this laptop", so it
should be true rather than promised.

---

## Model

Runs on the **host** via Ollama, reached from inside at
`host.lima.internal:11434`. Deliberately not inside the VM: a model running on
emulated CPU instead of the Apple Silicon GPU is slow enough to sink a live
demo.
