#!/usr/bin/env bash
# Make the dashboard reachable from anywhere through a Cloudflare Protected
# Quick Tunnel. Only the given emails can sign in.
# Usage: ./deploy/install-tunnel.sh you@example.com [other@example.com ...] [--port 8080]
set -euo pipefail

PORT=8080
EMAILS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        *@*) EMAILS+=("$1"); shift ;;
        *) echo "not an email: $1" >&2; exit 1 ;;
    esac
done
if [ ${#EMAILS[@]} -eq 0 ]; then
    echo "usage: $0 you@example.com [more emails] [--port 8080]" >&2
    exit 1
fi

DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"

if ! command -v cloudflared >/dev/null; then
    echo "Installing cloudflared from Cloudflare's apt repository"
    sudo mkdir -p --mode=0755 /usr/share/keyrings
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" |
        sudo tee /etc/apt/sources.list.d/cloudflared.list >/dev/null
    sudo apt-get update -qq && sudo apt-get install -y -qq cloudflared
fi
if ! cloudflared tunnel --help 2>&1 | grep -q -- --allowed-mail; then
    echo "cloudflared $(cloudflared --version) has no --allowed-mail; 2026.9.3 or newer is needed" >&2
    echo "try: sudo apt-get update && sudo apt-get install --only-upgrade cloudflared" >&2
    exit 1
fi

sudo mkdir -p /etc/pianotrack
printf '%s\n' "${EMAILS[@]}" | sudo tee /etc/pianotrack/allowed-emails >/dev/null
sed -e "s|@USER@|$RUN_USER|" -e "s|@DIR@|$DIR|" -e "s|@PORT@|$PORT|" \
    "$DIR/deploy/pianotrack-tunnel.service" | sudo tee /etc/systemd/system/pianotrack-tunnel.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable pianotrack-tunnel >/dev/null
sudo systemctl restart pianotrack-tunnel

echo "Waiting for the tunnel URL..."
for _ in $(seq 30); do
    if [ -s /var/lib/pianotrack/tunnel-url ]; then
        echo "Dashboard from anywhere: $(cat /var/lib/pianotrack/tunnel-url)"
        echo "Allowed to sign in: ${EMAILS[*]}"
        exit 0
    fi
    sleep 1
done
echo "No URL yet; check: journalctl -u pianotrack-tunnel -n 30" >&2
exit 1
