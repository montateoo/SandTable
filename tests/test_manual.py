import pytest

import manual


def test_new_token_is_url_safe_and_reasonably_unique():
    a, b = manual.new_token(), manual.new_token()
    assert a != b
    assert len(a) > 20


def test_token_matches_correct_and_incorrect():
    token = manual.new_token()
    assert manual.token_matches(token, token) is True
    assert manual.token_matches(token, "wrong") is False


def test_token_matches_rejects_missing_values():
    assert manual.token_matches(None, "x") is False
    assert manual.token_matches("x", None) is False
    assert manual.token_matches("", "") is False


def test_update_position_tracks_absolute_moves():
    pos = (0.0, 0.0)
    pos = manual.update_position(pos, "G1 X10 Y20 F3000")
    assert pos == (10.0, 20.0)
    pos = manual.update_position(pos, "G1 X15")
    assert pos == (15.0, 20.0)  # Y carries forward (modal, axis omitted)
    pos = manual.update_position(pos, "G1 Y5")
    assert pos == (15.0, 5.0)  # X carries forward


def test_update_position_ignores_non_move_lines():
    pos = (1.0, 2.0)
    assert manual.update_position(pos, "; a comment") == pos
    assert manual.update_position(pos, "") == pos
    assert manual.update_position(pos, "M114") == pos
    assert manual.update_position(pos, "G90") == pos


def test_update_position_strips_trailing_comments():
    pos = manual.update_position((0.0, 0.0), "G1 X5 Y5 ; move to start")
    assert pos == (5.0, 5.0)


def test_clamp_dt_caps_large_gaps_and_rejects_negative():
    assert manual.clamp_dt(0.05) == 0.05
    assert manual.clamp_dt(10.0) == manual.MAX_DT_SECONDS
    assert manual.clamp_dt(-1.0) == 0.0


def test_tilt_to_velocity_dead_zone_suppresses_small_tilt():
    vx, vy = manual.tilt_to_velocity(2.0, 2.0, dead_zone_deg=4, max_tilt_deg=35, max_speed_mm_s=40)
    assert vx == 0.0
    assert vy == 0.0


def test_tilt_to_velocity_full_tilt_hits_max_speed():
    vx, vy = manual.tilt_to_velocity(35.0, 35.0, dead_zone_deg=4, max_tilt_deg=35, max_speed_mm_s=40)
    assert vx == pytest.approx(40.0)
    assert vy == pytest.approx(40.0)


def test_tilt_to_velocity_beyond_max_tilt_still_clamps_to_max_speed():
    # dbeta=90 -> vy; dgamma=-90 -> vx (see tilt_to_velocity's axis mapping).
    vx, vy = manual.tilt_to_velocity(90.0, -90.0, dead_zone_deg=4, max_tilt_deg=35, max_speed_mm_s=40)
    assert vx == pytest.approx(-40.0)
    assert vy == pytest.approx(40.0)


def test_tilt_to_velocity_axis_mapping_and_sign():
    # gamma drives X, beta drives Y; sign of the tilt carries through.
    vx, vy = manual.tilt_to_velocity(dbeta=-20.0, dgamma=20.0, dead_zone_deg=4, max_tilt_deg=35, max_speed_mm_s=40)
    assert vx > 0
    assert vy < 0


def test_integrate_and_clamp_moves_and_clamps_to_bounds():
    bounds = (0.0, 100.0, 0.0, 100.0)
    x, y = manual.integrate_and_clamp(50.0, 50.0, vx=10.0, vy=-10.0, dt=1.0, bounds=bounds)
    assert (x, y) == (60.0, 40.0)

    x, y = manual.integrate_and_clamp(95.0, 5.0, vx=100.0, vy=-100.0, dt=1.0, bounds=bounds)
    assert (x, y) == (100.0, 0.0)  # clamped to the table edges, not driven off it


def test_distance_basic():
    assert manual.distance(0, 0, 3, 4) == pytest.approx(5.0)
