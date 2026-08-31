# Copyright (c) 2026 LG Electronics Inc.

SUMMARY = "{COMPONENT_NAME} service for webOS"
DESCRIPTION = "{DESCRIPTION}"
AUTHOR = "LG Electronics"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://LICENSE;md5=PLACEHOLDER_UPDATE_WITH_REAL_MD5"

# Source
SRC_URI = "git://wall.lge.com/starfish/{COMPONENT_NAME}.git;protocol=ssh;branch=master"
SRCREV = "${AUTOREV}"
S = "${WORKDIR}/git"

# Dependencies
DEPENDS = "cmake-native virtual/kernel"
RDEPENDS_${PN} = ""

# Build
inherit cmake

EXTRA_OECMAKE = ""

do_install_append() {
    # Install service files
    install -d ${D}${sbindir}
    install -m 0755 ${B}/{COMPONENT_NAME} ${D}${sbindir}/
}

# Packaging
FILES_${PN} += "${sbindir}/{COMPONENT_NAME}"
