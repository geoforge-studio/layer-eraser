# Changelog

## 0.2.1 — 2026-10-16

- Fix GeoPackage deletion invalidating connections to surviving tables: never assign empty sources to GeoPackage layers or reconstruct named siblings from XML.
- Synchronize data and field caches in existing providers after successful deletion, preserving source URIs, layer IDs, styles, filters, selections and layer-tree settings.
- Convert only numeric-index survivors directly to table-name sources, after backup completes. Restore their original sources on transaction failure.
- Avoid reopening a GeoPackage for every named project reference and verify the surviving catalog with one query.
- Show incremental backup progress with cancellation before deletion, remove cancelled partial backups, and bound retries for a busy database.
- Remove the automatic global Browser refresh. Refresh the affected Browser item manually when needed.
- Add regression tests for many loaded tables, filtered duplicates, source/validity signals, saved projects, cancellation and busy backup handling.

## 0.2.0 — 2026-10-16

- Adopt the public plugin name **Layer Eraser** and Python package `layer_eraser`.
- Use English throughout menus, dialogs, messages, documentation, tests and practice data.
- Use the native QGIS font and left-to-right dialog layout.
- Add complete publication metadata with the existing GeoForge Studio author/contact identity.
- Separate the installable plugin from tests, examples and repository documentation.
- Add a reproducible ZIP builder, release validation, and GitHub CI configuration.

## 0.1.0 — 2026-10-16

- Internal prototype under the name GeoForge Source Delete.
- Add source deletion for GeoPackage vector/attribute tables, Shapefile bundles and standalone GeoJSON.
- Add confirmation, optional backups, duplicate-reference checks, dependency checks and failure recovery.
