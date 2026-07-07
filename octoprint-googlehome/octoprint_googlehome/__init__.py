# coding=utf-8
"""OctoPrint-GoogleHome: exposes the SandTable as a Google Smart Home device.

Single-household simplification throughout: there's no real user database.
Account linking auto-approves (this household is the only "user"), and the
OAuth token endpoint always issues the one static long-lived token configured
in settings, for both the authorization_code and refresh_token grant types.

Reads f1sisyphus/sandtable status and triggers sandtable's skip in-process via
OctoPrint's plugin helpers mechanism (the same pattern f1sisyphus already uses
to drive nanoled) -- see _get_f1sisyphus()/_get_sandtable() below.
"""

from __future__ import absolute_import

import flask

import octoprint.plugin

from . import smarthome


class GoogleHomePlugin(
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.BlueprintPlugin,
):
    # ------------------------------------------------------------------ setup
    def initialize(self):
        self._f1sisyphus_helpers = None
        self._sandtable_helpers = None
        self._nanoled_helpers = None

    def _get_f1sisyphus(self):
        if self._f1sisyphus_helpers is None:
            helpers = self._plugin_manager.get_helpers("f1sisyphus", "get_status")
            if not helpers:
                return None
            self._f1sisyphus_helpers = helpers
        return self._f1sisyphus_helpers

    def _get_sandtable(self):
        if self._sandtable_helpers is None:
            helpers = self._plugin_manager.get_helpers("sandtable", "get_status", "skip_current")
            if not helpers:
                return None
            self._sandtable_helpers = helpers
        return self._sandtable_helpers

    def _get_nanoled(self):
        if self._nanoled_helpers is None:
            helpers = self._plugin_manager.get_helpers("nanoled", "next_pattern")
            if not helpers:
                return None
            self._nanoled_helpers = helpers
        return self._nanoled_helpers

    def _next_led_pattern(self):
        nanoled = self._get_nanoled()
        if not nanoled:
            return False
        try:
            return nanoled["next_pattern"]()
        except Exception:
            return False

    # ------------------------------------------------------------- activity
    def _current_activity(self):
        """F1 takes priority over SandTable when both could be 'active' -- when
        f1sisyphus is tracking/drawing a race it owns the table, the same
        assumption the nanoled integration already makes."""
        f1 = self._get_f1sisyphus()
        if f1:
            try:
                status = f1["get_status"]()
            except Exception:
                status = None
            if status and status.get("phase") in ("draw_circuit", "wait_for_live", "tracking"):
                return smarthome.ACTIVITY_GARA

        sandtable = self._get_sandtable()
        if sandtable:
            try:
                status = sandtable["get_status"]()
            except Exception:
                status = None
            if status and status.get("running"):
                if status.get("phase") == "eraser":
                    return smarthome.ACTIVITY_PULIZIA
                return smarthome.ACTIVITY_DISEGNO

        return smarthome.ACTIVITY_RIPOSO

    def _skip(self):
        """Returns (bool success, str message). Only meaningful while sandtable
        owns the table -- f1sisyphus has no skip concept, so this is a no-op
        (not an error) if f1 currently owns the table instead."""
        if self._current_activity() == smarthome.ACTIVITY_GARA:
            return False, "F1 tracking is active; nothing to skip"
        sandtable = self._get_sandtable()
        if not sandtable:
            return False, "SandTable plugin isn't available"
        return sandtable["skip_current"]()

    # --------------------------------------------------------------- settings
    def get_settings_defaults(self):
        return dict(
            client_id="",
            client_secret="",
            static_token="",
            device_name="Tavolo",
        )

    def get_settings_restricted_paths(self):
        return dict(admin=[["client_secret"], ["static_token"]])

    # -------------------------------------------------------------- assets/ui
    def get_template_configs(self):
        return [dict(type="settings", custom_bindings=True)]

    def get_assets(self):
        return dict(js=["js/googlehome.js"])

    # ------------------------------------------------------------- blueprint
    def _check_client(self, client_id, client_secret=None):
        if client_id != self._settings.get(["client_id"]):
            return False
        if client_secret is not None and client_secret != self._settings.get(["client_secret"]):
            return False
        return True

    def _check_bearer_token(self):
        auth = flask.request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        return token and token == self._settings.get(["static_token"])

    @octoprint.plugin.BlueprintPlugin.route("/oauth2/authorize", methods=["GET"])
    def oauth_authorize(self):
        client_id = flask.request.args.get("client_id", "")
        redirect_uri = flask.request.args.get("redirect_uri", "")
        state = flask.request.args.get("state", "")
        if not self._check_client(client_id) or not redirect_uri:
            return flask.abort(400)
        # Single-household shortcut: auto-approve, no login form. The "code" is
        # never actually validated for authenticity at /oauth2/token below --
        # it only matters that *some* code round-trips, since the token issued
        # is always the one static_token regardless.
        return flask.redirect("{}?code=linked&state={}".format(redirect_uri, state))

    @octoprint.plugin.BlueprintPlugin.route("/oauth2/token", methods=["POST"])
    def oauth_token(self):
        form = flask.request.form
        if not self._check_client(form.get("client_id", ""), form.get("client_secret", "")):
            return flask.jsonify(error="invalid_client"), 401
        if form.get("grant_type") not in ("authorization_code", "refresh_token"):
            return flask.jsonify(error="unsupported_grant_type"), 400
        token = self._settings.get(["static_token"])
        return flask.jsonify(
            token_type="Bearer",
            access_token=token,
            refresh_token=token,
            expires_in=31536000,
        )

    @octoprint.plugin.BlueprintPlugin.route("/smarthome", methods=["POST"])
    def smarthome_fulfillment(self):
        if not self._check_bearer_token():
            return flask.jsonify(error="invalid_token"), 401

        body = flask.request.get_json(silent=True) or {}
        request_id = body.get("requestId", "")
        inputs = body.get("inputs", [])
        intent = inputs[0].get("intent") if inputs else None

        if intent == "action.devices.SYNC":
            return flask.jsonify(
                smarthome.build_sync_response(request_id, self._settings.get(["device_name"]))
            )
        if intent == "action.devices.QUERY":
            devices = inputs[0].get("payload", {}).get("devices", [])
            activity = self._current_activity()
            mapping = {d["id"]: activity for d in devices}
            return flask.jsonify(smarthome.build_query_response(request_id, mapping))
        if intent == "action.devices.EXECUTE":
            commands = inputs[0].get("payload", {}).get("commands", [])
            return flask.jsonify(
                smarthome.build_execute_response(request_id, commands, self._skip, self._current_activity, self._next_led_pattern)
            )

        return flask.jsonify(requestId=request_id, payload={}), 400

    def is_blueprint_csrf_protected(self):
        return False

    def is_blueprint_protected(self):
        # Google will never have an OctoPrint login session/API key -- only our
        # own Bearer static_token (checked explicitly in each route above).
        return False


__plugin_name__ = "Google Home"
__plugin_pythoncompat__ = ">=3.7,<4"


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = GoogleHomePlugin()
