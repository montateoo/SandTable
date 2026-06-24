import datetime

import pytest
import requests as real_requests

import shelly


class FakeResponse:
    def __init__(self, json_data=None):
        self._json = json_data or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class FakeRequests:
    RequestException = real_requests.RequestException

    def __init__(self):
        self.calls = []
        self.json_to_return = {}

    def post(self, url, json=None, auth=None, timeout=None):
        self.calls.append(("POST", url, json, auth))
        return FakeResponse(self.json_to_return)

    @property
    def last(self):
        return self.calls[-1]


@pytest.fixture
def fake_requests(monkeypatch):
    fake = FakeRequests()
    monkeypatch.setattr(shelly, "requests", fake)
    return fake


# --- ShellyClient basics -----------------------------------------------------
def test_client_requires_host():
    with pytest.raises(shelly.ShellyError):
        shelly.ShellyClient("")


def test_rpc_posts_to_rpc_endpoint(fake_requests):
    shelly.ShellyClient("1.2.3.4").rpc("Sys.GetConfig")
    method, url, payload, _ = fake_requests.last
    assert method == "POST" and url == "http://1.2.3.4/rpc"
    assert payload["method"] == "Sys.GetConfig"


def test_rpc_no_password_means_no_auth(fake_requests):
    shelly.ShellyClient("1.2.3.4").rpc("Sys.GetConfig")
    _, _, _, auth = fake_requests.last
    assert auth is None


def test_rpc_password_uses_digest_auth_with_admin_user(fake_requests):
    from requests.auth import HTTPDigestAuth

    shelly.ShellyClient("1.2.3.4", password="secret").rpc("Sys.GetConfig")
    _, _, _, auth = fake_requests.last
    assert isinstance(auth, HTTPDigestAuth)
    assert auth.username == "admin"
    assert auth.password == "secret"


def test_rpc_error_field_raises(fake_requests):
    fake_requests.json_to_return = {"error": {"code": -103, "message": "bad"}}
    with pytest.raises(shelly.ShellyError):
        shelly.ShellyClient("1.2.3.4").rpc("Sys.GetConfig")


def test_switch_set_includes_toggle_after_when_given(fake_requests):
    shelly.ShellyClient("1.2.3.4").switch_set(True, switch_id=0, toggle_after=60)
    _, _, payload, _ = fake_requests.last
    assert payload["params"] == {"id": 0, "on": True, "toggle_after": 60}


def test_get_timezone_reads_location_tz(fake_requests):
    fake_requests.json_to_return = {"result": {"location": {"tz": "Europe/Rome"}}}
    tz = shelly.ShellyClient("1.2.3.4").get_timezone()
    assert tz == "Europe/Rome"


def test_list_schedules_returns_jobs(fake_requests):
    fake_requests.json_to_return = {"result": {"jobs": [{"id": 1}, {"id": 2}]}}
    jobs = shelly.ShellyClient("1.2.3.4").list_schedules()
    assert jobs == [{"id": 1}, {"id": 2}]


def test_create_schedule_returns_new_id(fake_requests):
    fake_requests.json_to_return = {"result": {"id": 3}}
    new_id = shelly.ShellyClient("1.2.3.4").create_schedule("0 0 12 1 1 *", [{"method": "Switch.Set"}])
    assert new_id == 3
    _, _, payload, _ = fake_requests.last
    assert payload["method"] == "Schedule.Create"
    assert payload["params"]["enable"] is True


def test_delete_schedule_swallows_not_found(fake_requests):
    fake_requests.json_to_return = {"error": {"code": -32000, "message": "not found"}}
    shelly.ShellyClient("1.2.3.4").delete_schedule(99)  # must not raise


def test_delete_schedule_reraises_other_errors(fake_requests):
    fake_requests.json_to_return = {"error": {"code": -32000, "message": "boom"}}
    with pytest.raises(shelly.ShellyError):
        shelly.ShellyClient("1.2.3.4").delete_schedule(99)


# --- to_timespec --------------------------------------------------------------
def test_to_timespec_formats_six_fields():
    dt = datetime.datetime(2026, 6, 28, 12, 5, 30)
    assert shelly.to_timespec(dt) == "30 5 12 28 6 *"


# --- build_wake_schedule_calls -------------------------------------------------
def test_build_wake_schedule_calls_shape():
    calls = shelly.build_wake_schedule_calls(switch_id=0, script_id=2)
    assert calls == [
        {"method": "Switch.Set", "params": {"id": 0, "on": True}},
        {"method": "Script.Eval", "params": {"id": 2, "code": "wakeAndStartF1()"}},
    ]


# --- replace_schedule (the critical shared-device-safety behavior) -----------
class FakeShellyClient:
    def __init__(self):
        self.calls = []
        self.next_id = 100

    def delete_schedule(self, schedule_id):
        self.calls.append(("delete", schedule_id))

    def create_schedule(self, timespec, calls):
        self.calls.append(("create", timespec, calls))
        new_id = self.next_id
        self.next_id += 1
        return new_id


def test_replace_schedule_first_time_only_creates_no_delete():
    client = FakeShellyClient()
    new_id = shelly.replace_schedule(client, None, "0 0 12 1 1 *", [{"method": "x"}])
    assert client.calls == [("create", "0 0 12 1 1 *", [{"method": "x"}])]
    assert new_id == 100


def test_replace_schedule_deletes_only_its_own_previous_id_then_creates():
    client = FakeShellyClient()
    new_id = shelly.replace_schedule(client, 7, "0 0 12 1 1 *", [{"method": "x"}])
    assert client.calls == [
        ("delete", 7),
        ("create", "0 0 12 1 1 *", [{"method": "x"}]),
    ]
    assert new_id == 100


def test_replace_schedule_never_calls_delete_all():
    client = FakeShellyClient()
    assert not hasattr(client, "delete_all_schedules")
    shelly.replace_schedule(client, 7, "0 0 12 1 1 *", [{"method": "x"}])
    for call in client.calls:
        assert call[0] != "delete_all"
