#!/usr/bin/env python3
"""
SandTable pattern gallery.

Point it at a folder of sand-table patterns and it renders every file as a drawing
and shows them in a scrollable thumbnail gallery. Click a thumbnail to enlarge.

Two formats are supported:
  * G-code (.gcode/.gco/.g/.nc): `G1 X.. Y..` linear moves in millimetres, drawn as
    one continuous polyline on the rectangular bed (default 370 x 400 mm).
  * Theta-rho (.thr): Sisyphus `theta rho` polar files (rho normalised 0..1), drawn
    on a circle inscribed in the bed.

Usage
-----
    # interactive scrollable gallery
    python pattern_gallery.py "A:/Projects/SandTable/draw/Pattern/ToUploadv2"

    # render a contact-sheet PNG instead of opening a window (no GUI needed)
    python pattern_gallery.py <folder> --export gallery.png

    # options
    --bed 370x400     bed size in mm (X x Y)
    --cols 4          columns in the grid
    --recursive       also scan sub-folders
    --invert          white line on sand background (mimics the real table)

Requires: matplotlib (pip install matplotlib). Tkinter ships with Python.
"""
from __future__ import annotations

import argparse
import base64
import io
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # render to memory only; Tkinter does all the displaying
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle

GCODE_EXTS = {".gcode", ".gco", ".g", ".nc"}
THR_EXTS = {".thr"}
PATTERN_EXTS = GCODE_EXTS | THR_EXTS

# colour themes ------------------------------------------------------------
SAND_BG = "#e7d9bd"
GROOVE = "#6b5836"
PAPER_BG = "#ffffff"
INK = "#1f3a5f"
BED_EDGE = "#b9a98a"


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------
def parse_gcode(path: Path):
    """Return a list of (x, y) points tracing the toolpath.

    Handles absolute (G90) coords with modal G1/G0 motion. Ignores Z/F/comments.
    These files are pure linear moves, so one continuous polyline is exactly the
    drawing the ball traces in the sand.
    """
    pts = []
    x = y = 0.0
    seen = False
    for raw in path.read_text(errors="ignore").splitlines():
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
        if nx is None and ny is None:
            continue
        if nx is not None:
            x = nx
        if ny is not None:
            y = ny
        pts.append((x, y))
        seen = True
    return pts if seen else []


def parse_thr(path: Path, bed):
    """Parse a Sisyphus theta-rho file into (x, y) points mapped onto the bed.

    Each line is `theta rho`: theta in radians (cumulative), rho normalised 0..1
    where 1 is the table rim. These are round-table patterns, so we map rho=1 to a
    circle inscribed in the bed (radius = min(bedX, bedY)/2, centred)."""
    bx, by = bed
    r_max = min(bx, by) / 2.0
    cx, cy = bx / 2.0, by / 2.0
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


def load_pattern(path: Path, bed):
    """Dispatch by extension. Returns (points_in_bed_coords, kind) where kind is
    'round' for theta-rho files and 'rect' for Cartesian G-code."""
    if path.suffix.lower() in THR_EXTS:
        return parse_thr(path, bed), "round"
    return parse_gcode(path), "rect"


def find_patterns(folder: Path, recursive: bool):
    it = folder.rglob("*") if recursive else folder.iterdir()
    files = [p for p in it if p.is_file() and p.suffix.lower() in PATTERN_EXTS]
    return sorted(files, key=lambda p: p.name.lower())


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
def draw_pattern(ax, pts, bed, title, invert, kind="rect"):
    bx, by = bed
    ax.set_facecolor(SAND_BG if invert else PAPER_BG)
    if pts:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.plot(xs, ys, "-", lw=0.5, color=("#fbf3e3" if invert else INK),
                solid_capstyle="round", solid_joinstyle="round")
    if kind == "round":
        ax.add_patch(Circle((bx / 2.0, by / 2.0), min(bx, by) / 2.0,
                            fill=False, ec=BED_EDGE, lw=1.0))
    else:
        ax.add_patch(Rectangle((0, 0), bx, by, fill=False, ec=BED_EDGE, lw=1.0))
    ax.set_aspect("equal")
    m = max(bx, by) * 0.03
    ax.set_xlim(-m, bx + m)
    ax.set_ylim(-m, by + m)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    if title:
        ax.set_title(title, fontsize=8)


def render_png(pts, bed, title, invert, px, dpi=100, kind="rect"):
    bx, by = bed
    w_in = px / dpi
    h_in = w_in * (by / bx) + 0.28  # extra strip for the caption
    fig = plt.figure(figsize=(w_in, h_in), dpi=dpi)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
    draw_pattern(ax, pts, bed, title, invert, kind)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def export_montage(files, bed, cols, invert, out: Path):
    n = len(files)
    cols = max(1, min(cols, n))
    rows = math.ceil(n / cols)
    bx, by = bed
    cell_w = 3.0
    cell_h = cell_w * (by / bx) + 0.4
    fig, axes = plt.subplots(rows, cols, figsize=(cols * cell_w, rows * cell_h))
    axes = [axes] if n == 1 else list(axes.reshape(-1))
    for i, f in enumerate(files):
        pts, kind = load_pattern(f, bed)
        draw_pattern(axes[i], pts, bed, f.stem, invert, kind)
    for j in range(n, len(axes)):
        axes[j].axis("off")
    fig.suptitle(f"{out.parent.name}  —  {n} patterns  (bed {bx:g}×{by:g} mm)", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    fig.savefig(out, dpi=110, facecolor="white")
    plt.close(fig)
    print(f"Wrote {out}  ({n} patterns)")


# --------------------------------------------------------------------------
# interactive Tk gallery
# --------------------------------------------------------------------------
def show_gallery(files, bed, cols, invert, thumb_px=240):
    import tkinter as tk

    root = tk.Tk()
    root.title(f"SandTable patterns — {len(files)} files  (bed {bed[0]:g}×{bed[1]:g} mm)")
    root.geometry("1180x800")

    canvas = tk.Canvas(root, background="#2b2b2b", highlightthickness=0)
    vsb = tk.Scrollbar(root, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    grid = tk.Frame(canvas, background="#2b2b2b")
    canvas.create_window((0, 0), window=grid, anchor="nw")
    grid.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

    refs = []  # keep PhotoImage refs alive

    def enlarge(path):
        win = tk.Toplevel(root)
        win.title(path.name)
        pts, kind = load_pattern(path, bed)
        png = render_png(pts, bed, path.stem, invert, px=760, kind=kind)
        img = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
        refs.append(img)
        tk.Label(win, image=img, background="#2b2b2b").pack()

    print(f"Rendering {len(files)} thumbnails...")
    for i, f in enumerate(files):
        pts, kind = load_pattern(f, bed)
        png = render_png(pts, bed, "", invert, px=thumb_px, kind=kind)
        img = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
        refs.append(img)
        cell = tk.Frame(grid, background="#2b2b2b", padx=6, pady=6)
        cell.grid(row=(i // cols) * 2, column=i % cols)
        thumb = tk.Label(cell, image=img, cursor="hand2", background="#2b2b2b")
        thumb.pack()
        thumb.bind("<Button-1>", lambda e, p=f: enlarge(p))
        tk.Label(grid, text=f.name, fg="#dddddd", background="#2b2b2b",
                 wraplength=thumb_px, font=("Segoe UI", 8)).grid(
            row=(i // cols) * 2 + 1, column=i % cols, pady=(0, 8))

    root.mainloop()


# --------------------------------------------------------------------------
def parse_bed(s):
    try:
        a, b = s.lower().replace(" ", "").split("x")
        return float(a), float(b)
    except Exception:
        raise argparse.ArgumentTypeError("bed must look like 370x400")


def main(argv=None):
    ap = argparse.ArgumentParser(description="View SandTable G-code patterns as a gallery.")
    ap.add_argument("folder", nargs="?", default=".", help="folder of .gcode / .thr files")
    ap.add_argument("--bed", type=parse_bed, default=(370.0, 400.0), help="bed size mm, e.g. 370x400")
    ap.add_argument("--cols", type=int, default=4, help="columns in the grid")
    ap.add_argument("--recursive", action="store_true", help="scan sub-folders too")
    ap.add_argument("--invert", action="store_true", help="white line on sand background")
    ap.add_argument("--export", metavar="OUT.png", help="render a contact-sheet PNG and exit (no window)")
    args = ap.parse_args(argv)

    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        sys.exit(f"Not a folder: {folder}")
    files = find_patterns(folder, args.recursive)
    if not files:
        sys.exit(f"No patterns ({', '.join(sorted(PATTERN_EXTS))}) found in {folder}")

    print(f"Found {len(files)} pattern(s) in {folder}")
    if args.export:
        export_montage(files, args.bed, args.cols, args.invert, Path(args.export))
    else:
        show_gallery(files, args.bed, args.cols, args.invert)


if __name__ == "__main__":
    main()
