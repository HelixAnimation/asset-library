import os
import sys
import logging

from qtpy.QtWidgets import QAction, QPushButton, QMenu, QMessageBox
from qtpy.QtCore import Qt, QTimer

from PrismUtils.Decorators import err_catcher as err_catcher

logger = logging.getLogger(__name__)


class Prism_AssetLibrary_Functions(object):
    def __init__(self, core, plugin):
        self.core = core
        self.plugin = plugin
        self._window = None

        self._addScriptPath()

        self.core.registerCallback(
            "trayContextMenuRequested",
            self.onTrayContextMenuRequested,
            plugin=self.plugin,
        )
        self.core.registerCallback(
            "projectBrowser_loadUI",
            self.onProjectBrowserLoadUI,
            plugin=self.plugin,
        )

    def _addScriptPath(self):
        scripts_dir = os.path.dirname(__file__)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    @err_catcher(name=__name__)
    def onTrayContextMenuRequested(self, tray, menu):
        sub = QMenu("Asset Library", menu)

        act_open = QAction("Open Library", sub)
        act_open.triggered.connect(self.launchAssetLibrary)
        sub.addAction(act_open)

        sub.addSeparator()

        act_scan = QAction("Scan / Sync Library", sub)
        act_scan.triggered.connect(self.scanLibrary)
        sub.addAction(act_scan)

        menu.addMenu(sub)

    @err_catcher(name=__name__)
    def onProjectBrowserLoadUI(self, origin):
        btn = QPushButton("Asset Library")
        btn.setToolTip("Open Asset Library")
        btn.clicked.connect(self.launchAssetLibrary)
        btn.setStyleSheet("QPushButton { font-size: 12px; padding: 4px 10px; }")
        origin.menubar.setCornerWidget(btn, Qt.TopRightCorner)

        if os.environ.get("ASSET_LIBRARY_AUTOOPEN") == "1":
            os.environ.pop("ASSET_LIBRARY_AUTOOPEN", None)
            QTimer.singleShot(500, self.launchAssetLibrary)

    # ------------------------------------------------------------------
    # Launch window
    # ------------------------------------------------------------------

    @err_catcher(name=__name__)
    def launchAssetLibrary(self):
        if self._window is None:
            from ui.library_browser import LibraryBrowser
            self._window = LibraryBrowser(self.core, plugin=self)

        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    # ------------------------------------------------------------------
    # Scan / sync
    # ------------------------------------------------------------------

    @err_catcher(name=__name__)
    def scanLibrary(self):
        asset_lib = self._getAssetLibRoot()
        if not asset_lib:
            self.core.popup(
                "ASSET_LIB environment variable is not set.\n"
                "Set it to the root of your NAS library and try again.",
                title="Asset Library",
            )
            return

        from core.db import AssetDB
        from core.scanner import PrismScanner

        db_path = os.path.join(asset_lib, "library.db")
        db = AssetDB(db_path)
        db.connect()

        try:
            scanner = PrismScanner(db, asset_lib, core=self.core)
            result = scanner.sync()
        finally:
            db.close()

        msg = (
            "Sync complete.\n\n"
            "Added:   {added}\n"
            "Updated: {updated}\n"
            "Removed: {removed}".format(**result)
        )
        if result["errors"]:
            msg += "\n\nErrors (%d):\n" % len(result["errors"])
            msg += "\n".join(result["errors"][:5])
            if len(result["errors"]) > 5:
                msg += "\n... (%d more)" % (len(result["errors"]) - 5)

        self.core.popup(msg, title="Asset Library Sync")

        if self._window is not None:
            try:
                self._window.refreshAssets()
            except Exception:
                pass

    def _getAssetLibRoot(self):
        try:
            stored = self.core.getConfig("assetLibrary", "rootPath")
            if stored and os.path.isdir(stored):
                return stored
        except Exception:
            pass
        return None

    def setLibraryRoot(self, path):
        try:
            self.core.setConfig("assetLibrary", "rootPath", val=path)
        except Exception as e:
            logger.error("Failed to save library root: %s", e)

    def getDB(self):
        asset_lib = self._getAssetLibRoot()
        if not asset_lib:
            return None

        from core.db import AssetDB
        db_path = os.path.join(asset_lib, "library.db")
        db = AssetDB(db_path)
        db.connect()
        return db
