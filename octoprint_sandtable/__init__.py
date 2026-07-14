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
        self._stop_dedup_key = None
        self._last_error = None
        self._autostart_inflight = False
        self._pausing = False
        self._recover_attempts = 0
        self._stop_complete = threading.Event()
        self._stop_complete.set()  # nothing in-flight until a skip clears it

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
            "post_draw_pause_seconds": 300,  # wait this long after each draw before eraser/power-off
            "program_wake": False,       # future: program the plug's wake timer
            "wake_mode": "after_hours",
            "wake_value": "8",
            "auto_recover": True,        # reconnect + retry after a communication death
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
                    r = int(rounds_override)
                    self._rounds = 0 if r <= 0 else max(1, r)  # 0 = unlimited (until stopped)
                except (TypeError, ValueError):
                    self._rounds = max(1, self._settings.get_int(["rounds"]) or 1)
            else:
                self._rounds = max(1, self._settings.get_int(["rounds"]) or 1)
            self._round = 0
            self._phase = None
            self._current_path = None
            self._skip = False
            self._last_error = None
            self._recover_attempts = 0
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
            self._printer.commands("!", force=True)
            self._printer.cancel_print()
            self._wait_until_not_printing(timeout=10)
            self._immediate_stop()
        self._logger.info("SandTable: cycle stopped by request")
        return was_running

    def skip_current(self):
        with self._lock:
            if not self._running:
                return False, "Cycle is not running"
            if self._skip:
                return True, "Already skipping"
            if self._pausing:
                self._skip = True  # _pause_between() will see this and exit early
                return True, "Skipping pause"
            if not self._printer.is_printing():
                return False, "Nothing is printing to skip"
            self._skip = True
            self._stop_complete.clear()
        self._printer.commands("!", force=True)  # best-effort immediate feed-hold request
        self._printer.cancel_print()
        # OctoPrint's serial writer serializes ALL sends (including force=True
        # ones) through one lock shared with the active file-streamer -- so
        # our commands don't actually jump the queue, they just wait their
        # turn behind whatever the streamer is still pushing until
        # cancel_print() genuinely stops it. Confirmed empirically: our '!'
        # and '\x18' showed up in serial.log milliseconds apart despite a
        # 3s Python-level sleep between them, because both calls sat queued
        # behind the same backlog and only got serviced once that cleared --
        # the sleep elapsed while blocked, not while GRBL was decelerating.
        # Wait for is_printing() to actually go False before doing anything
        # timing-sensitive, so the channel is genuinely free and our sleep
        # in _immediate_stop() means what it says.
        self._wait_until_not_printing(timeout=10)
        self._immediate_stop()
        self._stop_complete.set()
        return True, "Skipping current pattern"

    def _wait_until_not_printing(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline and self._printer.is_printing():
            time.sleep(0.1)

    def _immediate_stop(self):
        """Reset GRBL to a clean Idle state after skip_current() has already
        sent '!' (feed hold) and confirmed via is_printing()==False that
        OctoPrint's file-streamer has genuinely stopped competing for the
        serial channel (see the comment there for why that confirmation
        matters -- force=True does not give realtime commands priority over
        an active stream; they share the same send lock).

        With the channel now free, this sleep is real physical settle time,
        not queueing delay: the fastest feedrate anything in this codebase
        uses is 6000 mm/min (100 mm/s, manualdraw's jog_feedrate) and GRBL's
        configured acceleration is 50 mm/s^2 ($120/$121), so worst-case
        stop-from-full-speed takes 100/50 = 2.0s; 3.0s leaves a full second
        of margin. Soft-resetting GRBL while it's still physically
        decelerating trips Grbl ALARM:3 ("Reset while in motion ... lost
        steps are likely"), which then makes GRBL reject every G-code line
        the streamer sends with "error:9 G-code lock" until unlocked --
        that's the failure mode this wait exists to avoid.

        '\\x18' (soft reset) cleanly drops GRBL back to Idle. It also wipes
        GRBL's modal feedrate: most of our gcode files never set their own F
        (they've always relied on whatever F was left over from the previous
        job -- true for every job until this reset existed), so '$X'
        (unlock -- harmless no-op if no alarm was raised) is followed by an
        explicit 'G1 F2000' to re-arm a safe default. Without it, the next
        file printed would have every line rejected with "error:22 Undefined
        feed rate": nothing moves, which looks exactly like a crash but isn't
        one.
        """
        try:
            time.sleep(3.0)
            self._printer.commands("\x18", force=True)
            time.sleep(0.5)
            self._printer.commands("$X", force=True)
            time.sleep(0.2)
            self._printer.commands("G1 F2000", force=True)
        except Exception:
            self._logger.exception("SandTable: immediate stop failed")

    # --------------------------------------------------------- event handlers
    def _handle_print_done(self, payload, skip_pause=False):
        with self._lock:
            if not self._running:
                return
            if not self._is_our_print(payload):
                self._logger.debug("SandTable: ignoring PrintDone for a non-managed file")
                return
            self._recover_attempts = 0  # a completed print clears the recovery counter
            action, next_phase, next_round = cycle.advance(self._phase, self._round, self._rounds)
            self._round = next_round
            self._phase = next_phase

        if skip_pause:
            # This event is delivered on OctoPrint's event-worker thread,
            # concurrently with skip_current()'s own thread still running
            # cancel_print() + _immediate_stop() (feed-hold, wait for the
            # ball to physically stop, soft-reset, unlock, restore feedrate).
            # Without waiting here, we've on occasion gotten far enough to
            # select and start the *next* file while that reset was still
            # in-flight -- the new file's G1 lines arrive while GRBL is mid-
            # reset/alarm and every one bounces off with "error:9 G-code
            # lock". Block until the other thread signals it's genuinely
            # done before touching the printer again.
            self._stop_complete.wait(timeout=10)
        elif action in (cycle.ACTION_PRINT_ERASER, cycle.ACTION_COMPLETE):
            # After a draw, pause before the next eraser or the final power-
            # off -- but only for a *naturally finished* drawing. A manual
            # skip already means the user wants the table to move on now,
            # not sit idle for post_draw_pause_seconds.
            pause = self._settings.get_int(["post_draw_pause_seconds"]) or 0
            self._pause_between(pause)
            with self._lock:
                if not self._running:
                    return  # cycle was stopped during the pause

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
        # A single cancel emits BOTH a PrintCancelled and a PrintFailed(reason=
        # "cancelled") event. Without de-duping, the first consumes the skip flag
        # and advances the cycle, then the twin event sees skip already cleared,
        # mis-reads it as a spontaneous failure, and kills the cycle (running=
        # False) -- the table draws one more pattern then silently stops. Key off
        # the stopped file so only the first of the pair is acted on; the key is
        # re-armed in _print_file when the next print actually starts.
        stop_key = (payload or {}).get("path") or (payload or {}).get("name") or self._current_path
        with self._lock:
            if stop_key is not None and stop_key == self._stop_dedup_key:
                return
            self._stop_dedup_key = stop_key
            running = self._running
            skipping = self._skip
            if skipping:
                self._skip = False
        if not running:
            return
        if skipping:
            # We cancelled on purpose to skip the current pattern -> advance
            # immediately, bypassing the post-draw pause (that pause is for
            # letting a *naturally finished* drawing sit before the eraser
            # wipes it -- a manual skip means the user wants to move on now).
            self._handle_print_done(payload, skip_pause=True)
            return
        reason = (payload or {}).get("reason", "")
        label = "print {} {}".format(event, reason).strip()
        if event == Events.PRINT_CANCELLED or reason == "cancelled":
            # Deliberate cancel from the UI (not a malfunction) -> respect it.
            self._stop_with_error(label)
            return
        if not self._settings.get_boolean(["auto_recover"]):
            self._stop_with_error(label)
            return
        self._attempt_recovery(label)

    def _attempt_recovery(self, reason):
        """Self-heal after a communication death (GRBL freeze -> 'Offline after
        error'). Reconnecting reopens the serial port, which auto-resets the
        controller and unfreezes it; then the failed file is restarted. Gives
        up after 3 consecutive failures of the same file so a persistent
        hardware fault still surfaces instead of retrying forever."""
        with self._lock:
            if not self._running:
                return
            self._recover_attempts += 1
            attempt = self._recover_attempts
            path = self._current_path
        if attempt > 3:
            self._stop_with_error("giving up after 3 recovery attempts: {}".format(reason))
            return
        self._logger.warning(
            "SandTable: %s -- recovery attempt %d/3, reconnecting to reset the controller",
            reason, attempt,
        )
        try:
            self._printer.disconnect()
        except Exception:
            pass
        time.sleep(5)
        try:
            self._printer.connect()
        except Exception:
            self._logger.exception("SandTable: reconnect failed during recovery")
        if not self._wait_ready(timeout=120):
            self._stop_with_error(
                "printer did not come back after recovery reconnect ({})".format(reason)
            )
            return
        with self._lock:
            if not self._running:
                return
        if path is None:
            self._stop_with_error("recovery aborted: no file to restart")
            return
        try:
            self._logger.info("SandTable: recovered, restarting %s", path)
            self._print_file(path)
        except (CycleError, ValueError, PlugError) as exc:
            self._stop_with_error(str(exc))

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
        with self._lock:
            self._current_path = path
            # Re-arm stop de-dup for this fresh print. Safe against the twin-event
            # race: the duplicate stop arrives within ms of the first, well before
            # _wait_ready (>=0.5s) lets us reach here for the next print.
            self._stop_dedup_key = None
        rounds_label = "unlimited" if self._rounds <= 0 else str(self._rounds)
        self._logger.info(
            "SandTable: printing %s (%s, round %d/%s)",
            path, self._phase, self._round + 1, rounds_label,
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
    def _pause_between(self, seconds):
        """Wait between the end of a draw and the next eraser / power-off.
        Exits early if stop_cycle() is called or skip_current() sets _skip."""
        if seconds <= 0:
            return
        with self._lock:
            self._pausing = True
        self._logger.info("SandTable: pausing %ds after draw", seconds)
        deadline = time.time() + seconds
        while time.time() < deadline:
            with self._lock:
                if not self._running or self._skip:
                    break
            time.sleep(1)
        with self._lock:
            self._skip = False  # consume skip so the next print starts clean
            self._pausing = False

    def _wait_ready(self, timeout=90, _idle_stable_secs=2.0):
        """Wait until the printer is operational and GRBL's planner is empty.

        OctoPrint reports 'Operational' (is_operational()==True) when GRBL
        sends an <Idle> status response -- but a single <Idle> can be a brief
        transient while the planner drains the last segment. We require the
        printer to hold the Operational state continuously for _idle_stable_secs
        before starting the next file, which in practice means GRBL's motion
        buffer is truly empty and the first G1 command won't time out.
        """
        deadline = time.time() + timeout
        reconnect_at = time.time() + 20
        reconnected = False
        idle_since = None

        while time.time() < deadline:
            is_ready = (
                self._printer.is_operational()
                and not self._printer.is_printing()
                and not self._printer.is_paused()
            )
            if is_ready:
                if idle_since is None:
                    idle_since = time.time()
                elif time.time() - idle_since >= _idle_stable_secs:
                    return True  # GRBL held Idle for _idle_stable_secs → buffer empty
            else:
                idle_since = None  # dropped out of Idle — reset the stability timer

            # If the printer is stuck (e.g. OctoPrint in "Finishing" because
            # GRBL stopped responding at end-of-job), one reconnect resets it.
            if not reconnected and time.time() >= reconnect_at:
                reconnected = True
                self._logger.warning(
                    "SandTable: printer not ready after 20s; reconnecting to clear stuck state"
                )
                try:
                    self._printer.disconnect()
                    time.sleep(2)
                    self._printer.connect()
                    time.sleep(8)
                except Exception:
                    self._logger.exception("SandTable: reconnect attempt failed")
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
            pausing = self._pausing
        return {
            "running": running,
            "phase": phase,
            "pausing": pausing,
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

    def get_status(self):
        """Exposed via __plugin_helpers__ so other plugins (octoprint-googlehome)
        can read cycle phase/running state in-process."""
        return self._status()

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

    # Exposed so octoprint-googlehome can read status / trigger skip in-process,
    # the same helpers pattern used between f1sisyphus and nanoled -- see
    # https://docs.octoprint.org/en/main/plugins/helpers.html
    global __plugin_helpers__
    __plugin_helpers__ = dict(
        get_status=__plugin_implementation__.get_status,
        skip_current=__plugin_implementation__.skip_current,
    )
