#!/usr/bin/env python3
"""Convert Sisyphus theta-rho (.thr) files to G-code for the SandTable.

Usage
-----
    # single file -> prints to stdout
    python thr_to_gcode.py pattern.thr

    # single file -> save next to the source
    python thr_to_gcode.py pattern.thr -o pattern.gcode

    # whole folder -> converts every .thr in-place (writes .gcode siblings)
    python thr_to_gcode.py path/to/folder/

Options
-------
    --bed 370x400   bed size in mm (default: 370x400, the real sandtable)
    --feedrate 3000 G1 feedrate in mm/min (default: 3000)
    -o OUTPUT       output file (single-file mode only)
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path


def parse_thr(path: Path, bed_x: float, bed_y: float):
    r_max = min(bed_x, bed_y) / 2.0
    cx, cy = bed_x / 2.0, bed_y / 2.0
    pts = []
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            theta = float(parts[0])
            rho = float(parts[1])
        except ValueError:
            continue
        r = rho * r_max
        pts.append((cx + r * math.cos(theta), cy + r * math.sin(theta)))
    return pts


def to_gcode(pts, feedrate: int) -> str:
    lines = ["G90", "G1 F{}".format(feedrate)]
    for x, y in pts:
        lines.append("G1 X{:.3f} Y{:.3f}".format(x, y))
    return "\n".join(lines) + "\n"


def convert_file(src: Path, dst: Path, bed_x: float, bed_y: float, feedrate: int):
    pts = parse_thr(src, bed_x, bed_y)
    if not pts:
        print("WARNING: no points parsed from {}".format(src), file=sys.stderr)
        return
    dst.write_text(to_gcode(pts, feedrate))
    print("{} -> {} ({} points)".format(src, dst, len(pts)))


def parse_bed(s: str):
    try:
        a, b = s.lower().replace(" ", "").split("x")
        return float(a), float(b)
    except Exception:
        raise argparse.ArgumentTypeError("bed must look like 370x400")


def main():
    ap = argparse.ArgumentParser(description="Convert .thr theta-rho files to G-code.")
    ap.add_argument("input", help=".thr file or folder of .thr files")
    ap.add_argument("-o", "--output", help="output .gcode file (single-file mode only)")
    ap.add_argument("--bed", type=parse_bed, default=(370.0, 400.0), metavar="WxH",
                    help="bed size in mm (default: 370x400)")
    ap.add_argument("--feedrate", type=int, default=3000,
                    help="G1 feedrate in mm/min (default: 3000)")
    args = ap.parse_args()

    bed_x, bed_y = args.bed
    src = Path(args.input)

    if src.is_dir():
        files = sorted(src.glob("*.thr"))
        if not files:
            sys.exit("No .thr files found in {}".format(src))
        for f in files:
            convert_file(f, f.with_suffix(".gcode"), bed_x, bed_y, args.feedrate)
    elif src.is_file():
        if args.output:
            dst = Path(args.output)
        else:
            dst = src.with_suffix(".gcode")
        gcode = to_gcode(parse_thr(src, bed_x, bed_y), args.feedrate)
        if args.output == "-" or (not args.output and sys.stdout.isatty() is False):
            print(gcode, end="")
        else:
            dst.write_text(gcode)
            print("{} -> {} ({} points)".format(
                src, dst, gcode.count("\nG1 X")))
    else:
        sys.exit("Not a file or folder: {}".format(src))


if __name__ == "__main__":
    main()
