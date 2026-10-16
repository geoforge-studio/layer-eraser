# Layer Eraser 0.2.1

Layer Eraser adds **Delete Layer and Source…** immediately after **Remove Layer** in the QGIS Layers panel. It deletes a local layer's underlying source data and removes all current project references to that source after successful deletion.

Supported sources are individual vector or attribute tables in a GeoPackage, complete Shapefile bundles, and standalone GeoJSON. The English confirmation dialog displays the actual file/table and affected project layers, with backup creation enabled by default.

This maintenance release fixes GeoPackage deletion leaving surviving layers with invalid connection indicators. Named surviving layers keep the same provider objects and source URIs; data and field caches are synchronized without resetting their sources or reconstructing their XML. Index-based survivors are converted directly to table-name sources after backup completes.

Repeated container opens and the automatic global Browser refresh have been removed. Full GeoPackage backups still depend on database size, but now display incremental progress and support cancellation before deletion. Partial cancelled backups are removed, and a busy backup stops after bounded lock retries.

The release retains source-change checks, supported dependency checks, transactional GeoPackage deletion, staged file removal and recovery after errors. The runtime requires only QGIS and its bundled GDAL. **48 real-file/provider/widget tests passed** in the recorded Linux environment.

This operation deletes the entire source table or file, regardless of layer filters or selected features. QGIS Undo does not restore it. Use the optional backup for manual recovery.

Install **layer_eraser-0.2.1.zip** using **Plugins → Manage and Install Plugins → Install from ZIP**, then restart QGIS when upgrading from 0.2.0. The source archive is for development and should not be installed through Plugin Manager. For layers already marked invalid, check the original tables in Browser and follow the connection-repair steps in the user guide.

The recorded test environment is QGIS 3.34.4 / GDAL 3.8.4 on Linux. Windows, macOS and QGIS 4 / Qt 6 require separate validation; declared compatibility targets are not a claim of complete platform coverage.
