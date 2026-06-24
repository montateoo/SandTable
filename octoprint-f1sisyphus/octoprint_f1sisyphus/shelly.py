# coding=utf-8
"""Shelly Gen2+ JSON-RPC helper for OctoPrint-F1Sisyphus.

Deliberately NOT imported from octoprint_sandtable.plug -- each plugin owns
its own copy, per the user's stated long-term architecture, since the two
plugins independently manage their own schedule jobs on the same shared
Shelly device.

IMPORTANT: this device is SHARED with the SandTable plugin, which already
owns schedule ids 1 and 2 (confirmed live via Schedule.List against the real
device, 192.168.1.55). replace_schedule() below deletes only the single
schedule id THIS plugin itself previously created -- it must never call
Schedule.DeleteAll, which would silently wipe the sibling plugin's jobs too.
An earlier draft of this design called DeleteAll and was caught and
corrected during planning specifically because of this shared-device fact.
"""

import requests

DEFAULT_TIMEOUT = 8


class ShellyError(Exception):
    """Raised when a Shelly RPC call fails (network, auth, or a JSON-RPC error)."""


class ShellyClient(object):
    """JSON-RPC client at /rpc. Same auth pattern as octoprint_sandtable's
    ShellyGen2Plug: HTTPDigestAuth('admin', password) iff a password is set,
    else no auth (the local API is open with no password configured)."""

    def __init__(self, host, password=None, timeout=DEFAULT_TIMEOUT):
        host = (host or "").strip()
        if not host:
            raise ShellyError("Shelly host/IP is not configured.")
        if not host.startswith("http://") and not host.startswith("https://"):
            host = "http://" + host
        self.base_url = host.rstrip("/")
        self.password = password or None
        self.timeout = timeout
        self._id = 0

    def _auth(self):
        if self.password:
            from requests.auth import HTTPDigestAuth

            return HTTPDigestAuth("admin", self.password)
        return None

    def rpc(self, method, params=None):
        self._id += 1
        payload = {"id": self._id, "method": method}
        if params is not None:
            payload["params"] = params
        try:
            resp = requests.post(self.base_url + "/rpc", json=payload, auth=self._auth(), timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise ShellyError("{} failed: {}".format(method, exc))
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if isinstance(data, dict) and data.get("error"):
            raise ShellyError("{} error: {}".format(method, data["error"]))
        return data.get("result", {}) if isinstance(data, dict) else {}

    def switch_set(self, on, switch_id=0, toggle_after=None):
        params = {"id": switch_id, "on": on}
        if toggle_after:
            params["toggle_after"] = int(toggle_after)
        return self.rpc("Switch.Set", params)

    def get_timezone(self):
        cfg = self.rpc("Sys.GetConfig")
        return (cfg.get("location") or {}).get("tz")

    def list_schedules(self):
        return self.rpc("Schedule.List").get("jobs", [])

    def create_schedule(self, timespec, calls):
        result = self.rpc("Schedule.Create", {"enable": True, "timespec": timespec, "calls": calls})
        return result.get("id")

    def delete_schedule(self, schedule_id):
        try:
            self.rpc("Schedule.Delete", {"id": schedule_id})
        except ShellyError as exc:
            # Already gone (e.g. a retry after a partial earlier failure) -- fine.
            if "not found" not in str(exc).lower():
                raise


def to_timespec(local_dt):
    """Shelly 6-field cron: sec min hour day-of-month month day-of-week.
    day-of-week is '*' so the job fires on that exact calendar date.
    Ported verbatim from tools/f1_shelly_scheduler.py."""
    return "{} {} {} {} {} *".format(local_dt.second, local_dt.minute, local_dt.hour, local_dt.day, local_dt.month)


def build_wake_schedule_calls(switch_id, script_id):
    """The `calls` list for Schedule.Create: flip the relay on, then invoke
    the dedicated f1sisyphus_waker script's entry point -- matching the
    structure of the SandTable plugin's own live schedule jobs (confirmed via
    Schedule.List against the real device)."""
    return [
        {"method": "Switch.Set", "params": {"id": switch_id, "on": True}},
        {"method": "Script.Eval", "params": {"id": script_id, "code": "wakeAndStartF1()"}},
    ]


def replace_schedule(client, prev_schedule_id, timespec, calls):
    """Delete prev_schedule_id (if not None) then create exactly one new
    schedule job. Returns the new job's id, which the caller MUST persist
    (settings key `shelly_schedule_id`) and pass back in as prev_schedule_id
    next time. Never calls Schedule.DeleteAll -- see module docstring."""
    if prev_schedule_id is not None:
        client.delete_schedule(prev_schedule_id)
    return client.create_schedule(timespec, calls)
