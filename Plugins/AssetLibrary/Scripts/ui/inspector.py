import os

from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QDialog,
)
from qtpy.QtCore import Qt, Signal, QRectF
from qtpy.QtGui import QPixmap, QColor, QPainter, QPainterPath, QPen

from ui.styles import (
    BG_PRIMARY, BG_SECONDARY, BG_TERTIARY,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    BORDER_LIGHT, BORDER_MID, ACCENT, ACCENT_BG, ACCENT_TEXT, ACCENT_BORDER,
    THUMB_PALETTES,
)
from ui.asset_card import _ViewModeToggle

_VIEWS = [
    ("material", "#5ba3e0"),
    ("clay",     "#c8934a"),
    ("wire",     "#5dc8a0"),
]

_PREVIEW_SIZE = 310


class InspectorPanel(QWidget):
    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inspectorPanel")
        self.setFixedWidth(340)
        self._asset_data = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        header = QWidget()
        header.setFixedHeight(36)
        header.setStyleSheet("background: %s;" % BG_SECONDARY)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(12, 0, 8, 0)
        title = QLabel("Inspector")
        title.setStyleSheet(
            "font-size: 11px; font-weight: 500; color: %s; background: transparent;"
            % TEXT_TERTIARY
        )
        h_layout.addWidget(title)
        h_layout.addStretch()
        close_btn = QPushButton("X")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet(
            "border: none; background: transparent; color: %s; font-size: 12px;"
            % TEXT_TERTIARY
        )
        close_btn.clicked.connect(self.closeRequested.emit)
        h_layout.addWidget(close_btn)
        root.addWidget(header)

        # Scrollable body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: %s; border: none; }" % BG_SECONDARY
        )

        body = QWidget()
        body.setStyleSheet("background: %s;" % BG_SECONDARY)
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(14, 10, 14, 14)
        self._body_layout.setSpacing(10)

        # Preview
        self.preview = InspectorPreview()
        self._body_layout.addWidget(self.preview, 0, Qt.AlignHCenter)

        # Metadata
        self.metadata = _MetadataSection()
        self._body_layout.addWidget(self.metadata)

        # 3D viewport placeholder
        self.viewport = _ViewportPlaceholder()
        self._body_layout.addWidget(self.viewport)

        self._body_layout.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

    def setAsset(self, asset_data):
        self._asset_data = asset_data
        self.preview.setAsset(asset_data)
        self.metadata.setAsset(asset_data)


class InspectorPreview(QWidget):
    """Large thumbnail preview with gallery controls and fullscreen button."""

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
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setMouseTracking(True)
        self._build()

    def _build(self):
        self._radius = 8

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

        # Counter
        self.counter = _InspCounter(self)
        self.counter.hide()

        # Fullscreen button
        self.fs_btn = _ExpandBtn(self)
        self.fs_btn.setToolTip("Fullscreen preview")
        self.fs_btn.clicked.connect(self._onFullscreen)
        self.fs_btn.hide()

        # View mode toggle — always visible (no hide)
        self._mode_toggle = _ViewModeToggle(self, height=18)
        self._mode_toggle.toggled.connect(self._onViewModeToggled)

        self._positionOverlays()

    def _positionOverlays(self):
        s = _PREVIEW_SIZE
        mid_y = (s - 44) // 2
        self.arrow_left.move(6, mid_y)
        self.arrow_right.move(s - 50, mid_y)

        dot_size, dot_gap = 18, 8
        total = len(_VIEWS) * dot_size + (len(_VIEWS) - 1) * dot_gap
        dx = (s - total) // 2
        dy = s - 28
        for i, (view, _) in enumerate(_VIEWS):
            self._dots[view].move(dx + i * (dot_size + dot_gap), dy)

        self.counter.adjustSize()
        self.counter.move(s - self.counter.width() - 6, 6)

        self.fs_btn.move(s - 34, s - 34)

        self._mode_toggle.move(8, dy)
        self._mode_toggle.raise_()

    def setAsset(self, asset_data):
        self._asset_data = asset_data
        if self._view_mode != "2d":
            self._view_mode = "2d"
            self._mode_toggle.setMode("2d")
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
            for fname in sorted(os.listdir(tp)):
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
            self.arrow_left.hide(); self.arrow_right.hide(); return
        n = len(self._view_thumbs.get(self._current_view, []))
        if n > 1:
            self.arrow_left.show()
            self.arrow_right.show()
        else:
            self.arrow_left.hide()
            self.arrow_right.hide()

    def _refreshCounter(self):
        images = self._view_thumbs.get(self._current_view, [])
        n = len(images)
        if n > 1:
            self.counter.setText("%d/%d" % (self._current_idx + 1, n))
            self.counter.adjustSize()
            self.counter.move(_PREVIEW_SIZE - self.counter.width() - 6, 6)
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

    def _onViewModeToggled(self, mode):
        self._view_mode = mode
        if mode == "2d":
            self._showThumb()
        else:
            self._orig_px = None
        self._refreshArrows()
        self.update()

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
        for dot in self._dots.values():
            if dot._available:
                dot.show()
        self._refreshArrows()
        self._refreshCounter()
        self.fs_btn.show()
        self.fs_btn.raise_()

    def leaveEvent(self, e):
        self._hover = False
        for dot in self._dots.values():
            dot.hide()
        self.arrow_left.hide()
        self.arrow_right.hide()
        self.counter.hide()
        self.fs_btn.hide()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        r = QRectF(self.rect())
        d = self._radius * 2.0
        clip = QPainterPath()
        clip.moveTo(r.left() + self._radius, r.top())
        clip.lineTo(r.right() - self._radius, r.top())
        clip.arcTo(r.right() - d, r.top(), d, d, 90, -90)
        clip.lineTo(r.right(), r.bottom())
        clip.lineTo(r.left(), r.bottom())
        clip.arcTo(r.left(), r.top(), d, d, 180, -90)
        clip.closeSubpath()
        p.setClipPath(clip)

        if self._view_mode == "3d":
            idx = self._asset_data.get("id", 0) % len(THUMB_PALETTES) if self._asset_data else 0
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
                idx = self._asset_data.get("id", 0) % len(THUMB_PALETTES)
                bg, fg = THUMB_PALETTES[idx]
            else:
                bg, fg = BG_TERTIARY, TEXT_TERTIARY
            p.fillRect(self.rect(), QColor(bg))
            if self._asset_data:
                font = p.font()
                font.setPixelSize(40)
                p.setFont(font)
                p.setPen(QColor(fg))
                name = self._asset_data.get("name") or "?"
                p.drawText(r, Qt.AlignCenter, name[0].upper())


class _InspArrowBtn(QWidget):
    clicked = Signal()

    def __init__(self, parent=None, mirror=False):
        super().__init__(parent)
        self._mirror = mirror
        self._hover = False
        self.setFixedSize(44, 44)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_NoSystemBackground)

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
        self.setAttribute(Qt.WA_NoSystemBackground)
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
        self.setAttribute(Qt.WA_NoSystemBackground)
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
        total = len(_VIEWS) * dot_size + (len(_VIEWS) - 1) * dot_gap
        dx = (w - total) // 2
        for i, (view, _) in enumerate(_VIEWS):
            self._dots[view].move(dx + i * (dot_size + dot_gap), h - 80)

        close_x = w - 64
        self._close_btn.move(close_x, 16)

        self._counter.adjustSize()
        self._counter.move(close_x - self._counter.width() - 12, 24)

        for w_ in (self._arrow_left, self._arrow_right, self._counter, self._close_btn):
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
        n = len(self._view_thumbs.get(self._current_view, []))
        self._arrow_left.setVisible(n > 1)
        self._arrow_right.setVisible(n > 1)

    def _refreshCounter(self):
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
        if self._orig_px and not self._orig_px.isNull():
            dw, dh = self._drawSize()
            x = int((self.width()  - dw) / 2 + self._pan_x)
            y = int((self.height() - dh) / 2 + self._pan_y)
            scaled = self._orig_px.scaled(dw, dh, Qt.IgnoreAspectRatio,
                                          Qt.SmoothTransformation)
            p.drawPixmap(x, y, scaled)

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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._build()

    def _build(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: %s; border: none;" % BORDER_LIGHT)
        self._layout.addWidget(sep)
        self._layout.addSpacing(10)

        # Container for rows
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

        # Name
        name = d.get("name", "")
        if name:
            self._rows.addWidget(self._title(name))

        # Category . Subcategory
        cat = d.get("category", "")
        sub = d.get("subcategory", "")
        cat_text = cat + (" / " + sub if sub else "")
        if cat_text:
            self._rows.addWidget(self._kv("Category", cat_text))

        # Version
        ver = d.get("version", "")
        if ver:
            self._rows.addWidget(self._kv("Version", ver))

        # File type
        ft = d.get("filetype", "")
        if ft:
            self._rows.addWidget(self._kv("File type", ft))

        # Renderer
        renderer = d.get("renderer", "Any")
        self._rows.addWidget(self._kv("Renderer", renderer))

        # DCC
        dcc = d.get("dcc", "Universal")
        self._rows.addWidget(self._kv("DCC", dcc))

        # Author
        author = d.get("author", "")
        if author:
            self._rows.addWidget(self._kv("Author", author))

        # Project
        project = d.get("project", "")
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

        # Tags
        tags = d.get("tags", [])
        if tags:
            self._rows.addWidget(self._pills("Tags", tags))

        # File path
        filepath = d.get("filepath", "")
        if filepath:
            self._rows.addWidget(self._path("Path", filepath))

        # Dates
        created = d.get("created_at", "")
        if created:
            self._rows.addWidget(self._kv("Created", created[:10]))
        updated = d.get("updated_at", "")
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
            pill = QLabel(item)
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


class _ViewportPlaceholder(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(160)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("3D preview coming in a future update")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.setPen(QPen(QColor(255, 255, 255, 15), 1))
        p.setBrush(QColor(BG_TERTIARY))
        p.drawPath(path)

        # Cube icon (simple wireframe cube)
        cx, cy = self.width() // 2, self.height() // 2 - 10
        s = 18
        # Front face
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.drawRect(cx - s, cy - s, s * 2, s * 2)
        # Back face offset
        off = 8
        p.drawRect(cx - s + off, cy - s + off, s * 2, s * 2)
        # Connecting lines
        p.drawLine(cx - s, cy - s, cx - s + off, cy - s + off)
        p.drawLine(cx + s, cy - s, cx + s + off, cy - s + off)
        p.drawLine(cx - s, cy + s, cx - s + off, cy + s + off)
        p.drawLine(cx + s, cy + s, cx + s + off, cy + s + off)

        # Label
        font = p.font()
        font.setPixelSize(11)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 50))
        p.drawText(QRectF(0, cy + s + 14, self.width(), 20), Qt.AlignCenter, "3D Preview")


class _ExpandBtn(QWidget):
    """4-corner expand icon, semi-transparent dark pill — matches overlay style."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        self.setAttribute(Qt.WA_NoSystemBackground)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Background pill
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 140 if self._hover else 90))
        p.drawRoundedRect(QRectF(self.rect()), 5, 5)

        # 4-corner arrows
        pen = QPen(QColor(255, 255, 255, 200 if self._hover else 140), 1.5,
                   Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        a = 5   # arm length
        g = 7   # distance from centre to corner
        cx, cy = 14, 14
        for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            ox, oy = cx + dx * g, cy + dy * g
            p.drawLine(int(ox), int(oy), int(ox - dx * a), int(oy))
            p.drawLine(int(ox), int(oy), int(ox), int(oy - dy * a))

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


class _FsCloseBtn(QWidget):
    """Fullscreen close button — circle with ✕, same dark opacity as the counter."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(52, 52)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        self.setAttribute(Qt.WA_NoSystemBackground)

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
