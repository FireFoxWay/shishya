#!/bin/bash
# ============================================================================
# SHISHYA — builds the clone's desktop, inside the VM.
#
# Runs once, on first `limactl start`. Everything here exists to give the
# clone a real GUI to work in and to give us two ways to see and drive it:
#
#   noVNC  (port 6080)  — the pixels, streamed into your browser
#   AT-SPI (port 7070)  — the accessibility tree: real widget names, roles
#                         and values, which is what the executor actually
#                         grounds on. Pixels are the fallback, not the plan.
# ============================================================================
set -euxo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update

# Virtual display + a window manager light enough to boot in a second.
# Openbox over anything heavier: fewer animations means less visual noise for
# the recorder, and window titles stay stable between runs.
apt-get install -y --no-install-recommends \
  xvfb x11vnc openbox xterm x11-utils xdotool scrot \
  novnc websockify \
  python3-pip python3-venv python3-tk \
  at-spi2-core python3-pyatspi gir1.2-atspi-2.0 \
  libreoffice-calc libreoffice-writer evince \
  fonts-dejavu-core

# ─── The clone's own account ────────────────────────────────────────────────
# A separate unprivileged user, no sudo. Even inside the sandbox the clone
# is not root — if the agent goes wrong we want it to fail small.
id clone &>/dev/null || useradd -m -s /bin/bash clone
install -d -o clone -g clone /home/clone/shared /home/clone/.config/openbox

# ─── Display, WM, VNC, noVNC ────────────────────────────────────────────────
# 1440x900 to match a laptop screen: taught procedures reference on-screen
# layout, so the resolution wants to stay fixed forever once we start
# recording. Changing it later invalidates recorded traces.
cat > /etc/systemd/system/shishya-display.service <<'UNIT'
[Unit]
Description=Shishya virtual display
[Service]
User=clone
Environment=DISPLAY=:0
ExecStart=/usr/bin/Xvfb :0 -screen 0 1440x900x24 -nolisten tcp
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/shishya-wm.service <<'UNIT'
[Unit]
Description=Shishya window manager
After=shishya-display.service
Requires=shishya-display.service
[Service]
User=clone
Environment=DISPLAY=:0
# AT-SPI is opt-in on most distros; without this the accessibility tree is
# empty and the executor is blind to everything but pixels.
Environment=GTK_MODULES=gail:atk-bridge
Environment=QT_ACCESSIBILITY=1
Environment=NO_AT_BRIDGE=0
ExecStart=/usr/bin/openbox
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/shishya-vnc.service <<'UNIT'
[Unit]
Description=Shishya VNC
After=shishya-wm.service
Requires=shishya-wm.service
[Service]
User=clone
Environment=DISPLAY=:0
# -shared so you can watch while the agent drives: take-the-wheel depends on
# host and agent holding the same session at once, not taking turns.
ExecStart=/usr/bin/x11vnc -display :0 -forever -shared -nopw -rfbport 5900 -noxdamage
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/shishya-novnc.service <<'UNIT'
[Unit]
Description=Shishya noVNC bridge
After=shishya-vnc.service
Requires=shishya-vnc.service
[Service]
ExecStart=/usr/bin/websockify --web=/usr/share/novnc 6080 localhost:5900
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now shishya-display shishya-wm shishya-vnc shishya-novnc

echo "shishya: desktop up on :0 — noVNC at http://localhost:6080/vnc.html"
