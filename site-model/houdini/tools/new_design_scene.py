"""Make a Houdini design scene for one person: the site point cloud as context, an empty Design_<name> node to model in,
and a ROP that exports it to site-model/exports/design_<name>.glb, which the web viewer loads on top of the site.

Run it once, inside Houdini (Apprentice has no command-line hython). In Windows > Python Shell, paste one line
(change the path to where your copy of the repository is):

  p = "/Users/you/GitHub/sci-arc-studio-fall2026/site-model/houdini/tools/new_design_scene.py"; exec(open(p).read(), {"__file__": p, "hou": hou})

It asks for your name (lowercase, e.g. clark) and saves site-model/houdini/designs/<name>.hipnc. Claude can run it
for you through the Houdini MCP: import it (tools/ on sys.path), set new_design_scene.hou = hou, then
new_design_scene.make("clark").

The scene:
  /obj/Site_context   web/data/lidar_points.laz, the website's point cloud (8.8 M points, grey by return intensity;
                      not selectable, not exported)
  /obj/Design_<name>  model here: wire your SOPs into the "your_geometry" merge. One prim string attribute "name"
                      gives separate objects (clickable in the viewer); "layer" gives your own layer toggles
                      (default Design_<name>).
  /out/export_design  Render it to write site-model/exports/design_<name>.glb

Frame: Houdini's Y-up axes are the web viewer's: x = east, y = up (m, NAVD88), z = -north, from the site origin
E 384580 / N 3768520. Model in metres, at the real heights (the point cloud shows them).
"""
import os
import re

if "hou" not in globals():   # pasted into Houdini's Python Shell, hou is passed in; otherwise import it
    try:
        import hou
    except ImportError:      # imported outside Houdini (the Houdini MCP runs code in its own process): set nds.hou first
        hou = None

TAGS = r'''
// web contract: one glTF node per "name" (or one for everything), extras.layer = the viewer's layer toggle
string who = chs("../designer");
string nm = s@name != "" ? s@name : "Design_" + who;
string lay = s@layer != "" ? s@layer : "Design_" + who;
s@path = "/" + nm;
dict ex; ex["layer"] = lay; ex["designer"] = who;
d@gltf_node_extras = ex;
'''


def repo_root():
    here = os.path.dirname(os.path.abspath(globals().get("__file__", "")))
    root = os.path.normpath(os.path.join(here, "..", "..", ".."))
    if not os.path.exists(os.path.join(root, "web", "data", "lidar_points.laz")):
        raise RuntimeError("Run this file with __file__ set (see the docstring); web/data/lidar_points.laz not found under " + root)
    return root.replace("\\", "/")


def make(name, save=True):
    name = name.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError("name: lowercase letters, digits and _ (e.g. clark)")
    root = repo_root()
    hou.hipFile.clear(suppress_save_prompt=True)
    # paths are relative to the scene file ($HIP = site-model/houdini/designs), so it works in any copy of the repo
    folder = root + "/site-model/houdini/designs"
    os.makedirs(folder, exist_ok=True)
    hou.hipFile.setName(folder + "/" + name + ".hipnc")

    obj = hou.node("/obj")
    ctx = obj.createNode("geo", "Site_context")
    g = ctx.createNode("lidarimport", "site_points")
    g.parm("filename").set("$HIP/../../../web/data/lidar_points.laz")
    g.parm("intensity").set(1)
    g.parm("rx").set(-90)                           # LAS z-up (x east, y north) -> Houdini / web y-up (x east, z -north)
    grey = ctx.createNode("attribwrangle", "grey_by_intensity")
    grey.parm("class").set(2)                       # points
    # intensity is 0-255 in the file; lidarimport reads it as a share of 65535
    grey.parm("snippet").set("float i = clamp(f@intensity * 65535.0 / 255.0, 0, 1);\nv@Cd = set(1, 1, 1) * fit01(i, 0.25, 1.0);")
    grey.setInput(0, g)
    grey.setDisplayFlag(True); grey.setRenderFlag(True)
    ctx.layoutChildren()
    ctx.setSelectableInViewport(False)
    ctx.setColor(hou.Color(0.55, 0.55, 0.55))
    ctx.setComment("The site point cloud (web/data/lidar_points.laz). Do not edit; it is not exported.")

    d = obj.createNode("geo", "Design_" + name)
    d.addSpareParmTuple(hou.StringParmTemplate("designer", "Designer", 1, default_value=(name,)))
    merge = d.createNode("merge", "your_geometry")
    tags = d.createNode("attribwrangle", "web_tags")
    tags.parm("class").set(1)                      # primitives
    tags.parm("snippet").set(TAGS.strip())
    tags.setInput(0, merge)
    nrm = d.createNode("normal", "normals")         # glTF needs normals for shading
    nrm.setInput(0, tags)
    out = d.createNode("output", "OUT")
    out.setInput(0, nrm)
    out.setDisplayFlag(True); out.setRenderFlag(True)
    note = d.createStickyNote("how_to")
    note.setText("Wire your SOPs into 'your_geometry'.\nPrim attribute 'name' = separate objects in the viewer;\n"
                 "'layer' = your own layer toggles (default Design_" + name + ").\n"
                 "Export: /out/export_design -> Render. Metres; y = up, x = east, z = -north.")
    note.setSize(hou.Vector2(5, 1.6))
    d.layoutChildren()
    d.setColor(hou.Color(0.87, 0.9, 0.71))

    rop = hou.node("/out").createNode("gltf::2.0", "export_design")
    rop.parm("outputfile").set("$HIP/../../exports/design_" + name + ".glb")
    rop.parm("usesoppath").set(1)
    rop.parm("soppath").set(out.path())
    rop.parm("buildfrompath").set(1)
    rop.parm("pathattrib").set("path")
    rop.parm("exportextras").set(1)
    rop.parm("exportmaterials").set(0)              # the viewer colours design layers itself
    rop.parm("usedracocompression").set(1)

    obj.layoutChildren()
    if save:
        hou.hipFile.save()
    return d


# pasted into the Python Shell (see above): ask for the name. Imported as a module (Claude, other scripts): call make().
if hou is not None and __name__ in ("__main__", "builtins") and not globals().get("no_prompt") and hou.isUIAvailable():
    button, typed = hou.ui.readInput("Your name (lowercase, e.g. clark):", buttons=("OK", "Cancel"))
    if button == 0 and typed.strip():
        make(typed)
