"""Scrub-tick cost: GPU overlay vs GN path, against a no-visualizer baseline.

Answers "what does correct invalidation cost per scrub tick, and is the GN
path secretly the scale path?" (it is not — see ../POR.md).

Run:
  blender --background --factory-startup \
      --python dev_tasks/008_overlay_invalidation/tests/bench_invalidation.py

Two things are load-bearing and were both wrong in earlier drafts:

* **Force lazy evaluation.** Blender evaluates on access, not on
  ``dg.update()``. Without touching the evaluated data the "eval" column
  reads 0.0 ms and the cost silently lands in whichever column reads it
  first.
* **Measure against a no-visualizer baseline.** With GPU Overlay off the
  viz GN tree evaluates *inside* ``dg.update()``, so any attempt to split
  "source eval" from "viz eval" hides most of the GN cost in the source
  column. An earlier split reported a 3.2x gap where the real one is 12x.

``distinct`` must read n/n every row. If it does not, the seed change is
not re-evaluating and every number here is meaningless.
"""
import os
import sys
import time

import bpy
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, REPO)

import attrviz as av  # noqa: E402
from attrviz import gpu_sample, node_builder  # noqa: E402

av.register()
SCENE = bpy.context.scene
ITERS = 4
SCALES = (200, 400, 700, 1000)          # nside -> nside^2 verts


def build(nside):
    """Grid whose positions AND attribute are driven by a Seed input."""
    me = bpy.data.meshes.new(f"S{nside}")
    obj = bpy.data.objects.new(f"S{nside}", me)
    bpy.context.collection.objects.link(obj)
    t = bpy.data.node_groups.new(f"gn{nside}", "GeometryNodeTree")
    t.interface.new_socket("Geometry", in_out='OUTPUT',
                           socket_type="NodeSocketGeometry")
    t.interface.new_socket("Seed", in_out='INPUT',
                           socket_type="NodeSocketInt")
    gi = t.nodes.new("NodeGroupInput")
    go = t.nodes.new("NodeGroupOutput")
    grid = t.nodes.new("GeometryNodeMeshGrid")
    grid.inputs["Vertices X"].default_value = nside
    grid.inputs["Vertices Y"].default_value = nside
    grid.inputs["Size X"].default_value = 50.0
    grid.inputs["Size Y"].default_value = 50.0
    # 5.2 collapsed Random Value's per-type outputs to one dynamic socket.
    rnd = t.nodes.new("FunctionNodeRandomValue")
    rnd.data_type = 'FLOAT'
    store = t.nodes.new("GeometryNodeStoreNamedAttribute")
    store.data_type = 'FLOAT'
    store.domain = 'POINT'
    store.inputs["Name"].default_value = "heat"
    setpos = t.nodes.new("GeometryNodeSetPosition")
    off = t.nodes.new("ShaderNodeCombineXYZ")
    t.links.new(gi.outputs["Seed"], rnd.inputs["Seed"])
    t.links.new(grid.outputs["Mesh"], store.inputs["Geometry"])
    t.links.new(rnd.outputs[0], store.inputs["Value"])
    t.links.new(store.outputs["Geometry"], setpos.inputs["Geometry"])
    t.links.new(rnd.outputs[0], off.inputs["Z"])
    t.links.new(off.outputs["Vector"], setpos.inputs["Offset"])
    t.links.new(setpos.outputs["Geometry"], go.inputs[0])
    md = obj.modifiers.new("gn", 'NODES')
    md.node_group = t
    return obj, md


def tick(obj, gnmd, seed_base, make_ink):
    """Mean ms of one scrub tick: change Seed, evaluate, make ink ready."""
    out = []
    for i in range(ITERS):
        node_builder.set_input(gnmd, "Seed", seed_base + i * 13)
        obj.update_tag()
        t0 = time.perf_counter()
        bpy.context.view_layer.update()
        deps = bpy.context.evaluated_depsgraph_get()
        deps.update()
        ev = obj.evaluated_get(deps)
        _ = ev.data.vertices[0].co.z        # force the lazy GN evaluation
        make_ink(deps)
        t1 = time.perf_counter()
        if i:                               # drop the cold iteration
            out.append((t1 - t0) * 1000.0)
    return float(np.mean(out))


def main():
    print("%9s | %10s | %11s | %11s | %10s | %10s | %-9s | %s" % (
        "verts", "baseline", "GPU total", "GN total",
        "GPU marg.", "GN marg.", "winner", "distinct"))
    for nside in SCALES:
        obj, gnmd = build(nside)
        base = tick(obj, gnmd, 500, lambda deps: None)

        # GPU overlay: Python marshalling, GN carrier suppressed.
        SCENE.attrviz_gpu_markers = True
        viz = av.add_visualizer(bpy.context, target=obj, attribute="heat",
                                domain="Point", style="Heat",
                                display="Markers")
        md = av.viz_modifier(viz)
        state = {"n": 0, "seen": set()}

        def ink_gpu(_deps, _st=state):
            pos, vals, _dt = gpu_sample.sample_visualizer_targets(md)
            _st["n"] = len(pos)
            _st["seen"].add(round(float(vals[0]), 6))

        gpu_ms = tick(obj, gnmd, 1500, ink_gpu)
        bpy.data.objects.remove(viz, do_unlink=True)

        # GN path: C++ geometry synthesis through the depsgraph.
        SCENE.attrviz_gpu_markers = False
        viz_gn = av.add_visualizer(bpy.context, target=obj, attribute="heat",
                                   domain="Point", style="Heat",
                                   display="Markers")

        def ink_gn(deps, _v=viz_gn):
            _ = repr(_v.evaluated_get(deps).evaluated_geometry())

        gn_ms = tick(obj, gnmd, 2500, ink_gn)
        bpy.data.objects.remove(viz_gn, do_unlink=True)

        gpu_marg, gn_marg = gpu_ms - base, gn_ms - base
        win = ("GPU %.1fx" % (gn_marg / gpu_marg) if gpu_marg < gn_marg
               else "GN %.1fx" % (gpu_marg / gn_marg))
        print("%9d | %8.1fms | %9.1fms | %9.1fms | %8.1fms | %8.1fms | "
              "%-9s | %d/%d" % (
                  state["n"], base, gpu_ms, gn_ms, gpu_marg, gn_marg, win,
                  len(state["seen"]), ITERS))


main()
