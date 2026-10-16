# SPDX-License-Identifier: GPL-3.0-or-later
"""Launch via qgis --code PATH, using an isolated QGIS profile.

Writes internal QA screenshots and a JSON result under GEOF_SOURCE_QA_DIR.
All deletion targets are synthetic, freshly generated in that directory.
"""
import json
import os
from pathlib import Path
import sys
import traceback

from qgis.PyQt.QtCore import QPoint, QTimer
from qgis.PyQt.QtWidgets import QApplication, QDialog
from qgis.core import Qgis, QgsProject, QgsVectorLayer
from qgis.utils import iface

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from layer_eraser import plugin as plugin_module
from layer_eraser.dialogs import ConfirmDeleteDialog
from tests.test_core import make_gpkg


output = Path(os.environ["GEOF_SOURCE_QA_DIR"])
output.mkdir(parents=True, exist_ok=True)


def run():
    report = {"qgis": Qgis.QGIS_VERSION}
    project = QgsProject.instance()
    instance = None
    try:
        project.clear()
        path = output / "desktop_sample.gpkg"
        if path.exists():
            path.unlink()
        make_gpkg(path)
        target = QgsVectorLayer(str(path) + "|layername=target", 'Practice layer to delete', "ogr")
        keep = QgsVectorLayer(str(path) + "|layername=keep", 'Preserved layer', "ogr")
        assert target.isValid() and keep.isValid()
        project.addMapLayer(target)
        project.addMapLayer(keep)
        iface.setActiveLayer(target)
        view = iface.layerTreeView()
        view.setCurrentLayer(target)
        instance = plugin_module.LayerEraserPlugin(iface)
        instance.initGui()
        menu = view.menuProvider().createContextMenu()
        view.contextMenuAboutToShow.emit(menu)
        actions = menu.actions()
        index = next(i for i,a in enumerate(actions) if a.objectName() == plugin_module.ACTION_NAME)
        report["previous_action"] = actions[index - 1].text()
        report["next_action_object"] = actions[index + 1].objectName()
        assert "remove" in actions[index - 1].text().replace("&", "").lower()
        assert actions[index + 1].objectName() == "LayerActionSeparator"
        report["native_menu_placement"] = True
        menu.popup(QPoint(40, 40))
        QApplication.processEvents()
        menu.grab().save(str(output / "native_menu.png"))
        menu.close()
        class CancelDialog(ConfirmDeleteDialog):
            def exec(self):
                self.show()
                QApplication.processEvents()
                self.grab().save(str(output / "confirmation.png"))
                QTimer.singleShot(50, self.reject)
                return super().exec()
        plugin_module.ConfirmDeleteDialog = CancelDialog
        identifier = target.id()
        instance.run(identifier)
        assert project.mapLayer(identifier) is target and target.featureCount() == 3
        report["cancel_preserves_source"] = True
        class AcceptDialog(ConfirmDeleteDialog):
            def exec(self):
                self.backup_box.setChecked(False)
                QTimer.singleShot(50, self.accept)
                return super().exec()
        plugin_module.ConfirmDeleteDialog = AcceptDialog
        instance.run(identifier)
        assert project.mapLayer(identifier) is None
        assert keep.isValid() and keep.featureCount() == 3
        assert path.exists()
        reopened = QgsVectorLayer(str(path) + "|layername=target", "deleted", "ogr")
        assert not reopened.isValid()
        report["dialog_to_real_deletion"] = True
        report["surviving_layer_usable"] = True
        report["passed"] = True
    except Exception:
        report["passed"] = False
        report["error"] = traceback.format_exc()
    finally:
        if instance is not None:
            instance.unload()
        project.clear()
        project.setDirty(False)
        (output / "desktop_smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        QTimer.singleShot(50, QApplication.quit)


QTimer.singleShot(1000, run)
