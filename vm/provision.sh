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
  python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
  python3-openpyxl python3-docx \
  at-spi2-core python3-pyatspi gir1.2-atspi-2.0 \
  libreoffice-calc libreoffice-writer libreoffice-gtk3 evince poppler-utils \
  fonts-dejavu-core

# ─── The clone's own account ────────────────────────────────────────────────
# A separate unprivileged user, no sudo. Even inside the sandbox the clone
# is not root — if the agent goes wrong we want it to fail small.
id clone &>/dev/null || useradd -m -s /bin/bash clone

# Lima creates /home/clone first, as the parent of the virtiofs mount, so
# `useradd -m` finds it already there and leaves it owned by root. Without
# this the clone cannot write to its own home and nothing works.
# Non-recursive on purpose: -R would descend into the mount and fail.
chown clone:clone /home/clone
# .config too, recursively. Lima creates parts of the home before useradd
# runs, leaving directories owned by root — and LibreOffice refuses to start
# with "User installation could not be completed" when it cannot write its
# profile there. The message names nothing about permissions.
install -d -o clone -g clone /home/clone/.config
chown -R clone:clone /home/clone/.config

# NOT /home/clone/shared — that is the virtiofs mountpoint, and chowning a
# virtiofs mount fails with EPERM. Its ownership comes from the host side.
# dconf needs its directory to exist before gsettings can write anything,
# and without gsettings the toolkit-accessibility flag stays false — which
# leaves GTK apps registering with AT-SPI while exposing no widgets at all.
install -d -o clone -g clone /home/clone/.config/openbox /home/clone/.config/dconf

# ─── Display, WM, VNC, noVNC ────────────────────────────────────────────────
# 1440x900 to match a laptop screen: taught procedures reference on-screen
# layout, so the resolution wants to stay fixed forever once we start
# recording. Changing it later invalidates recorded traces.
# ─── One session bus, at an address everybody knows ─────────────────────────
# A headless systemd desktop has no D-Bus session bus, so at-spi-bus-launcher
# never starts and the accessibility tree comes back empty — which would leave
# the executor with nothing but pixels. Rather than let each process discover
# its own bus, we pin one at a fixed path and hand it to everything: the WM,
# the apps, and the recorder must all be on the SAME bus or they cannot see
# each other's widgets.
cat > /etc/shishya.env <<'ENV'
DISPLAY=:0
DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/shishya-bus
GTK_MODULES=atk-bridge
QT_ACCESSIBILITY=1
NO_AT_BRIDGE=0
GTK_A11Y=atspi
# LibreOffice defaults to its own VCL backend, which publishes nothing to
# AT-SPI. Forcing the GTK3 backend is what lets the recorder see inside Calc —
# and the clone has to learn in the same spreadsheet the person used.
SAL_USE_VCLPLUGIN=gtk3
ENV

cat > /etc/systemd/system/shishya-dbus.service <<'UNIT'
[Unit]
Description=Shishya session bus
[Service]
User=clone
ExecStartPre=/bin/rm -f /tmp/shishya-bus
ExecStart=/usr/bin/dbus-daemon --session --address=unix:path=/tmp/shishya-bus --nofork --nopidfile
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/shishya-atspi.service <<'UNIT'
[Unit]
Description=Shishya accessibility bus
After=shishya-dbus.service shishya-display.service
Requires=shishya-dbus.service
[Service]
User=clone
EnvironmentFile=/etc/shishya.env
ExecStart=/usr/libexec/at-spi-bus-launcher --launch-immediately
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/shishya-display.service <<'UNIT'
[Unit]
Description=Shishya virtual display
[Service]
User=clone
EnvironmentFile=/etc/shishya.env
StartLimitIntervalSec=0
ExecStart=/usr/bin/Xvfb :0 -screen 0 1440x900x24 -nolisten tcp
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/shishya-wm.service <<'UNIT'
[Unit]
Description=Shishya window manager
After=shishya-display.service shishya-atspi.service
Requires=shishya-display.service shishya-atspi.service
[Service]
User=clone
EnvironmentFile=/etc/shishya.env
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
EnvironmentFile=/etc/shishya.env
StartLimitIntervalSec=0
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

# python-pptx is not packaged for 24.04. --break-system-packages is fine
# here and only here: this is a disposable sandbox whose entire filesystem is
# one `cp -c` away from being restored.
pip3 install --break-system-packages --quiet python-pptx || \
  echo "shishya: WARNING python-pptx unavailable — PowerPoint output disabled"

# The desktop itself is a service, not something launched from a shell.
# Launching it over `limactl shell` never detached cleanly, so restarts left
# duplicates stacked on top of each other — two desktops, two taskbars, and
# clicks landing on whichever one happened to be on top.
cat > /etc/systemd/system/shishya-desktop.service <<'UNIT'
[Unit]
Description=Shishya desktop shell
After=shishya-wm.service shishya-atspi.service
Requires=shishya-wm.service
[Service]
User=clone
EnvironmentFile=/etc/shishya.env
WorkingDirectory=/opt/shishya/vm/shell
ExecStart=/usr/bin/python3 /opt/shishya/vm/shell/desktop.py
Restart=always
RestartSec=2
[Install]
WantedBy=multi-user.target
UNIT

# Create the LibreOffice profile once, then silence its welcome dialogs. Doing
# it at provisioning time means the first launch anyone sees is already quiet.
sudo -u clone env DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/shishya-bus \
  timeout 90 libreoffice --headless --terminate_after_init >/dev/null 2>&1 || true
sudo -u clone python3 /opt/shishya/vm/lo-quiet.py || true

# Keep LibreOffice warm. Cold, it takes about 45 seconds to put a window on
# screen; with the process already resident it is about two. Opening a file
# the clone just produced is the moment someone is watching, and the clone
# itself will be launching Calc unattended — neither can afford the wait.
cat > /etc/systemd/system/shishya-office.service <<'UNIT'
[Unit]
Description=Shishya LibreOffice warm start
After=shishya-wm.service
Requires=shishya-wm.service
[Service]
User=clone
EnvironmentFile=/etc/shishya.env
ExecStart=/usr/bin/libreoffice --calc --norestore --nologo
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
UNIT

# The desktop as a service, so it is restarted rather than remembered.
# Started by hand it stacked up silently — several desktops and several
# taskbars at once, each drawing over the last. systemd keeps exactly one.
cat > /etc/systemd/system/shishya-desktop.service <<'UNIT'
[Unit]
Description=Shishya desktop shell
After=shishya-wm.service
Requires=shishya-wm.service
[Service]
User=clone
EnvironmentFile=/etc/shishya.env
WorkingDirectory=/opt/shishya/vm/shell
ExecStart=/usr/bin/python3 /opt/shishya/vm/shell/desktop.py
Restart=always
RestartSec=3
# Never give up. The default start limit makes systemd stop retrying after a
# few quick failures, which is precisely when it is needed most.
StartLimitIntervalSec=0
[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now shishya-dbus shishya-display shishya-atspi shishya-wm shishya-vnc shishya-novnc shishya-desktop shishya-desktop

# GTK apps check this before exposing anything to AT-SPI.
sudo -u clone env DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/shishya-bus \
  gsettings set org.gnome.desktop.interface toolkit-accessibility true

# Loud on purpose. If this is false the accessibility tree is empty, the
# recorder captures nothing, and the failure is silent everywhere else.
echo -n "shishya: toolkit-accessibility = "
sudo -u clone env DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/shishya-bus \
  gsettings get org.gnome.desktop.interface toolkit-accessibility

echo "shishya: desktop up on :0 — noVNC at http://localhost:6080/vnc.html"
