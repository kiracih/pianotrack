#!/bin/sh
# Runs a Cloudflare Protected Quick Tunnel to the dashboard and records its
# public URL so the dashboard can show it. Only the emails listed in
# /etc/pianotrack/allowed-emails can sign in (Cloudflare sends them a code).
set -eu

EMAILS_FILE="${EMAILS_FILE:-/etc/pianotrack/allowed-emails}"
URL_FILE="${URL_FILE:-/var/lib/pianotrack/tunnel-url}"
PORT="${PORT:-8080}"

set --
while read -r email; do
    case "$email" in ''|'#'*) continue ;; esac
    set -- "$@" --allowed-mail "$email"
done < "$EMAILS_FILE"
if [ "$#" -eq 0 ]; then
    echo "no allowed emails in $EMAILS_FILE; refusing to start a public tunnel" >&2
    exit 1
fi

rm -f "$URL_FILE"
trap 'rm -f "$URL_FILE"' EXIT

# The quick tunnel's URL is random and only appears in cloudflared's log.
cloudflared tunnel --no-autoupdate --url "http://localhost:$PORT" "$@" 2>&1 |
while IFS= read -r line; do
    echo "$line"
    url=$(printf '%s\n' "$line" | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | head -n 1 || true)
    if [ -n "$url" ]; then
        printf '%s\n' "$url" > "$URL_FILE"
    fi
done
