import pytest

import cycle


def test_start_is_first_eraser():
    assert cycle.START == (cycle.ACTION_PRINT_ERASER, cycle.PHASE_ERASER, 0)


def test_advance_eraser_to_draw():
    assert cycle.advance(cycle.PHASE_ERASER, 0, 2) == (cycle.ACTION_PRINT_DRAW, cycle.PHASE_DRAW, 0)


def test_advance_draw_starts_next_round():
    assert cycle.advance(cycle.PHASE_DRAW, 0, 2) == (cycle.ACTION_PRINT_ERASER, cycle.PHASE_ERASER, 1)


def test_advance_draw_completes_last_round():
    assert cycle.advance(cycle.PHASE_DRAW, 1, 2) == (cycle.ACTION_COMPLETE, None, 2)


def test_advance_single_round_completes_immediately():
    assert cycle.advance(cycle.PHASE_DRAW, 0, 1) == (cycle.ACTION_COMPLETE, None, 1)


def test_advance_rejects_unknown_phase():
    with pytest.raises(ValueError):
        cycle.advance("bogus", 0, 2)


def test_pick_next_round_robin_wraps():
    pool = ["a", "b", "c"]
    assert cycle.pick_next(pool, 0) == ("a", 1)
    assert cycle.pick_next(pool, 1) == ("b", 2)
    assert cycle.pick_next(pool, 2) == ("c", 0)


def test_pick_next_normalizes_out_of_range_index():
    pool = ["a", "b"]
    # index persisted from a previous, larger pool should still be safe
    assert cycle.pick_next(pool, 5) == ("b", 0)


def test_pick_next_empty_pool_raises():
    with pytest.raises(ValueError):
        cycle.pick_next([], 0)


def test_full_cycle_action_sequence_two_rounds():
    rounds = 2
    action, phase, rnd = cycle.START
    sequence = [action]
    for _ in range(10):  # safety bound
        if action == cycle.ACTION_COMPLETE:
            break
        action, phase, rnd = cycle.advance(phase, rnd, rounds)
        sequence.append(action)
    assert sequence == [
        cycle.ACTION_PRINT_ERASER,
        cycle.ACTION_PRINT_DRAW,
        cycle.ACTION_PRINT_ERASER,
        cycle.ACTION_PRINT_DRAW,
        cycle.ACTION_COMPLETE,
    ]


def test_round_robin_advances_across_a_full_cycle():
    # Two erasers, three draws; verify the pointers each advance once per use.
    erasers = ["e1", "e2"]
    draws = ["d1", "d2", "d3"]
    e_idx, d_idx = 0, 0
    picked_e, picked_d = [], []

    action, phase, rnd = cycle.START
    for _ in range(10):
        if action == cycle.ACTION_COMPLETE:
            break
        if action == cycle.ACTION_PRINT_ERASER:
            name, e_idx = cycle.pick_next(erasers, e_idx)
            picked_e.append(name)
        elif action == cycle.ACTION_PRINT_DRAW:
            name, d_idx = cycle.pick_next(draws, d_idx)
            picked_d.append(name)
        action, phase, rnd = cycle.advance(phase, rnd, 2)

    assert picked_e == ["e1", "e2"]  # 2 rounds -> e1 then e2
    assert picked_d == ["d1", "d2"]  # 2 rounds -> d1 then d2
    assert e_idx == 0 and d_idx == 2  # pointers persist for the next boot
