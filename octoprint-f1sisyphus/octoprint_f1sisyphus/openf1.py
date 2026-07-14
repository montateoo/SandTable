# coding=utf-8
"""Thin OpenF1 (https://openf1.org) HTTP client, shared by circuit.py (circuit
outline generation) and __init__.py (live position polling, "next race"
lookup). Pure aside from `requests` -- no OctoPrint imports -- so it is
unit-testable with a FakeRequests fixture, mirroring plug.py/test_plug.py.
"""

import time

import requests

DEFAULT_API_BASE = "https://api.openf1.org/v1"
DEFAULT_TIMEOUT = 15

# The /location endpoint (used by circuit.py to fetch a whole historical
# session's worth of car position data) has been observed to 429 for several
# minutes at a time -- longer than the ~30 req/min the docs advertise for
# lightweight queries. A handful of short retries turns a single transient
# 429 into a success without making callers orchestrate their own backoff;
# callers that still exhaust retries get the same OpenF1Error as before.
RATE_LIMIT_MAX_RETRIES = 3
RATE_LIMIT_BACKOFF_SECONDS = (2, 5, 10)


class OpenF1Error(Exception):
    """Raised when an OpenF1 request fails (network, bad status, bad JSON)."""


class OpenF1Client(object):
    def __init__(self, api_base=DEFAULT_API_BASE, timeout=DEFAULT_TIMEOUT):
        self.api_base = (api_base or DEFAULT_API_BASE).rstrip("/")
        self.timeout = timeout

    def _get(self, path, params=None):
        url = "{}/{}".format(self.api_base, path)
        attempt = 0
        while True:
            try:
                resp = requests.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
            except requests.RequestException as exc:
                status = getattr(exc.response, "status_code", None)
                if status == 429 and attempt < RATE_LIMIT_MAX_RETRIES:
                    delay = _retry_after_seconds(exc.response) or RATE_LIMIT_BACKOFF_SECONDS[
                        min(attempt, len(RATE_LIMIT_BACKOFF_SECONDS) - 1)
                    ]
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise OpenF1Error("GET {} failed: {}".format(url, exc))
            try:
                return resp.json()
            except ValueError as exc:
                raise OpenF1Error("GET {} returned invalid JSON: {}".format(url, exc))

    def get_sessions(self, **params):
        return self._get("sessions", params=params)

    def get_laps(self, session_key, driver_number):
        return self._get("laps", params={"session_key": session_key, "driver_number": driver_number})

    def get_location(self, session_key, driver_number, date_gt=None):
        params = {"session_key": session_key, "driver_number": driver_number}
        if date_gt:
            params["date>"] = date_gt
        return self._get("location", params=params)

    def get_race_control(self, session_key, date_gt=None):
        params = {"session_key": session_key}
        if date_gt:
            params["date>"] = date_gt
        return self._get("race_control", params=params)

    def get_upcoming_race(self, after_utc):
        """The earliest Race session starting strictly after after_utc, or
        None if no future race is in the published calendar yet."""
        sessions = self.get_sessions(session_name="Race") or []
        candidates = [s for s in sessions if _session_date(s) and _session_date(s) > after_utc]
        if not candidates:
            return None
        return min(candidates, key=_session_date)

    def get_latest_past_race_at_circuit(self, circuit_key, before_utc):
        """The most recent Race session at circuit_key starting strictly
        before before_utc, or None if this circuit has no past race yet."""
        sessions = self.get_sessions(circuit_key=circuit_key, session_name="Race") or []
        candidates = [s for s in sessions if _session_date(s) and _session_date(s) < before_utc]
        if not candidates:
            return None
        return max(candidates, key=_session_date)


def _retry_after_seconds(response):
    """Honor the server's own Retry-After header when present (RFC 7231
    integer-seconds form); OpenF1 doesn't document sending one today, but
    respecting it if it ever appears beats guessing at a fixed backoff."""
    if response is None:
        return None
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        return None


def _session_date(session):
    date_start = session.get("date_start")
    if not date_start:
        return None
    return _parse_iso(date_start)


def _parse_iso(date_str):
    import datetime

    # OpenF1 dates are UTC, suffixed with 'Z' or '+00:00'.
    return datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
