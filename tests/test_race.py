import datetime

import pytest

import race


def test_start_is_draw_circuit():
    assert race.START == (race.ACTION_DRAW_CIRCUIT, race.PHASE_DRAW_CIRCUIT)


def test_advance_on_draw_done_happy_path():
    assert race.advance_on_draw_done(race.PHASE_DRAW_CIRCUIT) == (
        race.ACTION_WAIT_FOR_LIVE,
        race.PHASE_WAIT_FOR_LIVE,
    )


def test_advance_on_draw_done_wrong_phase_raises():
    with pytest.raises(ValueError):
        race.advance_on_draw_done(race.PHASE_TRACKING)


def test_advance_on_live_detected_happy_path():
    assert race.advance_on_live_detected(race.PHASE_WAIT_FOR_LIVE) == (
        race.ACTION_START_TRACKING,
        race.PHASE_TRACKING,
    )


def test_advance_on_live_detected_wrong_phase_raises():
    with pytest.raises(ValueError):
        race.advance_on_live_detected(race.PHASE_IDLE)


def test_advance_on_race_ended_happy_path():
    assert race.advance_on_race_ended(race.PHASE_TRACKING) == (
        race.ACTION_POWER_OFF,
        race.PHASE_COMPLETE,
    )


def test_advance_on_race_ended_wrong_phase_raises():
    with pytest.raises(ValueError):
        race.advance_on_race_ended(race.PHASE_WAIT_FOR_LIVE)


def test_full_sequence_idle_through_complete():
    action, phase = race.START
    sequence = [(action, phase)]

    action, phase = race.advance_on_draw_done(phase)
    sequence.append((action, phase))

    action, phase = race.advance_on_live_detected(phase)
    sequence.append((action, phase))

    action, phase = race.advance_on_race_ended(phase)
    sequence.append((action, phase))

    assert sequence == [
        (race.ACTION_DRAW_CIRCUIT, race.PHASE_DRAW_CIRCUIT),
        (race.ACTION_WAIT_FOR_LIVE, race.PHASE_WAIT_FOR_LIVE),
        (race.ACTION_START_TRACKING, race.PHASE_TRACKING),
        (race.ACTION_POWER_OFF, race.PHASE_COMPLETE),
    ]


def test_compute_wake_time_subtracts_lead_minutes():
    race_start = datetime.datetime(2026, 6, 28, 13, 0, tzinfo=datetime.timezone.utc)
    wake = race.compute_wake_time(race_start, 60)
    assert wake == datetime.datetime(2026, 6, 28, 12, 0, tzinfo=datetime.timezone.utc)


def test_compute_wake_time_zero_lead_returns_start():
    race_start = datetime.datetime(2026, 6, 28, 13, 0, tzinfo=datetime.timezone.utc)
    assert race.compute_wake_time(race_start, 0) == race_start
