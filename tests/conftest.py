"""Make the standalone modules importable without triggering the package __init__
(which imports OctoPrint). cycle.py and plug.py have no OctoPrint dependencies."""
import os
import sys

PKG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "octoprint_sandtable"))
if PKG_DIR not in sys.path:
    sys.path.insert(0, PKG_DIR)

# Same trick for octoprint-f1sisyphus's pure modules (race.py, circuit.py,
# shelly.py, openf1.py have no OctoPrint dependencies either).
F1_PKG_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "octoprint-f1sisyphus", "octoprint_f1sisyphus")
)
if F1_PKG_DIR not in sys.path:
    sys.path.insert(0, F1_PKG_DIR)

# Same trick for octoprint-nanoled's pure module (nano.py has no OctoPrint dependencies).
NANOLED_PKG_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "octoprint-nanoled", "octoprint_nanoled")
)
if NANOLED_PKG_DIR not in sys.path:
    sys.path.insert(0, NANOLED_PKG_DIR)
