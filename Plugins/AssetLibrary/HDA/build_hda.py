"""
Build / rebuild the Asset Publisher HDA.

Run inside Houdini's Python shell:
    exec(open(r"Z:/Users/Dimitar/Claude/Projects/Asset_Library/Plugins/AssetLibrary/HDA/build_hda.py").read())

What this does:
  - Creates a fresh /obj/subnet node (Object child context — can contain lookdev_scene)
  - Copies all parm templates from the existing HDA definition
  - Embeds a lookdev_scene HDA inside (512x512, Studio HDRI, no reference objects)
  - Saves as Asset Publisher HDA (same type name: AssetPublisher::1.3)
  - Restores all event handler sections (OnCreated, OnLoaded, PythonModule)

Re-run whenever you need to restructure the HDA (new parms, etc.).
"""

import hou
import shutil
import os

HDA_PATH     = r"Z:\Users\Dimitar\Claude\Projects\Asset_Library\Plugins\AssetLibrary\HDA\object_AssetPublisher.2.0.hda"
HDA_PATH_SRC = r"Z:\Users\Dimitar\Claude\Projects\Asset_Library\Plugins\AssetLibrary\HDA\object_AssetPublisher.1.2.hda"
TMP_PATH     = r"C:\Temp\ap_rebuild.hda"
HDA_TYPE     = "AssetPublisher::2.0"
HDA_LABEL    = "Asset Publisher"

PYTHON_MODULE = r"""import sys, os
_s = r'Z:\Users\Dimitar\Claude\Projects\Asset_Library\Plugins\AssetLibrary\Scripts'
def _m():
    if _s not in sys.path: sys.path.insert(0, _s)
    import core.houdini_publisher as _mod
    return _mod
def on_created(node, **kw):               _m().on_created(node, **kw)
def on_loaded(node, **kw):                _m().on_loaded(node, **kw)
def refresh_version_action(node, **kw):   _m().refresh_version_action(node, **kw)
def render_thumbnails_action(node, **kw): _m().render_thumbnails_action(node, **kw)
def publish_action(node, **kw):           _m().publish_action(node, **kw)
def asset_name_menu_items(node):   return _m().asset_name_menu_items(node)
def new_asset_name_action(node, **kw):    _m().new_asset_name_action(node, **kw)
def category_menu_items(node):     return _m().category_menu_items(node)
def subcategory_menu_items(node):  return _m().subcategory_menu_items(node)
def new_subcategory_action(node, **kw):   _m().new_subcategory_action(node, **kw)
def project_menu_items(node):      return _m().project_menu_items(node)
def new_project_action(node, **kw):       _m().new_project_action(node, **kw)
def add_tag_action(node, **kw):           _m().add_tag_action(node, **kw)
"""

# ------------------------------------------------------------------
# 1. Load the source HDA (v1.1) to grab its parm template group
# ------------------------------------------------------------------
print("Loading source HDA for parms...")
hou.hda.installFile(HDA_PATH_SRC)
src_defn  = hou.hda.definitionsInFile(HDA_PATH_SRC)[0]
ptg       = src_defn.parmTemplateGroup()
old_extra = src_defn.sections().get("ExtraFileOptions")

# ------------------------------------------------------------------
# 1b. PTG modifications — remove obsolete parms, inject camera folder at top
# ------------------------------------------------------------------

# Remove the old camera node-path and frame parms (replaced by lookdev controls)
for _rm in ("thumb_cam", "thumb_frame"):
    _t = ptg.find(_rm)
    if _t:
        ptg.remove(_t)

# Only inject the Camera folder if it isn't already in the PTG (idempotent rebuild)
if not ptg.find("ld_lookat"):
    _cam_folder = hou.FolderParmTemplate(
        "ld_cam", "Camera",
        folder_type=hou.folderType.Simple,
    )
    _cam_folder.addParmTemplate(hou.FloatParmTemplate(
        "ld_lookat", "Look At", 3,
        default_value=(0.0, 0.5, 0.0),
        naming_scheme=hou.parmNamingScheme.XYZW,
        min=-10.0, max=10.0,
    ))
    _cam_folder.addParmTemplate(hou.FloatParmTemplate(
        "ld_zoom", "Zoom", 1,
        default_value=(0.0,),
        min=-10.0, max=10.0,
    ))
    _cam_folder.addParmTemplate(hou.FloatParmTemplate(
        "ld_push", "Push In", 1,
        default_value=(0.0,),
        min=-10.0, max=10.0,
    ))
    _cam_folder.addParmTemplate(hou.FloatParmTemplate(
        "ld_tilt", "Tilt", 1,
        default_value=(0.0,),
        min=-10.0, max=10.0,
    ))
    _cam_folder.addParmTemplate(hou.IntParmTemplate(
        "ld_focal", "Focal Length", 1,
        default_value=(80,),
        min=1, max=200,
    ))
    _cam_folder.addParmTemplate(hou.SeparatorParmTemplate("sep_turntable"))
    _cam_folder.addParmTemplate(hou.IntParmTemplate(
        "ld_steps", "Turntable Steps", 1,
        default_value=(36,),
        min=4, max=72,
    ))

    _sep_passes = ptg.find("sep_passes")
    if _sep_passes:
        ptg.insertBefore(_sep_passes, _cam_folder)
    else:
        ptg.append(_cam_folder)

# Pass control parms — read by ROP/SOP expressions (thumb_output_dir / pass_name
# are set at submit time by submit_turntable_to_deadline).
if not ptg.find("use_override"):
    _pass_folder = hou.FolderParmTemplate(
        "pass_ctrl", "Pass Control",
        folder_type=hou.folderType.Simple,
        is_hidden=True,
    )
    for _pname, _plabel, _ptype, _pdefault in [
        ("use_override",    "Use Override",    "int",    0),
        ("hide_lookdev",    "Hide Lookdev",    "int",    0),
        ("thumb_output_dir","Thumb Output Dir","string", ""),
        ("pass_name",       "Pass Name",       "string", "material"),
        ("override_mat",    "Override Mat",    "string", ""),
    ]:
        if _ptype == "int":
            _pass_folder.addParmTemplate(hou.IntParmTemplate(_pname, _plabel, 1, default_value=(_pdefault,)))
        else:
            _pass_folder.addParmTemplate(hou.StringParmTemplate(_pname, _plabel, 1, default_value=(_pdefault,)))
    ptg.append(_pass_folder)

# Inject thumb_res into the Camera folder (separate guard — survives re-rebuilds)
if not ptg.find("thumb_res"):
    _thumb_res = hou.IntParmTemplate(
        "thumb_res", "Thumbnail Resolution", 1,
        default_value=(1024,),
        min=64, max=4096,
    )
    _sep_turntable = ptg.find("sep_turntable")
    if _sep_turntable:
        ptg.insertBefore(_sep_turntable, _thumb_res)
    else:
        _ld_focal = ptg.find("ld_focal")
        if _ld_focal:
            ptg.insertAfter(_ld_focal, _thumb_res)
        else:
            ptg.append(_thumb_res)

# Deadline farm controls — priority + frames-per-task for turntable submission
if not ptg.find("deadline_priority"):
    _dl_folder = hou.FolderParmTemplate(
        "deadline_ctrl", "Deadline",
        folder_type=hou.folderType.Simple,
    )
    _dl_folder.addParmTemplate(hou.IntParmTemplate(
        "deadline_priority", "Priority", 1,
        default_value=(5,),
        min=0, max=100,
    ))
    _dl_folder.addParmTemplate(hou.IntParmTemplate(
        "deadline_frames_per_task", "Frames Per Task", 1,
        default_value=(6,),
        min=1, max=72,
    ))
    _cam = ptg.find("ld_cam")
    if _cam:
        ptg.insertAfter(_cam, _dl_folder)
    else:
        ptg.append(_dl_folder)

# Multi-format export toggles. Keep the old export_format menu for backwards
# compatibility, but new publishes use these toggles when any are enabled.
if not ptg.find("export_abc"):
    _export_folder = hou.FolderParmTemplate(
        "export_formats", "Export Formats",
        folder_type=hou.folderType.Simple,
    )
    for _pname, _plabel, _default in [
        ("export_usd",  "USD",  0),
        ("export_abc",  "Alembic", 1),
        ("export_bgeo", "BGEO", 0),
        ("export_fbx",  "FBX", 0),
        ("export_obj",  "OBJ", 0),
        ("export_hda",  "HDA", 0),
        ("export_hip",  "HIP", 0),
    ]:
        _export_folder.addParmTemplate(
            hou.ToggleParmTemplate(_pname, _plabel, default_value=_default)
        )
    _old_export_format = ptg.find("export_format")
    if _old_export_format:
        ptg.insertAfter(_old_export_format, _export_folder)
    else:
        ptg.append(_export_folder)

# Replace asset_name plain string with a dynamic menu + "+" button (idempotent)
if not ptg.find("new_asset_name"):
    if ptg.find("asset_name"):
        ptg.remove("asset_name")
    _an_menu = hou.StringParmTemplate(
        "asset_name", "Asset Name", 1,
        item_generator_script="hou.phm().asset_name_menu_items(kwargs['node'])",
        item_generator_script_language=hou.scriptLanguage.Python,
    )
    _an_menu.setJoinWithNext(True)
    _an_btn = hou.ButtonParmTemplate(
        "new_asset_name", "+",
        script_callback="hou.phm().new_asset_name_action(kwargs['node'])",
        script_callback_language=hou.scriptLanguage.Python,
    )
    _cat = ptg.find("category")
    if _cat:
        ptg.insertBefore(_cat, _an_menu)  # menu before category
        ptg.insertBefore(_cat, _an_btn)   # btn before category (after menu)
    else:
        ptg.append(_an_menu)
        ptg.append(_an_btn)

# Move source_node above all tabs, relabelled to "Asset Path" (only if not already done)
_source_node = ptg.find("source_node")
if _source_node and _source_node.label() != "Asset Path" and ptg.find("stdswitcher5"):
    ptg.remove(_source_node)
    _asset_path = hou.StringParmTemplate(
        "source_node", "Asset Path", 1,
        string_type=hou.stringParmType.NodeReference,
    )
    ptg.insertBefore(ptg.find("stdswitcher5"), _asset_path)

# ------------------------------------------------------------------
# 1c. Delete stale temp file so createDigitalAsset always starts clean
# ------------------------------------------------------------------
if os.path.isfile(TMP_PATH):
    os.remove(TMP_PATH)

# ------------------------------------------------------------------
# 2. Clean up any leftover build nodes
# ------------------------------------------------------------------
for name in ("_ap_build_node",):
    n = hou.node("/obj/" + name)
    if n:
        n.destroy()

# ------------------------------------------------------------------
# 3. Create a fresh Object-context subnet (childTypeCategory = Object)
# ------------------------------------------------------------------
print("Creating Object subnet...")
subnet = hou.node("/obj").createNode("subnet", "_ap_build_node")

# ------------------------------------------------------------------
# 4a. Embed lookdev_scene (renders the transformed geometry in asset_preview)
# ------------------------------------------------------------------
print("Creating embedded lookdev_scene...")
lookdev = subnet.createNode("lookdev_scene::2.14", "lookdev_scene")
try:
    lookdev.parm("resx").set(512)
    lookdev.parm("resy").set(512)
    lookdev.parm("RSL_samples").set(64)
    lookdev.parm("Spheres").set(0)
    lookdev.parm("Chart").set(0)
    # Always point at asset_preview which has Asset_Transform1 applied.
    lookdev.parm("objpath2").setExpression(
        "hou.node('../asset_preview').path()",
        hou.exprLanguage.Python
    )
    # Camera controls — driven by HDA-level parms (ch("../") resolves to AssetPublisher)
    for _comp in ("x", "y", "z"):
        _p = lookdev.parm("LookAt" + _comp)
        if _p:
            _p.setExpression('ch("../ld_lookat%s")' % _comp, hou.exprLanguage.Hscript)
    for _src, _dst in [("Zoom", "ld_zoom"), ("Push", "ld_push"),
                        ("Tilt", "ld_tilt"), ("focal", "ld_focal")]:
        _p = lookdev.parm(_src)
        if _p:
            _p.setExpression('ch("../%s")' % _dst, hou.exprLanguage.Hscript)

    # Turntable rotation via main_rotation null inside lookdev_scene
    # From main_rotation, ../../ = AssetPublisher level where ld_steps lives
    lookdev.allowEditingOfContents()
    _rot_node = lookdev.node("main_rotation")
    if _rot_node:
        _rot_node.parm("ry").deleteAllKeyframes()
        _rot_node.parm("ry").setExpression(
            "($F - 1) % 1000 / max(ch('../../ld_steps'), 1) * 360.0",
            hou.exprLanguage.Hscript
        )
    else:
        print("  Warning — main_rotation not found inside lookdev_scene")
except Exception as e:
    print("  Warning — lookdev parm:", e)

# ------------------------------------------------------------------
# 4b. Embed asset_preview (Object Merge -> Asset_Transform1 -> OUT)
# ------------------------------------------------------------------
print("Creating embedded asset_preview with Asset_Transform1...")
preview = subnet.createNode("geo", "asset_preview")
try:
    merge = preview.createNode("object_merge", "objectmerge1")
    # Resolve source_node parm (may be relative path like ../box1) to absolute.
    # From objectmerge1, '../..' navigates to the Asset Publisher node.
    merge.parm("objpath1").setExpression(
        "n.path() if (n := hou.node('../..').node(hou.node('../..').parm('source_node').evalAsString())) else ''",
        hou.exprLanguage.Python
    )
    merge.parm("xformtype").set(0)  # world-space import

    xform = preview.createNode("Asset_Transform::2.2", "Asset_Transform1")
    xform.parm("Select_Transform").set(1)  # AboveGround
    xform.setInput(0, merge)
    xform.setDisplayFlag(False)
    xform.setRenderFlag(False)
    merge.setPosition([xform.position()[0], xform.position()[1] + 1.5])

    # Material override SOP — applies clay/wire material when use_override=1
    mat_sop = preview.createNode("material", "override_mat")
    mat_sop.parm("shop_materialpath1").setExpression('chs("../../override_mat")', hou.exprLanguage.Hscript)
    mat_sop.setInput(0, xform)
    mat_sop.setDisplayFlag(False)
    mat_sop.setRenderFlag(False)
    mat_sop.setPosition([xform.position()[0] + 2.5, xform.position()[1]])

    # Switch — input 0: original material, input 1: override material
    switch = preview.createNode("switch", "pass_switch")
    switch.parm("input").setExpression('ch("../../use_override")', hou.exprLanguage.Hscript)
    switch.setInput(0, xform)
    switch.setInput(1, mat_sop)
    switch.setDisplayFlag(False)
    switch.setRenderFlag(False)
    switch.setPosition([xform.position()[0], xform.position()[1] - 1.5])

    out = preview.createNode("null", "OUT")
    out.setInput(0, switch)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)
    out.setPosition([xform.position()[0], xform.position()[1] - 3.0])

    # Displacement + tessellation off for clay/wire passes (driven by use_override)
    preview.parm("RS_objprop_displace_enable").setExpression('1 - ch("../use_override")', hou.exprLanguage.Hscript)
    preview.parm("RS_objprop_proxy_ovrTess").setExpression('ch("../use_override")', hou.exprLanguage.Hscript)


except Exception as e:
    print("  Warning — asset_preview setup:", e)

# ------------------------------------------------------------------
# 4c. Embed ropnet1 with Redshift ROP for thumbnail rendering
# ------------------------------------------------------------------
print("Creating embedded ropnet1/rs_thumb...")
ropnet = subnet.createNode("ropnet", "ropnet1")
try:
    rs = ropnet.createNode("Redshift_ROP", "rs_thumb")
    # Camera: lookdev_scene's internal camera (../../ = AssetPublisher level)
    rs.parm("RS_renderCamera").setExpression(
        "hou.node('../../lookdev_scene/lookdev_camera').path()",
        hou.exprLanguage.Python
    )
    # Wire pass hides lookdev_scene (cyclorama); material/clay render everything.
    # Must return an absolute path — Redshift does not resolve relative paths here.
    rs.parm("RS_objects_exclude").setExpression(
        "hou.node('../../lookdev_scene').path() if int(ch('../../hide_lookdev')) else ''",
        hou.exprLanguage.Python
    )
    # Output path built from HDA parms — pass_name/thumb_output_dir set at submit time
    rs.parm("RS_outputFileNamePrefix").setExpression(
        'chs("../../thumb_output_dir") + "/" + chs("../../pass_name") + "_tmp"',
        hou.exprLanguage.Hscript
    )
    # Render at current timeline frame
    for _fp in ("f1", "f2"):
        rs.parm(_fp).setExpression("hou.frame()", hou.exprLanguage.Python)
    # Override resolution always ON — 1024x1024 default, overridden at render time from thumb_res
    try:
        rs.parm("RS_overrideCameraRes").set(1)
        rs.parm("RS_overrideRes1").set(1024)
        rs.parm("RS_overrideRes2").set(1024)
    except Exception as e:
        print("  Warning — RS_overrideRes:", e)
except Exception as e:
    print("  Warning — ropnet setup:", e)

# ------------------------------------------------------------------
# 4d. Embed thumb_mats — clay and wire materials for pass overrides
# ------------------------------------------------------------------
print("Creating embedded thumb_mats...")
try:
    mats = subnet.createNode("matnet", "thumb_mats")

    # clay_mat — warm grey RS Standard Material, no displacement
    clay_net = mats.createNode("redshift_vopnet", "clay_mat")
    clay = clay_net.createNode("redshift::StandardMaterial", "clay_std")
    clay.parm("base_colorr").set(0.75)
    clay.parm("base_colorg").set(0.72)
    clay.parm("base_colorb").set(0.68)
    clay.parm("refl_roughness").set(0.9)
    clay.parm("refl_ior").set(1.45)
    clay_out = clay_net.createNode("redshift_material", "redshift_material1")
    clay_out.setInput(0, clay, 0)
    clay_net.layoutChildren()

    # wire_mat — black base + white emission + WireFrame VOP
    wire_net = mats.createNode("redshift_vopnet", "wire_mat")
    wire = wire_net.createNode("redshift::StandardMaterial", "wire_std")
    for _ch in ("r", "g", "b"):
        wire.parm("base_color%s" % _ch).set(0.0)
    wire.parm("emission_weight").set(1.0)
    wire.parm("emission_colorr").set(1.0)
    wire.parm("emission_colorg").set(1.0)
    wire.parm("emission_colorb").set(1.0)
    try:
        wire_tex = wire_net.createNode("redshift::WireFrame", "wire_tex")
        wire.setInput(wire.inputIndex("emission_color"), wire_tex, 0)
    except Exception as _e:
        print("  Warning — WireFrame VOP:", _e)
    wire_out = wire_net.createNode("redshift_material", "redshift_material1")
    wire_out.setInput(0, wire, 0)
    wire_net.layoutChildren()

except Exception as e:
    print("  Warning — thumb_mats setup:", e)

# ------------------------------------------------------------------
# 4e. (Removed) TOPs topnet1 / pass_wedge — turntable now runs via the
#     per-HIP Deadline submission (submit_turntable_to_deadline). The live
#     HDA also has its topnet1 deleted; this block is left as a breadcrumb.
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# 5. Convert subnet to HDA (no spare parms yet — add them to definition after)
# ------------------------------------------------------------------
print("Creating digital asset...")
subnet = subnet.createDigitalAsset(
    name=HDA_TYPE,
    hda_file_name=TMP_PATH,
    description=HDA_LABEL,
    min_num_inputs=0,
    max_num_inputs=0,
    save_as_embedded=False,
    ignore_external_references=True,
)

# ------------------------------------------------------------------
# 6. Set parm template group + all sections on the definition
# ------------------------------------------------------------------
print("Writing HDA sections and parms...")
new_defn = next(
    d for d in hou.hda.definitionsInFile(TMP_PATH)
    if d.nodeTypeName() == HDA_TYPE
)

# Transfer all parms from the old HDA (menu scripts, callbacks, tabs — all intact)
new_defn.setParmTemplateGroup(ptg)

new_defn.addSection("PythonModule", PYTHON_MODULE)
new_defn.addSection("OnCreated",
    "import sys\n"
    "_s = r'Z:\\Users\\Dimitar\\Claude\\Projects\\Asset_Library\\Plugins\\AssetLibrary\\Scripts'\n"
    "if _s not in sys.path: sys.path.insert(0, _s)\n"
    "import core.houdini_publisher as _hp\n"
    "_hp.on_created(kwargs['node'])\n"
)
new_defn.addSection("OnLoaded",
    "import sys\n"
    "_s = r'Z:\\Users\\Dimitar\\Claude\\Projects\\Asset_Library\\Plugins\\AssetLibrary\\Scripts'\n"
    "if _s not in sys.path: sys.path.insert(0, _s)\n"
    "import core.houdini_publisher as _hp\n"
    "_hp.on_loaded(kwargs['node'])\n"
)

# Mark all three sections as Python (IsPython=False is the default and breaks execution)
for _sec in ("OnCreated", "OnLoaded", "PythonModule"):
    new_defn.setExtraFileOption("%s/IsPython" % _sec, True)
    new_defn.setExtraFileOption("%s/IsScript" % _sec, True)
    new_defn.setExtraFileOption("%s/IsExpr"   % _sec, False)

new_defn.save(TMP_PATH)

# ------------------------------------------------------------------
# 7. Copy to final location and reload
# ------------------------------------------------------------------
print("Copying to", HDA_PATH)
shutil.copy2(TMP_PATH, HDA_PATH)

# Uninstall the temp file so it doesn't conflict with the main HDA
try:
    hou.hda.uninstallFile(TMP_PATH, change_oplibraries_file=False)
except Exception:
    pass

# Also uninstall backups that share the same type name (prevent conflicts)
import glob as _glob
backup_dir = os.path.dirname(HDA_PATH) + r"\backup"
for bak in _glob.glob(backup_dir + r"\object_AssetPublisher.2.0*.hda"):
    try:
        hou.hda.uninstallFile(bak.replace("\\", "/"), change_oplibraries_file=False)
    except Exception:
        pass

# Reinstall the final HDA cleanly (single reload at the end of step 7b)
hou.hda.installFile(HDA_PATH)

# ------------------------------------------------------------------
# 7b. Patch DialogScript — setParmTemplateGroup silently drops
#     freshly-injected buttons (Houdini limitation). Patch runs on
#     the on-disk definition so save() doesn't regenerate over it.
# ------------------------------------------------------------------
print("Patching DialogScript for asset_name menu + new_asset_name button...")
_patch_defn = next(
    d for d in hou.hda.definitionsInFile(HDA_PATH)
    if d.nodeTypeName() == HDA_TYPE
)
_ds_section = _patch_defn.sections()["DialogScript"]
_ds = _ds_section.contents()

_OLD_AN = '''\
        parm {
            name    "asset_name"
            label   "Asset Name"
            type    string
            default { "" }
        }'''

_NEW_AN = '''\
        parm {
            name    "asset_name"
            label   "Asset Name"
            type    string
            joinnext
            default { "" }
            menu {
                [ "hou.phm().asset_name_menu_items(kwargs['node'])" ]
                language python
            }
        }
        parm {
            name    "new_asset_name"
            label   "+"
            type    button
            default { 0 }
            parmtag { "script_callback" "hou.phm().new_asset_name_action(kwargs['node'])" }
            parmtag { "script_callback_language" "python" }
        }'''

if _OLD_AN in _ds:
    _ds = _ds.replace(_OLD_AN, _NEW_AN)
    _ds_section.setContents(_ds)
    print("  DialogScript patched OK")
elif "new_asset_name" in _ds:
    print("  DialogScript already patched, skipping replace")
else:
    print("  WARNING — asset_name block not found in DialogScript")

# Always re-set PythonModule and event sections on the patch definition
# so a stale in-memory version doesn't overwrite the correct content on save.
_patch_defn.addSection("PythonModule", PYTHON_MODULE)
for _sec in ("OnCreated", "OnLoaded", "PythonModule"):
    _patch_defn.setExtraFileOption("%s/IsPython" % _sec, True)
    _patch_defn.setExtraFileOption("%s/IsScript" % _sec, True)
    _patch_defn.setExtraFileOption("%s/IsExpr"   % _sec, False)
_patch_defn.save(HDA_PATH)
hou.hda.reloadAllFiles()
print("  Saved OK")

# Clean up build node (now it's an AssetPublisher instance — delete it)
built = hou.node("/obj/_ap_build_node")
if built:
    built.destroy()

print("\nDone!")
print("  Type:     ", HDA_TYPE)
new_defn2 = hou.hda.definitionsInFile(HDA_PATH)[0]
print("  Child ctx:", new_defn2.nodeTypeCategory().name())
print("  Sections: ", list(new_defn2.sections().keys()))
