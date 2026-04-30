import os

from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QMenu, QAction, QActionGroup, QSizePolicy,
)
from qtpy.QtCore import Qt, Signal, QRectF
from qtpy.QtGui import QPixmap, QColor, QPainter, QPainterPath, QPen

from ui.styles import (
    BG_PRIMARY, BG_SECONDARY, BG_TERTIARY, TEXT_PRIMARY, TEXT_TERTIARY,
    BORDER_LIGHT, BORDER_MID, ACCENT, ACCENT_BG, ACCENT_TEXT,
    THUMB_PALETTES,
)

DEFAULT_CARD_WIDTH = 118

_VIEWS = [
    ("material", "#5ba3e0"),
    ("clay",     "#c8934a"),
    ("wire",     "#5dc8a0"),
]

_CARD_RADIUS = 6


class AssetCard(QWidget):
    starToggled     = Signal(int, bool)
    assetImport     = Signal(dict)
    assetClicked    = Signal(dict)
    versionChanged  = Signal(int, str)
    filetypeChanged = Signal(int, str)

    def __init__(self, asset_data, is_favorite=False, versions=None,
                 filetypes=None, parent=None):
        super().__init__(parent)
        self.asset_data = asset_data
        self._is_fav    = is_favorite
        self._versions  = versions or []
        self._filetypes = filetypes or []
        self._selected_version  = asset_data.get("version", "")
        self._selected_filetype = asset_data.get("filetype", "")
        self._current_view = "material"
        self._view_thumbs  = {"material": [], "clay": [], "wire": []}
        self._current_idx  = 0
        self._selected     = False
        self._hover        = False
        self._scanThumbs()

        # Prevent Qt from pre-erasing the widget rect to the palette dark colour
        # before our paintEvent runs — that's what caused the black corner artifact.
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setMouseTracking(True)

        self._build()
        # Overlay draws the border on top of all children (thumb would cover it otherwise)
        self._border = _BorderOverlay(self)
        self.setCardWidth(DEFAULT_CARD_WIDTH)
        self._showThumb()

    # ── Thumbnail discovery ────────────────────────────────────────────

    def _scanThumbs(self):
        tp = self.asset_data.get("thumbnail_path", "") or ""
        lib_root = self.asset_data.get("_lib_root", "") or ""
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

    # ── Build ──────────────────────────────────────────────────────────

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.thumb = _ThumbWidget(self.asset_data, self)
        layout.addWidget(self.thumb)

        # ── Overlays (absolute children of the card, not thumb) ──────
        # Parenting to self (AssetCard) avoids a Qt/Windows issue where
        # WA_NoSystemBackground on _ThumbWidget causes its children to
        # lose native-window embedding and appear as floating top-level
        # windows at screen position (0, 0).

        # Star — top-left
        self.star_btn = _StarBtn(self)
        self.star_btn.setCursor(Qt.PointingHandCursor)
        self.star_btn.clicked.connect(self._onStarClicked)
        self.star_btn.setFav(self._is_fav)
        if not self._is_fav:
            self.star_btn.hide()

        # Arrows — circle buttons matching HTML .thumb-arrow-btn
        self.arrow_left  = _ArrowBtn(self)
        self.arrow_right = _ArrowBtn(self, mirror=True)
        self.arrow_left.hide()
        self.arrow_right.hide()
        self.arrow_left.clicked.connect(self._onArrowLeft)
        self.arrow_right.clicked.connect(self._onArrowRight)

        # View dots
        self._dots = {}
        for view, _ in _VIEWS:
            dot = _DotButton(self)
            dot.setCursor(Qt.PointingHandCursor)
            dot.hide()
            dot.clicked.connect(lambda v=view: self._onViewDotClicked(v))
            self._dots[view] = dot

        # Counter pill — top-right
        self.thumb_counter = _CounterLabel("", self)
        self.thumb_counter.setStyleSheet(
            "QLabel { color: white; font-size: 13px;"
            " font-family: 'IBM Plex Mono', monospace; padding: 2px 8px; }"
        )
        self.thumb_counter.hide()

        # ── Info row ──────────────────────────────────────────────────
        info = QWidget()
        info.setAttribute(Qt.WA_NoSystemBackground)
        info.setStyleSheet(
            "QWidget { background: %(bg)s; border-top: 1px solid %(bl)s;"
            " border-bottom-left-radius: 6px; border-bottom-right-radius: 6px; }"
            % {"bg": BG_SECONDARY, "bl": BORDER_LIGHT}
        )
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(8, 5, 8, 6)
        info_layout.setSpacing(2)

        self.name_label = QLabel(self.asset_data.get("name", ""))
        self.name_label.setStyleSheet(
            "font-size: 11px; font-weight: 500; color: %s; background: transparent;" % TEXT_PRIMARY
        )
        self.name_label.setMaximumWidth(9999)
        self.name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        cat = self.asset_data.get("category", "")
        ft  = self._selected_filetype or self.asset_data.get("filetype", "")
        self.sub_label = QLabel("%s · %s" % (cat, ft))
        self.sub_label.setStyleSheet(
            "font-size: 10px; color: %s; font-family: 'IBM Plex Mono', monospace;"
            " background: transparent;" % TEXT_TERTIARY
        )

        info_layout.addWidget(self.name_label)
        info_layout.addWidget(self.sub_label)
        layout.addWidget(info)

        self._updateDotStyles()

    # ── Custom paint — background only (border is drawn by _BorderOverlay) ──

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        fill = QPainterPath()
        fill.addRoundedRect(QRectF(self.rect()), _CARD_RADIUS, _CARD_RADIUS)
        p.fillPath(fill, QColor(BG_PRIMARY))

    # ── Sizing / layout ────────────────────────────────────────────────

    def setCardWidth(self, w):
        thumb_h = max(60, w)
        card_h  = thumb_h + 46
        self.setFixedSize(w, card_h)
        self.thumb.setFixedSize(w, thumb_h)

        self.star_btn.move(5, 4)

        mid_y = (thumb_h - 44) // 2
        self.arrow_left.move(5, mid_y)
        self.arrow_right.move(w - 49, mid_y)

        dot_size, dot_gap = 22, 9
        total_w = len(_VIEWS) * dot_size + (len(_VIEWS) - 1) * dot_gap
        dot_x = (w - total_w) // 2
        dot_y = thumb_h - 30
        for i, (view, _) in enumerate(_VIEWS):
            self._dots[view].move(dot_x + i * (dot_size + dot_gap), dot_y)

        self.thumb_counter.adjustSize()
        self.thumb_counter.move(w - self.thumb_counter.width() - 5, 5)

        for w_ in (self.star_btn, self.arrow_left, self.arrow_right, self.thumb_counter):
            w_.raise_()
        for dot in self._dots.values():
            dot.raise_()

        # Border overlay always on top of everything
        self._border.setGeometry(0, 0, w, card_h)
        self._border.raise_()

    # ── Hover ──────────────────────────────────────────────────────────

    def _onHoverEnter(self):
        self._hover = True
        self._border.setHover(True)
        self._border._selected = self._selected
        if not self._is_fav:
            self.star_btn.show()
            self.star_btn.raise_()
        for dot in self._dots.values():
            dot.show()
            dot.raise_()
        self._refreshArrows()
        self._refreshCounter()

    def _onHoverLeave(self):
        if self.underMouse():
            return
        self._hover = False
        self._border.setHover(self._selected)
        if not self._is_fav:
            self.star_btn.hide()
        for dot in self._dots.values():
            dot.hide()
        self.arrow_left.hide()
        self.arrow_right.hide()
        self.thumb_counter.hide()

    def enterEvent(self, e):
        self._onHoverEnter()

    def leaveEvent(self, e):
        self._onHoverLeave()

    # ── Interaction ────────────────────────────────────────────────────

    def _onStarClicked(self):
        self._is_fav = not self._is_fav
        self.star_btn.setFav(self._is_fav)
        if self._is_fav:
            self.star_btn.show()
            self.star_btn.raise_()
        elif not self._hover:
            self.star_btn.hide()
        self.starToggled.emit(self.asset_data.get("id", -1), self._is_fav)

    def _onArrowLeft(self):
        images = self._view_thumbs.get(self._current_view, [])
        if len(images) > 1:
            self._current_idx = (self._current_idx - 1) % len(images)
            self._showThumb()
            self._refreshCounter()

    def _onArrowRight(self):
        images = self._view_thumbs.get(self._current_view, [])
        if len(images) > 1:
            self._current_idx = (self._current_idx + 1) % len(images)
            self._showThumb()
            self._refreshCounter()

    def _onViewDotClicked(self, view):
        if not self._view_thumbs.get(view):
            return
        self._current_view = view
        self._current_idx  = 0
        self._showThumb()
        self._updateDotStyles()
        self._refreshArrows()
        self._refreshCounter()

    def mouseDoubleClickEvent(self, e):
        self.assetImport.emit(self.asset_data)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.assetClicked.emit(self.asset_data)

    def setSelected(self, selected):
        self._selected = selected
        self._border._selected = selected
        self._border.setHover(selected or self._hover)
        self._border.update()

    # ── Thumbnail display ───────────────────────────────────────────────

    def _showThumb(self):
        images = self._view_thumbs.get(self._current_view, [])
        if images and 0 <= self._current_idx < len(images):
            self.thumb.setImage(images[self._current_idx])
        else:
            self.thumb.clearImage()

    def _refreshArrows(self):
        n = len(self._view_thumbs.get(self._current_view, []))
        if n > 1:
            self.arrow_left.show()
            self.arrow_left.raise_()
            self.arrow_right.show()
            self.arrow_right.raise_()
        else:
            self.arrow_left.hide()
            self.arrow_right.hide()

    def _refreshCounter(self):
        images = self._view_thumbs.get(self._current_view, [])
        n = len(images)
        if n > 1:
            self.thumb_counter.setText("%d/%d" % (self._current_idx + 1, n))
            self.thumb_counter.adjustSize()
            self.thumb_counter.move(self.width() - self.thumb_counter.width() - 5, 5)
            self.thumb_counter.show()
            self.thumb_counter.raise_()
        else:
            self.thumb_counter.hide()

    def _updateDotStyles(self):
        for view, _ in _VIEWS:
            dot = self._dots[view]
            has    = bool(self._view_thumbs.get(view))
            active = (view == self._current_view) and has
            dot.setState(view, active, has)

    # ── Context menu ───────────────────────────────────────────────────

    def contextMenuEvent(self, e):
        ss = self._menuStylesheet()
        menu = QMenu(self)
        menu.setStyleSheet(ss)

        if self._versions:
            ver_menu = QMenu("Version", menu)
            ver_menu.setStyleSheet(ss)
            grp = QActionGroup(ver_menu)
            grp.setExclusive(True)
            seen = set()
            for v in self._versions:
                ver_str = v.get("version", "")
                if ver_str in seen:
                    continue
                seen.add(ver_str)
                checked = ver_str == self._selected_version
                a = QAction(("● " if checked else "   ") + ver_str, ver_menu)
                a.setCheckable(True)
                a.setChecked(checked)
                a.triggered.connect(lambda _, v=ver_str: self._onVersionPicked(v))
                grp.addAction(a)
                ver_menu.addAction(a)
            menu.addMenu(ver_menu)

        if self._filetypes:
            ft_menu = QMenu("File type", menu)
            ft_menu.setStyleSheet(ss)
            grp2 = QActionGroup(ft_menu)
            grp2.setExclusive(True)
            for ft in self._filetypes:
                checked = ft == self._selected_filetype
                a = QAction(("● " if checked else "   ") + ft, ft_menu)
                a.setCheckable(True)
                a.setChecked(checked)
                a.triggered.connect(lambda _, f=ft: self._onFiletypePicked(f))
                grp2.addAction(a)
                ft_menu.addAction(a)
            menu.addMenu(ft_menu)

        usd_exts = {".usd", ".usda", ".usdc", ".usdz"}
        has_usd = any(
            os.path.splitext(v.get("filepath", ""))[1].lower() in usd_exts
            for v in self._versions
        )
        if has_usd:
            menu.addSeparator()
            menu.addAction("View USD").triggered.connect(self._onViewUSD)
            menu.addAction("View USD via Prism").triggered.connect(self._onViewUSDPrism)

        menu.addSeparator()
        menu.addAction("Open in Explorer").triggered.connect(self._onOpenInExplorer)
        menu.addSeparator()
        fav_label = "Remove from Favourites" if self._is_fav else "Add to Favourites"
        menu.addAction(fav_label).triggered.connect(self._onStarClicked)
        menu.addAction("Edit asset…").triggered.connect(self._onEditAsset)

        menu.exec_(e.globalPos())

    def _onVersionPicked(self, version):
        self._selected_version = version
        self.versionChanged.emit(self.asset_data.get("id", -1), version)

    def _onFiletypePicked(self, filetype):
        self._selected_filetype = filetype
        cat = self.asset_data.get("category", "")
        self.sub_label.setText("%s · %s" % (cat, filetype))
        self.filetypeChanged.emit(self.asset_data.get("id", -1), filetype)

    def _onOpenInExplorer(self):
        import subprocess
        lib_root = self.asset_data.get("_lib_root", "")
        filepath = ""
        for v in self._versions:
            if (v.get("version") == self._selected_version
                    and v.get("filetype") == self._selected_filetype):
                filepath = v.get("filepath", "")
                break
        if not filepath:
            filepath = self.asset_data.get("filepath", "")
        if filepath and not os.path.isabs(filepath) and lib_root:
            filepath = os.path.join(lib_root, filepath)
        folder = os.path.dirname(filepath) if filepath else ""
        if folder and os.path.isdir(folder):
            subprocess.Popen(["explorer", os.path.normpath(folder)])
        elif lib_root and os.path.isdir(lib_root):
            subprocess.Popen(["explorer", os.path.normpath(lib_root)])

    def _onViewUSD(self):
        pass

    def _onViewUSDPrism(self):
        pass

    def _onEditAsset(self):
        from ui.publish_dialog import PublishDialog
        dlg = PublishDialog(self.asset_data, parent=self)
        dlg.exec_()

    def _menuStylesheet(self):
        return """
            QMenu {
                background-color: %(bg)s;
                border: 1px solid %(bm)s;
                border-radius: 8px;
                padding: 4px 0;
                font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
                font-size: 12px;
                color: %(ts)s;
            }
            QMenu::item { padding: 5px 18px 5px 22px; background: transparent; }
            QMenu::item:selected {
                background-color: %(bg2)s; color: %(tp)s; border-radius: 4px;
            }
            QMenu::item:disabled {
                color: %(tt)s; font-size: 10px;
                font-family: "IBM Plex Mono", monospace;
                letter-spacing: 1px; padding: 8px 18px 2px 12px;
            }
            QMenu::item:checked { color: %(accent)s; font-weight: 500; }
            QMenu::indicator { width: 0; height: 0; }
            QMenu::separator { height: 1px; background: %(bl)s; margin: 3px 8px; }
        """ % {
            "bg": BG_SECONDARY, "bg2": BG_TERTIARY, "bl": BORDER_LIGHT, "bm": BORDER_MID,
            "tp": TEXT_PRIMARY, "ts": TEXT_TERTIARY, "tt": TEXT_TERTIARY, "accent": ACCENT,
        }


# ── Border overlay ─────────────────────────────────────────────────────────

class _BorderOverlay(QWidget):
    """
    Transparent widget that sits above all card children and draws only the
    rounded border.  Because it paints last, the border appears on top of
    the thumbnail image instead of being covered by it.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = False
        self._selected = False
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def setHover(self, hover):
        if self._hover != hover:
            self._hover = hover
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
            _CARD_RADIUS - 0.5, _CARD_RADIUS - 0.5,
        )
        if self._selected:
            p.setPen(QPen(QColor(ACCENT), 1.5))
        elif self._hover:
            p.setPen(QPen(QColor(255, 255, 255, 75), 1.0))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 20), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


# ── Counter pill ────────────────────────────────────────────────────────────

class _CounterLabel(QLabel):
    """Semi-transparent pill matching the HTML .thumb-counter style."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setAttribute(Qt.WA_NoSystemBackground)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))   # subtle — just enough to separate text from image
        p.drawRoundedRect(QRectF(self.rect()), 8, 8)
        p.end()
        super().paintEvent(e)


# ── Star button ─────────────────────────────────────────────────────────────

class _StarBtn(QWidget):
    """
    Anti-aliased star drawn with QPainter. Filled gold when favourited,
    outlined gold when not.
    """
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self._fav   = False
        self._hover = False
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setCursor(Qt.PointingHandCursor)

    def setFav(self, fav):
        self._fav = fav
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        star = self._starPath(11, 11, 9, 4.5)
        if self._fav:
            color = QColor(0xff, 0xe0, 0x60) if self._hover else QColor(0xf0, 0xc0, 0x30)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawPath(star)
        else:
            color = QColor(0xf0, 0xc0, 0x30) if self._hover else QColor(200, 160, 0, 150)
            p.setPen(QPen(color, 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(star)

    @staticmethod
    def _starPath(cx, cy, outer, inner):
        path = QPainterPath()
        import math
        for i in range(5):
            angle_o = math.radians(-90 + i * 72)
            ox = cx + outer * math.cos(angle_o)
            oy = cy + outer * math.sin(angle_o)
            angle_i = math.radians(-90 + i * 72 + 36)
            ix = cx + inner * math.cos(angle_i)
            iy = cy + inner * math.sin(angle_i)
            if i == 0:
                path.moveTo(ox, oy)
            else:
                path.lineTo(ox, oy)
            path.lineTo(ix, iy)
        path.closeSubpath()
        return path

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


# ── View dot button ─────────────────────────────────────────────────────────

class _DotButton(QWidget):
    """
    Custom-painted sphere dot. Each render type gets a radial-gradient fill
    matching its visual purpose (matching HTML):
      material — blue sphere (shader ball)
      clay     — warm brown sphere (terracotta)
      wire     — green sphere (viewport green)
    """
    clicked = Signal()

    _GRADIENTS = {
        "material": ((123, 191, 238), (24, 95, 165)),   # blue sphere
        "clay":     ((180, 180, 175), (90, 90, 85)),     # gray gradient
    }

    _ACTIVE_BORDER = QColor(255, 255, 255, 190)
    _INACTIVE_BORDER = QColor(255, 255, 255, 60)
    _UNAVAIL_BORDER = QColor(180, 180, 180, 90)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)
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
        if not self._available:
            p.setPen(QPen(self._UNAVAIL_BORDER, 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r.adjusted(1, 1, -1, -1))
        else:
            er = r.adjusted(1.5, 1.5, -1.5, -1.5) if self._active else r.adjusted(1, 1, -1, -1)
            if self._view == "wire":
                # Flat black — no gradient
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
            pen_w = 2.0 if self._active else 1.0
            p.setPen(QPen(pen, pen_w))
            p.drawEllipse(er)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


# ── Arrow button (matches HTML .thumb-arrow-btn) ────────────────────────────

class _ArrowBtn(QWidget):
    """
    22×22 circle with a white chevron, exactly like the HTML mockup:
      background: rgba(0,0,0,0.42);   on hover → rgba(0,0,0,0.65)
      border-radius: 50%;  color: #fff;  font-size: 16px
    """
    clicked = Signal()

    def __init__(self, parent=None, mirror=False):
        super().__init__(parent)
        self._mirror = mirror
        self._hover  = False
        self.setFixedSize(44, 44)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_NoSystemBackground)

    def paintEvent(self, _e):
        from qtpy.QtGui import QRadialGradient
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = 22, 22
        # Shadow
        shadow = QRadialGradient(cx, cy + 1, 18)
        shadow.setColorAt(0.0, QColor(0, 0, 0, 35 if self._hover else 21))
        shadow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(shadow)
        p.drawEllipse(self.rect())
        # < or > drawn as a single path — clean join at the tip
        s = 11
        tip_x = cx - 4 if not self._mirror else cx + 4
        end_x = cx + 6 if not self._mirror else cx - 6
        path = QPainterPath()
        path.moveTo(end_x, cy - s)
        path.lineTo(tip_x, cy)
        path.lineTo(end_x, cy + s)
        pen = QPen(QColor(255, 255, 255, 180 if self._hover else 91), 3.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
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


# ── Thumbnail widget ────────────────────────────────────────────────────────

class _ThumbWidget(QWidget):
    """
    Thumbnail area. WA_NoSystemBackground prevents Qt from pre-filling
    the widget rect with a dark palette colour before paintEvent — that
    was the black-corner artifact root cause.  paintEvent clips the image
    (or placeholder) to the top-rounded path; the untouched corners then
    show through to the card's own BG_PRIMARY fill.
    """

    _RADIUS = 6

    def __init__(self, asset_data, parent=None):
        super().__init__(parent)
        self.asset_data = asset_data
        self._orig_px   = None
        self.setAttribute(Qt.WA_NoSystemBackground)

    def setImage(self, path):
        px = QPixmap(path)
        self._orig_px = px if not px.isNull() else None
        self.update()

    def clearImage(self):
        self._orig_px = None
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setPen(Qt.NoPen)

        # Clip to top-rounded, bottom-square path
        r = QRectF(self.rect())
        d = self._RADIUS * 2.0
        clip = QPainterPath()
        clip.moveTo(r.left() + self._RADIUS, r.top())
        clip.lineTo(r.right() - self._RADIUS, r.top())
        clip.arcTo(r.right() - d, r.top(), d, d, 90, -90)
        clip.lineTo(r.right(), r.bottom())
        clip.lineTo(r.left(), r.bottom())
        clip.arcTo(r.left(), r.top(), d, d, 180, -90)
        clip.closeSubpath()
        p.setClipPath(clip)

        if self._orig_px and not self._orig_px.isNull():
            scaled = self._orig_px.scaled(
                self.width(), self.height(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            x = (self.width()  - scaled.width())  // 2
            y = (self.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        else:
            idx = self.asset_data.get("id", 0) % len(THUMB_PALETTES)
            bg, fg = THUMB_PALETTES[idx]
            p.fillRect(self.rect(), QColor(bg))
            font = p.font()
            font.setPixelSize(22)
            p.setFont(font)
            p.setPen(QColor(fg))
            name = self.asset_data.get("name") or "?"
            p.drawText(r, Qt.AlignCenter, name[0].upper())
