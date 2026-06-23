# coding=utf-8
"""OctoPrint-SandTable: autonomous ERASER/DRAW cycling + smart-plug power control.

See the README for the full picture. In short: while powered on the plugin runs
N rounds of ERASER -> DRAW (round-robin from two folders), then cuts power to the
whole machine via a local smart plug. An external schedule powers it back on and
this plugin auto-resumes on boot.
"""

from __future__ import absolute_import

import os
import subprocess
import threading
import time

import octoprint.plugin
from octoprint.events import Events

from . import cycle
from .plug import PLUG_TYPES, PlugError, make_plug


class CycleError(Exception):
    """A recoverable problem that should stop the cycle (e.g. empty pool)."""


class SandTablePlugin(
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.SimpleApiPlugin,
):
    # ------------------------------------------------------------------ setup
    def initialize(self):
        self._lock = threading.RLock()
        self._running = False
        self._phase = None
        self._round = 0
        self._rounds = 1
        self._current_path = None
        self._skip = False
        self._last_error = None
        self._autostart_inflight = False

    # --------------------------------------------------------------- settings
    def get_settings_defaults(self):
        return {
            "enabled": False,            # opt-in master switch
            "autostart_on_boot": True,   # resume the cycle when OctoPrint starts
            "eraser_folder": "eraser",
            "draw_folder": "draw",
            "rounds": 2,
            "plug_type": "shelly1",      # one of plug.PLUG_TYPES
            "plug_host": "",
            "plug_user": "",
            "plug_password": "",
            "off_delay_seconds": 60,     # plug stays on this long so the Pi can halt
            "shutdown_pi": True,         # clean OS shutdown before power is cut
            "startup_delay_seconds": 30,
            "program_wake": False,       # future: program the plug's wake timer
            "wake_mode": "after_hours",
            "wake_value": "8",
            "dry_run": True,             # SAFE DEFAULT: never actually power off/shut down
            "eraser_index": 0,           # persisted round-robin pointers
            "draw_index": 0,
        }

    def get_settings_restricted_paths(self):
        # Keep plug credentials out of the unauthenticated settings payload.
        return {"admin": [["plug_user"], ["plug_password"]]}

    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        # If the master switch was just enabled, arm autostart (no-op if running).
        self._maybe_autostart(reason="settings")

    # -------------------------------------------------------------- templates
    def get_template_configs(self):
        return [
            # Settings panel: let OctoPrint bind it (so `settings.plugins.sandtable.X`
            # in the template resolves correctly). Do NOT attach our custom view model
            # to it, or the binding context changes and the fields won't populate.
            {"type": "settings", "name": "SandTable", "custom_bindings": False},
            {"type": "tab", "name": "SandTable", "custom_bindings": True},
        ]

    def get_assets(self):
        return {"js": ["js/sandtable.js"], "css": ["css/sandtable.css"]}

    # ----------------------------------------------------------------- events
    def on_after_startup(self):
        self._maybe_autostart(reason="startup")

    def on_event(self, event, payload):
        if event == Events.CONNECTED:
            self._maybe_autostart(reason="connected")
        elif event == Events.PRINT_DONE:
            self._run_bg(self._handle_print_done, payload)
        elif event in (Events.PRINT_FAILED, Events.PRINT_CANCELLED, Events.ERROR):
            self._run_bg(self._handle_print_stop, event, payload)

    # ------------------------------------------------------------- public ops
    def start_cycle(self, rounds_override=None):
        with self._lock:
            if self._running:
                return False, "Cycle already running"
            if rounds_override is not None:
                try:
                    self._rounds = max(1, int(rounds_override))
                except (TypeError, ValueError):
                    self._rounds = max(1, self._settings.get_int(["rounds"]) or 1)
            else:
                self._rounds = max(1, self._settings.get_int(["rounds"]) or 1)
            self._round = 0
            self._phase = None
            self._current_path = None
            self._skip = False
            self._last_error = None
            self._running = True

        action, phase, rnd = cycle.START
        self._round = rnd
        self._phase = phase
        try:
            self._do_action(action)
        except (CycleError, ValueError, PlugError) as exc:
            self._stop_with_error(str(exc))
            return False, str(exc)
        return True, "Cycle started"

    def stop_cycle(self):
        with self._lock:
            was_running = self._running
            self._running = False
            self._current_path = None
            self._skip = False
        if self._printer.is_printing():
            self._printer.cancel_print()
        self._logger.info("SandTable: cycle stopped by request")
        return was_running

    def skip_current(self):
        with self._lock:
            if not self._running:
                return False, "Cycle is not running"
            self._skip = True
        if self._printer.is_printing():
            self._printer.cancel_print()
            return True, "Skipping current pattern"
        with self._lock:
            self._skip = False
        return False, "Nothing is printing to skip"

    # --------------------------------------------------------- event handlers
    def _handle_print_done(self, payload):
        with self._lock:
            if not self._running:
                return
            if not self._is_our_print(payload):
                self._logger.debug("SandTable: ignoring PrintDone for a non-managed file")
                return
            action, next_phase, next_round = cycle.advance(self._phase, self._round, self._rounds)
            self._round = next_round
            self._phase = next_phase

        if action == cycle.ACTION_COMPLETE:
            with self._lock:
                self._running = False
                self._current_path = None
            self._logger.info("SandTable: cycle complete after %d round(s); starting power-off", self._rounds)
            self._power_off_sequence()
        else:
            try:
                self._do_action(action)
            except (CycleError, ValueError, PlugError) as exc:
                self._stop_with_error(str(exc))

    def _handle_print_stop(self, event, payload):
        with self._lock:
            running = self._running
            skipping = self._skip
            if skipping:
                self._skip = False
        if not running:
            return
        if skipping:
            # We cancelled on purpose to skip the current pattern -> advance.
            self._handle_print_done(payload)
            return
        reason = (payload or {}).get("reason", "")
        self._stop_with_error("print {} {}".format(event, reason).strip())

    # ----------------------------------------------------------- cycle engine
    def _do_action(self, action):
        if action == cycle.ACTION_PRINT_ERASER:
            self._phase = cycle.PHASE_ERASER
            self._print_file(self._next_file("eraser"))
        elif action == cycle.ACTION_PRINT_DRAW:
            self._phase = cycle.PHASE_DRAW
            self._print_file(self._next_file("draw"))
        else:
            raise CycleError("Unknown action: {!r}".format(action))

    def _print_file(self, path):
        if not self._wait_ready():
            raise CycleError("Printer was not ready to start the next print")
        self._current_path = path
        self._logger.info(
            "SandTable: printing %s (%s, round %d/%d)",
            path, self._phase, self._round + 1, self._rounds,
        )
        self._printer.select_file(path, False, printAfterSelect=True)

    def _next_file(self, kind):
        folder = self._settings.get(["eraser_folder" if kind == "eraser" else "draw_folder"])
        index_key = "eraser_index" if kind == "eraser" else "draw_index"
        pool = self._list_pool(folder)
        if not pool:
            raise CycleError("No G-code files found in the '{}' folder".format(folder))
        index = self._settings.get_int([index_key]) or 0
        name, new_index = cycle.pick_next(pool, index)
        self._settings.set_int([index_key], new_index)
        self._settings.save()  # persist so we resume correctly after the power cycle
        return name

    def _stop_with_error(self, message):
        with self._lock:
            self._running = False
            self._current_path = None
            self._last_error = message
        self._logger.error("SandTable: stopping cycle: %s", message)

    # --------------------------------------------------------------- power off
    def _power_off_sequence(self):
        dry = self._settings.get_boolean(["dry_run"])
        delay = self._settings.get_int(["off_delay_seconds"]) or 0
        shutdown = self._settings.get_boolean(["shutdown_pi"])
        plug_type = self._settings.get(["plug_type"])
        host = self._settings.get(["plug_host"])

        if dry:
            self._logger.info(
                "SandTable DRY RUN: would power off via %s@%s (delay %ss); shutdown_pi=%s",
                plug_type, host, delay, shutdown,
            )
            return

        try:
            plug = make_plug(
                plug_type, host,
                self._settings.get(["plug_user"]),
                self._settings.get(["plug_password"]),
            )
            plug.off(delay)
            self._logger.info("SandTable: sent power-off (delay %ss) to %s", delay, host)
        except PlugError as exc:
            # Couldn't cut the table's power -> do NOT shut the Pi down, or we'd
            # leave the table running with no controller. Surface the error.
            self._stop_with_error("power-off failed, leaving machine on: {}".format(exc))
            return

        if shutdown:
            self._shutdown_pi()

    def _shutdown_pi(self):
        cmd = self._settings.global_get(["server", "commands", "systemShutdownCommand"])
        if not cmd:
            self._logger.warning(
                "SandTable: no systemShutdownCommand configured in OctoPrint; cannot shut down the host."
            )
            return
        self._logger.info("SandTable: shutting down host with: %s", cmd)
        try:
            subprocess.Popen(cmd, shell=True)
        except Exception:
            self._logger.exception("SandTable: host shutdown command failed")

    # ----------------------------------------------------------- autostart
    def _maybe_autostart(self, reason=""):
        if not self._settings.get_boolean(["enabled"]):
            return
        if not self._settings.get_boolean(["autostart_on_boot"]):
            return
        with self._lock:
            if self._running or self._autostart_inflight:
                return
            self._autostart_inflight = True
        self._logger.info("SandTable: autostart armed (%s)", reason)
        self._run_bg(self._autostart_worker)

    def _autostart_worker(self):
        try:
            if not self._wait_ready(timeout=120):
                self._logger.warning("SandTable: printer not ready in time; autostart aborted")
                return
            delay = self._settings.get_int(["startup_delay_seconds"]) or 0
            if delay > 0:
                time.sleep(delay)
            with self._lock:
                if self._running:
                    return
            self._logger.info("SandTable: autostarting cycle")
            self.start_cycle()
        finally:
            with self._lock:
                self._autostart_inflight = False

    # --------------------------------------------------------------- helpers
    def _wait_ready(self, timeout=15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if (
                self._printer.is_operational()
                and not self._printer.is_printing()
                and not self._printer.is_paused()
            ):
                return True
            time.sleep(0.5)
        return False

    def _is_our_print(self, payload):
        if not self._current_path:
            return True
        done = (payload or {}).get("path") or (payload or {}).get("file") or ""
        if not done:
            return True
        return os.path.basename(done) == os.path.basename(self._current_path)

    def _list_pool(self, folder):
        try:
            listing = self._file_manager.list_files(path=folder, recursive=True)
        except Exception:
            self._logger.exception("SandTable: could not list folder %r", folder)
            return []
        entries = (listing or {}).get("local", {})
        out = []
        _collect_gcode(entries, out)
        out.sort(key=lambda p: p.lower())
        return out

    def _peek(self, pool, index_key):
        if not pool:
            return None
        index = self._settings.get_int([index_key]) or 0
        return pool[index % len(pool)]

    def _run_bg(self, target, *args):
        def _safe():
            try:
                target(*args)
            except Exception:
                self._logger.exception("SandTable: background task failed")

        t = threading.Thread(target=_safe)
        t.daemon = True
        t.start()

    # -------------------------------------------------------------- simple api
    def get_api_commands(self):
        return {
            "start": [],
            "stop": [],
            "skip": [],
            "test_plug": ["state"],
            "simulate_complete": [],
            "power_off_now": [],
        }

    def on_api_command(self, command, data):
        import flask

        if command == "start":
            rounds = data.get("rounds") if data else None
            ok, msg = self.start_cycle(rounds_override=rounds)
            return flask.jsonify(ok=ok, message=msg, status=self._status())
        if command == "stop":
            self.stop_cycle()
            return flask.jsonify(ok=True, message="Cycle stopped", status=self._status())
        if command == "skip":
            ok, msg = self.skip_current()
            return flask.jsonify(ok=ok, message=msg, status=self._status())
        if command == "test_plug":
            state = (data.get("state") or "off").lower()
            try:
                plug = make_plug(
                    self._settings.get(["plug_type"]),
                    self._settings.get(["plug_host"]),
                    self._settings.get(["plug_user"]),
                    self._settings.get(["plug_password"]),
                )
                if state == "on":
                    plug.on()
                else:
                    plug.off(0)  # immediate; this is a deliberate manual test
                return flask.jsonify(ok=True, message="Plug switched {}".format(state))
            except PlugError as exc:
                return flask.jsonify(ok=False, message=str(exc))
        if command in ("simulate_complete", "power_off_now"):
            self._run_bg(self._power_off_sequence)
            return flask.jsonify(ok=True, message="Power-off sequence triggered", status=self._status())
        return flask.jsonify(ok=False, message="Unknown command")

    def on_api_get(self, request):
        import flask

        return flask.jsonify(self._status())

    def _status(self):
        eraser_pool = self._list_pool(self._settings.get(["eraser_folder"]))
        draw_pool = self._list_pool(self._settings.get(["draw_folder"]))
        with self._lock:
            running = self._running
            phase = self._phase
            rnd = self._round
            rounds = self._rounds
            current = self._current_path
            err = self._last_error
        return {
            "running": running,
            "phase": phase,
            "round": rnd,
            "rounds": rounds if running else (self._settings.get_int(["rounds"]) or 1),
            "current_file": current,
            "next_eraser": self._peek(eraser_pool, "eraser_index"),
            "next_draw": self._peek(draw_pool, "draw_index"),
            "eraser_count": len(eraser_pool),
            "draw_count": len(draw_pool),
            "dry_run": self._settings.get_boolean(["dry_run"]),
            "last_error": err,
            "plug_types": list(PLUG_TYPES),
        }

    # ------------------------------------------------------------ sw update
    def get_update_information(self):
        return {
            "sandtable": {
                "displayName": "OctoPrint-SandTable",
                "displayVersion": self._plugin_version,
                "type": "github_release",
                "user": "montateoo",
                "repo": "OctoPrint-SandTable",
                "current": self._plugin_version,
                "pip": "https://github.com/montateoo/OctoPrint-SandTable/archive/{target_version}.zip",
            }
        }


def _collect_gcode(entries, out):
    """Recursively collect machinecode (G-code) file paths from a file-manager tree."""
    for entry in entries.values():
        etype = entry.get("type")
        if etype == "folder":
            _collect_gcode(entry.get("children") or {}, out)
        elif etype == "machinecode":
            path = entry.get("path") or entry.get("name")
            if path:
                out.append(path)


__plugin_name__ = "OctoPrint-SandTable"
__plugin_pythoncompat__ = ">=3.7,<4"


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = SandTablePlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }
