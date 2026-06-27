"""SandTable viewer: a small Flask service showing what the table is drawing
right now, animated in sync with OctoPrint's reported job progress.

Runs standalone on the Pi (systemd unit, see README) alongside OctoPrint —
it's a separate process that just talks to OctoPrint's REST API, not a plugin.
"""
from __future__ import annotations

from flask import Flask, jsonify, render_template

import octoprint_client as octo
from config import config
from gcode_path import parse_gcode

app = Flask(__name__)

# Cache the parsed path by file path+size so we don't re-download/parse on every poll.
_path_cache: dict[str, tuple] = {}


def _file_label(name: str) -> str:
    stem = name.rsplit(".", 1)[0]
    return stem.replace("_", " ").replace("-", " ").strip().title()


@app.route("/")
def index():
    return render_template(
        "index.html",
        bed_x=config.bed_x,
        bed_y=config.bed_y,
        poll_interval=config.poll_interval,
    )


@app.route("/api/state")
def api_state():
    job = octo.get_job()
    phase_info = octo.get_sandtable_phase()

    file_info = job.get("job", {}).get("file", {}) or {}
    progress = job.get("progress", {}) or {}

    return jsonify(
        state=job.get("state", "Unknown"),
        printing=job.get("state") == "Printing",
        file={
            "path": file_info.get("path"),
            "name": file_info.get("name"),
            "label": _file_label(file_info.get("name") or "") if file_info.get("name") else None,
            "size": file_info.get("size"),
        },
        progress={
            "completion": progress.get("completion"),
            "printTime": progress.get("printTime"),
            "printTimeLeft": progress.get("printTimeLeft"),
        },
        phase=(phase_info or {}).get("phase"),
        round=(phase_info or {}).get("round"),
        rounds=(phase_info or {}).get("rounds"),
    )


@app.route("/api/path/<path:file_path>")
def api_path(file_path: str):
    cache_key = file_path
    cached = _path_cache.get(cache_key)
    if cached is not None:
        points = cached
    else:
        text = octo.get_gcode(file_path)
        points = parse_gcode(text)
        _path_cache[cache_key] = points
        # Keep the cache small; a sand table cycles through a couple of pools.
        if len(_path_cache) > 20:
            _path_cache.pop(next(iter(_path_cache)))

    return jsonify(
        points=points,
        bed=[config.bed_x, config.bed_y],
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.port)
