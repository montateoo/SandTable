import setuptools

plugin_identifier = "f1sisyphus"
plugin_package = "octoprint_f1sisyphus"
plugin_name = "OctoPrint-F1Sisyphus"
plugin_version = "0.1.0"
plugin_description = (
    "Traces your favourite F1 driver's live on-track position onto a Sisyphus "
    "sand table during race weekends, using the OpenF1 API."
)
plugin_author = "Matteo"
plugin_author_email = ""
plugin_url = "https://github.com/yourusername/OctoPrint-F1Sisyphus"
plugin_license = "AGPLv3"
plugin_requires = ["requests"]


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
