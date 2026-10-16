# SPDX-License-Identifier: GPL-3.0-or-later
"""Install a separate context action immediately after QGIS Remove Layer."""
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import QApplication, QDialog, QMessageBox
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction
from qgis.core import Qgis, QgsMessageLog, QgsProject

from .bridge import affected_layers, check_project, execute_delete, plan_layer
from .core import OperationCancelled
from .dialogs import ConfirmDeleteDialog, DeleteProgressDialog


ACTION_NAME = "LayerEraserDeleteSource"
ACTION_TEXT = 'Delete Layer and Source…'


def insertion_point(menu):
    """Prefer QGIS' named separator, independent of interface translation."""
    actions = menu.actions()
    for action in actions:
        if action.objectName() == "LayerActionSeparator":
            return action
    candidates = {
        QCoreApplication.translate("QgsAppLayerTreeViewMenuProvider", "&Remove Layer…"),
        QCoreApplication.translate("QgsAppLayerTreeViewMenuProvider", "&Remove Layer..."),
        "Remove Layer", "Remove Layer…", "Remove Layer...",
    }
    def normalized(text):
        return text.replace("&", "").replace("…", "").replace("...", "").strip()
    candidates = {normalized(value) for value in candidates}
    for i, action in enumerate(actions):
        if normalized(action.text()) in candidates:
            return actions[i + 1] if i + 1 < len(actions) else None
    return None


class LayerEraserPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.view = None
        self.busy = False

    def initGui(self):
        self.view = self.iface.layerTreeView()
        self.view.contextMenuAboutToShow.connect(self.populate_menu)

    def unload(self):
        if self.view is not None:
            try:
                self.view.contextMenuAboutToShow.disconnect(self.populate_menu)
            except (TypeError, RuntimeError):
                pass
        self.view = None

    def populate_menu(self, menu):
        if self.busy or any(a.objectName() == ACTION_NAME for a in menu.actions()):
            return
        # Single explicit layer only: never recurse through selected groups.
        nodes = self.view.selectedNodes()
        selected = self.view.selectedLayers()
        current_node = self.view.currentNode()
        if len(nodes) != 1 or len(selected) != 1 or not hasattr(current_node, "layer"):
            return
        layer = selected[0]
        if current_node.layer() is not layer:
            return
        action = QAction(QIcon(str(Path(__file__).parent / "icon.svg")), ACTION_TEXT, menu)
        action.setObjectName(ACTION_NAME)
        action.setToolTip('Delete the source table or file and remove its layer references from this project')
        # Keep menu population cheap: detailed validation occurs on click.
        if layer.providerType() != "ogr":
            action.setEnabled(False)
            action.setToolTip('This version supports local vector GeoPackage tables, Shapefiles, and GeoJSON only.')
        layer_id = layer.id()
        action.triggered.connect(lambda checked=False, identifier=layer_id: self.run(identifier))
        menu.insertAction(insertion_point(menu), action)

    def run(self, layer_id):
        if self.busy:
            return
        project = QgsProject.instance()
        layer = project.mapLayer(layer_id)
        if layer is None:
            return
        try:
            plan = plan_layer(layer)
            references = affected_layers(project, plan)
            check_project(project, plan, references)
        except Exception as exc:
            self._error(str(exc))
            return
        dialog = ConfirmDeleteDialog(plan, references, self.iface.mainWindow())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        canvases = list(self.iface.mapCanvases()) if hasattr(self.iface, "mapCanvases") else [self.iface.mapCanvas()]
        frozen = [(canvas, canvas.isFrozen()) for canvas in canvases]
        self.busy = True
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        result = None
        progress = None
        error = None
        try:
            for canvas, _ in frozen:
                canvas.stopRendering()
                canvas.freeze(True)
            progress = DeleteProgressDialog(plan, self.iface.mainWindow())
            result = execute_delete(project, layer, plan, backup=dialog.backup_requested,
                                    progress=progress)
        except OperationCancelled:
            self.iface.messageBar().pushInfo("Layer Eraser", 'Cancelled. No source data was deleted.')
        except Exception as exc:
            error = str(exc)
        finally:
            if progress is not None:
                progress.close()
                progress.deleteLater()
            for canvas, was_frozen in frozen:
                canvas.freeze(was_frozen)
                if not was_frozen:
                    canvas.refresh()
            self.busy = False
            QApplication.restoreOverrideCursor()
        if error is not None:
            self._error(error)
            return
        if result is None:
            return
        self.iface.messageBar().pushSuccess("Layer Eraser", 'The source data and its project layer references were deleted.')
        if result.backup_dir or result.warnings:
            box = QMessageBox(self.iface.mainWindow())
            box.setWindowTitle('Deletion Result — Layer Eraser')
            box.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            box.setIcon(QMessageBox.Icon.Information)
            box.setText('The source data was deleted.')
            details = []
            if result.backup_dir:
                details.append('Backup folder:\n' + result.backup_dir)
                open_button = box.addButton('Open Backup Folder', QMessageBox.ButtonRole.ActionRole)
                open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(result.backup_dir)))
            details.extend(result.warnings)
            box.setInformativeText("\n\n".join(details))
            box.addButton('Close', QMessageBox.ButtonRole.AcceptRole)
            box.exec()

    def _error(self, message):
        QgsMessageLog.logMessage(message, "Layer Eraser", Qgis.MessageLevel.Warning)
        box = QMessageBox(self.iface.mainWindow())
        box.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        box.setWindowTitle('Deletion Not Completed — Layer Eraser')
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText('The deletion operation did not complete.')
        box.setInformativeText(message)
        box.addButton('Close', QMessageBox.ButtonRole.AcceptRole)
        box.exec()
