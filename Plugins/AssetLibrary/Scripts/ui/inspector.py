import os
import logging

from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QSizePolicy, QDialog,
    QGraphicsDropShadowEffect, QComboBox, QMenu,
)
from qtpy.QtCore import Qt, Signal, QRectF, QMimeData
from qtpy.QtGui import QPixmap, QColor, QPainter, QPainterPath, QPen
from qtpy.QtWidgets import QApplication

from ui.styles import (
    BG_PRIMARY, BG_SECONDARY, BG_TERTIARY,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    BORDER_LIGHT, BORDER_MID, ACCENT, ACCENT_BG, ACCENT_TEXT, ACCENT_BORDER,
    THUMB_PALETTES, _NoFocusDelegate, VIEWS as _VIEWS,
)

_PREVIEW_SIZE = 340

logger = logging.getLogger(__name__)


def _text(value, default=""):
    if value is None:
        return default
    return str(value)


def _asset_palette_index(asset_data):
    if not asset_data:
        return 0
    try:
        return int(asset_data.get("id") or 0) % len(THUMB_PALETTES)
    except (TypeError, ValueError):
        return 0


class _VersionCombo(QComboBox):
    """QComboBox that styles the popup container frame directly so borders render on all sides."""
    def showPopup(self):
        super().showPopup()
        self.view().scrollToTop()
        container = self.view().parentWidget()
        if container and container is not self:
            container.setObjectName("_verPopup")
            container.setStyleSheet(
                "#_verPopup { border: 1px solid %s; border-radius: 4px;"
                " background: %s; }"
                "QAbstractItemView { border: none; background: %s; }"
                "QScrollBar { width: 0; height: 0; border: none; }"
                % (BORDER_MID, BG_PRIMARY, BG_PRIMARY)
            )


class InspectorPanel(QWidget):
    closeRequested = Signal()
    tagClicked     = Signal(str)
    versionChanged = Signal(str)   # emits the selected version string

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inspectorPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(340)
        self._asset_data = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Preview — fixed above scroll area so the scrollbar can never overlap it
        preview_wrap = QWidget()
        preview_wrap.setFixedHeight(_PREVIEW_SIZE)
        preview_wrap.setStyleSheet("background: transparent;")
        self.preview = InspectorPreview(preview_wrap)
        self.preview.setGeometry(0, 0, _PREVIEW_SIZE, _PREVIEW_SIZE)
        self.preview.closeClicked.connect(self.closeRequested.emit)
        root.addWidget(preview_wrap)

        # Fixed name + category + version below thumbnail (never scrolls)
        header = QWidget()
        header.setAttribute(Qt.WA_StyledBackground, True)
        header.setStyleSheet("background: %s;" % BG_SECONDARY)
        header_outer = QVBoxLayout(header)
        header_outer.setContentsMargins(14, 10, 14, 10)
        header_outer.setSpacing(2)

        # Row: name (left) + version combo (right)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.name_label = QLabel("")
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet(
            "font-size: 15px; font-weight: 600; color: %s; background: transparent;"
            % TEXT_PRIMARY
        )
        title_row.addWidget(self.name_label, 1)

        self.version_combo = _VersionCombo()
        self.version_combo.setFixedWidth(70)
        self.version_combo.view().setFocusPolicy(Qt.NoFocus)
        self.version_combo.view().setItemDelegate(_NoFocusDelegate(self.version_combo))
        self.version_combo.setMaxVisibleItems(10)
        self.version_combo.view().setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.version_combo.view().setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.version_combo.view().setAutoScroll(False)
        self.version_combo.setStyleSheet(
            "QComboBox { background: %s; border: 1px solid %s; border-radius: 4px;"
            " padding: 2px 6px; color: %s; font-size: 11px;"
            " font-family: 'IBM Plex Mono', monospace; min-width: 60px; outline: none; }"
            "QComboBox:focus, QComboBox:on { border: 1px solid %s; }"
            "QComboBox::drop-down { border: none; width: 16px; background: transparent; }"
            "QComboBox::down-arrow { image: none; border-left: 3px solid transparent;"
            " border-right: 3px solid transparent; border-top: 4px solid %s;"
            " width: 0; height: 0; }"
            "QComboBox QAbstractItemView { background: %s; border: none;"
            " color: %s; selection-background-color: %s; selection-color: %s;"
            " padding: 2px; outline: none; }"
            "QComboBox QAbstractItemView::item { padding: 3px 6px; }"
            "QComboBox QAbstractItemView::item:selected { background: %s; }"
            % (BG_PRIMARY, BORDER_LIGHT, TEXT_SECONDARY,
               BORDER_MID, TEXT_TERTIARY,
               BG_PRIMARY, TEXT_PRIMARY, ACCENT_BG, ACCENT_TEXT,
               ACCENT_BG)
        )
        self.version_combo.currentTextChanged.connect(
            lambda v: self.versionChanged.emit(v) if v else None
        )
        self.version_combo.hide()
        title_row.addWidget(self.version_combo)

        self.more_btn = QLabel("⋮")
        self.more_btn.setFixedSize(22, 22)
        self.more_btn.setAlignment(Qt.AlignCenter)
        self.more_btn.setCursor(Qt.PointingHandCursor)
        self.more_btn.setStyleSheet(
            "color: %s; font-size: 16px; background: transparent;"
            " border-radius: 4px;" % TEXT_TERTIARY
        )
        self.more_btn.hide()
        self.more_btn.mousePressEvent = self._onMoreClicked
        title_row.addWidget(self.more_btn)

        header_outer.addLayout(title_row)

        self.category_label = QLabel("")
        self.category_label.setStyleSheet(
            "font-size: 11px; color: %s; background: transparent;"
            % TEXT_TERTIARY
        )
        header_outer.addWidget(self.category_label)
        root.addWidget(header)

        # Scrollable metadata only
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: %s; border: none; }" % BG_PRIMARY
        )

        body = QWidget()
        body.setStyleSheet("background: %s;" % BG_PRIMARY)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 10, 14, 14)
        body_layout.setSpacing(0)
        self.metadata = _MetadataSection()
        self.metadata.tagClicked.connect(self.tagClicked.emit)
        body_layout.addWidget(self.metadata)
        body_layout.addStretch()

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

    def setAsset(self, asset_data, versions=None):
        self._asset_data = asset_data
        self.preview.setAsset(asset_data)
        self.metadata.setAsset(asset_data)

        if asset_data:
            name = _text(asset_data.get("name"))
            self.name_label.setText(name)
            cat = _text(asset_data.get("category"))
            sub = _text(asset_data.get("subcategory"))
            cat_text = cat + (" / " + sub if sub else "")
            self.category_label.setText(cat_text)

            # Version combo
            versions = versions or []
            self.version_combo.blockSignals(True)
            self.version_combo.clear()
            if versions:
                seen = set()
                for v in versions:
                    ver_str = v.get("version", "")
                    if ver_str and ver_str not in seen:
                        seen.add(ver_str)
                        self.version_combo.addItem(ver_str)
                # Select latest (first, since sorted DESC)
                self.version_combo.setCurrentIndex(0)
                self.version_combo.show()
                self.more_btn.show()
            else:
                self.version_combo.hide()
                self.more_btn.hide()
            self.version_combo.blockSignals(False)
        else:
            self.name_label.setText("")
            self.category_label.setText("")
            self.version_combo.hide()
            self.more_btn.hide()

    def _onMoreClicked(self, e):
        if e.button() != Qt.LeftButton:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #242424; border: 1px solid %s; border-radius: 6px;"
            " padding: 4px 0; color: %s; font-size: 12px; outline: none; }"
            "QMenu::item { padding: 5px 20px 5px 12px; background: transparent; outline: none; }"
            "QMenu::item:selected { background-color: %s; color: %s; outline: none; }"
            % (BORDER_MID, TEXT_SECONDARY, ACCENT_BG, ACCENT_TEXT)
        )
        act_explorer = menu.addAction("Open in Explorer")
        act_copy = menu.addAction("Copy Link")
        action = menu.exec_(self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()))
        if action == act_explorer:
            self._openInExplorer()
        elif action == act_copy:
            self._copyLink()

    def _getCurrentFilepath(self):
        if not self._asset_data:
            return None
        ver = self.version_combo.currentText()
        filepath = self._asset_data.get("filepath", "")
        lib_root = self._asset_data.get("_lib_root", "")
        if lib_root and not os.path.isabs(filepath):
            filepath = os.path.join(lib_root, filepath)
        return filepath

    def _openInExplorer(self):
        filepath = self._getCurrentFilepath()
        if not filepath:
            return
        import subprocess
        folder = os.path.dirname(filepath)
        if folder and os.path.isdir(folder):
            subprocess.Popen('explorer /select,"%s"' % os.path.normpath(filepath))
        elif os.path.isdir(filepath):
            subprocess.Popen('explorer "%s"' % os.path.normpath(filepath))

    def _copyLink(self):
        filepath = self._getCurrentFilepath()
        if not filepath:
            return
        mime = QMimeData()
        mime.setText(filepath)
        QApplication.clipboard().setMimeData(mime)


class InspectorPreview(QWidget):
    """Large thumbnail preview with gallery controls and fullscreen button."""

    closeClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_PREVIEW_SIZE, _PREVIEW_SIZE)
        self._asset_data = None
        self._orig_px = None
        self._current_view = "material"
        self._view_thumbs = {"material": [], "clay": [], "wire": []}
        self._current_idx = 0
        self._hover = False
        self._view_mode = "2d"
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setMouseTracking(True)
        self._build()

    def _build(self):
        # Arrows
        self.arrow_left = _InspArrowBtn(self, mirror=False)
        self.arrow_right = _InspArrowBtn(self, mirror=True)
        self.arrow_left.clicked.connect(self._onLeft)
        self.arrow_right.clicked.connect(self._onRight)
        self.arrow_left.hide()
        self.arrow_right.hide()

        # Dots
        self._dots = {}
        for view, _ in _VIEWS:
            dot = _InspDotBtn(self)
            dot.clicked.connect(lambda v=view: self._onDot(v))
            dot.hide()
            self._dots[view] = dot

        self.mode_btn = _ModeBtn(self, width=34, height=22, font_size=12)
        self.mode_btn.clicked.connect(self._toggleViewMode)
        self.mode_btn.hide()

        # Counter
        self.counter = _InspCounter(self)
        self.counter.hide()

        # Fullscreen button — bottom-left
        self.fs_btn = _ExpandBtn(self)
        self.fs_btn.setToolTip("Fullscreen preview")
        self.fs_btn.clicked.connect(self._onFullscreen)
        self.fs_btn.hide()

        # Close button — top-right, shown on hover
        self.close_btn = _InspCloseBtn(self)
        self.close_btn.clicked.connect(self.closeClicked.emit)
        self.close_btn.hide()

        self._positionOverlays()

    def _positionOverlays(self):
        s = _PREVIEW_SIZE
        mid_y = (s - 44) // 2
        self.arrow_left.move(6, mid_y)
        self.arrow_right.move(s - 50, mid_y)

        dot_size, dot_gap = 18, 8
        mode_gap = 7
        mode_w = self.mode_btn.width()
        total = mode_w + mode_gap + len(_VIEWS) * dot_size + (len(_VIEWS) - 1) * dot_gap
        dx = (s - total) // 2
        dy = s - 28
        self.mode_btn.move(dx, dy + (dot_size - self.mode_btn.height()) // 2)
        for i, (view, _) in enumerate(_VIEWS):
            x = dx + mode_w + mode_gap + i * (dot_size + dot_gap)
            self._dots[view].move(x, dy)

        self.counter.adjustSize()
        self.counter.move(6, s - self.counter.height() - 6)

        # Fullscreen — bottom-right
        self.fs_btn.move(s - self.fs_btn.width() - 6, s - self.fs_btn.height() - 6)

        # Close — top-right
        self.close_btn.move(s - self.close_btn.width() - 6, 6)

    def setAsset(self, asset_data):
        self._asset_data = asset_data
        self.setViewMode("2d")
        self._current_view = "material"
        self._current_idx = 0
        self._scanThumbs()
        self._showThumb()
        self._updateDotStyles()
        self._refreshArrows()
        self._refreshCounter()

    def _scanThumbs(self):
        self._view_thumbs = {"material": [], "clay": [], "wire": []}
        if not self._asset_data:
            return
        tp = self._asset_data.get("thumbnail_path", "") or ""
        lib_root = self._asset_data.get("_lib_root", "") or ""
        if tp and not os.path.isabs(tp) and lib_root:
            tp = os.path.join(lib_root, tp)
        if not tp:
            return
        if os.path.isfile(tp):
            self._view_thumbs["material"] = [tp]
        elif os.path.isdir(tp):
            try:
                names = sorted(os.listdir(tp))
            except OSError as exc:
                logger.warning("Could not scan inspector thumbnails at %s: %s", tp, exc)
                return
            for fname in names:
                low = fname.lower()
                if not low.endswith((".png", ".jpg", ".jpeg")):
                    continue
                fpath = os.path.join(tp, fname)
                for view, _ in _VIEWS:
                    if view in low:
                        self._view_thumbs[view].append(fpath)
                        break

    def _showThumb(self):
        images = self._view_thumbs.get(self._current_view, [])
        if images and 0 <= self._current_idx < len(images):
            px = QPixmap(images[self._current_idx])
            self._orig_px = px if not px.isNull() else None
        else:
            self._orig_px = None
        self.update()

    def _onLeft(self):
        images = self._view_thumbs.get(self._current_view, [])
        if len(images) > 1:
            self._current_idx = (self._current_idx - 1) % len(images)
            self._showThumb()
            self._refreshCounter()

    def _onRight(self):
        images = self._view_thumbs.get(self._current_view, [])
        if len(images) > 1:
            self._current_idx = (self._current_idx + 1) % len(images)
            self._showThumb()
            self._refreshCounter()

    def _onDot(self, view):
        if not self._view_thumbs.get(view):
            return
        self._current_view = view
        self._current_idx = 0
        self._showThumb()
        self._updateDotStyles()
        self._refreshArrows()
        self._refreshCounter()

    def _refreshArrows(self):
        if self._view_mode != "2d":
            self.arrow_left.hide()
            self.arrow_right.hide()
            return
        n = len(self._view_thumbs.get(self._current_view, []))
        if n > 1:
            self.arrow_left.show()
            self.arrow_right.show()
        else:
            self.arrow_left.hide()
            self.arrow_right.hide()

    def _refreshCounter(self):
        if self._view_mode != "2d":
            self.counter.hide()
            return
        images = self._view_thumbs.get(self._current_view, [])
        n = len(images)
        if n > 1:
            self.counter.setText("%d/%d" % (self._current_idx + 1, n))
            self.counter.adjustSize()
            self.counter.move(6, _PREVIEW_SIZE - self.counter.height() - 6)
            self.counter.show()
        else:
            self.counter.hide()

    def _updateDotStyles(self):
        for view, _ in _VIEWS:
            dot = self._dots[view]
            has = bool(self._view_thumbs.get(view))
            active = (view == self._current_view) and has
            dot.setState(view, active, has)

    def _onFullscreen(self):
        if not any(self._view_thumbs.values()):
            return
        self._fs_dlg = FullscreenPreviewDialog(
            self._view_thumbs, self._current_view, self._current_idx
        )
        self._fs_dlg.imageChanged.connect(self._onFullscreenChanged)
        self._fs_dlg.showFullScreen()

    def _onFullscreenChanged(self, view, idx):
        self._current_view = view
        self._current_idx = idx
        self._showThumb()
        self._updateDotStyles()
        self._refreshArrows()
        self._refreshCounter()

    def viewMode(self):
        return self._view_mode

    def setViewMode(self, mode):
        self._view_mode = "3d" if mode == "3d" else "2d"
        self.mode_btn.setMode(self._view_mode)
        if self._view_mode == "2d":
            self._showThumb()
        else:
            self._orig_px = None
        self._refreshArrows()
        self._refreshCounter()
        self.update()

    def _toggleViewMode(self):
        self.setViewMode("3d" if self._view_mode == "2d" else "2d")

    def _drawCubePlaceholder(self, p):
        scale = self.height() / 160.0
        s = int(18 * scale)
        off = int(8 * scale)
        cx = self.width() // 2
        cy = self.height() // 2 - off
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.drawRect(cx - s, cy - s, s * 2, s * 2)
        p.drawRect(cx - s + off, cy - s + off, s * 2, s * 2)
        p.drawLine(cx - s, cy - s, cx - s + off, cy - s + off)
        p.drawLine(cx + s, cy - s, cx + s + off, cy - s + off)
        p.drawLine(cx - s, cy + s, cx - s + off, cy + s + off)
        p.drawLine(cx + s, cy + s, cx + s + off, cy + s + off)
        font = p.font()
        font.setPixelSize(max(12, int(14 * scale)))
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 50))
        p.drawText(QRectF(0, cy + s + off + 6, self.width(), 24), Qt.AlignCenter, "3D Preview")

    def enterEvent(self, e):
        self._hover = True
        self.mode_btn.show()
        self.mode_btn.raise_()
        if self._view_mode == "2d":
            for dot in self._dots.values():
                if dot._available:
                    dot.show()
        self._refreshArrows()
        self._refreshCounter()
        if self._view_mode == "2d":
            self.fs_btn.show()
            self.fs_btn.raise_()
        self.close_btn.show()
        self.close_btn.raise_()

    def leaveEvent(self, e):
        self._hover = False
        for dot in self._dots.values():
            dot.hide()
        self.arrow_left.hide()
        self.arrow_right.hide()
        self.counter.hide()
        self.fs_btn.hide()
        self.mode_btn.hide()
        self.close_btn.hide()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        r = QRectF(self.rect())

        if self._view_mode == "3d":
            idx = _asset_palette_index(self._asset_data)
            bg, _ = THUMB_PALETTES[idx] if self._asset_data else (BG_TERTIARY, TEXT_TERTIARY)
            p.fillRect(self.rect(), QColor(bg))
            self._drawCubePlaceholder(p)
        elif self._orig_px and not self._orig_px.isNull():
            scaled = self._orig_px.scaled(
                int(r.width()), int(r.height()),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            x = (int(r.width()) - scaled.width()) // 2
            y = (int(r.height()) - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        else:
            # Placeholder
            if self._asset_data:
                idx = _asset_palette_index(self._asset_data)
                bg, fg = THUMB_PALETTES[idx]
            else:
                bg, fg = BG_TERTIARY, TEXT_TERTIARY
            p.fillRect(self.rect(), QColor(bg))
            if self._asset_data:
                font = p.font()
                font.setPixelSize(40)
                p.setFont(font)
                p.setPen(QColor(fg))
                name = _text(self._asset_data.get("name"), "?") or "?"
                p.drawText(r, Qt.AlignCenter, name[0].upper())


class _InspArrowBtn(QWidget):
    clicked = Signal()

    def __init__(self, parent=None, mirror=False):
        super().__init__(parent)
        self._mirror = mirror
        self._hover = False
        self.setFixedSize(44, 44)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, _e):
        from qtpy.QtGui import QRadialGradient
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        shadow = QRadialGradient(cx, cy + 1, min(w, h) * 0.42)
        shadow.setColorAt(0.0, QColor(0, 0, 0, 35 if self._hover else 21))
        shadow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(shadow)
        p.drawEllipse(self.rect())
        s  = h * 0.25
        tx = w * 0.09
        ex = w * 0.14
        tip_x = cx - tx if not self._mirror else cx + tx
        end_x = cx + ex if not self._mirror else cx - ex
        path = QPainterPath()
        path.moveTo(end_x, cy - s)
        path.lineTo(tip_x, cy)
        path.lineTo(end_x, cy + s)
        pen_w = max(2.0, min(w, h) * 0.08)
        pen = QPen(QColor(255, 255, 255, 180 if self._hover else 91), pen_w,
                    Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class _InspDotBtn(QWidget):
    clicked = Signal()

    _GRADIENTS = {
        "material": ((123, 191, 238), (24, 95, 165)),
        "clay":     ((180, 180, 175), (90, 90, 85)),
    }
    _ACTIVE_BORDER = QColor(255, 255, 255, 190)
    _INACTIVE_BORDER = QColor(255, 255, 255, 60)
    _UNAVAIL_BORDER = QColor(180, 180, 180, 90)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._view = ""
        self._active = False
        self._available = False

    def setState(self, view, active, available):
        self._view = view or ""
        self._active = active
        self._available = available
        self.update()

    def paintEvent(self, _e):
        from qtpy.QtGui import QRadialGradient
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        scale = self.width() / 18.0
        pw_active = max(1.0, 2.0 * scale)
        pw_normal = max(1.0, 1.0 * scale)
        if not self._available:
            p.setPen(QPen(self._UNAVAIL_BORDER, pw_normal))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r.adjusted(scale, scale, -scale, -scale))
        else:
            pad = 1.5 * scale if self._active else 1.0 * scale
            er = r.adjusted(pad, pad, -pad, -pad)
            if self._view == "wire":
                p.setBrush(QColor(20, 20, 20))
            else:
                pair = self._GRADIENTS.get(self._view)
                if pair:
                    bright, dark = pair
                    grad = QRadialGradient(er.x() + er.width() * 0.35,
                                           er.y() + er.height() * 0.30,
                                           max(er.width(), er.height()) * 0.55)
                    grad.setColorAt(0.0, QColor(*bright))
                    grad.setColorAt(1.0, QColor(*dark))
                    p.setBrush(grad)
                else:
                    p.setBrush(Qt.NoBrush)
            pen = self._ACTIVE_BORDER if self._active else self._INACTIVE_BORDER
            pen_w = pw_active if self._active else pw_normal
            p.setPen(QPen(pen, pen_w))
            p.drawEllipse(er)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class _InspCounter(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(
            "color: white; font-size: 12px;"
            " font-family: 'IBM Plex Mono', monospace; padding: 2px 8px;"
        )

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawRoundedRect(QRectF(self.rect()), 8, 8)
        p.end()
        super().paintEvent(e)


class _ModeBtn(QWidget):
    clicked = Signal()

    def __init__(self, parent=None, width=34, height=22, font_size=12):
        super().__init__(parent)
        self._mode = "2d"
        self._hover = False
        self._font_size = font_size
        self.setFixedSize(width, height)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._label = QLabel("2D", self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._label.setStyleSheet(
            "background: transparent; color: white; font-size: %dpx;"
            " font-weight: 600; padding: 0; margin: 0;" % font_size
        )
        self._label.setGeometry(0, 0, width, height)

    def setMode(self, mode):
        self._mode = "3d" if mode == "3d" else "2d"
        self._label.setText("3D" if self._mode == "3d" else "2D")
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        r = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        radius = min(6.0, r.height() / 2.6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 124 if self._hover else 86))
        p.drawRoundedRect(r, radius, radius)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
            e.accept()
            return
        super().mousePressEvent(e)


class FullscreenPreviewDialog(QDialog):
    imageChanged = Signal(str, int)  # (view, idx)

    _ZOOM_MIN = 0.5
    _ZOOM_MAX = 12.0
    _ZOOM_STEP = 1.15

    def __init__(self, view_thumbs, current_view, current_idx=0, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self._view_thumbs = view_thumbs
        self._current_view = current_view
        self._current_idx = current_idx
        self._view_mode = "2d"
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setStyleSheet("background: #1a1a1a;")
        self.setMouseTracking(True)
        self._orig_px = None
        self._zoom   = 1.0
        self._pan_x  = 0.0
        self._pan_y  = 0.0
        self._panning = False
        self._pan_start = None
        self._pan_offset_start = (0.0, 0.0)
        self._loadImage()
        self._buildOverlays()

    # ── Overlays ──────────────────────────────────────────────────────────

    def _buildOverlays(self):
        self._arrow_left = _InspArrowBtn(self, mirror=False)
        self._arrow_right = _InspArrowBtn(self, mirror=True)
        for a in (self._arrow_left, self._arrow_right):
            a.setFixedSize(132, 132)
        self._arrow_left.clicked.connect(self._onLeft)
        self._arrow_right.clicked.connect(self._onRight)

        self._dots = {}
        for view, _ in _VIEWS:
            dot = _InspDotBtn(self)
            dot.setFixedSize(54, 54)
            dot.clicked.connect(lambda v=view: self._onDot(v))
            self._dots[view] = dot

        self._counter = _InspCounter(self)
        self._counter.setStyleSheet(
            "color: white; font-size: 36px;"
            " font-family: 'IBM Plex Mono', monospace; padding: 6px 20px;"
        )

        self._mode_btn = _ModeBtn(self, width=74, height=44, font_size=22)
        self._mode_btn.clicked.connect(self._toggleViewMode)

        self._close_btn = _FsCloseBtn(self)
        self._close_btn.clicked.connect(self.close)

        self._updateDotStyles()
        self._refreshCounter()
        self._refreshArrows()

    def _positionOverlays(self):
        w, h = self.width(), self.height()

        self._arrow_left.move(24, (h - 132) // 2)
        self._arrow_right.move(w - 156, (h - 132) // 2)

        dot_size, dot_gap = 54, 16
        mode_gap = 16
        mode_w = self._mode_btn.width()
        total = mode_w + mode_gap + len(_VIEWS) * dot_size + (len(_VIEWS) - 1) * dot_gap
        dx = (w - total) // 2
        dy = h - 80
        self._mode_btn.move(dx, dy + (dot_size - self._mode_btn.height()) // 2)
        for i, (view, _) in enumerate(_VIEWS):
            x = dx + mode_w + mode_gap + i * (dot_size + dot_gap)
            self._dots[view].move(x, dy)

        close_x = w - 64
        self._close_btn.move(close_x, 16)

        self._counter.adjustSize()
        self._counter.move(24, h - self._counter.height() - 24)

        for w_ in (self._arrow_left, self._arrow_right, self._counter, self._close_btn,
                   self._mode_btn):
            w_.raise_()
        for dot in self._dots.values():
            dot.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._positionOverlays()

    # ── Image loading & navigation ─────────────────────────────────────────

    def _loadImage(self):
        images = self._view_thumbs.get(self._current_view, [])
        if images and 0 <= self._current_idx < len(images):
            px = QPixmap(images[self._current_idx])
            self._orig_px = px if not px.isNull() else None
        else:
            self._orig_px = None

    def _resetView(self):
        self._zoom  = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0

    def _onLeft(self):
        images = self._view_thumbs.get(self._current_view, [])
        if len(images) > 1:
            self._current_idx = (self._current_idx - 1) % len(images)
            self._loadImage()
            self._resetView()
            self._refreshCounter()
            self.imageChanged.emit(self._current_view, self._current_idx)
            self.update()

    def _onRight(self):
        images = self._view_thumbs.get(self._current_view, [])
        if len(images) > 1:
            self._current_idx = (self._current_idx + 1) % len(images)
            self._loadImage()
            self._resetView()
            self._refreshCounter()
            self.imageChanged.emit(self._current_view, self._current_idx)
            self.update()

    def _onDot(self, view):
        if not self._view_thumbs.get(view):
            return
        self._current_view = view
        self._current_idx = 0
        self._loadImage()
        self._resetView()
        self._updateDotStyles()
        self._refreshArrows()
        self._refreshCounter()
        self.imageChanged.emit(self._current_view, self._current_idx)
        self.update()

    def _refreshArrows(self):
        if self._view_mode != "2d":
            self._arrow_left.hide()
            self._arrow_right.hide()
            return
        n = len(self._view_thumbs.get(self._current_view, []))
        self._arrow_left.setVisible(n > 1)
        self._arrow_right.setVisible(n > 1)

    def _refreshCounter(self):
        if self._view_mode != "2d":
            self._counter.hide()
            return
        images = self._view_thumbs.get(self._current_view, [])
        n = len(images)
        if n > 1:
            self._counter.setText("%d/%d" % (self._current_idx + 1, n))
            self._counter.adjustSize()
            self._counter.show()
        else:
            self._counter.hide()

    def _updateDotStyles(self):
        for view, _ in _VIEWS:
            has = bool(self._view_thumbs.get(view))
            active = (view == self._current_view) and has
            self._dots[view].setState(view, active, has)

    def _toggleViewMode(self):
        self._view_mode = "3d" if self._view_mode == "2d" else "2d"
        self._mode_btn.setMode(self._view_mode)
        if self._view_mode == "2d":
            self._loadImage()
        else:
            self._orig_px = None
        self._resetView()
        self._refreshArrows()
        self._refreshCounter()
        self.update()

    # ── Zoom / pan helpers ─────────────────────────────────────────────────

    def _baseScale(self):
        if not self._orig_px or self._orig_px.isNull():
            return 1.0
        iw, ih = self._orig_px.width(), self._orig_px.height()
        if iw == 0 or ih == 0:
            return 1.0
        return min(self.width() / iw, self.height() / ih)

    def _drawSize(self):
        base = self._baseScale()
        iw = self._orig_px.width()
        ih = self._orig_px.height()
        return max(1, int(iw * base * self._zoom)), max(1, int(ih * base * self._zoom))

    # ── Paint ──────────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(26, 26, 26))
        if self._view_mode == "3d":
            self._drawCubePlaceholder(p)
        elif self._orig_px and not self._orig_px.isNull():
            dw, dh = self._drawSize()
            x = int((self.width()  - dw) / 2 + self._pan_x)
            y = int((self.height() - dh) / 2 + self._pan_y)
            scaled = self._orig_px.scaled(dw, dh, Qt.IgnoreAspectRatio,
                                          Qt.SmoothTransformation)
            p.drawPixmap(x, y, scaled)

    def _drawCubePlaceholder(self, p):
        w, h = self.width(), self.height()
        scale = min(w, h) / 320.0
        s = max(36, int(42 * scale))
        off = max(16, int(18 * scale))
        cx = w // 2
        cy = h // 2 - off
        p.setPen(QPen(QColor(255, 255, 255, 45), max(1, int(2 * scale))))
        p.drawRect(cx - s, cy - s, s * 2, s * 2)
        p.drawRect(cx - s + off, cy - s + off, s * 2, s * 2)
        p.drawLine(cx - s, cy - s, cx - s + off, cy - s + off)
        p.drawLine(cx + s, cy - s, cx + s + off, cy - s + off)
        p.drawLine(cx - s, cy + s, cx - s + off, cy + s + off)
        p.drawLine(cx + s, cy + s, cx + s + off, cy + s + off)
        font = p.font()
        font.setPixelSize(max(28, int(30 * scale)))
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 58))
        p.drawText(QRectF(0, cy + s + off + 18, w, 48), Qt.AlignCenter, "3D Preview")

    # ── Input ──────────────────────────────────────────────────────────────

    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        factor = self._ZOOM_STEP if delta > 0 else 1.0 / self._ZOOM_STEP
        new_zoom = max(self._ZOOM_MIN, min(self._ZOOM_MAX, self._zoom * factor))
        if new_zoom == self._zoom:
            return
        # Zoom centred on cursor
        cx = e.x() - self.width()  / 2
        cy = e.y() - self.height() / 2
        self._pan_x = cx - (cx - self._pan_x) * new_zoom / self._zoom
        self._pan_y = cy - (cy - self._pan_y) * new_zoom / self._zoom
        self._zoom = new_zoom
        self.update()
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = e.pos()
            self._pan_offset_start = (self._pan_x, self._pan_y)
            self.setCursor(Qt.ClosedHandCursor)
            e.accept()

    def mouseMoveEvent(self, e):
        if self._panning and self._pan_start is not None:
            d = e.pos() - self._pan_start
            self._pan_x = self._pan_offset_start[0] + d.x()
            self._pan_y = self._pan_offset_start[1] + d.y()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MiddleButton:
            self._panning = False
            self.unsetCursor()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton and self.childAt(e.pos()) is None:
            self._resetView()
            self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        elif e.key() == Qt.Key_Left:
            self._onLeft()
        elif e.key() == Qt.Key_Right:
            self._onRight()


class _MetadataSection(QWidget):
    tagClicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._build()

    def _build(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._rows = QVBoxLayout()
        self._rows.setSpacing(8)
        self._layout.addLayout(self._rows)

    def setAsset(self, asset_data):
        # Clear existing rows
        while self._rows.count():
            item = self._rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            if item.layout():
                self._clearLayout(item.layout())

        if not asset_data:
            return

        d = asset_data

        # Tags — always first, no label
        tags = d.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        elif tags is None:
            tags = []
        if tags:
            self._rows.addWidget(self._pills_only(tags))

        # File type
        ft = _text(d.get("filetype"))
        if ft:
            self._rows.addWidget(self._kv("File type", ft))

        # Renderer
        renderer = _text(d.get("renderer"), "Any") or "Any"
        self._rows.addWidget(self._kv("Renderer", renderer))

        # DCC
        dcc = _text(d.get("dcc"), "Universal") or "Universal"
        self._rows.addWidget(self._kv("DCC", dcc))

        # Author
        author = _text(d.get("author"))
        if author:
            self._rows.addWidget(self._kv("Author", author))

        # Project
        project = _text(d.get("project"))
        if project:
            self._rows.addWidget(self._kv("Project", project))

        # Includes
        includes = []
        if d.get("has_rig"):
            includes.append("Rig")
        if d.get("has_textures"):
            includes.append("Textures")
        if d.get("has_materials"):
            includes.append("Materials")
        if includes:
            self._rows.addWidget(self._pills("Includes", includes))

        # Dates
        created = _text(d.get("created_at"))
        if created:
            self._rows.addWidget(self._kv("Created", created[:10]))
        updated = _text(d.get("updated_at"))
        if updated:
            self._rows.addWidget(self._kv("Updated", updated[:10]))

    def _title(self, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            "font-size: 15px; font-weight: 600; color: %s; background: transparent;"
            % TEXT_PRIMARY
        )
        return lbl

    def _kv(self, label, value):
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        k = QLabel(label.upper())
        k.setFixedWidth(80)
        k.setStyleSheet(
            "font-size: 10px; color: %s; font-family: 'IBM Plex Mono', monospace;"
            " background: transparent;" % TEXT_TERTIARY
        )
        v = QLabel(value)
        v.setWordWrap(True)
        v.setStyleSheet(
            "font-size: 11px; color: %s; background: transparent;" % TEXT_PRIMARY
        )
        layout.addWidget(k)
        layout.addWidget(v, 1)
        return row

    def _pills_only(self, items):
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for item in items:
            pill = _ClickablePill(_text(item))
            pill.clicked.connect(lambda t=_text(item): self.tagClicked.emit(t))
            layout.addWidget(pill)
        layout.addStretch()
        return row

    def _pills(self, label, items):
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        k = QLabel(label.upper())
        k.setFixedWidth(80)
        k.setAlignment(Qt.AlignTop)
        k.setStyleSheet(
            "font-size: 10px; color: %s; font-family: 'IBM Plex Mono', monospace;"
            " background: transparent;" % TEXT_TERTIARY
        )
        layout.addWidget(k)
        pills_row = QHBoxLayout()
        pills_row.setSpacing(4)
        for item in items:
            pill = QLabel(_text(item))
            pill.setStyleSheet(
                "background: %s; color: %s; border: 1px solid %s;"
                " border-radius: 10px; padding: 2px 8px; font-size: 10px;"
                % (ACCENT_BG, ACCENT_TEXT, ACCENT_BORDER)
            )
            pills_row.addWidget(pill)
        pills_row.addStretch()
        layout.addLayout(pills_row, 1)
        return row

    def _path(self, label, value):
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        k = QLabel(label.upper())
        k.setFixedWidth(80)
        k.setAlignment(Qt.AlignTop)
        k.setStyleSheet(
            "font-size: 10px; color: %s; font-family: 'IBM Plex Mono', monospace;"
            " background: transparent;" % TEXT_TERTIARY
        )
        v = QLabel(value)
        v.setWordWrap(True)
        v.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.setStyleSheet(
            "font-size: 10px; color: %s; font-family: 'IBM Plex Mono', monospace;"
            " background: transparent;" % TEXT_SECONDARY
        )
        layout.addWidget(k)
        layout.addWidget(v, 1)
        return row

    def _clearLayout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            if item.layout():
                self._clearLayout(item.layout())


class _InspCloseBtn(QWidget):
    """Small close button for the inspector preview — same style as fullscreen close."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(160, 30, 30, 200) if self._hover else QColor(0, 0, 0, 110))
        p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        p.setPen(QColor(255, 255, 255, 220 if self._hover else 170))
        font = p.font()
        font.setPixelSize(12)
        p.setFont(font)
        p.drawText(QRectF(self.rect()), Qt.AlignCenter, "✕")

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        e.accept()


class _ExpandBtn(QWidget):
    """4-corner expand icon, matching the other preview overlay controls."""
    clicked = Signal()
    _SCALE = 1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(int(28 * self._SCALE), int(28 * self._SCALE))
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 140 if self._hover else 90))
        radius = 5 * self._SCALE
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        pen = QPen(QColor(205, 211, 219), int(2 * self._SCALE),
                   Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        icon_size = int(14 * self._SCALE)
        arm = int(5 * self._SCALE)
        left = int((self.width() - icon_size) / 2)
        top = int((self.height() - icon_size) / 2)
        right = left + icon_size
        bottom = top + icon_size

        p.drawLine(left, top + arm, left, top)
        p.drawLine(left, top, left + arm, top)
        p.drawLine(right - arm, top, right, top)
        p.drawLine(right, top, right, top + arm)
        p.drawLine(right, bottom - arm, right, bottom)
        p.drawLine(right, bottom, right - arm, bottom)
        p.drawLine(left + arm, bottom, left, bottom)
        p.drawLine(left, bottom, left, bottom - arm)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class _ClickablePill(QLabel):
    clicked = Signal()

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        self.setStyleSheet(
            "background: %s; color: %s; border: 1px solid %s;"
            " border-radius: 10px; padding: 2px 8px; font-size: 10px;"
            % (ACCENT_BG, ACCENT_TEXT, ACCENT_BORDER)
        )

    def enterEvent(self, e):
        self._hover = True
        self.setStyleSheet(
            "background: %s; color: %s; border: 1px solid %s;"
            " border-radius: 10px; padding: 2px 8px; font-size: 10px;"
            % (ACCENT_BORDER, ACCENT_TEXT, ACCENT)
        )

    def leaveEvent(self, e):
        self._hover = False
        self.setStyleSheet(
            "background: %s; color: %s; border: 1px solid %s;"
            " border-radius: 10px; padding: 2px 8px; font-size: 10px;"
            % (ACCENT_BG, ACCENT_TEXT, ACCENT_BORDER)
        )

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class _FsCloseBtn(QWidget):
    """Fullscreen close button — circle with ✕, same dark opacity as the counter."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(52, 52)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(160, 30, 30, 180) if self._hover else QColor(0, 0, 0, 60))
        p.drawEllipse(QRectF(self.rect()).adjusted(2, 2, -2, -2))
        p.setPen(QColor(255, 255, 255, 220 if self._hover else 160))
        font = p.font()
        font.setPixelSize(22)
        p.setFont(font)
        p.drawText(QRectF(self.rect()), Qt.AlignCenter, "✕")

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        e.accept()
