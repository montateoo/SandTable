/*
 * OctoPrint-NanoLED view model.
 * Drives both the settings panel and the manual-control tab.
 */
$(function () {
    function NanoLEDViewModel(parameters) {
        var self = this;

        self.settings = parameters[0];
        self.loginState = parameters[1];

        self.message = ko.observable("");

        self.command = function (cmd, payload) {
            return OctoPrint.simpleApiCommand("nanoled", cmd, payload || {}).done(function (resp) {
                self.message(resp && resp.ok ? "OK" : "Failed (check it's enabled + serial_port is set)");
            });
        };

        self.setPattern = function (n) { self.command("set_pattern", { n: n }); };
        self.setSolid = function (color) { self.command("set_solid", { color: color }); };
        self.flickerRainbow = function () { self.command("flicker_rainbow"); };
        self.flashWhite = function () { self.command("flash_white"); };

        self.patterns = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: NanoLEDViewModel,
        dependencies: ["settingsViewModel", "loginStateViewModel"],
        elements: ["#tab_plugin_nanoled", "#settings_plugin_nanoled"],
    });
});
