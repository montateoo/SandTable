"""Configuration for the SandTable viewer service.

Reads OctoPrint connection details from a local `secrets.toml` (same shape as
the repo-root one used for development) or, failing that, from environment
variables. This file is deployed standalone onto the Pi alongside the table,
separate from the OctoPrint plugin itself.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

HERE = Path(__file__).parent
SECRETS_PATH = HERE / "secrets.toml"


def _load_toml():
    if SECRETS_PATH.exists():
        with open(SECRETS_PATH, "rb") as f:
            return tomllib.load(f)
    return {}


class Config:
    def __init__(self):
        data = _load_toml()
        octo = data.get("octoprint", {})
        viewer = data.get("viewer", {})

        self.octoprint_url = (
            os.environ.get("OCTOPRINT_URL") or octo.get("url") or "http://127.0.0.1"
        ).rstrip("/")
        self.api_key = os.environ.get("OCTOPRINT_API_KEY") or octo.get("api_key") or ""
        if not self.api_key:
            raise RuntimeError(
                "No OctoPrint API key configured. Set [octoprint] api_key in "
                f"{SECRETS_PATH.name} (see secrets.toml.example) or the "
                "OCTOPRINT_API_KEY environment variable."
            )

        self.bed_x = float(os.environ.get("VIEWER_BED_X") or viewer.get("bed_x") or 370)
        self.bed_y = float(os.environ.get("VIEWER_BED_Y") or viewer.get("bed_y") or 400)
        self.port = int(os.environ.get("VIEWER_PORT") or viewer.get("port") or 8099)
        self.poll_interval = float(
            os.environ.get("VIEWER_POLL_INTERVAL") or viewer.get("poll_interval") or 2.5
        )


config = Config()
