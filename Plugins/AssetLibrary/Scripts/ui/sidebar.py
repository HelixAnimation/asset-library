from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QSizePolicy,
)
from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QFont

from ui.styles import (
    BG_SECONDARY, BG_PRIMARY, BG_TERTIARY,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    BORDER_LIGHT, ACCENT, ACCENT_BG,
)

# Sidebar tree definition — (display_name, category_key, subcategory_key, special)
# special: "favorites" | "recent" | "" (normal category)
_TREE = [
    ("QUICK ACCESS", None, None, "_header"),
    ("★  Favourites",  None,   None, "favorites"),
    ("◷  Recent",      None,   None, "recent"),
    (None, None, None, "_divider"),

    ("LIBRARY", None, None, "_header"),
    ("All assets",   None,       None,    ""),
    (None, None, None, "_divider"),

    ("Models",       "Models",   None,       ""),
    ("  Anatomy",    "Models",   "Anatomy",  ""),
    ("  Organs",     "Models",   "Organs",   ""),
    ("  Props",      "Models",   "Props",    ""),
    ("  Environments","Models",  "Environments",""),
    (None, None, None, "_divider"),

    ("Materials",    "Materials", None,      ""),
    ("  Skin",       "Materials", "Skin",    ""),
    ("  Metal",      "Materials", "Metal",   ""),
    ("  Glass",      "Materials", "Glass",   ""),
    ("  Fabric",     "Materials", "Fabric",  ""),
    ("  Organic",    "Materials", "Organic", ""),
    ("  Fluid",      "Materials", "Fluid",   ""),
    ("  GPU Open",   "Materials", "GPU Open",""),
    (None, None, None, "_divider"),

    ("HDAs",         "HDAs",      None,      ""),
    ("  Rigging",    "HDAs",      "Rigging", ""),
    ("  FX",         "HDAs",      "FX",      ""),
    ("  Modeling",   "HDAs",      "Modeling",""),
    (None, None, None, "_divider"),

    ("Textures",     "Textures",  None,      ""),
    ("  Skin",       "Textures",  "Skin",    ""),
    ("  Metal",      "Textures",  "Metal",   ""),
    ("  Glass",      "Textures",  "Glass",   ""),
    ("  Fabric",     "Textures",  "Fabric",  ""),
    ("  Organic",    "Textures",  "Organic", ""),
    (None, None, None, "_divider"),

    ("Lighting",     "Lighting",  None,      ""),
    ("  HDRIs",      "Lighting",  "HDRIs",   ""),
    ("  Light rigs", "Lighting",  "Light rigs",""),
    ("  Poly Haven", "Lighting",  "Poly Haven",""),
]


class SidebarWidget(QWidget):
    """Left-hand category tree.  Emits itemSelected on click."""

    itemSelected = Signal(str, str, str)
    # args: (category_or_"", subcategory_or_"", special_or_"")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(185)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self._items    = []   # list of _SidebarItem
        self._active   = None
        self._counts   = {}   # {"All": 259, "Models": 114, ...}

        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 8, 0, 8)
        vbox.setSpacing(0)

        for (label, cat, sub, special) in _TREE:
            if special == "_header":
                vbox.addWidget(_SectionHeader(label))
            elif special == "_divider":
                vbox.addWidget(_Divider())
            else:
                item = _SidebarItem(label, cat, sub, special)
                item.clicked.connect(self._onItemClicked)
                self._items.append(item)
                vbox.addWidget(item)
                # Select "All assets" by default
                if cat is None and sub is None and special == "":
                    self._setActive(item)

        vbox.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

    # ------------------------------------------------------------------

    def setCounts(self, counts):
        """Update count badges.  counts = {"All": 259, "Models": 114, ...}"""
        self._counts = counts
        for item in self._items:
            key = _countKey(item.cat, item.sub)
            item.setCount(counts.get(key, 0))

    def _onItemClicked(self, item):
        self._setActive(item)
        self.itemSelected.emit(item.cat or "", item.sub or "", item.special or "")

    def _setActive(self, item):
        if self._active:
            self._active.setActive(False)
        self._active = item
        item.setActive(True)


def _countKey(cat, sub):
    if cat is None and sub is None:
        return "All"
    if sub:
        return "%s/%s" % (cat, sub)
    return cat or "All"


# ── Sub-widgets ───────────────────────────────────────────────────────────────

class _SectionHeader(QLabel):
    def __init__(self, text):
        super().__init__(text)
        self.setStyleSheet(
            "color: %s; font-size: 10px; font-weight: 500;"
            " font-family: 'IBM Plex Mono', monospace;"
            " letter-spacing: 1px; padding: 6px 14px 4px;"
            " background: transparent;" % TEXT_TERTIARY
        )


class _Divider(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet(
            "background-color: %s; border: none; margin: 6px 10px;" % BORDER_LIGHT
        )


class _SidebarItem(QWidget):
    clicked = Signal(object)   # passes self

    def __init__(self, label, cat, sub, special):
        super().__init__()
        self.setObjectName("sidebarItem")
        self.cat     = cat
        self.sub     = sub
        self.special = special
        self._active = False

        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

        layout = QHBoxLayout(self)
        is_child = label.startswith("  ")
        indent = 28 if is_child else 14
        layout.setContentsMargins(indent, 0, 10, 0)
        layout.setSpacing(6)

        # Dot indicator
        self.dot = QLabel("●")
        self.dot.setFixedWidth(8)
        dot_size = "9px" if is_child else "10px"
        self.dot.setStyleSheet(
            "color: %s; font-size: %s; background: transparent;" % (TEXT_TERTIARY, dot_size)
        )
        layout.addWidget(self.dot)

        # Label
        self.label = QLabel(label.strip())
        font_size = "11px" if is_child else "12px"
        self.label.setStyleSheet(
            "color: %s; font-size: %s; background: transparent;" % (TEXT_SECONDARY, font_size)
        )
        layout.addWidget(self.label, 1)

        # Count badge
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(
            "color: %s; font-size: 10px; font-family: 'IBM Plex Mono', monospace;"
            " background: transparent;" % TEXT_TERTIARY
        )
        layout.addWidget(self.count_label)

        self.setFixedHeight(28 if not is_child else 24)
        self._updateStyle()

    def setCount(self, n):
        self.count_label.setText(str(n) if n else "")

    def setActive(self, active):
        self._active = active
        self._updateStyle()

    def _updateStyle(self):
        if self._active:
            self.setStyleSheet(
                "#sidebarItem { background-color: %s; border-left: 2px solid %s; }" % (BG_PRIMARY, ACCENT)
            )
            self.label.setStyleSheet(
                "color: %s; font-weight: 500; font-size: 12px; background: transparent;" % ACCENT
            )
            self.dot.setStyleSheet(
                "color: %s; font-size: 10px; background: transparent;" % ACCENT
            )
        else:
            self.setStyleSheet(
                "#sidebarItem { background: transparent; border-left: 2px solid transparent; }"
            )
            is_child = self.label.text() != self.label.text().lstrip()
            font_size = "11px" if is_child else "12px"
            self.label.setStyleSheet(
                "color: %s; font-size: %s; background: transparent;" % (TEXT_SECONDARY, font_size)
            )
            self.dot.setStyleSheet(
                "color: %s; font-size: 10px; background: transparent;" % TEXT_TERTIARY
            )

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self)

    def enterEvent(self, e):
        if not self._active:
            self.setStyleSheet(
                "#sidebarItem { background-color: %s; border-left: 2px solid transparent; }" % BG_PRIMARY
            )
            self.label.setStyleSheet(
                "color: %s; font-size: 12px; background: transparent;" % TEXT_PRIMARY
            )

    def leaveEvent(self, e):
        if not self._active:
            self._updateStyle()
