import os
import logging

from qtpy.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QSlider, QScrollArea,
    QFrame, QSizePolicy, QApplication, QSplitter,
)
from qtpy.QtCore import Qt, QTimer, Signal, QSize, QEvent
from qtpy.QtGui import QFont, QIcon

from ui.styles import (
    BG_PRIMARY, BG_SECONDARY, BG_TERTIARY,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    BORDER_LIGHT, BORDER_MID, ACCENT, GREEN, GREEN_BG, GREEN_BORDER,
    get_stylesheet,
)
from ui.sidebar import SidebarWidget
from ui.asset_card import AssetCard
from ui.publish_dialog import PublishDialog
from ui.settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)

_SORT_OPTIONS = ["Sort: Recent", "Sort: Name A–Z", "Sort: Name Z–A", "Sort: Category"]
_CARD_WIDTH_DEFAULT = 235
_CARD_WIDTH_MIN     = 90
_CARD_WIDTH_MAX     = 425


class LibraryBrowser(QMainWindow):
    def __init__(self, core, plugin=None):
        super().__init__()
        self.core   = core
        self.plugin = plugin

        # -- Filter state -------------------------------------------------
        self._category   = None
        self._subcategory = None
        self._special    = ""      # "favorites" | "recent" | ""
        self._search     = ""
        self._sort       = "recent"
        self._card_width = _CARD_WIDTH_DEFAULT
        self._dcc_filter = None
        self._type_filter = None
        self._ft_filter  = None

        # -- DB -----------------------------------------------------------
        self._db = None
        self._username = self._getUsername()

        # -- Cards cache --------------------------------------------------
        self._all_cards = []   # list of AssetCard (all loaded)
        self._visible_cards = []

        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._applyFilters)

        self._build()
        self._applyStylesheet()

        self.core.parentWindow(self)
        self.setWindowTitle("Asset Library")
        self.resize(960, 660)
        self._centerOnScreen()

        QTimer.singleShot(0, self._loadFromDB)

    # ------------------------------------------------------------------
    # Build layout
    # ------------------------------------------------------------------

    def _build(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        central.setStyleSheet("background: %s;" % BG_PRIMARY)
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._buildToolbar())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.sidebar = SidebarWidget()
        self.sidebar.itemSelected.connect(self._onSidebarSelect)
        body_layout.addWidget(self.sidebar)

        body_layout.addWidget(self._buildContent(), 1)
        root.addWidget(body, 1)

        root.addWidget(self._buildStatusBar())

    def _buildToolbar(self):
        bar = QWidget()
        bar.setObjectName("toolbar")
        bar.setFixedHeight(46)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)

        title = QLabel("Asset Library")
        title.setStyleSheet(
            "font-size: 13px; font-weight: 500; color: %s; margin-right: 4px;"
            " background: transparent; white-space: nowrap;" % TEXT_PRIMARY
        )
        layout.addWidget(title)

        # Search
        search_wrap = QWidget()
        search_wrap.setStyleSheet("background: transparent;")
        sw_layout = QHBoxLayout(search_wrap)
        sw_layout.setContentsMargins(0, 0, 0, 0)
        sw_layout.setSpacing(0)
        self.search_icon = QLabel("🔍")
        self.search_icon.setStyleSheet(
            "font-size: 10px; color: %s; background: transparent; margin-left: 8px;" % TEXT_TERTIARY
        )
        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("Search assets…")
        self.search_input.textChanged.connect(self._onSearchChanged)
        sw_layout.addWidget(self.search_input, 1)
        layout.addWidget(self.search_input, 1)

        # Sort
        self.sort_combo = QComboBox()
        self.sort_combo.setFixedWidth(130)
        self.sort_combo.addItems(_SORT_OPTIONS)
        self.sort_combo.currentIndexChanged.connect(self._onSortChanged)
        layout.addWidget(self.sort_combo)

        # Size slider
        slider_wrap = QWidget()
        slider_wrap.setStyleSheet("background: transparent;")
        sl_layout = QHBoxLayout(slider_wrap)
        sl_layout.setContentsMargins(0, 0, 0, 0)
        sl_layout.setSpacing(4)
        sm = QLabel("⬛")
        sm.setStyleSheet("font-size: 8px; color: %s; background: transparent;" % TEXT_TERTIARY)
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setFixedWidth(80)
        self.size_slider.setRange(_CARD_WIDTH_MIN, _CARD_WIDTH_MAX)
        self.size_slider.setValue(_CARD_WIDTH_DEFAULT)
        self.size_slider.valueChanged.connect(self._onSliderChanged)
        lg = QLabel("⬛")
        lg.setStyleSheet("font-size: 13px; color: %s; background: transparent;" % TEXT_TERTIARY)
        sl_layout.addWidget(sm)
        sl_layout.addWidget(self.size_slider)
        sl_layout.addWidget(lg)
        layout.addWidget(slider_wrap)

        # Filters button
        self.filters_btn = QPushButton("Filters")
        self.filters_btn.setObjectName("filtersBtn")
        self.filters_btn.setCheckable(True)
        self.filters_btn.toggled.connect(self._onFiltersToggled)
        layout.addWidget(self.filters_btn)

        # Settings button
        settings_btn = QPushButton("⚙")
        settings_btn.setObjectName("settingsBtn")
        settings_btn.setFixedSize(30, 30)
        settings_btn.setToolTip("Set library root path")
        settings_btn.clicked.connect(self._onSettingsClicked)
        layout.addWidget(settings_btn)

        # Import button
        import_btn = QPushButton("＋  Import")
        import_btn.setObjectName("importBtn")
        import_btn.clicked.connect(self._onImportClicked)
        layout.addWidget(import_btn)

        return bar

    def _buildContent(self):
        content = QWidget()
        content.setStyleSheet("background: %s;" % BG_PRIMARY)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Filters panel (hidden by default)
        self.filters_panel = _FiltersPanel()
        self.filters_panel.setVisible(False)
        self.filters_panel.filtersChanged.connect(self._onFilterPanelChanged)
        layout.addWidget(self.filters_panel)

        # Grid scroll area
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setFrameShape(QFrame.NoFrame)
        self.grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_scroll.setStyleSheet(
            "QScrollArea { background: %s; border: none; }" % BG_PRIMARY
        )
        self.grid_scroll.installEventFilter(self)

        self.flow = _FlowWidget()
        self.flow.setStyleSheet("background: %s;" % BG_PRIMARY)
        self.grid_scroll.setWidget(self.flow)
        layout.addWidget(self.grid_scroll, 1)

        # Empty state
        empty_wrap = QWidget()
        empty_wrap.setStyleSheet("background: %s;" % BG_PRIMARY)
        empty_layout = QVBoxLayout(empty_wrap)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(10)

        self.empty_label = QLabel("No assets found.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(
            "font-size: 13px; color: %s; background: transparent;" % TEXT_TERTIARY
        )
        empty_layout.addWidget(self.empty_label)

        self.set_path_btn = QPushButton("Open Settings…")
        self.set_path_btn.setObjectName("importBtn")
        self.set_path_btn.setFixedWidth(160)
        self.set_path_btn.clicked.connect(self._onSettingsClicked)
        empty_layout.addWidget(self.set_path_btn, 0, Qt.AlignCenter)

        self.empty_wrap = empty_wrap
        self.empty_wrap.setVisible(False)
        layout.addWidget(self.empty_wrap)

        return content

    def _buildStatusBar(self):
        bar = QWidget()
        bar.setObjectName("statusBar")
        bar.setFixedHeight(28)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(12)

        self.status_label = QLabel("0 assets")
        self.status_label.setStyleSheet(
            "font-size: 11px; color: %s; font-family: 'IBM Plex Mono', monospace;"
            " background: transparent;" % TEXT_TERTIARY
        )
        layout.addWidget(self.status_label)
        layout.addStretch()

        hint = QLabel("Drag card into DCC viewport to import")
        hint.setStyleSheet(
            "font-size: 11px; color: %s; font-style: italic; background: transparent;" % TEXT_TERTIARY
        )
        layout.addWidget(hint)

        return bar

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _loadFromDB(self):
        db = self._getDB()
        if db is None:
            self._showEmpty("No library path set.\nClick  Set Library Path…  to configure.")
            return

        try:
            counts = db.get_category_counts(username=self._username)
            self.sidebar.setCounts(counts)
            self._loadCards(db)
        finally:
            db.close()

    def _loadCards(self, db):
        assets = db.get_assets()
        lib_root = self.plugin._getAssetLibRoot() if self.plugin else ""
        self._all_cards = []

        for a in assets:
            a["_lib_root"] = lib_root
            is_fav    = db.is_favorite(a["id"], self._username)
            versions  = db.get_versions(a["id"])
            filetypes = db.get_filetypes_for_asset(a["id"])
            card = AssetCard(a, is_fav, versions, filetypes)
            card.starToggled.connect(self._onStarToggled)
            card.assetImport.connect(self._onAssetImport)
            self._all_cards.append(card)

        self._applyFilters()

    def refreshAssets(self):
        self._loadFromDB()

    # ------------------------------------------------------------------
    # Filtering & display
    # ------------------------------------------------------------------

    def _applyFilters(self):
        filtered = self._all_cards

        # Category / subcategory / special
        if self._special == "favorites":
            filtered = [c for c in filtered if c._is_fav]
        elif self._special == "recent":
            # Recent is handled by load order from DB
            pass
        else:
            if self._category:
                filtered = [c for c in filtered
                            if c.asset_data.get("category") == self._category]
            if self._subcategory:
                filtered = [c for c in filtered
                            if c.asset_data.get("subcategory") == self._subcategory]

        # Search
        if self._search:
            q = self._search.lower()
            filtered = [c for c in filtered
                        if q in c.asset_data.get("name", "").lower()]

        # DCC filter
        if self._dcc_filter and self._dcc_filter != "All":
            filtered = [c for c in filtered
                        if c.asset_data.get("dcc", "Universal") in (self._dcc_filter, "Universal")]

        # Type filter
        if self._type_filter:
            filtered = [c for c in filtered
                        if c.asset_data.get("category") == self._type_filter]

        # Sort
        if self._sort == "name_asc":
            filtered = sorted(filtered, key=lambda c: c.asset_data.get("name", "").lower())
        elif self._sort == "name_desc":
            filtered = sorted(filtered, key=lambda c: c.asset_data.get("name", "").lower(), reverse=True)
        elif self._sort == "category":
            filtered = sorted(filtered, key=lambda c: (c.asset_data.get("category", ""), c.asset_data.get("name", "").lower()))

        self._visible_cards = filtered
        self.flow.setCards(filtered, self._card_width)

        count = len(filtered)
        total = len(self._all_cards)
        if count == total:
            self.status_label.setText("%d assets" % count)
        else:
            self.status_label.setText("%d of %d assets" % (count, total))

        if count == 0:
            self.set_path_btn.setVisible(False)
        self.empty_wrap.setVisible(count == 0)
        self.grid_scroll.setVisible(count > 0)

    def _showEmpty(self, msg):
        self.empty_label.setText(msg)
        self.set_path_btn.setVisible("Set Library Path" in msg)
        self.empty_wrap.setVisible(True)
        self.grid_scroll.setVisible(False)
        self.status_label.setText("0 assets")

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _onSidebarSelect(self, category, subcategory, special):
        self._category    = category or None
        self._subcategory = subcategory or None
        self._special     = special
        self._applyFilters()

    def _onSearchChanged(self, text):
        self._search = text.strip()
        self._search_timer.start()

    def _onSortChanged(self, idx):
        mapping = {0: "recent", 1: "name_asc", 2: "name_desc", 3: "category"}
        self._sort = mapping.get(idx, "recent")
        self._applyFilters()

    def _onSliderChanged(self, value):
        self._card_width = value
        self.flow.setCardWidth(value)

    def _onFiltersToggled(self, checked):
        self.filters_panel.setVisible(checked)

    def _onFilterPanelChanged(self, dcc, type_filter):
        self._dcc_filter  = dcc
        self._type_filter = type_filter
        self._applyFilters()

    def _onStarToggled(self, asset_id, is_fav):
        db = self._getDB()
        if db is None:
            return
        try:
            db.toggle_favorite(asset_id, self._username)
        finally:
            db.close()
        if self._special == "favorites":
            self._applyFilters()

    def _onAssetImport(self, asset_data):
        pass  # Phase 4 — DCC bridge

    def _onSettingsClicked(self):
        dlg = SettingsDialog(plugin=self.plugin, parent=self)
        dlg.saved.connect(self.refreshAssets)
        dlg.exec_()

    def _onImportClicked(self):
        dlg = PublishDialog(parent=self)
        dlg.assetSubmitted.connect(self._onAssetSubmitted)
        dlg.exec_()

    def _onAssetSubmitted(self, data):
        db = self._getDB()
        if db is None:
            return
        try:
            asset_id = db.add_asset(data)
            db.upsert_version(
                asset_id,
                data.get("version", "v001"),
                data.get("filepath", ""),
                data.get("filetype", ""),
            )
            if data.get("tags"):
                db.set_asset_tags(asset_id, data["tags"])
        finally:
            db.close()
        self.refreshAssets()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _getDB(self):
        if self.plugin:
            return self.plugin.getDB()
        return None

    def _getUsername(self):
        try:
            return self.core.username
        except Exception:
            return os.environ.get("USERNAME", "artist")

    def _centerOnScreen(self):
        try:
            screen = self.core.getQScreenGeo()
            if screen:
                self.move(
                    (screen.width()  - self.width())  // 2,
                    (screen.height() - self.height()) // 2,
                )
        except Exception:
            pass

    def _applyStylesheet(self):
        self.setStyleSheet(get_stylesheet())

    def eventFilter(self, obj, event):
        if obj is self.grid_scroll and event.type() == QEvent.Wheel:
            if event.modifiers() & Qt.ControlModifier:
                delta = event.angleDelta().y()
                step  = int(delta / 120 * 10)   # ~10 px per scroll notch
                new_w = max(_CARD_WIDTH_MIN, min(_CARD_WIDTH_MAX, self._card_width + step))
                self.size_slider.setValue(new_w)
                return True   # consume — don't scroll the grid
        return super().eventFilter(obj, event)


# ─────────────────────────────────────────────────────────────────────────────
# Flow grid widget
# ─────────────────────────────────────────────────────────────────────────────

class _FlowWidget(QWidget):
    """Manually positions AssetCards in a responsive grid."""

    _GAP     = 10
    _PADDING = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards      = []
        self._card_width = _CARD_WIDTH_DEFAULT

    def setCards(self, cards, card_width=None):
        # Reparent old cards away without deleting (they're cached in LibraryBrowser)
        for c in self._cards:
            c.setParent(None)
            c.hide()

        self._cards = cards
        if card_width is not None:
            self._card_width = card_width

        for c in cards:
            c.setParent(self)
            c.setCardWidth(self._card_width)
            c.show()

        self._relayout()

    def setCardWidth(self, w):
        self._card_width = w
        for c in self._cards:
            c.setCardWidth(w)
        self._relayout()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    def _relayout(self):
        if not self._cards:
            self.setMinimumHeight(80)
            return

        avail = max(1, self.width() - 2 * self._PADDING)
        cols  = max(1, (avail + self._GAP) // (self._card_width + self._GAP))
        card_h = self._cards[0].height()

        for i, card in enumerate(self._cards):
            row = i // cols
            col = i % cols
            x   = self._PADDING + col * (self._card_width + self._GAP)
            y   = self._PADDING + row * (card_h + self._GAP)
            card.move(x, y)

        rows    = (len(self._cards) + cols - 1) // cols
        total_h = self._PADDING + rows * (card_h + self._GAP) + self._PADDING
        self.setMinimumHeight(max(total_h, 80))


# ─────────────────────────────────────────────────────────────────────────────
# Filters panel (shown below toolbar when ⚙ Filters is toggled)
# ─────────────────────────────────────────────────────────────────────────────

class _FiltersPanel(QWidget):
    filtersChanged = Signal(str, str)   # (dcc, type_filter)

    _DCC_OPTIONS  = ["All DCCs", "Houdini exclusive", "Maya exclusive"]
    _TYPE_OPTIONS = ["All types", "Materials", "Models", "HDAs", "Textures", "Lighting"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("filtersPanel")
        self.setStyleSheet(
            "#filtersPanel { background: %s; border-bottom: 1px solid %s; }" % (BG_SECONDARY, BORDER_LIGHT)
        )
        self.setFixedHeight(52)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(20)

        def _section(label_text, options, signal_slot):
            col = QHBoxLayout()
            col.setSpacing(6)
            lbl = QLabel(label_text)
            lbl.setStyleSheet(
                "font-size: 10px; color: %s; font-family: 'IBM Plex Mono', monospace;"
                " background: transparent;" % TEXT_TERTIARY
            )
            combo = QComboBox()
            combo.setFixedWidth(150)
            combo.addItems(options)
            combo.currentTextChanged.connect(signal_slot)
            col.addWidget(lbl)
            col.addWidget(combo)
            return col, combo

        dcc_col, self.dcc_combo   = _section("DCC",  self._DCC_OPTIONS,  self._emit)
        type_col, self.type_combo = _section("TYPE", self._TYPE_OPTIONS, self._emit)

        layout.addLayout(dcc_col)
        layout.addLayout(type_col)
        layout.addStretch()

        reset_btn = QPushButton("Reset filters")
        reset_btn.clicked.connect(self._reset)
        layout.addWidget(reset_btn)

    def _emit(self, _=None):
        dcc  = self.dcc_combo.currentText()
        typ  = self.type_combo.currentText()
        dcc_val  = "" if dcc  == "All DCCs"   else dcc.split()[0]
        type_val = "" if typ  == "All types"  else typ
        self.filtersChanged.emit(dcc_val, type_val)

    def _reset(self):
        self.dcc_combo.setCurrentIndex(0)
        self.type_combo.setCurrentIndex(0)
