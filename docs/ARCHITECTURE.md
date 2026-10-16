# Architecture

## Modules

| Module | Responsibility |
| --- | --- |
| `core.py` | Identify local files and GeoPackage tables; create a deletion plan; detect source changes; create backups; execute transactional or staged deletion. No Qt or QGIS imports. |
| `bridge.py` | Decode QGIS source URIs; find duplicate references and project dependencies; synchronize GeoPackage caches in existing providers; normalize index-based survivors; pause only standalone-file providers. |
| `dialogs.py` | English confirmation UI with selectable source values, explicit deletion scope, backup choice and Cancel as the default action; modal backup progress and cancellation. |
| `plugin.py` | Plugin lifecycle; context-menu insertion immediately after native Remove Layer; canvas handling; result and error messages. |
| `version.py` | Runtime release version, checked against `metadata.txt` by the builder. |

## Deletion sequence

1. Decode the selected layer's source and resolve the actual table name.
2. Build a read-only plan: exact path, table, recognized companion files, file/WAL stamps and GeoPackage catalog.
3. Find every reference to that source in the current project and check supported dependencies.
4. Show confirmation; no source or project layer is removed at this point.
5. Revalidate the confirmed identity and pause rendering.
6. For standalone files, save layer XML and release only affected file handles. For GeoPackage, leave providers connected.
7. Revalidate the source and create the optional backup in increments. Progress callbacks permit cancellation before any data is deleted. Partial cancelled backups are removed.
8. After backup succeeds, connect only numeric-index GeoPackage survivors directly by table name. Do not assign empty sources to GeoPackage layers.
9. Disable cancellation and delete through the transactional or staged backend.
10. Remove successfully deleted source references. Synchronize GeoPackage data and field caches with `layer.reload()` in existing provider objects, preserving selections. Do not reset source URIs or read sibling XML. Do not refresh the global Browser tree.

On failure, named GeoPackage providers remain untouched. Any changed numeric-index source is restored, and standalone-file providers recover their saved configuration. Restoring a paused file first uses the public `setDataSource` API to emit validity changes before reading XML. The project registry is never cleared as preparation for deletion.

Version 0.2.0 paused every vector sibling through an empty source and reconstructed them from XML. That could leave stale invalid-connection indicators and added repeated container opens. Version 0.2.1 removes that path. A plain no-refresh implementation also proved insufficient for cached connections with filtered duplicates/WAL: the native provider cache and layer field map must be synchronized after the schema change. This requires no invalid source assignment.

## Storage backends

GeoPackage inspection and backup use read-only SQLite connections. Table deletion uses GDAL's GPKG driver inside a dataset transaction. The code verifies removal of the selected table and geospatial metadata, and presence of surviving catalog entries, before committing. It does not implement database table deletion through a raw SQLite `DROP TABLE`.

GDAL post-delete verification uses constant SQL queries and compares the selected table name in Python. No table name or project value is interpolated into those queries. This removes the Bandit B608 finding reported for 0.2.1 without suppressions or weaker transaction checks. Read-only SQLite inspection continues to bind data values through placeholders; its PRAGMA identifier is quoted as an identifier.

QGIS integration uses `qgis.PyQt`, scoped enums and explicit provider read flags. The flag factory accommodates the move from `QgsDataProvider.ReadFlags` to `Qgis.DataProviderReadFlags`. The CI runner asserts QGIS and Qt versions so a Qt 5 image cannot accidentally satisfy a QGIS 4 check.

Standalone file bundles are renamed into a temporary directory on the same filesystem. If any move fails, completed moves are reversed. After successful staging, the temporary directory is removed. An incomplete temporary-file purge is reported separately from removal of the active source.

## Limits and extension points

This implementation is synchronous and operates on one selected underlying source. Large full-database backups still take time. SQLite copies 256 pages per step and calls the GUI progress callback; the application-modal dialog processes events while blocking editing elsewhere. Backup lock retries stop after five seconds of continuous busy/locked responses. Cancellation is supported only before source deletion; the final transaction is deliberately not interrupted. Additional formats require a format-specific plan, backup strategy, verification and failure tests. Group/batch deletion, automatic restore, raster deletion and remote databases are separate future features.

SQL dependency scanning is deliberately conservative. It cannot prove the absence of every dependency in custom applications, external databases or closed projects.
