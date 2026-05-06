import os

from qtpy.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QCheckBox, QWidget, QFrame,
    QScrollArea, QSizePolicy, QFileDialog, QInputDialog, QMessageBox, QListWidget, QListWidgetItem,
)
from qtpy.QtCore import Qt, Signal, QTimer, QRect, QRectF
from qtpy.QtGui import QPixmap, QPainter, QColor, QPainterPath, QPen

from ui.styles import (
    BG_PRIMARY, BG_SECONDARY, BG_TERTIARY, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    BORDER_LIGHT, BORDER_MID, GREEN, GREEN_BG, GREEN_BORDER, ACCENT,
    ACCENT_BG, ACCENT_TEXT, ACCENT_BORDER,
)

_CATEGORIES = ["Models", "Materials", "HDAs", "Textures", "Lighting"]

_SUBCATEGORIES = {
    "Models":    ["Anatomy", "Organs", "Props", "Environments"],
    "Materials": ["Skin", "Metal", "Glass", "Fabric", "Organic", "Fluid", "GPU Open"],
    "HDAs":      ["Rigging", "FX", "Modeling"],
    "Textures":  ["Skin", "Metal", "Glass", "Fabric", "Organic"],
    "Lighting":  ["HDRIs", "Light rigs", "Poly Haven"],
}


class PublishDialog(QDialog):
    """Import / Edit dialog for ingesting assets into the library."""

    assetSubmitted = Signal(dict)

    def __init__(self, prefill=None, plugin=None, db_tags=None, db_projects=None,
                 disk_projects=None, active_project=None, parent=None):
        super().__init__(parent)
        self.prefill = prefill or {}
        self.plugin = plugin
        self._db_tags = db_tags or []
        self._db_projects = db_projects or []
        self._disk_projects = disk_projects or []
        self._active_project = active_project or ""
        self._is_edit = bool(self.prefill.get("_edit_id"))

        self.setWindowTitle("Edit Asset" if self._is_edit else "Import Asset")
        self.setFixedWidth(452)
        self.setStyleSheet(self._buildStylesheet())
        self._tags = list(self.prefill.get("tags", []))
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
        self._title_lbl = QLabel(self.windowTitle())
        self._title_lbl.setStyleSheet(
            "font-size: 13px; font-weight: 500; color: %s;" % TEXT_PRIMARY
        )
        h_layout.addWidget(self._title_lbl)
        h_layout.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            "border: none; background: transparent; color: %s; font-size: 14px;" % TEXT_TERTIARY
        )
        close_btn.clicked.connect(self.reject)
        h_layout.addWidget(close_btn)
        root.addWidget(header)

        # Body scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: %s; border: none; }" % BG_PRIMARY)

        body = QWidget()
        body.setStyleSheet("background: %s;" % BG_PRIMARY)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 14, 16, 14)
        body_layout.setSpacing(12)

        if not self._is_edit:
            # Files section
            body_layout.addWidget(self._field("FILES"))
            self._file_list = _FileListWidget()
            self._file_list.nameHint.connect(self._onNameHint)
            body_layout.addWidget(self._file_list)

            # Textures section
            body_layout.addWidget(self._field("TEXTURES"))
            self._texture_list = _FileListWidget()
            body_layout.addWidget(self._texture_list)

            # Thumbnails section — MAIN / CLAY / WIRE stacked
            body_layout.addWidget(self._field("THUMBNAILS"))
            self._thumb_material = _ThumbZone("MAIN")
            self._thumb_clay = _ThumbZone("CLAY")
            self._thumb_wire = _ThumbZone("WIRE")
            body_layout.addWidget(self._thumb_material)
            body_layout.addWidget(self._thumb_clay)
            body_layout.addWidget(self._thumb_wire)
        else:
            # Edit mode: show current file as info
            body_layout.addWidget(self._field("CURRENT FILE"))
            fp_lbl = QLabel(self.prefill.get("filepath", "—"))
            fp_lbl.setStyleSheet(
                "color: %s; font-size: 11px; background: %s; border: 1px solid %s;"
                " border-radius: 6px; padding: 6px 8px;" % (TEXT_TERTIARY, BG_SECONDARY, BORDER_LIGHT)
            )
            fp_lbl.setWordWrap(True)
            body_layout.addWidget(fp_lbl)

        # Asset name
        body_layout.addWidget(self._field("ASSET NAME"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Asset name")
        body_layout.addWidget(self.name_edit)

        # Category + Subcategory
        cs_row = QHBoxLayout()
        cs_row.setSpacing(10)

        cat_col = QVBoxLayout()
        cat_col.setSpacing(4)
        cat_col.addWidget(self._field("CATEGORY"))
        self.cat_combo = _NoScrollCombo()
        self.cat_combo.addItems(_CATEGORIES + ["＋ Add custom…"])
        cat_col.addWidget(self.cat_combo)

        sub_col = QVBoxLayout()
        sub_col.setSpacing(4)
        sub_col.addWidget(self._field("SUBCATEGORY"))
        self.sub_combo = _NoScrollCombo()
        sub_col.addWidget(self.sub_combo)

        cs_row.addLayout(cat_col)
        cs_row.addLayout(sub_col)
        body_layout.addLayout(cs_row)

        # Renderer + DCC
        rd_row = QHBoxLayout()
        rd_row.setSpacing(10)
        for label_text, attr, items in [
            ("RENDERER", "renderer_combo", ["Any", "Redshift", "Arnold", "V-Ray"]),
            ("DCC",      "dcc_combo",      ["Universal", "Houdini only", "Maya only"]),
        ]:
            col = QVBoxLayout()
            col.addWidget(self._field(label_text))
            combo = _NoScrollCombo()
            combo.addItems(items)
            setattr(self, attr, combo)
            col.addWidget(combo)
            rd_row.addLayout(col)
        body_layout.addLayout(rd_row)

        # Connect category/subcategory signals and seed subcategory list
        self.cat_combo.currentIndexChanged.connect(self._onCatIndexChanged)
        self.sub_combo.currentIndexChanged.connect(self._onSubIndexChanged)
        self._refreshSubcategory(_CATEGORIES[0])

        # Includes
        body_layout.addWidget(self._field("INCLUDES"))
        inc_row = QHBoxLayout()
        inc_row.setSpacing(16)
        self.chk_rig = QCheckBox("Rig")
        self.chk_mat = QCheckBox("Materials")
        for c in (self.chk_rig, self.chk_mat):
            inc_row.addWidget(c)
        inc_row.addStretch()
        body_layout.addLayout(inc_row)

        # Tags
        body_layout.addWidget(self._field("TAGS"))
        self.tag_container = _TagContainer(self._tags, suggestions=self._db_tags)
        body_layout.addWidget(self.tag_container)

        # Project
        body_layout.addWidget(self._field("PROJECT"))
        self.project_combo = _NoScrollCombo()
        self.project_combo.setEditable(True)
        self.project_combo.lineEdit().setPlaceholderText("Project name")
        body_layout.addWidget(self.project_combo)

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
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        submit_text = "Save Changes" if self._is_edit else "Import Asset"
        submit = QPushButton(submit_text)
        submit.setObjectName("submitBtn")
        submit.clicked.connect(self._onSubmit)
        f_layout.addWidget(cancel)
        f_layout.addWidget(submit)
        root.addWidget(footer)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _field(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-size: 10px; color: %s; font-family: 'IBM Plex Mono', monospace;"
            " letter-spacing: 1px; background: transparent;" % TEXT_TERTIARY
        )
        return lbl

    def _onNameHint(self, name):
        if not self.name_edit.text():
            self.name_edit.setText(name)

    def _buildProjectCombo(self):
        seen = set()
        projects = []
        # Active project first so it's the default
        if self._active_project:
            seen.add(self._active_project)
            projects.append(self._active_project)
        for p in list(self._disk_projects) + list(self._db_projects):
            if p and p not in seen:
                seen.add(p)
                projects.append(p)

        self.project_combo.clear()
        self.project_combo.addItems(projects)

        # Replace default MatchStartsWith completer with MatchContains
        from qtpy.QtWidgets import QCompleter
        comp = QCompleter(projects, self.project_combo)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.project_combo.setCompleter(comp)

    # ------------------------------------------------------------------
    # Populate
    # ------------------------------------------------------------------

    def _populate(self):
        # Name
        if self.prefill.get("name"):
            self.name_edit.setText(self.prefill["name"])

        # Category / subcategory
        if self.prefill.get("category"):
            idx = self.cat_combo.findText(self.prefill["category"])
            if idx >= 0:
                self.cat_combo.blockSignals(True)
                self.cat_combo.setCurrentIndex(idx)
                self.cat_combo.blockSignals(False)
                self._refreshSubcategory(self.prefill["category"])
            else:
                insert_at = self.cat_combo.count() - 1
                self.cat_combo.blockSignals(True)
                self.cat_combo.insertItem(insert_at, self.prefill["category"])
                self.cat_combo.setCurrentIndex(insert_at)
                self.cat_combo.blockSignals(False)
                self._refreshSubcategory(self.prefill["category"])
        if self.prefill.get("subcategory"):
            idx = self.sub_combo.findText(self.prefill["subcategory"])
            if idx >= 0:
                self.sub_combo.setCurrentIndex(idx)
            else:
                insert_at = max(self.sub_combo.count() - 1, 0)
                self.sub_combo.insertItem(insert_at, self.prefill["subcategory"])
                self.sub_combo.setCurrentIndex(insert_at)

        # Renderer / DCC
        if self.prefill.get("renderer"):
            idx = self.renderer_combo.findText(self.prefill["renderer"])
            if idx >= 0:
                self.renderer_combo.setCurrentIndex(idx)
        if self.prefill.get("dcc"):
            for text in [self.prefill["dcc"], self.prefill["dcc"] + " only"]:
                idx = self.dcc_combo.findText(text)
                if idx >= 0:
                    self.dcc_combo.setCurrentIndex(idx)
                    break

        # Includes
        if self.prefill.get("has_rig"):
            self.chk_rig.setChecked(bool(self.prefill["has_rig"]))
        if self.prefill.get("has_materials"):
            self.chk_mat.setChecked(bool(self.prefill["has_materials"]))

        # Author — stored internally, not shown in UI
        username = ""
        if self.plugin:
            try:
                username = self.plugin.core.username or ""
            except Exception:
                pass
        self._author = self.prefill.get("author") or username

        # Project — grouped combo: disk folders + library projects
        self._buildProjectCombo()
        target = self.prefill.get("project") or self._active_project
        if target:
            idx = self.project_combo.findText(target)
            if idx >= 0:
                self.project_combo.setCurrentIndex(idx)
            else:
                self.project_combo.setEditText(target)

    # ------------------------------------------------------------------
    # Category / subcategory signals
    # ------------------------------------------------------------------

    def _refreshSubcategory(self, cat):
        self.sub_combo.blockSignals(True)
        self.sub_combo.clear()
        self.sub_combo.addItems(_SUBCATEGORIES.get(cat, []) + ["＋ Add custom…"])
        self.sub_combo.blockSignals(False)

    def _onCatIndexChanged(self, idx):
        if self.cat_combo.itemText(idx) == "＋ Add custom…":
            text, ok = QInputDialog.getText(self, "Add Category", "Category name:")
            text = text.strip()
            self.cat_combo.blockSignals(True)
            if ok and text:
                insert_at = self.cat_combo.count() - 1
                self.cat_combo.insertItem(insert_at, text)
                self.cat_combo.setCurrentIndex(insert_at)
            else:
                self.cat_combo.setCurrentIndex(0)
            self.cat_combo.blockSignals(False)
            self._refreshSubcategory(self.cat_combo.currentText())
            return
        self._refreshSubcategory(self.cat_combo.currentText())

    def _onSubIndexChanged(self, idx):
        if self.sub_combo.itemText(idx) == "＋ Add custom…":
            text, ok = QInputDialog.getText(self, "Add Subcategory", "Subcategory name:")
            text = text.strip()
            self.sub_combo.blockSignals(True)
            if ok and text:
                insert_at = self.sub_combo.count() - 1
                self.sub_combo.insertItem(insert_at, text)
                self.sub_combo.setCurrentIndex(insert_at)
            else:
                self.sub_combo.setCurrentIndex(0)
            self.sub_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    def _onSubmit(self):
        name = self.name_edit.text().strip()
        if not name:
            self._highlightField(self.name_edit)
            return

        filepaths = []
        if not self._is_edit:
            filepaths = self._file_list.getFiles()
            if not filepaths:
                self._file_list.setError(True)
                QTimer.singleShot(2000, lambda: self._file_list.setError(False))
                return

        filetype = (
            self._file_list.getPrimaryType() if not self._is_edit
            else self.prefill.get("filetype", "")
        )

        thumbnails = {}
        texture_files = []
        if not self._is_edit:
            thumbnails = {
                "material": self._thumb_material.getImages(),
                "clay":     self._thumb_clay.getImages(),
                "wire":     self._thumb_wire.getImages(),
            }
            texture_files = self._texture_list.getFiles()

        data = {
            "name":          name,
            "version":       "v001",
            "category":      self.cat_combo.currentText(),
            "subcategory":   self.sub_combo.currentText(),
            "filepaths":     filepaths,
            "filetype":      filetype,
            "renderer":      self.renderer_combo.currentText(),
            "dcc":           self.dcc_combo.currentText().split()[0],
            "has_rig":       int(self.chk_rig.isChecked()),
            "has_textures":  int(bool(texture_files)),
            "has_materials": int(self.chk_mat.isChecked()),
            "tags":          self.tag_container.getTags(),
            "author":        self._author,
            "project":       self.project_combo.currentText().strip(),
            "_thumbnails":    thumbnails,
            "_texture_files": texture_files,
        }

        edit_id = self.prefill.get("_edit_id")
        if edit_id:
            data["_edit_id"] = edit_id

        self.assetSubmitted.emit(data)
        self.accept()

    def _highlightField(self, widget):
        red = "#e04040"
        orig = widget.styleSheet()
        widget.setStyleSheet(orig + "; border: 1px solid %s;" % red)
        QTimer.singleShot(2000, lambda: widget.setStyleSheet(orig))

    def _buildStylesheet(self):
        return """
            QDialog { background: %(bg)s; }
            #dialogHeader, #dialogFooter {
                background: %(bg2)s;
                border-bottom: 1px solid %(bl)s;
            }
            #dialogFooter { border-top: 1px solid %(bl)s; border-bottom: none; }
            #submitBtn {
                background: %(gbg)s; border: 1px solid %(gborder)s;
                border-radius: 6px; color: %(green)s; font-weight: 500;
                padding: 5px 14px;
            }
            #submitBtn:hover { background: #063a2a; }
        """ % {
            "bg": BG_PRIMARY, "bg2": BG_SECONDARY, "bl": BORDER_LIGHT,
            "gbg": GREEN_BG, "gborder": GREEN_BORDER, "green": GREEN,
        }


# ── Helper widgets ─────────────────────────────────────────────────────────────

class _NoScrollCombo(QComboBox):
    def wheelEvent(self, e):
        e.ignore()



class _FileListWidget(QFrame):
    filesChanged = Signal()
    nameHint     = Signal(str)

    _SS_EMPTY = (
        "QFrame { background: %(bg)s; border: none; border-radius: 6px; }"
        "QListWidget { background: transparent; border: none; outline: none; }"
        "QListWidget::item { border: none; outline: none; }"
        "QListWidget::item:focus { border: none; outline: none; }"
        "QScrollBar:vertical { width: 8px; background: transparent; }"
        "QScrollBar::handle:vertical { background: %(bm)s; border-radius: 4px; min-height: 20px; }"
        "QScrollBar::handle:vertical:hover { background: %(ts)s; }"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
    )
    _SS_FILLED = (
        "QFrame { background: %(bg)s; border: none; border-radius: 6px; }"
        "QListWidget { background: transparent; border: none; outline: none; }"
        "QListWidget::item { border: none; outline: none; }"
        "QListWidget::item:focus { border: none; outline: none; }"
        "QScrollBar:vertical { width: 8px; background: transparent; }"
        "QScrollBar::handle:vertical { background: %(bm)s; border-radius: 4px; min-height: 20px; }"
        "QScrollBar::handle:vertical:hover { background: %(ts)s; }"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
    )
    _SS_ERR = "QFrame { background: %(bg)s; border: 1px solid #e04040; border-radius: 6px; }"

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self._files = []

        ss_vals = dict(bg=BG_SECONDARY, bg2=BG_TERTIARY, bm=BORDER_MID, tp=TEXT_PRIMARY, ts=TEXT_SECONDARY)
        self._empty_ss  = self._SS_EMPTY % ss_vals
        self._filled_ss = self._SS_FILLED % ss_vals
        self._error_ss  = self._SS_ERR % ss_vals
        self.setStyleSheet(self._empty_ss)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.NoSelection)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._list.hide()
        outer.addWidget(self._list)

        self._placeholder = QLabel("Drop files here")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setFixedHeight(32)
        self._placeholder.setStyleSheet(
            "color: %s; font-size: 11px; background: transparent;" % TEXT_TERTIARY
        )
        outer.addWidget(self._placeholder)

        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.HLine)
        self._sep.setStyleSheet("color: %s; background: %s; border: none; max-height: 1px;" % (BORDER_MID, BORDER_MID))
        self._sep.hide()
        outer.addWidget(self._sep)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)
        add_btn = QPushButton("+ Add…")
        add_btn.setStyleSheet(
            "border: none; background: transparent; color: %s; font-size: 11px;"
            " text-align: left; padding: 0;" % ACCENT
        )
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._onBrowse)
        self._type_label = QLabel()
        self._type_label.setStyleSheet(
            "color: %s; font-size: 10px; background: transparent;" % TEXT_TERTIARY
        )
        bottom.addWidget(add_btn)
        bottom.addStretch()
        bottom.addWidget(self._type_label)
        outer.addLayout(bottom)

    _ROW_H = 24

    def _refresh(self):
        from qtpy.QtCore import QSize
        self._list.clear()
        for path in self._files:
            item = QListWidgetItem()
            item.setToolTip(path)
            item.setSizeHint(QSize(0, self._ROW_H))
            self._list.addItem(item)

            row = QWidget()
            row.setFixedHeight(self._ROW_H)
            row.setStyleSheet("background: transparent;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 0, 4, 0)
            rl.setSpacing(4)
            lbl = QLabel(os.path.basename(path))
            lbl.setStyleSheet("color: %s; font-size: 11px; background: transparent;" % TEXT_PRIMARY)
            lbl.setToolTip(path)
            rm = QPushButton("✕")
            rm.setFixedSize(14, 14)
            rm.setStyleSheet(
                "border: none; background: transparent; color: %s; font-size: 9px;"
                " padding: 0;" % TEXT_TERTIARY
            )
            rm.setCursor(Qt.PointingHandCursor)
            rm.clicked.connect(lambda _, p=path: self._removeFile(p))
            rl.addWidget(lbl, 1)
            rl.addWidget(rm)
            self._list.setItemWidget(item, row)

        has = bool(self._files)
        self._placeholder.setVisible(not has)
        self._list.setVisible(has)
        self._sep.setVisible(has)
        self.setStyleSheet(self._filled_ss if has else self._empty_ss)
        if has:
            visible = min(len(self._files), 6)
            self._list.setFixedHeight(visible * self._ROW_H + 4)

        exts = list(dict.fromkeys(
            os.path.splitext(p)[1].lower() for p in self._files if os.path.splitext(p)[1]
        ))
        self._type_label.setText(", ".join(exts) if exts else "")
        self.filesChanged.emit()

    def _onBrowse(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Files")
        self._addFiles(paths)

    def _addFiles(self, paths):
        first_add = not self._files
        for p in paths:
            if p and os.path.isfile(p) and p not in self._files:
                self._files.append(p)
        if first_add and self._files:
            self.nameHint.emit(os.path.splitext(os.path.basename(self._files[0]))[0])
        self._refresh()

    def _removeFile(self, path):
        if path in self._files:
            self._files.remove(path)
        self._refresh()

    def _removeSelected(self):
        for item in self._list.selectedItems():
            path = next((p for p in self._files if os.path.basename(p) == item.text()), None)
            if path:
                self._files.remove(path)
        self._refresh()

    def setError(self, on):
        if on:
            self.setStyleSheet(self._error_ss)
        else:
            self.setStyleSheet(self._filled_ss if self._files else self._empty_ss)

    def getFiles(self):
        return list(self._files)

    def getPrimaryType(self):
        return os.path.splitext(self._files[0])[1].lower() if self._files else ""

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._removeSelected()
        else:
            super().keyPressEvent(e)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self._addFiles([
            url.toLocalFile() for url in event.mimeData().urls()
            if url.toLocalFile() and os.path.isfile(url.toLocalFile())
        ])


class _ThumbZone(QFrame):
    """
    Thumbnail drop zone. Supports multiple images — index 0 is always the
    primary (shown first on the card). Click any tile to promote it to primary.
    """

    def __init__(self, label):
        super().__init__()
        self.setAcceptDrops(True)
        self._images = []
        self._label = label
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("background: %s; border-radius: 6px;" % BG_SECONDARY)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        # Tile strip inside a horizontal scroll area
        self._strip_widget = QWidget()
        self._strip_widget.setFixedHeight(_ThumbTile._SIZE)
        self._strip_widget.setStyleSheet("background: transparent;")
        self._strip_layout = QHBoxLayout(self._strip_widget)
        self._strip_layout.setContentsMargins(0, 0, 0, 0)
        self._strip_layout.setSpacing(4)
        self._strip_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        _SCROLL_BAR_H = 8
        self._strip_scroll = QScrollArea()
        self._strip_scroll.setWidget(self._strip_widget)
        self._strip_scroll.setWidgetResizable(False)
        self._strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._strip_scroll.setFixedHeight(_ThumbTile._SIZE)
        self._strip_scroll.setFrameShape(QFrame.NoFrame)
        self._strip_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
            "QScrollBar:horizontal { height: %(h)dpx; background: transparent; margin: 0; }"
            "QScrollBar::handle:horizontal { background: %(bm)s; border-radius: 4px; min-width: 20px; }"
            "QScrollBar::handle:horizontal:hover { background: %(ts)s; }"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }"
            % dict(h=_SCROLL_BAR_H, bm=BORDER_MID, ts=TEXT_SECONDARY)
        )
        self._strip_scroll.hide()
        outer.addWidget(self._strip_scroll)

        # Empty placeholder
        self._placeholder = QLabel("Drop images here")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet(
            "color: %s; font-size: 11px; background: transparent;" % TEXT_TERTIARY
        )
        self._placeholder.setFixedHeight(32)
        outer.addWidget(self._placeholder)

        # Separator (shown only when tiles present)
        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.HLine)
        self._sep.setStyleSheet("background: %s; border: none; max-height: 1px;" % BORDER_MID)
        self._sep.hide()
        outer.addWidget(self._sep)

        # Bottom row
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)
        add_btn = QPushButton("+ Add…")
        add_btn.setStyleSheet(
            "border: none; background: transparent; color: %s; font-size: 11px;"
            " text-align: left; padding: 0;" % ACCENT
        )
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._onBrowse)
        self._info_lbl = QLabel(label)
        self._info_lbl.setStyleSheet(
            "color: %s; font-size: 10px; background: transparent;" % TEXT_TERTIARY
        )
        bottom.addWidget(add_btn)
        bottom.addStretch()
        bottom.addWidget(self._info_lbl)
        outer.addLayout(bottom)

        self._updateHeight()

    def _onBrowse(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Images", "", "Images (*.png *.jpg *.jpeg)"
        )
        self._addImages(paths)

    def _addImages(self, paths):
        for p in paths:
            if p and os.path.isfile(p) and p not in self._images:
                self._images.append(p)
        self._refresh()

    def _remove(self, path):
        if path in self._images:
            self._images.remove(path)
            self._refresh()

    def _refresh(self):
        while self._strip_layout.count():
            item = self._strip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        has = bool(self._images)
        self._placeholder.setVisible(not has)
        self._strip_scroll.setVisible(has)
        self._sep.setVisible(has)

        for i, path in enumerate(self._images):
            tile = _ThumbTile(path, primary=(i == 0))
            tile.removeClicked.connect(lambda p=path: self._remove(p))
            self._strip_layout.addWidget(tile)

        n = len(self._images)
        if n:
            total_w = n * _ThumbTile._SIZE + max(0, n - 1) * 4
            self._strip_widget.setFixedWidth(total_w)
        self._info_lbl.setText(
            "%s  ·  %d  ·  drag to reorder" % (self._label, n) if n > 1 else self._label
        )

        self._updateHeight()

    _MAX_TILES_NO_SCROLL = 5

    def _updateHeight(self):
        if self._images:
            needs_scroll = len(self._images) > self._MAX_TILES_NO_SCROLL
            scroll_h = _ThumbTile._SIZE + (8 if needs_scroll else 0)
            self._strip_scroll.setFixedHeight(scroll_h)
            self.setFixedHeight(12 + scroll_h + 4 + 1 + 4 + 20)
        else:
            self._strip_scroll.setFixedHeight(_ThumbTile._SIZE)
            self.setFixedHeight(70)

    def getImages(self):
        return list(self._images)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasText():
            path = event.mimeData().text()
            if path in self._images:
                scroll_x = self._strip_scroll.horizontalScrollBar().value()
                tile_x = event.pos().x() - 8 + scroll_x
                insert_idx = max(0, min(len(self._images) - 1, tile_x // (_ThumbTile._SIZE + 4)))
                self._images.remove(path)
                self._images.insert(insert_idx, path)
                self._refresh()
                event.acceptProposedAction()
                return
        self._addImages([
            url.toLocalFile() for url in event.mimeData().urls()
            if url.toLocalFile()
            and os.path.isfile(url.toLocalFile())
            and os.path.splitext(url.toLocalFile())[1].lower() in (".png", ".jpg", ".jpeg")
        ])


class _ThumbTile(QWidget):
    """Thumbnail tile. Accent border when primary. Drag to reorder, X to remove."""

    removeClicked = Signal()
    _SIZE = 76

    def __init__(self, path, primary=False):
        super().__init__()
        self._path       = path
        self._primary    = primary
        self._hover      = False
        self._drag_start = None
        self.setFixedSize(self._SIZE, self._SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setMouseTracking(True)

        px = QPixmap(path)
        if not px.isNull():
            self._px = px.scaled(
                self._SIZE, self._SIZE,
                Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
            )
        else:
            self._px = None

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        r = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(r, 4, 4)
        p.setClipPath(clip)

        p.fillRect(self.rect(), QColor("#1a1a1a"))
        if self._px:
            x = (self._SIZE - self._px.width())  // 2
            y = (self._SIZE - self._px.height()) // 2
            p.drawPixmap(x, y, self._px)
        if self._hover and not self._primary:
            p.fillRect(self.rect(), QColor(0, 0, 0, 55))

        p.setClipping(False)

        # Border
        if self._primary:
            p.setPen(QPen(QColor(ACCENT), 2.0))
        elif self._hover:
            p.setPen(QPen(QColor(255, 255, 255, 80), 1.0))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 25), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 3.5, 3.5)

        # Primary dot indicator (bottom-left)
        if self._primary:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(QRectF(4, self._SIZE - 10, 6, 6))

        # X button (top-right, on hover)
        if self._hover:
            xr = QRectF(self._SIZE - 16, 2, 14, 14)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 160))
            p.drawEllipse(xr)
            cx, cy = xr.center().x(), xr.center().y()
            p.setPen(QPen(QColor(255, 255, 255, 210), 1.5))
            p.drawLine(int(cx - 3), int(cy - 3), int(cx + 3), int(cy + 3))
            p.drawLine(int(cx + 3), int(cy - 3), int(cx - 3), int(cy + 3))

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_start   = e.pos()
            self._press_on_x   = QRect(self._SIZE - 16, 2, 14, 14).contains(e.pos())
        e.accept()

    def mouseMoveEvent(self, e):
        if not (e.buttons() & Qt.LeftButton) or self._drag_start is None:
            return
        if (e.pos() - self._drag_start).manhattanLength() < 8:
            return
        self._drag_start = None
        from qtpy.QtGui import QDrag
        from qtpy.QtCore import QMimeData
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(self._path)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(e.pos())
        drag.exec_(Qt.MoveAction)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drag_start is not None:
            if self._press_on_x:
                self.removeClicked.emit()
            self._drag_start = None
        e.accept()


class _TagContainer(QWidget):
    """Tag pills + input + inline suggestion dropdown matching the search bar style."""

    def __init__(self, initial_tags=None, suggestions=None):
        super().__init__()
        self._tags = list(initial_tags or [])
        self._suggestions = list(suggestions or [])

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(3)

        # ── pill + input row (same look as #searchInput) ─────────────────
        pill_frame = QFrame()
        pill_frame.setObjectName("tagInputFrame")
        pill_frame.setStyleSheet(
            "#tagInputFrame { background: %s; border: 1px solid %s; border-radius: 6px; }"
            % (BG_PRIMARY, BORDER_MID)
        )
        self._layout = QHBoxLayout(pill_frame)
        self._layout.setContentsMargins(8, 5, 8, 5)
        self._layout.setSpacing(4)

        self._input = QLineEdit()
        self._input.setPlaceholderText("+ tag")
        self._input.setFrame(False)
        self._input.setStyleSheet(
            "background: transparent; border: none; color: %s;"
            " font-size: 12px; font-family: 'IBM Plex Sans', sans-serif;"
            " min-width: 60px;" % TEXT_PRIMARY
        )
        self._input.returnPressed.connect(self._addTagFromInput)
        self._input.textChanged.connect(self._onTextChanged)

        # ── suggestion dropdown (same look as TagDropdown) ────────────────
        self._sugg_frame = QFrame()
        self._sugg_frame.setObjectName("tagSuggFrame")
        self._sugg_frame.setStyleSheet(
            "#tagSuggFrame { background: %s; border: 1px solid %s; border-radius: 6px; }"
            % (BG_PRIMARY, BORDER_MID)
        )
        self._sugg_layout = QVBoxLayout(self._sugg_frame)
        self._sugg_layout.setContentsMargins(0, 4, 0, 4)
        self._sugg_layout.setSpacing(0)
        self._sugg_frame.hide()

        outer.addWidget(pill_frame)
        outer.addWidget(self._sugg_frame)

        self._rebuild()

    def _onTextChanged(self, text):
        q = text.strip().lower()
        if not q:
            self._sugg_frame.hide()
            return
        matches = [s for s in self._suggestions if q in s.lower() and s not in self._tags][:8]
        self._showSuggestions(matches)

    def _showSuggestions(self, matches):
        while self._sugg_layout.count():
            item = self._sugg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not matches:
            self._sugg_frame.hide()
            return

        # Header — same as TagDropdown._addHeader
        hdr = QLabel("TAGS")
        hdr.setStyleSheet(
            "color: %s; font-size: 10px; font-family: 'IBM Plex Mono', monospace;"
            " letter-spacing: 1px; padding: 4px 12px 2px; background: transparent;"
            % TEXT_TERTIARY
        )
        self._sugg_layout.addWidget(hdr)

        for tag in matches:
            btn = QPushButton("# " + tag)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.setStyleSheet(
                "QPushButton {"
                "  background: transparent; border: none; color: %s;"
                "  font-size: 12px; font-family: 'IBM Plex Sans', sans-serif;"
                "  padding: 0 12px; text-align: left;"
                "}"
                "QPushButton:hover { background: %s; color: %s; }"
                % (TEXT_SECONDARY, BG_SECONDARY, TEXT_PRIMARY)
            )
            btn.clicked.connect(lambda _, t=tag: self._addTagFromSuggestion(t))
            self._sugg_layout.addWidget(btn)

        self._sugg_frame.setFixedHeight(min((1 + len(matches)) * 28 + 16, 220))
        self._sugg_frame.show()

    def _addTagFromInput(self):
        text = self._input.text().strip()
        self._input.clear()
        self._sugg_frame.hide()
        if text and text not in self._tags:
            self._tags.append(text)
            self._rebuild()

    def _addTagFromSuggestion(self, tag):
        self._input.clear()
        self._sugg_frame.hide()
        if tag and tag not in self._tags:
            self._tags.append(tag)
            self._rebuild()

    def _rebuild(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w and w is not self._input:
                w.deleteLater()
        for tag in self._tags:
            pill = _TagPill(tag)
            pill.removed.connect(self._removeTag)
            self._layout.addWidget(pill)
        self._layout.addWidget(self._input)
        self._layout.addStretch()

    def _removeTag(self, tag):
        if tag in self._tags:
            self._tags.remove(tag)
        self._rebuild()

    def getTags(self):
        return list(self._tags)


class _TagPill(QWidget):
    removed = Signal(str)

    def __init__(self, tag):
        super().__init__()
        self._tag = tag
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "background: %s; border: 0.5px solid %s; border-radius: 10px;"
            % (ACCENT_BG, ACCENT_BORDER)
        )
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 1, 2, 1)
        layout.setSpacing(2)

        label = QLabel(tag)
        label.setStyleSheet(
            "color: %s; font-size: 10px; border: none; background: transparent;"
            " font-family: 'IBM Plex Sans', sans-serif;" % ACCENT_TEXT
        )
        layout.addWidget(label)

        btn = QPushButton("×")
        btn.setFixedSize(14, 14)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton {"
            "  background: transparent; border: none; color: %s;"
            "  font-size: 11px; padding: 0; margin: 0;"
            "}"
            "QPushButton:hover { color: %s; }"
            % (ACCENT_TEXT, TEXT_PRIMARY)
        )
        btn.clicked.connect(lambda: self.removed.emit(self._tag))
        layout.addWidget(btn)

        self.setFixedHeight(20)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
