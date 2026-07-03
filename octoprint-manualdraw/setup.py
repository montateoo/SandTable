import setuptools

plugin_identifier = "manualdraw"
plugin_package = "octoprint_manualdraw"
plugin_name = "OctoPrint-ManualDraw"
plugin_version = "0.1.0"
plugin_description = (
    "Scan a QR code next to the table to pause whatever it's drawing and take direct, "
    "real-time control of the ball via your phone's tilt -- release to resume."
)
plugin_author = "Matteo"
plugin_author_email = "monta.m2001@gmail.com"
plugin_url = "https://github.com/montateoo/OctoPrint-ManualDraw"
plugin_license = "AGPLv3"
plugin_requires = ["qrcode[pil]"]


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
                "static_public/*",
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
