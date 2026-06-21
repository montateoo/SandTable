import pytest
import requests as real_requests

import plug


class FakeResponse:
    def __init__(self, json_data=None):
        self._json = json_data or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class FakeRequests:
    """Stand-in for the `requests` module used inside plug.py."""

    RequestException = real_requests.RequestException

    def __init__(self):
        self.calls = []
        self.json_to_return = {}

    def get(self, url, params=None, auth=None, timeout=None):
        self.calls.append(("GET", url, params, auth))
        return FakeResponse()

    def post(self, url, json=None, auth=None, timeout=None):
        self.calls.append(("POST", url, json, auth))
        return FakeResponse(self.json_to_return)

    @property
    def last(self):
        return self.calls[-1]


@pytest.fixture
def fake_requests(monkeypatch):
    fake = FakeRequests()
    monkeypatch.setattr(plug, "requests", fake)
    return fake


# --- factory --------------------------------------------------------------
def test_make_plug_returns_right_type():
    assert isinstance(plug.make_plug("shelly1", "1.2.3.4"), plug.ShellyGen1Plug)
    assert isinstance(plug.make_plug("shelly2", "1.2.3.4"), plug.ShellyGen2Plug)
    assert isinstance(plug.make_plug("tasmota", "1.2.3.4"), plug.TasmotaPlug)
    assert isinstance(plug.make_plug("kasa", "1.2.3.4"), plug.KasaPlug)


def test_make_plug_unknown_type_raises():
    with pytest.raises(plug.PlugError):
        plug.make_plug("nope", "1.2.3.4")


def test_make_plug_requires_host():
    with pytest.raises(plug.PlugError):
        plug.make_plug("shelly1", "")


def test_base_url_adds_scheme_and_strips_slash():
    assert plug.ShellyGen1Plug("1.2.3.4").base_url() == "http://1.2.3.4"
    assert plug.ShellyGen1Plug("http://host:8080/").base_url() == "http://host:8080"


# --- Shelly Gen1 ----------------------------------------------------------
def test_shelly1_on(fake_requests):
    plug.ShellyGen1Plug("1.2.3.4").on()
    method, url, params, _ = fake_requests.last
    assert method == "GET" and url == "http://1.2.3.4/relay/0"
    assert params == {"turn": "on"}


def test_shelly1_off_with_delay_keeps_on_then_autooff(fake_requests):
    plug.ShellyGen1Plug("1.2.3.4").off(60)
    _, url, params, _ = fake_requests.last
    assert url == "http://1.2.3.4/relay/0"
    assert params == {"turn": "on", "timer": 60}


def test_shelly1_off_immediate(fake_requests):
    plug.ShellyGen1Plug("1.2.3.4").off(0)
    _, _, params, _ = fake_requests.last
    assert params == {"turn": "off"}


def test_shelly1_basic_auth(fake_requests):
    plug.ShellyGen1Plug("1.2.3.4", user="u", password="p").on()
    _, _, _, auth = fake_requests.last
    assert auth == ("u", "p")


# --- Shelly Gen2 ----------------------------------------------------------
def test_shelly2_off_with_delay_uses_toggle_after(fake_requests):
    plug.ShellyGen2Plug("1.2.3.4").off(45)
    method, url, payload, _ = fake_requests.last
    assert method == "POST" and url == "http://1.2.3.4/rpc"
    assert payload["method"] == "Switch.Set"
    assert payload["params"] == {"id": 0, "on": True, "toggle_after": 45}


def test_shelly2_off_immediate(fake_requests):
    plug.ShellyGen2Plug("1.2.3.4").off(0)
    _, _, payload, _ = fake_requests.last
    assert payload["params"] == {"id": 0, "on": False}


def test_shelly2_rpc_error_raises(fake_requests):
    fake_requests.json_to_return = {"error": {"code": -103, "message": "bad"}}
    with pytest.raises(plug.PlugError):
        plug.ShellyGen2Plug("1.2.3.4").off(0)


def test_shelly2_no_password_means_no_auth(fake_requests):
    plug.ShellyGen2Plug("1.2.3.4").on()
    _, _, _, auth = fake_requests.last
    assert auth is None


def test_shelly2_password_uses_digest_auth_with_admin_user(fake_requests):
    from requests.auth import HTTPDigestAuth

    plug.ShellyGen2Plug("1.2.3.4", password="secret").on()
    _, _, _, auth = fake_requests.last
    assert isinstance(auth, HTTPDigestAuth)
    assert auth.username == "admin"  # Shelly Gen2+ user is always admin
    assert auth.password == "secret"


# --- Tasmota --------------------------------------------------------------
def test_tasmota_off_with_delay_builds_backlog(fake_requests):
    plug.TasmotaPlug("1.2.3.4").off(60)
    _, url, params, _ = fake_requests.last
    assert url == "http://1.2.3.4/cmnd"
    assert params["cmnd"] == "Backlog Delay 600; Power Off"  # 60s -> 600 in 0.1s units


def test_tasmota_off_caps_delay_at_360s(fake_requests):
    plug.TasmotaPlug("1.2.3.4").off(9999)
    _, _, params, _ = fake_requests.last
    assert params["cmnd"] == "Backlog Delay 3600; Power Off"


def test_tasmota_off_immediate(fake_requests):
    plug.TasmotaPlug("1.2.3.4").off(0)
    _, _, params, _ = fake_requests.last
    assert params["cmnd"] == "Power Off"


def test_tasmota_auth_is_query_params(fake_requests):
    plug.TasmotaPlug("1.2.3.4", user="admin", password="secret").on()
    _, _, params, _ = fake_requests.last
    assert params["cmnd"] == "Power On"
    assert params["user"] == "admin" and params["password"] == "secret"


# --- capability flags -----------------------------------------------------
def test_safe_delay_capability_flags():
    assert plug.ShellyGen1Plug("h").supports_safe_delay() is True
    assert plug.ShellyGen2Plug("h").supports_safe_delay() is True
    assert plug.TasmotaPlug("h").supports_safe_delay() is True
    assert plug.KasaPlug("h").supports_safe_delay() is False


def test_request_failure_becomes_plugerror(fake_requests):
    def boom(*a, **k):
        raise real_requests.RequestException("network down")

    fake_requests.get = boom
    with pytest.raises(plug.PlugError):
        plug.ShellyGen1Plug("1.2.3.4").on()
