"""Reads the piano over ALSA raw MIDI and feeds the recorder.

A USB class-compliant instrument like the Roland FP-30X shows up as
/dev/snd/midiC<card>D<device>. We read that file directly, so there is no
dependency on rtmidi or mido. When the piano is switched off the device node
disappears; the collector waits and reconnects.
"""

import errno
import glob
import logging
import os
import re
import select
import threading
import time

from .midi import StreamParser
from .recorder import Recorder

log = logging.getLogger(__name__)

RETRY_SECONDS = 2.0
# Kernel MIDI devices that are never a piano.
_IGNORED = re.compile(r"midi through|thru", re.I)


def card_name(path):
    m = re.search(r"midiC(\d+)D\d+$", path)
    if not m:
        return os.path.basename(path)
    try:
        with open(f"/proc/asound/card{m.group(1)}/id") as f:
            return f.read().strip()
    except OSError:
        return os.path.basename(path)


def find_device(match=None):
    """Pick the raw MIDI device to read.

    `match` may be a path (used as is, e.g. a FIFO for testing) or a regex
    matched against the ALSA card id. Otherwise the first non-virtual device
    wins, preferring anything that looks like a Roland.
    """
    if match and (match.startswith("/") or os.path.exists(match)):
        return match if os.path.exists(match) else None
    devices = sorted(glob.glob("/dev/snd/midiC*D*"))
    named = [(d, card_name(d)) for d in devices]
    named = [(d, n) for d, n in named if not _IGNORED.search(n)]
    if match:
        named = [(d, n) for d, n in named if re.search(match, n, re.I)]
    named.sort(key=lambda dn: (not re.search(r"roland|fp", dn[1], re.I), dn[0]))
    return named[0][0] if named else None


class Collector:
    """Owns the device loop. Run `run()` in a thread or as the main loop."""

    def __init__(self, store, device=None, idle_gap=180.0, clock=time.time):
        self.store = store
        self.device_match = device
        self.clock = clock
        self.recorder = Recorder(store, idle_gap=idle_gap)
        self.status = {"connected": False, "device": None, "name": None,
                       "last_event": None, "since": None}
        self.messages_seen = 0
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        for sid in self.store.close_dangling():
            self._finish_dangling(sid)
        while not self._stop.is_set():
            path = find_device(self.device_match)
            if not path:
                self._set_disconnected()
                self._idle_wait(RETRY_SECONDS)
                continue
            try:
                self._read_device(path)
            except OSError as e:
                if e.errno not in (errno.ENODEV, errno.EIO, errno.ENOENT, errno.EBUSY):
                    log.exception("unexpected error reading %s", path)
                else:
                    log.info("device %s went away (%s)", path, e.strerror)
            self._set_disconnected()
            self._idle_wait(RETRY_SECONDS)
        self.recorder.close_session()

    def _finish_dangling(self, sid):
        """Compute metrics for a session cut short by a crash or reboot."""
        from . import metrics
        notes = self.store.notes(sid)
        if len(notes) < self.recorder.min_notes:
            self.store.delete_session(sid)
            return
        m = metrics.session_metrics(notes, self.store.pedals(sid))
        self.store.close_session(sid, m["end"], m)

    def _idle_wait(self, seconds):
        end = time.monotonic() + seconds
        while not self._stop.is_set() and time.monotonic() < end:
            self.recorder.tick(self.clock())
            self._stop.wait(min(0.5, max(0.0, end - time.monotonic())))

    def _set_disconnected(self):
        if self.status["connected"]:
            log.info("piano disconnected")
            self.recorder.close_session()
        self.status.update(connected=False, since=self.clock())

    def _read_device(self, path):
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        parser = StreamParser()
        name = card_name(path)
        log.info("connected to %s (%s)", path, name)
        self.status.update(connected=True, device=path, name=name, since=self.clock())
        self.recorder.source = name
        try:
            while not self._stop.is_set():
                ready, _, _ = select.select([fd], [], [], 0.5)
                now = self.clock()
                if ready:
                    data = os.read(fd, 1024)
                    if not data:  # FIFO writer closed or device gone
                        if not os.path.exists(path) or path.startswith("/dev/snd"):
                            raise OSError(errno.ENODEV, "end of stream")
                        time.sleep(0.2)
                    for msg in parser.feed(data):
                        self.messages_seen += 1
                        self.recorder.handle(now, msg)
                        self.status["last_event"] = now
                self.recorder.tick(now)
        finally:
            os.close(fd)
