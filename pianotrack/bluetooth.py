"""Bluetooth LE MIDI fallback, used only while the piano's USB cable is out.

The Roland FP-30X speaks BLE MIDI, but accepts a single connection, so the Pi
takes it only when USB is gone (for example while the USB port records audio
on a phone) and lets go as soon as USB is back, leaving it free for the phone.

BlueZ's own MIDI driver can't be used with this piano: the FP-30X cuts its
128-bit characteristic UUIDs short in GATT replies, so BlueZ never recognises
the MIDI characteristic, never switches its notifications on, and the ALSA
port it publishes stays silent. Instead we talk GATT to the piano ourselves
with `gatttool` (part of BlueZ on Raspberry Pi OS): find the MIDI
characteristic from its declaration, write 01 00 to its notification switch
over an encrypted link, and decode the notifications as BLE MIDI packets.
`bluetoothctl` handles power, scanning and the one-time "Just Works" pairing.
There is still nothing to pip install.
"""

import logging
import re
import shutil
import subprocess

log = logging.getLogger(__name__)

# Names a Roland piano advertises over BLE, e.g. "FP-30X MIDI".
DEFAULT_NAME = r"roland|fp-?\d|piano"
_MAC = re.compile(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$", re.I)
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x01|\x02")

# The BLE MIDI data characteristic, 7772e5db-3868-4112-a1a9-f2669d106bf3, as it
# sits little-endian in a characteristic declaration.
MIDI_IO_LE = bytes.fromhex("7772e5db38684112a1a9f2669d106bf3")[::-1]
_DESC = re.compile(r"handle\s*=\s*0x([0-9a-f]+),\s*uuid\s*=\s*([0-9a-f-]+)", re.I)
_VALUE = re.compile(r"(?:value/descriptor|value):\s*([0-9a-f ]+)", re.I)
_NOTIFY = re.compile(r"Notification handle = 0x([0-9a-f]+) value:\s*([0-9a-f ]+)", re.I)
_DATA_LEN = {0x80: 2, 0x90: 2, 0xA0: 2, 0xB0: 2, 0xC0: 1, 0xD0: 1, 0xE0: 2}
_SYS_LEN = {0xF1: 1, 0xF2: 2, 0xF3: 1}
# FP-30X layout, used if discovery can't read the declarations.
FP30X_HANDLES = (0x000C, 0x000D)


def decode_ble_midi(pkt):
    """One BLE MIDI packet (Bluetooth MIDI spec) to MIDI message tuples.

    Layout: a header byte (bit 7 set), then messages, each preceded by a
    timestamp byte (bit 7 set) when it carries a status byte; running-status
    messages may follow with or without a timestamp. SysEx and realtime
    bytes are skipped, as the USB parser does. Notes are timestamped when the
    packet arrives, like USB.
    """
    out = []
    n = len(pkt)
    if n < 2 or not pkt[0] & 0x80:
        return out
    i, status = 1, None
    while i < n:
        b = pkt[i]
        if b & 0x80:  # timestamp, then a status byte or running-status data
            i += 1
            if i >= n:
                break
            b = pkt[i]
            if b & 0x80:
                i += 1
                if b == 0xF0:  # SysEx: skip to its end (F7, after a timestamp byte)
                    while i < n and pkt[i] != 0xF7:
                        i += 1
                    i += 1
                    status = None
                    continue
                if b >= 0xF8:
                    continue
                if b >= 0xF0:
                    status = None
                    i += _SYS_LEN.get(b, 0)
                    continue
                status = b
        if status is None:
            i += 1
            continue
        need = _DATA_LEN[status & 0xF0]
        data = pkt[i:i + need]
        if len(data) < need or any(d & 0x80 for d in data):
            i += 1
            continue
        out.append((status, *data))
        i += need
    return out


def parse_notification(line, handle=None):
    """A `gatttool --listen` notification line to MIDI messages."""
    m = _NOTIFY.search(line)
    if not m or (handle is not None and int(m.group(1), 16) != handle):
        return []
    try:
        pkt = bytes.fromhex(m.group(2))
    except ValueError:
        return []
    return decode_ble_midi(pkt)


def parse_descriptors(text):
    """`gatttool --char-desc` output to [(handle, uuid)]."""
    return [(int(h, 16), u.lower()) for h, u in _DESC.findall(text)]


def _short(uuid):
    """'2803' for both '2803' and '00002803-0000-1000-8000-00805f9b34fb'."""
    return uuid[4:8] if len(uuid) == 36 else uuid


def is_midi_declaration(value):
    """Characteristic declaration bytes (props, value handle, UUID) -> value handle
    if it declares the MIDI characteristic. The UUID may be cut short, as the
    FP-30X sends only its first two bytes."""
    if len(value) < 5:
        return None
    uuid = value[3:]
    if MIDI_IO_LE.startswith(uuid) or uuid.startswith(MIDI_IO_LE):
        return value[1] | value[2] << 8
    return None


def ccc_after(descs, value_handle):
    """The notification switch (0x2902) that belongs to a characteristic value."""
    for h, u in descs:
        if h <= value_handle:
            continue
        if _short(u) == "2803":
            break
        if _short(u) == "2902":
            return h
    return value_handle + 1


def parse_devices(text):
    """`bluetoothctl devices` output to [(mac, name)]."""
    out = []
    for line in _ANSI.sub("", text).splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) >= 2 and parts[0] == "Device" and _MAC.match(parts[1]):
            out.append((parts[1].upper(), parts[2] if len(parts) > 2 else ""))
    return out


def parse_info(text):
    """`bluetoothctl info` / `show` output to {key: value} (first value wins).
    The address type from the first line ("Device X (random)") is in '_type'."""
    out = {}
    text = _ANSI.sub("", text)
    m = re.search(r"^(?:Device|Controller) \S+ \((random|public)\)", text, re.M)
    if m:
        out["_type"] = m.group(1)
    for line in text.splitlines():
        if ":" in line and line[:1] in ("\t", " "):
            k, v = line.strip().split(":", 1)
            out.setdefault(k.strip(), v.strip())
    return out


class BleMidi:
    """Finds, pairs, connects and releases the piano.

    `target` is a MAC address or a regex for the advertised name. `run` is the
    subprocess runner, swapped out in tests.
    """

    def __init__(self, target=None, run=None):
        target = target or DEFAULT_NAME
        self.address = target.upper() if _MAC.match(target) else None
        self.pattern = None if self.address else target
        self.name = None
        self.addr_type = "random"
        self.handles = None  # (MIDI value handle, its CCC handle)
        self.linked = False  # notifications switched on, notes can flow
        self._run = run or self._subprocess
        self.state = "idle"  # idle | searching | linking | connected | released | unavailable
        self.last_error = None

    @staticmethod
    def available():
        return all(shutil.which(t) for t in ("bluetoothctl", "gatttool"))

    def status(self):
        return {"address": self.address, "name": self.name, "state": self.state,
                "last_error": self.last_error}

    # --- tools ----------------------------------------------------------------
    @staticmethod
    def _subprocess(args, timeout, input=None):
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                               input=input, stdin=None if input is not None else subprocess.DEVNULL)
            return p.returncode, p.stdout + p.stderr
        except subprocess.TimeoutExpired as e:
            out = e.stdout or ""
            return 124, out.decode(errors="replace") if isinstance(out, bytes) else out
        except OSError as e:
            return 127, str(e)

    def _ctl(self, *args, timeout=10):
        return self._run(["bluetoothctl", *args], timeout)

    def _gatt(self, *args, timeout=15):
        return self._run(["gatttool", "-t", self.addr_type, "-b", self.address, *args], timeout)

    def _info(self):
        if not self.address:
            return {}
        return parse_info(self._ctl("info", self.address)[1])

    # --- steps --------------------------------------------------------------------
    def _ensure_powered(self):
        info = parse_info(self._ctl("show")[1])
        if info.get("Powered") == "yes":
            return True
        self._ctl("power", "on")
        info = parse_info(self._ctl("show")[1])
        if info.get("Powered") == "yes":
            return True
        self.last_error = ("the Pi's Bluetooth is off (" + info.get("PowerState", "no controller")
                           + "); run deploy/enable-bluetooth.sh")
        return False

    def _find(self):
        """Resolve the piano's address from BlueZ's known devices, scanning if needed."""
        if self.address:
            return True
        for scan in (False, True):
            if scan:
                self._ctl("--timeout", "8", "scan", "le", timeout=15)
            for mac, name in parse_devices(self._ctl("devices")[1]):
                if re.search(self.pattern, name, re.I):
                    self.address, self.name = mac, name
                    log.info("bluetooth: found %s at %s", name, mac)
                    return True
        return False

    def pair(self):
        """One-time "Just Works" pairing; the piano sends notes only over an
        encrypted link. Needs the piano advertising (no phone connected)."""
        self._ctl("--timeout", "6", "scan", "le", timeout=12)
        script = (f"agent NoInputNoOutput\ndefault-agent\npair {self.address}\n")
        # Keep bluetoothctl open while the pairing completes, then quit.
        self._run(["sh", "-c", f"(printf '{script}'; sleep 12; echo quit) | bluetoothctl"], 25)
        ok = self._info().get("Paired") == "yes"
        log.info("bluetooth: pairing with %s %s", self.address, "worked" if ok else "failed")
        return ok

    def _discover(self):
        """MIDI value handle and its notification switch, from the declarations."""
        descs = parse_descriptors(self._gatt("--char-desc", timeout=20)[1])
        for h, u in descs:
            if _short(u) != "2803":
                continue
            m = _VALUE.search(self._gatt("--char-read", "-a", f"0x{h:04x}")[1])
            if not m:
                continue
            try:
                value = bytes.fromhex(m.group(1))
            except ValueError:
                continue
            vh = is_midi_declaration(value)
            if vh:
                return vh, ccc_after(descs, vh)
        if descs:
            log.warning("bluetooth: no MIDI characteristic found; trying the FP-30X handles")
            return FP30X_HANDLES
        return None

    def connect(self):
        """Get ready to stream: returns True when `open_stream` can be started."""
        self.state, self.last_error, self.linked = "searching", None, False
        if not self._ensure_powered():
            self.state = "unavailable"
            return False
        if not self._find():
            self.state, self.last_error = "idle", "piano not found (is it on, and free of other phones?)"
            return False
        info = self._info()
        self.name = info.get("Name") or self.name or "Piano"
        self.addr_type = info.get("_type", self.addr_type)
        if info.get("Trusted") == "yes":
            # A trusted LE device is reconnected by BlueZ on its own whenever it
            # advertises, which would hold the piano's only BLE slot while USB
            # works. Untrusted, it connects only when we ask.
            self._ctl("untrust", self.address)
        if info.get("Connected") == "yes":
            self._ctl("disconnect", self.address)  # BlueZ's own link is of no use
        if info.get("Paired") != "yes" and not self.pair():
            self.state = "idle"
            self.last_error = "pairing failed (turn the piano's Bluetooth on, phone disconnected)"
            return False
        if not self.handles:
            self.handles = self._discover()
            if not self.handles:
                self.state, self.last_error = "idle", "could not reach the piano"
                return False
            log.info("bluetooth: MIDI on handle 0x%04x, notifications 0x%04x", *self.handles)
        self.state = "linking"
        return True

    def open_stream(self):
        """Start gatttool listening for MIDI notifications (line-buffered stdout)."""
        cmd = ["gatttool", "-t", self.addr_type, "-b", self.address, "--sec-level=medium",
               "--char-write-req", "-a", f"0x{self.handles[1]:04x}", "-n", "0100", "--listen"]
        if shutil.which("stdbuf"):
            cmd = ["stdbuf", "-oL"] + cmd  # timestamps are taken when lines arrive
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL)

    def parse_line(self, line):
        """A gatttool output line to MIDI messages; notes the link going live."""
        if not self.linked and "written successfully" in line:
            self.linked, self.state = True, "connected"
            log.info("bluetooth: connected to %s (%s)", self.name, self.address)
        elif "error" in line.lower():
            self.last_error = line.strip()
        return parse_notification(line, self.handles[0] if self.handles else None)

    def is_connected(self):
        return self._info().get("Connected") == "yes"

    def release(self):
        """Let go of the piano so its single BLE slot is free for the phone.
        (Stopping gatttool drops our link; this catches BlueZ's own.)"""
        self.linked = False
        if self.address and self.is_connected():
            self._ctl("disconnect", self.address)
            log.info("bluetooth: released %s", self.address)
        self.state = "released"
