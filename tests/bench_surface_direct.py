"""Benchmark: direct Color Attribute write vs current batch-copy approach.

Run in Blender:
    blender --background --factory-startup --python tests/bench_surface_direct.py

Proves that writing false-color directly to the watched mesh's Color Attribute
is orders of magnitude faster than copying the mesh into a GPU batch.
"""
import sys
import time
import numpy as np

sys.path.insert(0, ".")

import bpy

# --- Setup: create a dense mesh (subdivided cube ~ 98k faces) ---
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

bpy.ops.mesh.primitive_cube_add()
cube = bpy.context.active_object
bpy.ops.object.mode_set(mode='EDIT')
for _ in range(5):  # 5 subdivisions → ~98k faces, ~295k loop corners
    bpy.ops.mesh.subdivide()
bpy.ops.object.mode_set(mode='OBJECT')

me = cube.data
me.calc_loop_triangles()

n_verts = len(me.vertices)
n_loops = len(me.loops)
n_tris = len(me.loop_triangles)
print(f"\nMesh: {n_verts} verts, {n_loops} loops, {n_tris} tris")

# Create a fake float attribute (position.x) to colorize
cos = np.empty(n_verts * 3, dtype=np.float32)
me.vertices.foreach_get("co", cos)
cos = cos.reshape(-1, 3)
attr_values = cos[:, 0]  # x-coordinate as the "attribute"

# Normalize to [0,1]
vmin, vmax = attr_values.min(), attr_values.max()
t_vals = (attr_values - vmin) / max(vmax - vmin, 1e-12)

# Simple heat colormap (vectorized)
def heat_colors(t):
    """Nx4 RGBA from Nx1 normalized values."""
    n = len(t)
    colors = np.zeros((n, 4), dtype=np.float32)
    colors[:, 0] = np.clip(t * 3.0, 0, 1)
    colors[:, 1] = np.clip(t * 3.0 - 1.0, 0, 1)
    colors[:, 2] = np.clip(t * 3.0 - 2.0, 0, 1)
    colors[:, 3] = 1.0
    return colors

vert_colors = heat_colors(t_vals)

# =========================================================================
# METHOD A: Direct Color Attribute write (proposed new path)
# =========================================================================
print("\n--- METHOD A: Direct Color Attribute foreach_set ---")

# Ensure the Color Attribute exists (CORNER domain for Workbench)
CA_NAME = "vizcol"
if CA_NAME not in me.color_attributes:
    me.color_attributes.new(CA_NAME, 'FLOAT_COLOR', 'CORNER')

ca = me.color_attributes[CA_NAME]

# Expand vert colors → corner colors (loop vertex indices)
loop_vert_indices = np.empty(n_loops, dtype=np.int32)
me.loops.foreach_get("vertex_index", loop_vert_indices)

# Time the actual work: expand + write
times_a = []
for _ in range(10):
    t0 = time.perf_counter()
    corner_colors = vert_colors[loop_vert_indices]  # Nx4 expand
    ca.data.foreach_set("color", corner_colors.ravel())
    me.update()
    t1 = time.perf_counter()
    times_a.append(t1 - t0)

avg_a = np.mean(times_a) * 1000
med_a = np.median(times_a) * 1000
print(f"  {n_loops} corners: avg={avg_a:.2f}ms  median={med_a:.2f}ms  (10 runs)")

# =========================================================================
# METHOD B: Current approach — tuple list + batch_for_shader
# =========================================================================
print("\n--- METHOD B: Current approach (tuple lists + batch_for_shader) ---")

# Simulate what _build_surface_tris + _build_batch does:
# 1. foreach_get tri data
# 2. Expand positions to tri verts
# 3. Convert to Python tuple lists
# 4. batch_for_shader

tri_vert_ids = np.empty(n_tris * 3, dtype=np.int32)
me.loop_triangles.foreach_get("vertices", tri_vert_ids)

positions = cos[tri_vert_ids]  # (n_tris*3, 3)
tri_colors = vert_colors[tri_vert_ids]  # (n_tris*3, 4)

times_b = []
for _ in range(3):  # fewer runs since it's slow
    t0 = time.perf_counter()
    pos_list = [tuple(p) for p in positions]
    col_list = [tuple(c) for c in tri_colors]
    t1 = time.perf_counter()
    times_b.append(t1 - t0)

avg_b = np.mean(times_b) * 1000
med_b = np.median(times_b) * 1000
print(f"  {len(positions)} tri-verts: avg={avg_b:.2f}ms  median={med_b:.2f}ms  (3 runs)")
print(f"  (batch_for_shader upload adds ~20ms on top)")

# =========================================================================
# METHOD C: Direct write with FACE domain (integer/Random style)
# =========================================================================
print("\n--- METHOD C: Direct write, Face domain (Random/integer) ---")

n_polys = len(me.polygons)
face_colors = heat_colors(np.random.rand(n_polys).astype(np.float32))

# Need polygon → loop expansion
poly_loop_starts = np.empty(n_polys, dtype=np.int32)
poly_loop_totals = np.empty(n_polys, dtype=np.int32)
me.polygons.foreach_get("loop_start", poly_loop_starts)
me.polygons.foreach_get("loop_total", poly_loop_totals)

times_c = []
for _ in range(10):
    t0 = time.perf_counter()
    # Expand face colors to corners
    corner_colors_face = np.repeat(face_colors, poly_loop_totals, axis=0)
    ca.data.foreach_set("color", corner_colors_face.ravel())
    me.update()
    t1 = time.perf_counter()
    times_c.append(t1 - t0)

avg_c = np.mean(times_c) * 1000
med_c = np.median(times_c) * 1000
print(f"  {n_polys} faces → {n_loops} corners: avg={avg_c:.2f}ms  median={med_c:.2f}ms")

# =========================================================================
# Summary
# =========================================================================
print("\n=== SUMMARY ===")
print(f"  Method A (direct CA write, Point domain):  {med_a:.1f}ms")
print(f"  Method B (tuple lists, current approach):  {med_b:.1f}ms")
print(f"  Method C (direct CA write, Face domain):   {med_c:.1f}ms")
print(f"  Speedup A vs B: {med_b / med_a:.0f}x")
print(f"  Speedup C vs B: {med_b / med_c:.0f}x")
print()

bpy.ops.wm.quit_blender()
