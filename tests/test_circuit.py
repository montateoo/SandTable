import pytest

import circuit


# --- pick_reference_lap -----------------------------------------------------
def test_pick_reference_lap_picks_fastest_clean_lap():
    laps = [
        {"date_start": "2026-06-28T13:00:00Z", "lap_duration": 80.5, "is_pit_out_lap": False},
        {"date_start": "2026-06-28T13:02:00Z", "lap_duration": 70.0, "is_pit_out_lap": True},  # pit-out, excluded
        {"date_start": "2026-06-28T13:04:00Z", "lap_duration": 75.2, "is_pit_out_lap": False},  # fastest clean
    ]
    lap = circuit.pick_reference_lap(laps)
    assert lap["lap_duration"] == 75.2


def test_pick_reference_lap_excludes_laps_without_duration():
    laps = [
        {"date_start": "2026-06-28T13:00:00Z", "lap_duration": None, "is_pit_out_lap": False},
        {"date_start": "2026-06-28T13:02:00Z", "lap_duration": 80.0, "is_pit_out_lap": False},
    ]
    lap = circuit.pick_reference_lap(laps)
    assert lap["lap_duration"] == 80.0


def test_pick_reference_lap_raises_when_no_clean_lap():
    laps = [{"date_start": "2026-06-28T13:00:00Z", "lap_duration": 80.0, "is_pit_out_lap": True}]
    with pytest.raises(ValueError):
        circuit.pick_reference_lap(laps)


def test_pick_reference_lap_raises_on_empty_list():
    with pytest.raises(ValueError):
        circuit.pick_reference_lap([])


# --- filter_points_to_lap ----------------------------------------------------
def test_filter_points_to_lap_keeps_only_in_window_points_sorted():
    points = [
        {"date": "2026-06-28T13:01:30Z", "x": 2, "y": 2},  # inside
        {"date": "2026-06-28T12:59:00Z", "x": -1, "y": -1},  # before
        {"date": "2026-06-28T13:00:00Z", "x": 0, "y": 0},  # exactly at start
        {"date": "2026-06-28T13:05:00Z", "x": 9, "y": 9},  # after
    ]
    result = circuit.filter_points_to_lap(points, "2026-06-28T13:00:00Z", 90)
    assert [p["x"] for p in result] == [0, 2]


def test_filter_points_to_lap_returns_empty_for_no_overlap():
    points = [{"date": "2026-06-28T11:00:00Z", "x": 0, "y": 0}]
    result = circuit.filter_points_to_lap(points, "2026-06-28T13:00:00Z", 90)
    assert result == []


# --- points_to_gcode ----------------------------------------------------------
def _identity_transform(x, y):
    return (float(x), float(y))


def test_points_to_gcode_emits_g1_lines_and_closes_loop():
    points = [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 10, "y": 10}]
    gcode = circuit.points_to_gcode(points, _identity_transform, feedrate=3000)
    lines = gcode.strip().split("\n")
    assert lines[0] == "G1 X0.00 Y0.00 F3000"
    assert lines[-1] == "G1 X0.00 Y0.00 F3000"  # closed loop returns to first point
    assert len(lines) == 4


def test_points_to_gcode_open_loop_does_not_close():
    points = [{"x": 0, "y": 0}, {"x": 10, "y": 0}]
    gcode = circuit.points_to_gcode(points, _identity_transform, feedrate=3000, closed_loop=False)
    assert len(gcode.strip().split("\n")) == 2


def test_points_to_gcode_skips_points_transform_rejects():
    def reject_second(x, y):
        return None if x == 10 else (float(x), float(y))

    points = [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 20, "y": 0}]
    gcode = circuit.points_to_gcode(points, reject_second, feedrate=3000, closed_loop=False)
    lines = gcode.strip().split("\n")
    assert len(lines) == 2  # the x=10 point was dropped


def test_points_to_gcode_empty_points_returns_empty_string():
    assert circuit.points_to_gcode([], _identity_transform, feedrate=3000) == ""


# --- circuit_cache_path -------------------------------------------------------
def test_circuit_cache_path_builds_expected_path():
    assert circuit.circuit_cache_path("circuits", 19) == "circuits/19.gcode"


# --- build_circuit_gcode orchestration (fixture-backed, not a live client) ---
class FakeOpenF1:
    def __init__(self, past_race=None, laps=None, points=None):
        self._past_race = past_race
        self._laps = laps or []
        self._points = points or []

    def get_latest_past_race_at_circuit(self, circuit_key, before_utc):
        return self._past_race

    def get_laps(self, session_key, driver_number):
        return self._laps

    def get_location(self, session_key, driver_number):
        return self._points


TABLE_BOUNDS = (0, 5, 0, 5)


def test_build_circuit_gcode_raises_when_no_past_race():
    client = FakeOpenF1(past_race=None)
    with pytest.raises(circuit.CircuitError):
        circuit.build_circuit_gcode(client, 19, 1, None, TABLE_BOUNDS, 0, False, False, 3000)


def test_build_circuit_gcode_raises_when_no_clean_lap():
    client = FakeOpenF1(past_race={"session_key": 1}, laps=[])
    with pytest.raises(circuit.CircuitError):
        circuit.build_circuit_gcode(client, 19, 1, None, TABLE_BOUNDS, 0, False, False, 3000)


def test_build_circuit_gcode_raises_when_no_location_points_in_window():
    client = FakeOpenF1(
        past_race={"session_key": 1},
        laps=[{"date_start": "2026-06-28T13:00:00Z", "lap_duration": 80.0, "is_pit_out_lap": False}],
        points=[],
    )
    with pytest.raises(circuit.CircuitError):
        circuit.build_circuit_gcode(client, 19, 1, None, TABLE_BOUNDS, 0, False, False, 3000)


def test_build_circuit_gcode_happy_path_returns_gcode_text():
    client = FakeOpenF1(
        past_race={"session_key": 1},
        laps=[{"date_start": "2026-06-28T13:00:00Z", "lap_duration": 80.0, "is_pit_out_lap": False}],
        points=[
            {"date": "2026-06-28T13:00:10Z", "x": 0, "y": 0},
            {"date": "2026-06-28T13:00:20Z", "x": 5, "y": 5},
        ],
    )
    gcode = circuit.build_circuit_gcode(client, 19, 1, None, TABLE_BOUNDS, 0, False, False, 3000)
    assert "G1 X0.00 Y0.00 F3000" in gcode


# --- compute_bounds -----------------------------------------------------------
def test_compute_bounds_finds_min_max():
    points = [{"x": 3, "y": -1}, {"x": -2, "y": 5}, {"x": 0, "y": 0}]
    assert circuit.compute_bounds(points) == (-2, 3, -1, 5)


def test_compute_bounds_returns_none_when_no_xy():
    assert circuit.compute_bounds([{"date": "x"}]) is None


# --- make_transform ------------------------------------------------------------
def test_make_transform_maps_corners_into_table_area_with_margin():
    bounds = (0, 10, 0, 10)
    transform_fn = circuit.make_transform(bounds, 0, 100, 0, 100, margin=10, flip_x=False, flip_y=False)
    assert transform_fn(0, 0) == (10, 10)
    assert transform_fn(10, 10) == (90, 90)


def test_make_transform_flip_x_and_flip_y():
    bounds = (0, 10, 0, 10)
    transform_fn = circuit.make_transform(bounds, 0, 100, 0, 100, margin=10, flip_x=True, flip_y=True)
    assert transform_fn(0, 0) == (90, 90)
    assert transform_fn(10, 10) == (10, 10)


def test_make_transform_none_bounds_returns_none_for_any_point():
    transform_fn = circuit.make_transform(None, 0, 100, 0, 100, margin=10, flip_x=False, flip_y=False)
    assert transform_fn(5, 5) is None


def test_make_transform_zero_span_returns_none():
    transform_fn = circuit.make_transform((5, 5, 0, 10), 0, 100, 0, 100, margin=10, flip_x=False, flip_y=False)
    assert transform_fn(5, 5) is None
