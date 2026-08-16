"""AttrViz analytic tests — headless, self-contained (no other addons).

Run:
  blender --background --factory-startup --python-exit-code 1 \
      --python tests/headless_test.py
"""
import os
import sys

import bpy
import bmesh
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import attrviz as av  # noqa: E402

PASS = 0
FAIL = 0

# This suite cooks the materials/GN path (vizcol / vizval). GPU Overlay
# (default on) suppresses GN carriers — turn it off for these checks.
av.register()
bpy.context.scene.attrviz_gpu_markers = False


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}  {detail}")


def cook(obj):
    """Synchronous depsgraph eval; hold the GeometrySet (GC gotcha)."""
    obj.update_tag()
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    return obj.evaluated_get(deps).evaluated_geometry()


def attr_arr(data_block, name, dtype=np.float32, field="value",
             width=1):
    data = data_block.attributes[name].data
    arr = np.empty(len(data) * width, dtype=dtype)
    data.foreach_get(field, arr)
    return arr.reshape(-1, width) if width > 1 else arr


def make_grid(name, n=5, size=2.0, loc=(0.0, 0.0, 0.0)):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=n - 1, y_segments=n - 1,
                          size=size)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = loc
    bpy.context.collection.objects.link(obj)
    return obj


print("\n== V1-V4: Heat markers on an authored float attribute ==")
grid = make_grid("Heat Grid", n=8)
heat = grid.data.attributes.new("heat", 'FLOAT', 'POINT')
nv = len(heat.data)
for i, d in enumerate(heat.data):
    d.value = i / (nv - 1)
mods_before = [m.name for m in grid.modifiers]
viz = av.add_visualizer(bpy.context, target=grid, attribute="heat",
                        domain="Point", style="Heat", display="Markers")
gs = cook(viz)
mesh = gs.mesh
npts = len(mesh.vertices) if mesh else 0
check("V1 visualizer emits marker geometry", npts >= nv * 12,
      f"verts={npts}")
names = set(mesh.attributes.keys()) if mesh else set()
check("V2 markers carry vizcol + vizval",
      "vizcol" in names and "vizval" in names, str(sorted(names)))
check("V3 watched object's stack is UNTOUCHED",
      [m.name for m in grid.modifiers] == mods_before
      and av.viz_modifier(grid) is None,
      str([m.name for m in grid.modifiers]))
vv = attr_arr(mesh, "vizval")
check("V4 auto-range normalizes to [0,1] exactly",
      float(vv.min()) < 1e-3 and abs(float(vv.max()) - 1.0) < 1e-3,
      f"min={vv.min():.4f} max={vv.max():.4f}")

print("\n== V5: Density culls markers ==")
vmd = av.viz_modifier(viz)
av.node_builder.set_input(vmd, "Density", 0.2)
gs2 = cook(viz)
n_dense = len(gs2.mesh.vertices) if gs2.mesh else 0
check("V5 density 0.2 -> markedly fewer markers",
      0 < n_dense < 0.5 * npts, f"full={npts} culled={n_dense}")
av.node_builder.set_input(vmd, "Density", 1.0)

print("\n== V6: Arrows on a vector attribute ==")
flow_obj = make_grid("Flow Grid", n=4, loc=(6.0, 0.0, 0.0))
fattr = flow_obj.data.attributes.new("flow", 'FLOAT_VECTOR', 'POINT')
for d in fattr.data:
    d.vector = (0.3, 0.0, 1.0)
viz2 = av.add_visualizer(bpy.context, target=flow_obj,
                         attribute="flow", domain="Point",
                         style="Heat", display="Arrows")
gs3 = cook(viz2)
n_arrows = len(gs3.mesh.vertices) if gs3.mesh else 0
check("V6 vector attribute -> arrow geometry", n_arrows >= 16 * 7,
      f"verts={n_arrows}")

print("\n== V7: Collection scope covers many objects ==")
scol = bpy.data.collections.new("ScopeTest")
bpy.context.scene.collection.children.link(scol)
counts = []
for i in range(2):
    o = make_grid(f"S{i}", n=3, size=0.5, loc=(i * 3.0, 4.0, 0.0))
    a = o.data.attributes.new("heatv", 'FLOAT', 'POINT')
    for j, d in enumerate(a.data):
        d.value = float(j)
    for c in list(o.users_collection):
        c.objects.unlink(o)
    scol.objects.link(o)
    counts.append(len(o.data.vertices))
viz3 = av.add_visualizer(bpy.context, scope=scol, attribute="heatv",
                         domain="Point", style="Heat", display="Markers")
gs4 = cook(viz3)
# icosphere subdiv 1 = icosahedron = 12 verts per marker
n_markers = (len(gs4.mesh.vertices) // 12) if gs4.mesh else 0
check("V7 one visualizer marks BOTH scoped objects",
      n_markers == sum(counts),
      f"markers={n_markers} expected={sum(counts)}")

print("\n== V9: THE default-cube gesture — position as surface RGB ==")
cme = bpy.data.meshes.new("Cube9")
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=2.0)
bm.to_mesh(cme)
bm.free()
cobj = bpy.data.objects.new("Cube9", cme)
bpy.context.collection.objects.link(cobj)
viz9 = av.add_visualizer(bpy.context, target=cobj,
                         attribute="position", domain="Point",
                         style="RGB", display="Surface")
gs9 = cook(viz9)
m9 = gs9.mesh
check("V9a surface display keeps the target's faces (tinted copy)",
      (len(m9.polygons) if m9 else 0) == 6,
      f"faces={len(m9.polygons) if m9 else 0}")
names9 = set(m9.attributes.keys()) if m9 else set()
check("V9b tinted surface carries vizcol per vertex",
      "vizcol" in names9, str(sorted(names9)))
if m9 and "vizcol" in names9:
    cols = attr_arr(m9, "vizcol", field="color", width=4)
    spans = cols.max(axis=0) - cols.min(axis=0)
    check("V9c RGB style: each position axis spans the channel",
          bool((spans[:3] > 0.9).all()),
          f"channel spans={spans[:3].round(3)}")

print("\n== V10: auto-pick table (domain-aware RMB defaults) ==")
# (domain, data_type, has_faces) → (style, display)
table = (
    (("Point", 'FLOAT_VECTOR', True), ("RGB", "Surface")),
    (("Point", 'FLOAT_VECTOR', False), ("RGB", "Markers")),
    (("Point", 'FLOAT', True), ("Heat", "Surface")),
    (("Point", 'FLOAT', False), ("Heat", "Markers")),
    (("Point", 'INT', False), ("Random", "Markers")),
    (("Face", 'INT', True), ("Random", "Surface")),
    (("Face", 'FLOAT', True), ("Heat", "Surface")),
    (("Edge", 'FLOAT', True), ("Heat", "Markers")),
    (("Corner", 'FLOAT', True), ("Heat", "Markers")),
)
ok10 = all(av.auto_pick(*args) == want for args, want in table)
check("V10 auto_pick matches the pinned table", ok10,
      str([(a, av.auto_pick(*a)) for a, _ in table]))
check("V10b Normal defaults to Arrows",
      av.auto_pick("Point", 'FLOAT_VECTOR', True, attribute="Normal")
      == ("RGB", "Arrows"))

print("\n== V12: Face domain + Random color for integer ids ==")
fme = bpy.data.meshes.new("FaceID")
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=2.0)
bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=2,
                          use_grid_fill=True)
bm.to_mesh(fme)
bm.free()
fobj = bpy.data.objects.new("FaceID", fme)
bpy.context.collection.objects.link(fobj)
fid = fme.attributes.new("face_id", 'INT', 'FACE')
for i, d in enumerate(fid.data):
    d.value = i
nfaces = len(fid.data)
viz12 = av.add_visualizer(bpy.context, target=fobj, attribute="face_id",
                          domain="Face", style="Random",
                          display="Surface")
gs12 = cook(viz12)
m12 = gs12.mesh
vc = m12.attributes.get("vizcol") if m12 else None
# Workbench needs a Color Attribute — CORNER (Face-domain color is not one)
check("V12a face Random promotes vizcol to CORNER Color Attribute",
      vc is not None and vc.domain == 'CORNER',
      f"domain={getattr(vc, 'domain', None)} len={len(vc.data) if vc else 0}")
if vc is not None:
    cols = attr_arr(m12, "vizcol", field="color", width=4)
    uniq = len({tuple(np.round(r, 4)) for r in cols})
    check("V12b each face id gets a distinct hash color",
          uniq == nfaces, f"unique={uniq} faces={nfaces}")

print("\n== V13: intrinsic Index on Face (post-topology, unique) ==")
ime = bpy.data.meshes.new("IdxFace")
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=2.0)
bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=1,
                          use_grid_fill=True)
bm.to_mesh(ime)
bm.free()
iobj = bpy.data.objects.new("IdxFace", ime)
bpy.context.collection.objects.link(iobj)
nfaces_i = len(ime.polygons)
by_i, _ = av.attributes_by_domain(iobj)
face_names = [n for n, _t in by_i.get("Face", [])]
check("V13a menu lists Index / Position / Normal first",
      face_names[:3] == ["Index", "Position", "Normal"],
      str(face_names[:6]))
viz13 = av.add_visualizer(bpy.context, target=iobj, attribute="Index",
                          domain="Face", style="Random",
                          display="Surface")
gs13 = cook(viz13)
m13 = gs13.mesh
vc13 = m13.attributes.get("vizcol") if m13 else None
check("V13b Index Random promotes vizcol to CORNER Color Attribute",
      vc13 is not None and vc13.domain == 'CORNER',
      f"domain={getattr(vc13, 'domain', None)} "
      f"len={len(vc13.data) if vc13 else 0} faces={nfaces_i}")
if vc13 is not None:
    cols13 = attr_arr(m13, "vizcol", field="color", width=4)
    uniq13 = len({tuple(np.round(r, 4)) for r in cols13})
    check("V13c each evaluated face Index gets a distinct color",
          uniq13 == nfaces_i, f"unique={uniq13} faces={nfaces_i}")

print("\n== V14: intrinsic Normal pipes real directions (not +Z default) ==")
nme = bpy.data.meshes.new("Nrm")
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=2.0)
bm.normal_update()
bm.to_mesh(nme)
bm.free()
nobj = bpy.data.objects.new("Nrm", nme)
bpy.context.collection.objects.link(nobj)
viz14 = av.add_visualizer(bpy.context, target=nobj, attribute="Normal",
                          domain="Point", style="RGB", display="Markers")
gs14 = cook(viz14)
m14 = gs14.mesh
vc14 = m14.attributes.get("vizcol") if m14 else None
check("V14a Normal Markers emit vizcol", vc14 is not None)
if vc14 is not None:
    cols14 = attr_arr(m14, "vizcol", field="color", width=4)
    uniq14 = len({tuple(np.round(r, 3)) for r in cols14})
    finite = bool(np.isfinite(cols14).all())
    # Unit normals → RGB auto-range should land in a sane band, not 1e6
    # from zero-span stats on point-cloud Input Normal.
    sane = bool(np.max(np.abs(cols14[:, :3])) < 10.0)
    check("V14b Normal colors vary across vertices",
          uniq14 >= 4, f"unique={uniq14}")
    check("V14c Normal RGB range is finite/sane (baked before M2P)",
          finite and sane,
          f"maxabs={np.max(np.abs(cols14[:, :3])):.3g} finite={finite}")

print("\n== V15: Arrows non-vector → (0,0,0); domain mismatch detect ==")
sme = bpy.data.meshes.new("Scal")
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=2.0)
bm.to_mesh(sme)
bm.free()
sobj = bpy.data.objects.new("Scal", sme)
bpy.context.collection.objects.link(sobj)
h = sme.attributes.new("heat", 'FLOAT', 'POINT')
for i, d in enumerate(h.data):
    d.value = float(i)
viz15 = av.add_visualizer(bpy.context, target=sobj, attribute="heat",
                          domain="Point", style="Heat", display="Arrows")
md15 = av.viz_modifier(viz15)
check("V15a Attr Is Vector false for float",
      av.node_builder.get_input(md15, "Attr Is Vector") is False)
gs15 = cook(viz15)
# Zero-scale instances → no meaningful arrow mesh (or empty)
n15 = len(gs15.mesh.vertices) if gs15.mesh else 0
check("V15b non-vector Arrows emit no shaft geometry",
      n15 == 0, f"verts={n15}")
check("V15c heat missing on Face domain is detected",
      av._attr_available_on_domain(sobj, "heat", "Face") is False)
check("V15d heat present on Point domain",
      av._attr_available_on_domain(sobj, "heat", "Point") is True)

print("\n== V11: per-visualizer engine copies (independent ramps) ==")
g1, g2 = viz.modifiers[0].node_group, viz2.modifiers[0].node_group
r1 = next((n for n in g1.nodes
           if n.bl_idname == 'ShaderNodeValToRGB'), None)
r2 = next((n for n in g2.nodes
           if n.bl_idname == 'ShaderNodeValToRGB'), None)
check("V11 visualizers own distinct engine copies with own ramps",
      g1 is not g2 and r1 is not None and r2 is not None
      and r1.color_ramp is not r2.color_ramp,
      f"g1={g1.name} g2={g2.name}")

print("\n== V16: EEVEE pixels (Material Preview path) + display-only flags ==")
import mathutils  # noqa: E402

def _eevee_max(path, subject):
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and ob is not subject:
            ob.hide_render = True
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.resolution_x = 96
    sc.render.resolution_y = 96
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path)
    pix = np.array(img.pixels[:]).reshape(-1, 4)[:, :3]
    bpy.data.images.remove(img)
    return float(pix.max())


# Camera looking at origin
if bpy.context.scene.camera is None:
    cam_d = bpy.data.cameras.new("AttrVizTestCam")
    cam = bpy.data.objects.new("AttrVizTestCam", cam_d)
    bpy.context.collection.objects.link(cam)
    cam.location = (0.0, -8.0, 3.0)
    direction = (mathutils.Vector((0, 0, 0))
                 - mathutils.Vector(cam.location))
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.camera = cam

pme = bpy.data.meshes.new("PixGrid")
bm = bmesh.new()
bmesh.ops.create_grid(bm, x_segments=7, y_segments=7, size=2.0)
bm.to_mesh(pme)
bm.free()
pobj = bpy.data.objects.new("PixGrid", pme)
bpy.context.collection.objects.link(pobj)
ph = pme.attributes.new("heat", 'FLOAT', 'POINT')
for i, d in enumerate(ph.data):
    d.value = i / max(len(ph.data) - 1, 1)

pix_viz = av.add_visualizer(bpy.context, target=pobj, attribute="heat",
                            domain="Point", style="Heat", display="Surface")
check("V16a visible_camera True (Material Preview needs it)",
      getattr(pix_viz, "visible_camera", True) is True)
check("V16b hide_render True (skip beauty pass)",
      pix_viz.hide_render is True)
# Geometry path already covered; pixel path must not be black when
# temporarily allowed into the beauty pass (same EEVEE shading as Preview).
pix_viz.hide_render = False
pobj.hide_render = True
cook(pix_viz)
rmax = _eevee_max("/tmp/attrviz_v16_surface.png", pix_viz)
check("V16c Surface Heat EEVEE pixels are lit (not black)",
      rmax > 0.1, f"max={rmax:.4f}")
pix_viz.hide_render = True

print("\n== V17: engine group builds complete on this Blender ==")
from attrviz import node_builder as nb  # noqa: E402

# Guards a whole class of Blender-version breakage: a renamed socket
# identifier kills the builder mid-tree, and the half-built group is then
# cached and reused, so the real error resurfaces as a confusing KeyError
# from set_input further downstream (5.0.x A_STR/B_STR vs 5.2 A/B).
eng = nb.ensure_viz_group(force=True)
eng_in = {i.name for i in eng.interface.items_tree
          if i.item_type == 'SOCKET' and i.in_out == 'INPUT'}
_want = {"Target", "Scope", "Attribute", "Domain", "Style", "Display"}
check("V17a engine group has every control socket",
      _want <= eng_in, f"missing={sorted(_want - eng_in)}")
check("V17b completed build carries the version stamp",
      eng.get("attrviz_version") == nb.engine_signature(),
      f"stamp={eng.get('attrviz_version')!r}")

# FunctionNodeCompare STRING inputs: A/B on 5.2, A_STR/B_STR on 5.0.x.
_probe = bpy.data.node_groups.new("attrviz_cmp_probe", "GeometryNodeTree")
_cmp = _probe.nodes.new("FunctionNodeCompare")
_cmp.data_type = 'STRING'
_cmp.operation = 'EQUAL'
try:
    nb._sock_by_id(_cmp, "A", "A_STR")
    nb._sock_by_id(_cmp, "B", "B_STR")
    check("V17c compare STRING sockets resolve on this Blender", True)
except KeyError as exc:  # noqa: BLE001
    check("V17c compare STRING sockets resolve on this Blender", False,
          f"KeyError {exc} — inputs={[s.identifier for s in _cmp.inputs]}")
bpy.data.node_groups.remove(_probe)

# An unstamped group is a failed build: rebuild it, never hand it back.
del eng["attrviz_version"]
_again = nb.ensure_viz_group(force=False)
_again_in = {i.name for i in _again.interface.items_tree
             if i.item_type == 'SOCKET' and i.in_out == 'INPUT'}
check("V17d unstamped (half-built) group is rebuilt, not reused",
      _again.get("attrviz_version") == nb.engine_signature() and "Style" in _again_in,
      f"stamp={_again.get('attrviz_version')!r} n_in={len(_again_in)}")

print("\n== V8: registry + register/unregister smoke ==")
n_viz = len(av.visualizers(bpy.context.scene))
check("V8a visualizers registry lists all entries",
      n_viz == 9,
      f"count={n_viz} {[o.name for o in av.visualizers(bpy.context.scene)]}")
try:
    av.unregister()
    av.register()
    av.unregister()
    check("V8b addon register/unregister clean", True)
except Exception as exc:  # noqa: BLE001
    check("V8b addon register/unregister clean", False, str(exc))

print(f"\n[attrviz tests] {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
