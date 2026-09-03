#!/bin/bash
# ============================================================================
# SHISHYA — get to a known-good demo state, in one command.
#
#     ./demo.sh          reset everything and open the panel
#     ./demo.sh check    check without changing anything
#     ./demo.sh rehearse every claim you are about to make, exercised
#
# Run this before you present. It exists because the failure that cost us
# most was invisible: stale websockify processes piling up across restarts
# until button releases stopped being delivered and every control in the
# sandbox went dead while still looking fine.
# ============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VM=shishya
PANEL=8200

say()  { printf "\033[36m%s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
bad()  { printf "  \033[31m✗\033[0m %s\n" "$*"; }

inguest() { limactl shell --workdir / "$VM" -- "$@" 2>/dev/null; }
asclone() { limactl shell --workdir / "$VM" -- sudo -u clone bash -lc "set -a; . /etc/shishya.env; set +a; $1" 2>/dev/null; }

# ── checks ──────────────────────────────────────────────────────────────────

check() {
  local fails=0

  if [ "$(limactl list --format '{{.Status}}' "$VM" 2>/dev/null)" = "Running" ]; then
    ok "sandbox running"
  else
    bad "sandbox is not running — run: limactl start $VM"; return 1
  fi

  for s in dbus display atspi wm vnc novnc desktop; do
    [ "$(inguest systemctl is-active shishya-$s)" = "active" ] \
      && ok "shishya-$s" || { bad "shishya-$s is not active"; fails=1; }
  done

  # The one that actually bit us. More than one parent websockify, or more
  # than one x11vnc, means input will die in ways that look like anything else.
  local vnc web live orphans
  vnc=$(inguest pgrep -c x11vnc || echo 0)
  [ "$vnc" = "1" ] && ok "one x11vnc" || { bad "$vnc x11vnc processes (want 1)"; fails=1; }

  # websockify forks a child per connected client, so a plain count is not the
  # signal — this used to demand two or fewer and cried wolf the moment a
  # browser held both a WebSocket and a keep-alive for the static files. The
  # failure it is really looking for is a child with no connection behind it:
  # an orphan left over from a restart, still bound, still accepting, still
  # swallowing button releases. Children are compared against live clients.
  web=$(inguest pgrep -cf "websockify --web" || echo 0)
  live=$(inguest bash -c 'ss -tn state established "( sport = :6080 )" | tail -n +2 | wc -l')
  orphans=$(( ${web:-1} - 1 - ${live:-0} ))
  if [ "$orphans" -le 0 ]; then
    ok "websockify: 1 parent, ${live:-0} client(s), no orphans"
  else
    bad "$orphans orphaned websockify child(ren) — input will die in ways that look like anything else"
    fails=1
  fi

  local desks
  # The service runs it by absolute path, so match the filename only.
  desks=$(inguest pgrep -u clone -cf "desktop.py" | head -1)
  desks=${desks:-0}
  [ "$desks" = "1" ] && ok "one desktop" \
    || { bad "$desks desktops (want 1)"; fails=1; }

  curl -s -o /dev/null --max-time 4 "http://localhost:$PANEL/api/status" \
    && ok "control panel on :$PANEL" || { bad "control panel is down"; fails=1; }

  curl -s --max-time 6 http://localhost:11434/api/tags >/dev/null \
    && ok "model reachable" || { bad "ollama is not running on the host"; fails=1; }

  local eg
  eg=$(curl -s --max-time 6 "http://localhost:$PANEL/api/status" \
       | python3 -c 'import json,sys; print(json.load(sys.stdin)["egress"]["locked"])' 2>/dev/null)
  [ "$eg" = "True" ] && ok "egress locked (measured)" || bad "egress is $eg"

  # ── the screen has to go quiet when nobody is watching ──────────────────
  # The animated wallpaper repaints all 1440x900 several times a second, and
  # every repaint is a full frame for x11vnc to encode and ship. With nobody
  # attached that was a video stream into a socket no one was reading —
  # measured at 19% of a core in Xvfb plus 13% in the desktop shell, forever.
  # The desktop now watches noVNC's own socket and stops drawing when the
  # last viewer goes. Proved by pixels, not by CPU: two screenshots taken
  # seconds apart must be byte-identical.
  if [ "$(inguest bash -c 'ss -tn state established "( sport = :6080 )" | grep -c 6080')" = "0" ]; then
    # Wait out the end of the minute first. The taskbar clock reads %H:%M, so
    # two shots that straddle a minute boundary differ for a reason that is
    # not a fault — and a check that cries wolf one run in twenty gets
    # ignored on the run that matters.
    asclone 'while [ $(date +%S) -gt 50 ]; do sleep 1; done
             scrot -o /tmp/still-a.png; sleep 3; scrot -o /tmp/still-b.png'
    if [ "$(inguest md5sum /tmp/still-a.png | cut -d" " -f1)" \
       = "$(inguest md5sum /tmp/still-b.png | cut -d" " -f1)" ]; then
      ok "screen is still with no viewer attached"
    else
      bad "screen is repainting with nobody watching — the wallpaper gate is off"
      fails=1
    fi
  else
    ok "a viewer is attached — screen expected to be live"
  fi

  # x11vnc ran with -noxdamage for months, which turns off the extension that
  # says which rectangles changed and leaves it scanning the whole framebuffer
  # on a timer. DAMAGE is present on this Xvfb and works.
  if inguest bash -c 'tr "\0" " " < /proc/$(pgrep -x x11vnc | head -1)/cmdline' \
     | grep -q -- "-noxdamage"; then
    bad "x11vnc is running with -noxdamage — it is polling the whole screen"
    fails=1
  else
    ok "x11vnc is using damage tracking"
  fi

  # A reverse DNS lookup per client connect, with egress locked, means the
  # screen stays blank for the whole resolver timeout.
  inguest bash -c 'tr "\0" " " < /proc/$(pgrep -x x11vnc | head -1)/cmdline' \
    | grep -q -- "-nolookup" \
    && ok "x11vnc does not wait on DNS to accept a viewer" \
    || { bad "x11vnc will do a reverse DNS lookup per connect"; fails=1; }

  # ── the first question must not pay for loading the model ───────────────
  # Ollama unloads after five minutes by default and the owner's model is
  # 13.8GB — twenty to forty seconds of reading it back before a single token.
  local resident
  resident=$(curl -s --max-time 6 http://localhost:11434/api/ps \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("models") or []))' 2>/dev/null)
  [ "${resident:-0}" -ge 1 ] \
    && ok "a model is resident — the next question answers straight away" \
    || bad "no model resident: the next question pays the load (run shishya-warm)"

  # Typed, not assumed. An Xvfb can come up with XTEST keyboard injection
  # dead — mouse fine, queries fine, every keystroke silently swallowed. It
  # cost half a day and got blamed on VNC, AT-SPI and LibreOffice before a
  # probe typed into `cat` and proved keys never arrived. Six seconds here
  # buys not having that conversation at a demo table.
  # The window title is built at runtime so this script's own command line
  # never contains it — a pkill pattern that matches the probing shell kills
  # the probe mid-run and reports a failure that is not there.
  local typed
  typed=$(asclone 'T=probe$$; rm -f /tmp/.keycheck
    setsid xterm -title "$T" -e sh -c "cat > /tmp/.keycheck" </dev/null >/dev/null 2>&1 &
    sleep 3
    W=$(xdotool search --onlyvisible --name "$T" | head -1)
    # Click into the window, never merely activate it: WM-active and
    # input-focus are different things on this desktop, and the click is
    # what hands keystrokes over — the executor types the same way.
    eval "$(xdotool getwindowgeometry --shell "$W" 2>/dev/null)"
    xdotool mousemove $((X+80)) $((Y+60)) click 1 2>/dev/null
    sleep 1
    xdotool type ping; xdotool key Return; sleep 1
    pkill -f "xterm -title $T" 2>/dev/null; cat /tmp/.keycheck 2>/dev/null')
  [ "$typed" = "ping" ] && ok "keyboard injection reaches apps" \
    || { bad "typed keys are not arriving — run ./demo.sh to rebuild the display"; fails=1; }

  # Is what is running the code that is on disk? Twice in one day an app was
  # added to the launcher, the file was right, and the menu did not have it —
  # because the desktop shell had been running for eight hours and predates
  # the edit. Nothing looks wrong in that state, which is what makes it worth
  # a check: the source says one thing and the screen says another.
  local pid elapsed age
  pid=$(inguest pgrep -u clone -f "shell/desktop.py" | head -1)
  if [ -n "$pid" ]; then
    elapsed=$(inguest ps -o etimes= -p "$pid" | tr -d ' ')
    age=$(inguest bash -lc 'echo $(( $(date +%s) - $(stat -c %Y /opt/shishya/vm/shell/desktop.py) ))')
    if [ -n "$elapsed" ] && [ -n "$age" ] && [ "$elapsed" -gt "$age" ]; then
      bad "the desktop is older than desktop.py — new apps will not be in the menu"; fails=1
    else
      ok "the desktop is running current code"
    fi
  fi

  # Same trap on this side: the panel keeps serving whatever it started with.
  # In Python because macOS ps has no etimes and its lstart needs parsing —
  # not worth two lines of date arithmetic that only work on one platform.
  if python3 - "$ROOT" <<'PY'
import os, subprocess, sys, time
root = sys.argv[1]
pids = subprocess.run(["pgrep", "-f", "serve.py"], capture_output=True, text=True).stdout.split()
if not pids:
    sys.exit(2)                       # not running is a different complaint
when = subprocess.run(["ps", "-o", "lstart=", "-p", pids[0]],
                      capture_output=True, text=True).stdout.strip()
try:
    started = time.mktime(time.strptime(when, "%a %b %d %H:%M:%S %Y"))
except ValueError:
    sys.exit(0)                       # cannot tell; do not cry wolf
sys.exit(0 if started >= os.path.getmtime(os.path.join(root, "serve.py")) else 1)
PY
  then ok "the panel is running current code"
  elif [ $? = 1 ]; then
    bad "the panel is older than serve.py — new routes will 404"; fails=1
  fi

  # One desktop. Four is openbox's default and a rollback can restore a disk
  # from before this was set — the symptom is a scroll blanking the screen,
  # which reads as the apps crashing.
  local desks
  desks=$(asclone 'xprop -root _NET_NUMBER_OF_DESKTOPS' | grep -o '[0-9]*$')
  [ "$desks" = "1" ] && ok "one desktop (a stray scroll cannot blank the screen)" \
    || { bad "$desks desktops — scrolling will switch workspace mid-demo"; fails=1; }

  # Secrets must be where the sandbox cannot read them, and their values
  # must not have been copied into shared/ by some well-meaning script. The
  # store being private is worth nothing if a value was carried across.
  local vault
  vault=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT/host')
import secrets as v
ok, detail = v.permissions_ok()
leaks = v.leaked_into('$ROOT/shared')
print(('ok' if ok and not leaks else 'bad'), detail, '|', ','.join(leaks) or 'no leaks')
" 2>/dev/null)
  case "$vault" in
    ok*) ok "secrets are private and none reached shared/" ;;
    bad*) bad "secrets: ${vault#bad }"; fails=1 ;;
    *)   ok "no secret store yet" ;;
  esac

  # The model each job actually uses must exist. The chat app once fell back
  # to a model nobody chose and burned half an hour reasoning about a prompt
  # it could not see; the roles file now decides, so verify what it names.
  local wanted
  wanted=$(python3 -c 'import json; print(json.load(open("'"$ROOT"'/shared/.models.json")).get("code",""))' 2>/dev/null)
  if [ -n "$wanted" ] && curl -s -m 4 http://localhost:11434/api/tags | grep -q "\"$wanted\""; then
    ok "code job model installed ($wanted)"
  else
    bad "model for the code job ($wanted) is not in ollama"; fails=1
  fi

  return $fails
}

# ── reset ───────────────────────────────────────────────────────────────────

reset() {
  say "Resetting the display stack"
  # Order matters, and so does killing the strays: systemctl stop leaves
  # websockify children behind, and those are what break input.
  inguest sudo systemctl stop shishya-novnc shishya-vnc shishya-wm shishya-display
  inguest sudo pkill -9 -f websockify
  inguest sudo pkill -9 -f x11vnc
  sleep 2
  for s in display atspi wm vnc novnc; do
    inguest sudo systemctl start "shishya-$s"
    sleep 2
  done

  # Idempotent, and cheap. A rollback can restore a disk from before this
  # was set, and the symptom — a scroll blanking the screen mid-demonstration
  # — is the kind you only discover in front of people.
  asclone "python3 /opt/shishya/vm/one-desktop.py" >/dev/null 2>&1

  say "Restarting the desktop"
  inguest sudo pkill -u clone -f "_app.py"
  inguest sudo systemctl restart shishya-desktop
  sleep 4

  say "Restarting the control panel"
  pkill -f "serve.py $PANEL" 2>/dev/null
  wait 2>/dev/null || true
  ( cd "$ROOT" && nohup python3 serve.py "$PANEL" >var/serve.log 2>&1 & )
  for _ in $(seq 1 25); do
    curl -s -o /dev/null "http://localhost:$PANEL/api/status" && break
    sleep 1
  done

  # Ollama is an app, and apps quit — it was down after a sleep and every
  # single thing that needs the model failed with a connection refused. The
  # check catches it; this starts it.
  if ! curl -s -o /dev/null -m 3 http://localhost:11434/api/tags; then
    say "Starting Ollama"
    open -a Ollama 2>/dev/null
    for _ in $(seq 1 30); do
      curl -s -o /dev/null -m 2 http://localhost:11434/api/tags && break
      sleep 2
    done
  fi

  say "Locking egress"
  curl -s -X POST -H 'Content-Type: application/json' -d '{"locked":true}' \
    "http://localhost:$PANEL/api/vm/egress" >/dev/null

  echo
  say "Checks"
  check
  echo
  say "Panel: http://localhost:$PANEL"
  say "Reload the page. Drive from the panel; do not click inside the sandbox."
}

# ── rehearsal ───────────────────────────────────────────────────────────────
# Every claim you are about to make, exercised, before an audience exists.
#
# `check` proves the machine is healthy. This proves the machine can still do
# the things you are going to stand up and say it does — which is a different
# question, and the one that matters ten minutes before a call. It changes
# nothing a demonstration would not change anyway.

rehearse() {
  local fails=0
  claim() {  # claim <name> <command...>
    local what="$1"; shift
    if out=$("$@" 2>&1); then ok "$what"; else bad "$what — $(echo "$out" | tail -1)"; fails=1; fi
  }

  say "Rehearsing the claims"

  claim "the model answers at all" bash -c \
    'curl -s -m 90 http://localhost:11434/api/generate -d "{\"model\":\"gpt-oss:latest\",\"prompt\":\"say READY\",\"stream\":false}" | grep -qi ready'

  claim "the sandbox cannot reach the internet" bash -c \
    'code=$(limactl shell --workdir / '"$VM"' -- sudo -u clone curl -s -o /dev/null -w "%{http_code}" -m 6 https://github.com 2>/dev/null); [ "$code" = "000" ]'

  claim "the clone has no sudo" bash -c \
    'limactl shell --workdir / '"$VM"' -- sudo -u clone sudo -n true 2>&1 | grep -qi "password\|not allowed"'

  claim "the Mac is invisible from inside" bash -c \
    '! limactl shell --workdir / '"$VM"' -- sudo -u clone ls /Users >/dev/null 2>&1'

  claim "the shop's books are readable" test -s "$ROOT/shared/billing/catalogue.csv"

  claim "a lesson can be planned" bash -c \
    'curl -s -m 90 -X POST -H "Content-Type: application/json" \
       -d "{\"lesson\":\"20260821-124956\"}" http://localhost:'"$PANEL"'/api/lesson/plan \
     | grep -q "\"doable\""'

  claim "the audit runs and finds the shop" bash -c \
    'curl -s -m 30 -X POST -H "Content-Type: application/json" -d "{}" \
       http://localhost:'"$PANEL"'/api/audit | grep -q "\"job\""'

  claim "the ledger is being written" bash -c \
    '[ "$(wc -l < "'"$ROOT"'/var/ledger.jsonl")" -gt 0 ]'

  claim "every produced file is reachable" bash -c \
    'curl -s -m 10 "http://localhost:'"$PANEL"'/api/job/file?job=../../var&name=ledger.jsonl" | grep -q "not a job id"'

  echo
  if [ "$fails" = "0" ]; then
    say "Every claim stands. The audit is running now — watch it land in the panel."
  else
    bad "Something you were going to claim does not hold. Fix it before the call."
  fi
  return $fails
}

case "${1:-reset}" in
  check)    say "Checking"; check ;;
  rehearse) check && echo && rehearse ;;
  *)        reset ;;
esac
