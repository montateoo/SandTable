/*
 * OctoPrint-GoogleHome view model.
 * Settings-only -- no tab, this plugin has no manual UI of its own, it's
 * purely a fulfillment backend for Google's Smart Home Action.
 */
$(function () {
    function GoogleHomeViewModel(parameters) {
        var self = this;
        self.settings = parameters[0];
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: GoogleHomeViewModel,
        dependencies: ["settingsViewModel"],
        elements: ["#settings_plugin_googlehome"],
    });
});
