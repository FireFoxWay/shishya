#!/bin/bash
# ============================================================================
# SHISHYA — the display stack: Xvfb, openbox, x11vnc, noVNC.
#
# Split out of provision.sh so it can be re-run. provision.sh is one-shot
# (`[ -f /var/lib/shishya-provisioned ] && exit 0`), which meant every tuning
# change to the screen needed the whole VM rebuilt — an hour, to change one
# flag on one service. This is idempotent and safe to run against a machine
# that is up and working:
#
#   bash /opt/shishya/vm/display.sh            # rewrite config, restart VNC only
#   bash /opt/shishya/vm/display.sh --all      # also restart X and the WM
#
# Without --all the clone's open apps and documents survive: only the path
# between your eyes and the screen is rebuilt. With --all the X server itself
# restarts, and everything the clone had open dies with it.
# ============================================================================
set -euo pipefail

ALL=no
[ "${1:-}" = "--all" ] && ALL=yes

# ─── The virtual screen ─────────────────────────────────────────────────────
# 1440x900 to match a laptop screen, and pinned: taught procedures reference
# on-screen layout, so changing the resolution invalidates every recorded
# trace. This is why noVNC is told to scale in the browser rather than ask the
# server to resize — a fit-to-window resize would silently break the lessons.
#
#   -noreset   an X server resets when its last client exits, wiping the
#              root window and every server-side resource. On a machine where
#              the shell is restarted by systemd that is a race waiting to
#              happen; -noreset makes the display outlive its clients.
#   -s 0       never blank. MIT-SCREEN-SAVER is compiled in, and a screen that
#              goes black after ten idle minutes is indistinguishable, over a
#              video stream, from the sandbox having crashed.
#   -dpi 96    fixed font scaling, for the same reason the resolution is fixed.
cat > /etc/systemd/system/shishya-display.service <<'UNIT'
[Unit]
Description=Shishya virtual display
StartLimitIntervalSec=0
[Service]
User=clone
EnvironmentFile=/etc/shishya.env
ExecStart=/usr/bin/Xvfb :0 -screen 0 1440x900x24 -nolisten tcp -noreset -s 0 -dpi 96
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/shishya-wm.service <<'UNIT'
[Unit]
Description=Shishya window manager
After=shishya-display.service shishya-atspi.service
Requires=shishya-display.service shishya-atspi.service
StartLimitIntervalSec=0
[Service]
User=clone
EnvironmentFile=/etc/shishya.env
ExecStart=/usr/bin/openbox
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

# ─── The VNC server ─────────────────────────────────────────────────────────
#   -shared      so you can watch while the agent drives: take-the-wheel
#                depends on host and agent holding the same session at once,
#                not taking turns.
#
#   XDAMAGE      this used to run with -noxdamage, which turns off the X
#                extension that reports which rectangles changed and leaves
#                x11vnc scanning the whole 1440x900 framebuffer on a timer
#                looking for differences. DAMAGE is present on this Xvfb
#                (xdpyinfo lists it) and works; the flag is gone.
#
#   -nolookup    x11vnc does a reverse DNS lookup on every client that
#                connects. The egress lock drops outbound DNS, so that query
#                does not fail — it waits for the resolver to time out, and
#                the screen stays blank for the whole of it. The same failure
#                mode as the sudo hostname lookup dealt with in provision.sh:
#                the security feature strangling the thing that reports on it.
#
#   -wait/-defer 20ms rather than the 30ms default, in both directions. With
#                damage tracking on, an idle screen now costs nothing to poll,
#                so the budget is better spent on latency.
#
#   -nodpms      belt and braces with Xvfb's -s 0: nothing may blank a screen
#                that is being watched.
#
#   No -threads. It would stop a large screen update from blocking input
#   delivery, which is the exact symptom that has bitten this project twice —
#   but x11vnc 0.9.16's threaded mode is known to race, and trading a
#   reproducible stall for an unreproducible one is not an improvement.
cat > /etc/systemd/system/shishya-vnc.service <<'UNIT'
[Unit]
Description=Shishya VNC
After=shishya-wm.service
Requires=shishya-wm.service
StartLimitIntervalSec=0
[Service]
User=clone
EnvironmentFile=/etc/shishya.env
ExecStart=/usr/bin/x11vnc -display :0 -forever -shared -nopw -rfbport 5900 \
          -nolookup -nodpms -wait 20 -defer 20 -q
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

# ─── The browser bridge ─────────────────────────────────────────────────────
# --heartbeat: a WebSocket ping every 30s. The connection reaches the browser
# through WSL's localhost forwarding, and a silent one gets reaped by the relay
# after an idle spell — the screen then freezes on its last frame rather than
# reporting that it has gone, which is the worst way for it to fail.
cat > /etc/systemd/system/shishya-novnc.service <<'UNIT'
[Unit]
Description=Shishya noVNC bridge
After=shishya-vnc.service
Requires=shishya-vnc.service
StartLimitIntervalSec=0
[Service]
ExecStart=/usr/bin/websockify --web=/usr/share/novnc --heartbeat=30 6080 localhost:5900
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

# ─── Fewer pixels to send ───────────────────────────────────────────────────
# Everything drawn on this desktop becomes a rectangle x11vnc has to encode
# and ship. Animation is the expensive kind: it never stops, so the stream
# never goes quiet. GTK's fades and slides are invisible flourishes locally
# and a permanent bitrate floor over VNC.
install -d -o clone -g clone /home/clone/.config/gtk-3.0
cat > /home/clone/.config/gtk-3.0/settings.ini <<'INI'
[Settings]
gtk-enable-animations=0
gtk-primary-button-warps-slider=false
INI
chown clone:clone /home/clone/.config/gtk-3.0/settings.ini

# Openbox redraws a window's contents continuously while it is being dragged
# or resized, which turns one gesture into a few hundred full-window updates.
# Outlines instead: the same gesture, one rectangle.
RC=/home/clone/.config/openbox/rc.xml
if [ -f "$RC" ] && grep -q "<drawContents>yes</drawContents>" "$RC"; then
  sed -i 's|<drawContents>yes</drawContents>|<drawContents>no</drawContents>|' "$RC"
fi

# noVNC asks for its own package.json on every load to show a version number
# in its About panel, and Debian's package strips that file. The fetch 404s
# and noVNC logs "Couldn't fetch package.json" as an ERROR to the browser
# console — so anyone who opens the console while debugging the screen is
# greeted by a red line about a missing file that was never going to be there.
# One small file, and the console is quiet enough to be worth reading.
if [ ! -f /usr/share/novnc/package.json ]; then
  V=$(dpkg-query -W -f='${Version}' novnc 2>/dev/null | sed 's/^[0-9]*://;s/-.*//')
  printf '{"name":"@novnc/novnc","version":"%s"}\n' "${V:-1.3.0}" \
    > /usr/share/novnc/package.json
fi

systemctl daemon-reload

if [ "$ALL" = yes ]; then
  systemctl restart shishya-display shishya-wm shishya-vnc shishya-novnc
else
  # Stopping the units is not enough — websockify leaves children behind and
  # those are what hold the bad state — so strays are killed by name first.
  systemctl stop shishya-novnc shishya-vnc || true
  pkill -9 -f websockify || true
  pkill -9 -x x11vnc || true
  sleep 1
  systemctl start shishya-vnc
  sleep 1
  systemctl start shishya-novnc
fi

echo "shishya: display stack applied ($([ "$ALL" = yes ] && echo "full restart" || echo "vnc only"))"
