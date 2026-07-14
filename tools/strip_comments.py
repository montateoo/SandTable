#!/usr/bin/env python3
"""Strip comment-only and blank lines from gcode files, leaving pure motion
commands (plus any leading G1 F### feedrate line untouched).

Usage
-----
    python strip_comments.py path/to/folder/    # strips every .gcode in-place
    python strip_comments.py file.gcode          # strips a single file in-place
"""
from __future__ import annotations

import sys
from pathlib import Path


def strip_file(path: Path) -> tuple[int, int]:
    lines = path.read_text(errors="ignore").splitlines()
    kept = [l for l in lines if l.strip() and not l.strip().startswith(";")]
    if kept != lines:
        path.write_text("\n".join(kept) + "\n")
    return len(lines), len(kept)


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: strip_comments.py <file.gcode|folder>")
    src = Path(sys.argv[1])
    files = sorted(src.glob("*.gcode")) if src.is_dir() else [src]
    if not files:
        sys.exit("No .gcode files found in {}".format(src))

    changed = 0
    for f in files:
        before, after = strip_file(f)
        if before != after:
            print("{}: {} -> {} lines".format(f.name, before, after))
            changed += 1
    print("\n{} of {} files had comments/blank lines removed.".format(changed, len(files)))


if __name__ == "__main__":
    main()
