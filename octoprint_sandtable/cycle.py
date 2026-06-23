# coding=utf-8
"""Pure cycle logic for OctoPrint-SandTable.

Kept free of any OctoPrint imports so it can be unit-tested on its own. The
OctoPrint glue in __init__.py drives these helpers and performs the actual
file selection / printing / power control.

The cycle is: ERASER -> DRAW, repeated `rounds` times, then complete.
"""

PHASE_ERASER = "eraser"
PHASE_DRAW = "draw"

# Actions returned by START / advance(); the plugin maps these to real work.
ACTION_PRINT_ERASER = "print_eraser"
ACTION_PRINT_DRAW = "print_draw"
ACTION_COMPLETE = "complete"

# Starting state of a fresh cycle: print the first eraser, phase=ERASER, round 0.
START = (ACTION_PRINT_ERASER, PHASE_ERASER, 0)


def advance(completed_phase, round_index, rounds):
    """Given the phase that just finished, return the next step.

    Returns a 3-tuple ``(action, next_phase, next_round)``:
      - finishing an ERASER  -> print the DRAW for this round
      - finishing a DRAW     -> increment the round; print the next ERASER, or
                                COMPLETE once we've done `rounds` rounds.
    """
    if completed_phase == PHASE_ERASER:
        return (ACTION_PRINT_DRAW, PHASE_DRAW, round_index)

    if completed_phase == PHASE_DRAW:
        next_round = round_index + 1
        # rounds <= 0 means "unlimited" — keep going until explicitly stopped.
        if rounds <= 0 or next_round < rounds:
            return (ACTION_PRINT_ERASER, PHASE_ERASER, next_round)
        return (ACTION_COMPLETE, None, next_round)

    raise ValueError("Unknown phase: {!r}".format(completed_phase))


def pick_next(pool, index):
    """Round-robin pick from a (deterministically ordered) ``pool``.

    Returns ``(item, next_index)``. ``next_index`` is always normalised into
    range so it stays small and survives the pool changing size between reboots.
    Raises ValueError on an empty pool (caller should abort the cycle, never
    power off, so the problem is visible).
    """
    if not pool:
        raise ValueError("pool is empty")
    n = len(pool)
    i = index % n
    return pool[i], (i + 1) % n
