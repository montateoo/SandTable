#!/usr/bin/env python3
"""Scale gcode files to fit the SandTable bed (370x400 mm by default).

Each drawing is scaled uniformly (aspect ratio preserved) so it fills as much
of the bed as possible, then centered at (bed_x/2, bed_y/2).

Usage
-----
    # scale all .gcode files in a folder (in-place):
    python scale_gcode.py path/to/folder/

    # scale a single file (in-place):
    python scale_gcode.py file.gcode

    # single file with explicit output:
    python scale_gcode.py file.gcode -o out.gcode

    # dry-run (print stats, don't write):
    python scale_gcode.py folder/ --dry-run

Options
-------
    --bed 370x400    bed size in mm (default: 370x400)
    --margin 0       margin to leave on each side in mm (default: 0)
    --skip-names     comma-separated stems to skip (e.g. RhoOffsetCalibration)
    --dry-run        print scaling info only, do not write files
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BED_X = 370.0
BED_Y = 400.0
DEFAULT_SKIP = {"rhooffsetcalibration"}

_G1_XY = re.compile(
    r"^(G1\s+)(?=[^;]*X)((?:X([-\d.]+)\s*)?(?:Y([-\d.]+)\s*)?(?:F[\d.]+\s*)?)(.*)$",
    re.IGNORECASE,
)
_X_PART = re.compile(r"X([-\d.]+)", re.IGNORECASE)
_Y_PART = re.compile(r"Y([-\d.]+)", re.IGNORECASE)


def _has_xy(line: str) -> bool:
    upper = line.upper()
    return "X" in upper and "Y" in upper and upper.lstrip().startswith("G1")


def _parse_coords(lines: list[str]) -> tuple[list[float], list[float]]:
    xs, ys = [], []
    for line in lines:
        if not _has_xy(line):
            continue
        mx = _X_PART.search(line)
        my = _Y_PART.search(line)
        if mx and my:
            xs.append(float(mx.group(1)))
            ys.append(float(my.group(1)))
    return xs, ys


def _scale_line(line: str, scale: float, cx: float, cy: float, new_cx: float, new_cy: float) -> str:
    if not _has_xy(line):
        return line
    mx = _X_PART.search(line)
    my = _Y_PART.search(line)
    if not (mx and my):
        return line
    new_x = (float(mx.group(1)) - cx) * scale + new_cx
    new_y = (float(my.group(1)) - cy) * scale + new_cy
    line = _X_PART.sub("X{:.3f}".format(new_x), line)
    line = _Y_PART.sub("Y{:.3f}".format(new_y), line)
    return line


def scale_file(src: Path, dst: Path, bed_x: float, bed_y: float, margin: float, dry_run: bool):
    lines = src.read_text(errors="ignore").splitlines()
    xs, ys = _parse_coords(lines)
    if len(xs) < 2:
        print("SKIP (no coords): {}".format(src.name))
        return

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    w = max_x - min_x
    h = max_y - min_y

    usable_x = bed_x - 2 * margin
    usable_y = bed_y - 2 * margin

    if w < 1e-6 or h < 1e-6:
        print("SKIP (degenerate bbox): {}".format(src.name))
        return

    scale = min(usable_x / w, usable_y / h)
    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    new_cx = bed_x / 2.0
    new_cy = bed_y / 2.0

    new_w = w * scale
    new_h = h * scale

    action = "SCALE" if abs(scale - 1.0) > 0.002 else "CENTER"
    print("{}: {} x{:.4f}  bbox {}x{} -> {}x{}  ({})".format(
        src.name, action, scale,
        round(w, 1), round(h, 1),
        round(new_w, 1), round(new_h, 1),
        "dry-run" if dry_run else dst.name,
    ))

    if dry_run:
        return

    new_lines = [_scale_line(l, scale, cx, cy, new_cx, new_cy) for l in lines]
    dst.write_text("\n".join(new_lines) + "\n")


def parse_bed(s: str):
    try:
        a, b = s.lower().replace(" ", "").split("x")
        return float(a), float(b)
    except Exception:
        raise argparse.ArgumentTypeError("bed must look like 370x400")


def main():
    ap = argparse.ArgumentParser(description="Scale gcode to fill the SandTable bed.")
    ap.add_argument("input", help=".gcode file or folder of .gcode files")
    ap.add_argument("-o", "--output", help="output file (single-file mode only)")
    ap.add_argument("--bed", type=parse_bed, default=(BED_X, BED_Y), metavar="WxH")
    ap.add_argument("--margin", type=float, default=0.0, help="margin in mm on each side")
    ap.add_argument("--skip-names", default="RhoOffsetCalibration",
                    help="comma-separated file stems to skip")
    ap.add_argument("--dry-run", action="store_true", help="print stats only, no writes")
    args = ap.parse_args()

    bed_x, bed_y = args.bed
    skip = {s.strip().lower() for s in args.skip_names.split(",") if s.strip()}
    src = Path(args.input)

    if src.is_dir():
        files = sorted(src.glob("*.gcode"))
        for f in files:
            if f.stem.lower() in skip:
                print("SKIP (excluded): {}".format(f.name))
                continue
            scale_file(f, f, bed_x, bed_y, args.margin, args.dry_run)
    elif src.is_file():
        if src.stem.lower() in skip:
            print("SKIP (excluded): {}".format(src.name))
            return
        dst = Path(args.output) if args.output else src
        scale_file(src, dst, bed_x, bed_y, args.margin, args.dry_run)
    else:
        sys.exit("Not a file or folder: {}".format(src))


if __name__ == "__main__":
    main()
