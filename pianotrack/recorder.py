"""Turns timestamped MIDI messages into sessions, notes and pedal events."""

import logging

from . import metrics

log = logging.getLogger(__name__)

PEDAL_CCS = (64, 66, 67)  # sustain, sostenuto, soft
FLUSH_EVERY = 2.0  # seconds between batched database writes


class Recorder:
    """Session state machine.

    A session opens on the first note and closes once nothing has been played
    for `idle_gap` seconds. Notes are written when released, in small batches.
    """

    def __init__(self, store, idle_gap=180.0, source=None, min_notes=8):
        self.store = store
        self.idle_gap = idle_gap
        self.source = source
        self.min_notes = min_notes  # shorter sessions are discarded as noise
        self.sid = None
        self.last_activity = None
        self.note_count = 0
        self._held = {}  # (channel, pitch) -> (t_on, velocity)
        self._notes, self._pedals = [], []
        self._last_flush = 0.0

    @property
    def active(self):
        return self.sid is not None

    def handle(self, t, msg):
        status = msg[0]
        kind, ch = status & 0xF0, status & 0x0F
        if kind == 0x90 and msg[2] > 0:
            self._ensure_session(t)
            key = (ch, msg[1])
            if key in self._held:  # retrigger without release
                self._release(key, t)
            self._held[key] = (t, msg[2])
            self.last_activity = t
        elif kind == 0x80 or (kind == 0x90 and msg[2] == 0):
            if (ch, msg[1]) in self._held:
                self._release((ch, msg[1]), t)
                self.last_activity = t
        elif kind == 0xB0 and msg[1] in PEDAL_CCS:
            if self.sid is not None:
                self._pedals.append((self.sid, t, msg[1], msg[2]))
                self.last_activity = t
        elif kind == 0xB0 and msg[1] in (120, 123):  # all sound/notes off
            for key in list(self._held):
                self._release(key, t)

    def tick(self, now):
        """Call periodically. Flushes buffers and closes idle sessions."""
        if self.sid is None:
            return
        if now - self._last_flush >= FLUSH_EVERY:
            self.flush()
            self._last_flush = now
        idle = now - self.last_activity
        # A stuck key (missed note-off) must not keep a session open forever.
        if idle >= self.idle_gap and (not self._held or idle >= 2 * self.idle_gap):
            self.close_session()

    def flush(self):
        if self.sid is None:
            return
        if self._notes or self._pedals:
            self.store.add_batch(self._notes, self._pedals)
            self._notes, self._pedals = [], []
        self.store.touch_session(self.sid, self.last_activity)

    def close_session(self):
        if self.sid is None:
            return
        for key in list(self._held):
            self._release(key, self.last_activity)
        self.flush()
        sid, end = self.sid, self.last_activity
        self.sid = None
        if self.note_count < self.min_notes:
            log.info("discarding session %s with only %d notes", sid, self.note_count)
            self.store.delete_session(sid)
            return None
        m = metrics.session_metrics(self.store.notes(sid), self.store.pedals(sid))
        self.store.close_session(sid, end, m)
        log.info("closed session %s: %d notes, %.1f active min",
                 sid, m["note_count"], m["active_seconds"] / 60)
        return sid

    def _ensure_session(self, t):
        if self.sid is not None:
            return
        self.sid = self.store.open_session(t, self.source)
        self.last_activity = t
        self._last_flush = t
        self.note_count = 0
        log.info("opened session %s", self.sid)

    def _release(self, key, t):
        t_on, vel = self._held.pop(key)
        self._notes.append((self.sid, t_on, max(t, t_on), key[1], vel, key[0]))
        self.note_count += 1
