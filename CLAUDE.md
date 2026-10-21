# pianotrack

Headless piano practice tracker for a Raspberry Pi (Roland FP-30X over USB). Pure Python stdlib, no pip dependencies; keep it that way.

## Every code change must also

1. Update README.md so it describes what the code does now: feature list, metrics table, API table, CLI options.
2. Regenerate the screenshots in docs/ when anything visible changes:
   ```
   python3 -m pianotrack --db /tmp/demo.db backfill --days 120 --seed 3 --beginner
   python3 -m pianotrack --db /tmp/demo.db run --no-collector --port 8099 &
   npm install --no-save playwright && node tools/screenshots.mjs http://localhost:8099
   ```
   Look at the images before committing.
3. Pass `python3 -m unittest discover -v tests`. `tests/test_docs.py` fails if an API route is missing from the README.

## Layout

- `pianotrack/collector.py` reads /dev/snd/midiC*D* directly; `midi.py` parses bytes and .mid files.
- `recorder.py` turns messages into sessions (180 s idle gap); `store.py` is SQLite.
- `metrics.py` computes per-session and daily metrics; `server.py` serves the API and `static/`.
- `static/index.html` is the dashboard; `static/replay.js` the replay player; `static/piano/` Salamander samples (CC-BY 3.0, keep ATTRIBUTION.md).
- `backup.py` makes the nightly rotated copies (7 daily + 4 weekly) and restores; `deploy/mac/` pulls them onto the user's Mac (launchd, hourly).
- `simulate.py` produces synthetic practice for tests and demos.
- `auth.py` is the password login for tunnel visitors (requests with Cf-Ray/Cf-Connecting-Ip headers); the home network needs none.
- `deploy/` holds install.sh + pianotrack.service, and install-tunnel.sh + tunnel.sh + pianotrack-tunnel.service for the Cloudflare Protected Quick Tunnel.
