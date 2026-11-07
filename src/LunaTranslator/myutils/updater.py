"""This personal fork is updated explicitly through Git and local deployment.

Keep the two application entrypoints so startup and shutdown remain compatible.
Neither entrypoint queries upstream, downloads packages, or installs cached ones.
"""


def versioncheckthread():
    import gobject
    from myutils.config import globalconfig

    globalconfig["autoupdate"] = False
    gobject.base.update_avalable = False


def doupdate():
    # Old configuration and cached upstream packages cannot trigger installation.
    versioncheckthread()
