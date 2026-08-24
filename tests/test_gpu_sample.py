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
from attrviz import overlay_kind  # noqa: E402
from attrviz import tags_draw  # noqa: E402

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


def make_vert_mesh(name, n=8):
    me = bpy.data.meshes.new(name)
    me.vertices.add(n)
    for i in range(n):
        me.vertices[i].co = (float(i % 4), float(i // 4), 0.0)
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    return obj


def make_pointcloud(name, n=8, loc=(0.0, 0.0, 0.0)):
    """Native POINTCLOUD via mesh convert (Python cannot points.add)."""
    src = make_vert_mesh(name, n)
    src.location = loc
    for o in list(bpy.context.view_layer.objects):
        o.select_set(False)
    src.select_set(True)
    bpy.context.view_layer.objects.active = src
    bpy.ops.object.convert(target='POINTCLOUD')
    obj = bpy.context.view_layer.objects.active
    bpy.context.view_layer.update()
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

check("attr_text decodes bytes", gpu_sample.attr_text(b"FLAT") == "FLAT")
check("attr_text passes str", gpu_sample.attr_text("GARAGE") == "GARAGE")
check("tag fmt STRING drops b-prefix",
      tags_draw._fmt_value(b"FLAT", "STRING", 2) == "FLAT")

label_attr = grid.data.attributes.new("sign_text", "STRING", "POINT")
raw = b"SUSHI"
for d in label_attr.data:
    try:
        d.value = raw
    except TypeError:
        d.value = "SUSHI"
bpy.context.view_layer.update()
r_s = gpu_sample.sample_evaluated(grid, "sign_text", "Point", world_space=False)
check("sample STRING", r_s is not None and r_s[2] == "STRING")
if r_s:
    sample0 = gpu_sample.attr_text(r_s[1][0])
    check("sample STRING has no b-prefix",
          sample0 == "SUSHI" and not sample0.startswith("b'"),
          repr(sample0))

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

# Surface mute: Target hidden (BOUNDS) while Surface GPU on — no z-fight
prev_dt = grid.display_type
node_builder.set_input(md, "Display", "Surface")
bpy.context.scene.attrviz_gpu_markers = True
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("surface mute → BOUNDS", grid.display_type == "BOUNDS",
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

# Density 0.0 must stay 0.0 (not coerced by ``or 1.0``) and yield empty sample
node_builder.set_input(md, "Density", 0.0)
sock = gpu_overlay._socket_bundle(md)
check("density 0.0 socket read preserves zero",
      sock["density"] == 0.0, f"density={sock['density']}")
r0 = gpu_sample.sample_visualizer_targets(md, density=sock["density"], seed=0, cap=50000)
check("density 0.0 → empty sample",
      r0 is not None and len(r0[0]) == 0, str(None if r0 is None else len(r0[0])))
node_builder.set_input(md, "Density", 1.0)

# --- Tags Cap policy (Phase 7c) ------------------------------------------
node_builder.set_input(md, "Display", "Tags")
node_builder.set_input(md, "Attribute", "heat")
node_builder.set_input(md, "Domain", "Point")
cam = (0.0, -10.0, 2.0)

rows0 = tags_draw._collect_tags(md, cam, cap=0, facing_cull=False)
check("tag cap 0 → empty collect", rows0 == [])

rows_all = tags_draw._collect_tags(md, cam, cap=5, facing_cull=False)
check("collect does not nearest-slice under cap",
      len(rows_all) == nv, f"{len(rows_all)} vs {nv}")

# Screen-bin: near cluster vs far spread — nearest-N would take only cluster
sx = np.concatenate([np.full(40, 10.0), np.linspace(0.0, 800.0, 40)])
sy = np.concatenate([np.full(40, 10.0), np.linspace(0.0, 600.0, 40)])
depth = np.concatenate([
    np.linspace(0.1, 0.4, 40),
    np.linspace(5.0, 10.0, 40),
])
pick = tags_draw.screen_bin_select(sx, sy, depth, cap=16, rw=800, rh=600)
check("bin count ≤ cap", len(pick) <= 16, str(len(pick)))
check("bin count > 0", len(pick) > 0)
check("bin cap 0 empty",
      len(tags_draw.screen_bin_select(sx, sy, depth, cap=0, rw=800, rh=600)) == 0)
n_spread = int(np.sum(np.asarray(pick) >= 40))
check("bin spreads (not nearest-only pile)", n_spread > 0, f"spread={n_spread}")

pos_f = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]], dtype=np.float64)
nrms_f = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, -1.0]], dtype=np.float64)
mask_f = tags_draw.facing_keep_mask(pos_f, nrms_f, (0.0, 0.0, 10.0))
check("facing keeps toward camera", bool(mask_f[0]) is True)
check("facing drops away from camera", bool(mask_f[1]) is False)

sx_p, sy_p, valid_p = tags_draw.project_world_to_region(
    np.array([[0.0, 0.0, 0.0]]), np.eye(4), 200, 100)
check("project origin → screen center",
      valid_p[0] and abs(sx_p[0] - 100.0) < 1e-6 and abs(sy_p[0] - 50.0) < 1e-6,
      f"sx={sx_p} sy={sy_p} valid={valid_p}")
persp_b = np.eye(4, dtype=np.float64)
persp_b[3, 3] = -1.0  # w = -1 → behind
_sx_b, _sy_b, valid_b = tags_draw.project_world_to_region(
    np.array([[0.0, 0.0, 0.0]]), persp_b, 200, 100)
check("project w<=0 invalid", bool(valid_b[0]) is False)

check("card instancing probe does not raise",
      tags_draw._card_instancing_available() in (True, False))
print(f"  tags cards: "
      f"{'INSTANCED' if tags_draw._card_instancing_available() else 'SOUP fallback'}")
print("  tags text: BLF (atlas deferred)")

# Restore Markers for GN fallback check
node_builder.set_input(md, "Display", "Markers")
node_builder.set_input(md, "Attribute", "heat")
node_builder.set_input(md, "Domain", "Point")

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

print("\n== P0: per-viz ramp tree (off-engine, GPU-on shared) ==")
bpy.context.scene.attrviz_gpu_markers = True
va = av.add_visualizer(
    bpy.context, target=grid, attribute="heat",
    domain="Point", style="Heat", display="Markers",
    name="Viz · ramp A",
)
vb = av.add_visualizer(
    bpy.context, target=grid, attribute="heat",
    domain="Point", style="Heat", display="Markers",
    name="Viz · ramp B",
)
ga, gb = av.viz_modifier(va).node_group, av.viz_modifier(vb).node_group
ra = node_builder.ramp_node_for_viz(va)
rb = node_builder.ramp_node_for_viz(vb)
ta = node_builder.ramp_tree_for_viz(va)
tb = node_builder.ramp_tree_for_viz(vb)
engine_ramp = next(
    (n for n in ga.nodes if n.bl_idname == "ShaderNodeValToRGB"), None,
)
check("GPU-on vizs share engine group", ga is gb, f"{ga} vs {gb}")
check("each viz has a ramp node", ra is not None and rb is not None)
check("ramp trees are distinct", ta is not tb and ta is not None)
check("ramp ColorRamps are distinct",
      ra is not None and rb is not None and ra.color_ramp is not rb.color_ramp)
check("off-engine ramp is not the engine ValToRGB",
      ra is not None and ra is not engine_ramp)
check("new ramp has Heat 5-stop",
      ra is not None and len(ra.color_ramp.elements) == 5,
      str(None if ra is None else len(ra.color_ramp.elements)))
if ra is not None and rb is not None:
    rb.color_ramp.elements[0].color = (1.0, 0.0, 0.0, 1.0)
    check("editing one ramp does not change the other",
          tuple(ra.color_ramp.elements[0].color)
          != tuple(rb.color_ramp.elements[0].color))
old_tb = tb
if node_builder.RAMP_PROP in vb:
    del vb[node_builder.RAMP_PROP]
if old_tb is not None and old_tb.users == 0:
    bpy.data.node_groups.remove(old_tb)
check("cleared ramp pointer is None", node_builder.ramp_node_for_viz(vb) is None)
av.migrate_all_visualizers()
check("migrate restores ramp node", node_builder.ramp_node_for_viz(vb) is not None)
node_builder.release_viz_ramp(va)
node_builder.release_viz_ramp(vb)
bpy.data.objects.remove(va, do_unlink=True)
bpy.data.objects.remove(vb, do_unlink=True)

print("\n== P1: ramp_colors + extract_ramp ==")
bw = (
    (0.0, 0.0, 0.0, 0.0, 1.0),
    (1.0, 1.0, 1.0, 1.0, 1.0),
)
v = np.array([0.0, 0.5, 1.0], dtype=np.float32)
c_bw = gpu_color.ramp_colors(v, bw, vmin=0.0, vmax=1.0)
check("2-stop black→white endpoints",
      np.allclose(c_bw[0, :3], 0.0) and np.allclose(c_bw[2, :3], 1.0),
      str(c_bw))
check("2-stop midpoint is gray",
      np.allclose(c_bw[1, :3], 0.5, atol=1e-5), str(c_bw[1]))

v5 = np.array([0.0, 0.25, 0.5, 0.75], dtype=np.float32)
h5 = gpu_color.heat_colors(v5, vmin=0.0, vmax=1.0)
r5 = gpu_color.ramp_colors(v5, gpu_color.HEAT_STOPS, vmin=0.0, vmax=1.0)
check("5-stop matches heat_colors (interior)",
      np.allclose(h5, r5, atol=1e-5),
      f"max_delta={np.max(np.abs(h5 - r5))}")

clip = gpu_color.ramp_colors(
    np.array([-10.0, 10.0], dtype=np.float32), bw, vmin=0.0, vmax=1.0)
check("below vmin → first stop", np.allclose(clip[0, :3], 0.0))
check("above vmax → last stop", np.allclose(clip[1, :3], 1.0))
same = gpu_color.ramp_colors(
    np.array([3.0, 3.0], dtype=np.float32), bw, vmin=3.0, vmax=3.0)
check("hi<=lo → first stop", np.allclose(same[:, :3], 0.0))
empty = gpu_color.ramp_colors(np.zeros((0,), dtype=np.float32), bw)
check("empty values shape", empty.shape == (0, 4), str(empty.shape))
solid = gpu_color.ramp_colors(
    np.array([0.0, 1.0], dtype=np.float32),
    ((0.5, 1.0, 0.0, 0.0, 1.0),),
    vmin=0.0, vmax=1.0,
)
check("1-stop is solid", np.allclose(solid[:, :3], (1.0, 0.0, 0.0)))

lut = gpu_color.ramp_lut_rgba(bw, n=256)
check("LUT is 256×4", lut.shape == (256, 4), str(lut.shape))
check("LUT endpoints",
      np.allclose(lut[0, :3], 0.0) and np.allclose(lut[-1, :3], 1.0))

ramp_node = node_builder.ensure_viz_ramp(viz)
ext = gpu_color.extract_ramp(ramp_node)
check("extract_ramp from viz node has 5 stops", len(ext) == 5, str(len(ext)))
check("extract_ramp first pos is 0", abs(ext[0][0]) < 1e-6)

custom = ((0.0, 1.0, 0.0, 0.0, 1.0), (1.0, 0.0, 0.0, 1.0, 1.0))
cols_r = gpu_color.values_to_colors(
    np.array([0.0, 1.0], dtype=np.float32), "FLOAT", "Heat",
    vmin=0.0, vmax=1.0, ramp=custom,
)
check("values_to_colors ramp= overrides heat",
      np.allclose(cols_r[0, :3], (1.0, 0.0, 0.0))
      and np.allclose(cols_r[1, :3], (0.0, 0.0, 1.0)),
      str(cols_r))
cols_rgb = gpu_color.values_to_colors(
    np.array([[1.0, 0.0, 0.0]], dtype=np.float32), "FLOAT_VECTOR", "RGB",
    ramp=custom,
)
check("RGB ignores ramp=", cols_rgb.shape == (1, 4), str(cols_rgb.shape))

node_builder.set_input(md, "Display", "Surface")
node_builder.set_input(md, "Style", "Heat")
node_builder.set_input(md, "Attribute", "heat")
node_builder.set_input(md, "Domain", "Point")
gpu_overlay.invalidate(viz)
e1 = gpu_overlay._refresh_viz(viz, md, "Surface")
c1 = e1.get("colors")
rn = node_builder.ramp_node_for_viz(viz)
rn.color_ramp.elements[0].color = (1.0, 0.0, 0.0, 1.0)
rn.color_ramp.elements[-1].color = (0.0, 0.0, 1.0, 1.0)
e2 = gpu_overlay._refresh_viz(viz, md, "Surface")
c2 = e2.get("colors")
if e2.get("mode") == "heat_lut":
    check("ramp edit keeps heat_lut batch",
          e1.get("batch") is e2.get("batch"))
    check("ramp edit updates lut_key",
          e1.get("lut_key") != e2.get("lut_key"))
else:
    check("CPU fallback recolors on ramp edit",
          c1 is not None and c2 is not None and not np.allclose(c1, c2),
          f"mode={e2.get('mode')} c1={None if c1 is None else c1[0]} "
          f"c2={None if c2 is None else c2[0]}")
check("heat lut shader probe does not raise",
      gpu_overlay._heat_lut_shader_available() in (True, False))
print(f"  heat lut: "
      f"{'SHADER' if gpu_overlay._heat_lut_shader_available() else 'CPU fallback'}")

print("\n== P2: panel ramp widget target ==")
bpy.context.scene.attrviz_gpu_markers = True
panel = av._panel_heat_ramp_node(viz, md)
engine = next(
    (n for n in md.node_group.nodes
     if n.bl_idname == "ShaderNodeValToRGB"), None,
)
check("GPU-on panel ramp is off-engine",
      panel is not None and engine is not None
      and panel.as_pointer() != engine.as_pointer())
off_n = node_builder.ramp_node_for_viz(viz)
check("GPU-on panel ramp is ensure_viz_ramp",
      panel is not None and off_n is not None
      and panel.as_pointer() == off_n.as_pointer(),
      f"panel={panel} off={off_n}")
before = tuple(engine.color_ramp.elements[0].color)
panel.color_ramp.elements[0].color = (0.1, 0.2, 0.3, 1.0)
check("editing panel ramp does not dirty shared engine",
      tuple(engine.color_ramp.elements[0].color) == before)
vc = av.add_visualizer(
    bpy.context, target=grid, attribute="heat",
    domain="Point", style="Heat", display="Surface",
    name="Viz · panel peer",
)
p_peer = av._panel_heat_ramp_node(vc, av.viz_modifier(vc))
check("two vizs have distinct panel ramps",
      p_peer is not None and p_peer is not panel)
node_builder.release_viz_ramp(vc)
bpy.data.objects.remove(vc, do_unlink=True)

bpy.context.scene.attrviz_gpu_markers = False
vd = av.add_visualizer(
    bpy.context, target=grid, attribute="heat",
    domain="Point", style="Heat", display="Markers",
    name="Viz · gpuoff ramp",
)
mdd = av.viz_modifier(vd)
pd = av._panel_heat_ramp_node(vd, mdd)
ed = next(
    (n for n in mdd.node_group.nodes
     if n.bl_idname == "ShaderNodeValToRGB"), None,
)
check("GPU-off panel ramp is engine ValToRGB",
      pd is not None and ed is not None
      and pd.as_pointer() == ed.as_pointer(),
      f"pd={pd} ed={ed} gpu={av._gpu_overlay_on()}")
node_builder.release_viz_ramp(vd)
bpy.data.objects.remove(vd, do_unlink=True)
bpy.context.scene.attrviz_gpu_markers = True

try:
    gpu_overlay._subscribe_ramp_msgbus()
    gpu_overlay._tag_view3d_redraw()
    _msgbus_ok, _msgbus_err = True, ""
except Exception as exc:
    _msgbus_ok, _msgbus_err = False, str(exc)
check("ramp msgbus subscribe + redraw do not raise",
      _msgbus_ok, _msgbus_err)

print("\n== P3: ramp presets (Heat / RGB / BnW) ==")
rn = node_builder.ensure_viz_ramp(viz)
node_builder.apply_ramp_preset(rn, "bnw")
check("BnW has 2 stops", len(rn.color_ramp.elements) == 2,
      str(len(rn.color_ramp.elements)))
check("BnW start is black",
      all(abs(rn.color_ramp.elements[0].color[i]) < 1e-5 for i in range(3)))
check("BnW end is white",
      all(abs(rn.color_ramp.elements[-1].color[i] - 1.0) < 1e-5
          for i in range(3)))
node_builder.apply_ramp_preset(rn, "heat")
check("Heat after BnW has 5 stops (replace, not accumulate)",
      len(rn.color_ramp.elements) == 5, str(len(rn.color_ramp.elements)))
node_builder.apply_ramp_preset(rn, "rgb")
check("RGB preset has 5 stops",
      len(rn.color_ramp.elements) == 5, str(len(rn.color_ramp.elements)))
node_builder.apply_ramp_preset(rn, "heat")
check("Heat again still 5",
      len(rn.color_ramp.elements) == 5, str(len(rn.color_ramp.elements)))

bpy.context.scene.attrviz_gpu_markers = True
node_builder.set_input(md, "Display", "Surface")
node_builder.set_input(md, "Style", "RGB")
node_builder.set_input(md, "Attribute", "heat")
node_builder.set_input(md, "Domain", "Point")
gpu_overlay.invalidate(viz)
e_h = gpu_overlay._refresh_viz(viz, md, "Surface")
node_builder.apply_ramp_preset(rn, "bnw")
e_b = gpu_overlay._refresh_viz(viz, md, "Surface")
if e_h.get("mode") == "heat_lut":
    check("leftover Style=RGB Surface still uses ramp LUT",
          e_b.get("mode") == "heat_lut")
    check("preset does not rebuild mesh batch",
          e_h.get("batch") is e_b.get("batch"))
    check("preset updates lut_key",
          e_h.get("lut_key") != e_b.get("lut_key"),
          f"{e_h.get('lut_key')} vs {e_b.get('lut_key')}")
else:
    c_h, c_b = e_h.get("colors"), e_b.get("colors")
    check("CPU leftover Style=RGB still recolors via ramp",
          c_h is not None and c_b is not None and not np.allclose(c_h, c_b),
          f"mode={e_b.get('mode')}")
    if c_b is not None and len(c_b) > 1:
        check("CPU BnW low is black",
              np.allclose(c_b[0, :3], 0.0, atol=0.08), str(c_b[0]))
        check("CPU BnW high is white",
              np.allclose(c_b[-1, :3], 1.0, atol=0.08), str(c_b[-1]))

node_builder.set_input(md, "Attribute", "position")
gpu_overlay.invalidate(viz)
e_v = gpu_overlay._refresh_viz(viz, md, "Surface")
if e_v.get("mode") == "heat_lut":
    check("vector Surface uses ramp LUT (not leftover Style-RGB)", True)
else:
    cols_v = e_v.get("colors")
    built_v = gpu_sample.build_surface_tris(md, style="RGB")
    if cols_v is not None and built_v is not None:
        leftover = gpu_color.rgb_colors(built_v[1])
        check("vector Surface is not leftover XYZ→RGB",
              not np.allclose(cols_v[:, :3], leftover[:, :3], atol=1e-3),
              f"mode={e_v.get('mode')}")
    else:
        check("vector Surface CPU produced colors", cols_v is not None)

p_rgb = av._panel_heat_ramp_node(viz, md)
off_rgb = node_builder.ramp_node_for_viz(viz)
check("GPU-on panel ramp still off-engine when leftover Style=RGB",
      p_rgb is not None and off_rgb is not None
      and p_rgb.as_pointer() == off_rgb.as_pointer())

try:
    bpy.ops.attrviz.ramp_preset(name=viz.name, preset="rgb")
    _op_ok, _op_err = True, ""
except Exception as exc:
    _op_ok, _op_err = False, str(exc)
check("ramp_preset operator runs", _op_ok, _op_err)
check("operator wrote RGB stop count",
      len(rn.color_ramp.elements) == 5, str(len(rn.color_ramp.elements)))
node_builder.apply_ramp_preset(rn, "heat")

print("\n== 005: categorical hash (INT / BOOLEAN / INT8) ==")
check("color_mapper INT is hash", gpu_color.color_mapper("INT") == "hash")
check("color_mapper BOOLEAN is hash",
      gpu_color.color_mapper("BOOLEAN") == "hash")
check("color_mapper FLOAT is ramp", gpu_color.color_mapper("FLOAT") == "ramp")
check("legend override is ramp",
      gpu_color.color_mapper("INT", legend=True) == "ramp")
ids = np.array([0, 0, 1, 2], dtype=np.int32)
h0 = gpu_color.hash_colors(ids, seed=0)
h1 = gpu_color.hash_colors(ids, seed=1)
check("same id → same color", np.allclose(h0[0], h0[1]))
check("id 0 and 1 differ", not np.allclose(h0[0], h0[2], atol=1e-5))
check("seed changes palette", not np.allclose(h0, h1))
ramp_near = gpu_color.ramp_colors(
    np.array([5.0, 6.0], dtype=np.float32), gpu_color.HEAT_STOPS,
    vmin=0.0, vmax=10.0,
)
hash_near = gpu_color.hash_colors(np.array([5, 6], dtype=np.int32), seed=0)
check("consecutive ids are not a heat ramp",
      not np.allclose(hash_near, ramp_near, atol=0.12),
      f"hash={hash_near} ramp={ramp_near}")

node_builder.set_input(md, "Display", "Surface")
node_builder.set_input(md, "Attribute", "face_id")
node_builder.set_input(md, "Domain", "Face")
viz.attrviz_seed = 0
gpu_overlay.invalidate(viz)
e_id = gpu_overlay._refresh_viz(viz, md, "Surface")
built_id = gpu_sample.build_surface_tris(md)
if built_id is not None:
    _bv = np.asarray(built_id[1]).reshape(-1)
    check("face_id corner values are INT-like",
          built_id[2] in ("INT", "BOOLEAN", "INT8"), str(built_id[2]))
    check("face_id corner values not constant",
          len(np.unique(_bv)) > 1,
          f"dtype={built_id[2]} unique={np.unique(_bv)[:8]} shape={_bv.shape}")
check("face_id Surface is not heat_lut",
      e_id.get("mode") != "heat_lut", str(e_id.get("mode")))
cols_id = e_id.get("colors")
if e_id.get("mode") == "id_hash":
    check("face_id Surface id_hash path", True)
else:
    check("face_id Surface produced colors",
          cols_id is not None and len(cols_id) >= 6,
          f"mode={e_id.get('mode')} n={0 if cols_id is None else len(cols_id)}")
    if cols_id is not None and len(cols_id) >= 6:
        uniq = np.unique(np.round(cols_id, 5), axis=0)
        check("face_id Surface has multiple hash colors",
              len(uniq) > 1, f"n_unique={len(uniq)} c0={cols_id[0]}")
skey0 = e_id.get("sample_key")
batch0 = e_id.get("batch")
viz.attrviz_seed = 99
e_id2 = gpu_overlay._refresh_viz(viz, md, "Surface")
check("Seed does not bust Surface sample key",
      e_id2.get("sample_key") == skey0)
if e_id.get("mode") == "id_hash":
    check("Seed does not rebuild id_hash batch",
          e_id2.get("batch") is batch0)
    check("hash_seed uniform updated",
          e_id2.get("hash_seed") == 99, str(e_id2.get("hash_seed")))
else:
    c2 = e_id2.get("colors")
    if cols_id is not None and c2 is not None:
        check("Seed reshuffles face_id colors",
              not np.allclose(cols_id, c2),
              f"mode={e_id2.get('mode')}")
    else:
        check("Seed reshuffles face_id colors", False, "missing colors")

ramp_still = node_builder.ramp_node_for_viz(viz)
check("categorical viz still has a ramp tree (future legend)",
      ramp_still is not None)

node_builder.set_input(md, "Attribute", "heat")
node_builder.set_input(md, "Domain", "Point")
viz.attrviz_seed = 0
gpu_overlay.invalidate(viz)
e_f = gpu_overlay._refresh_viz(viz, md, "Surface")
check("float Surface still ramp mapper",
      e_f.get("mode") == "heat_lut" or e_f.get("colors") is not None,
      str(e_f.get("mode")))

print("\n== 006: point-only POINTCLOUD + vert mesh ==")
N_PC = 32
pc = make_pointcloud("PC006", n=N_PC)
check("fixture is POINTCLOUD", pc is not None and pc.type == 'POINTCLOUD',
      f"type={None if pc is None else pc.type}")
heat_pc = pc.data.attributes.new("heat", 'FLOAT', 'POINT')
id_pc = pc.data.attributes.new("id", 'INT', 'POINT')
flow_pc = pc.data.attributes.new("flow", 'FLOAT_VECTOR', 'POINT')
nv_pc = len(heat_pc.data)
for i, d in enumerate(heat_pc.data):
    d.value = i / max(1, nv_pc - 1)
for i, d in enumerate(id_pc.data):
    d.value = i % 4
for i, d in enumerate(flow_pc.data):
    d.vector = (1.0, 0.0, 0.0)
bpy.context.view_layer.update()
check("cloud attr count", nv_pc == N_PC, f"{nv_pc} vs {N_PC}")

r_pc = gpu_sample.sample_evaluated(pc, "heat", "Point", world_space=False)
check("sample cloud heat", r_pc is not None)
if r_pc:
    pos, vals, dt = r_pc
    check("cloud heat dtype", dt == 'FLOAT', dt)
    check("cloud heat n", len(pos) == N_PC, f"{len(pos)} vs {N_PC}")
    check("cloud pos shape", pos.shape == (N_PC, 3), str(pos.shape))

for dom in ("Edge", "Face", "Corner"):
    r_empty = gpu_sample.sample_evaluated(pc, "heat", dom, world_space=False)
    check(f"cloud {dom} sample empty", r_empty is None)

r_n = gpu_sample.sample_evaluated(pc, "Normal", "Point", world_space=False)
check("cloud Normal intrinsic empty", r_n is None)

r_idx = gpu_sample.sample_evaluated(pc, "Index", "Point", world_space=False)
check("cloud Index intrinsic",
      r_idx is not None and r_idx[2] == 'INT' and len(r_idx[0]) == N_PC)

pc.location = (10.0, 0.0, 0.0)
bpy.context.view_layer.update()
r_w = gpu_sample.sample_evaluated(pc, "heat", "Point", world_space=True)
r_l = gpu_sample.sample_evaluated(pc, "heat", "Point", world_space=False)
if r_w and r_l:
    check("cloud world-space translates",
          abs(float(r_w[0][0][0] - r_l[0][0][0]) - 10.0) < 1e-4,
          f"world0={r_w[0][0]} local0={r_l[0][0]}")
pc.location = (0.0, 0.0, 0.0)
bpy.context.view_layer.update()

by_pc, faces_pc = av.attributes_by_domain(pc)
check("cloud has_faces is False", faces_pc is False)
check("cloud Point attrs include heat",
      any(n == "heat" for n, _t in by_pc.get("Point", [])))
check("cloud Edge/Face/Corner empty",
      not by_pc.get("Edge") and not by_pc.get("Face") and not by_pc.get("Corner"))
check("cloud Point has Index not Normal",
      any(n == "Index" for n, _t in by_pc.get("Point", []))
      and not any(n == "Normal" for n, _t in by_pc.get("Point", [])))
style_pc, disp_pc = av.auto_pick("Point", "FLOAT", has_faces=False)
check("cloud auto_pick Markers", disp_pc == "Markers", disp_pc)

for o in list(bpy.context.view_layer.objects):
    o.select_set(False)
pc.select_set(True)
bpy.context.view_layer.objects.active = pc
cands = av._watch_candidates(bpy.context)
check("cloud is watch candidate", pc in cands, f"got={[o.name for o in cands]}")

verts = make_vert_mesh("VertOnly006", n=12)
vh = verts.data.attributes.new("heat", 'FLOAT', 'POINT')
for i, d in enumerate(vh.data):
    d.value = i / 11.0
bpy.context.view_layer.update()
r_v = gpu_sample.sample_evaluated(verts, "heat", "Point", world_space=False)
check("vert-only mesh samples", r_v is not None and len(r_v[0]) == 12)

viz_pc = av.add_visualizer(
    bpy.context, target=pc, attribute="heat",
    domain="Point", style="Heat", display="Markers",
)
md_pc = av.viz_modifier(viz_pc)
check("cloud viz modifier", md_pc is not None)
samp = gpu_sample.sample_visualizer_targets(md_pc, cap=50000)
check("cloud viz sample n",
      samp is not None and len(samp[0]) == N_PC,
      str(None if samp is None else len(samp[0])))
check("watch_has_faces cloud-only False",
      gpu_sample.watch_has_faces(md_pc) is False)

gpu_overlay.invalidate(viz_pc)
e_m = gpu_overlay._refresh_viz(viz_pc, md_pc, "Markers")
check("Markers on cloud heat n",
      e_m.get("n", 0) == N_PC and not e_m.get("empty"),
      f"n={e_m.get('n')} empty={e_m.get('empty')} mode={e_m.get('mode')}")
check("Markers on cloud float is ramp/lut",
      e_m.get("mode") in ("heat_lut", None) or e_m.get("colors") is not None,
      str(e_m.get("mode")))

node_builder.set_input(md_pc, "Attribute", "id")
gpu_overlay.invalidate(viz_pc)
e_h = gpu_overlay._refresh_viz(viz_pc, md_pc, "Markers")
check("Markers on cloud int is hash",
      e_h.get("mode") == "id_hash" or e_h.get("colors") is not None,
      f"mode={e_h.get('mode')} n={e_h.get('n')}")

node_builder.set_input(md_pc, "Attribute", "flow")
node_builder.set_input(md_pc, "Display", "Arrows")
gpu_overlay.invalidate(viz_pc)
e_a = gpu_overlay._refresh_viz(viz_pc, md_pc, "Arrows")
check("Arrows on cloud vector non-empty",
      e_a.get("n", 0) > 0 or e_a.get("cone_verts", 0) > 0,
      str({k: e_a.get(k) for k in ("n", "empty", "mode", "cone_verts")}))

node_builder.set_input(md_pc, "Attribute", "heat")
arrow_f = gpu_overlay._refresh_arrows(
    viz_pc, md_pc, samp[0], samp[1], samp[2])
check("Arrows on cloud float empty",
      arrow_f.get("empty") is True or arrow_f.get("batch") is None)

node_builder.set_input(md_pc, "Display", "Surface")
node_builder.set_input(md_pc, "Attribute", "heat")
node_builder.set_input(md_pc, "Domain", "Point")
surf_pc = gpu_sample.build_surface_tris(md_pc, style="Heat")
check("Surface on cloud-only is empty",
      surf_pc is None or surf_pc[3] == 0,
      str(None if surf_pc is None else surf_pc[3]))
gpu_overlay.invalidate(viz_pc)
e_s = gpu_overlay._refresh_viz(viz_pc, md_pc, "Surface")
check("Surface refresh on cloud does not crash",
      e_s.get("empty") is True or e_s.get("n", 0) == 0,
      f"empty={e_s.get('empty')} n={e_s.get('n')}")

gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("Surface-only does not mute cloud",
      gpu_overlay._MUTE_PROP not in pc and pc.display_type != "BOUNDS",
      f"display_type={pc.display_type} muted={gpu_overlay._MUTE_PROP in pc}")

node_builder.set_input(md_pc, "Display", "Tags")
node_builder.set_input(md_pc, "Attribute", "id")
gpu_overlay.invalidate(viz_pc)
rows_t = tags_draw._collect_tags(
    md_pc, (0.0, -10.0, 2.0), cap=50, facing_cull=False)
check("Tags on cloud positions",
      rows_t is not None and len(rows_t) == N_PC,
      str(None if rows_t is None else len(rows_t)))

# Mixed watch: mesh + cloud, no scene attrvis (API scope=)
mix = bpy.data.collections.new("Mix006")
bpy.context.scene.collection.children.link(mix)
mesh_m = make_grid("MixMesh006", segments=2)
mh = mesh_m.data.attributes.new("heat", 'FLOAT', 'POINT')
for d in mh.data:
    d.value = 0.25
pc_m = make_pointcloud("MixCloud006", n=8)
ph = pc_m.data.attributes.new("heat", 'FLOAT', 'POINT')
for d in ph.data:
    d.value = 0.75
bpy.context.view_layer.update()
mix.objects.link(mesh_m)
mix.objects.link(pc_m)
viz_mix = av.add_visualizer(
    bpy.context, scope=mix, attribute="heat",
    domain="Point", style="Heat", display="Markers")
md_mix = av.viz_modifier(viz_mix)
n_mesh = len(mesh_m.data.vertices)
n_cloud = len(pc_m.data.points)
mix_s = gpu_sample.sample_visualizer_targets(md_mix, cap=50000)
check("mixed mesh+cloud concat",
      mix_s is not None and len(mix_s[0]) == n_mesh + n_cloud,
      f"got={None if mix_s is None else len(mix_s[0])} want={n_mesh + n_cloud}")
check("mixed watch_has_faces True",
      gpu_sample.watch_has_faces(md_mix) is True)

# Vert-only Surface empty
viz_v = av.add_visualizer(
    bpy.context, target=verts, attribute="heat",
    domain="Point", style="Heat", display="Surface")
md_v = av.viz_modifier(viz_v)
surf_v = gpu_sample.build_surface_tris(md_v, style="Heat")
check("Surface on vert-only mesh empty",
      surf_v is None or surf_v[3] == 0,
      str(None if surf_v is None else surf_v[3]))

print("\n== 006 P4: point-cloud mute (Surface analog) ==")
bpy.context.scene.attrviz_gpu_markers = True
mesh_p4 = make_grid("P4Mesh", segments=2)
mh4 = mesh_p4.data.attributes.new("heat", 'FLOAT', 'POINT')
for d in mh4.data:
    d.value = 0.5
pc_p4 = make_pointcloud("P4Cloud", n=8)
ph4 = pc_p4.data.attributes.new("heat", 'FLOAT', 'POINT')
for d in ph4.data:
    d.value = 0.5
bpy.context.view_layer.update()
prev_mesh_p4 = mesh_p4.display_type
prev_pc_p4 = pc_p4.display_type

viz_geo = av.add_visualizer(
    bpy.context, target=pc_p4, attribute="heat",
    domain="Point", style="Heat", display="Markers")
viz_surf_p4 = av.add_visualizer(
    bpy.context, target=mesh_p4, attribute="heat",
    domain="Point", style="Heat", display="Surface")
check("P4 both on: cloud BOUNDS", pc_p4.display_type == "BOUNDS",
      pc_p4.display_type)
check("P4 both on: cloud mute prop", gpu_overlay._MUTE_PROP in pc_p4)
check("P4 both on: mesh BOUNDS", mesh_p4.display_type == "BOUNDS",
      mesh_p4.display_type)

viz_surf_p4.hide_viewport = True
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("P4 Markers only: cloud BOUNDS", pc_p4.display_type == "BOUNDS",
      pc_p4.display_type)
check("P4 Markers only: mesh restored",
      mesh_p4.display_type == prev_mesh_p4, mesh_p4.display_type)
check("P4 mesh+Markers does not mute mesh",
      mesh_p4.display_type != "BOUNDS" or prev_mesh_p4 == "BOUNDS",
      mesh_p4.display_type)

viz_surf_p4.hide_viewport = False
viz_geo.hide_viewport = True
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("P4 Surface only: mesh BOUNDS", mesh_p4.display_type == "BOUNDS",
      mesh_p4.display_type)
check("P4 Surface only: cloud restored",
      pc_p4.display_type == prev_pc_p4, pc_p4.display_type)
check("P4 Surface only: cloud prop cleared",
      gpu_overlay._MUTE_PROP not in pc_p4)

viz_surf_p4.hide_viewport = True
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("P4 both off: mesh restored",
      mesh_p4.display_type == prev_mesh_p4, mesh_p4.display_type)
check("P4 both off: cloud restored",
      pc_p4.display_type == prev_pc_p4, pc_p4.display_type)

viz_geo.hide_viewport = False
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("P4 GPU on Markers: cloud BOUNDS", pc_p4.display_type == "BOUNDS",
      pc_p4.display_type)
bpy.context.scene.attrviz_gpu_markers = False
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("P4 GPU off: cloud restored",
      pc_p4.display_type == prev_pc_p4, pc_p4.display_type)
bpy.context.scene.attrviz_gpu_markers = True
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("P4 GPU back on: cloud BOUNDS", pc_p4.display_type == "BOUNDS",
      pc_p4.display_type)

md_geo = av.viz_modifier(viz_geo)
node_builder.set_input(md_geo, "Display", "Arrows")
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("P4 Arrows mutes cloud", pc_p4.display_type == "BOUNDS",
      pc_p4.display_type)
node_builder.set_input(md_geo, "Display", "Tags")
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("P4 Tags mutes cloud", pc_p4.display_type == "BOUNDS",
      pc_p4.display_type)

viz_geo.hide_viewport = True
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("P4 disable viz restores cloud",
      pc_p4.display_type == prev_pc_p4, pc_p4.display_type)
check("P4 disable viz clears prop", gpu_overlay._MUTE_PROP not in pc_p4)

print("\n== 008 P2: attribute accessor reads match the legacy reads ==")
# Positions/normals now read through the contiguous attribute arrays rather
# than the legacy vertices collection (56x / 128x). The reads must be
# byte-identical or every visualizer silently moves.
import bmesh as _bm  # noqa: E402

_me = bpy.data.meshes.new("AccessorGrid")
_b = _bm.new()
_bm.ops.create_grid(_b, x_segments=12, y_segments=12, size=2.0)
_b.to_mesh(_me)
_b.free()
_obj = bpy.data.objects.new("AccessorGrid", _me)
bpy.context.collection.objects.link(_obj)

_n = len(_me.vertices)
_legacy = np.empty(_n * 3, dtype=np.float32)
_me.vertices.foreach_get("co", _legacy)
check("008 fast positions == vertices.foreach_get('co')",
      np.array_equal(gpu_sample._point_positions(_me),
                     _legacy.reshape(-1, 3)))

_legacy_n = np.empty(_n * 3, dtype=np.float32)
_me.vertices.foreach_get("normal", _legacy_n)
check("008 fast normals == vertices.foreach_get('normal')",
      np.array_equal(gpu_sample._point_normals(_me, _n),
                     _legacy_n.reshape(-1, 3)))

# The path that actually matters: EVALUATED geometry out of a GN tree, where
# the layer set differs from a plain datablock.
_tree = bpy.data.node_groups.new("AccessorGN", "GeometryNodeTree")
_tree.interface.new_socket("Geometry", in_out='INPUT',
                           socket_type="NodeSocketGeometry")
_tree.interface.new_socket("Geometry", in_out='OUTPUT',
                           socket_type="NodeSocketGeometry")
_gi = _tree.nodes.new("NodeGroupInput")
_go = _tree.nodes.new("NodeGroupOutput")
_sp = _tree.nodes.new("GeometryNodeSetPosition")
_off = _tree.nodes.new("ShaderNodeCombineXYZ")
_off.inputs["Z"].default_value = 3.0
_tree.links.new(_gi.outputs[0], _sp.inputs["Geometry"])
_tree.links.new(_off.outputs["Vector"], _sp.inputs["Offset"])
_tree.links.new(_sp.outputs["Geometry"], _go.inputs[0])
_gmd = _obj.modifiers.new("gn", 'NODES')
_gmd.node_group = _tree
bpy.context.view_layer.update()
_dg = bpy.context.evaluated_depsgraph_get()
_dg.update()
_ev = _obj.evaluated_get(_dg).data

_ev_legacy = np.empty(len(_ev.vertices) * 3, dtype=np.float32)
_ev.vertices.foreach_get("co", _ev_legacy)
_ev_fast = gpu_sample._point_positions(_ev)
check("008 evaluated GN positions byte-identical",
      np.array_equal(_ev_fast, _ev_legacy.reshape(-1, 3)))
check("008 evaluated GN positions reflect the modifier",
      abs(float(_ev_fast[0][2]) - 3.0) < 1e-5, str(_ev_fast[0]))

# Fallback must hold when the attribute is absent/wrong type.
_buf = np.empty(_n * 3, dtype=np.float32)
check("008 _attr_vec3 declines a missing attribute",
      gpu_sample._attr_vec3(_me, "definitely_not_here", _buf) is False)
check("008 _bulk_into declines a bad property",
      gpu_sample._bulk_into(_me.vertices, "not_a_prop", _buf) is False)

# Face / Edge / Corner used per-element Python loops. The bulk versions must
# reproduce them exactly — these are the reference implementations.
_sharp = _me.polygons[0]
_sharp.use_smooth = False


def _ref_face_centers(m):
    a = np.empty((len(m.polygons), 3), dtype=np.float32)
    for i, p in enumerate(m.polygons):
        a[i] = p.center
    return a


def _ref_edge_centers(m):
    a = np.empty((len(m.edges), 3), dtype=np.float32)
    for i, e in enumerate(m.edges):
        a[i] = (m.vertices[e.vertices[0]].co
                + m.vertices[e.vertices[1]].co) * 0.5
    return a


def _ref_corner_positions(m):
    a = np.empty((len(m.loops), 3), dtype=np.float32)
    for i, lp in enumerate(m.loops):
        a[i] = m.vertices[lp.vertex_index].co
    return a


def _ref_face_normals(m):
    a = np.empty((len(m.polygons), 3), dtype=np.float32)
    for i, p in enumerate(m.polygons):
        a[i] = p.normal
    return a


def _ref_corner_normals(m):
    vn = np.empty(len(m.vertices) * 3, dtype=np.float32)
    m.vertices.foreach_get("normal", vn)
    vn = vn.reshape(-1, 3)
    a = np.empty((len(m.loops), 3), dtype=np.float32)
    for i, lp in enumerate(m.loops):
        a[i] = vn[lp.vertex_index]
    return a


check("008 face centers match per-element reference",
      np.allclose(gpu_sample._face_centers(_me), _ref_face_centers(_me),
                  atol=1e-6))
check("008 edge centers match per-element reference",
      np.allclose(gpu_sample._edge_centers(_me), _ref_edge_centers(_me),
                  atol=1e-6))
check("008 corner positions match per-element reference",
      np.array_equal(gpu_sample._corner_positions(_me),
                     _ref_corner_positions(_me)))
check("008 face normals match per-element reference",
      np.allclose(gpu_sample._face_normals(_me, len(_me.polygons)),
                  _ref_face_normals(_me), atol=1e-6))
_corner_fast, _ = gpu_sample._read_intrinsic(
    _me, node_builder.NORMAL_ATTR, "Corner", len(_me.loops))
check("008 corner normals stay SMOOTH (not split) — behaviour preserved",
      np.allclose(_corner_fast, _ref_corner_normals(_me), atol=1e-6))

# Degenerate geometry must not crash the bulk paths.
_empty = bpy.data.meshes.new("EmptyMesh")
check("008 empty mesh: edge centers", len(gpu_sample._edge_centers(_empty)) == 0)
check("008 empty mesh: corner positions",
      len(gpu_sample._corner_positions(_empty)) == 0)
check("008 empty mesh: face centers", len(gpu_sample._face_centers(_empty)) == 0)

print("\n== 008 P0: depsgraph epochs invalidate the sample cache ==")
# Every row here used to leave the fingerprint untouched, so the overlay kept
# drawing the first frame it ever sampled.
_p0_me = bpy.data.meshes.new("P0Grid")
_pb = _bm.new()
_bm.ops.create_grid(_pb, x_segments=4, y_segments=4, size=1.0)
_pb.to_mesh(_p0_me)
_pb.free()
_p0_obj = bpy.data.objects.new("P0Grid", _p0_me)
bpy.context.collection.objects.link(_p0_obj)
_p0_attr = _p0_me.attributes.new("heat", 'FLOAT', 'POINT')
for _i, _d in enumerate(_p0_attr.data):
    _d.value = float(_i)

_p0_viz = av.add_visualizer(bpy.context, target=_p0_obj, attribute="heat",
                            domain="Point", style="Heat", display="Markers")
_p0_md = av.viz_modifier(_p0_viz)


def _cook_fp():
    """Settle the depsgraph so handlers run, then read the fingerprint."""
    bpy.context.view_layer.update()
    _d = bpy.context.evaluated_depsgraph_get()
    _d.update()
    return gpu_sample.watch_fingerprint(_p0_md)


_fp = _cook_fp()

for _i, _d in enumerate(_p0_me.attributes["heat"].data):
    _d.value = float(_i) * 10.0
_p0_obj.update_tag()
_fp_attr = _cook_fp()
check("008 P0 attribute value change moves the fingerprint", _fp_attr != _fp)

for _v in _p0_me.vertices:
    _v.co.z += 1.0
_p0_obj.update_tag()
_fp_pos = _cook_fp()
check("008 P0 vertex move moves the fingerprint", _fp_pos != _fp_attr)

_p0_obj.location.x += 2.0
_fp_xf = _cook_fp()
check("008 P0 transform moves the fingerprint", _fp_xf != _fp_pos)

# The case that proves counts were never the signal: a GN modifier that
# changes the evaluated element count, like a scatter reseeding.
_p0_tree = bpy.data.node_groups.new("P0GN", "GeometryNodeTree")
_p0_tree.interface.new_socket("Geometry", in_out='INPUT',
                              socket_type="NodeSocketGeometry")
_p0_tree.interface.new_socket("Geometry", in_out='OUTPUT',
                              socket_type="NodeSocketGeometry")
_p0_gi = _p0_tree.nodes.new("NodeGroupInput")
_p0_go = _p0_tree.nodes.new("NodeGroupOutput")
_p0_grid = _p0_tree.nodes.new("GeometryNodeMeshGrid")
_p0_grid.inputs["Vertices X"].default_value = 5
_p0_grid.inputs["Vertices Y"].default_value = 5
# The grid replaces the original geometry, so heat must be re-stored or the
# visualizer has nothing to sample.
_p0_store = _p0_tree.nodes.new("GeometryNodeStoreNamedAttribute")
_p0_store.data_type = 'FLOAT'
_p0_store.domain = 'POINT'
_p0_store.inputs["Name"].default_value = "heat"
_p0_idx = _p0_tree.nodes.new("GeometryNodeInputIndex")
_p0_tree.links.new(_p0_grid.outputs["Mesh"], _p0_store.inputs["Geometry"])
_p0_tree.links.new(_p0_idx.outputs["Index"], _p0_store.inputs["Value"])
_p0_tree.links.new(_p0_store.outputs["Geometry"], _p0_go.inputs[0])
_p0_gmd = _p0_obj.modifiers.new("gn", 'NODES')
_p0_gmd.node_group = _p0_tree
_fp_mod = _cook_fp()
check("008 P0 adding a GN modifier moves the fingerprint", _fp_mod != _fp_xf)

_n_before = len(gpu_sample.sample_visualizer_targets(_p0_md)[0])
_p0_grid.inputs["Vertices X"].default_value = 9
_p0_obj.update_tag()
_fp_count = _cook_fp()
_n_after = len(gpu_sample.sample_visualizer_targets(_p0_md)[0])
check("008 P0 evaluated element count change moves the fingerprint",
      _fp_count != _fp_mod, f"{_n_before} -> {_n_after}")
check("008 P0 sample really did change length", _n_before != _n_after,
      f"{_n_before} -> {_n_after}")

# Non-regressions: idle redraws and unrelated objects must still cache.
_fp_idle_a = _cook_fp()
_fp_idle_b = _cook_fp()
check("008 P0 no change => fingerprint stable (orbit still caches)",
      _fp_idle_a == _fp_idle_b)

_other = bpy.data.objects.new("P0Unrelated", bpy.data.meshes.new("P0Un"))
bpy.context.collection.objects.link(_other)
_fp_pre_other = _cook_fp()
_other.location.z += 5.0
_fp_post_other = _cook_fp()
check("008 P0 unrelated object change does NOT invalidate this viz",
      _fp_pre_other == _fp_post_other)

# Frame changes fire no depsgraph update at all, so they need their own bump.
_fp_pre_frame = _cook_fp()
bpy.context.scene.frame_set(bpy.context.scene.frame_current + 1)
_fp_post_frame = _cook_fp()
check("008 P0 frame change invalidates (animated sources)",
      _fp_pre_frame != _fp_post_frame)

# Handlers must actually be installed, or none of the above holds in a real
# session (the tests above drive the depsgraph directly).
check("008 P0 depsgraph handler registered",
      av._note_depsgraph_epochs in bpy.app.handlers.depsgraph_update_post)
check("008 P0 frame handler registered",
      av._note_frame_change in bpy.app.handlers.frame_change_post)
check("008 P0 epoch handler runs before vizcol sync",
      bpy.app.handlers.depsgraph_update_post.index(av._note_depsgraph_epochs)
      < bpy.app.handlers.depsgraph_update_post.index(av._sync_vizcol_active))

print("\n== 007: instance-domain attributes (un-realized instances) ==")
# Reproduces city_seed_scatter: Grid -> Distribute -> Store x3 -> Instance on
# Points, with NO Realize. Everything lands on the instance domain.
_i_me = bpy.data.meshes.new("InstSrc")
_i_obj = bpy.data.objects.new("InstSrc", _i_me)
bpy.context.collection.objects.link(_i_obj)
_it = bpy.data.node_groups.new("InstGN", "GeometryNodeTree")
_it.interface.new_socket("Geometry", in_out='OUTPUT',
                         socket_type="NodeSocketGeometry")
_igo = _it.nodes.new("NodeGroupOutput")
_igrid = _it.nodes.new("GeometryNodeMeshGrid")
_igrid.inputs["Vertices X"].default_value = 4
_igrid.inputs["Vertices Y"].default_value = 4
_igrid.inputs["Size X"].default_value = 10.0
_igrid.inputs["Size Y"].default_value = 10.0
_idist = _it.nodes.new("GeometryNodeDistributePointsOnFaces")
_idist.inputs["Density"].default_value = 1.0
_istore = _it.nodes.new("GeometryNodeStoreNamedAttribute")
_istore.data_type = 'FLOAT'
_istore.domain = 'POINT'
_istore.inputs["Name"].default_value = "height"
_iidx = _it.nodes.new("GeometryNodeInputIndex")
_icube = _it.nodes.new("GeometryNodeMeshCube")
# Base-shift the prototype so its pivot sits on its BASE, as real scatters do
# (city_seed_scatter does exactly this). Without it the cube is centred on its
# own pivot and the centroid-vs-pivot distinction is invisible.
_ishift = _it.nodes.new("GeometryNodeTransform")
_ishift.inputs["Translation"].default_value = (0.0, 0.0, 0.5)
_iiop = _it.nodes.new("GeometryNodeInstanceOnPoints")
_it.links.new(_igrid.outputs["Mesh"], _idist.inputs["Mesh"])
_it.links.new(_idist.outputs["Points"], _istore.inputs["Geometry"])
_it.links.new(_iidx.outputs["Index"], _istore.inputs["Value"])
_it.links.new(_istore.outputs["Geometry"], _iiop.inputs["Points"])
_it.links.new(_icube.outputs["Mesh"], _ishift.inputs["Geometry"])
_it.links.new(_ishift.outputs["Geometry"], _iiop.inputs["Instance"])
_it.links.new(_iiop.outputs["Instances"], _igo.inputs[0])   # NO Realize
_imd = _i_obj.modifiers.new("gn", 'NODES')
_imd.node_group = _it
bpy.context.view_layer.update()
_idg = bpy.context.evaluated_depsgraph_get()
_idg.update()
_igs = _i_obj.evaluated_get(_idg).evaluated_geometry()
_icloud = gpu_sample.instances_cloud(_igs)
_n_inst = len(_icloud.points) if _icloud is not None else 0

check("007 instances_cloud finds the component", _icloud is not None)
check("007 top-level mesh really is empty (the failure case)",
      len(_igs.mesh.vertices) == 0 if _igs.mesh else True)

_iby, _ihas_faces = av.attributes_by_domain(_i_obj)
_inst_names = [n for n, _t in _iby.get("Instance", [])]
check("007 height listed under Instance", "height" in _inst_names,
      str(_inst_names))
check("007 nothing bogus under Point",
      not [n for n, _t in _iby.get("Point", [])], str(_iby.get("Point")))
check("007 Index/Position intrinsics on Instance",
      "Index" in _inst_names and "Position" in _inst_names, str(_inst_names))
check("007 no Normal intrinsic on Instance (instances have none)",
      "Normal" not in _inst_names, str(_inst_names))
check("007 instance_transform hidden", "instance_transform" not in _inst_names)
check("007 id kept (INT -> hash colour)", "id" in _inst_names, str(_inst_names))

_iviz = av.add_visualizer(bpy.context, target=_i_obj, attribute="height",
                          domain="Instance", style="Heat", display="Markers")
_imd_viz = av.viz_modifier(_iviz)
check("007 Domain round-trips as Instance",
      node_builder.menu_input_name(_imd_viz, "Domain") == "Instance",
      str(node_builder.menu_input_name(_imd_viz, "Domain")))

_ires = gpu_sample.sample_visualizer_targets(_imd_viz)
check("007 sampling returns data", _ires is not None)
if _ires is not None:
    _ipos, _ivals, _idt = _ires
    check("007 one sample per instance, not per realized vert",
          len(_ipos) == _n_inst, f"{len(_ipos)} vs {_n_inst} instances")
    check("007 dtype is the stored FLOAT", _idt == 'FLOAT', str(_idt))
    check("007 values are the real per-instance values",
          len(set(np.round(np.asarray(_ivals), 4))) > 1)

    # Positions must come from instance_transform, not the `position`
    # attribute — on 5.2 that reads uninitialised memory on all but a lucky
    # first call. Ground truth is the depsgraph's own instance matrices.
    _truth = np.array(
        [list(di.matrix_world.translation)
         for di in bpy.context.evaluated_depsgraph_get().object_instances
         if di.is_instance and di.parent
         and di.parent.original == _i_obj],
        dtype=np.float32)
    # Sampled points are CENTROIDS, so they sit at the depsgraph pivot plus
    # the prototype's local centre — here (0, 0, 0.5) from the base-shift.
    # Still validated against the depsgraph rather than against the attribute
    # the implementation reads, so a wrong transform convention is caught.
    _off = np.sort(np.asarray(_ipos), axis=0) - np.sort(_truth, axis=0)
    check("007 positions = depsgraph pivot + prototype centroid offset",
          len(_truth) == len(_ipos)
          and np.allclose(_off, _off[0], atol=1e-3)
          and abs(float(_off[0][2]) - 0.5) < 1e-3,
          f"truth={len(_truth)} sampled={len(_ipos)} offset={_off[0]}")
    check("007 positions are not garbage/zero",
          float(np.abs(np.asarray(_ipos)).max()) > 1e-4
          and float(np.abs(np.asarray(_ipos)).max()) < 1e6,
          str(np.asarray(_ipos)[:1]))

    # Sample AGAIN. The original bug only appeared on the second evaluated
    # geometry in a process, so a single-shot test cannot see it.
    _ires2 = gpu_sample.sample_visualizer_targets(_imd_viz)
    check("007 second sample is identical (not a once-only read)",
          _ires2 is not None
          and np.allclose(np.asarray(_ires2[0]), np.asarray(_ipos), atol=1e-4),
          "second read drifted")

# Other domains must not invent instance data.
for _d in ("Edge", "Face", "Corner"):
    check(f"007 {_d} on an instance-only object samples nothing",
          gpu_sample.sample_evaluated(_i_obj, "height", _d) is None)

# --- the UI layer, which the data-layer tests above cannot see -------------
# The menu builds operator buttons and assigns op.domain. If that enum lacks
# "Instance" the assignment raises AFTER the button exists, so the menu
# truncates at whatever drew first and looks like "no attributes found".
_op_domains = [i.identifier for i in
               bpy.ops.attrviz.add.get_rna_type()
               .properties["domain"].enum_items]
check("007 add-operator domain enum accepts every UI domain",
      all(d in _op_domains for d in node_builder.UI_DOMAINS),
      f"enum={_op_domains}")
_obj_domains = [i.identifier for i in
                bpy.types.Object.bl_rna.properties["attrviz_domain"].enum_items]
check("007 panel Domain enum accepts every UI domain",
      all(d in _obj_domains for d in node_builder.UI_DOMAINS),
      f"enum={_obj_domains}")
# --- Instance positions are CENTROIDS, and Surface paints the instances ---
_i_protos = None
_i_geo = _i_obj.evaluated_get(bpy.context.evaluated_depsgraph_get()) \
    .evaluated_geometry()
_i_cloud = gpu_sample.instances_cloud(_i_geo)
_i_mats = gpu_sample._instance_transforms(_i_cloud)
_i_pivots = np.ascontiguousarray(_i_mats[:, 3, :3])
_i_cent = gpu_sample._instance_positions(_i_cloud, _i_geo)
check("007 centroid differs from the instance pivot",
      not np.allclose(_i_cent, _i_pivots, atol=1e-4),
      "centroid == pivot: markers would sit inside the geometry")
check("007 centroid sits inside the instance's own height span",
      float(_i_cent[:, 2].min()) > float(_i_pivots[:, 2].min()) - 1e-4,
      str(np.round(_i_cent[:3], 3)))

_i_surf = gpu_sample.build_surface_tris(_i_mdviz) \
    if (_i_mdviz := av.viz_modifier(av.add_visualizer(
        bpy.context, target=_i_obj, attribute="height", domain="Instance",
        style="Heat", display="Surface"))) else None
check("007 Surface on Instance builds geometry", _i_surf is not None)
if _i_surf is not None:
    _sp, _scv, _sdt, _snt = _i_surf
    check("007 Surface tris = instances x prototype tris",
          _snt == _n_inst * 12, f"{_snt} vs {_n_inst}*12")
    check("007 Surface corner count is 3 per tri",
          len(_sp) == _snt * 3, f"{len(_sp)} vs {_snt * 3}")
    check("007 Surface carries one distinct value per instance",
          len(set(np.round(np.asarray(_scv), 4))) == _n_inst,
          f"{len(set(np.round(np.asarray(_scv), 4)))} vs {_n_inst}")
    check("007 Surface spans the instanced geometry, not the origin",
          float(np.asarray(_sp)[:, 2].max()) > 0.9,
          str(np.round(np.asarray(_sp).max(axis=0), 2)))

# Instance markers must draw OVER the geometry: the centroid is inside the
# instanced geometry, so a depth test would hide every one of them.
_mk_inst = av.add_visualizer(bpy.context, target=_i_obj, attribute="height",
                             domain="Instance", style="Heat",
                             display="Markers")
_mk_pt = av.add_visualizer(bpy.context, target=_p0_obj, attribute="heat",
                           domain="Point", style="Heat", display="Markers")
_rows = gpu_overlay._gpu_visualizers(bpy.context.scene)
_geo_rows = [r for r in _rows
             if overlay_kind.kind(r[2]) == "geometric"]
_tested, _on_top = gpu_overlay._split_geometric_depth(_geo_rows)
_on_top_names = [r[0].name for r in _on_top]
_tested_names = [r[0].name for r in _tested]
check("007 Instance markers are drawn on top (no depth test)",
      _mk_inst.name in _on_top_names, str(_on_top_names))
check("007 Point markers keep the depth test",
      _mk_pt.name in _tested_names, str(_tested_names))
check("007 nothing lands in both lists",
      not (set(_on_top_names) & set(_tested_names)))

# The RMB menu explains WHY mesh domains are absent on un-realized instances
# rather than silently showing only Instance. Guard the condition that drives
# that label, so it cannot quietly stop firing.
_iby2, _ = av.attributes_by_domain(_i_obj)
check("007 un-realized instances: mesh domains genuinely empty",
      not any(_iby2.get(d) for d in node_builder.DOMAINS),
      str({d: _iby2.get(d) for d in node_builder.DOMAINS}))
check("007 un-realized instances: Instance domain populated",
      bool(_iby2.get(node_builder.INSTANCE_DOMAIN)))
check("007 realize-hint condition fires for this object",
      bool(_iby2.get(node_builder.INSTANCE_DOMAIN))
      and not any(_iby2.get(d) for d in node_builder.DOMAINS))
# ...and does NOT fire for an ordinary mesh, which must keep its intrinsics.
_pby, _ = av.attributes_by_domain(_p0_obj)
check("007 ordinary mesh still lists Point intrinsics",
      "Index" in [n for n, _t in _pby.get("Point", [])]
      and "Position" in [n for n, _t in _pby.get("Point", [])],
      str([n for n, _t in _pby.get("Point", [])]))
check("007 realize-hint does NOT fire for an ordinary mesh",
      not (bool(_pby.get(node_builder.INSTANCE_DOMAIN))
           and not any(_pby.get(d) for d in node_builder.DOMAINS)))

_menu_classes = {
    "Point": "ATTRVIZ_MT_domain_point", "Edge": "ATTRVIZ_MT_domain_edge",
    "Face": "ATTRVIZ_MT_domain_face", "Corner": "ATTRVIZ_MT_domain_corner",
    "Instance": "ATTRVIZ_MT_domain_instance",
}
check("007 every UI domain has a registered menu class",
      all(hasattr(bpy.types, _menu_classes.get(d, ""))
          for d in node_builder.UI_DOMAINS),
      str([d for d in node_builder.UI_DOMAINS
           if not hasattr(bpy.types, _menu_classes.get(d, ""))]))

# --- 009: buffer_stats must survive an empty sample -------------------------
# It is diagnostic rather than draw-path, so it is not hit every redraw -- but
# it fails exactly when someone reaches for it to debug an empty sample, which
# is the worst possible moment. See dev_tasks/009_empty_sample_crash/POR.md.

def _bstats(values, dtype):
    return gpu_sample.buffer_stats(
        (np.zeros((len(values), 3), np.float32), values, dtype))

_empty_ok, _empty_err = True, ""
try:
    for _vals, _dt in ((np.zeros((0, 3), np.float32), "FLOAT_VECTOR"),
                       (np.zeros((0,), np.float32), "FLOAT"),
                       (np.zeros((0,), np.int32), "INT")):
        _st = _bstats(_vals, _dt)
        if _st["n"] != 0 or _st["val_min"] is not None:
            _empty_ok, _empty_err = False, f"{_dt}: {_st}"
except Exception as _e:
    _empty_ok, _empty_err = False, f"{type(_e).__name__}: {_e}"
check("009 buffer_stats accepts an empty sample", _empty_ok, _empty_err)

_st = _bstats(np.array([[3, 4, 0], [0, 0, 5]], np.float32), "FLOAT_VECTOR")
check("009 buffer_stats min/max unchanged on a vector sample",
      _st["val_min"] == 0.0 and _st["val_max"] == 5.0, str(_st))

check("009 no ambiguous reshape(len(x), -1) in gpu_sample",
      "reshape(len(" not in open(
          os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                       "attrviz", "gpu_sample.py"), encoding="utf-8").read())

# --- 009 follow-up: authored lowercase "normal" vs the Normal intrinsic -----
# 009 flagged a suspected collision. There is none: the GN tree compares the
# attribute name EXACTLY against "Normal", so an authored lowercase "normal"
# routes to a Named Attribute lookup instead. Locked in so it stays true.
# (Only lowercase "position" is deliberately aliased onto the intrinsic.)

_al_me = bpy.data.meshes.new("AliasMesh")
_al_bm = bmesh.new()
bmesh.ops.create_grid(_al_bm, x_segments=2, y_segments=2, size=1.0)
_al_bm.to_mesh(_al_me)
_al_bm.free()
_al_obj = bpy.data.objects.new("AliasObj", _al_me)
bpy.context.collection.objects.link(_al_obj)
_al_lay = _al_me.attributes.new("normal", 'FLOAT_VECTOR', 'POINT')
for _d in _al_lay.data:
    _d.vector = (7.0, 0.0, 0.0)
bpy.context.view_layer.update()

_al_by, _ = av.attributes_by_domain(_al_obj)
_al_pts = [n for n, _t in _al_by.get("Point", [])]
check("009 authored 'normal' and intrinsic 'Normal' are both offered",
      "normal" in _al_pts and "Normal" in _al_pts, str(_al_pts))

_al_watch = av.active_scope(bpy.context, create=True)
av._link_to_watch(bpy.context, [_al_obj])


def _al_sample(attr):
    _v = av.add_visualizer(bpy.context, scope=_al_watch, attribute=attr,
                           domain="Point", style="Heat", display="Arrows")
    _r = gpu_sample.sample_visualizer_targets(av.viz_modifier(_v), cap=50000)
    return None if _r is None else np.asarray(_r[1])


_al_low = _al_sample("normal")
_al_cap = _al_sample("Normal")
check("009 authored 'normal' reads the AUTHORED data",
      _al_low is not None and abs(float(_al_low[0][0]) - 7.0) < 1e-4,
      str(None if _al_low is None else _al_low[0]))
check("009 intrinsic 'Normal' still reads the real normal",
      _al_cap is not None and abs(float(_al_cap[0][2]) - 1.0) < 1e-3,
      str(None if _al_cap is None else _al_cap[0]))
check("009 only lowercase 'position' is aliased onto an intrinsic",
      node_builder.INTRINSIC_ALIASES == frozenset({"position"}),
      str(node_builder.INTRINSIC_ALIASES))

# ---------------------------------------------------------------------------
print("")
print("== 016: a MESH that EVALUATES to a point cloud ==")
# The 006 cases use a NATIVE PointCloud object. A mesh carrying Mesh to Points
# is type MESH and evaluates to a cloud -- a different shape of the same case,
# and the one that shipped broken: nothing drew but Tags, because the
# decisions were made from obj.type / obj.data instead of evaluated geometry.

_m2p_me = bpy.data.meshes.new("M2P")
_bm2 = _bm.new()
_bm.ops.create_uvsphere(_bm2, u_segments=8, v_segments=6, radius=1.0)
_bm2.to_mesh(_m2p_me)
_bm2.free()
_m2p_obj = bpy.data.objects.new("M2P", _m2p_me)
bpy.context.scene.collection.objects.link(_m2p_obj)

_m2p_ng = bpy.data.node_groups.new("M2P_tree", 'GeometryNodeTree')
_m2p_ng.interface.new_socket("Geometry", in_out='INPUT',
                             socket_type='NodeSocketGeometry')
_m2p_ng.interface.new_socket("Geometry", in_out='OUTPUT',
                             socket_type='NodeSocketGeometry')
_gi = _m2p_ng.nodes.new("NodeGroupInput")
_go = _m2p_ng.nodes.new("NodeGroupOutput")
_m2pn = _m2p_ng.nodes.new("GeometryNodeMeshToPoints")
_posn = _m2p_ng.nodes.new("GeometryNodeInputPosition")
_stn = _m2p_ng.nodes.new("GeometryNodeStoreNamedAttribute")
_stn.data_type = 'FLOAT_VECTOR'
_stn.domain = 'POINT'
_stn.inputs["Name"].default_value = "Cd"
_m2p_ng.links.new(_gi.outputs[0], _m2pn.inputs["Mesh"])
_m2p_ng.links.new(_m2pn.outputs["Points"], _stn.inputs["Geometry"])
_m2p_ng.links.new(_posn.outputs["Position"], _stn.inputs["Value"])
_m2p_ng.links.new(_stn.outputs["Geometry"], _go.inputs[0])
_m2p_md = _m2p_obj.modifiers.new("GN", 'NODES')
_m2p_md.node_group = _m2p_ng
bpy.context.view_layer.update()

check("016 object type is still MESH", _m2p_obj.type == "MESH", _m2p_obj.type)
check("016 evaluated_component says POINTCLOUD",
      gpu_sample.evaluated_component(_m2p_obj) == "POINTCLOUD",
      gpu_sample.evaluated_component(_m2p_obj))

# A scope of its OWN: watch_has_faces answers for every watched object, and
# the default scope already holds meshes from the cases above.
_m2p_scope = av.new_scope_collection(bpy.context, "m2p_only")
av._link_to_watch(bpy.context, [_m2p_obj], _m2p_scope)
_m2p_viz = av.add_visualizer(bpy.context, scope=_m2p_scope, attribute="Cd",
                             domain="Point", style="RGB", display="Markers")
bpy.context.view_layer.update()
_m2p_vmd = av.viz_modifier(_m2p_viz)

check("016 watch_has_faces False (the cloud has none)",
      gpu_sample.watch_has_faces(_m2p_vmd) is False,
      str(gpu_sample.watch_has_faces(_m2p_vmd)))

_m2p_names = gpu_overlay._eval_attr_names(
    _m2p_obj, bpy.context.evaluated_depsgraph_get())
check("016 the cloud attribute is visible to the mute probe",
      _m2p_names is not None and "Cd" in _m2p_names.get("Point", {}),
      str(None if _m2p_names is None else sorted(_m2p_names.get("Point", {}))))
check("016 Normal withheld (a cloud has no vertices)",
      _m2p_names is not None
      and node_builder.NORMAL_ATTR not in _m2p_names.get("Point", {}),
      str(None if _m2p_names is None else sorted(_m2p_names.get("Point", {}))))

_m2p_res = gpu_sample.sample_visualizer_targets(_m2p_vmd)
check("016 the sampler returns the cloud points",
      _m2p_res is not None and gpu_sample.buffer_stats(_m2p_res)["n"] > 0,
      str(None if _m2p_res is None
          else gpu_sample.buffer_stats(_m2p_res)["n"]))


print(f"\n== Result: {PASS} passed, {FAIL} failed ==")
if FAIL:
    sys.exit(1)
print("ALL GPU SAMPLE TESTS PASSED")
