# coding=utf-8
"""Pure race-day lifecycle state machine for OctoPrint-F1Sisyphus.

Kept free of any OctoPrint/requests imports so it can be unit-tested on its
own. The OctoPrint glue in __init__.py drives these helpers and performs the
actual circuit drawing / OpenF1 polling / Shelly rescheduling / power-off.

The lifecycle is: DRAW_CIRCUIT -> WAIT_FOR_LIVE -> TRACKING -> COMPLETE.

Unlike octoprint_sandtable's cycle.py (one linear advance() driven entirely by
PrintDone events), this lifecycle has three distinct triggers coming from
three different places in __init__.py: a PrintDone event, a "session is now
live" poll result, and a "race has ended / gone quiet" poll result. Three
separate transition functions keep each call site unambiguous instead of
overloading one generic advance(event, phase).
"""

import datetime

PHASE_IDLE = "idle"
PHASE_DRAW_CIRCUIT = "draw_circuit"
PHASE_WAIT_FOR_LIVE = "wait_for_live"
PHASE_TRACKING = "tracking"
PHASE_COMPLETE = "complete"

ACTION_DRAW_CIRCUIT = "draw_circuit"
ACTION_WAIT_FOR_LIVE = "wait_for_live"
ACTION_START_TRACKING = "start_tracking"
ACTION_POWER_OFF = "power_off"

# Starting state of a fresh race cycle: draw the known circuit outline.
START = (ACTION_DRAW_CIRCUIT, PHASE_DRAW_CIRCUIT)


def advance_on_draw_done(phase):
    """The circuit-outline print finished -> start waiting for the session to
    go live. Raises ValueError if called from any phase other than DRAW_CIRCUIT."""
    if phase != PHASE_DRAW_CIRCUIT:
        raise ValueError("advance_on_draw_done called from phase {!r}".format(phase))
    return (ACTION_WAIT_FOR_LIVE, PHASE_WAIT_FOR_LIVE)


def advance_on_live_detected(phase):
    """The WAIT_FOR_LIVE poll found a live session -> start tracking.
    Raises ValueError if called from any phase other than WAIT_FOR_LIVE."""
    if phase != PHASE_WAIT_FOR_LIVE:
        raise ValueError("advance_on_live_detected called from phase {!r}".format(phase))
    return (ACTION_START_TRACKING, PHASE_TRACKING)


def advance_on_race_ended(phase):
    """The TRACKING poll detected the race ended (no-data timeout or safety
    cap) -> power off. Raises ValueError if called from any phase other than
    TRACKING."""
    if phase != PHASE_TRACKING:
        raise ValueError("advance_on_race_ended called from phase {!r}".format(phase))
    return (ACTION_POWER_OFF, PHASE_COMPLETE)


def compute_wake_time(next_race_start_utc, lead_minutes):
    """next_race_start_utc - lead_minutes. Pure UTC-in/UTC-out datetime
    arithmetic; converting to the Shelly device's local tz for the cron
    timespec happens in shelly.py, not here."""
    return next_race_start_utc - datetime.timedelta(minutes=lead_minutes)
