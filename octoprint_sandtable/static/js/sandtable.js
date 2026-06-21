/*
 * OctoPrint-SandTable view model.
 * Drives both the settings panel and the SandTable tab.
 */
$(function () {
    function SandtableViewModel(parameters) {
        var self = this;

        self.settings = parameters[0];
        self.loginState = parameters[1];

        self.running = ko.observable(false);
        self.phase = ko.observable("");
        self.round = ko.observable(0);
        self.rounds = ko.observable(0);
        self.currentFile = ko.observable("");
        self.nextEraser = ko.observable("");
        self.nextDraw = ko.observable("");
        self.eraserCount = ko.observable(0);
        self.drawCount = ko.observable(0);
        self.dryRun = ko.observable(true);
        self.lastError = ko.observable("");
        self.message = ko.observable("");

        self.stateText = ko.pureComputed(function () {
            if (!self.running()) {
                return "Idle";
            }
            var phase = self.phase() || "?";
            return "Running — " + phase + " (round " + (self.round() + 1) + "/" + self.rounds() + ")";
        });

        self.fromResponse = function (data) {
            if (!data) {
                return;
            }
            self.running(!!data.running);
            self.phase(data.phase || "");
            self.round(data.round || 0);
            self.rounds(data.rounds || 0);
            self.currentFile(data.current_file || "");
            self.nextEraser(data.next_eraser || "");
            self.nextDraw(data.next_draw || "");
            self.eraserCount(data.eraser_count || 0);
            self.drawCount(data.draw_count || 0);
            self.dryRun(!!data.dry_run);
            self.lastError(data.last_error || "");
        };

        self.refresh = function () {
            if (!self.loginState.isUser()) {
                return;
            }
            OctoPrint.simpleApiGet("sandtable").done(self.fromResponse);
        };

        self.command = function (cmd, payload) {
            return OctoPrint.simpleApiCommand("sandtable", cmd, payload || {}).done(function (resp) {
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
        self.skip = function () { self.command("skip"); };
        self.testOn = function () { self.command("test_plug", { state: "on" }); };
        self.testOff = function () { self.command("test_plug", { state: "off" }); };
        self.simulate = function () {
            if (confirm("Run the power-off sequence now? (Dry-run is honored.)")) {
                self.command("simulate_complete");
            }
        };

        self.onStartupComplete = function () { self.refresh(); };
        self.onAfterTabChange = function (current) {
            if (current === "#tab_plugin_sandtable") {
                self.refresh();
            }
        };
        self.onDataUpdaterPluginMessage = function (plugin) {
            if (plugin === "sandtable") {
                self.refresh();
            }
        };
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: SandtableViewModel,
        dependencies: ["settingsViewModel", "loginStateViewModel"],
        elements: ["#tab_plugin_sandtable", "#settings_plugin_sandtable"]
    });
});
