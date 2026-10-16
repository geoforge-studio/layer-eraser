#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the full release suite and fail if any real-QGIS tests are skipped."""
import argparse
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from qgis.core import Qgis
    from qgis.PyQt.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
    from osgeo import gdal
    from layer_eraser.plugin import LayerEraserPlugin
except ImportError as error:
    sys.exit("Use QGIS' Python environment for release validation: " + str(error))

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--expect-qgis', help='Required major.minor QGIS series, e.g. 4.0')
parser.add_argument('--expect-qt', help='Required Qt major version, e.g. 6')
args = parser.parse_args()
print("QGIS:", Qgis.QGIS_VERSION, flush=True)
print("GDAL:", gdal.VersionInfo("--version"), flush=True)
print("Qt:", QT_VERSION_STR, "PyQt:", PYQT_VERSION_STR, flush=True)
if args.expect_qgis and not Qgis.QGIS_VERSION.startswith(args.expect_qgis + '.'):
    sys.exit('Unexpected QGIS series: ' + Qgis.QGIS_VERSION)
if args.expect_qt and QT_VERSION_STR.split('.')[0] != args.expect_qt:
    sys.exit('Unexpected Qt version: ' + QT_VERSION_STR)
suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
result = unittest.TextTestRunner(verbosity=2).run(suite)
if result.skipped:
    print("Release validation failed: real-runtime tests were skipped.", file=sys.stderr)
sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
