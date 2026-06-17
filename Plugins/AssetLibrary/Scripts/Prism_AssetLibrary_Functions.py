import os
import sys
import logging

from qtpy.QtWidgets import QAction, QPushButton, QMessageBox, QWidget, QHBoxLayout
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
        self.core.registerCallback(
            "onHoudiniStartupComplete",
            self.onHoudiniStartupComplete,
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
        act = QAction("Asset Library", menu)
        act.triggered.connect(self.launchAssetLibrary)

        # Place just below Prism's "Project Browser" action
        actions = menu.actions()
        pb = next((a for a in actions if "browser" in a.text().lower()), None)
        if pb:
            idx = actions.index(pb)
            after = actions[idx + 1] if idx + 1 < len(actions) else None
            if after:
                menu.insertAction(after, act)
            else:
                menu.addAction(act)
        else:
            menu.addAction(act)

    @err_catcher(name=__name__)
    def onHoudiniStartupComplete(self, *args, **kwargs):
        self._installHoudiniShelf()
        self._installHoudiniPackage()
        self._installHoudiniPanel()
        self._installHoudiniHDA()

    def _installHoudiniShelf(self):
        try:
            import hou
        except ImportError:
            return
        shelf_path = os.path.join(
            self.plugin.pluginDirectory, "Houdini", "toolbar", "AssetLibrary.shelf"
        )
        if not os.path.isfile(shelf_path):
            return
        try:
            existing = {s.filePath() for s in hou.shelves.shelves().values()}
            if shelf_path not in existing:
                hou.shelves.loadFile(shelf_path)
        except Exception as exc:
            logger.warning("Could not install Asset Library shelf: %s", exc)

    def _installHoudiniPackage(self):
        """Write a Houdini package file so HOUDINI_PATH includes our Houdini/ dir.
        This makes python_panels/ (and toolbar/) auto-discovered on every startup."""
        try:
            import hou, json
        except ImportError:
            return
        houdini_dir = os.path.join(self.plugin.pluginDirectory, "Houdini")
        if not os.path.isdir(houdini_dir):
            return
        pref_dir = hou.getenv("HOUDINI_USER_PREF_DIR") or ""
        if not pref_dir:
            return
        try:
            pkg_dir = os.path.join(pref_dir, "packages")
            os.makedirs(pkg_dir, exist_ok=True)
            pkg_path = os.path.join(pkg_dir, "AssetLibrary.json")
            pkg_content = {"path": houdini_dir.replace("\\", "/")}
            # Only rewrite if path changed (plugin moved)
            if os.path.isfile(pkg_path):
                with open(pkg_path, "r") as f:
                    existing = json.load(f)
                if existing == pkg_content:
                    return
            with open(pkg_path, "w") as f:
                json.dump(pkg_content, f, indent=2)
        except Exception as exc:
            logger.warning("Could not write Asset Library package file: %s", exc)

    def _installHoudiniPanel(self):
        try:
            import hou
        except ImportError:
            return
        panel_path = os.path.join(
            self.plugin.pluginDirectory, "Houdini", "python_panels", "AssetLibrary.pypanel"
        )
        if not os.path.isfile(panel_path):
            return
        try:
            # Install into current session (package handles future startups)
            if "AssetLibrary" not in hou.pypanel.interfaces():
                hou.pypanel.installFile(panel_path)
        except Exception as exc:
            logger.warning("Could not install Asset Library panel: %s", exc)

    def _installHoudiniHDA(self):
        import glob
        try:
            import hou
        except ImportError:
            return
        otls_dir = os.path.join(self.plugin.pluginDirectory, "Houdini", "otls")
        # Version-agnostic: install every AssetPublisher HDA found in otls/. The
        # '*' doesn't cross '/', so otls/backup/ is naturally excluded. New Tab-menu
        # nodes pick the highest version (2.0); older ::1.3 scenes still resolve.
        hda_files = glob.glob(os.path.join(otls_dir, "object_AssetPublisher.*.hda"))
        if not hda_files:
            return
        canonical = {p.replace("\\", "/") for p in hda_files}
        try:
            # Evict any AssetPublisher HDA loaded from a stale path (e.g. a leftover
            # package file that still points to the old dev folder after the plugin
            # was moved to the NAS). Without this the dev HDA wins and the NAS one
            # never takes effect.
            for loaded_path in list(hou.hda.loadedFiles()):
                norm = loaded_path.replace("\\", "/")
                base = norm.rsplit("/", 1)[-1]
                if base.startswith("object_AssetPublisher.") and base.endswith(".hda"):
                    if norm not in canonical:
                        try:
                            hou.hda.uninstallFile(norm)
                        except Exception:
                            pass
            loaded = {f.replace("\\", "/") for f in hou.hda.loadedFiles()}
            for hda_path in hda_files:
                if hda_path.replace("\\", "/") not in loaded:
                    hou.hda.installFile(hda_path)
        except Exception as exc:
            logger.warning("Could not install Asset Publisher HDA: %s", exc)

    @err_catcher(name=__name__)
    def onProjectBrowserLoadUI(self, origin):
        btn = QPushButton("⊞  Asset Library")
        btn.setToolTip("Open Asset Library")
        btn.clicked.connect(self.launchAssetLibrary)
        btn.setStyleSheet(
            "QPushButton {"
            "  font-size: 12px; padding: 3px 10px;"
            "  background: transparent; border: none;"
            "  color: #c8cdd3;"
            "}"
            "QPushButton:hover {"
            "  color: #ffffff;"
            "  background: rgba(255,255,255,0.08);"
            "  border-radius: 3px;"
            "}"
            "QPushButton:pressed { background: rgba(255,255,255,0.14); border-radius: 3px; }"
        )

        # Preserve whatever Prism already placed at the top-right corner
        # (e.g. the project selector / user button) by wrapping both in a
        # container.  We must keep a Python reference to the container on self;
        # PySide6 does not reflect C++ ownership back to Python, so without it
        # the GC collects the container wrapper, deletes the C++ object, and
        # takes Prism's child widgets (b_user etc.) with it — crashing on the
        # next setText() call.
        existing = origin.menubar.cornerWidget(Qt.TopRightCorner)
        if existing:
            container = QWidget()
            container.setStyleSheet("background: transparent;")
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 4, 0)
            row.setSpacing(6)
            row.addWidget(btn)
            existing.setParent(container)
            row.addWidget(existing)
            self._corner_container = container  # keep alive — prevents GC crash
            origin.menubar.setCornerWidget(container, Qt.TopRightCorner)
        else:
            origin.menubar.setCornerWidget(btn, Qt.TopRightCorner)

        if os.environ.get("ASSET_LIBRARY_AUTOOPEN") == "1":
            os.environ.pop("ASSET_LIBRARY_AUTOOPEN", None)
            QTimer.singleShot(500, self.launchAssetLibrary)

    # ------------------------------------------------------------------
    # Launch window
    # ------------------------------------------------------------------

    @err_catcher(name=__name__)
    def launchAssetLibrary(self):
        try:
            import hou
            self._launchHoudiniPanel()
            return
        except ImportError:
            pass

        if self._window is None:
            from ui.library_browser import LibraryBrowser
            self._window = LibraryBrowser(self.core, plugin=self)

        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _launchHoudiniPanel(self):
        import hou
        iface = hou.pypanel.interfaceByName("AssetLibrary")
        if iface is None:
            self._installHoudiniPanel()
            iface = hou.pypanel.interfaceByName("AssetLibrary")

        desktop = hou.ui.curDesktop()

        # Reuse existing open panel if there is one
        for pane in desktop.panes():
            for tab in pane.tabs():
                if isinstance(tab, hou.PythonPanel):
                    active = tab.activeInterface()
                    if active and active.name() == "AssetLibrary":
                        tab.setIsCurrentTab()
                        return

        # Open a new floating panel
        tab = desktop.createFloatingPaneTab(hou.paneTabType.PythonPanel)
        if iface:
            tab.setActiveInterface(iface)

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
