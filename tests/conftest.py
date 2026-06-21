"""Make the standalone modules importable without triggering the package __init__
(which imports OctoPrint). cycle.py and plug.py have no OctoPrint dependencies."""
import os
import sys

PKG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "octoprint_sandtable"))
if PKG_DIR not in sys.path:
    sys.path.insert(0, PKG_DIR)
