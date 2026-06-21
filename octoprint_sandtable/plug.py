# coding=utf-8
"""Local-LAN smart-plug drivers for OctoPrint-SandTable.

No cloud. Each driver knows how to turn its plug ON and how to turn it OFF after
an optional safe delay (so the Raspberry Pi can shut down cleanly before power is
cut). The delay must live *on the plug* because the Pi is about to lose power, so
an in-process sleep can't be relied on.

The plug types here cover the three the user asked about: Shelly (Gen1 + Gen2/Plus),
Tasmota, and TP-Link Kasa.
"""

import logging

import requests

LOG = logging.getLogger("octoprint.plugins.sandtable.plug")

DEFAULT_TIMEOUT = 8  # seconds

PLUG_TYPES = ("shelly1", "shelly2", "tasmota", "kasa")


class PlugError(Exception):
    """Raised when a plug command fails (network, auth, bad config)."""


class BasePlug(object):
    def __init__(self, host, user=None, password=None, timeout=DEFAULT_TIMEOUT):
        self.host = (host or "").strip()
        self.user = (user or "").strip() or None
        self.password = password if password else None
        self.timeout = timeout
        if not self.host:
            raise PlugError("Smart-plug host/IP is not configured.")

    # --- helpers ---------------------------------------------------------
    def base_url(self):
        host = self.host
        if not host.startswith("http://") and not host.startswith("https://"):
            host = "http://" + host
        return host.rstrip("/")

    def _auth(self):
        if self.user:
            return (self.user, self.password or "")
        return None

    def _get(self, url, params=None):
        try:
            resp = requests.get(url, params=params, auth=self._auth(), timeout=self.timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            raise PlugError("GET {} failed: {}".format(url, exc))

    def _post_json(self, url, payload):
        try:
            resp = requests.post(url, json=payload, auth=self._auth(), timeout=self.timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            raise PlugError("POST {} failed: {}".format(url, exc))

    # --- interface -------------------------------------------------------
    def on(self):
        raise NotImplementedError

    def off(self, delay_seconds=0):
        """Turn the plug OFF. If delay_seconds > 0, the plug stays ON for that
        long and then switches OFF on its own (so the Pi can halt first)."""
        raise NotImplementedError

    def supports_safe_delay(self):
        """True if off(delay) is honoured on the device itself."""
        return False


class ShellyGen1Plug(BasePlug):
    """Shelly Gen1 legacy HTTP API: /relay/0?turn=on|off[&timer=N].

    The `timer` is a one-shot flip-back timer, so to keep the relay ON for D
    seconds and then drop it we send turn=on&timer=D (auto-off after D)."""

    def on(self):
        self._get(self.base_url() + "/relay/0", params={"turn": "on"})

    def off(self, delay_seconds=0):
        if delay_seconds and delay_seconds > 0:
            self._get(self.base_url() + "/relay/0", params={"turn": "on", "timer": int(delay_seconds)})
        else:
            self._get(self.base_url() + "/relay/0", params={"turn": "off"})

    def supports_safe_delay(self):
        return True


class ShellyGen2Plug(BasePlug):
    """Shelly Gen2/Gen3/Gen4 (and Plus) JSON-RPC at /rpc. Switch.Set with
    `toggle_after` keeps the relay in the requested state for N seconds then flips
    it back. These devices use HTTP *digest* auth (user is always "admin") when a
    password is set; with no password (default) the local API is open."""

    def _auth(self):
        if self.password:
            from requests.auth import HTTPDigestAuth

            return HTTPDigestAuth(self.user or "admin", self.password)
        return None

    def _rpc(self, method, params):
        payload = {"id": 1, "method": method, "params": params}
        resp = self._post_json(self.base_url() + "/rpc", payload)
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if isinstance(data, dict) and data.get("error"):
            raise PlugError("Shelly RPC {} error: {}".format(method, data["error"]))
        return data

    def on(self):
        self._rpc("Switch.Set", {"id": 0, "on": True})

    def off(self, delay_seconds=0):
        if delay_seconds and delay_seconds > 0:
            # Stay ON now, automatically toggle to OFF after delay_seconds.
            self._rpc("Switch.Set", {"id": 0, "on": True, "toggle_after": int(delay_seconds)})
        else:
            self._rpc("Switch.Set", {"id": 0, "on": False})

    def supports_safe_delay(self):
        return True


class TasmotaPlug(BasePlug):
    """Tasmota HTTP command API at /cmnd. For a safe delayed off we queue a
    `Backlog Delay <ds>; Power Off` (Delay is in 0.1s units, max 3600 = 360 s),
    which runs on the device while the HTTP call returns immediately."""

    MAX_DELAY_SECONDS = 360

    def _cmnd(self, command):
        params = {"cmnd": command}
        if self.user:
            params["user"] = self.user
            params["password"] = self.password or ""
        # auth is via query params for Tasmota, not HTTP basic
        try:
            resp = requests.get(self.base_url() + "/cmnd", params=params, timeout=self.timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            raise PlugError("Tasmota command failed: {}".format(exc))

    def on(self):
        self._cmnd("Power On")

    def off(self, delay_seconds=0):
        if delay_seconds and delay_seconds > 0:
            ds = min(int(delay_seconds), self.MAX_DELAY_SECONDS) * 10  # 0.1s units
            self._cmnd("Backlog Delay {}; Power Off".format(ds))
        else:
            self._cmnd("Power Off")

    def supports_safe_delay(self):
        return True


class KasaPlug(BasePlug):
    """TP-Link Kasa via the python-kasa library (lazy import; async under the hood).

    Kasa's local protocol has no simple reliable "off after N seconds" primitive
    we can lean on here, so off() is immediate -- meaning the Pi may lose power
    without a clean shutdown. Prefer Shelly/Tasmota when the plug also powers the
    Pi. See README."""

    def _run(self, make_coro):
        try:
            import asyncio

            import kasa  # noqa: F401  (presence check)
        except ImportError:
            raise PlugError(
                "The Kasa driver needs python-kasa. Install it with: pip install \"python-kasa>=0.5.0\""
            )
        import asyncio

        try:
            return asyncio.run(make_coro())
        except Exception as exc:  # network / protocol / version errors
            raise PlugError("Kasa command failed: {}".format(exc))

    async def _device(self):
        # Support both the newer (Device.connect) and older (SmartPlug) APIs.
        import kasa

        if hasattr(kasa, "Device") and hasattr(kasa.Device, "connect"):
            return await kasa.Device.connect(host=self.host)
        dev = kasa.SmartPlug(self.host)
        await dev.update()
        return dev

    def on(self):
        async def _do():
            dev = await self._device()
            await dev.turn_on()

        self._run(lambda: _do())

    def off(self, delay_seconds=0):
        if delay_seconds and delay_seconds > 0:
            LOG.warning("Kasa driver does not support a safe power-off delay; switching off immediately.")

        async def _do():
            dev = await self._device()
            await dev.turn_off()

        self._run(lambda: _do())

    def supports_safe_delay(self):
        return False


_DRIVERS = {
    "shelly1": ShellyGen1Plug,
    "shelly2": ShellyGen2Plug,
    "tasmota": TasmotaPlug,
    "kasa": KasaPlug,
}


def make_plug(plug_type, host, user=None, password=None, timeout=DEFAULT_TIMEOUT):
    """Factory: build a plug driver from settings."""
    cls = _DRIVERS.get((plug_type or "").strip().lower())
    if cls is None:
        raise PlugError(
            "Unknown plug type {!r}. Expected one of: {}".format(plug_type, ", ".join(PLUG_TYPES))
        )
    return cls(host, user=user, password=password, timeout=timeout)
