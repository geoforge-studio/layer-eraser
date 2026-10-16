# User guide

Layer Eraser deletes local vector source data and removes the corresponding layer references from the current QGIS project.

## Before deleting

Select one actual layer in the Layers panel. Finish any edit session on that source, including another table in the same GeoPackage. The plugin does not save or discard pending edits automatically.

Right-click and choose **Delete Layer and Source…** immediately after **Remove Layer**. The native Remove Layer action remains available for ordinary project-only removal.

## Confirmation

The dialog shows:

- The source format and full file path.
- The actual GeoPackage table name, when applicable.
- Every current project layer that points to the same table or file.
- The recognized file bundle for a Shapefile or standalone GeoJSON.
- A backup option, enabled by default.

A display name is not used as the database table identifier. Layer filters and selected features do not reduce the source deletion scope.

Cancel is the default action. There is no deletion keyboard shortcut. If the source changes while confirmation is open, the plugin stops and asks you to review it again.

## GeoPackage

Only a standard vector or attribute table can be deleted. Driver-managed table metadata and spatial indexes are removed with it. Other tables remain in the database; the container is kept even when its last user table is deleted.

Project references to surviving tables keep their layer IDs and settings. Named layers retain the same provider objects and source URIs while their caches are synchronized in place. They are never reset to empty sources. Where a surviving source used a numeric OGR table index, it is connected directly by table name so a changed index cannot redirect it to another table.

The plugin does not automatically refresh the entire Browser tree. If its table list still shows a deleted table, right-click the affected GeoPackage item in Browser and choose **Refresh**.

Deletion is blocked for supported foreign-key and related-table dependencies, dependent views/triggers, and project joins or relations. SQL dependency detection is conservative rather than a complete SQL parser.

## Shapefile

Recognized companion extensions include SHX, DBF, PRJ, QPJ, CPG, QIX, SBN, SBX, FBN, FBX, AIN, AIH, IXS, MXS, IDM, IND, FIX, ATX attribute indexes, and dedicated SHP/DBF XML metadata. The confirmation lists the exact existing files to be removed.

Files with the same stem but an independent format, such as `roads.csv`, `roads.tif`, or `roads.qml`, are preserved. The plugin does not use an unrestricted same-stem wildcard.

## Backups

Backups are created beside the source in `GeoForge_Backups`. For GeoPackage, the SQLite backup API produces a consistent full-database copy and includes committed WAL pages. For Shapefile and GeoJSON, the exact source bundle is copied.

If there is not enough space or the backup directory is not writable, no deletion is performed. Symbolic links are not used as source files or backup directories.

Large GeoPackage backups take time because they include every table. The progress dialog shows the backup progress and permits **Cancel** before deletion. Cancellation leaves all source data and project references in place and removes the partial backup. A busy backup stops after bounded lock retries. Once the operation begins deleting source data, cancellation is disabled until the transaction finishes.

The result dialog shows the backup folder and provides **Open Backup Folder**. Restore a Shapefile/GeoJSON by copying the files back. Restore a GeoPackage table by importing that table from the backup, preserving later changes to other tables.

## Errors

A failure to delete source data leaves the project layers registered while their saved provider configuration is restored. The plugin preserves IDs, style, opacity, filters, selections, custom properties, layer groups, visibility, and the previous canvas freeze state in the tested scenarios.

If a file is locked, close the application or table view holding that source and retry. A failed multi-file staging move returns already-staged files to their original locations. If operating-system errors also prevent recovery, the error message identifies files retained for manual recovery.

## Repairing an existing connection

Layer Eraser 0.2.0 could leave surviving GeoPackage layers with invalid connection indicators after resetting and reconstructing their providers. Installing 0.2.1 prevents that reset path; it cannot establish the state of a database it has not inspected.

1. Install 0.2.1 and restart QGIS to load the updated modules.
2. In Browser, expand the original GeoPackage and check whether the affected tables are present.
3. If a table is present, repair the broken layer's connection using QGIS' **Change Data Source** action when available. Select the original GeoPackage and that exact table, not the full container without a table name.
4. Alternatively, add the existing table again from Browser. Verify its attributes and geometry, then remove only the broken project reference using native **Remove Layer**.
5. If a table is absent, inspect the pre-deletion copy in `GeoForge_Backups` and import only the missing table. Avoid replacing the whole original database when other tables have subsequently changed.

A red warning icon indicates a connection problem; it is not proof that the table itself was deleted. Backups are never automatically restored over the current database.

## Outside the current scope

This release does not delete raster data, database schemas, complete GeoPackages, File Geodatabases, server data, web services, archives, virtual layers, views, or SQL-result layers. It does not recurse through layer groups or save the QGIS project automatically.
