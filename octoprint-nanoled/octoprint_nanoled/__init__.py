# coding=utf-8
"""OctoPrint-NanoLED: serial interface to the under-table WS2812FX LED strip.

Owns the serial connection to the Arduino Nano (LED-Arduino/LED-Control/LED-Control.ino) and
exposes a small command API (set_pattern, set_solid, flicker_rainbow, flash_white) -- used by this
plugin's own manual-control tab, and callable directly, in-process, by other OctoPrint plugins via
`self._plugin_manager.get_plugin("nanoled", True)` (octoprint-f1sisyphus uses this for race-flag-
reactive lighting).
"""

from __future__ import absolute_import

import flask

import octoprint.plugin

from . import nano


class NanoLEDPlugin(
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.SimpleApiPlugin,
):
    def initialize(self):
        self._nano = None

    # --------------------------------------------------------------- settings
    def get_settings_defaults(self):
        return dict(enabled=False, serial_port="", baud_rate=nano.DEFAULT_BAUD_RATE)

    def get_assets(self):
        return dict(js=["js/nanoled.js"], css=["css/nanoled.css"])

    def get_template_configs(self):
        return [
            dict(type="settings", custom_bindings=True),
            dict(type="tab", custom_bindings=True),
        ]

    # ------------------------------------------------------------------ nano
    def _get_nano(self):
        if not self._settings.get_boolean(["enabled"]):
            return None
        if self._nano is None:
            try:
                self._nano = nano.NanoClient(
                    self._settings.get(["serial_port"]),
                    baud_rate=self._settings.get_int(["baud_rate"]),
                )
            except nano.NanoError as exc:
                self._logger.warning("NanoLED: %s", exc)
                return None
        return self._nano

    def _send(self, method_name, *args):
        client = self._get_nano()
        if client is None:
            return False
        try:
            getattr(client, method_name)(*args)
            return True
        except nano.NanoError as exc:
            self._logger.warning("NanoLED: %s failed: %s", method_name, exc)
            return False

    def set_pattern(self, n):
        """n: 0-10. Returns True on success, False if disabled/unconfigured/failed."""
        return self._send("set_pattern", n)

    def set_solid(self, color_name):
        """color_name: RED, YELLOW, GREEN, or WHITE."""
        return self._send("set_solid", color_name)

    def flicker_rainbow(self):
        return self._send("flicker_rainbow")

    def flash_white(self):
        return self._send("flash_white")

    # -------------------------------------------------------------- simple api
    def get_api_commands(self):
        return dict(set_pattern=["n"], set_solid=["color"], flicker_rainbow=[], flash_white=[])

    def on_api_command(self, command, data):
        data = data or {}
        if command == "set_pattern":
            return flask.jsonify(ok=self.set_pattern(data.get("n")))
        if command == "set_solid":
            return flask.jsonify(ok=self.set_solid(data.get("color")))
        if command == "flicker_rainbow":
            return flask.jsonify(ok=self.flicker_rainbow())
        if command == "flash_white":
            return flask.jsonify(ok=self.flash_white())
        return flask.jsonify(ok=False, message="Unknown command")


__plugin_name__ = "NanoLED"
__plugin_pythoncompat__ = ">=3.7,<4"


def __plugin_load__():
    plugin = NanoLEDPlugin()

    global __plugin_implementation__
    __plugin_implementation__ = plugin

    # Exposed so other plugins (octoprint-f1sisyphus) can drive the LEDs directly,
    # in-process, via self._plugin_manager.get_helpers("nanoled", ...) -- see
    # https://docs.octoprint.org/en/main/plugins/helpers.html
    global __plugin_helpers__
    __plugin_helpers__ = dict(
        set_pattern=plugin.set_pattern,
        set_solid=plugin.set_solid,
        flicker_rainbow=plugin.flicker_rainbow,
        flash_white=plugin.flash_white,
    )
