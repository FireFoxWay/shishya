#!/bin/bash
# ============================================================================
# SHISHYA — re-apply the network lock at boot.
#
# Why this file exists, and it is worth reading before deleting it:
#
# nftables rules live in the running kernel and nowhere else. Nothing was
# re-applying them when the machine came up, so every time the laptop slept — and
# it sleeps often — the VM stopped, came back, and came back OPEN. The panel
# reported that honestly, because it reads the lock from the guest rather than
# remembering what it was told, which is the only reason anyone noticed.
#
# "Nothing leaves this laptop" is the central claim of the project and the one
# a judge can test in ten seconds. Until now it was a step somebody had to
# remember while nervous. It is a property of the machine now.
#
# Three modes, and this file is the only place any of them is written down:
#
#   egress.sh            locked — everything outbound dropped except the model
#   egress.sh web        browsing — DNS and 80/443 as well, and nothing else
#   egress.sh ssh        ssh — DNS and 22 as well, and nothing else
#
# host/vm.py runs this for every change the panel makes. The rules used to be
# spelled out there too, three times, with the host's address fixed; under
# WSL that address changes whenever Windows restarts, so it is looked up here
# at the moment the rules go on.
#
# Browsing and SSH are deliberate, temporary states — and neither survives a
# reboot, which is correct. Coming back locked is the safe default; coming
# back open is not.
# ============================================================================
set -euo pipefail

MODE="${1:-locked}"
case "$MODE" in
  locked|web|ssh) ;;
  *) echo "shishya: unknown egress mode '$MODE' — rules left as they were" >&2
     exit 2 ;;
esac
OLLAMA_PORT="${SHISHYA_OLLAMA_PORT:-11434}"

# WSL's NAT makes Windows the guest's default gateway. Waited for briefly,
# because at boot this can run a moment before eth0 has its route.
HOST_IP="${SHISHYA_HOST_IP:-}"
for _ in $(seq 1 20); do
  [ -n "$HOST_IP" ] && break
  HOST_IP=$(ip -4 route show default 2>/dev/null | awk '{print $3; exit}' || true)
  [ -n "$HOST_IP" ] || sleep 0.5
done

nft flush ruleset
nft add table inet shishya
nft add chain inet shishya out "{ type filter hook output priority 0; policy drop; }"

# Replies to connections we already made. Without this the model answers once
# and then hangs, because the return path is dropped.
nft add rule inet shishya out ct state established,related accept

# WSL's DNS tunnel. Newer WSL answers DNS at 10.255.255.254, an address on the
# guest's own loopback, and relays each query to Windows' resolver over a
# channel nftables never sees. Left alone, the loopback rule below would let
# a locked sandbox resolve any name on the internet — which is enough to
# carry data out, one query at a time. Dropped unless browsing or SSH asked
# for DNS.
if [ "$MODE" = locked ]; then
  nft add rule inet shishya out ip daddr 10.255.255.254 drop
fi

# The machine talking to itself: the panel, the noVNC bridge, the AT-SPI bus.
nft add rule inet shishya out oifname lo accept

# The one exception. The model runs on Windows because inside the sandbox it
# would have no GPU and be far too slow to use. Without a gateway there is no
# host to except, and the lock goes on without it: failing closed means the
# model is unreachable, which is loud; failing open would be silent.
if [ -n "$HOST_IP" ]; then
  nft add rule inet shishya out ip daddr "$HOST_IP" tcp dport "$OLLAMA_PORT" accept
else
  echo "shishya: no default route — locked with no exception for the model" >&2
fi

case "$MODE" in
  locked) ;;
  web)
    nft add rule inet shishya out udp dport 53 accept
    nft add rule inet shishya out tcp dport 53 accept
    nft add rule inet shishya out tcp dport "{ 80, 443 }" accept ;;
  ssh)
    nft add rule inet shishya out udp dport 53 accept
    nft add rule inet shishya out tcp dport 53 accept
    nft add rule inet shishya out tcp dport 22 accept ;;
esac

echo "shishya: egress $MODE — model at ${HOST_IP:-<none>}:${OLLAMA_PORT}"
