#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the full release suite and fail if any real-QGIS tests are skipped."""
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from qgis.core import Qgis
    from osgeo import gdal
    from layer_eraser.plugin import LayerEraserPlugin
except ImportError as error:
    sys.exit("Use QGIS' Python environment for release validation: " + str(error))

print("QGIS:", Qgis.QGIS_VERSION, flush=True)
print("GDAL:", gdal.VersionInfo("--version"), flush=True)
suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
result = unittest.TextTestRunner(verbosity=2).run(suite)
if result.skipped:
    print("Release validation failed: real-runtime tests were skipped.", file=sys.stderr)
sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
