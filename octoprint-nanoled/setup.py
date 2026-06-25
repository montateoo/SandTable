import setuptools

plugin_identifier = "nanoled"
plugin_package = "octoprint_nanoled"
plugin_name = "OctoPrint-NanoLED"
plugin_version = "0.1.0"
plugin_description = (
    "Drives the Sisyphus table's under-surface WS2812FX LED strip (via an Arduino Nano "
    "over serial), with manual pattern control plus an optional F1-race-flag-reactive mode."
)
plugin_author = "Matteo"
plugin_author_email = ""
plugin_url = "https://github.com/yourusername/OctoPrint-NanoLED"
plugin_license = "AGPLv3"
plugin_requires = ["pyserial"]


def params():
    return dict(
        name=plugin_name,
        version=plugin_version,
        description=plugin_description,
        author=plugin_author,
        author_email=plugin_author_email,
        url=plugin_url,
        license=plugin_license,
        packages=[plugin_package],
        package_data={
            plugin_package: [
                "templates/*.jinja2",
                "static/css/*.css",
                "static/js/*.js",
            ]
        },
        include_package_data=True,
        zip_safe=False,
        install_requires=plugin_requires,
        entry_points={
            "octoprint.plugin": [
                "{} = {}".format(plugin_identifier, plugin_package)
            ]
        },
    )


setuptools.setup(**params())
