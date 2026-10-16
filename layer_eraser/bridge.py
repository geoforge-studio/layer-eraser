# SPDX-License-Identifier: GPL-3.0-or-later
"""QGIS source decoding, project checks and narrowly scoped provider handling.

GeoPackage providers remain connected during transactional table deletion.
Only standalone-file providers need detachment for operating-system locks.
"""
from dataclasses import dataclass
import os
from pathlib import Path

from qgis.PyQt.QtXml import QDomDocument
from qgis.core import (
    Qgis, QgsDataProvider, QgsMapLayer, QgsProviderRegistry, QgsReadWriteContext,
    QgsVectorLayer,
)

from .core import SourceError, build_plan, local_path, revalidate


def decode_source(layer):
    if not isinstance(layer, QgsVectorLayer) or layer.providerType() != "ogr":
        raise SourceError('Select a local vector GeoPackage, Shapefile, or GeoJSON layer.')
    if not layer.isValid():
        raise SourceError('The layer is invalid. Repair its source connection first.')
    decoded = QgsProviderRegistry.instance().decodeUri("ogr", layer.source())
    if decoded.get("sql"):
        raise SourceError('Query-result layers cannot be deleted. Select the original table instead.')
    path = local_path(decoded.get("path", ""))
    return path, decoded


def actual_table(path, decoded):
    # QGIS normally stores an explicit table name. Avoid opening the entire
    # container once for every project layer; build_plan verifies this name.
    name = str(decoded.get("layerName") or "")
    if name:
        return name
    from osgeo import ogr
    dataset = ogr.Open(str(path), 0)
    if dataset is None:
        raise SourceError('The actual table name could not be read from the source.')
    try:
        if decoded.get("layerId") is not None:
            try:
                layer = dataset.GetLayerByIndex(int(decoded["layerId"]))
            except (TypeError, ValueError):
                layer = None
        elif dataset.GetLayerCount() >= 1:
            # QGIS normalizes |layerid=0 to a bare path. OGR's default layer
            # for that valid source is the first layer, even in a container.
            layer = dataset.GetLayerByIndex(0)
        else:
            raise SourceError('No table could be identified in this source.')
        if layer is None:
            raise SourceError('The specified table was not found in the source.')
        name = layer.GetName()
        layer = None
        return name
    finally:
        dataset = None


def plan_layer(layer):
    path, decoded = decode_source(layer)
    table = actual_table(path, decoded) if path.suffix.lower() == ".gpkg" else ""
    plan = build_plan(path, table)
    if plan.kind == "geojson":
        driver_name = layer.dataProvider().storageType().casefold()
        if "geojson" not in driver_name:
            raise SourceError('A JSON extension is not sufficient. The source must use the GeoJSON driver.')
    return plan


def _same_file(left, right):
    try:
        return os.path.samefile(str(left), str(right))
    except OSError:
        return os.path.normcase(str(left)) == os.path.normcase(str(right))


def affected_layers(project, plan):
    result = []
    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer) or layer.providerType() != "ogr":
            continue
        decoded = QgsProviderRegistry.instance().decodeUri("ogr", layer.source())
        raw = decoded.get("path")
        if not raw:
            continue
        try:
            path = Path(raw).resolve()
        except (OSError, ValueError):
            continue
        if not _same_file(path, plan.path):
            continue
        if plan.kind == "geopackage":
            table = actual_table(path, decoded)
            if table != plan.table:
                continue
        result.append(layer)
    if not result:
        raise SourceError('No project reference to this source was found. Select the layer again.')
    return result


def check_project(project, plan, layers):
    ids = {layer.id() for layer in layers}
    for layer in layers:
        if not (layer.flags() & QgsMapLayer.LayerFlag.Removable):
            raise SourceError('This layer is protected against removal in the project: ' + layer.name())
        if layer.isEditable():
            raise SourceError('Finish editing this layer before deleting its source: ' + layer.name())
        if project.layerIsEmbedded(layer.id()):
            raise SourceError('This layer is embedded from another project. Delete it from its original project.')
    # An open edit session on a sibling GPKG table may hold a transaction lock.
    for layer in project.mapLayers().values():
        if isinstance(layer, QgsVectorLayer) and layer.providerType() == "ogr":
            parts = QgsProviderRegistry.instance().decodeUri("ogr", layer.source())
            if parts.get("path") and _same_file(Path(parts["path"]).resolve(), plan.path):
                if layer.isEditable():
                    raise SourceError('Another layer from this source is being edited: ' + layer.name())
        if layer.id() in ids:
            continue
        if hasattr(layer, "vectorJoins"):
            if any(join.joinLayerId() in ids for join in layer.vectorJoins()):
                raise SourceError('Another layer has a join to this source: ' + layer.name())
        if any(dependency.layerId() in ids for dependency in layer.dependencies()):
            raise SourceError('Another layer depends on this layer: ' + layer.name())
    for relation in project.relationManager().relations().values():
        if relation.referencingLayerId() in ids or relation.referencedLayerId() in ids:
            raise SourceError('This layer is used by a project relation: ' + relation.name())


@dataclass
class LayerState:
    layer: object
    document: object
    selection: list
    source: str
    name: str
    stable_source: str = ""


class ProviderPause:
    """Recoverable standalone-file pause or numeric-source normalization."""

    def __init__(self, project, layers):
        self.project = project
        self.layers = list(layers)
        self.states = []
        self.context = QgsReadWriteContext()
        self.context.setPathResolver(project.pathResolver())
        self.dirty_before = project.isDirty()

    def capture(self):
        for layer in self.layers:
            doc = QDomDocument("geoforge_layer_recovery")
            element = doc.createElement("maplayer")
            doc.appendChild(element)
            if not layer.writeLayerXml(element, doc, self.context):
                raise SourceError('The layer state could not be saved for recovery: ' + layer.name())
            self.states.append(LayerState(
                layer, doc, list(layer.selectedFeatureIds()), layer.source(), layer.name()
            ))
            parts = QgsProviderRegistry.instance().decodeUri("ogr", layer.source())
            if parts.get("path") and Path(parts["path"]).suffix.lower() == ".gpkg":
                # Removing another table can shift numeric OGR layer indexes.
                # Store a name-based equivalent for surviving layers only.
                parts["layerName"] = actual_table(Path(parts["path"]), parts)
                parts.pop("layerId", None)
                self.states[-1].stable_source = QgsProviderRegistry.instance().encodeUri("ogr", parts)

    def options(self):
        options = QgsDataProvider.ProviderOptions()
        options.transformContext = self.project.transformContext()
        return options

    def set_source(self, state, source):
        # Read flags moved from QgsDataProvider to Qgis in newer QGIS builds.
        # Explicit empty flags preserve the existing style in both bindings.
        flag_type = getattr(Qgis, "DataProviderReadFlags", None)
        flags = flag_type(0) if flag_type is not None else QgsDataProvider.ReadFlags(0)
        state.layer.setDataSource(source, state.name, "ogr", self.options(), flags)

    def detach(self):
        self.capture()
        for state in self.states:
            # A real provider reset, not removing tree nodes or changing IDs.
            self.set_source(state, "")

    def stabilize(self):
        """Convert only index-based survivors directly to valid named sources."""
        self.capture()
        for state in self.states:
            self.set_source(state, state.stable_source)
            if not state.layer.isValid():
                raise SourceError('The indexed layer could not be connected by table name: ' + state.name)
            state.layer.selectByIds(state.selection)

    def restore(self):
        errors = []
        for state in self.states:
            try:
                # A public provider reset emits validity changes for the layer
                # tree. Reading XML alone left stale warning indicators in 0.2.0.
                self.set_source(state, state.source)
                doc = state.document.cloneNode(True).toDocument()
                ok = state.layer.readLayerXml(doc.documentElement(), self.context)
                if not ok or not state.layer.isValid():
                    errors.append(state.name)
                    continue
                state.layer.selectByIds(state.selection)
                state.layer.triggerRepaint()
            except Exception:
                errors.append(state.name)
        self.project.setDirty(self.dirty_before)
        if errors:
            raise SourceError('These layer connections could not be restored automatically: ' + ', '.join(errors))


def synchronize_geopackage(project, plan):
    """Refresh GDAL caches in the existing providers after a schema change.

    Filtered duplicates can enable WAL and retain shared connections. Merely
    keeping providers open is insufficient in that case. The public layer reload
    synchronizes provider internals and fields without setting invalid sources
    or rebuilding layer XML.
    """
    warnings = []
    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer) or layer.providerType() != "ogr" or not layer.isValid():
            continue
        parts = QgsProviderRegistry.instance().decodeUri("ogr", layer.source())
        if not parts.get("path") or not _same_file(Path(parts["path"]).resolve(), plan.path):
            continue
        try:
            provider = layer.dataProvider()
            selection = list(layer.selectedFeatureIds())
            # The public layer reload also updates its cached field map. The
            # provider object and source URI stay unchanged throughout.
            layer.reload()
            if not provider.isValid():
                raise SourceError('The existing provider could not refresh its data cache.')
            layer.selectByIds(selection)
            layer.triggerRepaint()
        except Exception as exc:
            warnings.append('The table was preserved, but its connection needs attention: '
                            + layer.name() + '. ' + str(exc))
    return warnings


def execute_delete(project, layer, confirmed_plan, backup=True, backend=None, progress=None):
    """Used by the dialog and real-data integration tests."""
    from .core import delete_source
    path, parts = decode_source(layer)
    table = actual_table(path, parts) if confirmed_plan.kind == "geopackage" else ""
    if not _same_file(path, confirmed_plan.path) or table != confirmed_plan.table:
        raise SourceError('The layer source changed. Review it again before deleting.')
    layers = affected_layers(project, confirmed_plan)
    check_project(project, confirmed_plan, layers)
    deletion_ids = {item.id() for item in layers}
    if confirmed_plan.kind == "geopackage":
        # Named siblings keep exactly the same provider, source URI and state.
        # Only numeric/bare-path sources need conversion: dropping a preceding
        # table shifts OGR indexes and would otherwise break saved projects.
        indexed = []
        for sibling in project.mapLayers().values():
            if sibling.id() in deletion_ids or not isinstance(sibling, QgsVectorLayer) or sibling.providerType() != "ogr":
                continue
            parts = QgsProviderRegistry.instance().decodeUri("ogr", sibling.source())
            if not parts.get("layerName") and sibling.isValid() and parts.get("path") and _same_file(Path(parts["path"]).resolve(), confirmed_plan.path):
                indexed.append(sibling)
        pause = ProviderPause(project, indexed)
        try:
            if backend is None:
                # Backup/cancellation finish before even indexed sources change.
                result = delete_source(confirmed_plan, backup=backup, progress=progress,
                                       before_delete=pause.stabilize)
            else:
                pause.stabilize()
                result = backend(confirmed_plan, backup=backup)
        except Exception as exc:
            try:
                pause.restore()
            except Exception as recovery:
                raise SourceError(str(exc) + "\n" + str(recovery)) from exc
            raise
        project.removeMapLayers(list(deletion_ids))
        result.warnings.extend(synchronize_geopackage(project, confirmed_plan))
        project.setDirty(True)
        return result

    # File bundles need closed handles on Windows. The GeoPackage path above
    # never assigns invalid sources to other tables.
    revalidate(confirmed_plan)
    pause = ProviderPause(project, layers)
    try:
        pause.detach()
        # Recheck the bundle after releasing file handles. Its advertised
        # scope must still match the confirmation.
        execution_plan = build_plan(confirmed_plan.path, confirmed_plan.table)
        if execution_plan.catalog != confirmed_plan.catalog or execution_plan.files != confirmed_plan.files:
            raise SourceError('The source structure changed while releasing its connection. Deletion was stopped.')
        if backend is None:
            result = delete_source(execution_plan, backup=backup, progress=progress)
        else:
            result = backend(execution_plan, backup=backup)
    except Exception as exc:
        try:
            pause.restore()
        except Exception as recovery:
            raise SourceError(str(exc) + "\n" + str(recovery)) from exc
        raise
    # Only a successful source operation reaches registry removal.
    project.removeMapLayers(list(deletion_ids))
    project.setDirty(True)
    return result
