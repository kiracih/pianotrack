"""Bluetooth LE MIDI fallback: parsing BlueZ/ALSA tool output and the
USB-first switching in the collector."""

import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from pianotrack import collector as col_mod
from pianotrack.bluetooth import (BleMidi, ccc_after, decode_ble_midi, is_midi_declaration,
                                  parse_descriptors, parse_devices, parse_info,
                                  parse_notification)
from pianotrack.collector import Collector
from pianotrack.store import Store

CHAR_DESC = """handle = 0x0001, uuid = 00002800-0000-1000-8000-00805f9b34fb
handle = 0x0002, uuid = 00002803-0000-1000-8000-00805f9b34fb
handle = 0x0003, uuid = 00002a00-0000-1000-8000-00805f9b34fb
handle = 0x0007, uuid = 00002800-0000-1000-8000-00805f9b34fb
handle = 0x0008, uuid = 00002803-0000-1000-8000-00805f9b34fb
handle = 0x0009, uuid = 00000318-0000-1000-8000-00805f9b34fb
handle = 0x000a, uuid = 00002902-0000-1000-8000-00805f9b34fb
handle = 0x000b, uuid = 00002803-0000-1000-8000-00805f9b34fb
handle = 0x000c, uuid = 0000fff2-0000-1000-8000-00805f9b34fb
handle = 0x000d, uuid = 00002902-0000-1000-8000-00805f9b34fb
handle = 0x000e, uuid = 00002803-0000-1000-8000-00805f9b34fb
handle = 0x000f, uuid = 0000fff1-0000-1000-8000-00805f9b34fb
"""
# Declarations as the FP-30X returns them: the MIDI one (0x000b) cut to 2 UUID bytes.
DECLS = {0x0002: "02 03 00 00 2a", 0x0008: "12 09 00 18 03",
         0x000b: "1e 0c 00 f3 6b", 0x000e: "0a 0f 00 f1 ff"}


class ParseTest(unittest.TestCase):
    def test_ble_midi_packets(self):
        # Captured from the FP-30X on the Pi.
        self.assertEqual(decode_ble_midi(bytes.fromhex("98f0803c58")), [(0x80, 60, 88)])
        self.assertEqual(decode_ble_midi(bytes.fromhex("99f2802d60f2904540")),
                         [(0x80, 45, 96), (0x90, 69, 64)])
        # Running status without a timestamp, then a pedal, SysEx and realtime skipped.
        self.assertEqual(decode_ble_midi(bytes.fromhex("8081903c64400081b0407f82f0010281f782fe")),
                         [(0x90, 60, 100), (0x90, 64, 0), (0xB0, 64, 127)])
        self.assertEqual(decode_ble_midi(b"\x00\x90"), [])
        self.assertEqual(parse_notification(
            "Notification handle = 0x000c value: 9b ba 90 45 2c ba 90 3c 3b ", 0x0C),
            [(0x90, 69, 44), (0x90, 60, 59)])
        self.assertEqual(parse_notification("Notification handle = 0x0010 value: 80 80 90 3c 64", 0x0C), [])

    def test_declarations_and_ccc(self):
        self.assertEqual(is_midi_declaration(bytes.fromhex("1e0c00f36b")), 0x0C)
        full = bytes.fromhex("1e0c00") + bytes.fromhex("7772e5db38684112a1a9f2669d106bf3")[::-1]
        self.assertEqual(is_midi_declaration(full), 0x0C)
        self.assertIsNone(is_midi_declaration(bytes.fromhex("0a0f00f1ff")))
        self.assertEqual(ccc_after(parse_descriptors(CHAR_DESC), 0x0C), 0x0D)

    def test_devices_and_info(self):
        self.assertEqual(parse_devices("Device E7:47:8F:02:4C:26 FP-30X MIDI\nnoise\n"),
                         [("E7:47:8F:02:4C:26", "FP-30X MIDI")])
        info = parse_info("Device E7:47:8F:02:4C:26 (random)\n\tName: FP-30X MIDI\n"
                          "\tPaired: yes\n\tConnected: no\n\tUUID: Vendor specific (03b8)\n")
        self.assertEqual(info["Name"], "FP-30X MIDI")
        self.assertEqual(info["Connected"], "no")
        self.assertEqual(info["_type"], "random")


class FakeTools:
    """Stands in for bluetoothctl, gatttool and the pairing shell."""

    def __init__(self, powered=True, trusted=True, paired=True, pair_ok=True):
        self.powered, self.trusted, self.paired, self.pair_ok = powered, trusted, paired, pair_ok
        self.connected = False
        self.calls = []

    def __call__(self, args, timeout):
        self.calls.append(args)
        if args[0] == "sh":
            self.paired = self.pair_ok
            return 0, ""
        if args[0] == "gatttool":
            if "--char-desc" in args:
                return 0, CHAR_DESC
            h = int(args[args.index("-a") + 1], 16)
            return 0, f"Characteristic value/descriptor: {DECLS[h]} \n"
        cmd = [a for a in args[1:] if a != "--timeout" and not a.isdigit()]
        if cmd[0] == "show":
            return 0, f"Controller X\n\tPowered: {'yes' if self.powered else 'no'}\n\tPowerState: off-blocked\n"
        if cmd[0] == "devices":
            return 0, "Device E7:47:8F:02:4C:26 FP-30X MIDI\n"
        if cmd[0] == "info":
            return 0, (f"Device {cmd[1]} (random)\n\tName: FP-30X MIDI\n"
                       f"\tPaired: {'yes' if self.paired else 'no'}\n"
                       f"\tTrusted: {'yes' if self.trusted else 'no'}\n"
                       f"\tConnected: {'yes' if self.connected else 'no'}\n")
        if cmd[0] == "untrust":
            self.trusted = False
        if cmd[0] == "disconnect":
            self.connected = False
        return 0, ""


class BleMidiTest(unittest.TestCase):
    def test_connect_finds_untrusts_and_discovers_handles(self):
        tools = FakeTools()
        ble = BleMidi(run=tools)
        self.assertTrue(ble.connect())
        self.assertEqual(ble.address, "E7:47:8F:02:4C:26")
        self.assertEqual(ble.handles, (0x0C, 0x0D))
        self.assertEqual(ble.addr_type, "random")
        self.assertIn(["bluetoothctl", "untrust", "E7:47:8F:02:4C:26"], tools.calls)
        self.assertEqual(ble.state, "linking")
        self.assertFalse(ble.linked)
        self.assertEqual(ble.parse_line("Characteristic value was written successfully"), [])
        self.assertTrue(ble.linked)
        self.assertEqual(ble.state, "connected")
        self.assertEqual(ble.parse_line("Notification handle = 0x000c value: 80 80 90 3c 64"),
                         [(0x90, 60, 100)])
        ble.release()
        self.assertEqual(ble.state, "released")
        self.assertFalse(ble.linked)

    def test_pairs_when_needed(self):
        tools = FakeTools(paired=False)
        self.assertTrue(BleMidi(run=tools).connect())
        self.assertTrue(any(c[0] == "sh" for c in tools.calls))
        self.assertFalse(BleMidi(run=FakeTools(paired=False, pair_ok=False)).connect())

    def test_radio_off_is_reported(self):
        ble = BleMidi(run=FakeTools(powered=False))
        self.assertFalse(ble.connect())
        self.assertEqual(ble.state, "unavailable")
        self.assertIn("enable-bluetooth", ble.last_error)


class FakeBle:
    """A BleMidi whose gatttool stream is a pipe the test writes lines to."""

    def __init__(self):
        self.real = BleMidi("E7:47:8F:02:4C:26", run=FakeTools())
        self.name, self.address = "FP-30X MIDI", "E7:47:8F:02:4C:26"
        self.handles = (0x0C, 0x0D)
        self.linked = False
        self.state = "idle"
        self.connects = self.releases = 0
        self.last_error = None
        self.writer = None
        self.ready = threading.Event()

    def status(self):
        return {"state": self.state}

    def connect(self):
        self.writer = None
        self.connects += 1
        self.state = "linking"
        return True

    def parse_line(self, line):
        self.real.linked, self.real.handles = self.linked, self.handles
        msgs = self.real.parse_line(line)
        if self.real.linked and not self.linked:
            self.linked, self.state = True, "connected"
        return msgs

    def is_connected(self):
        return self.linked

    def release(self):
        if self.state in ("connected", "linking"):
            self.releases += 1
        self.linked = False
        self.state = "released"

    def open_stream(self):
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
            time.sleep(0.3)
            self.assertFalse(col.status["connected"])  # not until the piano accepts
            os.write(ble.writer, b"Characteristic value was written successfully\n")
            self.assertTrue(wait_for(lambda: col.status["transport"] == "bluetooth"))
            self.assertEqual(col.status["name"], "FP-30X MIDI")
            self.play(lambda p: os.write(ble.writer, (
                f"Notification handle = 0x000c value: 80 80 90 {p:02x} 5a 81 80 {p:02x} 40\n"
                ).encode()), 60)
            self.assertTrue(wait_for(lambda: col.recorder.note_count == 10))

            # USB plugged in: Bluetooth is released and USB is read.
            os.mkfifo(self.usb)
            self.assertTrue(wait_for(lambda: col.status["transport"] == "usb"))
            self.assertEqual(ble.releases, 1)
            self.assertEqual(ble.state, "released")
            with open(self.usb, "wb", buffering=0) as f:
                self.play(lambda p: f.write(bytes([0x90, p, 80, 0x80, p, 0])), 40)
                self.assertTrue(wait_for(lambda: col.recorder.note_count >= 10
                                         and col.status["last_event"] is not None))
            sessions = self.store.sessions(closed_only=True)
            self.assertEqual(len(sessions), 1)  # the Bluetooth session, closed on the switch
            self.assertEqual(sessions[0]["source"], "FP-30X MIDI")

            # Unplug, then replug: back on Bluetooth meanwhile, USB again after.
            os.unlink(self.usb)
            self.assertTrue(wait_for(lambda: ble.connects == 2 and ble.writer is not None))
            os.write(ble.writer, b"Characteristic value was written successfully\n")
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
