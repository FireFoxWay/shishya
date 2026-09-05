#!/bin/bash
# ============================================================================
# SHISHYA — re-apply the network lock at boot.
#
# Why this file exists, and it is worth reading before deleting it:
#
# nftables rules live in the running kernel and nowhere else. Nothing was
# re-applying them when the machine came up, so every time the Mac slept — and
# it sleeps often — the VM stopped, came back, and came back OPEN. The panel
# reported that honestly, because it reads the lock from the guest rather than
# remembering what it was told, which is the only reason anyone noticed.
#
# "Nothing leaves this laptop" is the central claim of the project and the one
# a judge can test in ten seconds. Until now it was a step somebody had to
# remember while nervous. It is a property of the machine now.
#
# Locked means: everything outbound dropped, except the host's model.
# Browsing mode and SSH mode are deliberate, temporary states switched on from
# the panel — and neither survives a reboot either, which is correct. Coming
# back locked is the safe default; coming back open is not.
# ============================================================================
set -euo pipefail

# Lima's vz NAT puts the host at .2 on the guest's subnet. Kept in step with
# HOST_IP / OLLAMA_PORT in host/vm.py — if one changes, change both.
HOST_IP="${SHISHYA_HOST_IP:-192.168.5.2}"
OLLAMA_PORT="${SHISHYA_OLLAMA_PORT:-11434}"

nft flush ruleset
nft add table inet shishya
nft add chain inet shishya out "{ type filter hook output priority 0; policy drop; }"

# Replies to connections we already made. Without this the model answers once
# and then hangs, because the return path is dropped.
nft add rule inet shishya out ct state established,related accept

# The machine talking to itself: the panel, the noVNC bridge, the AT-SPI bus.
nft add rule inet shishya out oifname lo accept

# The one exception. The model runs on the host because inside the VM it would
# fall back to emulated CPU and be far too slow to use.
nft add rule inet shishya out ip daddr "$HOST_IP" tcp dport "$OLLAMA_PORT" accept

echo "shishya: egress locked — outbound dropped except ${HOST_IP}:${OLLAMA_PORT}"
