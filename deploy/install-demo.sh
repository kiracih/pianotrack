#!/usr/bin/env bash
# A public demo of the dashboard next to the real one: simulated practice, read-only,
# no password, on its own database, ports and Cloudflare Quick Tunnel (its own URL).
# The real service, its database and its tunnel are not touched.
# Usage: ./deploy/install-demo.sh [--port 8090] [--tunnel-port 8091]
#        ./deploy/install-demo.sh --remove
set -euo pipefail

PORT=8090
TUNNEL_PORT=8091
UNITS="pianotrack-demo pianotrack-demo-tunnel pianotrack-demo-rebuild.timer"
while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --tunnel-port) TUNNEL_PORT="$2"; shift 2 ;;
        --remove)
            sudo systemctl disable --now $UNITS 2>/dev/null || true
            for u in pianotrack-demo.service pianotrack-demo-tunnel.service \
                     pianotrack-demo-rebuild.service pianotrack-demo-rebuild.timer; do
                sudo rm -f "/etc/systemd/system/$u"
            done
            sudo systemctl daemon-reload
            echo "Demo removed (its data in /var/lib/pianotrack-demo can be deleted)."
            exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"

if ! command -v cloudflared >/dev/null; then
    echo "cloudflared is missing; ./deploy/install-tunnel.sh installs it" >&2
    exit 1
fi

for u in pianotrack-demo.service pianotrack-demo-tunnel.service \
         pianotrack-demo-rebuild.service pianotrack-demo-rebuild.timer; do
    sed -e "s|@USER@|$RUN_USER|" -e "s|@DIR@|$DIR|" -e "s|@PORT@|$PORT|" -e "s|@TUNNEL_PORT@|$TUNNEL_PORT|" \
        "$DIR/deploy/$u" | sudo tee "/etc/systemd/system/$u" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable pianotrack-demo pianotrack-demo-tunnel pianotrack-demo-rebuild.timer >/dev/null
sudo systemctl restart pianotrack-demo
sudo systemctl start pianotrack-demo-rebuild.timer
# Restarting the tunnel gives it a new address, so only start it when it is not running.
sudo systemctl start pianotrack-demo-tunnel

echo "Building the demo history (a few minutes on a Pi 4)..."
for _ in $(seq 600); do
    if curl -fs "http://127.0.0.1:$PORT/api/auth" >/dev/null; then break; fi
    sleep 1
done
for _ in $(seq 30); do
    if [ -s /var/lib/pianotrack-demo/tunnel-url ]; then
        echo "Demo at home: http://$(hostname).local:$PORT"
        echo "Demo from anywhere: $(cat /var/lib/pianotrack-demo/tunnel-url)"
        exit 0
    fi
    sleep 1
done
echo "No demo URL yet; check: journalctl -u pianotrack-demo-tunnel -n 30" >&2
exit 1
