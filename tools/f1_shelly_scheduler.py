#!/usr/bin/env python3
"""
f1_shelly_scheduler.py

SUPERSEDED -- kept for reference only, do not run as part of normal operation.

The octoprint-f1sisyphus plugin now self-manages its own Shelly schedule: it
computes the next race and reschedules itself after every race completes (see
octoprint_f1sisyphus/shelly.py's replace_schedule() and __init__.py's
_reschedule_for_next_race()), so this standalone batch script is no longer
needed for day-to-day use. It's kept because shelly.py's rpc()/to_timespec()/
list_schedules()/create_schedule() were ported from the code below.

Two more reasons not to run this script against the live device:
1. It loads MULTIPLE upcoming races as separate schedule jobs (see "budget"
   below), whereas the plugin deliberately keeps exactly ONE schedule job at a
   time (its own, tracked by the `shelly_schedule_id` setting).
2. The Shelly device is SHARED with the octoprint_sandtable plugin, which
   already owns its own schedule jobs on the same device -- any de-duplication
   logic in this script was never taught about those and could misbehave
   around them.

Original docstring follows, describing what it did when it was the only
scheduler:

Programs wake-up schedules on a Shelly 1PM Mini Gen4 so the relay turns ON
a configurable amount of time (default 60 min) before every upcoming F1 race.

How it works
------------
1. Pulls the season calendar from the jolpica-f1 API (the maintained Ergast
   successor). Each race carries a UTC date+time.
2. Reads the Shelly's configured timezone (Sys.GetConfig -> location.tz),
   because on-device schedules fire in *local* device time.
3. For each upcoming race: wakeup = race_start_UTC - lead, converted to the
   device's local tz, encoded as a Shelly 6-field cron timespec.
4. Creates Schedule jobs (Switch.Set on=true) on the device, de-duplicating
   against jobs that already exist so re-runs don't pile up.

Important constraints
---------------------
* Shelly Gen2+/Gen4 allows a MAX OF 20 schedule jobs per device. A full season
  is ~24 races, so the script only loads UPCOMING races and stops at the budget.
  Re-run it every few weeks (or after some races pass) to load the next batch.
* The Shelly cron format has no "year" field, so a job pinned to e.g. "March 15"
  will also fire on March 15 next year until you refresh schedules. Harmless for
  a brief relay-on, but worth knowing.

Usage
-----
    python3 f1_shelly_scheduler.py --host 192.168.1.50
    python3 f1_shelly_scheduler.py --host shelly1pm.local --password mypass --dry-run
    python3 f1_shelly_scheduler.py --host 192.168.1.50 --lead 90 --auto-off-hours 4

Dependencies: requests  (pip install requests). zoneinfo is stdlib on Py>=3.9.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from zoneinfo import ZoneInfo

import requests
from requests.auth import HTTPDigestAuth

JOLPICA_URL = "https://api.jolpi.ca/ergast/f1/{season}.json"
SHELLY_MAX_JOBS = 20  # hard device limit for schedule instances
HTTP_TIMEOUT = 15


# --------------------------------------------------------------------------- #
# F1 calendar
# --------------------------------------------------------------------------- #
def fetch_f1_calendar(season: int) -> list[dict]:
    """Return a list of {name, round, start_utc} for every race in the season.

    Races whose start time has not been published yet are skipped.
    """
    url = JOLPICA_URL.format(season=season)
    resp = requests.get(url, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    races = resp.json()["MRData"]["RaceTable"]["Races"]

    out: list[dict] = []
    for r in races:
        # jolpica gives date "YYYY-MM-DD" and time "HH:MM:SSZ" (UTC, may be absent)
        date_str = r.get("date")
        time_str = r.get("time")
        if not date_str or not time_str:
            continue
        start_utc = dt.datetime.fromisoformat(
            f"{date_str}T{time_str}".replace("Z", "+00:00")
        )
        out.append(
            {
                "name": r.get("raceName", "Grand Prix"),
                "round": int(r.get("round", 0)),
                "start_utc": start_utc,
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Shelly RPC
# --------------------------------------------------------------------------- #
class Shelly:
    def __init__(self, host: str, password: str | None = None):
        self.base = f"http://{host}/rpc"
        # Shelly Gen2+ uses HTTP digest auth (SHA-256) only when a password is set,
        # always with username "admin".
        self.auth = HTTPDigestAuth("admin", password) if password else None
        self._id = 0

    def rpc(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        payload = {"id": self._id, "method": method}
        if params is not None:
            payload["params"] = params
        resp = requests.post(
            self.base, json=payload, auth=self.auth, timeout=HTTP_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"{method} failed: {data['error']}")
        return data.get("result", {})

    def get_timezone(self) -> str | None:
        cfg = self.rpc("Sys.GetConfig")
        return (cfg.get("location") or {}).get("tz")

    def list_schedules(self) -> list[dict]:
        return self.rpc("Schedule.List").get("jobs", [])

    def create_schedule(self, timespec: str, switch_id: int, on: bool) -> dict:
        return self.rpc(
            "Schedule.Create",
            {
                "enable": True,
                "timespec": timespec,
                "calls": [
                    {"method": "Switch.Set", "params": {"id": switch_id, "on": on}}
                ],
            },
        )

    def set_auto_off(self, switch_id: int, delay_seconds: float) -> dict:
        """Make the relay turn itself off N seconds after any ON, without
        spending a second schedule job per race."""
        return self.rpc(
            "Switch.SetConfig",
            {
                "id": switch_id,
                "config": {"auto_off": True, "auto_off_delay": delay_seconds},
            },
        )


# --------------------------------------------------------------------------- #
# Scheduling logic
# --------------------------------------------------------------------------- #
def to_timespec(local_dt: dt.datetime) -> str:
    """Shelly 6-field cron: sec min hour day-of-month month day-of-week.
    day-of-week is '*' so the job fires on that exact calendar date."""
    return (
        f"{local_dt.second} {local_dt.minute} {local_dt.hour} "
        f"{local_dt.day} {local_dt.month} *"
    )


def build_wakeups(
    races: list[dict], lead_minutes: int, tz: ZoneInfo, now_utc: dt.datetime
) -> list[dict]:
    """Filter to upcoming races and compute each local wake-up + timespec."""
    lead = dt.timedelta(minutes=lead_minutes)
    wakeups = []
    for race in races:
        wake_utc = race["start_utc"] - lead
        if wake_utc <= now_utc:
            continue  # race already started / passed
        wake_local = wake_utc.astimezone(tz)
        wakeups.append(
            {
                "name": race["name"],
                "round": race["round"],
                "start_utc": race["start_utc"],
                "wake_local": wake_local,
                "timespec": to_timespec(wake_local),
            }
        )
    wakeups.sort(key=lambda w: w["wake_local"])
    return wakeups


def existing_on_timespecs(jobs: list[dict], switch_id: int) -> set[str]:
    """Timespecs already programmed as 'turn this switch ON', to avoid dupes."""
    found = set()
    for job in jobs:
        for call in job.get("calls", []):
            p = call.get("params", {})
            if (
                call.get("method") == "Switch.Set"
                and p.get("id") == switch_id
                and p.get("on") is True
            ):
                found.add(job["timespec"])
    return found


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Schedule a Shelly relay before each F1 race.")
    ap.add_argument("--host", required=True, help="Shelly IP or hostname (e.g. 192.168.1.50)")
    ap.add_argument("--password", default=None, help="Device password, if protection is enabled")
    ap.add_argument("--switch-id", type=int, default=0, help="Relay/switch id (default 0)")
    ap.add_argument("--season", type=int, default=dt.datetime.now().year, help="F1 season year")
    ap.add_argument("--lead", type=int, default=60, help="Minutes before race start to switch on")
    ap.add_argument("--tz", default=None,
                    help="Override timezone (e.g. Europe/Rome). Default: read from device.")
    ap.add_argument("--auto-off-hours", type=float, default=None,
                    help="If set, configure the relay to auto-off this many hours after each ON.")
    ap.add_argument("--clear-all", action="store_true",
                    help="Delete ALL existing schedules on the device first (destructive).")
    ap.add_argument("--dry-run", action="store_true", help="Print the plan, change nothing.")
    args = ap.parse_args()

    now_utc = dt.datetime.now(dt.timezone.utc)

    # 1. F1 calendar
    try:
        races = fetch_f1_calendar(args.season)
    except Exception as e:
        print(f"ERROR fetching F1 calendar: {e}", file=sys.stderr)
        return 1
    if not races:
        print(f"No races with published start times found for {args.season}.")
        return 0

    shelly = Shelly(args.host, args.password)

    # 2. Timezone
    if args.tz:
        tz_name = args.tz
    else:
        try:
            tz_name = shelly.get_timezone()
        except Exception as e:
            print(f"ERROR talking to Shelly at {args.host}: {e}", file=sys.stderr)
            return 1
        if not tz_name:
            print("Device has no timezone set; pass one with --tz (e.g. --tz Europe/Rome).",
                  file=sys.stderr)
            return 1
    tz = ZoneInfo(tz_name)
    print(f"Device timezone: {tz_name}")

    # 3. Compute upcoming wake-ups
    wakeups = build_wakeups(races, args.lead, tz, now_utc)
    if not wakeups:
        print("No upcoming races left this season. Nothing to schedule.")
        return 0

    print(f"\n{len(wakeups)} upcoming race(s); relay ON {args.lead} min before start:\n")
    for w in wakeups:
        print(f"  R{w['round']:>2} {w['name']:<28} "
              f"start {w['start_utc'].strftime('%Y-%m-%d %H:%M')}Z  ->  "
              f"ON {w['wake_local'].strftime('%a %Y-%m-%d %H:%M %Z')}  "
              f"[{w['timespec']}]")

    # 4. Apply
    if args.dry_run:
        print("\n(dry-run) No changes written to the device.")
        return 0

    if args.clear_all:
        shelly.rpc("Schedule.DeleteAll")
        print("\nDeleted all pre-existing schedules.")
        existing = set()
        current_count = 0
    else:
        jobs = shelly.list_schedules()
        existing = existing_on_timespecs(jobs, args.switch_id)
        current_count = len(jobs)

    if args.auto_off_hours:
        shelly.set_auto_off(args.switch_id, args.auto_off_hours * 3600)
        print(f"Configured relay auto-off {args.auto_off_hours} h after each ON.")

    budget = SHELLY_MAX_JOBS - current_count
    created, skipped = 0, 0
    for w in wakeups:
        if w["timespec"] in existing:
            skipped += 1
            continue
        if created >= budget:
            print(f"\nReached the {SHELLY_MAX_JOBS}-job device limit "
                  f"({budget} slot(s) were free). Remaining races not loaded — "
                  f"re-run after some races pass to add the rest.")
            break
        shelly.create_schedule(w["timespec"], args.switch_id, on=True)
        created += 1
        print(f"  + scheduled {w['name']} ({w['wake_local'].strftime('%Y-%m-%d %H:%M %Z')})")

    print(f"\nDone. Created {created}, skipped {skipped} already-present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
