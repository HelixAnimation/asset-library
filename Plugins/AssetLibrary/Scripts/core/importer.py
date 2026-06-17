import os
import re
import shutil
import struct
import logging
import sqlite3
import zlib
from dataclasses import dataclass, asdict

from qtpy.QtCore import QThread, Signal

logger = logging.getLogger(__name__)

_THUMB_PALETTES = [
    ("#3d2820", "#e8a090"),
    ("#1a2d3d", "#90b8e0"),
    ("#1e2e20", "#90c8a0"),
    ("#2e2a1a", "#c8b880"),
    ("#281e38", "#a090c8"),
]

_VERSION_RE = re.compile(r"^v\d{3}$|^master$")


@dataclass
class ImportResult:
    success: bool
    asset_id: int = -1
    nas_path: str = ""
    version_dir: str = ""
    error: str = ""
    error_type: str = ""


class AssetImporter:
    """Validates, copies, and registers a single asset into the library."""

    def __init__(self, library_root, db):
        self.root = library_root
        self.db = db

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, data):
        """Return list of error strings. Empty list means valid."""
        errors = []
        name = data.get("name", "").strip()
        filepaths = data.get("filepaths") or []
        category = data.get("category", "").strip()

        if not name:
            errors.append("Asset name is required.")
        if not filepaths:
            errors.append("At least one file is required.")
        else:
            for fp in filepaths:
                if not os.path.isfile(fp):
                    errors.append("Source file does not exist: %s" % fp)
        if not category:
            errors.append("Category is required.")

        if self.root and os.path.isdir(self.root):
            marker = os.path.join(self.root, ".assetlib_write_test")
            try:
                with open(marker, "w") as f:
                    f.write("test")
                os.remove(marker)
            except OSError:
                errors.append("Library root is not writable: %s" % self.root)

        return errors

    # ------------------------------------------------------------------
    # Path construction
    # ------------------------------------------------------------------

    def build_nas_path(self, data):
        """Absolute path to the version directory on NAS."""
        parts = [data["category"]]
        sub = data.get("subcategory", "")
        if sub:
            parts.append(sub)
        parts.append(data["name"])
        parts.append(data.get("version", "v001"))
        return os.path.join(self.root, *parts)

    def build_prism_path(self, data):
        """Relative path like 'Models/Anatomy/Heart' (forward slashes)."""
        parts = [data["category"]]
        sub = data.get("subcategory", "")
        if sub:
            parts.append(sub)
        parts.append(data["name"])
        return "/".join(parts)

    # ------------------------------------------------------------------
    # Main import
    # ------------------------------------------------------------------

    def import_asset(self, data, thumbnails=None, texture_files=None):
        """Full pipeline: validate -> determine version -> copy -> thumbnails -> DB write."""
        errors = self.validate(data)
        if errors:
            return ImportResult(False, error="\n".join(errors), error_type="validation")

        prism_path = self.build_prism_path(data)
        filetype = data.get("filetype") or (
            self._filetype_for_path(data["filepaths"][0])
            if data.get("filepaths") else ""
        )

        # Check if asset exists and determine version
        existing = self.db.conn.execute(
            "SELECT id FROM assets WHERE prism_path = ?", (prism_path,)
        ).fetchone()

        if existing:
            asset_id = existing[0]
            # Always auto-increment for existing assets — ignore dialog's "v001"
            version = self.db.next_version_number(asset_id)
        else:
            asset_id = None
            version = data.get("version", "v001")

        data["version"] = version
        version_dir = self.build_nas_path(data)
        filepaths = data.get("filepaths") or []

        # 1. Copy all files to version directory
        copied = []
        try:
            for src in filepaths:
                dest = self._copy_file(src, version_dir)
                copied.append(dest)
        except OSError as exc:
            for c in copied:
                try:
                    os.remove(c)
                except OSError:
                    pass
            return ImportResult(False, error="Copy failed: %s" % exc, error_type="copy")

        primary_rel = self._rel(copied[0]) if copied else ""
        copied_entries = [
            (path, self._rel(path), self._filetype_for_path(path))
            for path in copied
        ]

        # 2. Thumbnails — stored inside the version folder
        thumb_rel = self._handle_thumbnails(version_dir, data["name"], thumbnails or {})

        # 3. Textures
        has_textures = self._copy_textures(version_dir, texture_files or [])
        if has_textures:
            data["has_textures"] = 1

        # 4. DB write
        try:
            if asset_id:
                # Update asset's version-level columns to reflect new version
                update = {
                    "filepath": primary_rel,
                    "filetype": filetype,
                    "version": version,
                    "thumbnail_path": thumb_rel or "",
                    "renderer": data.get("renderer", "Any"),
                    "dcc": data.get("dcc", "Universal"),
                    "has_rig": int(data.get("has_rig", 0)),
                    "has_textures": int(data.get("has_textures", 0)),
                    "has_materials": int(data.get("has_materials", 0)),
                }
                if data.get("polycount") is not None:
                    update["polycount"] = int(data["polycount"])
                self.db.update_asset(asset_id, update)
            else:
                asset_data = {k: v for k, v in data.items() if not k.startswith("_")}
                asset_data["filepath"] = primary_rel
                asset_data["filetype"] = filetype
                asset_data["prism_path"] = prism_path
                asset_data["version"] = version
                asset_data.pop("filepaths", None)
                if thumb_rel:
                    asset_data["thumbnail_path"] = thumb_rel
                asset_id = self.db.add_asset(asset_data)

            # Write one version row per exported file type.
            for _abs_path, rel_path, version_filetype in copied_entries:
                self.db.upsert_version(
                    asset_id, version, rel_path, version_filetype, prism_path,
                    renderer=data.get("renderer"),
                    dcc=data.get("dcc"),
                    has_rig=data.get("has_rig", 0),
                    has_textures=data.get("has_textures", 0),
                    has_materials=data.get("has_materials", 0),
                    thumbnail_path=thumb_rel,
                )
            if data.get("tags"):
                self.db.set_asset_tags(asset_id, data["tags"])
        except sqlite3.Error as exc:
            return ImportResult(False, error="DB error: %s" % exc, error_type="db")

        return ImportResult(True, asset_id=asset_id, nas_path=primary_rel, version_dir=version_dir)

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------

    def _copy_file(self, src, dest_dir):
        """Copy source file to dest_dir. Returns absolute dest path."""
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(src))
        if os.path.abspath(src) == os.path.abspath(dest):
            return dest
        shutil.copy2(src, dest)
        return dest

    def _filetype_for_path(self, path):
        name = os.path.basename(path).lower()
        if name.endswith(".bgeo.sc"):
            return ".bgeo.sc"
        return os.path.splitext(name)[1].lower()

    def _handle_thumbnails(self, version_dir, name, thumbnails):
        """Ensure version_dir/thumbs/ exists and return its relative path.

        Houdini publishes render turntable frames directly into this directory
        via the AssetPublisher ROPs. Do not create static material.png/clay.png
        files here; the browser scans the directory for material/clay/wire
        frame images.
        """
        thumbs_dir = os.path.join(version_dir, "thumbs")
        os.makedirs(thumbs_dir, exist_ok=True)
        return self._rel(thumbs_dir)

    def _copy_textures(self, version_dir, texture_files):
        """Copy texture files to version_dir/textures/. Returns True if any were copied."""
        if not texture_files:
            return False
        textures_dir = os.path.join(version_dir, "textures")
        copied = False
        for src in texture_files:
            if os.path.isfile(src):
                try:
                    os.makedirs(textures_dir, exist_ok=True)
                    dest = os.path.join(textures_dir, os.path.basename(src))
                    if os.path.abspath(src) != os.path.abspath(dest):
                        shutil.copy2(src, dest)
                    copied = True
                except OSError as exc:
                    logger.warning("Could not copy texture %s: %s", src, exc)
        return copied

    def _generate_placeholder(self, dest_path, name):
        """Generate a 256x256 placeholder PNG (pure Python, thread-safe)."""
        size = 256
        idx = hash(name or "") % len(_THUMB_PALETTES)
        bg_hex, _ = _THUMB_PALETTES[idx]
        bg_r = int(bg_hex[1:3], 16)
        bg_g = int(bg_hex[3:5], 16)
        bg_b = int(bg_hex[5:7], 16)

        def _chunk(chunk_type, data):
            c = chunk_type + data
            crc = struct.pack(">I", zlib.crc32(c) & 0xffffffff)
            return struct.pack(">I", len(data)) + c + crc

        png = b"\x89PNG\r\n\x1a\n"
        png += _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        # Filter byte (0) + raw RGB per row
        row = bytes([0]) + bytes([bg_r, bg_g, bg_b]) * size
        raw_rows = row * size
        png += _chunk(b"IDAT", zlib.compress(raw_rows))
        png += _chunk(b"IEND", b"")

        with open(dest_path, "wb") as f:
            f.write(png)

    def _rel(self, abs_path):
        """Make path relative to library root, forward slashes."""
        try:
            return os.path.relpath(abs_path, self.root).replace("\\", "/")
        except ValueError:
            return abs_path.replace("\\", "/")


class ImportThread(QThread):
    """Runs AssetImporter.import_asset() off the main thread."""
    finished = Signal(dict)
    progress = Signal(int)

    def __init__(self, library_root, db_path, data, thumbnails=None, texture_files=None):
        super().__init__()
        self._root = library_root
        self._db_path = db_path
        self._data = data
        self._thumbnails = thumbnails or {}
        self._texture_files = texture_files or []

    def run(self):
        try:
            from core.db import AssetDB
            db = AssetDB(self._db_path)
            db.connect()
            try:
                importer = AssetImporter(self._root, db)
                result = importer.import_asset(self._data, self._thumbnails, self._texture_files)
                self.finished.emit(asdict(result))
            finally:
                db.close()
        except Exception as exc:
            self.finished.emit({
                "success": False,
                "asset_id": -1,
                "nas_path": "",
                "error": str(exc),
                "error_type": "unknown",
            })
