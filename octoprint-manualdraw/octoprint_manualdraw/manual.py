# coding=utf-8
"""Pure logic for OctoPrint-ManualDraw: no OctoPrint imports, unit-tested on its own.

Mirrors the role cycle.py plays for octoprint_sandtable and race.py plays for
octoprint_f1sisyphus -- the OctoPrint glue in __init__.py drives these helpers
and performs the actual pausing/jogging/resuming.
"""

from __future__ import annotations

import hmac
import math
import secrets

MAX_DT_SECONDS = 0.5  # caps the effect of a stalled/late jog packet


def new_token() -> str:
    return secrets.token_urlsafe(24)


def token_matches(expected, provided) -> bool:
    if not expected or not provided:
        return False
    return hmac.compare_digest(str(expected), str(provided))


def update_position(position, line):
    """Feed one sent G-code line through a modal (last-X/Y-carries) tracker.

    Same absolute G0/G1 handling as sandtable-viewer/gcode_path.py's
    parse_gcode, just applied one line at a time instead of over a whole
    file, so a live position cache can be kept fresh from the
    octoprint.comm.protocol.gcode.sent hook.
    """
    x, y = position
    raw = line.split(";", 1)[0].strip()
    if not raw:
        return (x, y)

    nx = ny = None
    is_move = False
    for tok in raw.replace("\t", " ").split():
        if not tok:
            continue
        c = tok[0].upper()
        v = tok[1:]
        if c == "G":
            try:
                is_move = int(float(v)) in (0, 1)
            except ValueError:
                pass
        elif c == "X":
            try:
                nx = float(v)
            except ValueError:
                pass
        elif c == "Y":
            try:
                ny = float(v)
            except ValueError:
                pass

    if not is_move:
        return (x, y)
    if nx is not None:
        x = nx
    if ny is not None:
        y = ny
    return (x, y)


def clamp_dt(dt, max_dt=MAX_DT_SECONDS):
    if dt < 0:
        return 0.0
    return min(dt, max_dt)


def _axis_speed(delta_deg, dead_zone_deg, max_tilt_deg, max_speed_mm_s):
    magnitude = abs(delta_deg)
    if magnitude <= dead_zone_deg:
        return 0.0
    magnitude = min(magnitude, max_tilt_deg)
    usable_range = max(max_tilt_deg - dead_zone_deg, 1e-9)
    scale = (magnitude - dead_zone_deg) / usable_range
    speed = scale * max_speed_mm_s
    return speed if delta_deg > 0 else -speed


def tilt_to_velocity(dbeta, dgamma, dead_zone_deg, max_tilt_deg, max_speed_mm_s):
    """Joystick-style mapping from calibrated tilt deltas (degrees) to a table
    velocity (mm/s). gamma (left/right tilt) drives X, beta (front/back tilt)
    drives Y -- a phone held flat and tilted like a tray."""
    vx = _axis_speed(dgamma, dead_zone_deg, max_tilt_deg, max_speed_mm_s)
    vy = _axis_speed(dbeta, dead_zone_deg, max_tilt_deg, max_speed_mm_s)
    return vx, vy


def integrate_and_clamp(x, y, vx, vy, dt, bounds):
    min_x, max_x, min_y, max_y = bounds
    nx = x + vx * dt
    ny = y + vy * dt
    nx = min(max(nx, min_x), max_x)
    ny = min(max(ny, min_y), max_y)
    return nx, ny


def distance(x1, y1, x2, y2):
    return math.hypot(x2 - x1, y2 - y1)
