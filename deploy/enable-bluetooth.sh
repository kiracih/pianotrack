#!/usr/bin/env bash
# Turn on the Pi's Bluetooth radio for pianotrack's BLE MIDI fallback.
# Raspberry Pi OS often ships with Bluetooth soft-blocked by rfkill. This
# unblocks it (systemd-rfkill keeps the choice across reboots), powers the
# controller on, and pairs the piano ("Just Works", no PIN) if it is in range
# with its Bluetooth on and no phone connected. pianotrack also pairs on its
# first Bluetooth connection if this step is skipped.
# Usage: ./deploy/enable-bluetooth.sh
set -euo pipefail

for r in /sys/class/rfkill/rfkill*; do
    [ "$(cat "$r/type" 2>/dev/null)" = bluetooth ] || continue
    if [ "$(cat "$r/soft")" = 1 ]; then
        echo "unblocking $(cat "$r/name")"
        echo 0 | sudo tee "$r/soft" >/dev/null
    fi
done
sleep 1
bluetoothctl power on || true
bluetoothctl show | grep -E 'Powered|PowerState' || true
echo
cd "$(dirname "$0")/.."
python3 -m pianotrack devices --pair || true
echo
echo "Restart the service to pick it up: sudo systemctl restart pianotrack"
