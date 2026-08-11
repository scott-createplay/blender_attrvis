"""Headless tests for AttrViz GPU sampler (Stage B Phase 5).

Does not exercise draw handlers (unavailable in --background).

Run:
  blender --background --factory-startup --python-exit-code 1 \\
      --python tests/test_gpu_sample.py
"""
from __future__ import annotations

import os
import sys

import bpy
import bmesh
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import attrviz as av  # noqa: E402
from attrviz import gpu_color, gpu_sample, node_builder  # noqa: E402

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


def make_grid(name, segments=4, size=2.0):
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


print("\n== AttrViz gpu_sample ==")
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

grid = make_grid("GPUGrid", segments=4)
heat = grid.data.attributes.new("heat", 'FLOAT', 'POINT')
nv = len(heat.data)
for i, d in enumerate(heat.data):
    d.value = i / max(1, nv - 1)
face_id = grid.data.attributes.new("face_id", 'INT', 'FACE')
for i, d in enumerate(face_id.data):
    d.value = i
bpy.context.view_layer.update()

r = gpu_sample.sample_evaluated(grid, "heat", "Point", world_space=False)
check("sample heat", r is not None)
if r:
    pos, vals, dt = r
    check("heat dtype", dt == 'FLOAT', dt)
    check("heat len", len(pos) == nv, f"{len(pos)} vs {nv}")

r2 = gpu_sample.sample_evaluated(grid, "face_id", "Face", world_space=False)
check("sample face_id", r2 is not None)
if r2:
    check("face count", len(r2[0]) == len(grid.data.polygons))

r3 = gpu_sample.sample_evaluated(grid, "Index", "Point", world_space=False)
check("intrinsic Index", r3 is not None and r3[2] == 'INT')

# Visualizer path
viz = av.add_visualizer(
    bpy.context, target=grid, attribute="heat",
    domain="Point", style="Heat", display="Markers",
)
md = av.viz_modifier(viz)
check("viz modifier", md is not None)
result = gpu_sample.sample_visualizer_targets(md, cap=50000)
check("sample via viz modifier", result is not None)
if result:
    check("viz sample n", result[0].shape[0] == nv, str(result[0].shape))

cols = gpu_color.values_to_colors(result[1], result[2], "Heat")
check("heat colors", cols.shape == (nv, 4), str(cols.shape))

# Flag exists after register (already registered via import side? need register)
av.register()
check("gpu markers flag default off",
      getattr(bpy.context.scene, "attrviz_gpu_markers", None) is False
      or bpy.context.scene.attrviz_gpu_markers is False)

# Existing geometry path still emits markers when GPU off
gs = None
viz.update_tag()
bpy.context.view_layer.update()
deps = bpy.context.evaluated_depsgraph_get()
deps.update()
gs = viz.evaluated_get(deps).evaluated_geometry()
mesh = gs.mesh
npts = len(mesh.vertices) if mesh else 0
check("GN markers still emit when GPU off", npts >= nv * 12, f"verts={npts}")

print(f"\n== Result: {PASS} passed, {FAIL} failed ==")
if FAIL:
    sys.exit(1)
print("ALL GPU SAMPLE TESTS PASSED")
