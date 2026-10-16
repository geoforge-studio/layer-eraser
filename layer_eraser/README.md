# Layer Eraser 0.2.1

Layer Eraser adds **Delete Layer and Source…** immediately after **Remove Layer** in the QGIS Layers panel.

## Install and use

Install the release ZIP through **Plugins → Manage and Install Plugins → Install from ZIP**. Select one supported layer, right-click it, and choose **Delete Layer and Source…**. Review the actual file path, GeoPackage table name, and affected project references before choosing **Delete Source Data**.

Cancel is the default action. Backups are enabled by default. If you used the GeoForge Source Delete prototype, uninstall or disable it before installing this renamed package.

## Supported sources

- One vector or attribute table in a GeoPackage. Other tables and the file are preserved.
- A Shapefile and its recognized companion files.
- Standalone GeoJSON, including `.json` only when it uses the GeoJSON driver.

Deletion affects the **whole underlying table or file**, even when the layer is filtered or features are selected. Other projects using the source are affected. QGIS Undo does not restore deleted source data.

Rasters, remote services, other databases, archives, virtual/memory layers, views and SQL results are not supported. Groups and multiple selected layers do not initiate batch deletion.

## Backups

Backups are stored in `GeoForge_Backups` beside the source. A GeoPackage backup contains the entire database and includes committed WAL data. Restore only the deleted table from that backup if other tables have changed since it was created. Restore Shapefile or GeoJSON by copying the backed-up files to the original locations.

If backup creation fails, deletion does not proceed. Recovery is manual; there is no Restore button in this release.

Full GeoPackage backups can take time. Progress is shown and can be cancelled before source deletion. Partial cancelled backups are removed. Cancellation is disabled during deletion itself.

## GeoPackage connection fix

Version 0.2.1 removes the empty-source resets and XML reconstruction of surviving GeoPackage layers used in 0.2.0. Existing named providers synchronize their data caches in place. Numeric-index sources are converted directly to table-name sources. The automatic global Browser refresh has been removed; refresh the affected Browser item manually if its table list is stale.

After upgrading from 0.2.0, restart QGIS. For an already invalid connection, first check that its table still exists by expanding the original GeoPackage in Browser. Repair that layer's source through QGIS' **Change Data Source** action when available, or add the existing table again and verify it before removing the broken project reference with native **Remove Layer**. A warning icon alone does not establish whether source data was lost.

## Validation and dependencies

The plugin stops for open edit sessions, supported project/database dependencies, changed sources and permission or lock failures. Layer connections are restored in place after source-deletion errors in the tested scenarios.

Requires QGIS 3.34 or later and its bundled GDAL, with no additional Python packages. Tested on QGIS 3.34.4 / GDAL 3.8.4 on Linux. Windows, macOS and QGIS 4 / Qt 6 remain separate validation targets.

Publisher: **GeoForge Studio**. License: **GPL-3.0-or-later**.

Source, full user guide, tests and examples are intended for the public repository **geoforge-studio/layer-eraser**. Publication is a separate step from preparing this release package.
