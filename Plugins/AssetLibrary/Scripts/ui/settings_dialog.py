import os

from qtpy.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QWidget, QFrame, QScrollArea, QSizePolicy,
    QFileDialog, QProgressBar,
)
from qtpy.QtCore import Qt, Signal, QThread

from ui.styles import (
    BG_PRIMARY, BG_SECONDARY, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    BORDER_LIGHT, BORDER_MID, GREEN, GREEN_BG, GREEN_BORDER, ACCENT,
)


class SettingsDialog(QDialog):
    """Plugin settings window. Expandable — add new sections below Library."""

    saved = Signal()

    def __init__(self, plugin=None, parent=None):
        super().__init__(parent)
        self.plugin = plugin
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

        # ── Add future sections here ──────────────────────────────────

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

    # ------------------------------------------------------------------

    def _populate(self):
        if self.plugin:
            current = self.plugin._getAssetLibRoot() or ""
            self.path_edit.setText(current)

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

    def _onSave(self):
        path = self.path_edit.text().strip()
        if path and not os.path.isdir(path):
            self.path_edit.setStyleSheet(
                "QLineEdit { border-color: #c0392b; }"
            )
            return
        if self.plugin and path:
            self.plugin.setLibraryRoot(path)
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
