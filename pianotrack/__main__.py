"""Command line entry point: python -m pianotrack <command>."""

import argparse
import logging
import os
import random
import signal
import sys
import threading
import time

from . import __version__, backup, pieces, recompute, simulate
from .collector import Collector, find_device
from .midi import read_smf
from .recorder import Recorder
from .server import Api, make_server
from .store import Store

DEFAULT_DB = os.environ.get("PIANOTRACK_DB", os.path.expanduser("~/.local/share/pianotrack/pianotrack.db"))
DEFAULT_BACKUP_DIR = os.environ.get("PIANOTRACK_BACKUP_DIR") or None


def _store(args):
    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    return Store(args.db)


def cmd_run(args):
    store = _store(args)
    # Before the collector starts writing: sessions stored under an older formula
    # are brought up to date once (a checked copy of the database is kept first).
    recompute.recompute(store, args.db)
    collector = None if args.no_collector else Collector(store, args.device, args.idle_gap)
    backups = None if args.no_backup else backup.Backups(args.db, args.backup_dir, args.backup_time)
    api = Api(store, collector, backups)
    threading.Thread(target=api.pieces, daemon=True).start()  # first pieces pass is slow
    servers = [make_server(api, args.host, args.port, allowed_hosts=args.allowed_host)]
    logging.info("dashboard on http://%s:%d", args.host, args.port)
    if args.tunnel_port:
        # Only this machine can reach it; cloudflared forwards here and every
        # request is treated as remote, so it always needs the password.
        servers.append(make_server(api, "127.0.0.1", args.tunnel_port, tunnel=True))
        logging.info("tunnel entrance on http://127.0.0.1:%d", args.tunnel_port)
    for httpd in servers:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

    stop = threading.Event()
    if backups:
        threading.Thread(target=backups.loop, args=(stop,), daemon=True).start()
        logging.info("nightly backups at %s into %s", args.backup_time, backups.dir)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: (collector and collector.stop(), stop.set()))
    if collector:
        collector.run()  # returns after stop(), closing any open session
    else:
        stop.wait()
    for httpd in servers:
        httpd.shutdown()
    store.close()


def cmd_devices(args):
    import glob
    from .collector import card_name
    devices = sorted(glob.glob("/dev/snd/midiC*D*"))
    if not devices:
        print("no raw MIDI devices found under /dev/snd (is the piano on and plugged in?)")
    for d in devices:
        print(f"{d}\t{card_name(d)}")
    chosen = find_device(args.device)
    print(f"would use: {chosen}")


def cmd_backfill(args):
    store = _store(args)
    ids = simulate.backfill(store, days=args.days, seed=args.seed, beginner=args.beginner)
    print(f"created {len(ids)} simulated sessions over {args.days} days in {args.db}")


def cmd_simulate(args):
    rng = random.Random(args.seed)
    events = simulate.practice_session(rng, args.minutes, skill=args.skill, beginner=args.beginner)
    if args.out:
        simulate.save_mid(args.out, events)
        print(f"wrote {args.out}")
        return
    print(f"streaming {args.minutes} min of practice into {args.fifo} at {args.speed}x")
    simulate.stream_to_fifo(args.fifo, events, speed=args.speed)


def cmd_replay(args):
    events = read_smf(args.file)
    if args.fifo:
        simulate.stream_to_fifo(args.fifo, events, speed=args.speed)
        return
    store = _store(args)
    rec = Recorder(store, idle_gap=args.idle_gap, source=os.path.basename(args.file))
    t0 = args.start if args.start else time.time() - (events[-1][0] if events else 0)
    sid = simulate.feed(rec, events, t0)
    print(f"stored session {sid}" if sid else "too few notes, nothing stored")


def cmd_backup(args):
    b = backup.Backups(args.db, args.backup_dir)
    try:
        path = b.run()
    except Exception as e:
        sys.exit(f"backup failed: {e}")
    st = b.status()
    print(f"wrote {path} ({st['daily']} daily, {st['weekly']} weekly copies in {b.dir})")
    if not st["off_card"]:
        print("note: this folder is on the same disk as the database; use --backup-dir "
              "on a USB stick or another machine so a dead SD card does not take both")


def cmd_restore(args):
    try:
        sessions, saved = backup.restore(args.file, args.db, force=args.force)
    except ValueError as e:
        sys.exit(f"restore refused: {e}")
    if saved:
        print(f"previous database kept as {saved}")
    print(f"restored {sessions} sessions from {args.file} into {args.db}")


def cmd_recompute(args):
    store = _store(args)
    try:
        n, copy = recompute.recompute(store, args.db, dry_run=args.dry_run)
    finally:
        store.close()
    if args.dry_run:
        print(f"{n} sessions would be recomputed")
    elif n:
        print(f"recomputed {n} sessions; the database from before is kept as {copy}")
    else:
        print("every session is up to date")


def cmd_pieces(args):
    if args.check:
        from datetime import datetime
        logging.getLogger("pianotrack.recorder").setLevel(logging.WARNING)
        store, log, days = Store(":memory:"), [], args.days or 30
        simulate.backfill(store, days=days, seed=args.seed, beginner=True, log=log,
                          now=datetime(2026, 1, 1, 22))
        matcher, segs = pieces.group(store)
        print(pieces.format_report(matcher, segs))
        r = pieces.evaluate(matcher, segs, log, simulate.REPERTOIRE)
        ok = r["right"] >= 0.9 and r["wrong"] < 0.05
        print(f"\nsimulated beginner, {days} days, seed {args.seed}: "
              f"{r['piece_segments']} piece segments, {r['right']:.1%} on the right piece, "
              f"{r['wrong']:.1%} of all segments on a wrong one; groups per piece "
              f"{r['groups_per_piece']}. Gate (>= 90% right, < 5% wrong): {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1
    if not os.path.exists(args.db):
        sys.exit(f"no database at {args.db}")
    store = Store(args.db, readonly=True)  # grouping is computed, never stored
    since = time.time() - args.days * 86400 if args.days else None
    matcher, segs = pieces.group(store, since=since)
    print(pieces.format_report(matcher, segs))
    if args.sessions:
        labels = {r["index"]: r["label"] for r in pieces.pieces_report(matcher)}
        print()
        for s in segs:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(s["start"]))
            print(f"session {s['session']:>5}  {when}  {(s['end'] - s['start']) / 60:5.1f} min  "
                  f"{labels.get(s['piece'], '-')}")
    store.close()


def cmd_vectors(args):
    from . import vectors
    for path in vectors.write_all(args.out):
        print(f"wrote {path} ({os.path.getsize(path) // 1024} KB)")


def main(argv=None):
    p = argparse.ArgumentParser(prog="pianotrack", description="Piano practice tracker")
    p.add_argument("--db", default=DEFAULT_DB, help="SQLite file (default %(default)s)")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="collect MIDI and serve the dashboard")
    r.add_argument("--device", help="ALSA card name regex, or a path such as a FIFO")
    r.add_argument("--host", default="0.0.0.0")
    r.add_argument("--port", type=int, default=8080)
    r.add_argument("--tunnel-port", type=int, default=8081,
                   help="localhost-only port for cloudflared, always behind the password (0: off)")
    r.add_argument("--allowed-host", action="append", default=[], metavar="NAME",
                   help="extra host name the home network may use for the dashboard (repeatable)")
    r.add_argument("--idle-gap", type=float, default=180.0,
                   help="seconds of silence that end a session")
    r.add_argument("--no-collector", action="store_true", help="dashboard only")
    r.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR,
                   help="folder for nightly copies, ideally off the SD card "
                        "(default: backups/ next to the database)")
    r.add_argument("--backup-time", default="03:30", help="local time of the nightly copy (HH:MM)")
    r.add_argument("--no-backup", action="store_true", help="no nightly copies")
    r.set_defaults(func=cmd_run)

    bk = sub.add_parser("backup", help="copy the database into the backup folder now")
    bk.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    bk.set_defaults(func=cmd_backup)

    rs = sub.add_parser("restore", help="replace the database with a backup copy")
    rs.add_argument("file", help="a backup .db file")
    rs.add_argument("--force", action="store_true", help="replace a database that has sessions")
    rs.set_defaults(func=cmd_restore)

    rc = sub.add_parser("recompute", help="update stored session metrics after a formula change "
                                         "(run does this at start; a copy is kept first)")
    rc.add_argument("--dry-run", action="store_true", help="only count the sessions")
    rc.set_defaults(func=cmd_recompute)

    d = sub.add_parser("devices", help="list MIDI devices")
    d.add_argument("--device")
    d.set_defaults(func=cmd_devices)

    b = sub.add_parser("backfill", help="fill the database with simulated history")
    b.add_argument("--days", type=int, default=30)
    b.add_argument("--seed", type=int)
    b.add_argument("--beginner", action="store_true",
                   help="play a fixed repertoire with a learner's mistakes")
    b.set_defaults(func=cmd_backfill)

    s = sub.add_parser("simulate", help="play synthetic practice into a FIFO or .mid")
    s.add_argument("--fifo", default="/tmp/pianotrack.fifo")
    s.add_argument("--out", help="write a .mid file instead of streaming")
    s.add_argument("--minutes", type=float, default=5)
    s.add_argument("--speed", type=float, default=1.0)
    s.add_argument("--skill", type=float, default=0.6)
    s.add_argument("--seed", type=int)
    s.add_argument("--beginner", action="store_true",
                   help="play a fixed repertoire with a learner's mistakes")
    s.set_defaults(func=cmd_simulate)

    pc = sub.add_parser("pieces", help="report which sessions played the same piece (read-only)")
    pc.add_argument("--report", action="store_true", help="the default; kept for clarity")
    pc.add_argument("--days", type=int, default=0, help="only the last N days (0: all)")
    pc.add_argument("--sessions", action="store_true", help="also list every segment")
    pc.add_argument("--check", action="store_true",
                    help="score the matcher on simulated beginner practice instead of the database")
    pc.add_argument("--seed", type=int, default=1, help="simulation seed for --check")
    pc.set_defaults(func=cmd_pieces)

    rp = sub.add_parser("replay", help="import a .mid file as a session, or stream it")
    rp.add_argument("file")
    rp.add_argument("--fifo", help="stream into this FIFO in real time instead")
    rp.add_argument("--speed", type=float, default=1.0)
    rp.add_argument("--start", type=float, help="unix time the session started")
    rp.add_argument("--idle-gap", type=float, default=180.0)
    rp.set_defaults(func=cmd_replay)

    v = sub.add_parser("vectors", help="rewrite the engine test vectors (tests/vectors/)")
    v.add_argument("--out", help="folder (default: tests/vectors in the source tree)")
    v.set_defaults(func=cmd_vectors)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
