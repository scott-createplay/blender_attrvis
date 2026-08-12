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

# Visualizer path + arrows honesty
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

# Arrows honesty: float → empty line geometry
from attrviz import gpu_overlay  # noqa: E402
arrow_entry = gpu_overlay._refresh_arrows(
    viz, md, result[0], result[1], result[2])
check("arrows on float → empty",
      arrow_entry.get("empty") is True or arrow_entry.get("batch") is None)

# Normal as vector arrows (4-sided cones)
r_n = gpu_sample.sample_evaluated(grid, "Normal", "Point", world_space=True)
check("sample Normal", r_n is not None and r_n[2] == 'FLOAT_VECTOR')
if r_n:
    a2 = gpu_overlay._refresh_arrows(viz, md, r_n[0], r_n[1], r_n[2])
    check("arrows on Normal produce cones",
          a2.get("n", 0) > 0 or a2.get("cone_verts", 0) > 0,
          str(a2))
    check("arrows instanced or soup fallback",
          a2.get("mode") == "instanced" or a2.get("cone_verts", 0) > 0,
          f"mode={a2.get('mode')} keys={list(a2.keys())}")
    if a2.get("mode") == "instanced":
        check("instanced count matches alive",
              a2.get("instance_count") == a2.get("n"),
              str(a2.get("instance_count")))
        print(f"  arrows path: INSTANCED n={a2.get('n')}")
    else:
        print(f"  arrows path: SOUP fallback (no GPU context) n={a2.get('n')}")
    # Geometry builder alone (soup oracle)
    cone, n_a = gpu_overlay._arrow_cone_geometry(
        r_n[0], r_n[1], 0.08, 0.01, sides=4)
    check("cone verts = arrows * 4 sides * 3",
          cone is not None and len(cone) == n_a * 12,
          f"verts={None if cone is None else len(cone)} n={n_a}")
    origins, dirs, n_f = gpu_overlay._arrow_alive_frames(r_n[0], r_n[1])
    check("alive frames match soup arrow count",
          n_f == n_a, f"frames={n_f} soup={n_a}")

# Surface tris — identity topology (no inflate / filter / face stride)
node_builder.set_input(md, "Display", "Surface")
node_builder.set_input(md, "Domain", "Point")
surf = gpu_sample.build_surface_tris(md, style="Heat")
check("surface tris build", surf is not None)
if surf:
    spos, svals, sdt, ntri = surf
    check("surface tri verts multiple of 3", len(spos) % 3 == 0, str(len(spos)))
    check("surface corner values match verts", len(svals) == len(spos))
    check("surface has triangles", ntri > 0, str(ntri))
    scols = gpu_color.values_to_colors(svals, sdt, "Heat")
    check("surface colors match verts", len(scols) == len(spos))
    print(f"  surface stats: tris={ntri} verts={len(spos)} dtype={sdt}")

    # Identity contract vs evaluated loop_triangles × matrix_world
    deps = bpy.context.evaluated_depsgraph_get()
    ev = grid.evaluated_get(deps)
    me = ev.data
    me.calc_loop_triangles()
    n_lt = len(me.loop_triangles)
    check("surface n_tris == loop_triangles", ntri == n_lt, f"{ntri} vs {n_lt}")
    cos = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("co", cos)
    cos = cos.reshape(-1, 3)
    expect = np.empty((n_lt * 3, 3), dtype=np.float32)
    k = 0
    for tri in me.loop_triangles:
        for vi in tri.vertices:
            expect[k] = cos[vi]
            k += 1
    mw = np.array(ev.matrix_world, dtype=np.float64).reshape(4, 4)
    hom = np.empty((len(expect), 4), dtype=np.float64)
    hom[:, :3] = expect
    hom[:, 3] = 1.0
    expect_w = (hom @ mw.T)[:, :3].astype(np.float32)
    delta = np.max(np.abs(spos - expect_w)) if len(spos) == len(expect_w) else 1e9
    check("surface positions identity (no inflate)", delta < 1e-5, f"max_delta={delta}")

node_builder.set_input(md, "Domain", "Face")
node_builder.set_input(md, "Attribute", "face_id")
surf_f = gpu_sample.build_surface_tris(md, style="Random")
check("surface face_id build", surf_f is not None and surf_f[3] > 0)
if surf_f:
    grid.data.calc_loop_triangles()
    check("surface face n_tris == loop_triangles",
          surf_f[3] == len(grid.data.loop_triangles),
          f"{surf_f[3]} vs {len(grid.data.loop_triangles)}")

# Restore Markers for GN fallback check
node_builder.set_input(md, "Display", "Markers")
node_builder.set_input(md, "Attribute", "heat")
node_builder.set_input(md, "Domain", "Point")

# Flag exists after register (already registered via import side? need register)
av.register()
check("gpu overlay flag default on",
      bool(bpy.context.scene.attrviz_gpu_markers) is True)

# Surface solid mute (z-fight): Target display_type → WIRE while Surface GPU on
prev_dt = grid.display_type
node_builder.set_input(md, "Display", "Surface")
bpy.context.scene.attrviz_gpu_markers = True
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("surface mute → WIRE", grid.display_type == "WIRE",
      f"display_type={grid.display_type}")
check("surface mute stashed prior",
      "attrviz_surface_mute_prev" in grid)
node_builder.set_input(md, "Display", "Markers")
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("markers restores solid display",
      grid.display_type == prev_dt,
      f"display_type={grid.display_type} expected={prev_dt}")
check("surface mute prop cleared",
      "attrviz_surface_mute_prev" not in grid)

# Existing geometry path still emits markers when GPU off
bpy.context.scene.attrviz_gpu_markers = False
node_builder.set_input(md, "Display", "Markers")
md.show_viewport = True
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
