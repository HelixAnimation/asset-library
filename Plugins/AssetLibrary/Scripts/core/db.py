import os
import sqlite3
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 5

_SCHEMA_V1 = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    category       TEXT NOT NULL,
    subcategory    TEXT,
    filepath       TEXT NOT NULL,
    filetype       TEXT NOT NULL,
    renderer       TEXT NOT NULL DEFAULT 'Any',
    dcc            TEXT NOT NULL DEFAULT 'Universal',
    has_rig        INTEGER NOT NULL DEFAULT 0,
    has_textures   INTEGER NOT NULL DEFAULT 0,
    has_materials  INTEGER NOT NULL DEFAULT 0,
    version        TEXT NOT NULL DEFAULT 'v001',
    author         TEXT,
    thumbnail_path TEXT,
    prism_path     TEXT,
    created_at     TEXT,
    updated_at     TEXT
);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS asset_tags (
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tags(id)   ON DELETE CASCADE,
    PRIMARY KEY (asset_id, tag_id)
);

CREATE TABLE IF NOT EXISTS favorites (
    asset_id   INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    username   TEXT    NOT NULL,
    created_at TEXT,
    PRIMARY KEY (asset_id, username)
);

CREATE TABLE IF NOT EXISTS recently_used (
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    username TEXT    NOT NULL,
    used_at  TEXT    NOT NULL,
    PRIMARY KEY (asset_id, username)
);
"""

# Migration to v2: adds versions table
_MIGRATION_V2 = """
CREATE TABLE IF NOT EXISTS versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id    INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    version     TEXT    NOT NULL,
    filepath    TEXT    NOT NULL,
    filetype    TEXT    NOT NULL,
    prism_path  TEXT,
    created_at  TEXT,
    UNIQUE(asset_id, version, filetype)
);
"""

# Migration to v3: adds project column to assets
_MIGRATION_V3 = """
ALTER TABLE assets ADD COLUMN project TEXT;
"""

# Migration to v4: adds omitted flag
_MIGRATION_V4 = """
ALTER TABLE assets ADD COLUMN omitted INTEGER NOT NULL DEFAULT 0;
"""

# Migration to v6: adds polycount
_MIGRATION_V6 = """
ALTER TABLE assets ADD COLUMN polycount INTEGER;
"""

# Migration to v5: adds version-level columns to versions table
_MIGRATION_V5 = """
ALTER TABLE versions ADD COLUMN renderer       TEXT NOT NULL DEFAULT 'Any';
ALTER TABLE versions ADD COLUMN dcc            TEXT NOT NULL DEFAULT 'Universal';
ALTER TABLE versions ADD COLUMN has_rig        INTEGER NOT NULL DEFAULT 0;
ALTER TABLE versions ADD COLUMN has_textures   INTEGER NOT NULL DEFAULT 0;
ALTER TABLE versions ADD COLUMN has_materials  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE versions ADD COLUMN thumbnail_path TEXT;
"""


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_dict(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


class AssetDB:
    def __init__(self, db_path):
        self.db_path = db_path
        self._conn = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self):
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self.create_schema()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    @property
    def conn(self):
        if self._conn is None:
            self.connect()
        return self._conn

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def create_schema(self):
        self.conn.executescript(_SCHEMA_V1)
        row = self.conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            self.conn.execute("INSERT INTO schema_version VALUES (1)")
            self.conn.commit()
            row = self.conn.execute("SELECT version FROM schema_version").fetchone()

        current = row[0]
        if current < 2:
            self.conn.executescript(_MIGRATION_V2)
            self.conn.execute("UPDATE schema_version SET version = 2")
            self.conn.commit()

        if current < 3:
            self.conn.executescript(_MIGRATION_V3)
            self.conn.execute("UPDATE schema_version SET version = 3")
            self.conn.commit()

        if current < 4:
            self.conn.executescript(_MIGRATION_V4)
            self.conn.execute("UPDATE schema_version SET version = 4")
            self.conn.commit()

        if current < 5:
            self.conn.executescript(_MIGRATION_V5)
            self.conn.execute("UPDATE schema_version SET version = 5")
            self.conn.commit()

        if current < 6:
            self.conn.executescript(_MIGRATION_V6)
            self.conn.execute("UPDATE schema_version SET version = 6")
            self.conn.commit()

    # ------------------------------------------------------------------
    # Assets
    # ------------------------------------------------------------------

    def get_assets(
        self,
        category=None,
        subcategory=None,
        dcc=None,
        filetype=None,
        renderer=None,
        tags=None,
        author=None,
        search=None,
        favorites_only=False,
        username=None,
    ):
        query = "SELECT a.* FROM assets a"
        joins = []
        wheres = []
        params = []

        if tags:
            joins.append(
                "JOIN asset_tags at_ ON at_.asset_id = a.id "
                "JOIN tags t ON t.id = at_.tag_id"
            )
            placeholders = ",".join("?" * len(tags))
            wheres.append("t.name IN (%s)" % placeholders)
            params.extend(tags)

        if favorites_only and username:
            joins.append("JOIN favorites f ON f.asset_id = a.id AND f.username = ?")
            params.insert(0, username)

        if joins:
            query += " " + " ".join(joins)

        if category:
            wheres.append("a.category = ?")
            params.append(category)
        if subcategory:
            wheres.append("a.subcategory = ?")
            params.append(subcategory)
        if dcc and dcc != "Universal":
            wheres.append("(a.dcc = 'Universal' OR a.dcc = ?)")
            params.append(dcc)
        if filetype:
            wheres.append("a.filetype = ?")
            params.append(filetype)
        if renderer and renderer != "Any":
            wheres.append("(a.renderer = 'Any' OR a.renderer = ?)")
            params.append(renderer)
        if author:
            wheres.append("a.author = ?")
            params.append(author)
        if search:
            wheres.append("a.name LIKE ?")
            params.append("%" + search + "%")

        wheres.append("a.omitted = 0")

        if wheres:
            query += " WHERE " + " AND ".join(wheres)

        if tags:
            query += " GROUP BY a.id HAVING COUNT(DISTINCT t.name) = ?"
            params.append(len(tags))

        query += " ORDER BY a.updated_at DESC"

        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_asset(self, asset_id):
        row = self.conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        return dict(row) if row else None

    def add_asset(self, data):
        now = _now()
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        data.setdefault("renderer", "Any")
        data.setdefault("dcc", "Universal")
        data.setdefault("version", "v001")
        data.setdefault("has_rig", 0)
        data.setdefault("has_textures", 0)
        data.setdefault("has_materials", 0)

        cols = [
            "name", "category", "subcategory", "filepath", "filetype",
            "renderer", "dcc", "has_rig", "has_textures", "has_materials",
            "version", "author", "thumbnail_path", "prism_path", "project",
            "polycount", "created_at", "updated_at",
        ]
        values = [data.get(c) for c in cols]
        placeholders = ",".join("?" * len(cols))
        cur = self.conn.execute(
            "INSERT INTO assets (%s) VALUES (%s)" % (",".join(cols), placeholders),
            values,
        )
        self.conn.commit()
        return cur.lastrowid

    def update_asset(self, asset_id, data):
        data["updated_at"] = _now()
        sets = ", ".join("%s = ?" % k for k in data)
        params = list(data.values()) + [asset_id]
        self.conn.execute("UPDATE assets SET %s WHERE id = ?" % sets, params)
        self.conn.commit()

    def omit_asset(self, asset_id):
        self.conn.execute("UPDATE assets SET omitted = 1 WHERE id = ?", (asset_id,))
        self.conn.commit()

    def restore_asset(self, asset_id):
        self.conn.execute("UPDATE assets SET omitted = 0 WHERE id = ?", (asset_id,))
        self.conn.commit()

    def get_omitted_assets(self):
        rows = self.conn.execute(
            "SELECT id, name, category, subcategory FROM assets WHERE omitted = 1 ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_asset(self, asset_id):
        self.conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
        self.conn.commit()

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def get_all_tags(self):
        rows = self.conn.execute("SELECT name FROM tags ORDER BY name").fetchall()
        return [r[0] for r in rows]

    def get_asset_tags(self, asset_id):
        rows = self.conn.execute(
            "SELECT t.name FROM tags t JOIN asset_tags at_ ON at_.tag_id = t.id "
            "WHERE at_.asset_id = ? ORDER BY t.name",
            (asset_id,),
        ).fetchall()
        return [r[0] for r in rows]

    def set_asset_tags(self, asset_id, tag_names):
        self.conn.execute("DELETE FROM asset_tags WHERE asset_id = ?", (asset_id,))
        for name in tag_names:
            self.conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            tag_id = self.conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()[0]
            self.conn.execute(
                "INSERT OR IGNORE INTO asset_tags (asset_id, tag_id) VALUES (?, ?)",
                (asset_id, tag_id),
            )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Favorites
    # ------------------------------------------------------------------

    def toggle_favorite(self, asset_id, username):
        existing = self.conn.execute(
            "SELECT 1 FROM favorites WHERE asset_id = ? AND username = ?",
            (asset_id, username),
        ).fetchone()
        if existing:
            self.conn.execute(
                "DELETE FROM favorites WHERE asset_id = ? AND username = ?",
                (asset_id, username),
            )
            self.conn.commit()
            return False
        else:
            self.conn.execute(
                "INSERT INTO favorites (asset_id, username, created_at) VALUES (?, ?, ?)",
                (asset_id, username, _now()),
            )
            self.conn.commit()
            return True

    def is_favorite(self, asset_id, username):
        row = self.conn.execute(
            "SELECT 1 FROM favorites WHERE asset_id = ? AND username = ?",
            (asset_id, username),
        ).fetchone()
        return row is not None

    def get_favorites(self, username):
        rows = self.conn.execute(
            "SELECT a.* FROM assets a JOIN favorites f ON f.asset_id = a.id "
            "WHERE f.username = ? ORDER BY f.created_at DESC",
            (username,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Recently used
    # ------------------------------------------------------------------

    def add_recent(self, asset_id, username):
        self.conn.execute(
            "INSERT INTO recently_used (asset_id, username, used_at) VALUES (?, ?, ?) "
            "ON CONFLICT(asset_id, username) DO UPDATE SET used_at = excluded.used_at",
            (asset_id, username, _now()),
        )
        self.conn.commit()

    def get_recents(self, username, limit=20):
        rows = self.conn.execute(
            "SELECT a.* FROM assets a JOIN recently_used r ON r.asset_id = a.id "
            "WHERE r.username = ? ORDER BY r.used_at DESC LIMIT ?",
            (username, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Versions
    # ------------------------------------------------------------------

    def get_versions(self, asset_id):
        rows = self.conn.execute(
            "SELECT * FROM versions WHERE asset_id = ? ORDER BY version DESC",
            (asset_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_version(self, asset_id, version, filetype=None):
        if filetype:
            row = self.conn.execute(
                "SELECT * FROM versions WHERE asset_id = ? AND version = ? AND filetype = ?",
                (asset_id, version, filetype),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM versions WHERE asset_id = ? AND version = ? ORDER BY id LIMIT 1",
                (asset_id, version),
            ).fetchone()
        return dict(row) if row else None

    def upsert_version(self, asset_id, version, filepath, filetype, prism_path=None,
                       renderer=None, dcc=None,
                       has_rig=0, has_textures=0, has_materials=0,
                       thumbnail_path=None):
        now = _now()
        self.conn.execute(
            "INSERT INTO versions (asset_id, version, filepath, filetype, prism_path,"
            " renderer, dcc, has_rig, has_textures, has_materials, thumbnail_path, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(asset_id, version, filetype) DO UPDATE SET "
            "filepath = excluded.filepath, prism_path = excluded.prism_path,"
            " renderer = excluded.renderer, dcc = excluded.dcc,"
            " has_rig = excluded.has_rig, has_textures = excluded.has_textures,"
            " has_materials = excluded.has_materials,"
            " thumbnail_path = excluded.thumbnail_path",
            (asset_id, version, filepath, filetype, prism_path,
             renderer or "Any", dcc or "Universal",
             int(has_rig), int(has_textures), int(has_materials),
             thumbnail_path, now),
        )
        self.conn.commit()

    def update_version(self, version_id, data):
        """Update version metadata columns by version row id."""
        now = _now()
        allowed = {"renderer", "dcc", "has_rig", "has_textures",
                   "has_materials", "thumbnail_path", "filepath", "filetype"}
        filtered = {k: v for k, v in data.items() if k in allowed}
        if not filtered:
            return
        sets = ", ".join("%s = ?" % k for k in filtered)
        params = list(filtered.values()) + [version_id]
        self.conn.execute("UPDATE versions SET %s WHERE id = ?" % sets, params)
        self.conn.commit()

    def delete_version(self, asset_id, version, filetype=None):
        if filetype:
            self.conn.execute(
                "DELETE FROM versions WHERE asset_id = ? AND version = ? AND filetype = ?",
                (asset_id, version, filetype),
            )
        else:
            self.conn.execute(
                "DELETE FROM versions WHERE asset_id = ? AND version = ?",
                (asset_id, version),
            )
        self.conn.commit()

    def get_version_by_id(self, version_id):
        row = self.conn.execute(
            "SELECT * FROM versions WHERE id = ?", (version_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_latest_version(self, asset_id):
        row = self.conn.execute(
            "SELECT * FROM versions WHERE asset_id = ? ORDER BY rowid DESC LIMIT 1",
            (asset_id,),
        ).fetchone()
        return dict(row) if row else None

    def next_version_number(self, asset_id):
        """Return the next version string (e.g. 'v002') for an asset."""
        row = self.conn.execute(
            "SELECT version FROM versions WHERE asset_id = ? ORDER BY version DESC LIMIT 1",
            (asset_id,),
        ).fetchone()
        if row is None:
            return "v001"
        try:
            num = int(row[0].lstrip("v").lstrip("0") or "0")
            return "v%03d" % (num + 1)
        except (ValueError, AttributeError):
            return "v001"

    def get_filetypes_for_asset(self, asset_id):
        rows = self.conn.execute(
            "SELECT DISTINCT filetype FROM versions WHERE asset_id = ? ORDER BY filetype",
            (asset_id,),
        ).fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # Category counts
    # ------------------------------------------------------------------

    def batch_get_asset_tags(self, asset_ids):
        if not asset_ids:
            return {}
        ph = ",".join("?" * len(asset_ids))
        rows = self.conn.execute(
            "SELECT at_.asset_id, t.name FROM asset_tags at_ "
            "JOIN tags t ON t.id = at_.tag_id "
            "WHERE at_.asset_id IN (%s) ORDER BY t.name" % ph,
            asset_ids,
        ).fetchall()
        out = {aid: [] for aid in asset_ids}
        for r in rows:
            out[r[0]].append(r[1])
        return out

    def batch_get_favorites(self, asset_ids, username):
        if not asset_ids:
            return set()
        ph = ",".join("?" * len(asset_ids))
        rows = self.conn.execute(
            "SELECT asset_id FROM favorites WHERE username = ? AND asset_id IN (%s)" % ph,
            [username] + list(asset_ids),
        ).fetchall()
        return {r[0] for r in rows}

    def batch_get_versions(self, asset_ids):
        if not asset_ids:
            return {}
        ph = ",".join("?" * len(asset_ids))
        rows = self.conn.execute(
            "SELECT * FROM versions WHERE asset_id IN (%s) ORDER BY version DESC" % ph,
            asset_ids,
        ).fetchall()
        out = {aid: [] for aid in asset_ids}
        for r in rows:
            out[r["asset_id"]].append(dict(r))
        return out

    def batch_get_filetypes(self, asset_ids):
        if not asset_ids:
            return {}
        ph = ",".join("?" * len(asset_ids))
        rows = self.conn.execute(
            "SELECT asset_id, filetype FROM versions WHERE asset_id IN (%s) GROUP BY asset_id, filetype ORDER BY filetype" % ph,
            asset_ids,
        ).fetchall()
        out = {aid: [] for aid in asset_ids}
        for r in rows:
            out[r[0]].append(r[1])
        return out

    def get_category_counts(self, username=None):
        rows = self.conn.execute(
            "SELECT category, subcategory, COUNT(*) as cnt FROM assets GROUP BY category, subcategory"
        ).fetchall()

        counts = {}
        for r in rows:
            cat, sub, cnt = r["category"], r["subcategory"], r["cnt"]
            counts[cat] = counts.get(cat, 0) + cnt
            if sub:
                counts["%s/%s" % (cat, sub)] = cnt

        counts["All"] = self.conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]

        if username:
            counts["favorites"] = self.conn.execute(
                "SELECT COUNT(*) FROM favorites WHERE username = ?", (username,)
            ).fetchone()[0]
            counts["recent"] = self.conn.execute(
                "SELECT COUNT(*) FROM recently_used WHERE username = ?", (username,)
            ).fetchone()[0]

        return counts
