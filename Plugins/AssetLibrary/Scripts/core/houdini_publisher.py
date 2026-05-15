"""
HDA PythonModule for the AssetPublisher HDA.

This file is embedded into asset_publisher.hda by build_hda.py.
Re-run build_hda.py to update the HDA after changing this file.

Assumes Prism has added the Scripts/ directory to sys.path (which it does
automatically when Houdini loads with the AssetLibrary plugin active).
Button callbacks in the HDA call these functions via hou.phm().<fn>(kwargs).
"""

import os
import sys


# ------------------------------------------------------------------
# Dynamic menu helpers — category and subcategory dropdowns
# ------------------------------------------------------------------

def category_menu_items(node):
    try:
        cats = _get_categories(node)
        return [x for cat in cats for x in (cat, cat)]
    except Exception:
        return []


def asset_name_menu_items(node):
    try:
        cat  = node.parm("category").evalAsString().strip()
        sub  = node.parm("subcategory").evalAsString().strip()
        names = _get_asset_names(node, cat, sub)
        return [x for name in names for x in (name, name)]
    except Exception:
        return []


def new_asset_name_action(node, **kwargs):
    import hou
    result = hou.ui.readInput(
        "Enter new asset name:",
        initial_contents=node.parm("asset_name").evalAsString().strip(),
        title="New Asset",
    )
    if result[0] == 0 and result[1].strip():
        node.parm("asset_name").set(result[1].strip())
        _refresh_version_label(node)


def _get_asset_names(node, category, subcategory):
    names = []
    try:
        lib_root = node.parm("lib_root").evalAsString().strip()
        if lib_root:
            from core.db import AssetDB
            db = AssetDB(os.path.join(lib_root, "library.db"))
            db.connect()
            try:
                if subcategory:
                    rows = db.conn.execute(
                        "SELECT DISTINCT name FROM assets "
                        "WHERE category=? AND subcategory=? AND name IS NOT NULL ORDER BY name",
                        (category, subcategory),
                    ).fetchall()
                else:
                    rows = db.conn.execute(
                        "SELECT DISTINCT name FROM assets "
                        "WHERE category=? AND name IS NOT NULL ORDER BY name",
                        (category,),
                    ).fetchall()
                names = [r[0] for r in rows if r[0]]
            finally:
                db.close()
    except Exception:
        pass
    current = node.parm("asset_name").evalAsString().strip()
    if current and current not in names:
        names.insert(0, current)
    return names


def subcategory_menu_items(node):
    try:
        cat  = node.parm("category").evalAsString().strip()
        subs = _get_subcategories(node, cat)
        return [x for sub in subs for x in (sub, sub)]
    except Exception:
        return []


def _get_categories(node):
    from core.dcc_bridge import SUBCATEGORIES
    cats = list(SUBCATEGORIES.keys())
    try:
        lib_root = node.parm("lib_root").evalAsString().strip()
        if lib_root:
            db_path = os.path.join(lib_root, "library.db")
            from core.db import AssetDB
            db = AssetDB(db_path)
            db.connect()
            try:
                rows = db.conn.execute(
                    "SELECT DISTINCT category FROM assets WHERE category IS NOT NULL ORDER BY category"
                ).fetchall()
                for row in rows:
                    if row[0] and row[0] not in cats:
                        cats.append(row[0])
            finally:
                db.close()
    except Exception:
        pass
    return cats


def _get_subcategories(node, category):
    from core.dcc_bridge import SUBCATEGORIES
    if category:
        subs = list(SUBCATEGORIES.get(category, []))
    else:
        subs = [s for v in SUBCATEGORIES.values() for s in v]

    # Always show the current value so custom entries are visible
    current = node.parm("subcategory").unexpandedString().strip()
    if current and current not in subs:
        subs.insert(0, current)

    try:
        lib_root = node.parm("lib_root").evalAsString().strip()
        if lib_root:
            db_path = os.path.join(lib_root, "library.db")
            from core.db import AssetDB
            db = AssetDB(db_path)
            db.connect()
            try:
                rows = db.conn.execute(
                    "SELECT DISTINCT subcategory FROM assets "
                    "WHERE category = ? AND subcategory IS NOT NULL ORDER BY subcategory",
                    (category,)
                ).fetchall()
                for row in rows:
                    if row[0] and row[0] not in subs:
                        subs.append(row[0])
            finally:
                db.close()
    except Exception:
        pass
    return subs


# ------------------------------------------------------------------
# HDA lifecycle callbacks
# ------------------------------------------------------------------

def on_created(node, **kwargs):
    """Auto-fill lib_root and author when the HDA is first placed."""
    lib_root = os.environ.get("ASSET_LIB", "")
    if lib_root:
        node.parm("lib_root").set(lib_root)

    author = _get_author(node)
    if author:
        node.parm("author").set(author)

    project = _get_project(node)
    if project:
        node.parm("project").set(project)

    node.parm("category").set("Models")

    _setup_turntable_rotation(node)
    _refresh_version_label(node)


def on_loaded(node, **kwargs):
    """Refresh the version label whenever the HDA is loaded."""
    _setup_turntable_rotation(node)
    _refresh_version_label(node)


# ------------------------------------------------------------------
# Button actions
# ------------------------------------------------------------------

def refresh_version_action(node, **kwargs):
    _refresh_version_label(node)


def new_subcategory_action(node, **kwargs):
    import hou
    result = hou.ui.readInput(
        "Enter new subcategory name:",
        initial_contents="",
        title="New Subcategory",
    )
    if result[0] == 0 and result[1].strip():
        node.parm("subcategory").set(result[1].strip())


def project_menu_items(node):
    try:
        projects = _get_projects(node)
        items = ["", "(none)"]
        for p in projects:
            items += [p, p]
        return items
    except Exception:
        return ["", "(none)"]


def add_tag_action(node, **kwargs):
    import hou, os

    lib_root = node.parm("lib_root").evalAsString().strip()
    all_tags = []
    if lib_root:
        try:
            from core.db import AssetDB
            db = AssetDB(os.path.join(lib_root, "library.db"))
            db.connect()
            try:
                rows = db.conn.execute(
                    "SELECT name FROM tags ORDER BY name"
                ).fetchall()
                all_tags = [r[0] for r in rows if r[0]]
            finally:
                db.close()
        except Exception:
            pass

    if not all_tags:
        result = hou.ui.readInput("Enter tag name:", initial_contents="", title="Add Tag")
        if result[0] == 0 and result[1].strip():
            _append_tag(node, result[1].strip())
        return

    indices = hou.ui.selectFromList(
        all_tags,
        exclusive=False,
        message="Select tags to add (Ctrl+click for multiple):",
        title="Add Tags",
        num_visible_rows=15,
    )
    for i in indices:
        _append_tag(node, all_tags[i])


def _append_tag(node, tag):
    current = node.parm("tags").evalAsString().strip()
    existing = [t.strip() for t in current.split(",") if t.strip()]
    if tag not in existing:
        existing.append(tag)
    node.parm("tags").set(", ".join(existing))


def new_project_action(node, **kwargs):
    import hou
    result = hou.ui.readInput(
        "Enter project name:",
        initial_contents="",
        title="Set Project",
    )
    if result[0] == 0 and result[1].strip():
        node.parm("project").set(result[1].strip())


def _get_projects(node):
    projects = []

    try:
        lib_root = node.parm("lib_root").evalAsString().strip()
        if lib_root:
            import os
            from core.db import AssetDB
            db = AssetDB(os.path.join(lib_root, "library.db"))
            db.connect()
            try:
                rows = db.conn.execute(
                    "SELECT DISTINCT project FROM assets WHERE project IS NOT NULL AND project != '' ORDER BY project"
                ).fetchall()
                for row in rows:
                    if row[0] and row[0] not in projects:
                        projects.append(row[0])
            finally:
                db.close()
    except Exception:
        pass

    # Always show current value
    current = node.parm("project").unexpandedString().strip()
    if current and current not in projects:
        projects.insert(0, current)

    return projects


def render_thumbnails_action(node, **kwargs):
    """Render material / clay / wire Redshift passes in the current scene."""
    import hou

    errors = _validate_base(node)
    if errors:
        hou.ui.displayMessage(
            "Cannot render thumbnails:\n\n" + "\n".join(errors),
            severity=hou.severityType.Error,
            title="Asset Publisher",
        )
        return

    source = node.parm("source_node").evalAsString().strip()
    if not source:
        hou.ui.displayMessage(
            "Set the Source Node path before rendering thumbnails.",
            severity=hou.severityType.Error,
            title="Asset Publisher",
        )
        return

    bridge = _make_bridge(node)
    output_dir = _preview_output_dir(node)

    passes = {
        "material": bool(node.parm("do_material").eval()),
        "clay":     bool(node.parm("do_clay").eval()),
        "wire":     bool(node.parm("do_wire").eval()),
    }
    if not any(passes.values()):
        hou.ui.displayMessage(
            "Enable at least one render pass (Material / Clay / Wire).",
            severity=hou.severityType.Warning,
            title="Asset Publisher",
        )
        return

    # lookdev_scene is embedded inside this HDA — derive path from node itself
    lookdev_path = node.path() + "/lookdev_scene"
    frame = int(hou.frame())

    try:
        results = bridge.render_thumbnails(source, output_dir, lookdev_path, frame, passes)
    except Exception as exc:
        hou.ui.displayMessage(
            "Render failed:\n\n%s" % exc,
            severity=hou.severityType.Error,
            title="Asset Publisher",
        )
        return

    # Cache the rendered paths on the node so publish_action can use them
    node.setCachedUserData("thumb_results", results)

    succeeded = [k for k, v in results.items() if v]
    failed    = [k for k, v in results.items() if passes.get(k) and not v]

    msg = "Thumbnails rendered:\n"
    for k in succeeded:
        msg += "\n  ✓ %s  →  %s" % (k, results[k])
    if failed:
        msg += "\n\nFailed passes: %s" % ", ".join(failed)
        msg += "\n(Check the Houdini console for details.)"

    hou.ui.displayMessage(
        msg,
        severity=hou.severityType.Message if not failed else hou.severityType.Warning,
        title="Asset Publisher",
    )


def publish_action(node, **kwargs):
    """Export geometry + textures and publish to the Asset Library."""
    import hou

    errors = _validate_base(node)
    if errors:
        hou.ui.displayMessage(
            "Cannot publish:\n\n" + "\n".join(errors),
            severity=hou.severityType.Error,
            title="Asset Publisher",
        )
        return

    source = node.parm("source_node").evalAsString().strip()
    if not source:
        hou.ui.displayMessage(
            "Set the Source Node path before publishing.",
            severity=hou.severityType.Error,
            title="Asset Publisher",
        )
        return

    bridge = _make_bridge(node)
    data   = _collect_data(node)
    fmt    = node.parm("export_format").evalAsString().lower()

    # Use a temp directory for exported files; importer copies them to NAS
    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="asset_pub_")

    try:
        # 1. Export geometry
        try:
            exported = bridge.export_geometry(source, tmp_dir, fmt)
        except Exception as exc:
            hou.ui.displayMessage(
                "Export failed:\n\n%s" % exc,
                severity=hou.severityType.Error,
                title="Asset Publisher",
            )
            return

        # 2. Export textures (optional)
        texture_files = []
        if node.parm("export_textures").eval():
            try:
                texture_files = bridge.export_textures(source, tmp_dir)
            except Exception as exc:
                hou.ui.displayMessage(
                    "Texture export failed:\n\n%s\n\nContinuing without textures." % exc,
                    severity=hou.severityType.Warning,
                    title="Asset Publisher",
                )

        # 3. Use previously rendered thumbnails (or empty dict)
        thumb_paths = node.cachedUserData("thumb_results") or {}

        # 4. Publish
        try:
            result = bridge.publish(data, exported, thumb_paths, texture_files)
        except Exception as exc:
            hou.ui.displayMessage(
                "Publish failed:\n\n%s" % exc,
                severity=hou.severityType.Error,
                title="Asset Publisher",
            )
            return

    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if result.success:
        _refresh_version_label(node)

        # Submit turntable renders to Deadline
        passes_enabled = {
            "material": bool(node.parm("do_material").eval()),
            "clay":     bool(node.parm("do_clay").eval()),
            "wire":     bool(node.parm("do_wire").eval()),
        }
        deadline_msg = ""
        if any(passes_enabled.values()):
            steps        = node.parm("ld_steps").eval()
            lookdev_path = node.path() + "/lookdev_scene"
            try:
                job_ids = bridge.submit_turntable_to_deadline(
                    source, lookdev_path, steps, passes_enabled, data["name"]
                )
                submitted = {k: v for k, v in job_ids.items() if v}
                if submitted:
                    deadline_msg = "\n\nDeadline turntable jobs:\n" + "\n".join(
                        "  %s: %s" % (k, v) for k, v in submitted.items()
                    )
                else:
                    deadline_msg = "\n\nTurntable submission failed — check Houdini console."
            except Exception as exc:
                deadline_msg = "\n\nTurntable submission failed:\n%s" % exc

        hou.ui.displayMessage(
            "Published successfully!\n\nAsset ID: %d\nPath: %s%s" % (
                result.asset_id, result.nas_path, deadline_msg
            ),
            severity=hou.severityType.Message,
            title="Asset Publisher",
        )
    else:
        hou.ui.displayMessage(
            "Publish failed [%s]:\n\n%s" % (result.error_type, result.error),
            severity=hou.severityType.Error,
            title="Asset Publisher",
        )


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------

def _make_bridge(node):
    from core.dcc_bridge import HoudiniBridge
    lib_root = node.parm("lib_root").evalAsString().strip()
    db_path  = os.path.join(lib_root, "library.db")
    return HoudiniBridge(lib_root, db_path)


def _collect_data(node):
    """Build the data dict expected by HoudiniBridge.publish()."""
    tags_raw = node.parm("tags").evalAsString()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    return {
        "name":          node.parm("asset_name").evalAsString().strip(),
        "category":      node.parm("category").evalAsString(),
        "subcategory":   node.parm("subcategory").evalAsString().strip(),
        "renderer":      node.parm("renderer").evalAsString(),
        "dcc":           node.parm("dcc").evalAsString(),
        "has_rig":       int(node.parm("has_rig").eval()),
        "has_materials": int(node.parm("has_materials").eval()),
        "has_textures":  0,  # importer sets this based on texture_files
        "author":        node.parm("author").evalAsString().strip(),
        "project":       node.parm("project").evalAsString().strip(),
        "tags":          tags,
    }


def _validate_base(node):
    errors = []
    if not node.parm("asset_name").evalAsString().strip():
        errors.append("Asset Name is required.")
    if not node.parm("lib_root").evalAsString().strip():
        errors.append("Library Root is not set. Check $ASSET_LIB.")
    return errors


def _preview_output_dir(node):
    """Temp output dir for pre-publish thumbnail renders."""
    import tempfile
    return tempfile.mkdtemp(prefix="asset_pub_thumbs_")


def _refresh_version_label(node):
    try:
        bridge = _make_bridge(node)
        cat    = node.parm("category").evalAsString()
        sub    = node.parm("subcategory").evalAsString().strip()
        name   = node.parm("asset_name").evalAsString().strip()
        if name:
            ver = bridge.get_next_version(cat, sub, name)
            node.parm("version_label").set("Next: %s" % ver)
        else:
            node.parm("version_label").set("(fill asset name first)")
    except Exception:
        pass


def _prism_core():
    try:
        import PrismInit
        return PrismInit.pcore
    except Exception:
        return None


def _get_author(node):
    try:
        core = _prism_core()
        if core:
            return core.username
    except Exception:
        pass
    return os.environ.get("USERNAME") or os.environ.get("USER") or ""


def _get_project(node):
    try:
        core = _prism_core()
        if core:
            return core.projectName
    except Exception:
        pass
    return ""


def _setup_turntable_rotation(node):
    """Wire main_rotation.ry inside lookdev_scene to ld_steps so turntable works.

    Called on_created and on_loaded because inner-HDA expressions don't survive
    the createDigitalAsset roundtrip — they must be set on the live instance.
    Works for frame ranges 1-N and 1001-(1000+N).
    """
    try:
        import hou
        ld = node.node("lookdev_scene")
        if ld is None:
            return
        ld.allowEditingOfContents()
        rot = ld.node("main_rotation")
        if rot is None:
            return
        rot.parm("ry").deleteAllKeyframes()
        rot.parm("ry").setExpression(
            "($F - 1) % 1000 / max(ch('../../ld_steps'), 1) * 360.0",
            hou.exprLanguage.Hscript,
        )
    except Exception:
        pass
