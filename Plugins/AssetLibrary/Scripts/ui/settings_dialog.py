import os

from qtpy.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QWidget, QFrame, QScrollArea, QSizePolicy,
    QFileDialog, QProgressBar, QSpinBox, QMessageBox,
)
from qtpy.QtCore import Qt, Signal, QThread

from ui.styles import (
    BG_PRIMARY, BG_SECONDARY, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    BORDER_LIGHT, BORDER_MID, GREEN, GREEN_BG, GREEN_BORDER, ACCENT,
)


class SettingsDialog(QDialog):
    """Plugin settings window. Expandable — add new sections below Library."""

    saved = Signal()
    cardWidthChanged = Signal(int)

    def __init__(self, plugin=None, parent=None, card_width=235):
        super().__init__(parent)
        self.plugin = plugin
        self._card_width = card_width
        self.setWindowTitle("Asset Library — Settings")
        self.setFixedWidth(480)
        self.setMinimumHeight(200)
        self.setStyleSheet(self._buildStylesheet())
        self._build()
        self._populate()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QWidget()
        header.setObjectName("dialogHeader")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 13, 16, 13)
        title = QLabel("Settings")
        title.setStyleSheet("font-size: 13px; font-weight: 500; color: %s;" % TEXT_PRIMARY)
        h_layout.addWidget(title)
        h_layout.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            "border: none; background: transparent; color: %s; font-size: 14px;" % TEXT_TERTIARY
        )
        close_btn.clicked.connect(self.reject)
        h_layout.addWidget(close_btn)
        root.addWidget(header)

        # Body scroll area (allows future sections to grow)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: %s; border: none; }" % BG_PRIMARY)

        body = QWidget()
        body.setStyleSheet("background: %s;" % BG_PRIMARY)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 16, 16, 16)
        body_layout.setSpacing(20)

        body_layout.addWidget(self._buildLibrarySection())
        body_layout.addWidget(self._buildDisplaySection())
        body_layout.addWidget(self._buildOmittedSection())

        body_layout.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # Footer
        footer = QWidget()
        footer.setObjectName("dialogFooter")
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(16, 10, 16, 10)
        f_layout.setSpacing(8)
        f_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("submitBtn")
        save_btn.clicked.connect(self._onSave)
        f_layout.addWidget(cancel_btn)
        f_layout.addWidget(save_btn)
        root.addWidget(footer)

    def _buildLibrarySection(self):
        section = _Section("LIBRARY")

        section.addField("LIBRARY ROOT PATH")
        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Path to NAS library root…")
        path_row.addWidget(self.path_edit, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._onBrowse)
        path_row.addWidget(browse_btn)
        section.addLayout(path_row)

        hint = QLabel("The folder that contains  library.db  and your 03_Production tree.")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "font-size: 10px; color: %s; background: transparent;" % TEXT_TERTIARY
        )
        section.addWidget(hint)

        # Scan row
        scan_row = QHBoxLayout()
        scan_row.setSpacing(8)
        self.scan_btn = QPushButton("Scan / Sync Library")
        self.scan_btn.setObjectName("scanBtn")
        self.scan_btn.clicked.connect(self._onScan)
        scan_row.addWidget(self.scan_btn)
        self.scan_status = QLabel("")
        self.scan_status.setStyleSheet(
            "font-size: 11px; color: %s; background: transparent;"
            " font-family: 'IBM Plex Mono', monospace;" % TEXT_TERTIARY
        )
        scan_row.addWidget(self.scan_status, 1)
        section.addLayout(scan_row)

        return section

    def _buildDisplaySection(self):
        section = _Section("DISPLAY")

        section.addField("THUMBNAIL SIZE (px)")
        size_row = QHBoxLayout()
        size_row.setSpacing(6)
        self.card_width_spin = QSpinBox()
        self.card_width_spin.setRange(90, 425)
        self.card_width_spin.setValue(self._card_width)
        self.card_width_spin.setSuffix(" px")
        self.card_width_spin.setStyleSheet(
            "QSpinBox { background: %(bg2)s; border: 1px solid %(bl)s;"
            " border-radius: 6px; padding: 4px 8px; color: %(tp)s; font-size: 12px; }"
            "QSpinBox:focus { border-color: %(bm)s; }"
            "QSpinBox::up-button, QSpinBox::down-button { width: 18px; }"
            % {"bg2": BG_SECONDARY, "bl": BORDER_LIGHT, "bm": BORDER_MID, "tp": TEXT_PRIMARY}
        )
        size_row.addWidget(self.card_width_spin)
        size_row.addStretch()
        section.addLayout(size_row)

        hint = QLabel("Width of each asset card in the grid (90 – 425 px, default 235).")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "font-size: 10px; color: %s; background: transparent;" % TEXT_TERTIARY
        )
        section.addWidget(hint)

        return section

    def _buildOmittedSection(self):
        self._omitted_section = _Section("OMITTED ASSETS")

        self._omitted_list = QWidget()
        self._omitted_list.setStyleSheet("background: transparent;")
        self._omitted_list_layout = QVBoxLayout(self._omitted_list)
        self._omitted_list_layout.setContentsMargins(0, 0, 0, 0)
        self._omitted_list_layout.setSpacing(4)

        self._omitted_section.addWidget(self._omitted_list)
        return self._omitted_section

    def _populateOmitted(self):
        layout = self._omitted_list_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        assets = []
        db = self._getDB()
        if db:
            try:
                assets = db.get_omitted_assets()
            finally:
                db.close()

        if not assets:
            empty = QLabel("No omitted assets.")
            empty.setStyleSheet(
                "font-size: 11px; color: %s; background: transparent;"
                " font-family: 'IBM Plex Mono', monospace;" % TEXT_TERTIARY
            )
            layout.addWidget(empty)
            return

        for asset in assets:
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            cat = asset.get("subcategory") or asset.get("category", "")
            name_lbl = QLabel(asset["name"])
            name_lbl.setStyleSheet("font-size: 11px; color: %s; background: transparent;" % TEXT_PRIMARY)
            cat_lbl = QLabel(cat)
            cat_lbl.setStyleSheet(
                "font-size: 10px; color: %s; background: transparent;"
                " font-family: 'IBM Plex Mono', monospace;" % TEXT_TERTIARY
            )

            restore_btn = QPushButton("Restore")
            restore_btn.setFixedHeight(24)
            restore_btn.setStyleSheet(
                "QPushButton { background: transparent; border: 1px solid %s;"
                " border-radius: 4px; padding: 2px 8px; color: %s; font-size: 10px; }"
                "QPushButton:hover { border-color: %s; color: %s; }" % (
                    BORDER_LIGHT, TEXT_SECONDARY, BORDER_MID, TEXT_PRIMARY
                )
            )
            delete_btn = QPushButton("Delete")
            delete_btn.setFixedHeight(24)
            delete_btn.setStyleSheet(
                "QPushButton { background: transparent; border: 1px solid #5a2020;"
                " border-radius: 4px; padding: 2px 8px; color: #c06060; font-size: 10px; }"
                "QPushButton:hover { border-color: #8b3030; color: #e08080; }"
            )

            asset_id = asset["id"]
            restore_btn.clicked.connect(lambda _, aid=asset_id: self._onRestoreAsset(aid))
            delete_btn.clicked.connect(lambda _, aid=asset_id, n=asset["name"]: self._onDeleteAsset(aid, n))

            row_layout.addWidget(name_lbl, 1)
            row_layout.addWidget(cat_lbl)
            row_layout.addWidget(restore_btn)
            row_layout.addWidget(delete_btn)
            layout.addWidget(row)

    def _getDB(self):
        if self.plugin:
            return self.plugin.getDB()
        return None

    def _onRestoreAsset(self, asset_id):
        db = self._getDB()
        if not db:
            return
        try:
            db.restore_asset(asset_id)
        finally:
            db.close()
        self._populateOmitted()
        self.saved.emit()

    def _onDeleteAsset(self, asset_id, name):
        msg = QMessageBox(self)
        msg.setWindowTitle("Delete permanently")
        msg.setText("Permanently delete <b>%s</b>?" % name)
        msg.setInformativeText("This cannot be undone. Files on disk will not be affected.")
        msg.setIcon(QMessageBox.Warning)
        msg.setStandardButtons(QMessageBox.Cancel)
        del_btn = msg.addButton("Delete", QMessageBox.DestructiveRole)
        msg.setDefaultButton(QMessageBox.Cancel)
        msg.exec_()
        if msg.clickedButton() is not del_btn:
            return
        db = self._getDB()
        if not db:
            return
        try:
            db.delete_asset(asset_id)
        finally:
            db.close()
        self._populateOmitted()
        self.saved.emit()

    # ------------------------------------------------------------------

    def _populate(self):
        if self.plugin:
            current = self.plugin._getAssetLibRoot() or ""
            self.path_edit.setText(current)
        self._populateOmitted()

    def _onBrowse(self):
        current = self.path_edit.text().strip()
        path = QFileDialog.getExistingDirectory(
            self, "Select Library Root Folder", current or ""
        )
        if path:
            self.path_edit.setText(path)

    def _onScan(self):
        # Save current path first so the scanner picks it up
        path = self.path_edit.text().strip()
        if not path or not os.path.isdir(path):
            self.scan_status.setText("Set a valid path first.")
            self.scan_status.setStyleSheet(
                "font-size: 11px; color: #c0392b; background: transparent;"
                " font-family: 'IBM Plex Mono', monospace;"
            )
            return

        if self.plugin:
            self.plugin.setLibraryRoot(path)

        self.scan_btn.setEnabled(False)
        self.scan_status.setText("Scanning…")
        self.scan_status.setStyleSheet(
            "font-size: 11px; color: %s; background: transparent;"
            " font-family: 'IBM Plex Mono', monospace;" % TEXT_TERTIARY
        )

        self._scanner_thread = _ScanThread(self.plugin, path)
        self._scanner_thread.finished.connect(self._onScanFinished)
        self._scanner_thread.start()

    def _onScanFinished(self, result):
        self.scan_btn.setEnabled(True)
        if "error" in result:
            self.scan_status.setText("Error: %s" % result["error"])
            self.scan_status.setStyleSheet(
                "font-size: 11px; color: #c0392b; background: transparent;"
                " font-family: 'IBM Plex Mono', monospace;"
            )
        else:
            self.scan_status.setText(
                "+%d  ~%d  -%d" % (result["added"], result["updated"], result["removed"])
            )
            self.scan_status.setStyleSheet(
                "font-size: 11px; color: %s; background: transparent;"
                " font-family: 'IBM Plex Mono', monospace;" % GREEN
            )
            self.saved.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._onSave()
        else:
            super().keyPressEvent(event)

    def _onSave(self):
        path = self.path_edit.text().strip()
        if path and not os.path.isdir(path):
            self.path_edit.setStyleSheet(
                "QLineEdit { border-color: #c0392b; }"
            )
            return
        if self.plugin and path:
            self.plugin.setLibraryRoot(path)
        self.cardWidthChanged.emit(self.card_width_spin.value())
        self.saved.emit()
        self.accept()

    def _buildStylesheet(self):
        return """
            QDialog { background: %(bg)s; }
            #dialogHeader {
                background: %(bg2)s;
                border-bottom: 1px solid %(bl)s;
            }
            #dialogFooter {
                background: %(bg2)s;
                border-top: 1px solid %(bl)s;
            }
            QPushButton {
                background: transparent;
                border: 1px solid %(bl)s;
                border-radius: 6px;
                padding: 5px 12px;
                color: %(ts)s;
                font-size: 11px;
            }
            QPushButton:hover {
                border-color: %(bm)s;
                color: %(tp)s;
            }
            #submitBtn {
                background: %(gbg)s;
                border: 1px solid %(gborder)s;
                color: %(green)s;
                font-weight: 500;
            }
            #submitBtn:hover { background: #063a2a; }
            #scanBtn {
                background: %(gbg)s;
                border: 1px solid %(gborder)s;
                color: %(green)s;
                font-size: 11px;
                padding: 5px 12px;
            }
            #scanBtn:hover { background: #063a2a; }
            #scanBtn:disabled { opacity: 0.4; }
            QLineEdit {
                background: %(bg2)s;
                border: 1px solid %(bl)s;
                border-radius: 6px;
                padding: 5px 8px;
                color: %(tp)s;
                font-size: 12px;
            }
            QLineEdit:focus { border-color: %(bm)s; }
        """ % {
            "bg": BG_PRIMARY, "bg2": BG_SECONDARY,
            "bl": BORDER_LIGHT, "bm": BORDER_MID,
            "tp": TEXT_PRIMARY, "ts": TEXT_SECONDARY,
            "gbg": GREEN_BG, "gborder": GREEN_BORDER, "green": GREEN,
        }


# ── Helper widgets ────────────────────────────────────────────────────────────

class _Section(QWidget):
    """Labeled settings section with a subtle top border."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

        header = QLabel(title)
        header.setStyleSheet(
            "font-size: 10px; font-weight: 500; color: %s;"
            " font-family: 'IBM Plex Mono', monospace;"
            " letter-spacing: 1px; background: transparent;"
            " padding-bottom: 6px; border-bottom: 1px solid %s;"
            % (TEXT_TERTIARY, BORDER_LIGHT)
        )
        self._layout.addWidget(header)

    def addField(self, label_text):
        lbl = QLabel(label_text)
        lbl.setStyleSheet(
            "font-size: 10px; color: %s; font-family: 'IBM Plex Mono', monospace;"
            " letter-spacing: 1px; background: transparent;" % TEXT_TERTIARY
        )
        self._layout.addWidget(lbl)

    def addWidget(self, widget):
        self._layout.addWidget(widget)

    def addLayout(self, layout):
        self._layout.addLayout(layout)


class _ScanThread(QThread):
    finished = Signal(dict)

    def __init__(self, plugin, asset_lib):
        super().__init__()
        self._plugin    = plugin
        self._asset_lib = asset_lib

    def run(self):
        try:
            from core.db import AssetDB
            from core.scanner import PrismScanner

            db_path = os.path.join(self._asset_lib, "library.db")
            db = AssetDB(db_path)
            db.connect()
            try:
                core = self._plugin.core if self._plugin else None
                scanner = PrismScanner(db, self._asset_lib, core=core)
                result = scanner.sync()
            finally:
                db.close()
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit({"error": str(e), "added": 0, "updated": 0, "removed": 0})
