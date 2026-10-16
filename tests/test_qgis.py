# SPDX-License-Identifier: GPL-3.0-or-later
"""Real QGIS providers, layer registry, layer tree, and widgets (offscreen)."""
from contextlib import closing
from pathlib import Path
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from qgis.core import (
        QgsApplication, QgsLayerTreeModel, QgsProject, QgsVectorLayer,
        QgsVectorLayerJoinInfo, QgsRelation,
    )
    from qgis.gui import QgsLayerTreeView, QgsMapCanvas
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtGui import QColor
    from qgis.PyQt.QtWidgets import QMainWindow, QMenu
    from layer_eraser import bridge, core
    from layer_eraser.dialogs import ConfirmDeleteDialog, DeleteProgressDialog
    from layer_eraser.plugin import LayerEraserPlugin, ACTION_NAME
    from tests.test_core import make_gpkg
    from osgeo import ogr
    HAVE_QGIS = True
except ImportError:
    HAVE_QGIS = False

APP = None


def setUpModule():
    global APP
    if HAVE_QGIS:
        APP = QgsApplication.instance()
        if APP is None:
            APP = QgsApplication([], False)
            APP.initQgis()


@unittest.skipUnless(HAVE_QGIS, "A real QGIS runtime is required")
class QgisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = QgsProject.instance()
        self.project.clear()
        self.gpkg = self.root / 'source data.gpkg'
        make_gpkg(self.gpkg)

    def tearDown(self):
        self.project.clear()
        self.tmp.cleanup()

    def add(self, uri, name='Test layer'):
        layer = QgsVectorLayer(str(uri), name, "ogr")
        self.assertTrue(layer.isValid(), "Could not open OGR layer: " + str(uri))
        self.project.addMapLayer(layer)
        return layer

    def make_geojson(self):
        path = self.root / 'points.geojson'
        path.write_text(json.dumps({"type":"FeatureCollection", "features":[
            {"type":"Feature","properties":{"code":1},"geometry":{"type":"Point","coordinates":[48,36]}},
            {"type":"Feature","properties":{"code":2},"geometry":{"type":"Point","coordinates":[49,37]}}
        ]}), encoding="utf-8")
        return path

    def snapshot_visual_state(self, layer):
        layer.renderer().symbol().setColor(QColor("#c82345"))
        layer.setOpacity(.43)
        layer.setCustomProperty("test-marker", "unchanged")
        layer.setSubsetString('"fid" = 1')
        layer.selectByIds([1])
        group = self.project.layerTreeRoot().addGroup('Example group')
        node = self.project.layerTreeRoot().findLayer(layer.id())
        clone = node.clone()
        node.parent().removeChildNode(node)
        group.addChildNode(clone)
        clone.setItemVisibilityChecked(False)
        return group

    def test_source_plan_uses_real_table_not_display_name(self):
        layer = self.add(str(self.gpkg) + "|layername=target", 'A completely different display name')
        plan = bridge.plan_layer(layer)
        self.assertEqual(plan.table, "target")

    def test_numeric_layer_id_is_resolved_to_table_name(self):
        layer = self.add(str(self.gpkg) + "|layerid=0")
        self.assertEqual(bridge.plan_layer(layer).table, "target")

    def test_duplicate_references_removed_sibling_survives(self):
        first = self.add(str(self.gpkg) + "|layername=target", 'First reference')
        second = self.add(str(self.gpkg) + "|layername=target", 'Second reference')
        second.setSubsetString('"fid"=1')
        keep = self.add(str(self.gpkg) + "|layername=keep", 'Preserved layer')
        ids = [first.id(), second.id()]
        keep_id = keep.id()
        bridge.execute_delete(self.project, first, bridge.plan_layer(first), backup=True)
        self.assertTrue(all(self.project.mapLayer(i) is None for i in ids))
        self.assertIs(self.project.mapLayer(keep_id), keep)
        self.assertTrue(keep.isValid())
        self.assertEqual(keep.featureCount(), 3)
        self.assertTrue(self.gpkg.exists())

    def test_numeric_sibling_is_preserved_and_stabilized_by_name(self):
        target = self.add(str(self.gpkg) + "|layername=target")
        keep = self.add(str(self.gpkg) + "|layerid=1", "numeric keep")
        self.snapshot_visual_state(keep)
        identifier = keep.id()
        bridge.execute_delete(self.project, target, bridge.plan_layer(target), backup=False)
        self.assertIs(self.project.mapLayer(identifier), keep)
        self.assertTrue(keep.isValid())
        self.assertEqual(bridge.plan_layer(keep).table, "keep")
        self.assertEqual(keep.featureCount(), 1)
        self.assertEqual(list(keep.selectedFeatureIds()), [1])
        self.assertEqual(keep.renderer().symbol().color().name(), "#c82345")
        # Reopening the preserved URI must select keep despite changed indexes.
        reopened = QgsVectorLayer(keep.source(), "reopened", "ogr")
        self.assertTrue(reopened.isValid())
        self.assertEqual(bridge.plan_layer(reopened).table, "keep")

    def test_many_named_siblings_keep_providers_sources_styles_and_validity(self):
        path = self.root / 'many tables.gpkg'
        names = ['target'] + ['keep_%02d' % i for i in range(30)]
        make_gpkg(path, names)
        target = self.add(str(path) + '|layername=target', 'Delete this')
        duplicate = self.add(str(path) + '|layername=target', 'Filtered duplicate')
        duplicate.setSubsetString('"fid"=1')
        survivors = [self.add(str(path) + '|layername=' + name, name) for name in names[1:]]
        styled = survivors[0]
        group = self.snapshot_visual_state(styled)
        snapshots = [(item, item.id(), item.source(), item.dataProvider()) for item in survivors]
        signals = []
        for item in survivors:
            item.dataSourceChanged.connect(lambda: signals.append('source changed'))
            item.isValidChanged.connect(lambda: signals.append('validity changed'))
        # An independent data source must not be globally reloaded either.
        independent = self.add(str(self.gpkg) + '|layername=keep', 'Independent')
        independent_signals = []
        independent.dataProvider().dataChanged.connect(lambda: independent_signals.append(True))
        result = bridge.execute_delete(self.project, target, bridge.plan_layer(target), backup=True)
        self.assertEqual(result.warnings, [])
        self.assertEqual(signals, [])
        self.assertEqual(independent_signals, [])
        for item, identifier, uri, provider in snapshots:
            self.assertIs(self.project.mapLayer(identifier), item)
            self.assertIs(item.dataProvider(), provider)
            self.assertEqual(item.source(), uri)
            self.assertTrue(item.isValid())
            features = list(item.getFeatures())
            self.assertEqual(len(features), 1 if item is styled else 3)
            self.assertEqual(features[0]['label'], item.name() + '-0')
            self.assertFalse(features[0].geometry().isEmpty())
        self.assertEqual(styled.renderer().symbol().color().name(), '#c82345')
        self.assertAlmostEqual(styled.opacity(), .43)
        self.assertEqual(styled.customProperty('test-marker'), 'unchanged')
        self.assertEqual(list(styled.selectedFeatureIds()), [1])
        node = self.project.layerTreeRoot().findLayer(styled.id())
        self.assertIs(node.parent(), group)
        self.assertFalse(node.itemVisibilityChecked())

    def test_saved_project_reopens_surviving_named_and_numeric_layers(self):
        project_path = self.root / 'saved project.qgz'
        self.project.setFileName(str(project_path))
        target = self.add(str(self.gpkg) + '|layername=target', 'Delete')
        named = self.add(str(self.gpkg) + '|layername=keep', 'Named')
        numeric = self.add(str(self.gpkg) + '|layerid=1', 'Numeric')
        self.snapshot_visual_state(named)
        self.snapshot_visual_state(numeric)
        ids = {named.id(), numeric.id()}
        bridge.execute_delete(self.project, target, bridge.plan_layer(target), backup=False)
        self.assertTrue(self.project.write())
        self.project.clear()
        self.assertTrue(self.project.read(str(project_path)))
        self.assertEqual(set(self.project.mapLayers()), ids)
        for item in self.project.mapLayers().values():
            self.assertTrue(item.isValid())
            self.assertEqual(bridge.plan_layer(item).table, 'keep')
            self.assertEqual([f['label'] for f in item.getFeatures()], ['keep-0'])
            self.assertEqual(item.renderer().symbol().color().name(), '#c82345')

    def test_cancel_backup_keeps_every_layer_and_removes_partial_backup(self):
        target = self.add(str(self.gpkg) + '|layername=target')
        keep = self.add(str(self.gpkg) + '|layerid=1')
        before = [(item, item.id(), item.source(), item.dataProvider()) for item in (target, keep)]
        self.project.setDirty(False)
        phases = []
        def cancel(phase, completed, total):
            phases.append(phase)
            if phase == 'backup':
                raise core.OperationCancelled('cancel backup')
        with self.assertRaises(core.OperationCancelled):
            bridge.execute_delete(self.project, target, bridge.plan_layer(target), progress=cancel)
        self.assertIn('backup', phases)
        self.assertNotIn('deleting', phases)
        for item, identifier, source, provider in before:
            self.assertIs(self.project.mapLayer(identifier), item)
            self.assertIs(item.dataProvider(), provider)
            self.assertEqual(item.source(), source)
            self.assertEqual(len(list(item.getFeatures())), 3)
        self.assertFalse(self.project.isDirty())
        self.assertEqual(list((self.root / 'GeoForge_Backups').iterdir()), [])

    def test_numeric_source_is_restored_after_transaction_failure(self):
        target = self.add(str(self.gpkg) + '|layername=target')
        keep = self.add(str(self.gpkg) + '|layerid=1')
        self.snapshot_visual_state(keep)
        source = keep.source()
        self.project.setDirty(False)
        # Cause post-delete verification to fail inside the transaction.
        with patch.object(core, '_ogr_first_column', return_value=('target',)):
            with self.assertRaises(core.SourceError):
                bridge.execute_delete(self.project, target, bridge.plan_layer(target), backup=False)
        self.assertEqual(keep.source(), source)
        self.assertTrue(keep.isValid())
        self.assertEqual([f['label'] for f in keep.getFeatures()], ['keep-0'])
        self.assertEqual(len(list(target.getFeatures())), 3)
        self.assertEqual(list(keep.selectedFeatureIds()), [1])
        self.assertEqual(keep.renderer().symbol().color().name(), '#c82345')
        self.assertFalse(self.project.isDirty())

    def test_progress_cancel_stops_before_deletion(self):
        target = self.add(str(self.gpkg) + '|layername=target')
        plan = bridge.plan_layer(target)
        progress = DeleteProgressDialog(plan)
        progress('backup', 1, 10)
        self.assertEqual(progress.value(), 100)
        progress.cancel()
        with self.assertRaises(core.OperationCancelled):
            core.delete_source(plan, backup=False, progress=progress)
        self.assertEqual(len(list(target.getFeatures())), 3)
        progress.close()

    def test_progress_disables_cancellation_during_deletion(self):
        target = self.add(str(self.gpkg) + '|layername=target')
        progress = DeleteProgressDialog(bridge.plan_layer(target))
        progress('ready', 0, 0)
        progress('deleting', 0, 0)
        self.assertFalse(progress.cancellable)
        progress.close()

    def test_failure_restores_duplicate_and_sibling_states(self):
        first = self.add(str(self.gpkg) + "|layername=target", "first")
        second = self.add(str(self.gpkg) + "|layername=target", "second")
        keep = self.add(str(self.gpkg) + "|layername=keep", "keep")
        self.snapshot_visual_state(second)
        keep.selectByIds([2])
        original_ids = set(self.project.mapLayers())
        def fail(plan, backup=True):
            raise core.SourceError("failure before commit")
        with self.assertRaises(core.SourceError):
            bridge.execute_delete(self.project, first, bridge.plan_layer(first), backup=False, backend=fail)
        self.assertEqual(set(self.project.mapLayers()), original_ids)
        self.assertEqual(first.featureCount(), 3)
        self.assertEqual(second.featureCount(), 1)
        self.assertEqual(keep.featureCount(), 3)
        self.assertEqual(list(second.selectedFeatureIds()), [1])
        self.assertEqual(list(keep.selectedFeatureIds()), [2])

    def test_project_relation_blocks_deletion(self):
        target = self.add(str(self.gpkg) + "|layername=target")
        keep = self.add(str(self.gpkg) + "|layername=keep")
        relation = QgsRelation()
        relation.setId("test-relation")
        relation.setName("test relation")
        relation.setReferencedLayer(target.id())
        relation.setReferencingLayer(keep.id())
        relation.addFieldPair("fid", "fid")
        self.project.relationManager().addRelation(relation)
        with self.assertRaises(core.SourceError):
            bridge.execute_delete(self.project, target, bridge.plan_layer(target), backup=False)
        self.assertEqual(target.featureCount(), 3)

    def test_failed_deletion_keeps_ids_style_subset_selection_and_group(self):
        layer = self.add(str(self.gpkg) + "|layername=target")
        group = self.snapshot_visual_state(layer)
        layer_id = layer.id()
        before_dirty = self.project.isDirty()
        plan = bridge.plan_layer(layer)
        def fail(plan, backup=True):
            raise core.SourceError("simulated lock")
        with self.assertRaises(core.SourceError):
            bridge.execute_delete(self.project, layer, plan, backend=fail)
        restored = self.project.mapLayer(layer_id)
        self.assertIs(restored, layer)
        self.assertTrue(restored.isValid())
        self.assertEqual(restored.renderer().symbol().color().name(), "#c82345")
        self.assertAlmostEqual(restored.opacity(), .43)
        self.assertEqual(restored.customProperty("test-marker"), "unchanged")
        self.assertEqual(restored.subsetString(), '"fid" = 1')
        self.assertEqual(list(restored.selectedFeatureIds()), [1])
        node = self.project.layerTreeRoot().findLayer(layer_id)
        self.assertIs(node.parent(), group)
        self.assertFalse(node.itemVisibilityChecked())
        self.assertEqual(self.project.isDirty(), before_dirty)
        self.assertEqual(restored.featureCount(), 1)

    def test_geojson_removed_from_project_and_disk(self):
        path = self.make_geojson()
        layer = self.add(path)
        identifier = layer.id()
        bridge.execute_delete(self.project, layer, bridge.plan_layer(layer), backup=False)
        self.assertFalse(path.exists())
        self.assertIsNone(self.project.mapLayer(identifier))

    def test_real_shapefile_bundle_removed_and_backed_up(self):
        path = self.root / "points.shp"
        dataset = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(str(path))
        created = dataset.CreateLayer("points", geom_type=ogr.wkbPoint)
        created.CreateField(ogr.FieldDefn("code", ogr.OFTInteger))
        feature = ogr.Feature(created.GetLayerDefn())
        feature.SetField("code", 1)
        feature.SetGeometry(ogr.CreateGeometryFromWkt("POINT (48 36)"))
        created.CreateFeature(feature)
        feature = created = dataset = None
        unrelated = path.with_suffix(".csv")
        unrelated.write_text("keep me", encoding="utf-8")
        layer = self.add(path)
        plan = bridge.plan_layer(layer)
        result = bridge.execute_delete(self.project, layer, plan, backup=True)
        self.assertFalse(path.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue((Path(result.backup_dir) / "points.dbf").exists())
        recovered = QgsVectorLayer(str(Path(result.backup_dir) / "points.shp"), "backup", "ogr")
        self.assertTrue(recovered.isValid())
        self.assertEqual(recovered.featureCount(), 1)

    def test_edit_mode_on_any_same_file_layer_blocks_deletion(self):
        target = self.add(str(self.gpkg) + "|layername=target")
        keep = self.add(str(self.gpkg) + "|layername=keep")
        self.assertTrue(keep.startEditing())
        with self.assertRaises(core.SourceError):
            bridge.execute_delete(self.project, target, bridge.plan_layer(target), backup=False)
        self.assertTrue(target.isValid())
        self.assertEqual(target.featureCount(), 3)
        keep.rollBack()

    def test_non_removable_layer_blocks_source_deletion_in_both_qt_bindings(self):
        from qgis.core import QgsMapLayer
        target = self.add(str(self.gpkg) + '|layername=target')
        target.setFlags(target.flags() & ~QgsMapLayer.LayerFlag.Removable)
        with self.assertRaisesRegex(core.SourceError, 'protected against removal'):
            bridge.execute_delete(self.project, target, bridge.plan_layer(target), backup=False)
        self.assertIs(self.project.mapLayer(target.id()), target)
        self.assertEqual(len(list(target.getFeatures())), 3)

    def test_join_dependency_blocks_deletion(self):
        target = self.add(str(self.gpkg) + "|layername=target")
        keep = self.add(str(self.gpkg) + "|layername=keep")
        join = QgsVectorLayerJoinInfo()
        join.setJoinLayer(target)
        join.setJoinFieldName("fid")
        join.setTargetFieldName("fid")
        keep.addJoin(join)
        with self.assertRaises(core.SourceError):
            bridge.execute_delete(self.project, target, bridge.plan_layer(target), backup=False)
        self.assertTrue(target.isValid())

    def test_memory_source_is_rejected(self):
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "temporary", "memory")
        with self.assertRaises(core.SourceError):
            bridge.plan_layer(layer)

    def test_non_geojson_json_provider_is_rejected(self):
        path = self.root / "other.json"
        path.write_text('{"hello":"world"}', encoding="utf-8")
        layer = QgsVectorLayer(str(path), "other", "ogr")
        with self.assertRaises(core.SourceError):
            bridge.plan_layer(layer)

    def test_changed_source_after_confirmation_is_rejected(self):
        first = self.add(str(self.gpkg) + "|layername=target")
        plan = bridge.plan_layer(first)
        first.setDataSource(str(self.gpkg) + "|layername=keep", "changed", "ogr")
        with self.assertRaises(core.SourceError):
            bridge.execute_delete(self.project, first, plan, backup=False)
        self.assertEqual(first.featureCount(), 3)

    def test_confirmation_backup_and_cancel_are_defaults(self):
        layer = self.add(str(self.gpkg) + "|layername=target")
        dialog = ConfirmDeleteDialog(bridge.plan_layer(layer), [layer])
        self.assertTrue(dialog.backup_requested)
        self.assertTrue(dialog.cancel_button.isDefault())
        self.assertFalse(dialog.delete_button.autoDefault())
        self.assertEqual(dialog.source_path.text(), str(self.gpkg))
        self.assertEqual(dialog.table_name.text(), "target")
        dialog.close()

    def make_iface(self, layer):
        class Iface:
            def layerTreeView(self): return self.view
            def mainWindow(self): return self.window
        iface = Iface()
        iface.window = QMainWindow()
        iface.view = QgsLayerTreeView()
        iface.model = QgsLayerTreeModel(self.project.layerTreeRoot())
        iface.view.setModel(iface.model)
        iface.view.setCurrentLayer(layer)
        return iface

    def test_action_inserted_after_remove_before_separator(self):
        layer = self.add(str(self.gpkg) + "|layername=target")
        iface = self.make_iface(layer)
        plugin = LayerEraserPlugin(iface)
        plugin.initGui()
        menu = QMenu()
        menu.addAction("Duplicate Layer")
        remove = menu.addAction("&Remove Layer…")
        separator = menu.addSeparator()
        separator.setObjectName("LayerActionSeparator")
        menu.addAction("Properties")
        plugin.populate_menu(menu)
        actions = menu.actions()
        i = actions.index(remove)
        self.assertEqual(actions[i + 1].objectName(), ACTION_NAME)
        self.assertIs(actions[i + 2], separator)
        plugin.populate_menu(menu)
        self.assertEqual(sum(a.objectName() == ACTION_NAME for a in menu.actions()), 1)
        plugin.unload()
        iface.window.close()
        iface.view.close()

    def test_action_not_added_for_group_selection(self):
        layer = self.add(str(self.gpkg) + "|layername=target")
        iface = self.make_iface(layer)
        group = self.project.layerTreeRoot().addGroup('Group')
        iface.view.setCurrentIndex(iface.view.proxyModel().mapFromSource(iface.model.node2index(group)))
        plugin = LayerEraserPlugin(iface)
        plugin.initGui()
        menu = QMenu()
        plugin.populate_menu(menu)
        self.assertFalse(any(a.objectName() == ACTION_NAME for a in menu.actions()))
        plugin.unload()

    def controller_iface(self, layer):
        iface = self.make_iface(layer)
        class Canvas:
            frozen = False
            def isFrozen(self): return self.frozen
            def freeze(self, value): self.frozen = value
            def stopRendering(self): pass
            def refresh(self): pass
        class Bar:
            def __init__(self): self.messages = []
            def pushSuccess(self, title, text): self.messages.append((title, text))
            def pushInfo(self, title, text): self.messages.append((title, text))
        iface.canvas = Canvas()
        iface.bar = Bar()
        iface.mapCanvases = lambda: [iface.canvas]
        iface.messageBar = lambda: iface.bar
        return iface

    def test_controller_cancel_leaves_source_and_project_unchanged(self):
        layer = self.add(str(self.gpkg) + "|layername=target")
        identifier = layer.id()
        iface = self.controller_iface(layer)
        plugin = LayerEraserPlugin(iface)
        with patch.object(ConfirmDeleteDialog, "exec", return_value=0):
            plugin.run(identifier)
        self.assertIs(self.project.mapLayer(identifier), layer)
        self.assertEqual(layer.featureCount(), 3)
        self.assertEqual(iface.bar.messages, [])

    def test_controller_accept_executes_real_source_deletion(self):
        layer = self.add(str(self.gpkg) + "|layername=target")
        identifier = layer.id()
        iface = self.controller_iface(layer)
        plugin = LayerEraserPlugin(iface)
        errors = []
        plugin._error = lambda text: errors.append(text)
        with patch.object(ConfirmDeleteDialog, "exec", return_value=1), patch.object(
            ConfirmDeleteDialog, "backup_requested", new=property(lambda self: False)
        ):
            plugin.run(identifier)
        self.assertEqual(errors, [])
        self.assertIsNone(self.project.mapLayer(identifier))
        self.assertEqual(len(iface.bar.messages), 1)
        self.assertFalse(iface.canvas.isFrozen())
        self.assertFalse(plugin.busy)
        deleted = QgsVectorLayer(str(self.gpkg) + "|layername=target", "deleted", "ogr")
        self.assertFalse(deleted.isValid())

    def test_controller_cancellation_restores_canvas_without_error(self):
        layer = self.add(str(self.gpkg) + '|layername=target')
        identifier = layer.id()
        iface = self.controller_iface(layer)
        plugin = LayerEraserPlugin(iface)
        errors = []
        plugin._error = lambda text: errors.append(text)
        with patch.object(ConfirmDeleteDialog, 'exec', return_value=1), patch(
            'layer_eraser.plugin.execute_delete', side_effect=core.OperationCancelled('cancel')
        ):
            plugin.run(identifier)
        self.assertEqual(errors, [])
        self.assertIs(self.project.mapLayer(identifier), layer)
        self.assertEqual(len(list(layer.getFeatures())), 3)
        self.assertIn('Cancelled', iface.bar.messages[0][1])
        self.assertFalse(iface.canvas.isFrozen())
        self.assertFalse(plugin.busy)


if __name__ == "__main__":
    unittest.main()
