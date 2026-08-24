"""Repro: attrvis-wide mute ignores which objects a visualizer can draw on.

Two meshes in attrvis. Only ONE carries the attribute "K". A single Surface
visualizer on "K" is enabled. Expected: the mesh that has K is muted (its
overlay replaces it); the mesh that does NOT have K stays visible, because
nothing is drawn in its place.

    blender --background --factory-startup --python-exit-code 1 \
      --python dev_tasks/010_mute_scope/mute_scope_repro.py
"""
import os
import sys

import bpy
import bmesh

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import attrviz as av
from attrviz import gpu_overlay, gpu_sample

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok    {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}   {detail}")


def make_grid(name):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=2, y_segments=2, size=2.0)
    bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    return obj


bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
av.register()
bpy.context.scene.attrviz_gpu_markers = True

has_K = make_grid("HasK")
no_K = make_grid("NoK")
a = has_K.data.attributes.new("K", 'FLOAT', 'POINT')
for d in a.data:
    d.value = 0.5

av._link_to_watch(bpy.context, [has_K, no_K])
watch = gpu_sample.scene_watch_collection()
print(f"\nattrvis holds: {[o.name for o in watch.objects]}")
print(f"HasK attributes: {[x.name for x in has_K.data.attributes]}")
print(f"NoK  attributes: {[x.name for x in no_K.data.attributes]}")

before = (has_K.display_type, no_K.display_type)
print(f"before viz: HasK={before[0]}  NoK={before[1]}")

viz = av.add_visualizer(bpy.context, scope=watch, attribute="K",
                        domain="Point", style="Heat", display="Surface")
print(f"\nafter enabling ONE Surface viz on 'K':")
print(f"  HasK display_type = {has_K.display_type}")
print(f"  NoK  display_type = {no_K.display_type}")

check("object carrying 'K' is muted", has_K.display_type == "BOUNDS",
      has_K.display_type)
check("object WITHOUT 'K' stays visible", no_K.display_type == before[1],
      f"muted to {no_K.display_type} but no overlay can be drawn on it")

# What does the sampler actually produce for the attribute-less object?
from attrviz import viz_modifier
md = viz_modifier(viz)
targets = gpu_sample.watch_meshes_for_visualizer(md)
print(f"\n  visualizer watch set: {[o.name for o in targets]}")
mute_targets = gpu_overlay._active_surface_watch_meshes(bpy.context.scene)
print(f"  mute target set:      {[o.name for o, _w in mute_targets]}")

# Now disable it and confirm both restore.
viz.attrviz_enabled = False
print(f"\nafter disabling the viz:")
print(f"  HasK display_type = {has_K.display_type}")
print(f"  NoK  display_type = {no_K.display_type}")
check("disabling the only viz restores HasK",
      has_K.display_type == before[0], has_K.display_type)
check("disabling the only viz restores NoK",
      no_K.display_type == before[1], no_K.display_type)

print(f"\n== Result: {PASS} passed, {FAIL} failed ==")
sys.exit(1 if FAIL else 0)
