#!/usr/bin/env bash
# Make the dashboard reachable from anywhere through a Cloudflare Quick Tunnel.
# Visitors sign in with the dashboard password, set on the dashboard at home.
# Emails are optional: they add Cloudflare's email-code gate in front, which is
# currently broken by cloudflared issue #1752 (login expires after seconds).
# Usage: ./deploy/install-tunnel.sh [you@example.com ...] [--port 8081]
set -euo pipefail

PORT=8081  # pianotrack run --tunnel-port: localhost only, always needs the password
EMAILS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        *@*) EMAILS+=("$1"); shift ;;
        *) echo "not an email: $1" >&2; exit 1 ;;
    esac
done

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
if [ ${#EMAILS[@]} -gt 0 ] && ! cloudflared tunnel --help 2>&1 | grep -q -- --allowed-mail; then
    echo "cloudflared $(cloudflared --version) has no --allowed-mail; 2026.9.3 or newer is needed" >&2
    echo "try: sudo apt-get update && sudo apt-get install --only-upgrade cloudflared" >&2
    exit 1
fi

sudo mkdir -p /etc/pianotrack
if [ ${#EMAILS[@]} -gt 0 ]; then
    printf '%s\n' "${EMAILS[@]}" | sudo tee /etc/pianotrack/allowed-emails >/dev/null
else
    : | sudo tee /etc/pianotrack/allowed-emails >/dev/null
fi
sed -e "s|@USER@|$RUN_USER|" -e "s|@DIR@|$DIR|" -e "s|@PORT@|$PORT|" \
    "$DIR/deploy/pianotrack-tunnel.service" | sudo tee /etc/systemd/system/pianotrack-tunnel.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable pianotrack-tunnel >/dev/null
# Stop first and clear the old URL so we don't report the previous tunnel's address.
sudo systemctl stop pianotrack-tunnel
sudo rm -f /var/lib/pianotrack/tunnel-url
sudo systemctl start pianotrack-tunnel

echo "Waiting for the tunnel URL..."
for _ in $(seq 30); do
    if [ -s /var/lib/pianotrack/tunnel-url ]; then
        echo "Dashboard from anywhere: $(cat /var/lib/pianotrack/tunnel-url)"
        if [ ${#EMAILS[@]} -gt 0 ]; then echo "Cloudflare email gate for: ${EMAILS[*]}"; fi
        echo "Visitors need the dashboard password. Set it at home: dashboard > Remote access."
        exit 0
    fi
    sleep 1
done
echo "No URL yet; check: journalctl -u pianotrack-tunnel -n 30" >&2
exit 1
