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
from attrviz import gpu_sample, node_builder  # noqa: E402

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

print(f"\n== Result: {PASS} passed, {FAIL} failed ==")
if FAIL:
    sys.exit(1)
print("ALL WATCH COLLECTION TESTS PASSED")
