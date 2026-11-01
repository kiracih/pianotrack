"""Bluetooth LE MIDI fallback: parsing BlueZ/ALSA tool output and the
USB-first switching in the collector."""

import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from pianotrack import collector as col_mod
from pianotrack.bluetooth import (BleMidi, parse_aseqdump, parse_devices, parse_info,
                                  parse_ports)
from pianotrack.collector import Collector
from pianotrack.store import Store

ASEQDUMP = """Waiting for data at port 129:0. Press Ctrl+C to end.
Source  Event                  Ch  Data
128:0   Note on                 0, note 60, velocity 100
128:0   Note off                0, note 60, velocity 64
128:0   Note on                 0, note 62, velocity 0
128:0   Control change          0, controller 64, value 127
128:0   Active Sensing
128:0   Program change          0, program 5
"""

PORTS = """ Port    Client name                      Port name
  0:0    System                           Timer
 14:0    Midi Through                     Midi Through Port-0
 28:0    Roland Digital Piano             Roland Digital Piano MIDI 1
128:0    FP-30X MIDI                      FP-30X MIDI Bluetooth
142:0    PipeWire-System                  input
"""


class ParseTest(unittest.TestCase):
    def test_aseqdump_lines(self):
        msgs = [m for m in map(parse_aseqdump, ASEQDUMP.splitlines()) if m]
        self.assertEqual(msgs, [(0x90, 60, 100), (0x80, 60, 64), (0x90, 62, 0), (0xB0, 64, 127)])
        self.assertEqual(parse_aseqdump("128:0   Note on                 3, note 21, velocity 5"),
                         (0x93, 21, 5))

    def test_ports(self):
        ports = parse_ports(PORTS)
        self.assertIn((128, 0, "FP-30X MIDI", "FP-30X MIDI Bluetooth"), ports)
        self.assertEqual(ports[0][:2], (0, 0))

    def test_devices_and_info(self):
        self.assertEqual(parse_devices("Device E7:47:8F:02:4C:26 FP-30X MIDI\nnoise\n"),
                         [("E7:47:8F:02:4C:26", "FP-30X MIDI")])
        info = parse_info("Device E7:47:8F:02:4C:26 (random)\n\tName: FP-30X MIDI\n"
                          "\tPaired: yes\n\tConnected: no\n\tUUID: Vendor specific (03b8)\n")
        self.assertEqual(info["Name"], "FP-30X MIDI")
        self.assertEqual(info["Connected"], "no")


class FakeCtl:
    """Stands in for bluetoothctl and aseqdump -l."""

    def __init__(self, powered=True, trusted=True, connect_ok=True):
        self.powered, self.trusted, self.connect_ok = powered, trusted, connect_ok
        self.connected = False
        self.calls = []

    def __call__(self, args, timeout):
        self.calls.append(args[1:])
        if args[0] == "aseqdump":
            return 0, PORTS if self.connected else PORTS.replace("128:0", "#")
        cmd = [a for a in args[1:] if a not in ("--timeout",) and not a.isdigit()]
        if cmd[0] == "show":
            return 0, f"Controller X\n\tPowered: {'yes' if self.powered else 'no'}\n\tPowerState: off-blocked\n"
        if cmd[0] == "devices":
            return 0, "Device E7:47:8F:02:4C:26 FP-30X MIDI\n"
        if cmd[0] == "info":
            return 0, (f"Device {cmd[1]}\n\tName: FP-30X MIDI\n\tPaired: yes\n"
                       f"\tTrusted: {'yes' if self.trusted else 'no'}\n"
                       f"\tConnected: {'yes' if self.connected else 'no'}\n")
        if cmd[0] == "untrust":
            self.trusted = False
        if cmd[0] == "connect":
            self.connected = self.connect_ok
            return (0, "Connection successful") if self.connect_ok else (1, "Failed to connect: org.bluez.Error.Failed")
        if cmd[0] == "disconnect":
            self.connected = False
        return 0, ""


class BleMidiTest(unittest.TestCase):
    def test_connect_finds_untrusts_and_returns_port(self):
        ctl = FakeCtl()
        ble = BleMidi(run=ctl)
        self.assertEqual(ble.connect(), "128:0")
        self.assertEqual(ble.address, "E7:47:8F:02:4C:26")
        self.assertIn(["untrust", "E7:47:8F:02:4C:26"], ctl.calls)
        self.assertEqual(ble.state, "connected")
        ble.release()
        self.assertFalse(ctl.connected)
        self.assertEqual(ble.state, "released")

    def test_radio_off_is_reported(self):
        ble = BleMidi(run=FakeCtl(powered=False))
        self.assertIsNone(ble.connect())
        self.assertEqual(ble.state, "unavailable")
        self.assertIn("enable-bluetooth", ble.last_error)

    def test_failed_connect(self):
        ble = BleMidi("e7:47:8f:02:4c:26", run=FakeCtl(connect_ok=False))
        self.assertIsNone(ble.connect())
        self.assertIn("Failed to connect", ble.last_error)


class FakeBle:
    """A BleMidi whose event stream is a pipe the test writes aseqdump lines to."""

    def __init__(self):
        self.name, self.address = "FP-30X MIDI", "E7:47:8F:02:4C:26"
        self.connected_by_us = False
        self.connects = self.releases = 0
        self.last_error = None
        self.writer = None
        self.ready = threading.Event()

    def status(self):
        return {"state": "connected" if self.connected_by_us else "idle"}

    def connect(self):
        self.connects += 1
        self.connected_by_us = True
        return "128:0"

    def find_port(self):
        return "128:0" if self.connected_by_us else None

    def is_connected(self):
        return self.connected_by_us

    def release(self):
        if self.connected_by_us:
            self.releases += 1
        self.connected_by_us = False

    def open_stream(self, port):
        r, w = os.pipe()
        self.writer = w
        self.ready.set()
        return FakeProc(r, w)


class FakeProc:
    def __init__(self, r, w):
        self.stdout = os.fdopen(r, "rb", buffering=0)
        self._w = w

    def kill(self):
        if self._w is not None:
            os.close(self._w)
            self._w = None

    def wait(self):
        self.stdout.close()


def wait_for(cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


@mock.patch.object(col_mod, "RETRY_SECONDS", 0.2)
@mock.patch.object(col_mod, "USB_CHECK_SECONDS", 0.2)
class FallbackTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, "t.db"))
        self.usb = os.path.join(self.dir.name, "usb.fifo")  # absent = unplugged

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def play(self, write, start, n=10):
        for i in range(n):
            write(start + i)
            time.sleep(0.02)

    def test_bluetooth_while_unplugged_then_back_to_usb_and_replug(self):
        ble = FakeBle()
        col = Collector(self.store, device=self.usb, idle_gap=60, bluetooth=ble)
        th = threading.Thread(target=col.run, daemon=True)
        th.start()
        try:
            # No USB: Bluetooth takes over and its notes are recorded.
            self.assertTrue(ble.ready.wait(5))
            self.assertTrue(wait_for(lambda: col.status["transport"] == "bluetooth"))
            self.assertEqual(col.status["name"], "FP-30X MIDI")
            self.play(lambda p: os.write(ble.writer, (
                f"128:0   Note on                 0, note {p}, velocity 90\n"
                f"128:0   Note off                0, note {p}, velocity 0\n").encode()), 60)
            self.assertTrue(wait_for(lambda: col.recorder.note_count == 10))

            # USB plugged in: Bluetooth is released and USB is read.
            os.mkfifo(self.usb)
            self.assertTrue(wait_for(lambda: col.status["transport"] == "usb"))
            self.assertEqual(ble.releases, 1)
            self.assertFalse(ble.connected_by_us)
            with open(self.usb, "wb", buffering=0) as f:
                self.play(lambda p: f.write(bytes([0x90, p, 80, 0x80, p, 0])), 40)
                self.assertTrue(wait_for(lambda: col.recorder.note_count >= 10
                                         and col.status["last_event"] is not None))
            sessions = self.store.sessions(closed_only=True)
            self.assertEqual(len(sessions), 1)  # the Bluetooth session, closed on the switch
            self.assertEqual(sessions[0]["source"], "FP-30X MIDI")

            # Unplug, then replug: back on Bluetooth meanwhile, USB again after.
            os.unlink(self.usb)
            self.assertTrue(wait_for(lambda: col.status["transport"] == "bluetooth"))
            os.mkfifo(self.usb)
            self.assertTrue(wait_for(lambda: col.status["transport"] == "usb"))
            self.assertEqual(ble.connects, 2)
            self.assertEqual(ble.releases, 2)
        finally:
            col.stop()
            th.join(5)
        self.assertFalse(th.is_alive())

    def test_without_bluetooth_usb_replug_is_picked_up(self):
        col = Collector(self.store, device=self.usb, idle_gap=60)
        th = threading.Thread(target=col.run, daemon=True)
        th.start()
        try:
            time.sleep(0.5)
            self.assertFalse(col.status["connected"])
            for _ in range(2):
                os.mkfifo(self.usb)
                with open(self.usb, "wb", buffering=0) as f:  # like a real device node
                    self.assertTrue(wait_for(lambda: col.status["transport"] == "usb"))
                    os.unlink(self.usb)  # unplugged: the stream ends and the node is gone
                self.assertTrue(wait_for(lambda: not col.status["connected"]))
        finally:
            col.stop()
            th.join(5)


if __name__ == "__main__":
    unittest.main()
