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
                        style="Heat", display="Markers")
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
                         attribute="flow", style="Heat",
                         display="Arrows")
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
                         style="Heat", display="Markers")
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
                         attribute="position", style="RGB",
                         display="Surface")
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

print("\n== V10: auto-pick table (the RMB defaults, pinned) ==")
table = ((('FLOAT_VECTOR', True), ("RGB", "Surface")),
         (('FLOAT_VECTOR', False), ("RGB", "Markers")),
         (('FLOAT2', True), ("RGB", "Surface")),
         (('FLOAT', True), ("Heat", "Surface")),
         (('FLOAT', False), ("Heat", "Markers")),
         (('INT', False), ("Heat", "Markers")))
ok10 = all(av.auto_pick(*args) == want for args, want in table)
check("V10 auto_pick matches the pinned table", ok10,
      str([(a, av.auto_pick(*a)) for a, _ in table]))

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

print("\n== V8: registry + register/unregister smoke ==")
check("V8a visualizers registry lists all four",
      len(av.visualizers(bpy.context.scene)) == 4,
      str([o.name for o in av.visualizers(bpy.context.scene)]))
try:
    av.register()
    av.unregister()
    check("V8b addon register/unregister clean", True)
except Exception as exc:  # noqa: BLE001
    check("V8b addon register/unregister clean", False, str(exc))

print(f"\n[attrviz tests] {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
