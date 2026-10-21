#!/usr/bin/env bash
# Install pianotrack as a systemd service on a Raspberry Pi (or any Linux box).
# Usage: ./deploy/install.sh [port]
set -euo pipefail

PORT="${1:-8080}"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"

python3 - <<'PY'
import sys
if sys.version_info < (3, 9):
    sys.exit("pianotrack needs Python 3.9 or newer")
PY

echo "Installing pianotrack from $DIR for user $RUN_USER on port $PORT"
sudo usermod -aG audio "$RUN_USER"
sed -e "s|@USER@|$RUN_USER|" -e "s|@DIR@|$DIR|" -e "s|@PORT@|$PORT|" \
    "$DIR/deploy/pianotrack.service" | sudo tee /etc/systemd/system/pianotrack.service >/dev/null
# Make time-sync.target actually wait for NTP (systemd-timesyncd) at boot.
if systemctl list-unit-files systemd-time-wait-sync.service >/dev/null 2>&1; then
    sudo systemctl enable systemd-time-wait-sync.service >/dev/null 2>&1 || true
fi
sudo systemctl daemon-reload
sudo systemctl enable --now pianotrack
sudo systemctl restart pianotrack
sleep 2
sudo systemctl --no-pager --lines=5 status pianotrack || true

echo
echo "MIDI devices seen right now:"
python3 -m pianotrack devices || true
echo
echo "Dashboard: http://$(hostname).local:$PORT  (or http://$(hostname -I | awk '{print $1}'):$PORT)"
echo "Logs:      journalctl -u pianotrack -f"
