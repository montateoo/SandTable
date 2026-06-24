# coding=utf-8
"""Circuit-outline generation for OctoPrint-F1Sisyphus.

Builds a one-time, cacheable G-code outline of a track from OpenF1 data: pick
one clean representative lap for a circuit's most recent past race, fetch
that lap's car-location points, and convert them to G1 moves through the same
table-mapping transform used for live tracking.

pick_reference_lap / filter_points_to_lap / points_to_gcode / circuit_cache_path
are pure (data in, data out) and unit-tested directly. build_circuit_gcode is
the I/O-coupled orchestration shell -- it takes a live OpenF1Client and is
exercised only via the replay verification plan, the same boundary
octoprint_sandtable draws around _power_off_sequence.
"""

import datetime

try:
    from .openf1 import OpenF1Error
except ImportError:
    # Tests import these pure modules standalone (sys.path trick, no parent
    # package), the same boundary octoprint_sandtable draws around cycle.py/plug.py.
    from openf1 import OpenF1Error


class CircuitError(Exception):
    """Raised when a circuit outline cannot be built (missing race/lap/location
    data); the caller decides whether to abort or soft-skip."""


def pick_reference_lap(laps):
    """laps: list of dicts with date_start/lap_duration/is_pit_out_lap.

    Filters to clean laps (is_pit_out_lap is False and lap_duration is
    truthy) and returns the one with the MINIMUM lap_duration -- the fastest
    clean lap, a single deterministic pick. Raises ValueError if none qualify.
    """
    clean = [lap for lap in laps if not lap.get("is_pit_out_lap") and lap.get("lap_duration")]
    if not clean:
        raise ValueError("No clean lap (non pit-out, with a recorded duration) found")
    return min(clean, key=lambda lap: lap["lap_duration"])


def filter_points_to_lap(points, lap_date_start, lap_duration_seconds):
    """points: list of dicts with ISO8601 'date' strings. Keeps points whose
    date falls within [lap_date_start, lap_date_start + lap_duration_seconds],
    sorted by date. Pure datetime parsing, no I/O."""
    start = _parse_iso(lap_date_start)
    end = start + datetime.timedelta(seconds=lap_duration_seconds)
    in_window = [p for p in points if p.get("date") and start <= _parse_iso(p["date"]) <= end]
    in_window.sort(key=lambda p: p["date"])
    return in_window


def compute_bounds(points):
    """points: list of dicts with 'x'/'y'. Returns (min_x, max_x, min_y, max_y)
    in OpenF1 track units, or None if no point carries both x and y. Pure --
    this is how a transform's bounds get calibrated, whether for a circuit
    outline (bounds from the reference lap's own points) or for live tracking
    (bounds from a calibration sample, see __init__.py's _calibrate_bounds)."""
    xs = [p["x"] for p in points if "x" in p]
    ys = [p["y"] for p in points if "y" in p]
    if not xs or not ys:
        return None
    return (min(xs), max(xs), min(ys), max(ys))


def make_transform(bounds, table_min_x, table_max_x, table_min_y, table_max_y, margin, flip_x, flip_y):
    """Builds a (x, y) -> (tx, ty) | None closure: uniform scale-to-fit (track
    aspect ratio preserved) + center + margin + optional flip. Pure -- ported
    out of __init__.py's _transform so the same math can calibrate a fresh
    bounds per circuit outline instead of reusing live-tracking's self._bounds
    (which isn't set yet while the outline is being drawn)."""
    if not bounds:
        return lambda x, y: None

    min_x, max_x, min_y, max_y = bounds
    span_x = max_x - min_x
    span_y = max_y - min_y
    if span_x <= 0 or span_y <= 0:
        return lambda x, y: None

    avail_w = (table_max_x - table_min_x) - 2 * margin
    avail_h = (table_max_y - table_min_y) - 2 * margin
    if avail_w <= 0 or avail_h <= 0:
        return lambda x, y: None

    # Uniform scale so the track's aspect ratio (its real shape) is preserved.
    scale = min(avail_w / span_x, avail_h / span_y)
    offset_x = (avail_w - span_x * scale) / 2
    offset_y = (avail_h - span_y * scale) / 2

    def _transform(x, y):
        nx = (x - min_x) * scale
        ny = (y - min_y) * scale
        if flip_x:
            nx = span_x * scale - nx
        if flip_y:
            ny = span_y * scale - ny
        tx = table_min_x + margin + offset_x + nx
        ty = table_min_y + margin + offset_y + ny
        return (tx, ty)

    return _transform


def points_to_gcode(points, transform_fn, feedrate, closed_loop=True):
    """Maps each point's (x, y) through transform_fn (same uniform
    scale/center/margin/flip semantics as __init__.py's _transform) into
    'G1 X.. Y.. F<feedrate>' lines. Closes the loop by repeating the first
    transformed point at the end, if requested. Returns the full gcode text."""
    lines = []
    first = None
    for p in points:
        if "x" not in p or "y" not in p:
            continue
        txy = transform_fn(p["x"], p["y"])
        if txy is None:
            continue
        tx, ty = txy
        if first is None:
            first = (tx, ty)
        lines.append("G1 X{:.2f} Y{:.2f} F{}".format(tx, ty, feedrate))

    if closed_loop and first is not None:
        lines.append("G1 X{:.2f} Y{:.2f} F{}".format(first[0], first[1], feedrate))

    return "\n".join(lines) + ("\n" if lines else "")


def circuit_cache_path(circuits_folder, circuit_key):
    """Pure path-naming helper: '{circuits_folder}/{circuit_key}.gcode'."""
    return "{}/{}.gcode".format(circuits_folder, circuit_key)


def build_circuit_gcode(openf1_client, circuit_key, driver_number, now_utc, table_bounds, margin, flip_x, flip_y, feedrate):
    """Orchestrates: get_latest_past_race_at_circuit -> get_laps ->
    pick_reference_lap -> get_location -> filter_points_to_lap ->
    compute_bounds -> make_transform -> points_to_gcode. Raises CircuitError
    with a clear message at any missing-data step.

    table_bounds = (table_min_x, table_max_x, table_min_y, table_max_y).
    Bounds for the transform are calibrated from the reference lap's own
    points (not the live-tracking self._bounds, which isn't calibrated yet
    while the outline is being drawn -- see __init__.py's _get_or_build_circuit_path)."""
    try:
        past_race = openf1_client.get_latest_past_race_at_circuit(circuit_key, now_utc)
        if past_race is None:
            raise CircuitError("No past race found at circuit_key={!r} yet".format(circuit_key))

        session_key = past_race["session_key"]
        laps = openf1_client.get_laps(session_key, driver_number) or []
        try:
            lap = pick_reference_lap(laps)
        except ValueError as exc:
            raise CircuitError(str(exc))

        points = openf1_client.get_location(session_key, driver_number) or []
        in_lap = filter_points_to_lap(points, lap["date_start"], lap["lap_duration"])
        if not in_lap:
            raise CircuitError(
                "No location points found within the reference lap window for session_key={!r}".format(session_key)
            )

        bounds = compute_bounds(in_lap)
        if bounds is None:
            raise CircuitError("Reference lap points have no x/y data for session_key={!r}".format(session_key))

        table_min_x, table_max_x, table_min_y, table_max_y = table_bounds
        transform_fn = make_transform(bounds, table_min_x, table_max_x, table_min_y, table_max_y, margin, flip_x, flip_y)
        return points_to_gcode(in_lap, transform_fn, feedrate)
    except OpenF1Error as exc:
        raise CircuitError(str(exc))


def _parse_iso(date_str):
    return datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
