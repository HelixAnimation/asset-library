import os
import logging

logger = logging.getLogger(__name__)

# File extensions that map to each category
_FILETYPE_CATEGORY = {
    ".rs":    "Materials",
    ".mtlx":  "Materials",
    ".hda":   "HDAs",
    ".otl":   "HDAs",
    ".abc":   "Models",
    ".bgeo":  "Models",
    ".bgeo.sc": "Models",
    ".fbx":   "Models",
    ".exr":   "Textures",   # also HDRIs — resolved below
    ".hdr":   "Lighting",
    ".tx":    "Textures",
    ".png":   "Textures",
    ".tif":   "Textures",
    ".tiff":  "Textures",
    ".hip":   "HDAs",
    ".hipnc": "HDAs",
    ".ma":    "Models",
    ".mb":    "Models",
    ".usd":   None,          # determined by context
    ".usda":  None,
    ".usdc":  None,
    ".usdz":  None,
}

_ASSET_FILE_EXTENSIONS = set(_FILETYPE_CATEGORY.keys())

# Extensions that are definitively Houdini-only
_HOUDINI_ONLY = {".hda", ".otl", ".hip", ".hipnc"}
# Extensions that are definitively Maya-only
_MAYA_ONLY = {".ma", ".mb"}


class PrismScanner:
    """
    Walks the asset library root and syncs discovered assets into library.db.

    Pass core=self.core when running inside Prism — used for reading versioninfo
    files (author, date) and resolving the current username.  Asset discovery
    always uses the filesystem; core is never needed for enumeration.
    """

    def __init__(self, db, asset_lib_root, core=None):
        self.db = db
        self.root = asset_lib_root
        self.core = core
        self._assets_root = asset_lib_root

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync(self):
        """
        Walk the NAS and sync all discovered assets into the DB.
        Returns a dict: {added, updated, removed, errors}.
        """
        if not os.path.isdir(self._assets_root):
            logger.warning("Assets root not found: %s", self._assets_root)
            return {"added": 0, "updated": 0, "removed": 0, "errors": ["Assets root not found: %s" % self._assets_root]}

        stats = {"added": 0, "updated": 0, "removed": 0, "errors": []}
        seen_prism_paths = set()

        for version_info in self._walk_versions():
            try:
                prism_path = version_info["prism_path"]
                seen_prism_paths.add(prism_path)
                added, updated = self._sync_version(version_info)
                stats["added"] += added
                stats["updated"] += updated
            except Exception as exc:
                msg = "Error syncing %s: %s" % (version_info.get("prism_path", "?"), exc)
                logger.error(msg)
                stats["errors"].append(msg)

        removed = self._remove_stale(seen_prism_paths)
        stats["removed"] = removed

        logger.info("Sync complete — added=%d updated=%d removed=%d errors=%d",
                    stats["added"], stats["updated"], stats["removed"], len(stats["errors"]))
        return stats

    def preview(self):
        """Dry-run: return a list of dicts describing what would be synced."""
        return list(self._walk_versions())

    # ------------------------------------------------------------------
    # Walking
    # ------------------------------------------------------------------

    def _walk_versions(self):
        """
        Walk the library root and yield one dict per (asset, product, version).

        Expected structure:
            {category}/{subcategory}/{asset_name}/Export/{product}/{version}/
        """
        yield from self._walk_filesystem()

    def _walk_filesystem(self):
        """
        Walks {category}/{subcategory}/{name}/{version}/ directly from the library root.
        Version folders are identified by _looks_like_version().
        """
        if not os.path.isdir(self._assets_root):
            return

        for dirpath, dirnames, _ in os.walk(self._assets_root):
            # Prune underscore-prefixed root-level dirs so os.walk never descends into them
            if os.path.normpath(dirpath) == os.path.normpath(self._assets_root):
                dirnames[:] = [d for d in dirnames if not d.startswith("_")]

            version_str = os.path.basename(dirpath)
            if not self._looks_like_version(version_str):
                continue

            files = self._list_asset_files(dirpath)
            if not files:
                continue

            # Path from root → everything above the version folder = asset identity
            asset_dir = os.path.dirname(dirpath)
            asset_path = os.path.relpath(asset_dir, self._assets_root).replace("\\", "/")
            category, subcategory, name = self._parse_asset_path(asset_path)

            yield {
                "name":        name,
                "category":    category,
                "subcategory": subcategory,
                "prism_path":  asset_path,
                "version":     version_str,
                "version_dir": dirpath,
                "asset_dir":   asset_dir,
                "files":       files,
                "author":      self._read_version_author(dirpath),
            }

    # ------------------------------------------------------------------
    # DB sync helpers
    # ------------------------------------------------------------------

    def _sync_version(self, info):
        """
        Ensure the asset row exists and upsert version records.
        Returns (added, updated) counts.
        """
        added = 0
        updated = 0

        # Find or create the asset row
        rows = self.db.conn.execute(
            "SELECT id, version FROM assets WHERE prism_path = ?",
            (info["prism_path"],),
        ).fetchall()

        # Determine preferred file (USD first, then first alphabetically)
        preferred_file = self._pick_preferred_file(info["files"])
        preferred_ext = os.path.splitext(preferred_file)[1].lower() if preferred_file else ""
        preferred_rel = self._rel(preferred_file)

        category = info["category"] or self._infer_category_from_files(info["files"])
        dcc = self._infer_dcc(info["files"])

        # Detect thumbs and textures folders inside the version folder
        version_dir = info.get("version_dir", "")
        thumbs_dir = os.path.join(version_dir, "thumbs") if version_dir else ""
        thumb_rel = self._rel(thumbs_dir) if thumbs_dir and os.path.isdir(thumbs_dir) else None
        textures_dir = os.path.join(version_dir, "textures") if version_dir else ""
        has_textures = 1 if textures_dir and os.path.isdir(textures_dir) else None

        if not rows:
            new_asset = {
                "name":           info["name"],
                "category":       category,
                "subcategory":    info["subcategory"],
                "filepath":       preferred_rel,
                "filetype":       preferred_ext,
                "dcc":            dcc,
                "version":        info["version"],
                "author":         info["author"],
                "prism_path":     info["prism_path"],
                "thumbnail_path": thumb_rel,
            }
            if has_textures:
                new_asset["has_textures"] = has_textures
            asset_id = self.db.add_asset(new_asset)
            added += 1
        else:
            asset_id = rows[0]["id"]
            current_ver = rows[0]["version"]
            update_data = {}
            if self._version_gt(info["version"], current_ver):
                update_data.update({
                    "filepath": preferred_rel,
                    "filetype": preferred_ext,
                    "version":  info["version"],
                    "dcc":      dcc,
                })
            if thumb_rel:
                update_data["thumbnail_path"] = thumb_rel
            if has_textures:
                update_data["has_textures"] = has_textures
            if update_data:
                self.db.update_asset(asset_id, update_data)
                updated += 1

        # Upsert a versions row for every file in this version folder
        for filepath in info["files"]:
            ext = os.path.splitext(filepath)[1].lower()
            self.db.upsert_version(
                asset_id=asset_id,
                version=info["version"],
                filepath=self._rel(filepath),
                filetype=ext,
                prism_path=info["prism_path"],
            )

        return added, updated

    def _remove_stale(self, seen_prism_paths):
        """Delete assets whose prism_path no longer exists on disk."""
        rows = self.db.conn.execute(
            "SELECT id, prism_path FROM assets WHERE prism_path IS NOT NULL"
        ).fetchall()
        removed = 0
        for row in rows:
            if row["prism_path"] not in seen_prism_paths:
                self.db.delete_asset(row["id"])
                removed += 1
        return removed

    # ------------------------------------------------------------------
    # Path / file helpers
    # ------------------------------------------------------------------

    def _parse_asset_path(self, asset_path):
        """
        Split a Prism asset_path like "Models/Anatomy/Heart" into
        (category, subcategory, name).  Handles 1-, 2-, and 3+-level paths.
        """
        parts = [p for p in asset_path.replace("\\", "/").split("/") if p]
        if len(parts) == 0:
            return "Uncategorized", None, "Unknown"
        elif len(parts) == 1:
            return "Uncategorized", None, parts[0]
        elif len(parts) == 2:
            return parts[0], None, parts[1]
        else:
            return parts[0], parts[1], parts[-1]

    def _list_asset_files(self, version_dir):
        """Return absolute paths of recognisable asset files in a version folder."""
        result = []
        try:
            for fname in os.listdir(version_dir):
                ext = os.path.splitext(fname)[1].lower()
                if ext in _ASSET_FILE_EXTENSIONS:
                    result.append(os.path.join(version_dir, fname))
        except OSError:
            pass
        return sorted(result)

    def _pick_preferred_file(self, files):
        """Pick the best single representative file: USD > rs > mtlx > first."""
        if not files:
            return None
        priority = [".usd", ".usda", ".usdc", ".usdz", ".rs", ".mtlx", ".hda", ".abc", ".fbx"]
        for ext in priority:
            for f in files:
                if f.lower().endswith(ext):
                    return f
        return files[0]

    def _infer_category_from_files(self, files):
        """Fallback category when path hierarchy doesn't tell us."""
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            cat = _FILETYPE_CATEGORY.get(ext)
            if cat:
                return cat
        return "Uncategorized"

    def _infer_dcc(self, files):
        exts = {os.path.splitext(f)[1].lower() for f in files}
        if exts & _HOUDINI_ONLY and not exts & _MAYA_ONLY:
            return "Houdini"
        if exts & _MAYA_ONLY and not exts & _HOUDINI_ONLY:
            return "Maya"
        return "Universal"

    def _looks_like_version(self, name):
        """True if the folder name looks like a Prism version (v001, master, etc.)."""
        n = name.lower()
        return n == "master" or (n.startswith("v") and n[1:].split("_")[0].isdigit())

    def _version_gt(self, a, b):
        """Return True if version string a is newer than b."""
        def _num(v):
            v = v.lower().split("_")[0]
            if v == "master":
                return 999999
            try:
                return int(v.lstrip("v"))
            except ValueError:
                return 0
        return _num(a) > _num(b)

    def _rel(self, abs_path):
        """Make a path relative to the asset library root."""
        try:
            return os.path.relpath(abs_path, self.root).replace("\\", "/")
        except ValueError:
            return abs_path.replace("\\", "/")

    def _read_version_author(self, version_dir):
        """Read author from versioninfo.json (preferred) or versioninfo.yml."""
        for fname in ("versioninfo.json", "versioninfo.yml"):
            fpath = os.path.join(version_dir, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                return self._parse_version_info(fpath)
            except Exception:
                pass
        return None

    def _parse_version_info(self, fpath):
        """Extract author from versioninfo.json or .yml."""
        import json
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        if fpath.endswith(".json"):
            data = json.loads(content)
            return data.get("username") or data.get("user") or data.get("author")
        # Minimal YAML: just scan for key: value lines
        for key in ("username", "user", "author"):
            for line in content.splitlines():
                if line.strip().startswith(key + ":"):
                    return line.split(":", 1)[1].strip().strip('"').strip("'")
        return None
