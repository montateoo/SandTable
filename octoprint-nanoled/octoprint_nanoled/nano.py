# coding=utf-8
"""Thin serial client for the Arduino Nano running LED-Arduino/LED-Control/LED-Control.ino.

Pure aside from `pyserial` -- no OctoPrint imports -- so it is unit-testable by monkeypatching
the `serial` module reference, mirroring shelly.py/test_shelly.py's FakeRequests pattern.
"""

import serial

DEFAULT_BAUD_RATE = 115200
DEFAULT_TIMEOUT = 2


class NanoError(Exception):
    """Raised when opening or writing to the Nano's serial connection fails."""


class NanoClient(object):
    def __init__(self, port, baud_rate=DEFAULT_BAUD_RATE, timeout=DEFAULT_TIMEOUT):
        port = (port or "").strip()
        if not port:
            raise NanoError("Serial port is not configured.")
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self._conn = None

    def _ensure_open(self):
        if self._conn is not None and getattr(self._conn, "is_open", True):
            return self._conn
        try:
            self._conn = serial.Serial(self.port, self.baud_rate, timeout=self.timeout)
        except Exception as exc:
            self._conn = None
            raise NanoError("Could not open {}: {}".format(self.port, exc))
        return self._conn

    def send_line(self, line):
        """Write line + '\\n' as utf-8 bytes. Raises NanoError on any failure,
        and drops the connection so the next call reopens it fresh."""
        conn = self._ensure_open()
        try:
            conn.write((line + "\n").encode("utf-8"))
        except Exception as exc:
            self._conn = None
            raise NanoError("Write to {} failed: {}".format(self.port, exc))

    def set_pattern(self, n):
        """n: 0-10, matches the sketch's existing pattern0()..pattern10()."""
        self.send_line("PATTERN:{}".format(int(n)))

    def set_solid(self, color_name):
        """color_name: RED, YELLOW, GREEN, or WHITE (case-insensitive)."""
        self.send_line("SOLID:{}".format((color_name or "").upper()))

    def flicker_rainbow(self):
        self.send_line("FLICKER_RAINBOW")

    def flash_white(self):
        self.send_line("FLASH_WHITE")

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
