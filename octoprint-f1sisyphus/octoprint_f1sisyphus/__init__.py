# coding=utf-8
"""OctoPrint-F1Sisyphus: race-day lifecycle for the Sisyphus table.

On race day the table wakes ~1 hour before the race (triggered externally by a
Shelly schedule that this plugin itself maintains), draws the circuit's outline
from a cached/auto-generated G-code pattern, waits for the session to actually
go live, then live-traces the chosen driver's on-track position for the race's
duration, then powers off and reschedules itself for the next race.

See the approved plan for the full design. In short: IDLE -> DRAW_CIRCUIT ->
WAIT_FOR_LIVE -> TRACKING -> COMPLETE (race.py owns the phase transitions).
"""

from __future__ import absolute_import

import datetime
import io
import os
import subprocess
import threading
import time

import flask

import octoprint.filemanager.util
import octoprint.plugin
from octoprint.events import Events
from octoprint.util import RepeatedTimer

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    from backports.zoneinfo import ZoneInfo

from . import circuit
from . import race
from . import shelly
from .circuit import CircuitError
from .openf1 import OpenF1Client, OpenF1Error
from .shelly import ShellyError


class F1SisyphusPlugin(
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.SimpleApiPlugin,
    octoprint.plugin.EventHandlerPlugin,
):
    # ------------------------------------------------------------------ setup
    def initialize(self):
        self._lock = threading.RLock()
        self._phase = race.PHASE_IDLE
        self._upcoming_session = None
        self._wait_timer = None
        self._tracking_timer = None
        self._bounds = None
        self._last_table_pos = None
        self._last_seen_date = None
        self._last_progress_time = None
        self._tracking_started_at = None
        self._points_drawn = 0
        self._current_circuit_path = None
        self._last_error = None
        self._next_scheduled_race = None
        self._openf1 = None

    def _get_openf1(self):
        if self._openf1 is None:
            self._openf1 = OpenF1Client(api_base=self._settings.get(["api_base"]))
        return self._openf1

    # --------------------------------------------------------------- settings
    def get_settings_defaults(self):
        return dict(
            enabled=False,
            dry_run=True,
            api_base="https://api.openf1.org/v1",
            driver_number=1,
            session_key="latest",
            circuit_key_override=None,
            force_live_for_testing=False,
            lead_minutes=60,
            wait_for_live_poll_interval=30,
            live_poll_interval=3,
            no_data_timeout_seconds=300,
            race_duration_safety_cap_minutes=180,
            circuits_folder="circuits",
            circuit_feedrate=3000,
            feedrate=6000,
            table_min_x=0,
            table_max_x=200,
            table_min_y=0,
            table_max_y=200,
            margin=10,
            flip_x=False,
            flip_y=False,
            min_move=0.4,
            off_delay_seconds=60,
            shutdown_pi=True,
            shelly_host="",
            shelly_password="",
            shelly_switch_id=0,
            shelly_script_id=None,
            shelly_schedule_id=None,
        )

    def get_settings_restricted_paths(self):
        return {"admin": [["shelly_password"]]}

    # -------------------------------------------------------------- templates
    def get_assets(self):
        return dict(js=["js/f1sisyphus.js"], css=["css/f1sisyphus.css"])

    def get_template_configs(self):
        return [
            dict(type="settings", custom_bindings=False),
            dict(type="tab", custom_bindings=True),
        ]

    # ----------------------------------------------------------------- events
    def on_after_startup(self):
        self._logger.info("F1 Sisyphus Tracker started")

    def on_event(self, event, payload):
        if event == Events.PRINT_DONE:
            with self._lock:
                phase = self._phase
            if phase == race.PHASE_DRAW_CIRCUIT and self._is_our_print(payload):
                self._run_bg(self._enter_wait_for_live)
        elif event in (Events.DISCONNECTED, Events.ERROR):
            with self._lock:
                phase = self._phase
                self._phase = race.PHASE_IDLE
            if phase != race.PHASE_IDLE:
                self._cancel_timers()
                self._stop_with_error("printer event: {}".format(event))

    # ------------------------------------------------------------- public ops
    def start_race_cycle(self):
        with self._lock:
            if not self._settings.get_boolean(["enabled"]):
                return False, "F1 Sisyphus is disabled in settings"
            if self._phase != race.PHASE_IDLE:
                return False, "Already running (phase={})".format(self._phase)
            if not self._printer.is_operational():
                return False, "Printer/table is not connected"
            if self._printer.is_printing():
                return False, "Refusing to start: a real print job is active"
            self._last_error = None
            _, phase = race.START
            self._phase = phase
        self._run_bg(self._begin_draw_circuit)
        return True, "Race cycle started"

    def _stop_cycle(self):
        with self._lock:
            self._phase = race.PHASE_IDLE
            self._upcoming_session = None
            self._current_circuit_path = None
        self._cancel_timers()
        if self._printer.is_printing():
            self._printer.cancel_print()
        self._logger.info("F1Sisyphus: cycle stopped by request")

    def _cancel_timers(self):
        with self._lock:
            wait_timer = self._wait_timer
            tracking_timer = self._tracking_timer
            self._wait_timer = None
            self._tracking_timer = None
        if wait_timer:
            wait_timer.cancel()
        if tracking_timer:
            tracking_timer.cancel()

    def _stop_with_error(self, message):
        with self._lock:
            self._last_error = message
        self._logger.error("F1Sisyphus: %s", message)

    # ---------------------------------------------- phase 1: IDLE -> DRAW_CIRCUIT
    def _begin_draw_circuit(self):
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        circuit_key_override = self._settings.get(["circuit_key_override"])
        session_key_override = self._settings.get(["session_key"])
        if session_key_override == "latest":
            session_key_override = None

        try:
            next_race = self._get_openf1().get_upcoming_race(now_utc)
        except OpenF1Error as exc:
            self._logger.warning("F1Sisyphus: could not look up the upcoming race: %s", exc)
            next_race = None

        upcoming = dict(next_race) if next_race else {}
        if circuit_key_override:
            upcoming["circuit_key"] = circuit_key_override
        if session_key_override:
            upcoming["session_key"] = session_key_override

        with self._lock:
            self._upcoming_session = upcoming

        circuit_key = upcoming.get("circuit_key")
        if not circuit_key:
            self._logger.warning(
                "F1Sisyphus: no circuit_key available (no upcoming race and no override); skipping circuit draw"
            )
            self._enter_wait_for_live()
            return

        try:
            path = self._get_or_build_circuit_path(circuit_key)
        except (CircuitError, OpenF1Error) as exc:
            self._logger.warning("F1Sisyphus: circuit draw skipped (%s); proceeding to wait-for-live", exc)
            self._enter_wait_for_live()
            return

        with self._lock:
            self._current_circuit_path = path
        self._logger.info("F1Sisyphus: printing circuit outline %s", path)
        self._printer.select_file(path, False, printAfterSelect=True)

    def _get_or_build_circuit_path(self, circuit_key):
        circuits_folder = self._settings.get(["circuits_folder"])
        rel_path = circuit.circuit_cache_path(circuits_folder, circuit_key)
        if self._file_manager.file_exists("local", rel_path):
            return rel_path

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        table_bounds = (
            float(self._settings.get(["table_min_x"])),
            float(self._settings.get(["table_max_x"])),
            float(self._settings.get(["table_min_y"])),
            float(self._settings.get(["table_max_y"])),
        )
        gcode_text = circuit.build_circuit_gcode(
            self._get_openf1(),
            circuit_key,
            self._settings.get_int(["driver_number"]),
            now_utc,
            table_bounds,
            float(self._settings.get(["margin"])),
            self._settings.get_boolean(["flip_x"]),
            self._settings.get_boolean(["flip_y"]),
            self._settings.get_int(["circuit_feedrate"]),
        )
        self._file_manager.add_file(
            "local",
            rel_path,
            octoprint.filemanager.util.StreamWrapper(
                os.path.basename(rel_path), io.BytesIO(gcode_text.encode("utf-8"))
            ),
            allow_overwrite=True,
        )
        return rel_path

    # ----------------------------------------- phase 2: DRAW_CIRCUIT -> WAIT_FOR_LIVE
    def _enter_wait_for_live(self):
        with self._lock:
            _, phase = race.advance_on_draw_done(self._phase)
            self._phase = phase

        interval = float(self._settings.get(["wait_for_live_poll_interval"]))
        timer = RepeatedTimer(interval, self._poll_session_live, run_first=True)
        with self._lock:
            self._wait_timer = timer
        timer.start()

    def _poll_session_live(self):
        with self._lock:
            if self._phase != race.PHASE_WAIT_FOR_LIVE:
                return
            upcoming = self._upcoming_session

        if self._settings.get_boolean(["force_live_for_testing"]):
            live = True
        else:
            live = self._check_session_live(upcoming)

        if not live:
            return

        with self._lock:
            timer = self._wait_timer
            self._wait_timer = None
        if timer:
            timer.cancel()
        self._run_bg(self._enter_tracking)

    def _check_session_live(self, upcoming):
        if not upcoming or not upcoming.get("session_key"):
            return False
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        date_gt = (now_utc - datetime.timedelta(seconds=120)).isoformat()
        try:
            points = self._get_openf1().get_location(
                upcoming["session_key"], self._settings.get_int(["driver_number"]), date_gt=date_gt
            )
        except OpenF1Error as exc:
            self._logger.warning("F1Sisyphus: live-check poll failed: %s", exc)
            return False
        return bool(points)

    # ----------------------------------------------- phase 3: WAIT_FOR_LIVE -> TRACKING
    def _enter_tracking(self):
        with self._lock:
            _, phase = race.advance_on_live_detected(self._phase)
            self._phase = phase
            self._last_seen_date = None
            self._last_table_pos = None
            self._points_drawn = 0
            self._last_progress_time = time.time()
            self._tracking_started_at = time.time()
            upcoming = self._upcoming_session

        bounds = self._calibrate_bounds(upcoming)
        with self._lock:
            self._bounds = bounds

        interval = float(self._settings.get(["live_poll_interval"]))
        timer = RepeatedTimer(interval, self._poll_position, run_first=True)
        with self._lock:
            self._tracking_timer = timer
        timer.start()

    def _calibrate_bounds(self, upcoming):
        if not upcoming or not upcoming.get("session_key"):
            return None
        try:
            data = self._get_openf1().get_location(upcoming["session_key"], self._settings.get_int(["driver_number"]))
        except OpenF1Error as exc:
            self._logger.warning("F1Sisyphus: calibration request failed: %s", exc)
            return None
        if not data:
            return None
        xs = [p["x"] for p in data if "x" in p]
        ys = [p["y"] for p in data if "y" in p]
        if not xs or not ys:
            return None
        return (min(xs), max(xs), min(ys), max(ys))

    def _poll_position(self):
        with self._lock:
            if self._phase != race.PHASE_TRACKING:
                return
            upcoming = self._upcoming_session
            last_progress = self._last_progress_time
            started_at = self._tracking_started_at

        no_data_timeout = self._settings.get_int(["no_data_timeout_seconds"]) or 300
        safety_cap = (self._settings.get_int(["race_duration_safety_cap_minutes"]) or 180) * 60
        now = time.time()
        if (last_progress and now - last_progress > no_data_timeout) or (
            started_at and now - started_at > safety_cap
        ):
            with self._lock:
                timer = self._tracking_timer
                self._tracking_timer = None
            if timer:
                timer.cancel()
            self._run_bg(self._enter_complete)
            return

        if not upcoming or not upcoming.get("session_key"):
            return

        with self._lock:
            last_seen = self._last_seen_date

        try:
            points = self._get_openf1().get_location(
                upcoming["session_key"], self._settings.get_int(["driver_number"]), date_gt=last_seen
            )
        except OpenF1Error as exc:
            self._logger.warning("F1Sisyphus: tracking poll failed: %s", exc)
            return

        if not points:
            return

        points.sort(key=lambda p: p.get("date", ""))

        with self._lock:
            self._last_progress_time = time.time()

        for p in points:
            with self._lock:
                if self._phase != race.PHASE_TRACKING:
                    break
            self._handle_point(p)
            if "date" in p:
                with self._lock:
                    self._last_seen_date = p["date"]

    def _handle_point(self, point):
        if "x" not in point or "y" not in point:
            return

        table_xy = self._transform(point["x"], point["y"])
        if table_xy is None:
            return
        tx, ty = table_xy

        with self._lock:
            last_pos = self._last_table_pos
        if last_pos is not None:
            dx = tx - last_pos[0]
            dy = ty - last_pos[1]
            min_move = float(self._settings.get(["min_move"]))
            if (dx * dx + dy * dy) ** 0.5 < min_move:
                return

        feedrate = int(self._settings.get(["feedrate"]))
        self._printer.commands("G1 X{:.2f} Y{:.2f} F{}".format(tx, ty, feedrate))

        with self._lock:
            self._last_table_pos = (tx, ty)
            self._points_drawn += 1
            points_drawn = self._points_drawn

        self._plugin_manager.send_plugin_message(
            self._identifier,
            dict(
                type="position",
                track_x=point["x"],
                track_y=point["y"],
                table_x=tx,
                table_y=ty,
                points_drawn=points_drawn,
            ),
        )

    def _transform(self, x, y):
        if not self._bounds:
            return None

        transform_fn = circuit.make_transform(
            self._bounds,
            float(self._settings.get(["table_min_x"])),
            float(self._settings.get(["table_max_x"])),
            float(self._settings.get(["table_min_y"])),
            float(self._settings.get(["table_max_y"])),
            float(self._settings.get(["margin"])),
            self._settings.get_boolean(["flip_x"]),
            self._settings.get_boolean(["flip_y"]),
        )
        return transform_fn(x, y)

    # ------------------------------------ phase 4: TRACKING -> COMPLETE -> power off
    def _enter_complete(self):
        with self._lock:
            _, phase = race.advance_on_race_ended(self._phase)
            self._phase = phase

        try:
            self._reschedule_for_next_race()
        except (OpenF1Error, ShellyError) as exc:
            self._stop_with_error("reschedule failed, leaving phase=complete: {}".format(exc))
            return

        try:
            self._power_off()
        except ShellyError as exc:
            # Couldn't cut the table's power -> do NOT shut the Pi down, or we'd
            # leave the table running with no controller. Surface the error.
            self._stop_with_error("power-off failed, leaving machine on: {}".format(exc))
            return

        with self._lock:
            self._phase = race.PHASE_IDLE
            self._upcoming_session = None
            self._current_circuit_path = None

    def _reschedule_for_next_race(self):
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        next_race = self._get_openf1().get_upcoming_race(now_utc)
        if next_race is None:
            self._logger.warning("F1Sisyphus: no upcoming race found; skipping reschedule")
            return

        race_start_utc = _parse_iso_utc(next_race["date_start"])
        wake_utc = race.compute_wake_time(race_start_utc, self._settings.get_int(["lead_minutes"]))

        dry = self._settings.get_boolean(["dry_run"])
        host = self._settings.get(["shelly_host"])
        switch_id = self._settings.get_int(["shelly_switch_id"])
        script_id = self._settings.get(["shelly_script_id"])
        race_name = "F1-{}".format(next_race.get("country_name", "Unknown"))

        client = shelly.ShellyClient(host, self._settings.get(["shelly_password"]))
        tz_name = client.get_timezone()
        wake_local = wake_utc.astimezone(ZoneInfo(tz_name)) if tz_name else wake_utc
        timespec = shelly.to_timespec(wake_local)

        if dry:
            calls = shelly.build_wake_schedule_calls(switch_id, script_id)
            self._logger.info(
                "F1Sisyphus DRY RUN: would reschedule %s, wake=%s, timespec=%r, calls=%r",
                race_name, wake_local, timespec, calls,
            )
            with self._lock:
                self._next_scheduled_race = next_race
            return

        if script_id is None:
            raise ShellyError("shelly_script_id is not configured; deploy f1sisyphus_waker on the Shelly first")

        calls = shelly.build_wake_schedule_calls(switch_id, script_id)
        prev_id = self._settings.get(["shelly_schedule_id"])
        new_id = shelly.replace_schedule(client, prev_id, timespec, calls)
        self._settings.set(["shelly_schedule_id"], new_id)
        self._settings.save()
        with self._lock:
            self._next_scheduled_race = next_race
        self._logger.info("F1Sisyphus: rescheduled %s, new schedule id=%s, wake=%s", race_name, new_id, wake_local)

    def _power_off(self):
        dry = self._settings.get_boolean(["dry_run"])
        delay = self._settings.get_int(["off_delay_seconds"]) or 0
        shutdown = self._settings.get_boolean(["shutdown_pi"])
        host = self._settings.get(["shelly_host"])
        switch_id = self._settings.get_int(["shelly_switch_id"])

        if dry:
            self._logger.info(
                "F1Sisyphus DRY RUN: would power off via %s (delay %ss); shutdown_pi=%s", host, delay, shutdown
            )
            return

        client = shelly.ShellyClient(host, self._settings.get(["shelly_password"]))
        if delay > 0:
            # Stay ON now, automatically toggle to OFF after delay seconds (mirrors
            # octoprint_sandtable's ShellyGen2Plug.off(): the delay must live on the
            # plug itself since the Pi is about to lose power).
            client.switch_set(True, switch_id=switch_id, toggle_after=delay)
        else:
            client.switch_set(False, switch_id=switch_id)
        self._logger.info("F1Sisyphus: sent power-off (delay %ss) to %s", delay, host)

        if shutdown:
            self._shutdown_pi()

    def _shutdown_pi(self):
        cmd = self._settings.global_get(["server", "commands", "systemShutdownCommand"])
        if not cmd:
            self._logger.warning(
                "F1Sisyphus: no systemShutdownCommand configured in OctoPrint; cannot shut down the host."
            )
            return
        self._logger.info("F1Sisyphus: shutting down host with: %s", cmd)
        try:
            subprocess.Popen(cmd, shell=True)
        except Exception:
            self._logger.exception("F1Sisyphus: host shutdown command failed")

    # --------------------------------------------------------------- helpers
    def _is_our_print(self, payload):
        with self._lock:
            current = self._current_circuit_path
        if not current:
            return True
        done = (payload or {}).get("path") or (payload or {}).get("file") or ""
        if not done:
            return True
        return os.path.basename(done) == os.path.basename(current)

    def _run_bg(self, target, *args):
        def _safe():
            try:
                target(*args)
            except Exception:
                self._logger.exception("F1Sisyphus: background task failed")

        t = threading.Thread(target=_safe)
        t.daemon = True
        t.start()

    # -------------------------------------------------------------- simple api
    def get_api_commands(self):
        return dict(
            start=[],
            stop=[],
            test_plug=["state"],
            simulate_complete=[],
            power_off_now=[],
            reschedule_now=[],
        )

    def on_api_command(self, command, data):
        if command == "start":
            ok, msg = self.start_race_cycle()
            return flask.jsonify(ok=ok, message=msg, status=self._status())
        if command == "stop":
            self._stop_cycle()
            return flask.jsonify(ok=True, message="Stopped", status=self._status())
        if command == "test_plug":
            state = ((data or {}).get("state") or "off").lower()
            try:
                client = shelly.ShellyClient(self._settings.get(["shelly_host"]), self._settings.get(["shelly_password"]))
                client.switch_set(state == "on", switch_id=self._settings.get_int(["shelly_switch_id"]))
                return flask.jsonify(ok=True, message="Plug switched {}".format(state))
            except ShellyError as exc:
                return flask.jsonify(ok=False, message=str(exc))
        if command == "simulate_complete":
            self._run_bg(self._enter_complete)
            return flask.jsonify(ok=True, message="Simulating race-complete", status=self._status())
        if command == "power_off_now":
            self._run_bg(self._power_off)
            return flask.jsonify(ok=True, message="Power-off triggered", status=self._status())
        if command == "reschedule_now":
            self._run_bg(self._reschedule_for_next_race)
            return flask.jsonify(ok=True, message="Reschedule triggered", status=self._status())
        return flask.jsonify(ok=False, message="Unknown command")

    def on_api_get(self, request):
        return flask.jsonify(self._status())

    def _status(self):
        with self._lock:
            return dict(
                phase=self._phase,
                upcoming_session=self._upcoming_session,
                points_drawn=self._points_drawn,
                last_table_pos=self._last_table_pos,
                dry_run=self._settings.get_boolean(["dry_run"]),
                last_error=self._last_error,
                next_scheduled_race=self._next_scheduled_race,
            )


def _parse_iso_utc(date_str):
    return datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))


__plugin_name__ = "F1 Sisyphus Tracker"
__plugin_pythoncompat__ = ">=3.9,<4"


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = F1SisyphusPlugin()
