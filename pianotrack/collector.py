"""Reads the piano over ALSA raw MIDI and feeds the recorder.

A USB class-compliant instrument like the Roland FP-30X shows up as
/dev/snd/midiC<card>D<device>. We read that file directly, so there is no
dependency on rtmidi or mido. When the piano is switched off the device node
disappears; the collector waits and reconnects, and picks the device up
again after a replug (the card number may change).

USB is always the primary input. With a `bluetooth.BleMidi` attached, the
collector falls back to Bluetooth LE MIDI while no USB device is present, and
switches back (releasing Bluetooth) within a second of USB returning.
"""

import errno
import glob
import logging
import os
import re
import select
import threading
import time

from .bluetooth import parse_aseqdump
from .midi import StreamParser
from .recorder import Recorder

log = logging.getLogger(__name__)

RETRY_SECONDS = 2.0
# Seconds to wait after a failed Bluetooth attempt (piano off, or the phone
# holds its single BLE connection). The last value repeats.
BLE_BACKOFF = (5, 10, 20, 30, 60)
USB_CHECK_SECONDS = 1.0     # how often a Bluetooth session looks for USB
BLE_ALIVE_SECONDS = 5.0     # how often a Bluetooth session checks the link
BLE_GUARD_SECONDS = 30.0    # how often, on USB, a stray BLE link is released
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

    def __init__(self, store, device=None, idle_gap=180.0, clock=time.time, bluetooth=None):
        self.store = store
        self.device_match = device
        self.clock = clock
        self.recorder = Recorder(store, idle_gap=idle_gap)
        self.ble = bluetooth
        self.status = {"connected": False, "device": None, "name": None, "transport": None,
                       "last_event": None, "since": None,
                       "bluetooth": bluetooth.status() if bluetooth else None}
        self.messages_seen = 0
        self._stop = threading.Event()
        self._ble_failures = 0
        self._ble_next = 0.0

    def stop(self):
        self._stop.set()

    def run(self):
        for sid in self.store.close_dangling():
            self._finish_dangling(sid)
        if self.ble:
            threading.Thread(target=self._ble_guard, daemon=True).start()
        while not self._stop.is_set():
            path = find_device(self.device_match)
            if path:
                self._ble_failures, self._ble_next = 0, 0.0
                if self.ble and self.ble.connected_by_us:
                    self._ble_release()
                try:
                    self._read_device(path)
                except OSError as e:
                    if e.errno not in (errno.ENODEV, errno.EIO, errno.ENOENT, errno.EBUSY):
                        log.exception("unexpected error reading %s", path)
                    else:
                        log.info("device %s went away (%s)", path, e.strerror)
                self._set_disconnected()
                self._idle_wait(RETRY_SECONDS)
            elif self.ble and time.monotonic() >= self._ble_next:
                self._read_bluetooth()
            else:
                self._set_disconnected()
                self._idle_wait(RETRY_SECONDS)
        if self.ble:
            self._ble_release()
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
        self.status.update(connected=False, transport=None, since=self.clock())

    def _read_device(self, path):
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        parser = StreamParser()
        name = card_name(path)
        log.info("connected to %s (%s)", path, name)
        self.status.update(connected=True, device=path, name=name, transport="usb",
                           since=self.clock())
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

    # --- Bluetooth fallback -----------------------------------------------------
    def _ble_release(self):
        try:
            self.ble.release()
        except Exception:
            log.exception("bluetooth: release failed")
        self.status["bluetooth"] = self.ble.status()

    def _ble_guard(self):
        """While USB is in use, keep the piano's BLE slot free for the phone,
        even if BlueZ connected on its own."""
        while not self._stop.wait(BLE_GUARD_SECONDS):
            if self.status["transport"] == "usb":
                try:
                    if self.ble.is_connected():
                        self._ble_release()
                except Exception:
                    log.exception("bluetooth: guard check failed")

    def _read_bluetooth(self):
        try:
            port = self.ble.connect()
        except Exception:
            log.exception("bluetooth: connect failed")
            port = None
        self.status["bluetooth"] = self.ble.status()
        if not port:
            delay = BLE_BACKOFF[min(self._ble_failures, len(BLE_BACKOFF) - 1)]
            self._ble_failures += 1
            self._ble_next = time.monotonic() + delay
            if self._ble_failures == 1:
                log.info("bluetooth: not connected (%s); retrying with backoff",
                         self.ble.last_error)
            self._set_disconnected()
            return
        self._ble_failures = 0
        usb_back = False
        try:
            proc = self.ble.open_stream(port)
        except OSError:
            log.exception("bluetooth: could not start aseqdump")
            self._ble_release()
            self._ble_next = time.monotonic() + BLE_BACKOFF[-1]
            return
        name = self.ble.name or "Piano"
        self.status.update(connected=True, device="bluetooth:" + (self.ble.address or port),
                           name=name, transport="bluetooth", since=self.clock())
        self.recorder.source = name
        fd = proc.stdout.fileno()
        buf = b""
        next_usb = next_alive = time.monotonic()
        next_alive += BLE_ALIVE_SECONDS
        try:
            while not self._stop.is_set():
                ready, _, _ = select.select([fd], [], [], 0.5)
                now = self.clock()
                if ready:
                    data = os.read(fd, 4096)
                    if not data:
                        log.info("bluetooth: event stream ended")
                        break
                    *lines, buf = (buf + data).split(b"\n")
                    for line in lines:
                        msg = parse_aseqdump(line.decode("utf-8", "replace"))
                        if msg:
                            self.messages_seen += 1
                            self.recorder.handle(now, msg)
                            self.status["last_event"] = now
                self.recorder.tick(now)
                mono = time.monotonic()
                if mono >= next_usb:
                    next_usb = mono + USB_CHECK_SECONDS
                    if find_device(self.device_match):
                        log.info("bluetooth: USB is back, switching to it")
                        usb_back = True
                        break
                if mono >= next_alive:
                    next_alive = mono + BLE_ALIVE_SECONDS
                    if not self.ble.find_port():
                        log.info("bluetooth: link to %s dropped", name)
                        break
        finally:
            proc.kill()
            proc.wait()
            self._ble_release()
            self._set_disconnected()
        if not usb_back:
            self._ble_next = time.monotonic() + BLE_BACKOFF[0]
