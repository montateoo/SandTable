#!/usr/bin/env python3
"""F1 race-day bridge coordinator — self-scheduling edition.

First run (manual):
    python f1_race_autostart.py

Subsequent races are scheduled automatically via Windows Task Scheduler.
After each race the script reschedules itself for the next one — no further
manual intervention needed.

What it does each race:
  1. Sleeps until `lead_minutes` before the race start.
  2. Starts the f1sisyphus_location_bridge on this PC.
  3. Points the Pi's f1sisyphus plugin at the local bridge (api_base + session_key).
  4. After the race safety cap, resets Pi settings back to the public OpenF1 API.
  5. Queries OpenF1 for the next race and registers a Task Scheduler task to
     run itself again automatically.

Flags
-----
    --lead 60     minutes before race start to wake (default: 60)
    --cap  210    safety cap in minutes before forced reset (default: 210)
    --port 8081   bridge HTTP port (default: 8081)
    --now         skip the sleep — race is already starting
    --schedule-only   only (re)schedule the Task Scheduler task, don't run
"""
from __future__ import annotations

import argparse
import datetime
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OCTOPRINT_URL = "http://192.168.1.53"
OCTOPRINT_API_KEY = "B8518F1E2A5247CC89D96F5899DBDA4B"

BRIDGE_SCRIPT = Path(r"A:\Projects\DriverTV\bridge\f1sisyphus_location_bridge.py")
BRIDGE_VENV_PYTHON = Path(r"A:\Projects\DriverTV\.venv\Scripts\python.exe")
BRIDGE_PORT = 8081

OPENF1_API = "https://api.openf1.org/v1"
TASK_NAME = "F1-Race-Autostart"
# ---------------------------------------------------------------------------


def get_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.1.1", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def get_next_race(after_utc: datetime.datetime) -> dict | None:
    resp = requests.get(
        f"{OPENF1_API}/sessions",
        params={"session_name": "Race"},
        timeout=15,
    )
    resp.raise_for_status()
    sessions = resp.json() or []
    candidates = []
    for s in sessions:
        ds = s.get("date_start")
        if not ds:
            continue
        dt = datetime.datetime.fromisoformat(ds.replace("Z", "+00:00"))
        if dt > after_utc:
            candidates.append((dt, s))
    if not candidates:
        return None
    _, session = min(candidates, key=lambda x: x[0])
    return session


def pi_set_settings(**kwargs):
    resp = requests.post(
        f"{OCTOPRINT_URL}/api/settings",
        json={"plugins": {"f1sisyphus": kwargs}},
        headers={"X-Api-Key": OCTOPRINT_API_KEY},
        timeout=10,
    )
    resp.raise_for_status()


def schedule_next_race(lead_minutes: int, cap_minutes: int, port: int):
    """Register a Task Scheduler task to run this script for the next race."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    print("\nQuerying OpenF1 for the next race to schedule...")
    race = get_next_race(now_utc)
    if race is None:
        print("No further races found on OpenF1 — nothing scheduled.")
        return

    race_start_utc = datetime.datetime.fromisoformat(
        race["date_start"].replace("Z", "+00:00")
    )
    wake_utc = race_start_utc - datetime.timedelta(minutes=lead_minutes)
    wake_local = wake_utc.astimezone()
    race_name = f"F1-{race.get('country_name', 'Unknown')}"

    # schtasks expects local time: MM/DD/YYYY and HH:MM
    sd = wake_local.strftime("%m/%d/%Y")
    st = wake_local.strftime("%H:%M")

    this_script = Path(sys.argv[0]).resolve()
    python = Path(sys.executable).resolve()
    task_cmd = (
        f'"{python}" "{this_script}" '
        f"--lead {lead_minutes} --cap {cap_minutes} --port {port}"
    )

    result = subprocess.run(
        [
            "schtasks", "/Create",
            "/TN", TASK_NAME,
            "/TR", task_cmd,
            "/SC", "ONCE",
            "/SD", sd,
            "/ST", st,
            "/F",          # overwrite if already exists
        ],
        capture_output=True, text=True,
    )

    if result.returncode == 0:
        print(f"Scheduled '{TASK_NAME}' for {race_name} "
              f"on {wake_local.strftime('%Y-%m-%d %H:%M %Z')}.")
    else:
        print(f"WARNING: schtasks failed: {result.stderr.strip()}")
        print(f"Schedule manually: run this script at {wake_local.strftime('%H:%M %Z')} "
              f"on {wake_local.strftime('%Y-%m-%d')} with --now")


def parse_args():
    ap = argparse.ArgumentParser(description="F1 race-day bridge autostart coordinator.")
    ap.add_argument("--lead", type=int, default=60, metavar="MIN",
                    help="minutes before race start to launch the bridge (default: 60)")
    ap.add_argument("--cap", type=int, default=210, metavar="MIN",
                    help="safety cap in minutes — reset Pi after this long (default: 210)")
    ap.add_argument("--port", type=int, default=BRIDGE_PORT,
                    help=f"bridge port (default: {BRIDGE_PORT})")
    ap.add_argument("--now", action="store_true",
                    help="skip the sleep — race is already starting")
    ap.add_argument("--schedule-only", action="store_true",
                    help="only register the Task Scheduler task, do not run the bridge")
    return ap.parse_args()


def main():
    args = parse_args()

    if args.schedule_only:
        schedule_next_race(args.lead, args.cap, args.port)
        return

    now_utc = datetime.datetime.now(datetime.timezone.utc)

    print("Querying OpenF1 for the current/next race...")
    race = get_next_race(now_utc)
    if race is None:
        if not args.now:
            sys.exit("No upcoming race found on OpenF1. Use --now to launch immediately.")
        session_key = int(input("Enter session_key manually: ").strip())
        race_start_utc = now_utc
        race_name = "Unknown"
    else:
        session_key = race["session_key"]
        race_start_utc = datetime.datetime.fromisoformat(
            race["date_start"].replace("Z", "+00:00")
        )
        race_name = f"F1-{race.get('country_name', 'Unknown')} (session {session_key})"

    lan_ip = get_lan_ip()
    bridge_base = f"http://{lan_ip}:{args.port}/v1"

    print(f"Race      : {race_name}")
    print(f"Race start: {race_start_utc.astimezone().strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"Bridge    : {bridge_base}")
    print(f"Session   : {session_key}")

    if not args.now:
        wake_utc = race_start_utc - datetime.timedelta(minutes=args.lead)
        wait_seconds = (wake_utc - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        if wait_seconds > 0:
            wake_local = wake_utc.astimezone()
            print(f"\nSleeping until {wake_local.strftime('%H:%M:%S %Z')} "
                  f"({wait_seconds / 60:.0f} min from now)...")
            time.sleep(wait_seconds)
        else:
            print("Wake time already passed — launching immediately.")

    # 1. Start the bridge
    print("\nStarting bridge...")
    bridge_proc = subprocess.Popen(
        [str(BRIDGE_VENV_PYTHON), str(BRIDGE_SCRIPT),
         "--host", "0.0.0.0", "--port", str(args.port)],
        cwd=str(BRIDGE_SCRIPT.parent),
    )
    time.sleep(3)

    if bridge_proc.poll() is not None:
        sys.exit("Bridge process exited immediately — check the bridge script.")

    print(f"Bridge running (pid {bridge_proc.pid})")

    # 2. Point Pi at the local bridge
    print("Updating Pi settings...")
    try:
        pi_set_settings(api_base=bridge_base, session_key=str(session_key))
        print("Pi settings updated.")
    except Exception as exc:
        print(f"WARNING: could not update Pi settings: {exc}")
        print(f"Update manually: api_base={bridge_base}  session_key={session_key}")

    # 3. Wait for the race to end
    cap_seconds = args.cap * 60
    print(f"\nRace running — will reset Pi in {args.cap} min (safety cap).")
    print("Press Ctrl+C to reset early.\n")
    try:
        time.sleep(cap_seconds)
    except KeyboardInterrupt:
        print("\nInterrupted — resetting now.")

    # 4. Reset Pi settings
    print("Resetting Pi settings to public OpenF1 API...")
    try:
        pi_set_settings(api_base=OPENF1_API, session_key="latest")
        print("Pi settings reset.")
    except Exception as exc:
        print(f"WARNING: could not reset Pi settings: {exc}")
        print(f"Reset manually: api_base={OPENF1_API}  session_key=latest")

    # 5. Stop the bridge
    print("Stopping bridge...")
    bridge_proc.terminate()
    bridge_proc.wait(timeout=5)
    print("Bridge stopped.")

    # 6. Schedule next race
    schedule_next_race(args.lead, args.cap, args.port)


if __name__ == "__main__":
    main()
