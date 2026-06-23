#!/usr/bin/env python3
"""Clean sand-table G-code so Grbl streams it without errors.

Sandify exports — especially patterns imported from `.thr` — embed a single huge
comment line (the original file's whole comment history). That line can overrun
Grbl's serial buffer, get chopped mid-stream, and surface as:

    error:2  Bad number format

This tool strips comments (`;...` and `(...)`) and blank lines, uppercases command
letters (Grbl wants upper case), and reports anything still suspect. The motion
itself is untouched.

Usage
-----
    python gcode_clean.py file.gcode                 # -> file.clean.gcode
    python gcode_clean.py folder --inplace           # clean every *.gcode (saves .bak)
    python gcode_clean.py folder --out cleaned        # write cleaned copies into ./cleaned
    python gcode_clean.py folder --check              # report problems only, write nothing
    --recursive   also descend into sub-folders
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Grbl's default line buffer is 80 chars; warn well before that.
GRBL_LINE_WARN = 70
TOKEN_RE = re.compile(r"^[A-Z][-+]?(\d+\.?\d*|\.\d+)$")


def clean_text(text: str):
    """Return (cleaned_lines, stats). stats = dict with counts and any warnings."""
    out = []
    longest_in = 0
    dropped = 0
    bad_tokens = []
    for i, raw in enumerate(text.splitlines(), 1):
        longest_in = max(longest_in, len(raw))
        # strip comments: everything after ';' and anything inside '(...)'
        code = raw.split(";", 1)[0]
        code = re.sub(r"\([^)]*\)", "", code)
        code = code.strip()
        if not code:
            dropped += 1
            continue
        code = code.upper()
        # sanity-check tokens (post-clean) so we surface real bad numbers, if any
        for tok in code.split():
            if not TOKEN_RE.match(tok):
                bad_tokens.append((i, tok, raw.strip()))
        out.append(code)
    longest_out = max((len(l) for l in out), default=0)
    stats = {
        "lines_in": len(text.splitlines()),
        "lines_out": len(out),
        "dropped": dropped,
        "longest_in": longest_in,
        "longest_out": longest_out,
        "bad_tokens": bad_tokens,
    }
    return out, stats


def report(path: Path, stats):
    flag = ""
    if stats["longest_in"] >= GRBL_LINE_WARN:
        flag = f"  <-- had a {stats['longest_in']}-char line (Grbl overflow risk)"
    print(f"{path.name}: {stats['lines_in']} -> {stats['lines_out']} lines "
          f"(dropped {stats['dropped']} comment/blank), longest {stats['longest_in']}"
          f"->{stats['longest_out']}{flag}")
    for ln, tok, line in stats["bad_tokens"][:10]:
        print(f"    ! line {ln}: still-bad token '{tok}'  ({line})")


def process_file(path: Path, mode, out_dir: Path | None):
    text = path.read_text(errors="ignore")
    lines, stats = clean_text(text)
    report(path, stats)
    if mode == "check":
        return
    body = "\n".join(lines) + "\n"
    if mode == "inplace":
        path.with_suffix(path.suffix + ".bak").write_text(text, encoding="utf-8")
        path.write_text(body, encoding="utf-8", newline="\n")
        print(f"    wrote {path.name} (backup: {path.name}{path.suffix}.bak)")
    elif mode == "out":
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / path.name
        dest.write_text(body, encoding="utf-8", newline="\n")
        print(f"    wrote {dest}")
    else:  # single-file default
        dest = path.with_name(path.stem + ".clean" + path.suffix)
        dest.write_text(body, encoding="utf-8", newline="\n")
        print(f"    wrote {dest}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Strip comments/blank lines from sand-table G-code for Grbl.")
    ap.add_argument("path", help="a .gcode file or a folder")
    ap.add_argument("--inplace", action="store_true", help="overwrite files (keeps a .bak)")
    ap.add_argument("--out", metavar="DIR", help="write cleaned copies into DIR")
    ap.add_argument("--check", action="store_true", help="report problems only; write nothing")
    ap.add_argument("--recursive", action="store_true", help="descend into sub-folders")
    args = ap.parse_args(argv)

    p = Path(args.path).expanduser()
    mode = "check" if args.check else "inplace" if args.inplace else "out" if args.out else "single"
    out_dir = Path(args.out).expanduser() if args.out else None

    if p.is_file():
        process_file(p, "single" if mode == "out" else mode, out_dir)
    elif p.is_dir():
        files = (p.rglob("*.gcode") if args.recursive else p.glob("*.gcode"))
        files = sorted(files, key=lambda f: f.name.lower())
        if not files:
            sys.exit(f"No .gcode files in {p}")
        for f in files:
            process_file(f, mode, out_dir)
    else:
        sys.exit(f"Not found: {p}")


if __name__ == "__main__":
    main()
