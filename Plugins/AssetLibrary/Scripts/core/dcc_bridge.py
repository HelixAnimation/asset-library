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
        """Render material/clay/wire passes using the embedded ropnet inside the HDA.

        passes: dict {"material": bool, "clay": bool, "wire": bool}
        Returns: dict {"material": str|None, "clay": str|None, "wire": str|None}

        lookdev_path: path to the lookdev_scene node embedded in AssetPublisher.
          The AssetPublisher node is derived as lookdev_path's parent.
          The internal ROP at ropnet1/rs_thumb is used for rendering — it already has
          RS_renderCamera and RS_objects_exclude wired via expressions.
        """
        import hou

        thumb_dir = os.path.join(output_dir, "thumbs")
        os.makedirs(thumb_dir, exist_ok=True)

        # Derive the AssetPublisher node and its internal pieces from lookdev_path
        lookdev_node = hou.node(lookdev_path)
        if lookdev_node is None:
            raise ValueError("lookdev_scene not found at: %s" % lookdev_path)

        pub = lookdev_node.parent()
        pub.allowEditingOfContents()

        rop = pub.node("ropnet1/rs_thumb")
        if rop is None:
            raise RuntimeError(
                "Internal ROP not found at %s/ropnet1/rs_thumb. "
                "Re-run fix_add_rop.py to rebuild the HDA." % pub.path()
            )

        preview = pub.node("asset_preview")
        if preview is None:
            raise RuntimeError("asset_preview not found inside %s" % pub.path())

        results = {}

        for pass_name in ("material", "clay", "wire"):
            if not passes.get(pass_name):
                results[pass_name] = None
                continue

            out_png = os.path.join(thumb_dir, "%s.png" % pass_name)
            prefix  = os.path.join(thumb_dir, "%s_tmp" % pass_name)

            # Set output path for this pass (clears any prior expression — that's fine)
            rop.parm("RS_outputFileNamePrefix").set(prefix)

            override_nodes = []
            orig_mat = None

            if pass_name == "clay":
                mat = _create_clay_material()
                override_nodes.append(mat)
                orig_mat = preview.parm("shop_materialpath").eval()
                preview.parm("shop_materialpath").set(mat.path())
            elif pass_name == "wire":
                mat = _create_wire_material()
                override_nodes.append(mat)
                orig_mat = preview.parm("shop_materialpath").eval()
                preview.parm("shop_materialpath").set(mat.path())

            try:
                rop.parm("execute").pressButton()
                rendered = _find_rendered_output(prefix, out_png)
                results[pass_name] = rendered
            finally:
                if orig_mat is not None:
                    preview.parm("shop_materialpath").set(orig_mat)
                for n in override_nodes:
                    try:
                        n.destroy()
                    except Exception:
                        pass

        return results

    # ------------------------------------------------------------------
    # Turntable Deadline submission
    # ------------------------------------------------------------------

    def submit_turntable_to_deadline(self, source_node_path, lookdev_path, steps, passes, asset_name, priority=25):
        """Save per-pass .hip files to NAS and submit them to Deadline at low priority.

        passes: dict {"material": bool, "clay": bool, "wire": bool}
        Returns dict {"material": job_id|None, ...}
        """
        import hou

        lookdev_node = hou.node(lookdev_path)
        if lookdev_node is None:
            raise ValueError("lookdev_scene not found: %s" % lookdev_path)

        pub = lookdev_node.parent()
        pub.allowEditingOfContents()

        rop = pub.node("ropnet1/rs_thumb")
        if rop is None:
            raise RuntimeError("ROP not found at ropnet1/rs_thumb")

        preview = pub.node("asset_preview")

        jobs_dir  = os.path.join(self.lib_root, "_farm_jobs", asset_name)
        thumbs_dir = os.path.join(jobs_dir, "thumbs")
        os.makedirs(thumbs_dir, exist_ok=True)

        frame_spec = "1-%d,1001-%d" % (steps, 1000 + steps)
        original_hip = hou.hipFile.path()
        job_ids = {}

        for pass_name in ("material", "clay", "wire"):
            if not passes.get(pass_name):
                job_ids[pass_name] = None
                continue

            prefix = os.path.join(thumbs_dir, pass_name + "_").replace("\\", "/")
            rop.parm("RS_outputFileNamePrefix").set(prefix)

            override_nodes = []
            orig_mat = None
            if pass_name == "clay":
                mat = _create_clay_material()
                override_nodes.append(mat)
                orig_mat = preview.parm("shop_materialpath").eval()
                preview.parm("shop_materialpath").set(mat.path())
            elif pass_name == "wire":
                mat = _create_wire_material()
                override_nodes.append(mat)
                orig_mat = preview.parm("shop_materialpath").eval()
                preview.parm("shop_materialpath").set(mat.path())

            try:
                hip_path = os.path.join(jobs_dir, "turntable_%s.hip" % pass_name)
                hou.hipFile.save(hip_path)
                job_id = _submit_via_prism_deadline(
                    hip_path=hip_path,
                    rop_path=rop.path(),
                    frame_spec=frame_spec,
                    name="%s_turntable_%s" % (asset_name, pass_name),
                    priority=priority,
                )
                job_ids[pass_name] = job_id
            except Exception as exc:
                logger.error("Turntable submission failed for pass %s: %s", pass_name, exc)
                job_ids[pass_name] = None
            finally:
                if orig_mat is not None:
                    preview.parm("shop_materialpath").set(orig_mat)
                for n in override_nodes:
                    try:
                        n.destroy()
                    except Exception:
                        pass

        # Restore original hip path
        if original_hip and os.path.isfile(original_hip):
            hou.hipFile.save(original_hip)

        return job_ids

    # ------------------------------------------------------------------
    # Publish (delegates to AssetImporter)
    # ------------------------------------------------------------------

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
# Module-level helpers (not part of the class)
# ------------------------------------------------------------------

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
    """Recursively find texture file paths in node's material network."""
    import hou

    visited = set()

    def _walk(n):
        if n.path() in visited:
            return
        visited.add(n.path())

        type_name = n.type().name().lower()
        if any(kw in type_name for kw in ("texture", "file", "tex", "sprite")):
            for parm in n.parms():
                if parm.name().lower() in _TEX_PARM_NAMES:
                    try:
                        val = parm.eval()
                        if val and isinstance(val, str) and os.path.isfile(val):
                            out_set.add(os.path.normpath(val))
                    except Exception:
                        pass

        try:
            for child in n.inputAncestors():
                _walk(child)
        except AttributeError:
            pass

        # Chase material assignment
        mat_parm = n.parm("shop_materialpath")
        if mat_parm:
            try:
                mat_node = hou.node(mat_parm.eval())
                if mat_node:
                    for child in mat_node.allSubChildren():
                        _walk(child)
            except Exception:
                pass

    _walk(node)


def _find_rendered_output(prefix, desired_path):
    """Locate the actual rendered file and move it to desired_path.

    Handles Redshift's frame-number suffix (prefix.0001.png, prefix.1.png, etc.).
    Returns desired_path if successful, None otherwise.
    """
    if os.path.isfile(desired_path):
        return desired_path

    # Search for any file matching the prefix pattern
    for candidate in sorted(glob.glob(prefix + "*.png")):
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
    """Create a wireframe RS material (dark base + white wireframe emission) in /mat."""
    import hou
    mat_net = _ensure_mat_network()
    for name in ("asset_pub_wire", "asset_pub_wiretex"):
        n = mat_net.node(name)
        if n:
            n.destroy()

    wire = mat_net.createNode("redshift::StandardMaterial", "asset_pub_wire")
    for ch in ("r", "g", "b"):
        wire.parm("base_color%s" % ch).set(0.05)

    try:
        wire_tex = mat_net.createNode("redshift::Wireframe", "asset_pub_wiretex")
        wire.setInput(wire.inputIndex("emission_color"), wire_tex, 0)
        wire.parm("emission_weight").set(1.0)
    except Exception:
        logger.warning(
            "redshift::Wireframe VOP not available; wireframe pass will be a dark material"
        )

    return wire


def _ensure_mat_network():
    import hou
    mat_net = hou.node("/mat")
    if mat_net is None:
        mat_net = hou.node("/obj").createNode("matnet", "mat")
    return mat_net


def _submit_via_prism_deadline(hip_path, rop_path, frame_spec, name, priority=25):
    """Submit a Houdini ROP job to Deadline via Prism's submitHoudiniJob.

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
        raise RuntimeError("Prism Deadline plugin not loaded — enable it in Prism settings")

    result = dl.submitHoudiniJob(
        jobName=name,
        frames=frame_spec,
        driver=rop_path,
        jobPrio=priority,
        jobFramesPerTask=1,
    )

    job_id = dl.getJobIdFromSubmitResult(result)
    return job_id or str(result).strip()
