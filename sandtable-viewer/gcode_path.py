"""Parse sand-table G-code into a polyline.

Same modal-move handling as tools/pattern_gallery.py (absolute G0/G1 moves,
ignore Z/F/comments) but without the matplotlib dependency this service
doesn't otherwise need.
"""
from __future__ import annotations


def parse_gcode(text: str) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    x = y = 0.0
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        nx = ny = None
        is_move = False
        for tok in line.replace("\t", " ").split():
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
        if not is_move or (nx is None and ny is None):
            continue
        if nx is not None:
            x = nx
        if ny is not None:
            y = ny
        pts.append((x, y))
    return pts
