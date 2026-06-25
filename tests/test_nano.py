import pytest

import nano


class FakeSerialConn:
    def __init__(self, port, baud_rate, timeout=None, fail_open=False, fail_write=False):
        if fail_open:
            raise OSError("could not open port")
        self.port = port
        self.baud_rate = baud_rate
        self.is_open = True
        self.written = []
        self.closed = False
        self._fail_write = fail_write

    def write(self, data):
        if self._fail_write:
            raise OSError("write failed")
        self.written.append(data)

    def close(self):
        self.closed = True
        self.is_open = False


class FakeSerialModule:
    def __init__(self, fail_open=False, fail_write=False):
        self.fail_open = fail_open
        self.fail_write = fail_write
        self.instances = []

    def Serial(self, port, baud_rate, timeout=None):
        conn = FakeSerialConn(port, baud_rate, timeout, fail_open=self.fail_open, fail_write=self.fail_write)
        self.instances.append(conn)
        return conn


@pytest.fixture
def fake_serial(monkeypatch):
    fake = FakeSerialModule()
    monkeypatch.setattr(nano, "serial", fake)
    return fake


# --- NanoClient basics -------------------------------------------------------
def test_client_requires_port():
    with pytest.raises(nano.NanoError):
        nano.NanoClient("")


def test_send_line_opens_and_writes(fake_serial):
    client = nano.NanoClient("/dev/serial0")
    client.send_line("PATTERN:3")
    conn = fake_serial.instances[-1]
    assert conn.written == [b"PATTERN:3\n"]


def test_send_line_reuses_open_connection(fake_serial):
    client = nano.NanoClient("/dev/serial0")
    client.send_line("PATTERN:1")
    client.send_line("PATTERN:2")
    assert len(fake_serial.instances) == 1


def test_open_failure_raises_nano_error(monkeypatch):
    fake = FakeSerialModule(fail_open=True)
    monkeypatch.setattr(nano, "serial", fake)
    client = nano.NanoClient("/dev/serial0")
    with pytest.raises(nano.NanoError):
        client.send_line("PATTERN:1")


def test_write_failure_raises_nano_error_and_drops_connection(monkeypatch):
    fake = FakeSerialModule(fail_write=True)
    monkeypatch.setattr(nano, "serial", fake)
    client = nano.NanoClient("/dev/serial0")
    with pytest.raises(nano.NanoError):
        client.send_line("PATTERN:1")
    assert client._conn is None


# --- command-building helpers -------------------------------------------------
def test_set_pattern_sends_expected_line(fake_serial):
    client = nano.NanoClient("/dev/serial0")
    client.set_pattern(7)
    assert fake_serial.instances[-1].written == [b"PATTERN:7\n"]


def test_set_solid_uppercases_color(fake_serial):
    client = nano.NanoClient("/dev/serial0")
    client.set_solid("red")
    assert fake_serial.instances[-1].written == [b"SOLID:RED\n"]


def test_flicker_rainbow_sends_expected_line(fake_serial):
    client = nano.NanoClient("/dev/serial0")
    client.flicker_rainbow()
    assert fake_serial.instances[-1].written == [b"FLICKER_RAINBOW\n"]


def test_flash_white_sends_expected_line(fake_serial):
    client = nano.NanoClient("/dev/serial0")
    client.flash_white()
    assert fake_serial.instances[-1].written == [b"FLASH_WHITE\n"]


def test_close_closes_connection(fake_serial):
    client = nano.NanoClient("/dev/serial0")
    client.send_line("PATTERN:1")
    conn = fake_serial.instances[-1]
    client.close()
    assert conn.closed is True
    assert client._conn is None
