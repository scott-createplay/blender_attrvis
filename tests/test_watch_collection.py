"""Headless tests for the scene-level attrvis watch collection.

Run:
  blender --background --factory-startup --python-exit-code 1 \\
      --python tests/test_watch_collection.py
"""
from __future__ import annotations

import os
import sys

import bpy
import bmesh

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import attrviz as av  # noqa: E402
from attrviz import gpu_overlay, gpu_sample, node_builder  # noqa: E402

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


def make_grid(name, segments=2, size=2.0):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(
        bm, x_segments=segments, y_segments=segments, size=size,
    )
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    return obj


print("\n== Watch collection attrvis ==")
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
av.register()

check("API add_visualizer(target=) does not create attrvis",
      bpy.data.collections.get(av.WATCH_COLLECTION) is None)
grid = make_grid("APIGrid")
av.add_visualizer(
    bpy.context, target=grid, attribute="position",
    domain="Point", style="Heat", display="Markers")
check("API target= still does not create attrvis",
      bpy.data.collections.get(av.WATCH_COLLECTION) is None)

watch = av._ensure_watch_collection(bpy.context)
viz_coll = bpy.data.collections.get(av.VIZ_COLLECTION)
check("attrvis exists", watch is not None)
check("attrvis ≠ Visualizers",
      viz_coll is not None and watch != viz_coll)
check("attrvis linked under scene",
      watch.name in bpy.context.scene.collection.children)

a = make_grid("WatchA")
b = make_grid("WatchB")
c = make_grid("WatchC")
for o in (a, b, c):
    heat = o.data.attributes.new("heat", 'FLOAT', 'POINT')
    for d in heat.data:
        d.value = 0.5

for o in list(bpy.context.view_layer.objects):
    o.select_set(False)
a.select_set(True)
b.select_set(True)
c.select_set(True)
bpy.context.view_layer.objects.active = a

viz_w = av.add_visualizer_from_selection(
    bpy.context, attribute="heat", domain="Point",
    style="Heat", display="Markers")
md_w = av.viz_modifier(viz_w)
scope_w = node_builder.get_input(md_w, "Scope")
target_w = node_builder.get_input(md_w, "Target")
check("GUI add-viz Scope is attrvis", scope_w == watch)
check("GUI add-viz Target unset", target_w is None)
check("multi-select linked into attrvis",
      all(watch in o.users_collection for o in (a, b, c)))
meshes_w = gpu_sample.iter_watch_meshes(target_w, scope_w)
check("iter_watch_meshes covers all three",
      set(meshes_w) >= {a, b, c},
      f"got={[o.name for o in meshes_w]}")

av._link_to_watch(bpy.context, [a, b, c])
check("re-link is a no-op",
      all(watch in o.users_collection for o in (a, b, c)))

# Surface mute must follow Add/Remove objects (not only add-viz).
bpy.context.scene.attrviz_gpu_markers = True
prev_dt = {o.name: o.display_type for o in (a, b, c)}
viz_surf = av.add_visualizer_from_selection(
    bpy.context, attribute="heat", domain="Point",
    style="Heat", display="Surface")
check("add Surface viz mutes watch set to BOUNDS",
      all(o.display_type == "BOUNDS" for o in (a, b, c)),
      str({o.name: o.display_type for o in (a, b, c)}))
av._unlink_from_watch(bpy.context, [c])
check("remove objects restores mute on C",
      c.display_type == prev_dt["WatchC"],
      f"display_type={c.display_type} expected={prev_dt['WatchC']}")
check("remove objects keeps mute on remaining",
      a.display_type == "BOUNDS" and b.display_type == "BOUNDS",
      f"A={a.display_type} B={b.display_type}")
av._link_to_watch(bpy.context, [c])
check("add objects mutes newly watched mesh",
      c.display_type == "BOUNDS", f"display_type={c.display_type}")

# File reopen: in-memory mute set is gone; newly added meshes load Solid.
gpu_overlay._muted_ptrs.clear()
a.display_type = prev_dt["WatchA"]
b.display_type = prev_dt["WatchB"]
c.display_type = prev_dt["WatchC"]
gpu_overlay._on_load_post(None)
check("load_post re-mutes watch set to BOUNDS",
      all(o.display_type == "BOUNDS" for o in (a, b, c)),
      str({o.name: o.display_type for o in (a, b, c)}))

av._unlink_from_watch(bpy.context, [c])
check("second remove restores C again",
      c.display_type == prev_dt["WatchC"],
      f"display_type={c.display_type}")
bpy.data.objects.remove(viz_surf, do_unlink=True)
av._sync_watch_draw(bpy.context)
check("remove Surface viz restores remaining mutes",
      a.display_type == prev_dt["WatchA"]
      and b.display_type == prev_dt["WatchB"],
      f"A={a.display_type} B={b.display_type}")

child = bpy.data.collections.new("attrvis_nested")
watch.children.link(child)
nested = make_grid("WatchNested")
for coll in list(nested.users_collection):
    coll.objects.unlink(nested)
child.objects.link(nested)
meshes_n = gpu_sample.iter_watch_meshes(None, watch)
check("nested collection meshes included",
      nested in meshes_n, f"got={[o.name for o in meshes_n]}")

av._unlink_from_watch(bpy.context, [c])
check("remove unlinks from attrvis", watch not in c.users_collection)
check("remove does not delete the object",
      bpy.data.objects.get(c.name) is c)
check("removed object still in some collection",
      len(c.users_collection) >= 1)

for o in list(bpy.context.view_layer.objects):
    o.select_set(False)
viz_w.select_set(True)
bpy.context.view_layer.objects.active = viz_w
cands = av._watch_candidates(bpy.context)
check("viz carrier skipped as watch candidate",
      viz_w not in cands)

scol = bpy.data.collections.new("ScopeOverride")
bpy.context.scene.collection.children.link(scol)
solo = make_grid("ScopeSolo")
for coll in list(solo.users_collection):
    coll.objects.unlink(solo)
scol.objects.link(solo)
viz_s = av.add_visualizer(
    bpy.context, scope=scol, attribute="heat", domain="Point",
    style="Heat", display="Markers")
md_s = av.viz_modifier(viz_s)
check("API scope= override is not attrvis",
      node_builder.get_input(md_s, "Scope") == scol)
check("API scope= does not force attrvis membership",
      watch not in solo.users_collection)

heat_s = solo.data.attributes.new("heat", 'FLOAT', 'POINT')
for d in heat_s.data:
    d.value = 0.5
bpy.context.view_layer.update()

def _drain_coll(coll):
    for obj in list(coll.objects):
        coll.objects.unlink(obj)
    for ch in list(coll.children):
        _drain_coll(ch)

_drain_coll(watch)
check("drained attrvis has no meshes",
      gpu_sample.iter_watch_meshes(None, watch) == [])
r_empty = gpu_sample.sample_visualizer_targets(md_s, cap=50000)
check("empty attrvis suppresses per-viz Scope",
      r_empty is None or len(r_empty[0]) == 0,
      str(None if r_empty is None else len(r_empty[0])))

bpy.data.collections.remove(watch)
r_fb = gpu_sample.sample_visualizer_targets(md_s, cap=50000)
check("no attrvis → Scope fallback samples",
      r_fb is not None and len(r_fb[0]) > 0,
      str(None if r_fb is None else len(r_fb[0])))

print("\n== 006: POINTCLOUD watch candidates ==")


def make_pointcloud(name, n=8):
    me = bpy.data.meshes.new(name + "_mesh")
    me.vertices.add(n)
    for i in range(n):
        me.vertices[i].co = (float(i), 0.0, 0.0)
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    for o in list(bpy.context.view_layer.objects):
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.convert(target='POINTCLOUD')
    return bpy.context.view_layer.objects.active


# Recreate attrvis — previous block removed it for the Scope fallback test.
watch = av._ensure_watch_collection(bpy.context)
pc_w = make_pointcloud("WatchCloud", n=8)
heat_w = pc_w.data.attributes.new("heat", 'FLOAT', 'POINT')
for d in heat_w.data:
    d.value = 0.5
bpy.context.view_layer.update()
av._link_to_watch(bpy.context, [pc_w])
check("cloud linked into attrvis", watch in pc_w.users_collection)
watched = gpu_sample.iter_watch_meshes(None, watch)
check("iter_watch_meshes includes POINTCLOUD",
      pc_w in watched, f"got={[o.name for o in watched]}")

for o in list(bpy.context.view_layer.objects):
    o.select_set(False)
pc_w.select_set(True)
bpy.context.view_layer.objects.active = pc_w
cands_pc = av._watch_candidates(bpy.context)
check("_watch_candidates includes POINTCLOUD", pc_w in cands_pc)

print("\n== 006 P4: attrvis point-cloud mute ==")
bpy.context.scene.attrviz_gpu_markers = True
for v in list(av.visualizers(bpy.context.scene)):
    v.hide_viewport = True
gpu_overlay.suppress_gn_carriers(bpy.context.scene)

mesh_p4 = make_grid("P4WatchMesh")
heat_m4 = mesh_p4.data.attributes.new("heat", 'FLOAT', 'POINT')
for d in heat_m4.data:
    d.value = 0.5
av._link_to_watch(bpy.context, [mesh_p4])
prev_pc_w = pc_w.display_type
prev_mesh_p4 = mesh_p4.display_type
check("P4 isolated: cloud not muted", gpu_overlay._MUTE_PROP not in pc_w)
check("P4 isolated: mesh not muted", gpu_overlay._MUTE_PROP not in mesh_p4)

viz_mk = av.add_visualizer(
    bpy.context, scope=watch, attribute="heat",
    domain="Point", style="Heat", display="Markers")
check("P4 Markers only: cloud BOUNDS", pc_w.display_type == "BOUNDS",
      pc_w.display_type)
check("P4 Markers only: cloud mute prop", gpu_overlay._MUTE_PROP in pc_w)
check("P4 Markers only: mesh original",
      mesh_p4.display_type == prev_mesh_p4, mesh_p4.display_type)

viz_sf = av.add_visualizer(
    bpy.context, scope=watch, attribute="heat",
    domain="Point", style="Heat", display="Surface")
check("P4 both on: cloud BOUNDS", pc_w.display_type == "BOUNDS",
      pc_w.display_type)
check("P4 both on: mesh BOUNDS", mesh_p4.display_type == "BOUNDS",
      mesh_p4.display_type)

viz_mk.hide_viewport = True
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("P4 Surface only: mesh BOUNDS", mesh_p4.display_type == "BOUNDS",
      mesh_p4.display_type)
check("P4 Surface only: cloud restored",
      pc_w.display_type == prev_pc_w, pc_w.display_type)

viz_sf.hide_viewport = True
viz_mk.hide_viewport = False
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("P4 Markers again: cloud BOUNDS", pc_w.display_type == "BOUNDS",
      pc_w.display_type)
check("P4 Markers again: mesh restored",
      mesh_p4.display_type == prev_mesh_p4, mesh_p4.display_type)

av._unlink_from_watch(bpy.context, [pc_w])
check("P4 unlink cloud restores",
      pc_w.display_type == prev_pc_w, pc_w.display_type)
av._link_to_watch(bpy.context, [pc_w])
check("P4 relink cloud mutes", pc_w.display_type == "BOUNDS",
      pc_w.display_type)

gpu_overlay._muted_ptrs.clear()
pc_w.display_type = prev_pc_w
mesh_p4.display_type = prev_mesh_p4
gpu_overlay._on_load_post(None)
check("P4 load_post remutes cloud", pc_w.display_type == "BOUNDS",
      pc_w.display_type)
check("P4 load_post does not mute mesh (Markers only)",
      mesh_p4.display_type == prev_mesh_p4, mesh_p4.display_type)

print(f"\n== Result: {PASS} passed, {FAIL} failed ==")
if FAIL:
    sys.exit(1)
print("ALL WATCH COLLECTION TESTS PASSED")
