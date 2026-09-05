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

# The sandbox must be able to resolve its own name without asking anyone.
# sudo does a lookup on the hostname; with egress locked that query goes
# nowhere and waits for the DNS timeout, so every single sudo took ten
# seconds. The control panel polls status every three, so requests piled up
# and the whole panel looked hung — the security feature strangling the
# interface that reports on it.
grep -q "127.0.1.1" /etc/hosts || echo "127.0.1.1 $(hostname)" >> /etc/hosts

apt-get update

# Virtual display + a window manager light enough to boot in a second.
# Openbox over anything heavier: fewer animations means less visual noise for
# the recorder, and window titles stay stable between runs.
apt-get install -y --no-install-recommends \
  xvfb x11vnc openbox xterm x11-utils xdotool scrot \
  novnc websockify \
  python3-pip python3-venv python3-tk \
  python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
  python3-openpyxl python3-docx python3-pandas \
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

# The display stack — Xvfb, openbox, x11vnc, the noVNC bridge — lives in its
# own script. This file runs exactly once per machine, so anything defined
# here can only be changed by rebuilding the VM; display.sh is idempotent and
# can be re-run against a machine that is up, which is what the panel's
# "Rebuild display" button now does.
bash /opt/shishya/vm/display.sh --all

# python-pptx is not packaged for 24.04. --break-system-packages is fine
# here and only here: this is a disposable sandbox whose entire filesystem is
# one `cp -c` away from being restored.
pip3 install --break-system-packages --quiet python-pptx || \
  echo "shishya: WARNING python-pptx unavailable — PowerPoint output disabled"

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

# Warm the model too, for the same reason LibreOffice is kept warm above.
# Ollama unloads a model five minutes after its last use; the owner's is
# 13.8GB and takes twenty to forty seconds to read back. This asks the host to
# load it the moment the sandbox is up, so the first question of a session is
# answered rather than waited on. Type=oneshot and it does not matter if it
# fails — a cold model is slow, not broken.
cat > /etc/systemd/system/shishya-warm.service <<'UNIT'
[Unit]
Description=Shishya model warm start
After=shishya-desktop.service
[Service]
Type=oneshot
User=clone
EnvironmentFile=/etc/shishya.env
WorkingDirectory=/opt/shishya/vm/shell
ExecStart=/usr/bin/python3 -c "import common; print('warm:', common.warm())"
TimeoutStartSec=330
[Install]
WantedBy=multi-user.target
UNIT

# The network lock, re-applied at every boot.
#
# nftables rules live in the running kernel and nowhere else, so a VM that
# came back from the Mac sleeping came back with no rules at all — open. The
# panel reported it honestly and that is the only reason it was ever noticed.
# Coming back locked is the safe default; coming back open is not.
#
# Before the network is up, so there is no window in which the sandbox is
# running and unlocked.
cat > /etc/systemd/system/shishya-egress.service <<'UNIT'
[Unit]
Description=Shishya network lock
DefaultDependencies=no
Before=network-pre.target
Wants=network-pre.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash /opt/shishya/vm/egress.sh
[Install]
WantedBy=sysinit.target
UNIT

# The desktop as a service, so it is restarted rather than remembered.
# Started by hand it stacked up silently — several desktops and several
# taskbars at once, each drawing over the last. systemd keeps exactly one.
cat > /etc/systemd/system/shishya-desktop.service <<'UNIT'
[Unit]
Description=Shishya desktop shell
After=shishya-wm.service
Requires=shishya-wm.service
# Never give up. The default start limit makes systemd stop retrying after a
# few quick failures, which is precisely when it is needed most. This lived
# under [Service] until now, where systemd does not look for it — it logged
# "Unknown key name ... ignoring" once per boot and gave up as usual.
StartLimitIntervalSec=0
[Service]
User=clone
EnvironmentFile=/etc/shishya.env
WorkingDirectory=/opt/shishya/vm/shell
ExecStart=/usr/bin/python3 /opt/shishya/vm/shell/desktop.py
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now shishya-dbus shishya-display shishya-atspi shishya-wm shishya-vnc shishya-novnc shishya-desktop shishya-warm shishya-egress

# GTK apps check this before exposing anything to AT-SPI.
sudo -u clone env DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/shishya-bus \
  gsettings set org.gnome.desktop.interface toolkit-accessibility true

# Loud on purpose. If this is false the accessibility tree is empty, the
# recorder captures nothing, and the failure is silent everywhere else.
echo -n "shishya: toolkit-accessibility = "
sudo -u clone env DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/shishya-bus \
  gsettings get org.gnome.desktop.interface toolkit-accessibility

echo "shishya: desktop up on :0 — noVNC at http://localhost:6080/vnc.html"

# One desktop, not openbox's four. The wheel over the desktop switches
# workspace by default, so a scroll that misses a window blanks the screen and
# looks exactly like the apps crashing — on a machine whose screen is watched
# through a video stream by people who cannot tell the difference.
sudo -u clone env HOME=/home/clone python3 /opt/shishya/vm/one-desktop.py || true
