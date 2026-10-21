#!/bin/bash
# Install the launchd agent that copies the Pi's backups to this Mac.
# Usage: ./deploy/mac/install.sh [user@pi-address]
# Needs the SSH key that already logs in to the Pi without a password.
set -euo pipefail

PI="${1:-raspberry@192.168.1.108}"
HERE="$(cd "$(dirname "$0")" && pwd)"
AGENT="$HOME/Library/LaunchAgents/com.pianotrack.backup.plist"
LOG="$HOME/Library/Logs/pianotrack-backup.log"

if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$PI" true; then
    echo "Can't log in to $PI with a key; fix that first (ssh-copy-id $PI)." >&2
    exit 1
fi
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
sed -e "s|@SCRIPT@|$HERE/pull-backup.sh|" -e "s|@PI@|$PI|" -e "s|@LOG@|$LOG|" \
    "$HERE/com.pianotrack.backup.plist" > "$AGENT"
launchctl bootout "gui/$(id -u)" "$AGENT" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$AGENT"
sleep 5
tail -n 3 "$LOG" 2>/dev/null || true
echo "Copies go to ~/Backups/pianotrack. Log: $LOG"
echo "Remove with: launchctl bootout gui/$(id -u) $AGENT && rm $AGENT"
