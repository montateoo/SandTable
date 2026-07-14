import setuptools

plugin_identifier = "googlehome"
plugin_package = "octoprint_googlehome"
plugin_name = "OctoPrint-GoogleHome"
plugin_version = "0.1.0"
plugin_description = (
    "Exposes the SandTable as a Google Smart Home device, so Google Home/Nest "
    "Mini can ask what it's drawing and tell it to skip the current pattern."
)
plugin_author = "Matteo"
plugin_author_email = ""
plugin_url = "https://github.com/yourusername/OctoPrint-GoogleHome"
plugin_license = "AGPLv3"
plugin_requires = []


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
