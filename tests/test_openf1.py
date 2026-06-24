import datetime

import pytest
import requests as real_requests

import openf1


class FakeResponse:
    def __init__(self, json_data=None):
        self._json = json_data if json_data is not None else []

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class FakeRequests:
    RequestException = real_requests.RequestException

    def __init__(self):
        self.calls = []
        self.json_to_return = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(("GET", url, params))
        return FakeResponse(self.json_to_return)

    @property
    def last(self):
        return self.calls[-1]


@pytest.fixture
def fake_requests(monkeypatch):
    fake = FakeRequests()
    monkeypatch.setattr(openf1, "requests", fake)
    return fake


NOW = datetime.datetime(2026, 6, 24, 12, 0, tzinfo=datetime.timezone.utc)


def _session(session_key, date_start, circuit_key=19, country_name="Austria"):
    return {
        "session_key": session_key,
        "date_start": date_start,
        "circuit_key": circuit_key,
        "country_name": country_name,
        "session_name": "Race",
    }


def test_get_sessions_passes_params(fake_requests):
    openf1.OpenF1Client().get_sessions(year=2026, session_name="Race")
    method, url, params = fake_requests.last
    assert method == "GET"
    assert url == "https://api.openf1.org/v1/sessions"
    assert params == {"year": 2026, "session_name": "Race"}


def test_get_laps_builds_query(fake_requests):
    openf1.OpenF1Client().get_laps(session_key=1234, driver_number=1)
    _, url, params = fake_requests.last
    assert url.endswith("/laps")
    assert params == {"session_key": 1234, "driver_number": 1}


def test_get_location_includes_date_filter_when_given(fake_requests):
    openf1.OpenF1Client().get_location(session_key=1234, driver_number=1, date_gt="2026-06-24T12:00:00Z")
    _, _, params = fake_requests.last
    assert params["date>"] == "2026-06-24T12:00:00Z"


def test_get_location_omits_date_filter_when_not_given(fake_requests):
    openf1.OpenF1Client().get_location(session_key=1234, driver_number=1)
    _, _, params = fake_requests.last
    assert "date>" not in params


def test_get_upcoming_race_picks_earliest_future_session(fake_requests):
    fake_requests.json_to_return = [
        _session(1, "2026-06-01T13:00:00Z"),  # past
        _session(3, "2026-08-01T13:00:00Z"),  # future, later
        _session(2, "2026-07-01T13:00:00Z"),  # future, earliest
    ]
    result = openf1.OpenF1Client().get_upcoming_race(NOW)
    assert result["session_key"] == 2


def test_get_upcoming_race_returns_none_when_no_future_sessions(fake_requests):
    fake_requests.json_to_return = [_session(1, "2026-06-01T13:00:00Z")]
    assert openf1.OpenF1Client().get_upcoming_race(NOW) is None


def test_get_latest_past_race_at_circuit_picks_most_recent_past_session(fake_requests):
    fake_requests.json_to_return = [
        _session(1, "2025-06-01T13:00:00Z"),
        _session(2, "2024-06-01T13:00:00Z"),
        _session(3, "2026-08-01T13:00:00Z"),  # future, excluded
    ]
    result = openf1.OpenF1Client().get_latest_past_race_at_circuit(19, NOW)
    assert result["session_key"] == 1


def test_get_latest_past_race_at_circuit_returns_none_when_no_past_sessions(fake_requests):
    fake_requests.json_to_return = [_session(1, "2027-01-01T13:00:00Z")]
    assert openf1.OpenF1Client().get_latest_past_race_at_circuit(19, NOW) is None
