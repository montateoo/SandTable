/*
 * OctoPrint-F1Sisyphus view model.
 * Drives both the settings panel and the F1 Sisyphus tab.
 */
$(function () {
    function F1SisyphusViewModel(parameters) {
        var self = this;

        self.settings = parameters[0];
        self.loginState = parameters[1];

        self.phase = ko.observable("idle");
        self.upcomingSession = ko.observable(null);
        self.pointsDrawn = ko.observable(0);
        self.lastTrackX = ko.observable("-");
        self.lastTrackY = ko.observable("-");
        self.dryRun = ko.observable(true);
        self.lastError = ko.observable("");
        self.nextScheduledRace = ko.observable(null);
        self.message = ko.observable("");

        self.running = ko.pureComputed(function () {
            return self.phase() !== "idle";
        });

        self.stateText = ko.pureComputed(function () {
            if (!self.running()) {
                return "Idle";
            }
            return "Running — " + self.phase();
        });

        self.upcomingLabel = ko.pureComputed(function () {
            var s = self.upcomingSession();
            if (!s) {
                return "—";
            }
            var bits = [];
            if (s.country_name) { bits.push(s.country_name); }
            if (s.date_start) { bits.push(s.date_start); }
            return bits.length ? bits.join(" — ") : "—";
        });

        self.nextRaceLabel = ko.pureComputed(function () {
            var r = self.nextScheduledRace();
            if (!r) {
                return "—";
            }
            var bits = [];
            if (r.country_name) { bits.push(r.country_name); }
            if (r.date_start) { bits.push(r.date_start); }
            return bits.length ? bits.join(" — ") : "—";
        });

        self.fromResponse = function (data) {
            if (!data) {
                return;
            }
            self.phase(data.phase || "idle");
            self.upcomingSession(data.upcoming_session || null);
            self.pointsDrawn(data.points_drawn || 0);
            if (data.last_table_pos) {
                self.lastTrackX(data.last_table_pos[0].toFixed(1));
                self.lastTrackY(data.last_table_pos[1].toFixed(1));
            }
            self.dryRun(!!data.dry_run);
            self.lastError(data.last_error || "");
            self.nextScheduledRace(data.next_scheduled_race || null);
        };

        self.refresh = function () {
            if (!self.loginState.isUser()) {
                return;
            }
            OctoPrint.simpleApiGet("f1sisyphus").done(self.fromResponse);
        };

        self.command = function (cmd, payload) {
            return OctoPrint.simpleApiCommand("f1sisyphus", cmd, payload || {}).done(function (resp) {
                if (resp && resp.message) {
                    self.message(resp.message);
                }
                if (resp && resp.status) {
                    self.fromResponse(resp.status);
                } else {
                    self.refresh();
                }
            });
        };

        self.start = function () { self.command("start"); };
        self.stop = function () { self.command("stop"); };
        self.testOn = function () { self.command("test_plug", { state: "on" }); };
        self.testOff = function () { self.command("test_plug", { state: "off" }); };
        self.simulateComplete = function () {
            if (confirm("Run the reschedule + power-off sequence now? (Dry-run is honored.)")) {
                self.command("simulate_complete");
            }
        };
        self.rescheduleNow = function () { self.command("reschedule_now"); };

        self.onStartupComplete = function () { self.refresh(); };
        self.onAfterTabChange = function (current) {
            if (current === "#tab_plugin_f1sisyphus") {
                self.refresh();
            }
        };
        self.onDataUpdaterPluginMessage = function (plugin, data) {
            if (plugin !== "f1sisyphus") {
                return;
            }
            if (data.type === "position") {
                self.lastTrackX(data.table_x.toFixed(1));
                self.lastTrackY(data.table_y.toFixed(1));
                self.pointsDrawn(data.points_drawn);
            }
        };
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: F1SisyphusViewModel,
        dependencies: ["settingsViewModel", "loginStateViewModel"],
        elements: ["#tab_plugin_f1sisyphus", "#settings_plugin_f1sisyphus"],
    });
});
