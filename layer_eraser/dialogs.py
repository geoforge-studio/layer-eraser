# SPDX-License-Identifier: GPL-3.0-or-later
"""English confirmation and cancellable backup progress UI."""
import time

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QLineEdit, QPlainTextEdit, QProgressDialog, QPushButton, QVBoxLayout,
)

from .core import OperationCancelled


class ConfirmDeleteDialog(QDialog):
    def __init__(self, plan, layers, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Delete Layer and Source — Layer Eraser')
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.resize(720, 570)
        layout = QVBoxLayout(self)
        heading = QLabel('Delete layer data at its source')
        heading.setStyleSheet("font-size: 20px; font-weight: 600; padding: 4px 0;")
        layout.addWidget(heading)
        description = QLabel(
            'This deletes the entire source table or file, regardless of layer filters or selected features.'
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        self.source_path = QLineEdit(str(plan.path))
        self.source_path.setReadOnly(True)
        self.source_path.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.source_path.setCursorPosition(0)
        types = {"geopackage": 'GeoPackage — one table', "shapefile": 'Shapefile — file bundle', "geojson": 'GeoJSON — standalone file'}
        form.addRow('Source type:', QLabel(types[plan.kind]))
        form.addRow('Source file:', self.source_path)
        if plan.table:
            self.table_name = QLineEdit(plan.table)
            self.table_name.setReadOnly(True)
            form.addRow('Table to delete:', self.table_name)
        layout.addLayout(form)
        layout.addWidget(QLabel('Project layers that will be removed:'))
        references = QPlainTextEdit("\n".join(layer.name() for layer in layers))
        option = references.document().defaultTextOption()
        option.setTextDirection(Qt.LayoutDirection.LeftToRight)
        option.setAlignment(Qt.AlignmentFlag.AlignLeft)
        references.document().setDefaultTextOption(option)
        references.setReadOnly(True)
        references.setMaximumHeight(90)
        layout.addWidget(references)
        if plan.kind == "geopackage":
            explanation = QLabel('Only the specified table will be deleted. Other layers in the GeoPackage will be preserved.')
            explanation.setWordWrap(True)
            layout.addWidget(explanation)
        else:
            layout.addWidget(QLabel('Files to delete:'))
            files = QPlainTextEdit("\n".join(p.name for p in plan.files))
            files.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            files.setReadOnly(True)
            files.setMaximumHeight(105)
            layout.addWidget(files)
        self.backup_box = QCheckBox('Create a backup before deleting')
        self.backup_box.setChecked(True)
        layout.addWidget(self.backup_box)
        suffix = ('For GeoPackage, the backup contains the entire database '
                  'and may take time for large files. Backup progress is shown '
                  'and can be cancelled before deletion.') if plan.kind == "geopackage" else ""
        backup_hint = QLabel('Backups are saved in GeoForge_Backups beside the source file. ' + suffix)
        backup_hint.setWordWrap(True)
        layout.addWidget(backup_hint)
        notice = QLabel('QGIS Undo cannot restore deleted source data. Other projects using this source will also be affected.')
        notice.setWordWrap(True)
        notice.setStyleSheet("padding: 8px; border: 1px solid #bd655b; border-radius: 4px;")
        layout.addWidget(notice)
        layout.addStretch()
        buttons = QDialogButtonBox(self)
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.setDefault(True)
        self.cancel_button.setAutoDefault(True)
        self.delete_button = QPushButton('Delete Source Data')
        self.delete_button.setAutoDefault(False)
        buttons.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.addButton(self.delete_button, QDialogButtonBox.ButtonRole.DestructiveRole)
        self.cancel_button.clicked.connect(self.reject)
        self.delete_button.clicked.connect(self.accept)
        layout.addWidget(buttons)
        self.cancel_button.setFocus()

    @property
    def backup_requested(self):
        return self.backup_box.isChecked()


class DeleteProgressDialog(QProgressDialog):
    """Process UI events during backup; cancellation stops before source DDL."""

    def __init__(self, plan, parent=None):
        super().__init__('Preparing source deletion…', 'Cancel', 0, 0, parent)
        self.setWindowTitle('Deleting Source Data — Layer Eraser')
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setMinimumDuration(0)
        self.setAutoClose(False)
        self.setAutoReset(False)
        self.resize(520, 150)
        self.plan = plan
        self.cancellable = True
        self.phase = ''
        self.last_update = 0.0
        self.show()

    def __call__(self, phase, completed=0, total=0):
        if self.cancellable and self.wasCanceled():
            raise OperationCancelled('Deletion cancelled. No source data was deleted.')
        now = time.monotonic()
        if phase == self.phase and now - self.last_update < .08 and completed != total:
            return
        self.last_update = now
        self.phase = phase
        if phase == 'deleting':
            self.cancellable = False
            self.setCancelButton(None)
            self.setLabelText('Deleting the selected source data…')
        elif phase == 'backup':
            description = ('Creating a full GeoPackage backup…' if self.plan.kind == 'geopackage'
                           else 'Creating a source backup…')
            self.setLabelText(description)
        else:
            self.setLabelText('Checking the source before deletion…')
        if phase == 'backup' and total > 0:
            self.setRange(0, 1000)
            self.setValue(min(1000, int(1000 * completed / total)))
        else:
            self.setRange(0, 0)
        QApplication.processEvents()
        if self.cancellable and self.wasCanceled():
            raise OperationCancelled('Deletion cancelled. No source data was deleted.')

    def keyPressEvent(self, event):
        if not self.cancellable and event.key() == Qt.Key.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)
