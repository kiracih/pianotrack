"""Demo instance: a database of simulated practice, rebuilt once a day.

`pianotrack run --demo` serves it read-only and without a password, for showing
the dashboard to people who should never see the real recordings. The history
is rebuilt once a day (at the first start of the day) so it always ends today.
It refuses to touch a database that holds anything the simulator did not write.
"""

import logging
import os
import sqlite3
from collections import Counter
from datetime import date

from . import pieces, simulate
from .store import Store

log = logging.getLogger(__name__)
DISPLAY = {"Fur Elise": "Für Elise"}


def is_simulated(path):
    """True when the database is missing or every session in it came from the simulator."""
    if not os.path.exists(path):
        return True
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        n = con.execute("SELECT COUNT(*) FROM sessions WHERE COALESCE(source, '') != 'simulator'").fetchone()[0]
    except sqlite3.DatabaseError:
        return False  # not ours to replace
    finally:
        con.close()
    return n == 0


def built_today(path):
    if not os.path.exists(path):
        return False
    store = Store(path, readonly=True)
    try:
        return store.secret("demo_built") == date.today().isoformat()
    finally:
        store.close()


def build(path, days=120, seed=3, force=False):
    """Write a fresh demo database at `path`, ending now, with the pieces named.
    Keeps one already built today unless `force`. True when it built one."""
    if not is_simulated(path):
        raise ValueError(f"{path} holds real recordings; the demo needs its own --db")
    if not force and built_today(path):
        return False
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".building"
    for p in (tmp, tmp + "-wal", tmp + "-shm"):
        if os.path.exists(p):
            os.remove(p)
    store, played = Store(tmp), []
    recorder_log = logging.getLogger("pianotrack.recorder")
    level = recorder_log.level
    recorder_log.setLevel(logging.WARNING)  # a line per simulated session otherwise
    try:
        simulate.backfill(store, days=days, seed=seed, beginner=True, log=played)
    finally:
        recorder_log.setLevel(level)
    _name_pieces(store, played)
    store.set_secret("demo_built", date.today().isoformat())
    store.close()
    for p in (path + "-wal", path + "-shm"):
        if os.path.exists(p):
            os.remove(p)
    os.replace(tmp, path)
    log.info("demo database rebuilt at %s (%d days, seed %s)", path, days, seed)
    return True


def _name_pieces(store, played):
    """Name each piece after the tune the simulator played most in it, as the owner would."""
    from .server import Api  # the naming rules live with the API
    api = Api(store)
    matcher, view = api._pieces()
    used = set()
    for row in view:
        heard = Counter(pieces.truth(s, played) for i in row["_groups"] for s in matcher.pieces[i]["segments"])
        name = heard.most_common(1)[0][0] if heard else None
        if name in simulate.REPERTOIRE and name not in used:
            used.add(name)
            api.name_piece({"key": row["_keys"][0], "name": DISPLAY.get(name, name)})
