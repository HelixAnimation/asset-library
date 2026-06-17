"""
HoudiniBridge — geometry export, texture copy, Redshift thumbnail render,
and asset publish orchestration for the Asset Library Houdini HDA.

Requires:
  - Houdini (hou module) at runtime
  - Redshift installed and loaded for thumbnail rendering
  - Prism loaded (so core.db / core.importer are on sys.path)
"""

import glob
import logging
import os
import shutil
import sys

logger = logging.getLogger(__name__)

SUBCATEGORIES = {
    "Models":    ["Anatomy", "Organs", "Props", "Environments"],
    "Materials": ["Skin", "Metal", "Glass", "Fabric", "Organic", "Fluid", "GPU Open"],
    "HDAs":      ["Rigging", "FX", "Modeling"],
    "Textures":  ["Skin", "Metal", "Glass", "Fabric", "Organic"],
    "Lighting":  ["HDRIs", "Light rigs", "Poly Haven"],
}

# Parm names on RS texture / file VOP nodes that hold texture file paths
_TEX_PARM_NAMES = frozenset({"filename", "tex0", "tex1", "tex2", "map", "image", "texture"})


class HoudiniBridge:
    def __init__(self, lib_root, db_path):
        self.lib_root = lib_root
        self.db_path = db_path

    # ------------------------------------------------------------------
    # Version query
    # ------------------------------------------------------------------

    def get_next_version(self, category, subcategory, name):
        """Return the next version string for this asset, e.g. 'v002'."""
        _ensure_on_path()
        from core.db import AssetDB

        prism_path = _build_prism_path(category, subcategory, name)
        db = AssetDB(self.db_path)
        db.connect()
        try:
            row = db.conn.execute(
                "SELECT id FROM assets WHERE prism_path = ?", (prism_path,)
            ).fetchone()
            if row:
                return db.next_version_number(row[0])
            return "v001"
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Geometry export
    # ------------------------------------------------------------------

    def export_geometry(self, source_node_path, output_dir, fmt):
        """Export the node at source_node_path to output_dir.

        fmt: "usd" | "abc" | "obj" | "fbx" | "hda" | "hip"
        Returns list of exported absolute file paths.
        """
        import hou

        os.makedirs(output_dir, exist_ok=True)
        node = hou.node(source_node_path)
        if node is None:
            raise ValueError("Source node not found: %s" % source_node_path)

        fmt = fmt.lower().lstrip(".")
        base_name = node.name().replace(" ", "_")

        # If OBJ-level node, drill into its display SOP
        if isinstance(node, hou.ObjNode):
            sop = node.displayNode()
            if sop is None:
                raise ValueError("OBJ node %s has no display SOP" % node.path())
            node = sop

        output_path = os.path.join(output_dir, "%s.%s" % (base_name, fmt))

        if fmt == "hda":
            defn = node.type().definition()
            if defn is None:
                raise ValueError("Node %s is not an HDA" % node.path())
            defn.save(output_path)

        elif fmt == "hip":
            hou.hipFile.save(output_path)

        else:
            # USD, ABC, OBJ, FBX, BGEO — all handled by Houdini's geo I/O
            geo = node.geometry()
            if geo is None:
                raise ValueError("Node %s has no geometry output" % node.path())
            geo.saveToFile(output_path)

        return [output_path]

    # ------------------------------------------------------------------
    # Texture export
    # ------------------------------------------------------------------

    def export_textures(self, source_node_path, output_dir):
        """Walk material network from source_node_path and copy texture files.

        Returns list of copied absolute file paths.
        """
        import hou

        node = hou.node(source_node_path)
        if node is None:
            return []

        tex_dir = os.path.join(output_dir, "textures")
        os.makedirs(tex_dir, exist_ok=True)

        texture_paths = set()
        _collect_textures(node, texture_paths)

        copied = []
        for src in sorted(texture_paths):
            dst = os.path.join(tex_dir, os.path.basename(src))
            try:
                shutil.copy2(src, dst)
                copied.append(dst)
            except OSError as exc:
                logger.warning("Could not copy texture %s: %s", src, exc)

        return copied

    # ------------------------------------------------------------------
    # Thumbnail rendering
    # ------------------------------------------------------------------

    def render_thumbnails(self, source_node_path, output_dir, lookdev_path, frame, passes):
        """Render material/clay/wire passes via dedicated ROPs.

        passes: dict {"material": bool, "clay": bool, "wire": bool}
        Returns: dict {"material": str|None, "clay": str|None, "wire": str|None}
        """
        import hou

        thumb_dir = os.path.join(output_dir, "thumbs")
        os.makedirs(thumb_dir, exist_ok=True)

        lookdev_node = hou.node(lookdev_path)
        if lookdev_node is None:
            raise ValueError("lookdev_scene not found at: %s" % lookdev_path)

        pub = lookdev_node.parent()
        pub.allowEditingOfContents()
        pub.parm("thumb_output_dir").set(thumb_dir.replace("\\", "/"))

        resolution = pub.parm("thumb_res").eval() if pub.parm("thumb_res") else 1024

        rop_map = {
            "material": pub.node("ropnet1/rs_thumb"),
            "clay":     pub.node("ropnet1/rs_clay"),
            "wire":     pub.node("ropnet1/rs_wire"),
        }

        results = {}
        for pass_name in ("material", "clay", "wire"):
            if not passes.get(pass_name):
                results[pass_name] = None
                continue

            rop = rop_map[pass_name]
            if rop is None:
                logger.warning("ROP not found for pass: %s", pass_name)
                results[pass_name] = None
                continue

            rop.parm("RS_overrideRes1").set(resolution)
            rop.parm("RS_overrideRes2").set(resolution)
            prefix = os.path.join(thumb_dir, pass_name).replace("\\", "/")
            p_out = rop.parm("RS_outputFileNamePrefix")
            p_out.deleteAllKeyframes()
            p_out.set(prefix)
            rop.render()

            prefix = os.path.join(thumb_dir, pass_name).replace("\\", "/")
            out_jpg = os.path.join(thumb_dir, "%s.jpg" % pass_name)
            results[pass_name] = _find_rendered_output(prefix, out_jpg)

        return results

    # ------------------------------------------------------------------
    # Turntable Deadline submission (per-HIP via Prism)
    # ------------------------------------------------------------------

    def submit_turntable_to_deadline(self, source_node_path, lookdev_path, steps, passes, asset_name, thumbs_dir, priority=5, frames_per_task=6):
        """Submit one Deadline job per enabled pass using the dedicated per-pass ROPs.

        passes: dict {"material": bool, "clay": bool, "wire": bool}
        thumbs_dir: absolute path to the version's thumbs folder
        Returns dict {"material": job_id|None, ...}
        """
        import hou

        lookdev_node = hou.node(lookdev_path)
        if lookdev_node is None:
            raise ValueError("lookdev_scene not found: %s" % lookdev_path)

        pub = lookdev_node.parent()
        pub.allowEditingOfContents()

        os.makedirs(thumbs_dir, exist_ok=True)
        pub.parm("thumb_output_dir").set(thumbs_dir.replace("\\", "/"))
        pub.parm("pass_name").set("material")

        resolution = pub.parm("thumb_res").eval() if pub.parm("thumb_res") else 1024

        rop_map = {
            "material": pub.node("ropnet1/rs_thumb"),
            "clay":     pub.node("ropnet1/rs_clay"),
            "wire":     pub.node("ropnet1/rs_wire"),
        }

        # Normalize the HDA state before saving per-pass HIPs for Deadline.
        # The render loop below sets explicit prefixes per pass on the saved copy.
        _thumb_base = thumbs_dir.replace("\\", "/")
        _pass_rop = (("material", "rs_thumb"), ("clay", "rs_clay"), ("wire", "rs_wire"))
        for _pass, _rop_name in _pass_rop:
            _rop = pub.node("ropnet1/" + _rop_name)
            if _rop:
                _p = _rop.parm("RS_outputFileNamePrefix")
                _p.deleteAllKeyframes()
                _p.set("%s/%s.$F4" % (_thumb_base, _pass))

        frame_spec   = "1001-%d" % (1000 + steps)
        original_hip = hou.hipFile.path()
        job_ids      = {}
        version_dir  = os.path.dirname(thumbs_dir)
        jobs_dir     = os.path.join(version_dir, "source")
        os.makedirs(jobs_dir, exist_ok=True)

        # Save one shared HIP — all three ROPs are already baked into it
        hip_path = os.path.join(jobs_dir, "turntable.hip")
        hou.hipFile.save(hip_path)

        for pass_name in ("material", "clay", "wire"):
            if not passes.get(pass_name):
                job_ids[pass_name] = None
                continue
            rop = rop_map[pass_name]
            if rop is None:
                logger.error("ROP not found for pass: %s", pass_name)
                job_ids[pass_name] = None
                continue
            try:
                job_id = _submit_via_prism_deadline(
                    hip_path=hip_path,
                    rop_path=rop.path(),
                    frame_spec=frame_spec,
                    name="%s_turntable_%s" % (asset_name, pass_name),
                    priority=priority,
                    frames_per_task=frames_per_task,
                )
                job_ids[pass_name] = job_id
            except Exception as exc:
                logger.error("Turntable submission failed for pass %s: %s", pass_name, exc)
                job_ids[pass_name] = None

        if original_hip and os.path.isfile(original_hip):
            hou.hipFile.save(original_hip)

        return job_ids

    # ------------------------------------------------------------------
    # Publish (delegates to AssetImporter)
    # ------------------------------------------------------------------

    def export_material_manifest(self, source_node_path, version_dir, texture_files):
        """Write materials.json to version_dir. Returns path or None."""
        import hou
        node = hou.node(source_node_path)
        if node is None:
            return None
        return _export_material_manifest(node, version_dir, texture_files)

    def export_rs_object_props(self, source_node_path, version_dir):
        """Write rs_object_props.json with Redshift OBJ-level parms (tessellation,
        displacement, motion blur, visibility, etc.). Returns path or None.
        """
        import hou
        node = hou.node(source_node_path)
        if node is None:
            return None
        return _export_rs_object_props(node, version_dir)

    def get_polycount(self, source_node_path):
        """Return primitive count from the display SOP of source_node_path, or None."""
        import hou
        node = hou.node(source_node_path)
        if node is None:
            return None
        try:
            sop = node.displayNode() if hasattr(node, "displayNode") else node
            if sop is None:
                return None
            geo = sop.geometry()
            if geo is None:
                return None
            return int(geo.intrinsicValue("primitivecount"))
        except Exception as exc:
            logger.warning("Could not get polycount from %s: %s", source_node_path, exc)
            return None

    def publish(self, data, exported_files, thumb_paths, texture_files):
        """Run the full AssetImporter pipeline.

        data: dict with keys: name, category, subcategory, renderer, dcc,
              has_rig, has_materials, tags (list), author, project
        exported_files: list of absolute file paths to import
        thumb_paths: dict {"material": path|None, "clay": path|None, "wire": path|None}
        texture_files: list of absolute texture file paths

        Returns ImportResult (from core.importer).
        """
        _ensure_on_path()
        from core.db import AssetDB
        from core.importer import AssetImporter

        thumbnails = {}
        for k in ("material", "clay", "wire"):
            p = thumb_paths.get(k)
            thumbnails[k] = [p] if p else []

        import_data = {k: v for k, v in data.items() if not k.startswith("_")}
        import_data["filepaths"] = exported_files

        db = AssetDB(self.db_path)
        db.connect()
        try:
            importer = AssetImporter(self.lib_root, db)
            return importer.import_asset(import_data, thumbnails, texture_files or [])
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Import / Load into scene
    # ------------------------------------------------------------------

    def import_asset(self, filepath, version_dir, asset_name, mode="import"):
        """Load a published asset into the current Houdini scene.

        Creates a geo node with a file or alembic SOP, then reconstructs
        Redshift materials from materials.json if present.

        mode: "import"    — geometry SOP reads directly from NAS
              "reference" — alembic SOP uses packed alembic (non-destructive)
        """
        import hou, json

        if not os.path.isfile(filepath):
            raise ValueError("Asset file not found: %s" % filepath)

        fp_fwd = filepath.replace("\\", "/")

        if filepath.lower().endswith(".bgeo.sc"):
            ext = "bgeo.sc"
        else:
            ext = os.path.splitext(filepath)[1].lstrip(".").lower()

        safe_name = asset_name.replace(" ", "_").replace("-", "_")
        version   = os.path.basename(version_dir) if version_dir else ""
        geo_name  = ("%s_%s" % (safe_name, version)) if version else safe_name

        obj = hou.node("/obj")
        geo = obj.createNode("geo", geo_name)
        geo.moveToGoodPosition()

        # Remove the default file SOP Houdini adds inside new geo nodes
        for child in list(geo.children()):
            child.destroy()

        if ext == "abc":
            sop = geo.createNode("alembic", "alembic_load")
            sop.parm("fileName").set(fp_fwd)
            if mode == "reference":
                sop.parm("loadmode").set("alembic")   # Alembic Delayed Load (packed)
            else:
                sop.parm("loadmode").set("unpack")    # Unpack → actual polygons + prim attribs
        else:
            sop = geo.createNode("file", "file_load")
            sop.parm("file").set(fp_fwd)

        sop.setDisplayFlag(True)
        sop.setRenderFlag(True)

        # Apply Redshift object-level properties (tessellation, displacement, etc.)
        rs_props_json = os.path.join(version_dir, "rs_object_props.json") if version_dir else ""
        if rs_props_json and os.path.isfile(rs_props_json):
            try:
                with open(rs_props_json) as f:
                    rs_props = json.load(f)
                for parm_name, parm_val in rs_props.items():
                    parm = geo.parm(parm_name)
                    if parm is not None:
                        try:
                            parm.set(parm_val)
                        except Exception:
                            pass
            except Exception as exc:
                logger.warning("Could not apply RS object props: %s", exc)

        mat_json = os.path.join(version_dir, "materials.json") if version_dir else ""
        if mat_json and os.path.isfile(mat_json):
            try:
                with open(mat_json) as f:
                    manifest = json.load(f)

                assignments = manifest.get("assignments", {})
                if assignments:
                    # Local matnet inside the geo node keeps everything self-contained
                    local_matnet = geo.createNode("matnet", "materials")
                    _reconstruct_materials(manifest, version_dir, local_matnet)

                    # Remap shop_materialpath from original paths to local matnet
                    matnet_path = local_matnet.path()
                    lines = ['string mat = prim(0, "shop_materialpath", @primnum);']
                    for short_name, orig_path in assignments.items():
                        lines.append(
                            'if (mat == "%s") setprimattrib(0, "shop_materialpath",'
                            ' @primnum, "%s/%s");' % (orig_path, matnet_path, short_name)
                        )
                    wrangle = geo.createNode("attribwrangle", "remap_materials")
                    wrangle.parm("class").set(1)   # Primitive class
                    wrangle.parm("snippet").set("\n".join(lines))
                    wrangle.setInput(0, sop)
                    wrangle.setDisplayFlag(True)
                    wrangle.setRenderFlag(True)
                    sop.setDisplayFlag(False)
                    sop.setRenderFlag(False)
            except Exception as exc:
                logger.warning("Could not reconstruct materials from %s: %s", mat_json, exc)

        return geo


# ------------------------------------------------------------------
# Module-level helpers (not part of the class)
# ------------------------------------------------------------------

def _reconstruct_materials(manifest, version_dir, mat_net):
    """Recreate RS material networks inside mat_net from a materials.json manifest.

    The first node in each material's nodes list is the root container
    (redshift_vopnet). All subsequent nodes are children inside it.
    Skips materials that already exist in mat_net.
    """
    import hou

    materials = manifest.get("materials", {})
    tex_dir   = os.path.join(version_dir, "textures") if version_dir else ""

    def _set_parms(node, parms_dict):
        for parm_name, parm_val in parms_dict.items():
            try:
                if isinstance(parm_val, list):
                    pt = node.parmTuple(parm_name)
                    if pt is not None:
                        pt.set(parm_val)
                else:
                    parm = node.parm(parm_name)
                    if parm is None:
                        continue
                    if isinstance(parm_val, str):
                        if (parm_name.lower() in _TEX_PARM_NAMES
                                and tex_dir and parm_val
                                and not os.path.isfile(parm_val)):
                            candidate = os.path.join(tex_dir, os.path.basename(parm_val))
                            if os.path.isfile(candidate):
                                parm_val = candidate.replace("\\", "/")
                    parm.set(parm_val)
            except Exception:
                pass

    for short_name, mat_data in materials.items():
        if mat_net.node(short_name) is not None:
            logger.debug("%s/%s already exists — skipping", mat_net.path(), short_name)
            continue

        nodes_data = mat_data.get("nodes", [])
        conns_data = mat_data.get("connections", [])

        if not nodes_data:
            continue

        # Index 0 is the root container (redshift_vopnet); rest are children inside it
        root_info = nodes_data[0]
        try:
            root_node = mat_net.createNode(root_info["type"], root_info["name"])
        except Exception as exc:
            logger.warning("Could not create root material %s (%s): %s",
                           root_info["name"], root_info["type"], exc)
            continue

        _set_parms(root_node, root_info.get("parms", {}))

        # Houdini auto-creates default nodes inside a new redshift_vopnet.
        # Destroy them so JSON nodes don't get renamed to *2, *3, etc.
        for auto_child in list(root_node.children()):
            auto_child.destroy()

        # Create child nodes inside the root vopnet
        created = {root_info["name"]: root_node}
        for node_info in nodes_data[1:]:
            node_name = node_info.get("name", "")
            node_type = node_info.get("type", "")
            try:
                n = root_node.createNode(node_type, node_name)
                created[node_name] = n
                _set_parms(n, node_info.get("parms", {}))
            except Exception as exc:
                logger.warning("Could not create material node %s (%s): %s",
                               node_name, node_type, exc)

        # Wire VOP connections between child nodes (skip root node connections)
        root_name = root_info["name"]
        for conn in conns_data:
            fn = conn.get("from_node", "")
            tn = conn.get("to_node", "")
            if fn == root_name or tn == root_name:
                continue
            from_node = created.get(fn)
            to_node   = created.get(tn)
            if from_node and to_node:
                try:
                    to_node.setInput(conn.get("to_input", 0), from_node)
                except Exception as exc:
                    logger.warning("Material wire failed %s→%s[%d]: %s",
                                   fn, tn, conn.get("to_input", 0), exc)

        root_node.layoutChildren()

    mat_net.layoutChildren()


def _export_rs_object_props(node, version_dir):
    """Write rs_object_props.json with all RS_objprop_* parms from an OBJ node."""
    import hou, json

    _RS_PREFIXES = ("RS_objprop_", "RS_MBLUR_", "RS_objprop_rstess_",
                    "RS_objprop_displace_", "RS_objprop_vis_")

    props = {}
    for parm in node.parms():
        name = parm.name()
        if any(name.startswith(p) for p in _RS_PREFIXES) or name.startswith("RS_"):
            try:
                props[name] = parm.eval()
            except Exception:
                pass

    if not props:
        return None

    json_path = os.path.join(version_dir, "rs_object_props.json")
    with open(json_path, "w") as f:
        json.dump(props, f, indent=2)
    return json_path


def _build_prism_path(category, subcategory, name):
    parts = [category]
    if subcategory:
        parts.append(subcategory)
    parts.append(name)
    return "/".join(parts)


def _ensure_on_path():
    """Ensure the Scripts/ directory is on sys.path so core.* imports work."""
    scripts_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)


def _collect_textures(node, out_set):
    """Find texture file paths from all materials assigned to node's geometry."""
    import hou

    visited_mats = set()

    def _walk_mat(mat_node):
        if mat_node is None or mat_node.path() in visited_mats:
            return
        visited_mats.add(mat_node.path())
        for n in [mat_node] + list(mat_node.allSubChildren()):
            for parm in n.parms():
                if parm.name().lower() in _TEX_PARM_NAMES:
                    try:
                        val = parm.evalAsString()
                        if val and os.path.isfile(val):
                            out_set.add(os.path.normpath(val))
                    except Exception:
                        pass

    mat_paths = set()

    # OBJ-level material
    obj_mat = node.parm("shop_materialpath")
    if obj_mat:
        p = obj_mat.evalAsString().strip()
        if p:
            mat_paths.add(p)

    # Prim-level material assignments from the display SOP
    try:
        sop = node.displayNode() if hasattr(node, "displayNode") else None
        if sop:
            geo = sop.geometry()
            if geo and geo.findPrimAttrib("shop_materialpath"):
                for prim in geo.prims():
                    p = prim.attribValue("shop_materialpath")
                    if p:
                        mat_paths.add(p)
    except Exception:
        pass

    for mat_path in mat_paths:
        _walk_mat(hou.node(mat_path))


def _export_material_manifest(node, version_dir, texture_files):
    """Write materials.json alongside the exported geometry.

    Captures:
    - prim-level material assignments (short name → full Houdini path)
    - full node graph per material (nodes, parm values, connections)
    - texture paths relative to version_dir

    Returns the path to the written JSON, or None on failure.
    """
    import hou, json

    _SKIP_TYPES = {
        hou.parmTemplateType.Folder,
        hou.parmTemplateType.FolderSet,
        hou.parmTemplateType.Separator,
        hou.parmTemplateType.Label,
        hou.parmTemplateType.Button,
        hou.parmTemplateType.Data,
    }

    def _capture_parms(n):
        parms = {}
        for pt in n.parmTuples():
            if pt.parmTemplate().type() in _SKIP_TYPES:
                continue
            try:
                val = pt.eval()
                parms[pt.name()] = val[0] if len(val) == 1 else list(val)
            except Exception:
                pass
        return parms

    def _capture_network(mat_node):
        nodes_out = []
        conns_out = []
        all_nodes = [mat_node] + list(mat_node.allSubChildren())
        for n in all_nodes:
            nodes_out.append({
                "name": n.name(),
                "type": n.type().name(),
                "parms": _capture_parms(n),
            })
            for idx, inp in enumerate(n.inputs()):
                if inp is not None:
                    conns_out.append({
                        "from_node": inp.name(),
                        "to_node":   n.name(),
                        "to_input":  idx,
                    })
        return {"nodes": nodes_out, "connections": conns_out}

    # --- Collect unique material paths from geometry ---
    mat_map = {}  # short_name → houdini_path

    obj_mat = node.parm("shop_materialpath")
    if obj_mat:
        p = obj_mat.evalAsString().strip()
        if p:
            mat_map[p.split("/")[-1]] = p

    try:
        sop = node.displayNode() if hasattr(node, "displayNode") else None
        if sop:
            geo = sop.geometry()
            if geo and geo.findPrimAttrib("shop_materialpath"):
                for prim in geo.prims():
                    p = prim.attribValue("shop_materialpath")
                    if p and p not in mat_map.values():
                        mat_map[p.split("/")[-1]] = p
    except Exception:
        pass

    if not mat_map:
        return None

    # --- Capture each material network ---
    materials = {}
    for short_name, mat_path in mat_map.items():
        mat_node_obj = hou.node(mat_path)
        if mat_node_obj is None:
            continue
        materials[short_name] = {
            "houdini_path": mat_path,
            **_capture_network(mat_node_obj),
        }

    # --- Texture references (relative to version_dir) ---
    textures = []
    for tex_path in texture_files:
        try:
            rel = os.path.relpath(tex_path, version_dir).replace("\\", "/")
        except ValueError:
            rel = tex_path.replace("\\", "/")
        textures.append({"name": os.path.basename(tex_path), "path": rel})

    manifest = {
        "version": 1,
        "renderer": "Redshift",
        "assignments": mat_map,
        "materials": materials,
        "textures": textures,
    }

    json_path = os.path.join(version_dir, "materials.json")
    with open(json_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return json_path


def _find_rendered_output(prefix, desired_path):
    """Locate the actual rendered file and move it to desired_path.

    Handles Redshift's frame-number suffix (prefix.0001.png, prefix.1.png, etc.).
    Returns desired_path if successful, None otherwise.
    """
    if os.path.isfile(desired_path):
        return desired_path

    # Search for any rendered file matching the prefix (Redshift appends .$F4.ext)
    for candidate in sorted(glob.glob(prefix + ".*")):
        if os.path.isfile(candidate):
            try:
                os.replace(candidate, desired_path)
                return desired_path
            except OSError:
                pass

    return None


def _create_clay_material():
    """Create a warm grey RS Standard clay material in /mat."""
    import hou
    mat_net = _ensure_mat_network()
    existing = mat_net.node("asset_pub_clay")
    if existing:
        existing.destroy()

    clay = mat_net.createNode("redshift::StandardMaterial", "asset_pub_clay")
    clay.parm("base_colorr").set(0.75)
    clay.parm("base_colorg").set(0.72)
    clay.parm("base_colorb").set(0.68)
    clay.parm("refl_roughness").set(0.9)
    clay.parm("refl_ior").set(1.45)
    return clay


def _create_wire_material():
    """Create an incandescent wireframe RS material (WireFrame VOP → emission only, no lighting)."""
    import hou
    mat_net = _ensure_mat_network()
    for name in ("asset_pub_wire", "asset_pub_wiretex"):
        n = mat_net.node(name)
        if n:
            n.destroy()

    wire = mat_net.createNode("redshift::StandardMaterial", "asset_pub_wire")
    for ch in ("r", "g", "b"):
        wire.parm("base_color%s" % ch).set(0.0)
    wire.parm("emission_weight").set(1.0)

    try:
        wire_tex = mat_net.createNode("redshift::WireFrame", "asset_pub_wiretex")
        wire.setInput(wire.inputIndex("emission_color"), wire_tex, 0)
    except Exception as exc:
        logger.warning("redshift::WireFrame VOP not available: %s", exc)

    return wire


def _ensure_mat_network():
    import hou
    mat_net = hou.node("/mat")
    if mat_net is None:
        mat_net = hou.node("/obj").createNode("matnet", "mat")
    return mat_net


def _submit_via_prism_deadline(hip_path, rop_path, frame_spec, name, priority=5, frames_per_task=6):
    """Submit a Houdini ROP job to Deadline via Prism's Deadline plugin.

    hip_path must already be the current open file (call hou.hipFile.save(hip_path) first).
    Returns the Deadline Job ID string, or raises on failure.
    """
    _ensure_on_path()

    try:
        import PrismInit
        pcore = PrismInit.pcore
    except Exception as exc:
        raise RuntimeError("Prism not available: %s" % exc)

    dl = pcore.plugins.getPlugin("Deadline")
    if dl is None:
        raise RuntimeError("Prism Deadline plugin not loaded - enable it in Prism settings")

    result = dl.submitHoudiniJob(
        jobName=name,
        frames=frame_spec,
        driver=rop_path,
        jobPrio=priority,
        jobFramesPerTask=frames_per_task,
    )

    job_id = dl.getJobIdFromSubmitResult(result)
    return job_id or str(result).strip()
