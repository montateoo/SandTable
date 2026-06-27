"""Thin OctoPrint REST client: job status + raw G-code download.

Only the handful of calls the viewer needs, with the API key attached.
"""
from __future__ import annotations

import requests

from config import config

_session = requests.Session()
_session.headers["X-Api-Key"] = config.api_key

TIMEOUT = 5


def get_job() -> dict:
    """Current job state, file and progress, straight from /api/job."""
    r = _session.get(f"{config.octoprint_url}/api/job", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_sandtable_phase() -> dict | None:
    """Phase/round info from the SandTable plugin, if it's installed and running."""
    try:
        r = _session.get(f"{config.octoprint_url}/api/plugin/sandtable", timeout=TIMEOUT)
        if r.ok:
            return r.json()
    except requests.RequestException:
        pass
    return None


def get_gcode(path: str) -> str:
    """Download the raw G-code text for a file path like 'draw/squalo.gcode'."""
    r = _session.get(
        f"{config.octoprint_url}/downloads/files/local/{path}", timeout=TIMEOUT
    )
    r.raise_for_status()
    return r.text
