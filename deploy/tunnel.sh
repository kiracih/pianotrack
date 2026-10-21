#!/bin/sh
# Runs a Cloudflare Quick Tunnel to the dashboard and records its public URL so
# the dashboard can show it. Visitors must sign in with the dashboard password
# (the server refuses tunnel traffic until one is set). If emails are listed in
# /etc/pianotrack/allowed-emails, Cloudflare's email-code gate is added in front;
# note cloudflared issue #1752, which currently expires that login after seconds.
set -eu

EMAILS_FILE="${EMAILS_FILE:-/etc/pianotrack/allowed-emails}"
URL_FILE="${URL_FILE:-/var/lib/pianotrack/tunnel-url}"
PORT="${PORT:-8080}"

set --
if [ -f "$EMAILS_FILE" ]; then
    while read -r email; do
        case "$email" in ''|'#'*) continue ;; esac
        set -- "$@" --allowed-mail "$email"
    done < "$EMAILS_FILE"
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
