# coding=utf-8
"""Setup for the OctoPrint-SandTable plugin."""

########################################################################################################################
plugin_identifier = "sandtable"
plugin_package = "octoprint_sandtable"
plugin_name = "OctoPrint-SandTable"
plugin_version = "0.1.1"
plugin_description = (
    "Turns a Sisyphus-style sand table into an autonomous appliance: runs N rounds of "
    "ERASER -> DRAW (round-robin from two folders), then cuts power via a local smart plug. "
    "An external schedule wakes it and the plugin auto-resumes on boot."
)
plugin_author = "montateoo"
plugin_author_email = "monta.m2001@gmail.com"
plugin_url = "https://github.com/montateoo/OctoPrint-SandTable"
plugin_license = "AGPLv3"

# Only needed for the bundled Kasa driver. Everything else uses requests (bundled with OctoPrint).
plugin_requires = []
plugin_extras = {"kasa": ["python-kasa>=0.5.0"]}

plugin_additional_data = []
plugin_additional_packages = []
plugin_ignored_packages = []
additional_setup_parameters = {}
########################################################################################################################

from setuptools import setup

try:
    import octoprint_setuptools
except ImportError:
    print(
        "Could not import OctoPrint's setuptools, are you sure you are running that under "
        "the same python installation that OctoPrint is installed under?"
    )
    import sys

    sys.exit(-1)

setup_parameters = octoprint_setuptools.create_plugin_setup_parameters(
    identifier=plugin_identifier,
    package=plugin_package,
    name=plugin_name,
    version=plugin_version,
    description=plugin_description,
    author=plugin_author,
    mail=plugin_author_email,
    url=plugin_url,
    license=plugin_license,
    requires=plugin_requires,
    extra_requires=plugin_extras,
    additional_packages=plugin_additional_packages,
    ignored_packages=plugin_ignored_packages,
    additional_data=plugin_additional_data,
)

if len(additional_setup_parameters):
    from octoprint.util import dict_merge

    setup_parameters = dict_merge(setup_parameters, additional_setup_parameters)

setup(**setup_parameters)
