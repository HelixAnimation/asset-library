import os

from qtpy.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QCheckBox, QWidget, QFrame,
    QScrollArea, QSizePolicy, QFileDialog,
)
from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QFont

from ui.styles import (
    BG_PRIMARY, BG_SECONDARY, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
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

_FILETYPES = {
    "Models":    [".usd", ".abc", ".fbx"],
    "Materials": [".usd", ".rs", ".mtlx"],
    "HDAs":      [".usd", ".hda", ".otl"],
    "Textures":  [".exr", ".tx", ".png", ".tif"],
    "Lighting":  [".usd", ".exr", ".hdr", ".hip", ".ma"],
}


class PublishDialog(QDialog):
    """Publish / Import dialog for ingesting new assets into the library."""

    assetSubmitted = Signal(dict)

    def __init__(self, prefill=None, parent=None):
        super().__init__(parent)
        self.prefill = prefill or {}
        self.setWindowTitle("Import Asset")
        self.setFixedWidth(430)
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
        title = QLabel("Import Asset")
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

        # Source
        body_layout.addWidget(self._field("SOURCE"))
        self.src_disk  = _SourceOption("From disk",          "Browse for a file on disk")
        self.src_prism = _SourceOption("From Prism publish", "Use a Prism-published product")
        self.src_disk.setActive(True)
        self.src_disk.clicked.connect(lambda: self._selectSource("disk"))
        self.src_prism.clicked.connect(lambda: self._selectSource("prism"))
        src_row = QHBoxLayout()
        src_row.setSpacing(8)
        src_row.addWidget(self.src_disk)
        src_row.addWidget(self.src_prism)
        body_layout.addLayout(src_row)

        # File path
        body_layout.addWidget(self._field("FILE PATH"))
        fp_row = QHBoxLayout()
        fp_row.setSpacing(6)
        self.filepath_edit = QLineEdit()
        self.filepath_edit.setPlaceholderText("Select a file…")
        fp_row.addWidget(self.filepath_edit, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._onBrowse)
        fp_row.addWidget(browse_btn)
        body_layout.addLayout(fp_row)

        # Name + Version row
        nv_row = QHBoxLayout()
        nv_row.setSpacing(10)
        name_col = QVBoxLayout()
        name_col.addWidget(self._field("ASSET NAME"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Skin SSS")
        name_col.addWidget(self.name_edit)
        ver_col = QVBoxLayout()
        ver_col.addWidget(self._field("VERSION"))
        self.version_edit = QLineEdit("v001")
        ver_col.addWidget(self.version_edit)
        nv_row.addLayout(name_col, 2)
        nv_row.addLayout(ver_col, 1)
        body_layout.addLayout(nv_row)

        # Category + Subcategory
        cs_row = QHBoxLayout()
        cs_row.setSpacing(10)
        cat_col = QVBoxLayout()
        cat_col.addWidget(self._field("CATEGORY"))
        self.cat_combo = QComboBox()
        self.cat_combo.addItems(_CATEGORIES)
        cat_col.addWidget(self.cat_combo)
        sub_col = QVBoxLayout()
        sub_col.addWidget(self._field("SUBCATEGORY"))
        self.sub_combo = QComboBox()
        sub_col.addWidget(self.sub_combo)
        cs_row.addLayout(cat_col)
        cs_row.addLayout(sub_col)
        body_layout.addLayout(cs_row)

        # Filetype + Renderer + DCC — created BEFORE connecting cat_combo signal
        frd_row = QHBoxLayout()
        frd_row.setSpacing(10)
        for label_text, attr in [("FILE TYPE", "ft_combo"), ("RENDERER", "renderer_combo"), ("DCC", "dcc_combo")]:
            col = QVBoxLayout()
            col.addWidget(self._field(label_text))
            combo = QComboBox()
            setattr(self, attr, combo)
            col.addWidget(combo)
            frd_row.addLayout(col)
        self.renderer_combo.addItems(["Any", "Redshift", "Arnold", "V-Ray"])
        self.dcc_combo.addItems(["Universal", "Houdini only", "Maya only"])
        body_layout.addLayout(frd_row)

        # Connect signal and populate now that ft_combo exists
        self.cat_combo.currentTextChanged.connect(self._onCategoryChanged)
        self._onCategoryChanged(_CATEGORIES[0])

        # Includes
        body_layout.addWidget(self._field("INCLUDES"))
        inc_row = QHBoxLayout()
        inc_row.setSpacing(16)
        self.chk_rig = QCheckBox("Rig")
        self.chk_tex = QCheckBox("Textures")
        self.chk_mat = QCheckBox("Materials")
        for c in (self.chk_rig, self.chk_tex, self.chk_mat):
            inc_row.addWidget(c)
        inc_row.addStretch()
        body_layout.addLayout(inc_row)

        # Tags
        body_layout.addWidget(self._field("TAGS"))
        self.tag_container = _TagContainer(self._tags)
        body_layout.addWidget(self.tag_container)

        # Author
        body_layout.addWidget(self._field("AUTHOR"))
        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText("Your name")
        body_layout.addWidget(self.author_edit)

        # Project
        body_layout.addWidget(self._field("PROJECT"))
        self.project_edit = QLineEdit()
        self.project_edit.setPlaceholderText("Project this asset belongs to")
        body_layout.addWidget(self.project_edit)

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
        submit = QPushButton("Import Asset")
        submit.setObjectName("submitBtn")
        submit.clicked.connect(self._onSubmit)
        f_layout.addWidget(cancel)
        f_layout.addWidget(submit)
        root.addWidget(footer)

    # ------------------------------------------------------------------

    def _field(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-size: 10px; color: %s; font-family: 'IBM Plex Mono', monospace;"
            " letter-spacing: 1px; background: transparent;" % TEXT_TERTIARY
        )
        return lbl

    def _populate(self):
        if self.prefill.get("name"):
            self.name_edit.setText(self.prefill["name"])
        if self.prefill.get("version"):
            self.version_edit.setText(self.prefill["version"])
        if self.prefill.get("category"):
            idx = self.cat_combo.findText(self.prefill["category"])
            if idx >= 0:
                self.cat_combo.setCurrentIndex(idx)
        if self.prefill.get("subcategory"):
            idx = self.sub_combo.findText(self.prefill["subcategory"])
            if idx >= 0:
                self.sub_combo.setCurrentIndex(idx)
        if self.prefill.get("author"):
            self.author_edit.setText(self.prefill["author"])
        if self.prefill.get("project"):
            self.project_edit.setText(self.prefill["project"])

    def _onCategoryChanged(self, cat):
        self.sub_combo.clear()
        subs = _SUBCATEGORIES.get(cat, [])
        self.sub_combo.addItems(subs + ["+ Custom…"])

        self.ft_combo.clear()
        self.ft_combo.addItems(_FILETYPES.get(cat, []))

    def _selectSource(self, mode):
        self.src_disk.setActive(mode == "disk")
        self.src_prism.setActive(mode == "prism")

    def _onBrowse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Asset File")
        if path:
            self.filepath_edit.setText(path)
            if not self.name_edit.text():
                self.name_edit.setText(os.path.splitext(os.path.basename(path))[0])

    def _onSubmit(self):
        data = {
            "name":         self.name_edit.text().strip(),
            "version":      self.version_edit.text().strip() or "v001",
            "category":     self.cat_combo.currentText(),
            "subcategory":  self.sub_combo.currentText() if "+ Custom" not in self.sub_combo.currentText() else "",
            "filepath":     self.filepath_edit.text().strip(),
            "filetype":     self.ft_combo.currentText(),
            "renderer":     self.renderer_combo.currentText(),
            "dcc":          self.dcc_combo.currentText().split()[0],
            "has_rig":      int(self.chk_rig.isChecked()),
            "has_textures": int(self.chk_tex.isChecked()),
            "has_materials":int(self.chk_mat.isChecked()),
            "tags":         self.tag_container.getTags(),
            "author":       self.author_edit.text().strip(),
            "project":      self.project_edit.text().strip(),
        }
        if not data["name"] or not data["filepath"]:
            return
        self.assetSubmitted.emit(data)
        self.accept()

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


# ── Helper widgets ────────────────────────────────────────────────────────────

class _SourceOption(QFrame):
    clicked = Signal()

    def __init__(self, title, desc):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self._active = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        t = QLabel(title)
        t.setStyleSheet("font-size: 12px; font-weight: 500; color: %s; background: transparent;" % TEXT_PRIMARY)
        d = QLabel(desc)
        d.setStyleSheet("font-size: 10px; color: %s; background: transparent;" % TEXT_TERTIARY)
        d.setWordWrap(True)
        layout.addWidget(t)
        layout.addWidget(d)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._updateStyle()

    def setActive(self, v):
        self._active = v
        self._updateStyle()

    def _updateStyle(self):
        if self._active:
            self.setStyleSheet(
                "QFrame { background: %s; border: 1px solid %s; border-radius: 6px; }" % (GREEN_BG, GREEN_BORDER)
            )
        else:
            self.setStyleSheet(
                "QFrame { background: transparent; border: 1px solid %s; border-radius: 6px; }" % BORDER_LIGHT
            )

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class _TagContainer(QWidget):
    def __init__(self, initial_tags=None):
        super().__init__()
        self._tags = list(initial_tags or [])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(5)
        self.setStyleSheet(
            "background: %s; border: 1px solid %s; border-radius: 6px;" % (BG_SECONDARY, BORDER_LIGHT)
        )
        self._layout = layout
        self._input = QLineEdit()
        self._input.setPlaceholderText("+ tag")
        self._input.setStyleSheet(
            "background: transparent; border: none; color: %s; font-size: 11px; min-width: 60px;" % TEXT_PRIMARY
        )
        self._input.returnPressed.connect(self._addTagFromInput)
        self._rebuild()

    def _rebuild(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for tag in self._tags:
            pill = _TagPill(tag)
            pill.removed.connect(self._removeTag)
            self._layout.addWidget(pill)
        self._layout.addWidget(self._input)
        self._layout.addStretch()

    def _addTagFromInput(self):
        text = self._input.text().strip()
        if text and text not in self._tags:
            self._tags.append(text)
            self._input.clear()
            self._rebuild()

    def _removeTag(self, tag):
        if tag in self._tags:
            self._tags.remove(tag)
            self._rebuild()

    def getTags(self):
        return list(self._tags)


class _TagPill(QLabel):
    removed = Signal(str)

    def __init__(self, tag):
        super().__init__(tag + "  ✕")
        self._tag = tag
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "background: %s; color: %s; border: 1px solid %s;"
            " border-radius: 10px; padding: 2px 8px; font-size: 11px;" % (
                ACCENT_BG, ACCENT_TEXT, ACCENT_BORDER
            )
        )

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.removed.emit(self._tag)
