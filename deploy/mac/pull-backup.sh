#!/bin/bash
# Pull the newest pianotrack backup from the Pi onto this Mac.
#
# Run by the launchd agent (com.pianotrack.backup.plist) at login, on wake and
# every hour. When the Pi can't be reached (Mac away from home, Pi off) it does
# nothing and the next run tries again, so a missed night is caught up as soon
# as both are on the home network. Each copy passes SQLite's integrity check
# before it replaces anything; the Mac keeps 7 daily and 4 weekly copies.
set -u

PI="${PIANOTRACK_PI:-raspberry@192.168.1.108}"
REMOTE_DIR="${PIANOTRACK_REMOTE_DIR:-/var/lib/pianotrack/backups}"
DEST="${PIANOTRACK_DEST:-$HOME/Backups/pianotrack}"
SSH="${PIANOTRACK_SSH:-ssh}"
KEEP_DAILY=7
KEEP_WEEKLY=4

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }
pi() { $SSH -o BatchMode=yes -o ConnectTimeout=10 "$PI" "$@"; }
prune() {  # keep the newest $2 files matching $1
    ls -1 "$DEST" | grep -E "$1" | sort -r | tail -n +"$(($2 + 1))" | while read -r f; do
        rm -f "$DEST/$f"
    done
}

mkdir -p "$DEST" || exit 1
newest=$(pi "ls -1 '$REMOTE_DIR' | grep -E '^daily-[0-9]{4}-[0-9]{2}-[0-9]{2}\.db\$' | sort | tail -n 1") \
    || exit 0  # Pi not reachable: try again next run
if [ -z "$newest" ]; then
    log "no backups on the Pi yet"
    exit 0
fi
sig=$(pi "stat -c '%Y %s' '$REMOTE_DIR/$newest'") || exit 0
if [ "$(cat "$DEST/.last-pull" 2>/dev/null)" = "$newest $sig" ]; then
    exit 0  # already have it
fi

tmp="$DEST/.incoming.db"
if ! pi "cat '$REMOTE_DIR/$newest'" > "$tmp"; then
    rm -f "$tmp"
    log "copy of $newest was interrupted; will try again"
    exit 0
fi
check=$(sqlite3 "$tmp" "PRAGMA integrity_check;" 2>&1)
sessions=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sessions;" 2>&1)
if [ "$check" != "ok" ] || ! [[ "$sessions" =~ ^[0-9]+$ ]]; then
    rm -f "$tmp"
    log "copy of $newest failed its check ($check $sessions); previous copies kept"
    exit 1
fi

day=${newest#daily-}
day=${day%.db}
week=$(date -j -f %Y-%m-%d "$day" +%G-W%V 2>/dev/null || date -d "$day" +%G-W%V)
mv -f "$tmp" "$DEST/$newest"
cp -f "$DEST/$newest" "$DEST/.weekly.tmp" && mv -f "$DEST/.weekly.tmp" "$DEST/weekly-$week.db"
prune '^daily-[0-9-]+\.db$' $KEEP_DAILY
prune '^weekly-[0-9]{4}-W[0-9]{2}\.db$' $KEEP_WEEKLY
echo "$newest $sig" > "$DEST/.last-pull"

# Tell the Pi, so its dashboard shows when the Mac last took a copy.
pi "echo '$(hostname -s) $newest' > '$REMOTE_DIR/offsite'" || log "copied, but could not tell the Pi"
log "copied $newest ($sessions sessions) to $DEST"
