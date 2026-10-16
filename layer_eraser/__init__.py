# SPDX-License-Identifier: GPL-3.0-or-later
"""Layer Eraser — QGIS plugin entry point."""


def classFactory(iface):
    from .plugin import LayerEraserPlugin
    return LayerEraserPlugin(iface)
