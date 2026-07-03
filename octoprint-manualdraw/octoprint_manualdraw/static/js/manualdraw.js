/*
 * OctoPrint-ManualDraw view model.
 * Drives both the settings panel and the ManualDraw tab.
 */
$(function () {
    function ManualDrawViewModel(parameters) {
        var self = this;

        self.settings = parameters[0];
        self.loginState = parameters[1];

        self.enabled = ko.observable(false);
        self.active = ko.observable(false);
        self.pausedByUs = ko.observable(false);
        self.positionXY = ko.observable(null);
        self.lastError = ko.observable("");
        self.url = ko.observable("");
        self.qrBust = ko.observable(Date.now());

        self.qrSrc = ko.pureComputed(function () {
            return "/api/plugin/manualdraw?qr=1&_=" + self.qrBust();
        });

        self.stateText = ko.pureComputed(function () {
            if (!self.active()) {
                return "Idle";
            }
            return self.pausedByUs() ? "In controllo manuale (disegno in pausa)" : "In controllo manuale";
        });

        self.positionText = ko.pureComputed(function () {
            var xy = self.positionXY();
            if (!xy) {
                return "—";
            }
            return xy[0].toFixed(1) + ", " + xy[1].toFixed(1);
        });

        self.fromResponse = function (data) {
            if (!data) {
                return;
            }
            self.enabled(!!data.enabled);
            self.active(!!data.active);
            self.pausedByUs(!!data.paused_by_us);
            self.positionXY(data.current_xy || null);
            self.lastError(data.last_error || "");
            self.url(data.url || "");
        };

        self.refresh = function () {
            if (!self.loginState.isUser()) {
                return;
            }
            OctoPrint.simpleApiGet("manualdraw").done(self.fromResponse);
        };

        self.regenerate = function () {
            OctoPrint.simpleApiCommand("manualdraw", "regenerate_token").done(function (resp) {
                if (resp && resp.status) {
                    self.fromResponse(resp.status);
                }
                self.qrBust(Date.now());
            });
        };

        self.onStartupComplete = function () { self.refresh(); };
        self.onAfterTabChange = function (current) {
            if (current === "#tab_plugin_manualdraw") {
                self.refresh();
            }
        };
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: ManualDrawViewModel,
        dependencies: ["settingsViewModel", "loginStateViewModel"],
        elements: ["#tab_plugin_manualdraw"]
    });
});
