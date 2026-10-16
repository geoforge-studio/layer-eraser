# Validation report — Layer Eraser 0.2.1

Date: 2026-10-16.

## Actual execution environment

- Ubuntu 24.04, Linux x86_64.
- QGIS **3.34.4-Prizren**, with real PyQGIS providers and widgets.
- GDAL **3.8.4**, using real GPKG, Shapefile and GeoJSON drivers.
- Python 3.12; Qt 5 / PyQt5; offscreen widget rendering.

**48 tests passed, 0 skipped, 0 failures.** The suite includes the original 39 tests and nine regressions for the GeoPackage connection fix, cancellation and busy backup handling.

## Verified behavior

| Area | Checks |
| --- | --- |
| Standalone files | Exact Shapefile bundle deletion; dedicated GeoJSON sidecars; preservation of independent same-stem CSV/TIFF/QML/GeoJSON files |
| File recovery | A simulated second-file lock rolls back earlier moves; failed backup creation leaves the source intact |
| Source identity | Detect changed files, added sidecars and committed WAL changes after confirmation; reject unsupported, remote, virtual and symbolic-link sources |
| GeoPackage | Delete one table while preserving another table's geometry and catalog; remove deleted layer metadata and RTree indexes; keep the container after its last layer is deleted |
| Transactions | Inject a failure after DeleteLayer and before commit, then verify the original table and rows remain |
| Backups | Capture committed WAL data in a consistent SQLite backup; reopen backed-up Shapefiles as real QGIS layers |
| Dependencies | Block known project joins, project relations, edit sessions, foreign keys and dependent views; permit unrelated views |
| Project references | Remove duplicate references only after source deletion; keep surviving layer IDs; stabilize surviving numeric-index sources by table name |
| State recovery | Preserve the same layer objects and IDs, style, opacity, filters, custom properties, selected features, groups, visibility and project dirty state after source-operation failure |
| Menus and dialogs | Insert exactly one action after Remove Layer and before the named native separator; exclude groups; default to Cancel and backup enabled |
| Controller | Cancel preserves source and project; accepting confirmation performs actual source deletion and returns the canvas to its previous freeze state |
| Connection regression | A 31-table GeoPackage with a filtered duplicate retains all 30 named surviving provider objects and URIs, with zero source/validity signals; real feature attributes and geometries remain readable; style, opacity, selections, custom properties, groups and visibility remain intact |
| Saved projects | A saved project reopens named and normalized numeric survivors with the intended table, filter and style |
| Cancellation | Cancel during a partial multi-step backup leaves the source and project references unchanged and removes the partial copy; the real progress widget propagates cancellation and disables it during deletion |
| Busy backup | A real exclusive SQLite lock exercises bounded retry handling; source tables remain intact and partial backup files are cleaned up |

The menu insertion test uses real QGIS layer-tree widgets and Qt menus containing the named separator used by the native menu provider. Its location was also checked against QGIS source code.

## GeoPackage performance observation

A single local comparison used the same synthetic fixture generator for a 101-table GeoPackage (three point features per table, 2,105,344 bytes), with every table loaded and full backup enabled. Timing includes the confirmed execution path and excludes fixture creation and initial loading.

| Version | Elapsed time | Surviving-layer validity signals | Surviving tables readable |
| --- | ---: | ---: | --- |
| 0.2.0 | 4.564 s | 200 | All 100 |
| 0.2.1 | 0.095 s | 0 | All 100 |

This is a small synthetic, single-run observation on the environment above, not a promise for large or remote-storage databases. Full backups still scale with database size and storage speed. The improvement removes repeated container opens and sibling XML reconstruction; it does not skip the requested backup or the transaction's scope checks.

The Linux GDAL/QGIS combination emits some WAL/NOLOCK diagnostics while opening filtered fixture references, including in a no-deletion baseline. The regression assertions verify the post-operation attributes, geometry, fields and validity after cache synchronization; the test result is not a claim of a warning-free native GDAL log on every fixture.

## English and packaging review

- Menu labels, confirmation text, error messages, result messages and runtime metadata are English.
- Dialog layout and reference text use left-to-right alignment and the native QGIS font.
- README, usage and architecture guides, publishing instructions, release notes, comments and sample layer names are English.
- The actual English confirmation and backup-progress widgets were rendered and visually inspected. Their documentation screenshots use only synthetic values and a generic example path.
- The release builder checks required metadata, version consistency, English runtime text, the QGIS entry point, icon format and byte-for-byte equivalence between source files and ZIP entries.
- The practice project is tested after relocation by extracting the source archive to a new directory and reopening all four layers.

## Limits

The full desktop executable could not start successfully in the constrained display environment used for the prototype's native-app smoke attempt. The real-provider/widget suite does not claim full desktop-process certification. `tests/qgis_desktop_smoke.py` remains available for a normal desktop or CI display.

Windows file locking, macOS and QGIS 4 / Qt 6 were not exercised here. Scoped Qt enums and `qgis.PyQt` imports target both Qt generations, but compatibility bounds are not test coverage.

The recorded local results above are separate from the current [GitHub Actions status](https://github.com/geoforge-studio/layer-eraser/actions). The workflow reruns the real-provider/widget suite, builds the installable ZIP and publishes a new version only after those checks succeed on `main`. QGIS catalog submission remains a separate step.

## Reproduce

Using QGIS' Python from the repository root:

```sh
QT_QPA_PLATFORM=offscreen python3 -X faulthandler scripts/run_qgis_tests.py
python3 scripts/build_plugin.py
```

The release runner fails if real-runtime imports are unavailable or any tests are skipped. Ordinary `unittest discover -s tests -v` is also available for development.
