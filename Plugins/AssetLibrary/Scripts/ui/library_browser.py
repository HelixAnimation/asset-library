import os
import math
import shutil
import logging

from qtpy.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QScrollArea,
    QFrame, QSizePolicy, QApplication, QCheckBox,
    QGridLayout, QGraphicsDropShadowEffect, QMessageBox,
    QSplitter, QSplitterHandle,
)
from qtpy.QtCore import Qt, QTimer, Signal, QSize, QEvent
from qtpy.QtGui import QFont, QIcon, QColor

from ui.styles import (
    BG_PRIMARY, BG_SECONDARY, BG_TERTIARY,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    BORDER_LIGHT, BORDER_MID, ACCENT, ACCENT_BG, ACCENT_BORDER, ACCENT_TEXT,
    GREEN, GREEN_BG, GREEN_BORDER,
    get_stylesheet, _NoFocusDelegate,
)
from ui.sidebar import SidebarWidget
from ui.asset_card import AssetCard
from ui.publish_dialog import PublishDialog
from ui.version_dialog import VersionEditDialog
from ui.settings_dialog import SettingsDialog
from ui.inspector import InspectorPanel
from ui.tag_dropdown import TagDropdown as _TagDropdown

logger = logging.getLogger(__name__)

_SORT_OPTIONS = ["Sort: Recent", "Sort: Name A–Z", "Sort: Name Z–A", "Sort: Category"]
_SIDEBAR_WIDTH = 200


class _SplitterHandle(QSplitterHandle):
    """Splitter handle with an arrow button pinned to the top."""

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._btn = QPushButton("«", self)
        self._btn.setFixedSize(20, 52)
        self._btn.move(0, 0)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setToolTip("Collapse sidebar")
        self._btn.setStyleSheet(
            "QPushButton {"
            "  background: %s; border: none;"
            "  border-bottom-right-radius: 4px;"
            "  color: %s; font-size: 13px; padding: 0;"
            "}"
            "QPushButton:hover { background: %s; color: %s; }"
            % (BG_TERTIARY, TEXT_SECONDARY, ACCENT_BG, TEXT_PRIMARY)
        )
        self._btn.clicked.connect(self._onToggle)

    def paintEvent(self, event):
        # Fill handle with content-area colour — makes the divider line invisible
        from qtpy.QtGui import QPainter
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG_SECONDARY))
        p.end()

    def _onToggle(self):
        sp = self.splitter()
        sizes = sp.sizes()
        if sizes[0] > 0:
            sp._saved_sidebar_width = sizes[0]
            sp.setSizes([0, sizes[0] + sizes[1]])
            self._btn.setText("»")
            self._btn.setToolTip("Expand sidebar")
        else:
            w = getattr(sp, "_saved_sidebar_width", _SIDEBAR_WIDTH)
            total = sizes[0] + sizes[1]
            sp.setSizes([w, total - w])
            self._btn.setText("«")
            self._btn.setToolTip("Collapse sidebar")


class _ResizableSplitter(QSplitter):
    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._saved_sidebar_width = _SIDEBAR_WIDTH

    def createHandle(self):
        return _SplitterHandle(self.orientation(), self)
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
        self._filter_state = {}
        self._active_tags = []     # ordered list of active tag names

        # -- DB -----------------------------------------------------------
        self._db = None
        self._username = self._getUsername()

        # -- Cards cache --------------------------------------------------
        self._all_cards = []   # list of AssetCard (all loaded)
        self._visible_cards = []
        self._selected_card = None
        self._pending_inspector_asset = None
        self._pending_inspector_versions = []

        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._applyFilters)

        self._build()
        self._applyStylesheet()

        self.core.parentWindow(self)
        self.setWindowTitle("Asset Library")
        self.resize(1299, 731)
        self._centerOnScreen()

        QTimer.singleShot(0, self._loadFromDB)

    # ------------------------------------------------------------------
    # Build layout
    # ------------------------------------------------------------------

    def _build(self):
        # Splitter is the central widget — left = sidebar, right = main panel
        self._splitter = _ResizableSplitter(Qt.Horizontal)
        self._splitter.setHandleWidth(20)
        self._splitter.setCollapsible(0, True)
        self.setCentralWidget(self._splitter)

        # Left: full-height sidebar
        self.sidebar = SidebarWidget()
        self.sidebar.itemSelected.connect(self._onSidebarSelect)
        self._splitter.addWidget(self.sidebar)

        # Right: toolbar + filters + content + status
        right = QWidget()
        right.setAttribute(Qt.WA_StyledBackground, True)
        right.setStyleSheet("background: %s;" % BG_SECONDARY)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        right_layout.addWidget(self._buildToolbar())
        right_layout.addWidget(self._buildFilterBar())

        body = QWidget()
        body.setAttribute(Qt.WA_StyledBackground, True)
        body.setStyleSheet("background: %s;" % BG_PRIMARY)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self._buildContent(), 1)

        self.inspector = InspectorPanel()
        self.inspector.setFixedWidth(340)
        self.inspector.closeRequested.connect(self._hideInspector)
        self.inspector.tagClicked.connect(self._onTagAdded)
        self.inspector.editInfoRequested.connect(self._onInspectorEditInfo)
        self.inspector.addVersionRequested.connect(self._onInspectorAddVersion)
        self.inspector.editVersionRequested.connect(self._onEditVersion)
        self.inspector.versionPicked.connect(self._onInspectorVersionPicked)
        self.inspector.favToggleRequested.connect(self._onInspectorFavToggle)
        self.inspector.omitRequested.connect(self._onInspectorOmit)
        self.inspector.hide()

        _shadow = QGraphicsDropShadowEffect(self.inspector)
        _shadow.setBlurRadius(24)
        _shadow.setOffset(-6, 0)
        _shadow.setColor(QColor(0, 0, 0, 60))
        self.inspector.setGraphicsEffect(_shadow)

        body_layout.addWidget(self.inspector)

        right_layout.addWidget(body, 1)
        right_layout.addWidget(self._buildStatusBar())
        self._splitter.addWidget(right)

        # Initial sizes: sidebar at default width, right takes the rest
        self._splitter.setSizes([_SIDEBAR_WIDTH, 9999])

    def _buildToolbar(self):
        bar = QWidget()
        bar.setObjectName("toolbar")
        bar.setFixedHeight(58)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        # Search + tag input
        self.tag_input = _TagInput()
        self.tag_input.searchChanged.connect(self._onSearchChanged)
        self.tag_input.tagAdded.connect(self._onTagAdded)
        self.tag_input.tagRemoved.connect(self._onTagRemoved)
        layout.addWidget(self.tag_input, 1)

        # Sort
        self.sort_combo = QComboBox()
        self.sort_combo.setFixedWidth(130)
        self.sort_combo.view().setFocusPolicy(Qt.NoFocus)
        self.sort_combo.view().setItemDelegate(_NoFocusDelegate(self.sort_combo))
        self.sort_combo.addItems(_SORT_OPTIONS)
        self.sort_combo.currentIndexChanged.connect(self._onSortChanged)
        layout.addWidget(self.sort_combo)

        # Settings button
        settings_btn = QPushButton("⚙")
        settings_btn.setObjectName("settingsBtn")
        settings_btn.setFixedSize(30, 30)
        settings_btn.setToolTip("Set library root path")
        settings_btn.clicked.connect(self._onSettingsClicked)
        layout.addWidget(settings_btn)

        # Import button
        self.import_btn = QPushButton("＋  Import")
        self.import_btn.setObjectName("importBtn")
        self.import_btn.clicked.connect(self._onImportClicked)
        layout.addWidget(self.import_btn)

        return bar

    def _buildFilterBar(self):
        self.filter_bar = _FilterBar()
        self.filter_bar.filtersChanged.connect(self._onFilterPanelChanged)
        return self.filter_bar

    def _buildContent(self):
        content = QWidget()
        content.setAttribute(Qt.WA_StyledBackground, True)
        content.setStyleSheet("background: %s;" % BG_PRIMARY)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Grid scroll area
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setFrameShape(QFrame.NoFrame)
        self.grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_scroll.setStyleSheet(
            "QScrollArea { background: %s; border: none; }" % BG_PRIMARY
        )


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
        bar.setAttribute(Qt.WA_StyledBackground, True)
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
            self.tag_input.setTags(db.get_all_tags())
            self._loadCards(db)
        finally:
            db.close()

    def _loadCards(self, db):
        assets = db.get_assets()
        lib_root = self.plugin._getAssetLibRoot() if self.plugin else ""
        self._all_cards = []

        ids = [a["id"] for a in assets]
        tags_map = db.batch_get_asset_tags(ids)
        fav_ids  = db.batch_get_favorites(ids, self._username)
        vers_map = db.batch_get_versions(ids)
        ft_map   = db.batch_get_filetypes(ids)

        for a in assets:
            a["_lib_root"] = lib_root
            a["tags"] = tags_map.get(a["id"], [])
            card = AssetCard(
                a,
                a["id"] in fav_ids,
                vers_map.get(a["id"], []),
                ft_map.get(a["id"], []),
            )
            card.starToggled.connect(self._onStarToggled)
            card.assetImport.connect(self._onAssetImport)
            card.assetClicked.connect(self._onCardClicked)
            card.versionChanged.connect(self._onCardVersionChanged)
            card.editRequested.connect(self._onEditAsset)
            card.editVersionRequested.connect(self._onEditVersion)
            card.addVersionRequested.connect(self._onAddVersion)
            card.omitRequested.connect(self._onOmitAsset)
            card.loadInHoudiniRequested.connect(self._onLoadInHoudini)
            card.refreshRequested.connect(self._onRefreshAsset)
            self._all_cards.append(card)

        names = [c.asset_data.get("name", "") for c in self._all_cards]
        self.tag_input.setAssets(names)
        authors = sorted({c.asset_data.get("author", "") for c in self._all_cards if c.asset_data.get("author", "")})
        self.filter_bar.setAuthors(authors)
        projects = sorted({c.asset_data.get("project", "") for c in self._all_cards if c.asset_data.get("project", "")})
        self.filter_bar.setProjects(projects)
        self._applyFilters()

    def refreshAssets(self):
        self._loadFromDB()

    def _onRefreshAsset(self, asset_id):
        """Re-query the DB for a single asset and update its card in-place."""
        if asset_id < 0:
            return
        db = self._getDB()
        if db is None:
            return
        try:
            asset = db.get_asset(asset_id)
            if not asset:
                return
            lib_root = self.plugin._getAssetLibRoot() if self.plugin else ""
            asset["_lib_root"] = lib_root
            asset["tags"] = db.get_asset_tags(asset_id)
            fav_ids  = db.batch_get_favorites([asset_id], self._username)
            versions = db.batch_get_versions([asset_id]).get(asset_id, [])
            filetypes = db.batch_get_filetypes([asset_id]).get(asset_id, [])
        finally:
            db.close()

        for card in self._all_cards:
            if card.asset_data.get("id") == asset_id:
                card.refreshData(asset, asset_id in fav_ids, versions, filetypes)
                if self.inspector.isVisible() and self._selected_card is card:
                    self.inspector.setAsset(asset, versions)
                break

    # ------------------------------------------------------------------
    # Filtering & display
    # ------------------------------------------------------------------

    def _applyFilters(self):
        filtered = self._all_cards

        # Category / subcategory / special
        if self._special == "favorites":
            filtered = [c for c in filtered if c._is_fav]
        elif self._special == "recent":
            recent_ids = set(self._getRecentIds())
            filtered = [c for c in filtered if c.asset_data.get("id") in recent_ids]
            # Order by most recently used
            order = {aid: i for i, aid in enumerate(recent_ids)}
            filtered.sort(key=lambda c: order.get(c.asset_data.get("id"), 999999))
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

        # Toolbar filters
        fs = self._filter_state or {}
        dcc_values = fs.get("dcc") or set()
        if dcc_values:
            filtered = [c for c in filtered
                        if c.asset_data.get("dcc", "Universal") in dcc_values
                        or c.asset_data.get("dcc", "Universal") == "Universal"]

        type_values = fs.get("type") or set()
        if type_values:
            filtered = [c for c in filtered
                        if c.asset_data.get("category") in type_values]

        filetype_values = fs.get("filetype") or set()
        if filetype_values:
            filtered = [c for c in filtered
                        if (c._selected_filetype or c.asset_data.get("filetype", "")) in filetype_values]

        includes_values = fs.get("includes") or set()
        if includes_values:
            include_fields = {
                "Rig": "has_rig",
                "Textures": "has_textures",
                "Materials": "has_materials",
            }
            filtered = [
                c for c in filtered
                if all(int(c.asset_data.get(include_fields[name], 0) or 0) for name in includes_values)
            ]

        author_values = fs.get("author") or set()
        if author_values:
            filtered = [c for c in filtered
                        if c.asset_data.get("author", "") in author_values]

        polycount_values = fs.get("polycount") or set()
        if polycount_values:
            _PC_RANGES = {
                "< 10k":        (0,       10_000),
                "10k – 50k":    (10_000,  50_000),
                "50k – 200k":   (50_000,  200_000),
                "200k – 500k":  (200_000, 500_000),
                "500k+":        (500_000, None),
            }
            def _pc_match(asset_data, ranges):
                pc = asset_data.get("polycount")
                if pc is None:
                    return False
                pc = int(pc)
                for label in ranges:
                    lo, hi = _PC_RANGES.get(label, (None, None))
                    if lo is None:
                        continue
                    if hi is None and pc >= lo:
                        return True
                    if hi is not None and lo <= pc < hi:
                        return True
                return False
            filtered = [c for c in filtered if _pc_match(c.asset_data, polycount_values)]

        project_values = fs.get("project") or set()
        if project_values:
            filtered = [c for c in filtered
                        if c.asset_data.get("project", "") in project_values]

        # Tags (AND logic — card must have ALL active tags)
        if self._active_tags:
            active_set = set(self._active_tags)
            filtered = [c for c in filtered
                        if active_set.issubset(set(c.asset_data.get("tags", [])))]

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
        elif self._active_tags:
            tag_str = " + ".join(self._active_tags)
            self.status_label.setText("%d assets · filtered by %s" % (count, tag_str))
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

    def _onTagAdded(self, tag):
        if tag not in self._active_tags:
            self._active_tags.append(tag)
        self.tag_input._addTag(tag)
        self._applyFilters()

    def _onTagRemoved(self, tag):
        if tag in self._active_tags:
            self._active_tags.remove(tag)
        self._applyFilters()

    def _onSortChanged(self, idx):
        mapping = {0: "recent", 1: "name_asc", 2: "name_desc", 3: "category"}
        self._sort = mapping.get(idx, "recent")
        self._applyFilters()

    def _onFilterPanelChanged(self, state):
        self._filter_state = state
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
        asset_id = asset_data.get("id")
        if asset_id is None:
            return
        db = self._getDB()
        if db is None:
            return
        try:
            db.add_recent(asset_id, self._username)
            counts = db.get_category_counts(username=self._username)
        finally:
            db.close()
        self.sidebar.setCounts(counts)
        if self._special == "recent":
            self._applyFilters()

    def _onLoadInHoudini(self, load_data, mode):
        try:
            import hou
        except ImportError:
            from qtpy.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Not in Houdini",
                                "This action requires running inside Houdini.")
            return

        filepath = load_data.get("filepath", "")
        if not filepath or not os.path.isfile(filepath):
            from qtpy.QtWidgets import QMessageBox
            QMessageBox.warning(self, "File Not Found",
                                "Asset file not found:\n%s" % filepath)
            return

        try:
            from core.dcc_bridge import HoudiniBridge
            lib_root = self.plugin._getAssetLibRoot() if self.plugin else ""
            db = self._getDB()
            db_path = db.db_path if db else ""
            if db:
                db.close()
            bridge = HoudiniBridge(lib_root, db_path)
            geo = bridge.import_asset(
                filepath    = filepath,
                version_dir = load_data.get("version_dir", ""),
                asset_name  = load_data.get("name", "asset"),
                mode        = mode,
            )
            hou.ui.displayMessage(
                "Loaded %s at %s" % (load_data.get("name", ""), geo.path()),
                severity=hou.severityType.Message,
            )
        except Exception as exc:
            from qtpy.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Load Failed", str(exc))

    def _onCardClicked(self, asset_data):
        try:
            # Deselect previous
            if self._selected_card:
                self._selected_card.setSelected(False)
            self._selected_card = None

            # Find and select new card
            for c in self._visible_cards:
                if c.asset_data.get("id") == asset_data.get("id"):
                    c.setSelected(True)
                    self._selected_card = c
                    break

            # Opening a hidden splitter child and resizing the Prism-hosted
            # window during mousePressEvent can crash some Qt hosts. Defer it.
            self._pending_inspector_asset = dict(asset_data or {})
            if self._selected_card:
                self._pending_inspector_asset["_is_fav"] = self._selected_card._is_fav
            self._pending_inspector_versions = list(self._selected_card._versions) if self._selected_card else []
            QTimer.singleShot(0, self._openPendingInspector)
        except Exception:
            logger.exception(
                "Failed to open inspector for asset id=%r name=%r",
                asset_data.get("id") if isinstance(asset_data, dict) else None,
                asset_data.get("name") if isinstance(asset_data, dict) else None,
            )

    def _openPendingInspector(self):
        asset_data = self._pending_inspector_asset
        versions = self._pending_inspector_versions
        self._pending_inspector_asset = None
        self._pending_inspector_versions = []
        if not asset_data:
            return
        try:
            self.inspector.setAsset(asset_data, versions)
            self.inspector.show()
        except Exception:
            logger.exception(
                "Failed to populate inspector for asset id=%r name=%r",
                asset_data.get("id"),
                asset_data.get("name"),
            )

    def _onCardVersionChanged(self, asset_id, version):
        """Sync the inspector's version combo when a card's version changes."""
        if (self.inspector.isVisible()
                and self._selected_card
                and self._selected_card.asset_data.get("id") == asset_id):
            self.inspector.setVersion(version)

    def _onInspectorVersionPicked(self, version):
        if self._selected_card:
            self._selected_card._onVersionPicked(version)
        self.inspector.setVersion(version)

    def _onInspectorFavToggle(self):
        if not self._selected_card:
            return
        self._selected_card._onStarClicked()
        self.inspector.setFav(self._selected_card._is_fav)

    def _onInspectorEditInfo(self):
        if self._selected_card:
            self._onEditAsset(self._selected_card.asset_data)

    def _onInspectorAddVersion(self):
        if self._selected_card:
            self._onAddVersion(self._selected_card.asset_data)

    def _onInspectorOmit(self):
        if self._selected_card:
            self._onOmitAsset(self._selected_card.asset_data)

    def _hideInspector(self):
        self.inspector.hide()
        if self._selected_card:
            self._selected_card.setSelected(False)
            self._selected_card = None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.inspector.isVisible():
            self._hideInspector()
        else:
            super().keyPressEvent(e)

    def _onSettingsClicked(self):
        dlg = SettingsDialog(plugin=self.plugin, parent=self, card_width=self._card_width)
        dlg.saved.connect(self.refreshAssets)
        dlg.cardWidthChanged.connect(self._onCardWidthChanged)
        dlg.exec_()

    def _onCardWidthChanged(self, w):
        self._card_width = w
        self.flow.setCardWidth(w)

    def _onImportClicked(self):
        db_tags, db_projects = [], []
        db = self._getDB()
        if db:
            try:
                db_tags = db.get_all_tags()
                rows = db.conn.execute(
                    "SELECT DISTINCT project FROM assets"
                    " WHERE project IS NOT NULL AND project != '' ORDER BY project"
                ).fetchall()
                db_projects = [r[0] for r in rows]
            finally:
                db.close()
        dlg = PublishDialog(
            plugin=self.plugin,
            db_tags=db_tags,
            db_projects=db_projects,
            disk_projects=self._getDiskProjects(),
            active_project=self._getActivePrismProject(),
            parent=self,
        )
        dlg.assetSubmitted.connect(self._onAssetSubmitted)
        dlg.exec_()

    def _getActivePrismProject(self):
        try:
            return self.plugin.core.getConfig("project", "name") or ""
        except Exception:
            return ""

    def _getDiskProjects(self):
        import json
        scan_path = "X:\\"
        if self.plugin:
            try:
                p = self.plugin.core.getConfig("globals", "localProjectRootPath") or ""
                if p and os.path.isdir(p):
                    scan_path = p
            except Exception:
                pass
        if not os.path.isdir(scan_path):
            return []
        try:
            folders = sorted([
                f for f in os.listdir(scan_path)
                if os.path.isdir(os.path.join(scan_path, f)) and not f.startswith(".")
            ])
        except Exception:
            return []
        result = []
        for folder in folders:
            pipeline_json = os.path.join(scan_path, folder, "00_Pipeline", "pipeline.json")
            if not os.path.isfile(pipeline_json):
                continue
            name = folder
            try:
                with open(pipeline_json, "r", encoding="utf-8") as jf:
                    data = json.load(jf)
                for key in ("project_name", "projectName", "name"):
                    val = data.get(key) or (data.get("globals") or {}).get(key)
                    if val:
                        name = str(val)
                        break
            except Exception:
                pass
            result.append(name)
        return result

    def _onAssetSubmitted(self, data):
        if not self.plugin:
            return
        library_root = self.plugin._getAssetLibRoot()
        if not library_root:
            QMessageBox.warning(self, "Import", "Library root is not configured.")
            return

        db = self._getDB()
        if db is None:
            return
        db_path = db.db_path
        db.close()

        self.import_btn.setEnabled(False)
        self.status_label.setText("Importing…")

        from core.importer import ImportThread
        thumbnails = data.pop("_thumbnails", {})
        texture_files = data.pop("_texture_files", [])
        self._import_thread = ImportThread(library_root, db_path, data, thumbnails, texture_files)
        self._import_thread.finished.connect(self._onImportFinished)
        self._import_thread.start()

    def _onImportFinished(self, result):
        self.import_btn.setEnabled(True)
        if result["success"]:
            self.status_label.setText("Imported successfully")
            self.refreshAssets()
        else:
            self.status_label.setText("Import failed")
            QMessageBox.warning(
                self, "Import Failed",
                result.get("error", "Unknown error"),
            )

    # ------------------------------------------------------------------
    # Edit asset
    # ------------------------------------------------------------------

    def _onEditAsset(self, asset_data):
        asset_id = asset_data.get("id")
        if not asset_id:
            return
        db = self._getDB()
        if db is None:
            return
        try:
            full = db.get_asset(asset_id)
            if not full:
                return
            tags = db.get_asset_tags(asset_id)
            db_tags = db.get_all_tags()
            rows = db.conn.execute(
                "SELECT DISTINCT project FROM assets"
                " WHERE project IS NOT NULL AND project != '' ORDER BY project"
            ).fetchall()
            db_projects = [r[0] for r in rows]
        finally:
            db.close()

        prefill = dict(full)
        prefill["tags"] = tags
        prefill["_edit_id"] = asset_id
        dlg = PublishDialog(
            prefill=prefill,
            plugin=self.plugin,
            db_tags=db_tags,
            db_projects=db_projects,
            disk_projects=self._getDiskProjects(),
            active_project=self._getActivePrismProject(),
            parent=self,
        )
        dlg.assetSubmitted.connect(self._onAssetEdited)
        dlg.exec_()

    def _onAssetEdited(self, data):
        asset_id = data.pop("_edit_id", None)
        if not asset_id:
            return
        db = self._getDB()
        if db is None:
            return
        tags = data.pop("tags", None)

        try:
            current = db.get_asset(asset_id)
            if not current:
                return

            old_name = current.get("name", "")
            old_cat  = current.get("category", "")
            old_sub  = current.get("subcategory") or ""
            new_name = data.get("name", old_name)
            new_cat  = data.get("category", old_cat)
            new_sub  = data.get("subcategory") or ""

            lib_root = self.plugin._getAssetLibRoot() if self.plugin else ""

            if lib_root and (new_name != old_name or new_cat != old_cat or new_sub != old_sub):
                old_parts  = [old_cat] + ([old_sub] if old_sub else []) + [old_name]
                new_parts  = [new_cat] + ([new_sub] if new_sub else []) + [new_name]
                old_folder = os.path.join(lib_root, *old_parts)
                new_folder = os.path.join(lib_root, *new_parts)
                old_prism  = "/".join(old_parts)
                new_prism  = "/".join(new_parts)

                if old_folder != new_folder and os.path.isdir(old_folder):
                    if os.path.exists(new_folder):
                        QMessageBox.warning(
                            self, "Rename Failed",
                            "A folder already exists at:\n%s" % new_folder,
                        )
                        return
                    os.makedirs(os.path.dirname(new_folder), exist_ok=True)
                    shutil.move(old_folder, new_folder)

                def _repath(p):
                    if not p:
                        return p
                    fwd = p.replace("\\", "/")
                    if fwd.startswith(old_prism + "/"):
                        return new_prism + fwd[len(old_prism):]
                    if fwd == old_prism:
                        return new_prism
                    return p

                data["filepath"]       = _repath(current.get("filepath", ""))
                data["thumbnail_path"] = _repath(current.get("thumbnail_path", ""))
                data["prism_path"]     = new_prism

                for v in db.get_versions(asset_id):
                    db.conn.execute(
                        "UPDATE versions SET filepath=?, prism_path=?, thumbnail_path=? WHERE id=?",
                        (_repath(v.get("filepath", "")), new_prism,
                         _repath(v.get("thumbnail_path", "")), v["id"]),
                    )
                db.conn.commit()

            db.update_asset(asset_id, data)
            if tags is not None:
                db.set_asset_tags(asset_id, tags)
        finally:
            db.close()
        self.refreshAssets()

    # ------------------------------------------------------------------
    # Edit version
    # ------------------------------------------------------------------

    def _onEditVersion(self, version_data):
        if not version_data or not version_data.get("id"):
            return
        lib_root = self.plugin._getAssetLibRoot() if self.plugin else ""
        dlg = VersionEditDialog(version_data=version_data, lib_root=lib_root, parent=self)
        dlg.versionSubmitted.connect(self._onVersionEdited)
        dlg.exec_()

    def _onVersionEdited(self, data):
        version_id = data.pop("version_id", None)
        version_dir = data.pop("_version_dir", "")
        if not version_id:
            return

        # File operations
        if version_dir and os.path.isdir(version_dir):
            self._applyFileOps(version_dir, data)

        db = self._getDB()
        if db is None:
            return
        try:
            db.update_version(version_id, data)

            # Update thumbnail_path if thumbs changed
            current_thumbs = data.pop("_current_thumbs", None)
            if current_thumbs is not None:
                thumbs_rel_path = self._thumbsRelPath(version_dir, current_thumbs)
                db.update_version(version_id, {"thumbnail_path": thumbs_rel_path})

            # Update has_textures flag if textures changed
            current_textures = data.pop("_current_textures", None)
            if current_textures is not None:
                has_tex = 1 if current_textures else 0
                db.update_version(version_id, {"has_textures": has_tex})

            # Sync version-level metadata to the parent asset
            version = db.get_version_by_id(version_id)
            if version:
                thumbs = current_thumbs if current_thumbs is not None else []
                thumbs_rel = self._thumbsRelPath(version_dir, thumbs) if version_dir else ""
                db.conn.execute(
                    "UPDATE assets SET renderer=?, dcc=?, has_rig=?, "
                    "has_textures=?, has_materials=?, thumbnail_path=? "
                    "WHERE id=?",
                    (version.get("renderer", "Any"),
                     version.get("dcc", "Universal"),
                     int(version.get("has_rig", 0)),
                     int(data.get("has_textures", version.get("has_textures", 0))),
                     int(version.get("has_materials", 0)),
                     thumbs_rel or "",
                     version["asset_id"]),
                )
                db.conn.commit()
        finally:
            db.close()
        self.refreshAssets()

    def _applyFileOps(self, version_dir, data):
        """Copy added files, delete removed files."""
        # Files
        for src in data.get("_files_to_add", []):
            try:
                shutil.copy2(src, os.path.join(version_dir, os.path.basename(src)))
            except OSError:
                pass
        for name in data.get("_files_to_remove", []):
            try:
                os.remove(os.path.join(version_dir, name))
            except OSError:
                pass

        # Thumbnails
        thumbs_dir = os.path.join(version_dir, "thumbs")
        if data.get("_thumbs_to_add"):
            os.makedirs(thumbs_dir, exist_ok=True)
        for src in data.get("_thumbs_to_add", []):
            try:
                shutil.copy2(src, os.path.join(thumbs_dir, os.path.basename(src)))
            except OSError:
                pass
        for name in data.get("_thumbs_to_remove", []):
            try:
                os.remove(os.path.join(thumbs_dir, name))
            except OSError:
                pass
        thumbs_by_view = data.get("_current_thumbs_by_view")
        if thumbs_by_view:
            self._applyThumbOrder(thumbs_dir, thumbs_by_view)

        # Textures
        textures_dir = os.path.join(version_dir, "textures")
        if data.get("_textures_to_add"):
            os.makedirs(textures_dir, exist_ok=True)
        for src in data.get("_textures_to_add", []):
            try:
                shutil.copy2(src, os.path.join(textures_dir, os.path.basename(src)))
            except OSError:
                pass
        for name in data.get("_textures_to_remove", []):
            try:
                os.remove(os.path.join(textures_dir, name))
            except OSError:
                pass

    def _applyThumbOrder(self, thumbs_dir, thumbs_by_view):
        """Rename thumb files to match drag-reorder. Uses two-pass rename to avoid conflicts."""
        if not os.path.isdir(thumbs_dir):
            return
        for view, names in thumbs_by_view.items():
            ordered = [n for n in names if os.path.isfile(os.path.join(thumbs_dir, n))]
            if not ordered:
                continue
            # Pass 1: rename to temp names
            temp_to_final = {}
            for i, name in enumerate(ordered):
                ext = os.path.splitext(name)[1]
                final = "%s_%03d%s" % (view, i + 1, ext)
                if name == final:
                    continue
                temp = "__tmp_%d_%s%s" % (i, view, ext)
                try:
                    os.rename(os.path.join(thumbs_dir, name), os.path.join(thumbs_dir, temp))
                    temp_to_final[temp] = final
                except OSError:
                    pass
            # Pass 2: rename temps to final names
            for temp, final in temp_to_final.items():
                try:
                    os.rename(os.path.join(thumbs_dir, temp), os.path.join(thumbs_dir, final))
                except OSError:
                    pass

    def _thumbsRelPath(self, version_dir, thumb_names):
        """Return relative thumbs dir path from lib_root, or empty if no thumbs."""
        if not thumb_names or not version_dir:
            return ""
        thumbs_dir = os.path.join(version_dir, "thumbs")
        lib_root = self.plugin._getAssetLibRoot() if self.plugin else ""
        if not lib_root:
            return ""
        try:
            return os.path.relpath(thumbs_dir, lib_root).replace("\\", "/")
        except ValueError:
            return ""

    # ------------------------------------------------------------------
    # Add version — opens import dialog pre-filled with asset metadata
    # ------------------------------------------------------------------

    def _onAddVersion(self, asset_data):
        asset_id = asset_data.get("id")
        if not asset_id:
            return
        db = self._getDB()
        if db is None:
            return
        try:
            full = db.get_asset(asset_id)
            if not full:
                return
            db_tags = db.get_all_tags()
            rows = db.conn.execute(
                "SELECT DISTINCT project FROM assets"
                " WHERE project IS NOT NULL AND project != '' ORDER BY project"
            ).fetchall()
            db_projects = [r[0] for r in rows]
        finally:
            db.close()

        # Pre-fill with asset metadata so the user only adds files
        prefill = {k: v for k, v in full.items()
                   if k in ("name", "category", "subcategory", "project")}
        prefill["_add_version_asset_id"] = asset_id
        dlg = PublishDialog(
            prefill=prefill,
            plugin=self.plugin,
            db_tags=db_tags,
            db_projects=db_projects,
            disk_projects=self._getDiskProjects(),
            active_project=self._getActivePrismProject(),
            parent=self,
        )
        dlg.assetSubmitted.connect(self._onAssetSubmitted)
        dlg.exec_()

    def _onOmitAsset(self, asset_data):
        asset_id = asset_data.get("id")
        name = asset_data.get("name", "this asset")
        if not asset_id:
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Omit asset")
        msg.setText("Omit <b>%s</b> from the library?" % name)
        msg.setInformativeText("The asset will be hidden from the library. Files on disk will not be affected. You can restore it later by clearing the omitted flag in the database.")
        msg.setIcon(QMessageBox.Warning)
        msg.setStandardButtons(QMessageBox.Cancel)
        omit_btn = msg.addButton("Omit", QMessageBox.DestructiveRole)
        msg.setDefaultButton(QMessageBox.Cancel)
        msg.exec_()

        if msg.clickedButton() is not omit_btn:
            return

        db = self._getDB()
        if db is None:
            return
        try:
            db.omit_asset(asset_id)
        finally:
            db.close()

        if self._selected_card and self._selected_card.asset_data.get("id") == asset_id:
            self._hideInspector()
            self._selected_card = None
        self.refreshAssets()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _getDB(self):
        if self.plugin:
            return self.plugin.getDB()
        return None

    def _getRecentIds(self):
        db = self._getDB()
        if db is None:
            return []
        try:
            recents = db.get_recents(self._username)
            return [r["id"] for r in recents]
        finally:
            db.close()

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

        avail    = max(1, self.width() - 2 * self._PADDING)
        # ceil: snap to a new column the moment cards would exceed _card_width
        fit_cols = max(1, math.ceil((avail + self._GAP) / (self._card_width + self._GAP)))

        if len(self._cards) < fit_cols:
            # Partial row — don't stretch, just place at set width
            cols     = len(self._cards)
            actual_w = self._card_width
        else:
            cols     = fit_cols
            actual_w = max(_CARD_WIDTH_MIN, int((avail - (cols - 1) * self._GAP) / cols))

        for i, card in enumerate(self._cards):
            card.setCardWidth(actual_w)

        card_h = self._cards[0].height()

        for i, card in enumerate(self._cards):
            row = i // cols
            col = i % cols
            x   = self._PADDING + col * (actual_w + self._GAP)
            y   = self._PADDING + row * (card_h + self._GAP)
            card.move(x, y)

        rows    = (len(self._cards) + cols - 1) // cols
        total_h = self._PADDING + rows * (card_h + self._GAP) + self._PADDING
        self.setMinimumHeight(max(total_h, 80))


# ─────────────────────────────────────────────────────────────────────────────
# Tag input widget (search bar with inline tag pills + autocomplete)
# ─────────────────────────────────────────────────────────────────────────────

class _TagInput(QWidget):
    """Search bar with inline tag pills and autocomplete dropdown.

    - Type to see tag + asset name suggestions from the dropdown
    - Press Enter or click a tag suggestion to add a tag pill (filters grid)
    - Click an asset name suggestion or press Enter with no tag match → text search
    - Each pill has a × button to remove it; Backspace on empty removes last pill
    """

    searchChanged = Signal(str)   # emitted on explicit text search (Enter / name click), not per-keystroke
    tagAdded = Signal(str)
    tagRemoved = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_tags = []
        self._all_asset_names = []
        self._active_tags = []
        self._pills = {}

        self.setObjectName("searchInput")
        self.setFixedHeight(30)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.IBeamCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 1, 4, 1)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignVCenter)

        # Search icon
        icon = QLabel("🔍")
        icon.setStyleSheet(
            "font-size: 11px; color: %s; background: transparent; border: none;" % TEXT_TERTIARY
        )
        icon.setFixedWidth(16)
        layout.addWidget(icon)

        # Scroll area for pills + inline text input
        self._pill_area = QWidget()
        self._pill_area.setStyleSheet("background: transparent;")
        self._pill_layout = QHBoxLayout(self._pill_area)
        self._pill_layout.setContentsMargins(0, 0, 0, 0)
        self._pill_layout.setSpacing(3)
        self._pill_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Inline text input (shares space with pills)
        self._edit = QLineEdit()
        self._edit.setFrame(False)
        self._edit.setStyleSheet(
            "QLineEdit {"
            "  background: transparent; border: none; outline: none; padding: 0 2px;"
            "  color: %s; font-size: 12px;"
            "  font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif;"
            "}"
            "QLineEdit:focus { border: none; outline: none; }"
        )
        self._edit.setPlaceholderText("Search assets…")
        self._edit.setMinimumWidth(80)
        self._edit.textChanged.connect(self._onTextChanged)
        self._edit.keyPressEvent = self._onEditKeyPress
        self._edit.installEventFilter(self)
        self._pill_layout.addWidget(self._edit, 1)

        layout.addWidget(self._pill_area, 1)

        # Autocomplete dropdown
        self._popup = _TagDropdown(self)
        self._popup.tagSelected.connect(self._addTagFromPopup)
        self._popup.nameSelected.connect(self._searchByName)

        self.setStyleSheet(self._containerStyle())
        QApplication.instance().installEventFilter(self)

    def _containerStyle(self):
        return (
            "#searchInput {"
            "  background-color: %s;"
            "  border: 1px solid %s;"
            "  border-radius: 6px;"
            "}"
            "#searchInput QLineEdit {"
            "  background: transparent; border: none; border-radius: 0;"
            "}"
        ) % (BG_PRIMARY, BORDER_MID)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def setTags(self, tags):
        self._all_tags = list(tags)

    def setAssets(self, names):
        self._all_asset_names = [n for n in names if n]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _onTextChanged(self, text):
        if not text.strip():
            self.searchChanged.emit("")   # clear any active text-search filter
        self._showAutocomplete(text)

    def _showAutocomplete(self, text):
        if not text.strip():
            self._popup.hide()
            return
        q = text.strip().lower()
        tags  = [t for t in self._all_tags
                 if q in t.lower() and t not in self._active_tags][:8]
        names = [n for n in self._all_asset_names
                 if q in n.lower()][:6]
        if not tags and not names:
            self._popup.hide()
            return
        self._popup.setItems(tags, names)
        pos = self.mapToGlobal(self.rect().bottomLeft())
        self._popup.move(pos.x(), pos.y() + 2)
        self._popup.show()

    def _onEditKeyPress(self, e):
        if e.key() == Qt.Key_Down:
            if self._popup.isVisible():
                self._popup.selectNext()
            e.accept()
            return
        if e.key() == Qt.Key_Up:
            if self._popup.isVisible():
                self._popup.selectPrev()
            e.accept()
            return
        if e.key() in (Qt.Key_Enter, Qt.Key_Return):
            # If popup has a highlighted item, activate it
            if self._popup.isVisible() and self._popup.activateSelected():
                e.accept()
                return
            # Otherwise use typed text
            text = self._edit.text().strip()
            self._popup.hide()
            if text:
                tag = self._findTag(text)
                if tag:
                    self._addTag(tag)
                    self._edit.setText("")
                else:
                    self.searchChanged.emit(text)
            e.accept()
            return
        if e.key() == Qt.Key_Escape:
            self._popup.hide()
            e.accept()
            return
        if e.key() == Qt.Key_Backspace and not self._edit.text():
            if self._active_tags:
                self._removeTag(self._active_tags[-1])
            e.accept()
            return
        QLineEdit.keyPressEvent(self._edit, e)

    def _findTag(self, text):
        q = text.lower()
        # Exact match
        for t in self._all_tags:
            if t.lower() == q:
                return t
        # Prefix match
        for t in self._all_tags:
            if t.lower().startswith(q):
                return t
        # Partial match
        for t in self._all_tags:
            if q in t.lower():
                return t
        return None

    def _addTagFromPopup(self, tag):
        self._addTag(tag)
        self._edit.setText("")
        self._edit.setFocus()

    def _searchByName(self, name):
        self._edit.setText(name)
        self.searchChanged.emit(name)
        self._edit.setFocus()

    def _addTag(self, tag):
        if tag in self._active_tags:
            return
        self._active_tags.append(tag)
        pill = _TagPill(tag)
        pill.removed.connect(self._removeTag)
        # Insert before the QLineEdit (last item in layout)
        idx = self._pill_layout.count() - 1
        self._pill_layout.insertWidget(idx, pill)
        self._pills[tag] = pill
        self.tagAdded.emit(tag)

    def _removeTag(self, tag):
        if tag not in self._active_tags:
            return
        self._active_tags.remove(tag)
        pill = self._pills.pop(tag, None)
        if pill:
            self._pill_layout.removeWidget(pill)
            pill.deleteLater()
        self.tagRemoved.emit(tag)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and self._popup.isVisible():
            try:
                if not self._popup.geometry().contains(event.globalPos()):
                    self._popup.hide()
            except Exception:
                pass
        return super().eventFilter(obj, event)


class _TagPill(QWidget):
    """A removable tag chip displayed inside the search bar."""

    removed = Signal(str)

    def __init__(self, tag, parent=None):
        super().__init__(parent)
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
            " font-family: 'IBM Plex Sans', sans-serif;"
            % ACCENT_TEXT
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




# ─────────────────────────────────────────────────────────────────────────────
# Filter bar — inline row of per-category dropdown filters
# ─────────────────────────────────────────────────────────────────────────────

class _FilterBar(QWidget):
    filtersChanged = Signal(dict)

    _DEFS = [
        ("dcc",      "All DCCs",      ["Houdini exclusive", "Maya exclusive"]),
        ("type",     "All Types",     ["Materials", "Models", "HDAs", "HDRIs / Light rigs", "Textures"]),
        ("filetype", "All Files",     [".usd", ".rs", ".mtlx", ".abc", ".bgeo.sc", ".fbx", ".obj", ".hda", ".exr", ".hdr", ".hip", ".ma"]),
        ("includes", "Includes",      ["Rig", "Textures", "Materials"]),
        ("polycount", "Any Size",     ["< 10k", "10k – 50k", "50k – 200k", "200k – 500k", "500k+"]),
        ("author",   "All Authors",   []),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("filterBar")
        self.setFixedHeight(34)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "#filterBar { background: %s; }" % BG_SECONDARY
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(2)

        self._btns = {}
        self._state = {}

        for key, label, opts in self._DEFS:
            btn = _FilterDropBtn(label, opts)
            btn.selectionChanged.connect(lambda vals, k=key: self._onChange(k, vals))
            self._btns[key] = btn
            layout.addWidget(btn)

        # Project filter — search-as-you-type instead of checkbox list
        self._project_btn = _ProjectFilterBtn()
        self._project_btn.selectionChanged.connect(lambda vals: self._onChange("project", vals))
        layout.addWidget(self._project_btn)

        layout.addStretch(1)

    def setAuthors(self, authors):
        self._btns["author"].setOptions(list(authors))

    def setProjects(self, projects):
        self._project_btn.setProjects(projects)

    def _onChange(self, key, vals):
        self._state[key] = vals
        # Translate UI labels → filter values expected by _applyFilters
        state = dict(self._state)
        dcc = set()
        for x in state.get("dcc", set()):
            if x == "Houdini exclusive":
                dcc.add("Houdini")
            elif x == "Maya exclusive":
                dcc.add("Maya")
        state["dcc"] = dcc

        type_vals = state.get("type", set())
        state["type"] = {"Lighting" if x == "HDRIs / Light rigs" else x for x in type_vals}

        self.filtersChanged.emit(state)


class _FilterDropBtn(QWidget):
    selectionChanged = Signal(set)

    def __init__(self, default_label, options, parent=None):
        super().__init__(parent)
        self._default_label = default_label
        self._options = list(options)
        self._selected = set()
        self._popup_ref = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._btn = QPushButton(default_label + "  ▾")
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setStyleSheet(
            "QPushButton {"
            "  color: %s; background: transparent; border: none;"
            "  font-size: 11px; font-family: 'IBM Plex Sans', sans-serif;"
            "  padding: 4px 8px; border-radius: 4px;"
            "}"
            "QPushButton:hover { background: %s; color: %s; }"
            % (TEXT_SECONDARY, BG_TERTIARY, TEXT_PRIMARY)
        )
        self._btn.clicked.connect(self._showPopup)
        layout.addWidget(self._btn)

    def setOptions(self, options):
        self._options = list(options)
        self._selected = self._selected & set(options)
        self._updateLabel()

    def _updateLabel(self):
        if not self._selected:
            label = self._default_label
            color = TEXT_SECONDARY
        elif len(self._selected) == 1:
            label = next(iter(self._selected))
            color = ACCENT
        else:
            label = "%d selected" % len(self._selected)
            color = ACCENT
        self._btn.setText(label + "  ▾")
        self._btn.setStyleSheet(
            "QPushButton {"
            "  color: %s; background: transparent; border: none;"
            "  font-size: 11px; font-family: 'IBM Plex Sans', sans-serif;"
            "  padding: 4px 8px; border-radius: 4px;"
            "}"
            "QPushButton:hover { background: %s; color: %s; }"
            % (color, BG_TERTIARY, TEXT_PRIMARY)
        )

    def _showPopup(self):
        if not self._options:
            return
        self._popup_ref = _CheckPopup(self._options, self._selected)
        self._popup_ref.changed.connect(self._onChanged)
        pos = self._btn.mapToGlobal(self._btn.rect().bottomLeft())
        self._popup_ref.move(pos)
        self._popup_ref.show()

    def _onChanged(self, selected):
        self._selected = selected
        self._updateLabel()
        self.selectionChanged.emit(selected)


class _ProjectFilterBtn(QWidget):
    """Filter bar button for projects — click to open a search-as-you-type popup."""
    selectionChanged = Signal(set)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._projects = []
        self._selected = set()
        self._popup_ref = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._btn = QPushButton("All Projects  ▾")
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.clicked.connect(self._showPopup)
        layout.addWidget(self._btn)
        self._updateStyle()

    def setProjects(self, projects):
        self._projects = list(projects)
        self._selected = self._selected & set(projects)
        self._updateLabel()

    def _updateLabel(self):
        if not self._selected:
            label = "All Projects"
            color = TEXT_SECONDARY
        elif len(self._selected) == 1:
            label = next(iter(self._selected))
            color = ACCENT
        else:
            label = "%d projects" % len(self._selected)
            color = ACCENT
        self._btn.setText(label + "  ▾")
        self._updateStyle(color)

    def _updateStyle(self, color=None):
        c = color or TEXT_SECONDARY
        self._btn.setStyleSheet(
            "QPushButton {"
            "  color: %s; background: transparent; border: none;"
            "  font-size: 11px; font-family: 'IBM Plex Sans', sans-serif;"
            "  padding: 4px 8px; border-radius: 4px;"
            "}"
            "QPushButton:hover { background: %s; color: %s; }"
            % (c, BG_TERTIARY, TEXT_PRIMARY)
        )

    def _showPopup(self):
        if not self._projects:
            return
        self._popup_ref = _ProjectSearchPopup(self._projects, self._selected)
        self._popup_ref.selectionChanged.connect(self._onChanged)
        pos = self._btn.mapToGlobal(self._btn.rect().bottomLeft())
        self._popup_ref.move(pos)
        self._popup_ref.show()
        self._popup_ref.focusSearch()

    def _onChanged(self, selected):
        self._selected = selected
        self._updateLabel()
        self.selectionChanged.emit(selected)


class _ProjectSearchPopup(QFrame):
    """Popup with a search input + filtered project list."""
    selectionChanged = Signal(set)

    def __init__(self, projects, selected, parent=None):
        super().__init__(None, Qt.Popup)
        self._all_projects = list(projects)
        self._selected = set(selected)

        self.setObjectName("projectPopup")
        self.setFixedWidth(240)
        self.setStyleSheet("""
            #projectPopup {
                background: %(bg)s;
                border: 1px solid %(bm)s;
                border-radius: 6px;
            }
            QLineEdit {
                background: %(bg2)s;
                border: 1px solid %(bl)s;
                border-radius: 4px;
                padding: 4px 8px;
                color: %(tp)s;
                font-size: 11px;
            }
            QScrollArea { background: transparent; border: none; }
        """ % dict(bg=BG_PRIMARY, bg2=BG_SECONDARY, bl=BORDER_LIGHT,
                   bm=BORDER_MID, tp=TEXT_PRIMARY))

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search projects…")
        self._search.textChanged.connect(self._onSearch)
        root.addWidget(self._search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMaximumHeight(280)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)

        scroll.setWidget(self._list_widget)
        root.addWidget(scroll)

        self._buildList(self._all_projects)

    def focusSearch(self):
        self._search.setFocus()

    def _buildList(self, projects):
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for proj in projects:
            row = _ProjectRow(proj, proj in self._selected)
            row.toggled.connect(self._onToggle)
            self._list_layout.addWidget(row)

        self._list_layout.addStretch()

    def _onSearch(self, text):
        q = text.strip().lower()
        matches = [p for p in self._all_projects if q in p.lower()] if q else self._all_projects
        self._buildList(matches)

    def _onToggle(self, project, checked):
        if checked:
            self._selected.add(project)
        else:
            self._selected.discard(project)
        self.selectionChanged.emit(set(self._selected))


class _ProjectRow(QWidget):
    toggled = Signal(str, bool)

    def __init__(self, project, checked, parent=None):
        super().__init__(parent)
        self._project = project
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setCursor(Qt.PointingHandCursor)
        self._checked = checked

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        self._dot = QLabel("●" if checked else "○")
        self._dot.setFixedWidth(12)
        self._dot.setStyleSheet(
            "font-size: 9px; color: %s; background: transparent;" % (ACCENT if checked else TEXT_TERTIARY)
        )
        layout.addWidget(self._dot)

        lbl = QLabel(project)
        lbl.setStyleSheet(
            "font-size: 11px; color: %s; background: transparent;"
            " font-family: 'IBM Plex Sans', sans-serif;" % (TEXT_PRIMARY if checked else TEXT_SECONDARY)
        )
        layout.addWidget(lbl, 1)
        self.setFixedHeight(26)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._checked = not self._checked
            self._dot.setText("●" if self._checked else "○")
            self._dot.setStyleSheet(
                "font-size: 9px; color: %s; background: transparent;"
                % (ACCENT if self._checked else TEXT_TERTIARY)
            )
            self.toggled.emit(self._project, self._checked)


class _CheckPopup(QFrame):
    changed = Signal(set)

    def __init__(self, options, selected, parent=None):
        super().__init__(None, Qt.Popup)
        self._selected = set(selected)
        self._checkboxes = {}

        self.setObjectName("checkPopup")
        self.setStyleSheet("""
            #checkPopup {{
                background: {bg};
                border: 1px solid {bm};
                border-radius: 6px;
                padding: 4px 0;
            }}
            QCheckBox {{
                color: {ts};
                font-family: "IBM Plex Sans", sans-serif;
                font-size: 12px;
                spacing: 8px;
                background: transparent;
                padding: 3px 12px;
                min-height: 22px;
            }}
            QCheckBox:hover {{ color: {tp}; }}
            QCheckBox::indicator {{
                width: 13px; height: 13px;
                border: 1px solid {bl};
                border-radius: 3px;
                background: {bg2};
            }}
            QCheckBox::indicator:checked {{
                background: {accent};
                border-color: {accent};
            }}
        """.format(
            bg=BG_PRIMARY, bg2=BG_SECONDARY, bl=BORDER_LIGHT, bm=BORDER_MID,
            ts=TEXT_SECONDARY, tp=TEXT_PRIMARY, accent=ACCENT,
        ))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)

        for opt in options:
            cb = QCheckBox(opt)
            cb.setChecked(opt in selected)
            cb.stateChanged.connect(self._onChanged)
            self._checkboxes[opt] = cb
            layout.addWidget(cb)

        self.setFixedWidth(200)

    def _onChanged(self):
        self._selected = {opt for opt, cb in self._checkboxes.items() if cb.isChecked()}
        self.changed.emit(self._selected)
