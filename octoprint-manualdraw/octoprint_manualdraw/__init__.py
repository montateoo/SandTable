# coding=utf-8
"""OctoPrint-ManualDraw: scan a QR code, take live control of the ball.

Scanning the QR code (posted next to the table) opens a phone page with a
"Disegna tu stesso" button. Holding it 3s pauses whatever is currently
drawing (octoprint_sandtable's cycle, an f1sisyphus tracking session, or
nothing at all) and hands real-time control of the ball to the phone's tilt,
joystick-style. Releasing resumes whatever was paused.

No coordination with octoprint_sandtable/octoprint_f1sisyphus is needed:
OctoPrint's own pause_print()/resume_print() only gate the file reader, so
neither plugin's PrintDone-driven state machine ever sees it happen.
"""

from __future__ import annotations

import io
import os
import threading
import time

import flask
import qrcode

import octoprint.plugin
from octoprint.events import Events
from octoprint.util import RepeatedTimer

from . import manual

WATCHDOG_INTERVAL_SECONDS = 1.0


class ManualDrawPlugin(
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.SimpleApiPlugin,
    octoprint.plugin.BlueprintPlugin,
    octoprint.plugin.EventHandlerPlugin,
):
    # ------------------------------------------------------------------ setup
    def initialize(self):
        self._lock = threading.RLock()
        self._token = manual.new_token()
        self._manual_active = False
        self._session_secret = None  # identifies which phone currently owns the active session
        self._paused_by_us = False
        self._last_known_xy = (0.0, 0.0)
        self._current_xy = (0.0, 0.0)
        self._last_jog_ts = 0.0
        self._last_error = None
        self._watchdog = None

    def on_after_startup(self):
        # Persisted, not regenerated per boot: octoprint_sandtable power-cycles
        # this Pi after every ERASER/DRAW cycle as part of normal operation, so
        # a per-boot token would make a printed QR sticker stale after the
        # first cycle. Only "Regenerate code" (or a fresh install) rotates it.
        token = self._settings.get(["token"])
        if not token:
            token = manual.new_token()
            self._settings.set(["token"], token)
            self._settings.save()
        self._token = token
        self._watchdog = RepeatedTimer(WATCHDOG_INTERVAL_SECONDS, self._watchdog_tick)
        self._watchdog.start()

    # --------------------------------------------------------------- settings
    def get_settings_defaults(self):
        return {
            "enabled": False,  # opt-in master switch, same convention as sandtable
            "token": None,     # generated on first boot, persisted; see on_after_startup
            "table_min_x": 0,
            "table_max_x": 370,  # real calibrated bed (sandtable-viewer, tools/pattern_gallery.py)
            "table_min_y": 0,
            "table_max_y": 400,
            "max_speed_mm_s": 40,     # deliberately well under jog_feedrate's implied ceiling
            "jog_feedrate": 6000,     # matches the repo's fast/live-jog convention
            "dead_zone_deg": 4,
            "max_tilt_deg": 35,
            "watchdog_timeout_seconds": 2,
            "hold_seconds": 3,
            "min_move": 0.4,          # reuse octoprint_f1sisyphus's dedup default
            "swap_axes": False,       # swap which physical tilt axis drives X vs Y
            "invert_x": False,
            "invert_y": False,
        }

    def get_settings_restricted_paths(self):
        # Keep the control token out of the unauthenticated settings payload,
        # same convention octoprint_sandtable uses for its plug credentials.
        return {"admin": [["token"]]}

    # -------------------------------------------------------------- templates
    def get_template_configs(self):
        return [
            {"type": "settings", "name": "ManualDraw", "custom_bindings": False},
            {"type": "tab", "name": "ManualDraw", "custom_bindings": True},
        ]

    def get_assets(self):
        return {"js": ["js/manualdraw.js"], "css": ["css/manualdraw.css"]}

    # ----------------------------------------------------------------- events
    def on_event(self, event, payload):
        if event in (Events.DISCONNECTED, Events.ERROR):
            with self._lock:
                was_active = self._manual_active
                self._manual_active = False
                self._paused_by_us = False
                self._session_secret = None
            if was_active:
                self._logger.warning(
                    "ManualDraw: printer event %s while a manual session was active; "
                    "ending it without attempting to resume", event,
                )

    # ------------------------------------------------------- gcode.sent hook
    def on_gcode_sent(self, comm_instance, phase, cmd, cmd_type, gcode, subcode=None, tags=None, *args, **kwargs):
        if not cmd:
            return
        with self._lock:
            self._last_known_xy = manual.update_position(self._last_known_xy, cmd)

    # ------------------------------------------------------------ public API
    def is_blueprint_protected(self):
        # This plugin's whole point is a login-free page + endpoints for
        # anyone who scans the physical QR code -- gated by the per-boot
        # token embedded in that QR's URL, not by an OctoPrint session.
        return False

    @octoprint.plugin.BlueprintPlugin.route("/draw", methods=["GET"])
    def public_draw_page(self):
        return self._send_public_file("draw.html")

    @octoprint.plugin.BlueprintPlugin.route("/draw.js", methods=["GET"])
    def public_draw_js(self):
        return self._send_public_file("draw.js")

    @octoprint.plugin.BlueprintPlugin.route("/draw.css", methods=["GET"])
    def public_draw_css(self):
        return self._send_public_file("draw.css")

    @octoprint.plugin.BlueprintPlugin.route("/api/config", methods=["GET"])
    def public_api_config(self):
        # No token needed: nothing sensitive, just the UI timing the phone
        # needs to match the server-side "hold to activate" duration.
        return flask.jsonify(hold_seconds=self._settings.get_float(["hold_seconds"]) or 3.0)

    @octoprint.plugin.BlueprintPlugin.route("/api/status", methods=["GET"])
    def public_api_status(self):
        # No token needed either: this only reveals "is someone else already
        # drawing", not anything sensitive, so the idle page can show it
        # before inviting a hold-and-get-rejected attempt.
        with self._lock:
            active = self._manual_active
        return flask.jsonify(enabled=self._settings.get_boolean(["enabled"]), active=active)

    @octoprint.plugin.BlueprintPlugin.route("/api/start", methods=["POST"])
    def public_api_start(self):
        err = self._check_public_request()
        if err:
            return err

        with self._lock:
            if self._manual_active:
                return flask.jsonify(ok=False, message="Sessione gia' attiva"), 409
            if not self._printer.is_operational():
                return flask.jsonify(ok=False, message="Tavolo non connesso"), 503
            self._manual_active = True  # claim it before releasing the lock

        paused_by_us = False
        try:
            if self._printer.is_printing():
                self._printer.pause_print()
                paused_by_us = True
            self._printer.commands("G90")
        except Exception as exc:
            with self._lock:
                self._manual_active = False
            self._logger.exception("ManualDraw: failed to start manual session")
            return flask.jsonify(ok=False, message="Impossibile avviare: {}".format(exc)), 500

        session_secret = manual.new_token()
        with self._lock:
            x, y = self._last_known_xy
            self._paused_by_us = paused_by_us
            self._session_secret = session_secret
            self._current_xy = (x, y)
            self._last_jog_ts = time.time()

        self._logger.info(
            "ManualDraw: manual session started (paused_by_us=%s) at (%.1f, %.1f)", paused_by_us, x, y
        )
        return flask.jsonify(ok=True, x=x, y=y, bounds=self._bounds_dict(), session=session_secret)

    @octoprint.plugin.BlueprintPlugin.route("/api/jog", methods=["POST"])
    def public_api_jog(self):
        err = self._check_public_request()
        if err:
            return err

        data = flask.request.get_json(silent=True) or {}
        err = self._check_session_owner(data)
        if err:
            return err
        try:
            dbeta = float(data.get("dbeta", 0.0))
            dgamma = float(data.get("dgamma", 0.0))
        except (TypeError, ValueError):
            return flask.jsonify(ok=False, message="Payload non valido"), 400

        with self._lock:
            if not self._manual_active:
                return flask.jsonify(ok=False, message="Sessione non attiva"), 409
            now = time.time()
            dt = manual.clamp_dt(now - self._last_jog_ts)
            self._last_jog_ts = now
            x, y = self._current_xy

        dead_zone = self._settings.get_float(["dead_zone_deg"])
        max_tilt = self._settings.get_float(["max_tilt_deg"])
        max_speed = self._settings.get_float(["max_speed_mm_s"])
        swap = self._settings.get_boolean(["swap_axes"])
        inv_x = self._settings.get_boolean(["invert_x"])
        inv_y = self._settings.get_boolean(["invert_y"])
        vx, vy = manual.tilt_to_velocity(dbeta, dgamma, dead_zone, max_tilt, max_speed,
                                         swap_axes=swap, invert_x=inv_x, invert_y=inv_y)
        nx, ny = manual.integrate_and_clamp(x, y, vx, vy, dt, self._bounds())

        min_move = self._settings.get_float(["min_move"]) or 0.0
        if manual.distance(x, y, nx, ny) >= min_move:
            feedrate = self._settings.get_int(["jog_feedrate"])
            self._printer.commands("G1 X{:.2f} Y{:.2f} F{}".format(nx, ny, feedrate))
            with self._lock:
                self._current_xy = (nx, ny)
        else:
            nx, ny = x, y

        return flask.jsonify(ok=True, x=nx, y=ny)

    @octoprint.plugin.BlueprintPlugin.route("/api/stop", methods=["POST"])
    def public_api_stop(self):
        err = self._check_public_request()
        if err:
            return err
        data = flask.request.get_json(silent=True) or {}
        err = self._check_session_owner(data)
        if err:
            return err
        resumed = self._stop_manual_session()
        return flask.jsonify(ok=True, resumed=resumed)

    def _check_public_request(self):
        if not self._settings.get_boolean(["enabled"]):
            return flask.jsonify(ok=False, message="ManualDraw non abilitato"), 503
        data = flask.request.get_json(silent=True) or {}
        if not manual.token_matches(self._token, data.get("token")):
            return flask.jsonify(ok=False, message="Codice scaduto, effettua una nuova scansione"), 403
        return None

    def _check_session_owner(self, data):
        # Distinct from the shared QR token: this identifies which specific
        # phone started the currently-active session, so a second phone that
        # also holds the (shared) token can't jog/stop someone else's session.
        with self._lock:
            current = self._session_secret
        if not current or not manual.token_matches(current, data.get("session")):
            return flask.jsonify(ok=False, message="Sessione di un altro dispositivo"), 403
        return None

    def _send_public_file(self, filename):
        directory = os.path.join(os.path.dirname(__file__), "static_public")
        return flask.send_from_directory(directory, filename)

    def _bounds(self):
        return (
            float(self._settings.get_float(["table_min_x"])),
            float(self._settings.get_float(["table_max_x"])),
            float(self._settings.get_float(["table_min_y"])),
            float(self._settings.get_float(["table_max_y"])),
        )

    def _bounds_dict(self):
        min_x, max_x, min_y, max_y = self._bounds()
        return {"min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y}

    def _stop_manual_session(self):
        with self._lock:
            if not self._manual_active:
                return False
            self._manual_active = False
            paused_by_us = self._paused_by_us
            self._paused_by_us = False
            self._session_secret = None
        if paused_by_us:
            try:
                self._printer.resume_print()
            except Exception:
                self._logger.exception("ManualDraw: failed to resume the paused print")
        self._logger.info("ManualDraw: manual session ended (resumed=%s)", paused_by_us)
        return paused_by_us

    def _watchdog_tick(self):
        with self._lock:
            active = self._manual_active
            last = self._last_jog_ts
        if not active:
            return
        timeout = self._settings.get_float(["watchdog_timeout_seconds"]) or 2.0
        if time.time() - last > timeout:
            self._logger.warning("ManualDraw: watchdog timeout (%ss), ending manual session", timeout)
            self._stop_manual_session()

    # -------------------------------------------------------------- admin API
    def get_api_commands(self):
        return {"regenerate_token": []}

    def on_api_command(self, command, data):
        if command == "regenerate_token":
            self._stop_manual_session()
            self._token = manual.new_token()
            self._settings.set(["token"], self._token)
            self._settings.save()
            return flask.jsonify(ok=True, status=self._status())
        return flask.jsonify(ok=False, message="Unknown command")

    def on_api_get(self, request):
        if request.args.get("qr") is not None:
            return self._qr_png_response()
        return flask.jsonify(self._status())

    def _qr_png_response(self):
        url = flask.request.host_url.rstrip("/") + "/plugin/manualdraw/draw?t=" + self._token
        img = qrcode.make(url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return flask.Response(buf.read(), mimetype="image/png")

    def _status(self):
        with self._lock:
            return {
                "enabled": self._settings.get_boolean(["enabled"]),
                "active": self._manual_active,
                "paused_by_us": self._paused_by_us,
                "current_xy": self._current_xy,
                "last_error": self._last_error,
                "url": flask.request.host_url.rstrip("/") + "/plugin/manualdraw/draw?t=" + self._token,
            }

    # ------------------------------------------------------------ sw update
    def get_update_information(self):
        return {
            "manualdraw": {
                "displayName": "OctoPrint-ManualDraw",
                "displayVersion": self._plugin_version,
                "type": "github_release",
                "user": "montateoo",
                "repo": "OctoPrint-ManualDraw",
                "current": self._plugin_version,
                "pip": "https://github.com/montateoo/OctoPrint-ManualDraw/archive/{target_version}.zip",
            }
        }


__plugin_name__ = "OctoPrint-ManualDraw"
__plugin_pythoncompat__ = ">=3.7,<4"


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = ManualDrawPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
        "octoprint.comm.protocol.gcode.sent": __plugin_implementation__.on_gcode_sent,
    }
