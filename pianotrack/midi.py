"""MIDI byte-stream parsing plus a small Standard MIDI File reader/writer.

Everything here is pure Python so the collector has no native dependencies.
"""

import struct

# Number of data bytes that follow each channel-voice status (high nibble).
_CHANNEL_DATA_LEN = {0x80: 2, 0x90: 2, 0xA0: 2, 0xB0: 2, 0xC0: 1, 0xD0: 1, 0xE0: 2}
# System common messages and their data length.
_SYSTEM_COMMON_LEN = {0xF1: 1, 0xF2: 2, 0xF3: 1, 0xF6: 0}


class StreamParser:
    """Turns raw MIDI bytes (as read from /dev/snd/midiCxDy) into messages.

    Handles running status, realtime bytes interleaved anywhere (Roland pianos
    send Active Sensing 0xFE every ~300 ms), and SysEx. Emits tuples of ints,
    e.g. (0x90, 60, 100). Realtime and SysEx messages are dropped because the
    tracker has no use for them.
    """

    def __init__(self):
        self._status = None
        self._needed = 0
        self._data = []
        self._in_sysex = False

    def feed(self, data):
        out = []
        for b in data:
            if b >= 0xF8:  # realtime: never affects running status
                continue
            if b == 0xF0:
                self._in_sysex = True
                self._status = None
                continue
            if b == 0xF7:
                self._in_sysex = False
                continue
            if b & 0x80:
                self._in_sysex = False
                if b >= 0xF0:  # system common cancels running status
                    self._status = None
                    n = _SYSTEM_COMMON_LEN.get(b, 0)
                    if n:
                        self._status, self._needed, self._data = b, n, []
                    continue
                self._status = b
                self._needed = _CHANNEL_DATA_LEN[b & 0xF0]
                self._data = []
                continue
            if self._in_sysex or self._status is None:
                continue
            self._data.append(b)
            if len(self._data) == self._needed:
                msg = (self._status, *self._data)
                if self._status >= 0xF0:
                    self._status = None  # system common has no running status
                else:
                    out.append(msg)
                self._data = []
        return out


def encode(msg):
    return bytes(msg)


# --- Standard MIDI Files -----------------------------------------------------

def _read_varlen(buf, pos):
    value = 0
    while True:
        b = buf[pos]
        pos += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, pos


def _write_varlen(value):
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def read_smf(path):
    """Read a .mid file and return [(seconds, msg_tuple)] sorted by time.

    Supports formats 0 and 1 with tempo changes (ticks-per-beat timing only).
    """
    with open(path, "rb") as f:
        buf = f.read()
    if buf[:4] != b"MThd":
        raise ValueError("not a MIDI file")
    hlen = struct.unpack(">I", buf[4:8])[0]
    _fmt, ntracks, division = struct.unpack(">HHH", buf[8:14])
    if division & 0x8000:
        raise ValueError("SMPTE time division is not supported")
    pos = 8 + hlen
    events = []  # (tick, order, kind, payload)
    order = 0
    for _ in range(ntracks):
        if buf[pos:pos + 4] != b"MTrk":
            raise ValueError("bad track chunk")
        tlen = struct.unpack(">I", buf[pos + 4:pos + 8])[0]
        p, end = pos + 8, pos + 8 + tlen
        tick, status = 0, None
        while p < end:
            delta, p = _read_varlen(buf, p)
            tick += delta
            b = buf[p]
            if b == 0xFF:
                mtype = buf[p + 1]
                mlen, p = _read_varlen(buf, p + 2)
                if mtype == 0x51 and mlen == 3:
                    tempo = int.from_bytes(buf[p:p + 3], "big")
                    events.append((tick, order, "tempo", tempo))
                p += mlen
                if mtype == 0x2F:
                    break
            elif b in (0xF0, 0xF7):
                slen, p = _read_varlen(buf, p + 1)
                p += slen
            else:
                if b & 0x80:
                    status = b
                    p += 1
                n = _CHANNEL_DATA_LEN[status & 0xF0]
                msg = (status, *buf[p:p + n])
                p += n
                events.append((tick, order, "msg", msg))
            order += 1
        pos = end
    events.sort(key=lambda e: (e[0], e[1]))
    out = []
    tempo = 500000
    last_tick, seconds = 0, 0.0
    for tick, _, kind, payload in events:
        seconds += (tick - last_tick) * tempo / 1e6 / division
        last_tick = tick
        if kind == "tempo":
            tempo = payload
        else:
            out.append((seconds, payload))
    return out


def write_smf(events, path=None, division=480, tempo=500000):
    """Write [(seconds, msg_tuple)] as a format-0 file. Returns the bytes."""
    track = bytearray()
    track += b"\x00\xff\x51\x03" + tempo.to_bytes(3, "big")
    ticks_per_sec = division * 1e6 / tempo
    last = 0
    for seconds, msg in sorted(events, key=lambda e: e[0]):
        tick = max(0, int(round(seconds * ticks_per_sec)))
        track += _write_varlen(tick - last) + bytes(msg)
        last = tick
    track += b"\x00\xff\x2f\x00"
    data = (b"MThd" + struct.pack(">IHHH", 6, 0, 1, division)
            + b"MTrk" + struct.pack(">I", len(track)) + bytes(track))
    if path:
        with open(path, "wb") as f:
            f.write(data)
    return data
