import os

from qtpy.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QCheckBox, QWidget, QFrame,
    QScrollArea, QSizePolicy,
)
from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QPixmap

from ui.styles import (
    BG_PRIMARY, BG_SECONDARY, BG_TERTIARY,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    BORDER_LIGHT, BORDER_MID, GREEN, GREEN_BG, GREEN_BORDER,
    ACCENT, ACCENT_BG, ACCENT_TEXT, ACCENT_BORDER,
)
from ui.publish_dialog import _FileListWidget, _ThumbZone

_ROW_H = 24


# ── Tracked file list ────────────────────────────────────────────────────────

class _TrackedFileList(_FileListWidget):
    """Reuses publish dialog's _FileListWidget. Tracks add/remove for disk ops.
    self._files stores basenames (not full paths) for existing version files."""

    def __init__(self, files=None):
        self._src_map = {}       # basename → original src path (newly added)
        self._to_remove = set()  # basenames to delete from disk
        super().__init__()
        # Pre-populate with existing basenames
        for name in (files or []):
            if name not in self._files:
                self._files.append(name)
        if self._files:
            self._refresh()

    def showEvent(self, event):
        super().showEvent(event)
        if self._files:
            self._refresh()

    def _addFiles(self, paths):
        for p in paths:
            if p and os.path.isfile(p):
                base = os.path.basename(p)
                if base not in self._files:
                    self._files.append(base)
                    self._src_map[base] = p
                    self._to_remove.discard(base)
        self._refresh()

    def _removeFile(self, name):
        if name in self._files:
            self._files.remove(name)
        if name in self._src_map:
            del self._src_map[name]
        else:
            self._to_remove.add(name)
        self._refresh()

    def getFiles(self):
        return list(self._files)

    def getFilesToAdd(self):
        return [(src,) for src in self._src_map.values()]

    def getFilesToRemove(self):
        return list(self._to_remove)

    def getAddedFilenames(self):
        return set(self._src_map.keys())


class _TrackedThumbZone(_ThumbZone):
    """ThumbZone that also tracks additions and removals for disk ops."""

    def __init__(self, label):
        super().__init__(label)
        self._existing = set()   # filenames that existed on disk at init
        self._to_remove = set()
        self._to_add = []        # source paths of newly-added images

    def _addImages(self, paths):
        for p in paths:
            if p and os.path.isfile(p):
                base = os.path.basename(p)
                if base not in self._existing and p not in self._to_add:
                    self._to_add.append(p)
        super()._addImages(paths)

    def _remove(self, path):
        """Override to track removals before delegating to parent."""
        base = os.path.basename(path)
        if base in self._existing:
            self._to_remove.add(base)
        else:
            # Was just added in this session — remove from add list
            self._to_add = [p for p in self._to_add if os.path.basename(p) != base]
        super()._remove(path)

    def setExisting(self, abs_paths):
        """Initialize with existing files from disk."""
        self._existing = set(os.path.basename(p) for p in abs_paths)
        self._addImages(abs_paths)

    def getImages(self):
        """Return list of absolute paths (same contract as publish dialog)."""
        return list(self._images)

    def getToRemove(self):
        return list(self._to_remove)

    def getToAdd(self):
        return list(self._to_add)


class VersionEditDialog(QDialog):
    """Dialog for editing version-level metadata and managing version files."""

    versionSubmitted = Signal(dict)

    def __init__(self, version_data=None, lib_root="", parent=None):
        super().__init__(parent)
        self.version_data = version_data or {}
        self._lib_root = lib_root
        self._version_dir = ""

        fp = self.version_data.get("filepath", "") or ""
        if fp and not os.path.isabs(fp) and lib_root:
            self._version_dir = os.path.dirname(os.path.join(lib_root, fp))
        elif fp and os.path.isabs(fp):
            self._version_dir = os.path.dirname(fp)

        # Scan current files from disk
        self._version_files = []   # filenames in version dir (excluding thumbs/textures)
        self._thumb_zones = {}     # "material" → _TrackedThumbZone
        self._thumb_scanned = {}   # view_key → [abs paths] (populated by _scanFiles)
        self._texture_files = []   # filenames in textures dir

        self._scanFiles()

        self.setWindowTitle("Edit Version")
        self.setFixedWidth(440)
        self.setStyleSheet(self._buildStylesheet())
        self._build()
        self._populate()

    # ── File scanning ────────────────────────────────────────────────────────

    def _scanFiles(self):
        if not self._version_dir or not os.path.isdir(self._version_dir):
            return
        try:
            all_names = sorted(os.listdir(self._version_dir))
        except OSError:
            return
        for name in all_names:
            fpath = os.path.join(self._version_dir, name)
            if name in ("thumbs", "textures") or not os.path.isfile(fpath):
                continue
            self._version_files.append(name)

        # Thumbnails: categorize into material/clay/wire by filename
        from ui.styles import VIEWS as _VIEWS
        thumbs_dir = os.path.join(self._version_dir, "thumbs")
        by_view = {v: [] for v, _ in _VIEWS}
        if os.path.isdir(thumbs_dir):
            try:
                for fname in sorted(os.listdir(thumbs_dir)):
                    fpath = os.path.join(thumbs_dir, fname)
                    if not os.path.isfile(fpath):
                        continue
                    matched = False
                    for view, _ in _VIEWS:
                        if view in fname.lower():
                            by_view[view].append(fpath)
                            matched = True
                            break
                    if not matched:
                        by_view["material"].append(fpath)
            except OSError:
                pass

        self._thumb_scanned = by_view

        # Textures
        textures_dir = os.path.join(self._version_dir, "textures")
        if os.path.isdir(textures_dir):
            try:
                self._texture_files = sorted(
                    n for n in os.listdir(textures_dir)
                    if os.path.isfile(os.path.join(textures_dir, n))
                )
            except OSError:
                pass

    # ── UI build ─────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ───────────────────────────────────────────────────────
        header = QWidget()
        header.setObjectName("dialogHeader")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 13, 16, 13)
        title_lbl = QLabel("Edit Version")
        title_lbl.setStyleSheet("font-size: 13px; font-weight: 500; color: %s;" % TEXT_PRIMARY)
        h_layout.addWidget(title_lbl)
        h_layout.addStretch()

        ver = self.version_data.get("version", "")
        ver_lbl = QLabel(str(ver))
        ver_lbl.setStyleSheet(
            "color: %s; font-size: 11px; font-weight: 500; background: transparent;"
            " font-family: 'IBM Plex Mono', monospace;" % TEXT_TERTIARY
        )
        h_layout.addWidget(ver_lbl)
        h_layout.addSpacing(8)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            "border: none; background: transparent; color: %s; font-size: 14px;" % TEXT_TERTIARY
        )
        close_btn.clicked.connect(self.reject)
        h_layout.addWidget(close_btn)
        root.addWidget(header)

        # ── Scrollable body ──────────────────────────────────────────────
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

        # ── Files section ────────────────────────────────────────────
        if self._version_files is not None:
            body_layout.addWidget(self._field_label("FILES"))
            self._file_list = _TrackedFileList(self._version_files)
            body_layout.addWidget(self._file_list)

        # ── Textures section ─────────────────────────────────────────
        if self._texture_files is not None:
            body_layout.addWidget(self._field_label("TEXTURES"))
            self._texture_list = _TrackedFileList(self._texture_files)
            body_layout.addWidget(self._texture_list)

        # ── Thumbnails sections ──────────────────────────────────────
        from ui.styles import VIEWS as _VIEWS
        if self._thumb_zones is not None:
            body_layout.addWidget(self._field_label("THUMBNAILS"))
            for view_key, view_label in _VIEWS:
                zone = _TrackedThumbZone(view_label)
                if view_key in self._thumb_scanned:
                    zone.setExisting(self._thumb_scanned[view_key])
                self._thumb_zones[view_key] = zone
                body_layout.addWidget(zone)

        # ── Metadata ─────────────────────────────────────────────────
        body_layout.addSpacing(4)
        body_layout.addWidget(self._sep())
        body_layout.addSpacing(4)

        body_layout.addWidget(self._field_label("RENDERER"))
        self.renderer_combo = QComboBox()
        self.renderer_combo.addItems(["Any", "Redshift", "Arnold", "V-Ray"])
        body_layout.addWidget(self.renderer_combo)

        body_layout.addWidget(self._field_label("DCC"))
        self.dcc_combo = QComboBox()
        self.dcc_combo.addItems(["Universal", "Houdini only", "Maya only"])
        body_layout.addWidget(self.dcc_combo)

        body_layout.addWidget(self._field_label("INCLUDES"))
        inc_row = QHBoxLayout()
        inc_row.setSpacing(16)
        self.chk_rig = QCheckBox("Rig")
        self.chk_mat = QCheckBox("Materials")
        self.chk_tex = QCheckBox("Textures")
        for c in (self.chk_rig, self.chk_mat, self.chk_tex):
            inc_row.addWidget(c)
        inc_row.addStretch()
        body_layout.addLayout(inc_row)

        body_layout.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # ── Footer ───────────────────────────────────────────────────
        footer = QWidget()
        footer.setObjectName("dialogFooter")
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(16, 10, 16, 10)
        f_layout.setSpacing(8)
        f_layout.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        submit = QPushButton("Save Changes")
        submit.setObjectName("submitBtn")
        submit.clicked.connect(self._onSubmit)
        f_layout.addWidget(cancel)
        f_layout.addWidget(submit)
        root.addWidget(footer)

    # ── Populate ────────────────────────────────────────────────────────────

    def _populate(self):
        v = self.version_data
        renderer = v.get("renderer", "Any")
        idx = self.renderer_combo.findText(renderer)
        if idx >= 0:
            self.renderer_combo.setCurrentIndex(idx)

        dcc = v.get("dcc", "Universal")
        for text in [dcc, dcc + " only"]:
            idx = self.dcc_combo.findText(text)
            if idx >= 0:
                self.dcc_combo.setCurrentIndex(idx)
                break

        self.chk_rig.setChecked(bool(v.get("has_rig", 0)))
        self.chk_mat.setChecked(bool(v.get("has_materials", 0)))
        self.chk_tex.setChecked(bool(v.get("has_textures", 0)))

    # ── Submit ──────────────────────────────────────────────────────────────

    def _onSubmit(self):
        # Thumbnail changes
        all_thumbs_to_add = []
        all_thumbs_to_remove = []
        current_thumbs = {}
        from ui.styles import VIEWS as _VIEWS
        for view_key, view_label in _VIEWS:
            zone = self._thumb_zones.get(view_key)
            if not zone:
                continue
            all_thumbs_to_add.extend(zone.getToAdd())
            all_thumbs_to_remove.extend(zone.getToRemove())
            # Current images: list of filenames in order
            current_thumbs[view_key] = [os.path.basename(p) for p in zone.getImages()]

        # Compute flat list of all current thumb filenames
        flat_thumbs = []
        for vlist in current_thumbs.values():
            flat_thumbs.extend(vlist)

        # Texture changes
        texture_srcs = self._texture_list.getFilesToAdd() if hasattr(self, '_texture_list') else []
        tex_remove = self._texture_list.getFilesToRemove() if hasattr(self, '_texture_list') else []
        current_textures = self._texture_list.getFiles() if hasattr(self, '_texture_list') else []
        tex_to_add = [src for (src,) in texture_srcs] if texture_srcs else []

        # File changes
        file_srcs = self._file_list.getFilesToAdd() if hasattr(self, '_file_list') else []
        file_remove = self._file_list.getFilesToRemove() if hasattr(self, '_file_list') else []
        file_to_add = [src for (src,) in file_srcs] if file_srcs else []

        data = {
            "version_id": self.version_data.get("id"),
            "renderer": self.renderer_combo.currentText(),
            "dcc": self.dcc_combo.currentText().split()[0],
            "has_rig": int(self.chk_rig.isChecked()),
            "has_materials": int(self.chk_mat.isChecked()),
            "has_textures": int(bool(current_textures)),
            "_version_dir": self._version_dir,
            "_files_to_add": file_to_add,
            "_files_to_remove": file_remove,
            "_thumbs_to_add": all_thumbs_to_add,
            "_thumbs_to_remove": all_thumbs_to_remove,
            "_textures_to_add": tex_to_add,
            "_textures_to_remove": tex_remove,
            "_current_thumbs": flat_thumbs,
            "_current_thumbs_by_view": current_thumbs,
            "_current_textures": current_textures,
        }
        self.versionSubmitted.emit(data)
        self.accept()

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _field_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-size: 10px; color: %s; font-family: 'IBM Plex Mono', monospace;"
            " letter-spacing: 1px; background: transparent;" % TEXT_TERTIARY
        )
        return lbl

    def _sep(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("border: none; border-top: 1px solid %s;" % BORDER_LIGHT)
        return line

    def _buildStylesheet(self):
        return """
            QDialog { background: %(bg)s; }
            #dialogHeader, #dialogFooter {
                background: %(bg2)s;
                border-bottom: 1px solid %(bl)s;
            }
            #dialogFooter { border-top: 1px solid %(bl)s; border-bottom: none; }
            QComboBox {
                background: %(bg)s; border: 1px solid %(bl)s; border-radius: 6px;
                padding: 4px 8px; color: %(tp)s; font-size: 12px; min-height: 20px;
            }
            QComboBox:focus, QComboBox:on { border: 1px solid %(bm)s; }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox::down-arrow {
                image: none; border-left: 4px solid transparent;
                border-right: 4px solid transparent; border-top: 5px solid %(ts)s;
                width: 0; height: 0;
            }
            QComboBox QAbstractItemView {
                background: %(bg)s; border: none; color: %(tp)s;
                selection-background-color: %(abg)s; selection-color: %(at)s;
                padding: 2px;
            }
            QCheckBox {
                color: %(tp)s; font-size: 12px; spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px; height: 16px; border: 1px solid %(bm)s;
                border-radius: 3px; background: %(bg)s;
            }
            QCheckBox::indicator:checked {
                background: %(ac)s; border-color: %(ac)s;
            }
            #submitBtn {
                background: %(gbg)s; border: 1px solid %(gborder)s;
                border-radius: 6px; color: %(green)s; font-weight: 500;
                padding: 5px 14px;
            }
            #submitBtn:hover { background: #063a2a; }
            QScrollBar:vertical {
                background: transparent; width: 8px; margin: 0;
            }
            QScrollBar::handle:vertical {
                background: %(bl)s; border-radius: 4px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """ % {
            "bg": BG_PRIMARY, "bg2": BG_SECONDARY, "bl": BORDER_LIGHT,
            "bm": BORDER_MID, "tp": TEXT_PRIMARY, "ts": TEXT_SECONDARY,
            "gbg": GREEN_BG, "gborder": GREEN_BORDER, "green": GREEN,
            "ac": ACCENT, "abg": ACCENT_BG, "at": ACCENT_TEXT,
        }
