"""Diagnose 006 pipeline against examples/attrviz_pointclouds.blend."""
from __future__ import annotations

import os
import sys

import bpy

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BLEND = os.path.join(REPO, "examples", "attrviz_pointclouds.blend")
sys.path.insert(0, REPO)

bpy.ops.wm.open_mainfile(filepath=BLEND)

import attrviz as av  # noqa: E402
from attrviz import gpu_overlay, gpu_sample, node_builder  # noqa: E402

av.register()
bpy.context.scene.attrviz_gpu_markers = True
bpy.context.view_layer.update()

ATTRS = ("heat", "cluster_id", "flow", "strand_id", "density", "wave")

print("\n== objects ==")
watch = bpy.data.collections.get("attrvis")
print(f"attrvis={[o.name for o in (watch.objects if watch else [])]}")
print(f"WATCH_TYPES={gpu_sample.WATCH_TYPES}")

for obj in bpy.data.objects:
    if obj.type not in ("POINTCLOUD", "MESH"):
        continue
    if av.is_visualizer(obj):
        md = av.viz_modifier(obj)
        attr = node_builder.get_input(md, "Attribute") if md else "?"
        disp = node_builder.menu_input_name(md, "Display") if md else "?"
        print(f"  VIZ {obj.name} hide_vp={obj.hide_viewport} "
              f"attr={attr} display={disp}")
        continue
    data = obj.data
    n_data = 0
    try:
        n_data = len(getattr(data, "points", []) or [])
    except Exception:
        n_data = len(getattr(data, "vertices", []) or [])
    ev, me, pc, gs = gpu_sample._evaluated_source(obj)
    n_pc = gpu_sample._point_count(pc) if pc is not None else 0
    n_me = len(me.vertices) if me is not None else 0
    print(f"\n  {obj.name} type={obj.type} data_n={n_data}")
    print(f"    hasattr vertices={hasattr(data, 'vertices')} "
          f"points={hasattr(data, 'points')}")
    if gs is not None:
        gspc = getattr(gs, "pointcloud", None)
        gsme = getattr(gs, "mesh", None)
        print(f"    gs.pc={gspc is not None} gs.mesh={gsme is not None} "
              f"is_pc_data={gpu_sample._is_pointcloud_data(gspc)} "
              f"has_pts={gpu_sample._geom_has_points(gspc)}")
        if gspc is not None:
            print(f"    gs.pc hasattr vertices={hasattr(gspc, 'vertices')} "
                  f"points={hasattr(gspc, 'points')} "
                  f"n={gpu_sample._point_count(gspc)}")
            print(f"    gs.pc attrs="
                  f"{[(a.name, a.domain, a.data_type) for a in gspc.attributes]}")
    print(f"    source me_n={n_me} pc_n={n_pc}")
    for aname in ATTRS:
        r = gpu_sample.sample_evaluated(obj, aname, "Point", world_space=True)
        if r is None:
            print(f"    sample {aname}: NONE")
        else:
            pos, vals, dt = r
            print(f"    sample {aname}: n={len(pos)} dtype={dt} "
                  f"pos0={pos[0] if len(pos) else None}")

print("\n== visualizer samples / refresh ==")
for viz in av.visualizers(bpy.context.scene):
    md = av.viz_modifier(viz)
    attr = node_builder.get_input(md, "Attribute")
    disp = node_builder.menu_input_name(md, "Display")
    watched = gpu_sample.watch_meshes_for_visualizer(md)
    print(f"\n  {viz.name} hide={viz.hide_viewport} attr={attr} display={disp}")
    print(f"    watch={[o.name for o in watched]}")
    samp = gpu_sample.sample_visualizer_targets(md, cap=50000)
    if samp is None:
        print("    sample_visualizer_targets: NONE")
    else:
        print(f"    sample_visualizer_targets: n={len(samp[0])} dtype={samp[2]}")
    gpu_overlay.invalidate(viz)
    entry = gpu_overlay._refresh_viz(viz, md, disp)
    print(f"    refresh empty={entry.get('empty')} n={entry.get('n')} "
          f"mode={entry.get('mode')} batch={entry.get('batch') is not None}")
