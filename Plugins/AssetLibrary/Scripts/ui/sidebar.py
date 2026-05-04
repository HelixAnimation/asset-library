from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QSizePolicy,
)
from qtpy.QtCore import Qt, Signal, QVariantAnimation, QEasingCurve
from qtpy.QtGui import QFont, QColor

from ui.styles import (
    BG_SECONDARY, BG_PRIMARY, BG_SIDEBAR,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    BORDER_LIGHT, ACCENT,
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
    """Left-hand category tree.  Emits itemSelected."""

    itemSelected = Signal(str, str, str)
    # args: (category_or_"", subcategory_or_"", special_or_"")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(200)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setStyleSheet("#sidebar { background: %s; border-right: 1px solid %s; }" % (BG_SIDEBAR, BORDER_LIGHT))

        self._items        = []    # list of _SidebarItem
        self._active       = None
        self._counts       = {}    # {"All": 259, "Models": 114, ...}
        self._groups       = {}    # cat -> {"parent": widget, "children": [widgets]}
        self._expanded_cat = None  # currently expanded category (None = all collapsed)

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

        current_parent_cat = None

        for (label, cat, sub, special) in _TREE:
            if special == "_header":
                vbox.addWidget(_SectionHeader(label))
                continue
            if special == "_divider":
                continue

            is_child = label.startswith("  ")
            item = _SidebarItem(label, cat, sub, special)
            item.clicked.connect(self._onItemClicked)
            self._items.append(item)
            vbox.addWidget(item)

            if is_child:
                self._groups[current_parent_cat]["children"].append(item)
                item.setVisible(False)  # collapsed by default
            elif cat and not sub and not special:
                current_parent_cat = cat
                self._groups[cat] = {"parent": item, "children": []}

            # Select "All assets" by default
            if cat is None and sub is None and special == "":
                self._setActive(item)

        # Mark parents that have children as expandable
        for cat, group in self._groups.items():
            if group["children"]:
                group["parent"].setExpandable(True)

        vbox.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

    # ------------------------------------------------------------------

    def setCounts(self, counts):
        """Update count badges.  counts = {"All": 259, "Models": 114, "favorites": 7, ...}"""
        self._counts = counts
        for item in self._items:
            key = _countKey(item.cat, item.sub, item.special)
            item.setCount(counts.get(key, 0))

    def _onItemClicked(self, item):
        self._setActive(item)
        self.itemSelected.emit(item.cat or "", item.sub or "", item.special or "")

        if item._expandable:
            if self._expanded_cat == item.cat:
                self._collapseCategory(item.cat)
                self._expanded_cat = None
            else:
                if self._expanded_cat:
                    self._collapseCategory(self._expanded_cat)
                self._expandCategory(item.cat)
                self._expanded_cat = item.cat
        else:
            # Collapse only if clicking outside the expanded group
            if self._expanded_cat and item.cat != self._expanded_cat:
                self._collapseCategory(self._expanded_cat)
                self._expanded_cat = None

    def _expandCategory(self, cat):
        group = self._groups.get(cat)
        if group:
            group["parent"].setExpanded(True)
            for child in group["children"]:
                child.setVisible(True)

    def _collapseCategory(self, cat):
        group = self._groups.get(cat)
        if group:
            group["parent"].setExpanded(False)
            for child in group["children"]:
                child.setVisible(False)

    def _setActive(self, item):
        if self._active:
            self._active.setActive(False)
        self._active = item
        item.setActive(True)


def _countKey(cat, sub, special=""):
    if special:
        return special        # "favorites" or "recent"
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
        self.cat      = cat
        self.sub      = sub
        self.special  = special
        self._active  = False
        self._is_child = label.startswith("  ")
        self._expandable = False
        self._expanded   = False

        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        indent = 28 if self._is_child else 14
        layout.setContentsMargins(indent, 0, 10, 0)
        layout.setSpacing(6)

        # Dot / chevron indicator
        self.dot = QLabel("●")
        self.dot.setFixedWidth(8)
        dot_size = "9px" if self._is_child else "10px"
        self.dot.setStyleSheet(
            "color: %s; font-size: %s; background: transparent;" % (TEXT_TERTIARY, dot_size)
        )
        layout.addWidget(self.dot)

        # Label
        self.label = QLabel(label.strip())
        font_size = "11px" if self._is_child else "12px"
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

        self.setFixedHeight(28 if not self._is_child else 24)

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(300)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim.valueChanged.connect(self._onHoverColor)

        self._updateStyle()

    def setExpandable(self, expandable):
        self._expandable = expandable
        if expandable:
            self.dot.setText("▸")

    def setExpanded(self, expanded):
        self._expanded = expanded
        self.dot.setText("▾" if expanded else "▸")

    def setCount(self, n):
        self.count_label.setText(str(n) if n else "")

    def setActive(self, active):
        self._active = active
        self._hover_anim.stop()
        self._updateStyle()

    def _catBg(self):
        if self._is_child:
            return "#0f0f0f"
        return "transparent"

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
                "#sidebarItem { background-color: %s; border-left: 2px solid transparent; }" % self._catBg()
            )
            font_size = "11px" if self._is_child else "12px"
            self.label.setStyleSheet(
                "color: %s; font-size: %s; background: transparent;" % (TEXT_SECONDARY, font_size)
            )
            self.dot.setStyleSheet(
                "color: %s; font-size: 10px; background: transparent;" % TEXT_TERTIARY
            )

    def _onHoverColor(self, color):
        if not self._active:
            font_size = "11px" if self._is_child else "12px"
            self.label.setStyleSheet(
                "color: %s; font-size: %s; background: transparent;" % (color.name(), font_size)
            )

    def _animateTo(self, target_hex):
        self._hover_anim.stop()
        current = self._hover_anim.currentValue()
        start = current if isinstance(current, QColor) else QColor(TEXT_SECONDARY)
        self._hover_anim.setStartValue(start)
        self._hover_anim.setEndValue(QColor(target_hex))
        self._hover_anim.start()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self)

    def enterEvent(self, e):
        if not self._active:
            self._animateTo(TEXT_PRIMARY)

    def leaveEvent(self, e):
        if not self._active:
            self._animateTo(TEXT_SECONDARY)
