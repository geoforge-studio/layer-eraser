# Layer Eraser 0.2.2

This release addresses the Bandit B608 finding in GeoPackage verification and adds required QGIS 4 / Qt 6 runtime checks. The same installable ZIP supports QGIS 3.34 and later, including QGIS 4.

GeoPackage post-delete verification now uses constant SQL queries. The selected table name is compared in Python, rather than inserted into SQL text. Verification still runs before transaction commit, so a failed scope check rolls back the deletion. No Bandit checks are suppressed. Regression coverage includes a table name containing quotes and SQL-like text.

Scoped map-layer flags and explicit provider read flags accommodate both Qt 5 and Qt 6 bindings. The release workflow requires a clean Bandit scan and the full 50-test real-provider/widget suite on QGIS 3.34 / Qt 5 and official QGIS 4.0.3 and 4.2.3 / Qt 6 Linux images. It verifies the actual QGIS and Qt versions before running tests and publishes only after every job succeeds.

The GeoPackage connection fix and cancellable backup progress from 0.2.1 are retained. Supported sources remain one vector/attribute GeoPackage table, a Shapefile bundle or standalone GeoJSON. The operation deletes the entire source table or file, regardless of filters or selection. QGIS Undo does not restore deleted source data; use the optional backup for manual recovery.

Install **layer_eraser-0.2.2.zip** through **Plugins → Manage and Install Plugins → Install from ZIP**, then restart QGIS after upgrading. A separate ZIP for QGIS 4 is not required. The source archive is for development.

Tests use real QGIS providers and Qt widgets on Linux. Windows file locking, macOS and full native desktop-process validation remain separate platform checks. See `docs/VALIDATION.md` and the linked GitHub Actions run for execution evidence.
