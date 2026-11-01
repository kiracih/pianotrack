"""Bluetooth LE MIDI fallback, used only while the piano's USB cable is out.

The Roland FP-30X speaks BLE MIDI, but accepts a single connection, so the Pi
takes it only when USB is gone (for example while the USB port records audio
on a phone) and lets go as soon as USB is back, leaving it free for the phone.

BlueZ does the radio work: once `bluetoothctl connect` succeeds, its MIDI
plugin publishes the piano as an ALSA sequencer client, and `aseqdump` (from
alsa-utils) prints that client's events as text, one per line. Both tools ship
with Raspberry Pi OS, so there is still nothing to pip install.
"""

import logging
import os
import re
import shutil
import subprocess
import time

log = logging.getLogger(__name__)

# Names a Roland piano advertises over BLE, e.g. "FP-30X MIDI".
DEFAULT_NAME = r"roland|fp-?\d|piano"
_MAC = re.compile(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$", re.I)
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x01|\x02")
_EVENT = re.compile(
    r"^\s*\d+:\d+\s+(Note on|Note off|Control change)\s+(\d+),\s*"
    r"(?:note|controller)\s+(\d+),\s*(?:velocity|value)\s+(\d+)", re.I)
_KIND = {"note on": 0x90, "note off": 0x80, "control change": 0xB0}
_PORT = re.compile(r"^\s*(\d+):(\d+)\s+(.+?)\s{2,}(.*?)\s*$")


def parse_aseqdump(line):
    """One aseqdump output line to a MIDI message tuple, or None.

    Only notes and controllers matter to the recorder; everything else
    (active sensing, headers, program changes) is dropped.
    """
    m = _EVENT.match(line)
    if not m:
        return None
    ch, a, b = (int(x) for x in m.groups()[1:])
    if ch > 15 or a > 127 or b > 127:
        return None
    return (_KIND[m.group(1).lower()] | ch, a, b)


def parse_ports(text):
    """`aseqdump -l` output to [(client, port, client_name, port_name)]."""
    out = []
    for line in text.splitlines():
        m = _PORT.match(line)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), m.group(3).strip(), m.group(4).strip()))
    return out


def parse_devices(text):
    """`bluetoothctl devices` output to [(mac, name)]."""
    out = []
    for line in _ANSI.sub("", text).splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) >= 2 and parts[0] == "Device" and _MAC.match(parts[1]):
            out.append((parts[1].upper(), parts[2] if len(parts) > 2 else ""))
    return out


def parse_info(text):
    """`bluetoothctl info` / `show` output to {key: value} (first value wins)."""
    out = {}
    for line in _ANSI.sub("", text).splitlines():
        if ":" in line and line[:1] in ("\t", " "):
            k, v = line.strip().split(":", 1)
            out.setdefault(k.strip(), v.strip())
    return out


class BleMidi:
    """Finds, connects and releases the piano over BlueZ.

    `target` is a MAC address or a regex for the advertised name. `run` is the
    subprocess runner, swapped out in tests.
    """

    CONNECT_TIMEOUT = 20
    PORT_WAIT = 6.0

    def __init__(self, target=None, run=None):
        target = target or DEFAULT_NAME
        self.address = target.upper() if _MAC.match(target) else None
        self.pattern = None if self.address else target
        self.name = None
        self.connected_by_us = False
        self._run = run or self._subprocess
        self.state = "idle"  # idle | searching | connected | released | unavailable
        self.last_error = None

    @staticmethod
    def available():
        return all(shutil.which(t) for t in ("bluetoothctl", "aseqdump"))

    def status(self):
        return {"address": self.address, "name": self.name, "state": self.state,
                "last_error": self.last_error}

    # --- bluetoothctl ---------------------------------------------------------
    @staticmethod
    def _subprocess(args, timeout):
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                               stdin=subprocess.DEVNULL)
            return p.returncode, p.stdout + p.stderr
        except subprocess.TimeoutExpired as e:
            out = e.stdout or ""
            return 124, out.decode(errors="replace") if isinstance(out, bytes) else out
        except OSError as e:
            return 127, str(e)

    def _ctl(self, *args, timeout=10):
        return self._run(["bluetoothctl", *args], timeout)

    def _info(self):
        if not self.address:
            return {}
        return parse_info(self._ctl("info", self.address)[1])

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

    def connect(self):
        """Connect and return the ALSA sequencer address 'client:port', or None."""
        self.state, self.last_error = "searching", None
        if not self._ensure_powered():
            self.state = "unavailable"
            return None
        if not self._find():
            self.state, self.last_error = "idle", "piano not found (is it on, and free of other phones?)"
            return None
        info = self._info()
        self.name = info.get("Name") or self.name
        if info.get("Trusted") == "yes":
            # A trusted LE device is reconnected by BlueZ on its own whenever it
            # advertises, which would hold the piano's only BLE slot while USB
            # works. Untrusted, it connects only when we ask.
            self._ctl("untrust", self.address)
        if info.get("Connected") != "yes":
            if info.get("Paired") != "yes":
                # Pairing needs the piano advertising: refresh BlueZ's view first.
                self._ctl("--timeout", "5", "scan", "le", timeout=10)
            code, out = self._ctl("connect", self.address, timeout=self.CONNECT_TIMEOUT)
            if "Connection successful" not in out and parse_info(
                    self._ctl("info", self.address)[1]).get("Connected") != "yes":
                lines = [l for l in _ANSI.sub("", out).splitlines() if l.strip()]
                self.state = "idle"
                self.last_error = lines[-1].strip() if lines else f"connect failed ({code})"
                return None
        self.connected_by_us = True
        port = self._wait_for_port()
        if not port:
            self.last_error = "connected, but BlueZ published no MIDI port"
            self.release()
            self.state = "idle"
            return None
        self.state = "connected"
        log.info("bluetooth: connected to %s (%s), MIDI on %s", self.name, self.address, port)
        return port

    def _wait_for_port(self):
        end = time.monotonic() + self.PORT_WAIT
        while True:
            port = self.find_port()
            if port or time.monotonic() >= end:
                return port
            time.sleep(0.5)

    def find_port(self):
        """The sequencer port BlueZ made for the piano. BlueZ is a user client
        (number 128 and up); the USB piano is a kernel client below 128."""
        code, out = self._run(["aseqdump", "-l"], 5)
        name = (self.name or "").lower()
        for client, port, cname, pname in parse_ports(out):
            if client < 128 or "aseqdump" in cname.lower():
                continue
            if name and (name in cname.lower() or name in pname.lower()):
                return f"{client}:{port}"
        return None

    def is_connected(self):
        return self._info().get("Connected") == "yes"

    def release(self):
        """Disconnect so the piano's single BLE slot is free for the phone."""
        if not self.address:
            return
        if self.connected_by_us or self.is_connected():
            self._ctl("disconnect", self.address)
            log.info("bluetooth: released %s", self.address)
        self.connected_by_us = False
        self.state = "released"

    # --- events -------------------------------------------------------------------
    def open_stream(self, port):
        """Start aseqdump on the port; returns the Popen (line-buffered stdout)."""
        cmd = ["aseqdump", "-p", port]
        if shutil.which("stdbuf"):
            cmd = ["stdbuf", "-oL"] + cmd  # timestamps are taken when lines arrive
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, env={**os.environ, "LC_ALL": "C"})
