#!/bin/bash
# ============================================================================
# SHISHYA — get to a known-good demo state, in one command.
#
#     ./demo.sh          reset everything and open the panel
#     ./demo.sh check    check without changing anything
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
  local vnc web
  vnc=$(inguest pgrep -c x11vnc || echo 0)
  web=$(inguest pgrep -cf "websockify --web" || echo 0)
  [ "$vnc" = "1" ] && ok "one x11vnc" || { bad "$vnc x11vnc processes (want 1)"; fails=1; }
  [ "$web" -le 2 ] && ok "$web websockify" || { bad "$web websockify processes — input will be dead"; fails=1; }

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

  say "Restarting the desktop"
  inguest sudo pkill -u clone -f "_app.py"
  inguest sudo systemctl restart shishya-desktop
  sleep 4

  say "Restarting the control panel"
  pkill -f "serve.py $PANEL" 2>/dev/null
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
  say "Reload the page, then press TAKE THE WHEEL before clicking in the sandbox."
}

case "${1:-reset}" in
  check) say "Checking"; check ;;
  *)     reset ;;
esac
