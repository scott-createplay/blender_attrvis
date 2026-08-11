"""Headless tests for probe sample plumbing (Phase 1).

Run:
  blender --background --factory-startup --python-exit-code 1 \\
      --python dev_tasks/001_gpu_overlay/tests/test_probe_sample.py
"""
from __future__ import annotations

import os
import sys

import bpy
import bmesh
import numpy as np

TASK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(TASK))
sys.path.insert(0, TASK)

from probe import sample  # noqa: E402
from probe.build_fixture import author_attributes  # noqa: E402
from probe import color_map  # noqa: E402

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
    """segments = edge divisions; verts = (segments+1)^2 for create_grid."""
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


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)


print("\n== Probe Phase 1: sample_evaluated ==")
clear_scene()

# Known grid: x_segments=4 → 5×5 = 25 verts; 4×4 = 16 faces
SEG = 4
grid = make_grid("ProbeTestGrid", segments=SEG, size=2.0)
stats = author_attributes(grid)
n_verts = len(grid.data.vertices)
n_faces = len(grid.data.polygons)
expected_verts = (SEG + 1) ** 2
expected_faces = SEG * SEG

check("grid vertex count", n_verts == expected_verts,
      f"got {n_verts} want {expected_verts}")
check("grid face count", n_faces == expected_faces,
      f"got {n_faces} want {expected_faces}")

# Force depsgraph eval
bpy.context.view_layer.update()

# POINT / heat
result = sample.sample_evaluated(grid, "heat", 'POINT', world_space=False)
check("heat sample returns", result is not None)
if result:
    pos, vals, dtype = result
    check("heat dtype FLOAT", dtype == 'FLOAT', dtype)
    check("heat length == verts", len(pos) == n_verts and len(vals) == n_verts,
          f"pos={len(pos)} vals={len(vals)} n={n_verts}")
    check("heat values in [0,1]", float(vals.min()) >= -1e-4 and float(vals.max()) <= 1.0 + 1e-4,
          f"min={vals.min()} max={vals.max()}")
    # Match authored: first vertex value via foreach
    authored = np.empty(n_verts, dtype=np.float32)
    grid.data.attributes["heat"].data.foreach_get("value", authored)
    check("heat values match authored",
          np.allclose(vals, authored, atol=1e-5),
          f"max_delta={np.max(np.abs(vals - authored))}")
    print(f"  stats heat: {sample.buffer_stats(result)}")

# FACE / face_id
result_f = sample.sample_evaluated(grid, "face_id", 'FACE', world_space=False)
check("face_id sample returns", result_f is not None)
if result_f:
    pos_f, vals_f, dtype_f = result_f
    check("face_id dtype INT", dtype_f == 'INT', dtype_f)
    check("face_id length == faces",
          len(pos_f) == n_faces and len(vals_f) == n_faces,
          f"pos={len(pos_f)} vals={len(vals_f)} n={n_faces}")
    check("face_id is 0..n-1",
          int(vals_f.min()) == 0 and int(vals_f.max()) == n_faces - 1,
          f"min={vals_f.min()} max={vals_f.max()}")
    # Face centers: compare first poly
    expected_c0 = np.array(grid.data.polygons[0].center, dtype=np.float32)
    check("face center[0] matches",
          np.allclose(pos_f[0], expected_c0, atol=1e-5),
          f"got {pos_f[0]} want {expected_c0}")
    print(f"  stats face_id: {sample.buffer_stats(result_f)}")

# flow vector
result_v = sample.sample_evaluated(grid, "flow", 'POINT', world_space=False)
check("flow sample returns", result_v is not None)
if result_v:
    pos_v, vals_v, dtype_v = result_v
    check("flow dtype FLOAT_VECTOR", dtype_v == 'FLOAT_VECTOR', dtype_v)
    check("flow shape Nx3", vals_v.shape == (n_verts, 3), str(vals_v.shape))
    print(f"  stats flow: {sample.buffer_stats(result_v)}")

# Missing attr
missing = sample.sample_evaluated(grid, "nope_missing", 'POINT')
check("missing attr → None", missing is None)

# World space: move object and confirm positions change
grid.location = (10.0, 0.0, 0.0)
bpy.context.view_layer.update()
result_w = sample.sample_evaluated(grid, "heat", 'POINT', world_space=True)
result_l = sample.sample_evaluated(grid, "heat", 'POINT', world_space=False)
if result_w and result_l:
    check("world positions offset by location",
          np.allclose(result_w[0][:, 0], result_l[0][:, 0] + 10.0, atol=1e-4),
          f"w0={result_w[0][0]} l0={result_l[0][0]}")

print("\n== Probe Phase 1: color_map ==")
heat_cols = color_map.heat_colors(np.array([0.0, 0.5, 1.0], dtype=np.float32))
check("heat_colors shape", heat_cols.shape == (3, 4), str(heat_cols.shape))
check("heat low is bluish", heat_cols[0, 2] > heat_cols[0, 0],
      str(heat_cols[0]))
check("heat high is reddish", heat_cols[2, 0] > heat_cols[2, 2],
      str(heat_cols[2]))

hash_a = color_map.hash_colors(np.array([1, 2, 1], dtype=np.int32))
check("hash stable for same id",
      np.allclose(hash_a[0], hash_a[2]), str(hash_a))
check("hash differs across ids",
      not np.allclose(hash_a[0], hash_a[1]), str(hash_a))

print(f"\n== Result: {PASS} passed, {FAIL} failed ==")
if FAIL:
    sys.exit(1)
print("ALL PROBE SAMPLE TESTS PASSED")
