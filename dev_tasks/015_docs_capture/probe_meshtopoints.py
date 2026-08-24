"""Reproduce: UV sphere -> Mesh to Points -> named attribute, nothing draws but Tags.

Mesh to Points makes the evaluated geometry a POINTCLOUD, so this exercises the
006 path. Sampling needs no GL, so the question "does the sampler return any
points and values" is answerable headlessly — and if it returns nothing, the
draw side was never the problem.

Run:
  blender --background --factory-startup \
      --python dev_tasks/015_docs_capture/probe_meshtopoints.py
"""
from __future__ import annotations

import os
import sys

import bmesh
import bpy

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import attrviz as av  # noqa: E402
from attrviz import gpu_sample, node_builder  # noqa: E402


def build(color_type="FLOAT_VECTOR"):
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    me = bpy.data.meshes.new("Sphere")
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=1.0)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new("Sphere", me)
    bpy.context.scene.collection.objects.link(obj)

    ng = bpy.data.node_groups.new("MeshToPoints", 'GeometryNodeTree')
    ng.interface.new_socket("Geometry", in_out='INPUT',
                            socket_type='NodeSocketGeometry')
    ng.interface.new_socket("Geometry", in_out='OUTPUT',
                            socket_type='NodeSocketGeometry')
    gin = ng.nodes.new("NodeGroupInput")
    gout = ng.nodes.new("NodeGroupOutput")
    m2p = ng.nodes.new("GeometryNodeMeshToPoints")
    # NOT Input Normal: a point cloud has no normals, so it evaluates to
    # zero and the probe would blame AttrViz for the graph's own zeros.
    nrm = ng.nodes.new("GeometryNodeInputPosition")
    st = ng.nodes.new("GeometryNodeStoreNamedAttribute")
    st.data_type = color_type
    st.domain = 'POINT'
    st.inputs["Name"].default_value = "Cd"
    ng.links.new(gin.outputs[0], m2p.inputs["Mesh"])
    ng.links.new(m2p.outputs["Points"], st.inputs["Geometry"])
    ng.links.new(nrm.outputs["Position"], st.inputs["Value"])
    ng.links.new(st.outputs["Geometry"], gout.inputs[0])

    md = obj.modifiers.new("GN", 'NODES')
    md.node_group = ng
    bpy.context.view_layer.update()
    return obj


def report(obj, label):
    print("\n" + "=" * 68)
    print(label)
    print("=" * 68)

    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    gs = ev
    print(f"  evaluated type            : {ev.type}")
    try:
        me = ev.to_mesh()
        print(f"  to_mesh() verts / polys   : {len(me.vertices)} / "
              f"{len(me.polygons)}")
        ev.to_mesh_clear()
    except Exception as exc:
        print(f"  to_mesh() raised          : {exc!r}")

    # What does Blender itself hold on the evaluated cloud?
    try:
        gs = ev.evaluated_geometry()
        pc = getattr(gs, "pointcloud", None)
        if pc is not None:
            import numpy as np
            a = pc.attributes.get("Cd")
            print(f"  cloud points              : {len(pc.points)}")
            print(f"  cloud has 'Cd'            : {a is not None}")
            if a is not None:
                n = len(a.data)
                buf = np.empty(n * (3 if a.data_type == 'FLOAT_VECTOR' else 4),
                               dtype=np.float32)
                a.data.foreach_get("vector" if a.data_type == 'FLOAT_VECTOR'
                                   else "color", buf)
                print(f"  cloud Cd min/max          : "
                      f"{float(buf.min()):.4f} / {float(buf.max()):.4f}")
        else:
            print("  evaluated_geometry().pointcloud is None")
    except Exception as exc:
        print(f"  geometry read raised      : {exc!r}")

    by, _ = av.attributes_by_domain(obj)
    print(f"  menu offers on Point      : "
          f"{[n for n, _t in by.get('Point', [])]}")

    viz = av.add_visualizer(bpy.context, scope=av.active_scope(
        bpy.context, create=True), attribute="Cd", domain="Point",
        style="RGB", display="Markers")
    av._link_to_watch(bpy.context, [obj], av.active_scope(bpy.context))
    bpy.context.view_layer.update()
    md = av.viz_modifier(viz)

    meshes = gpu_sample.watch_meshes_for_visualizer(md)
    print(f"  watch_meshes_for_visualizer: {[o.name for o in meshes]}")
    print(f"  watch_has_faces           : {gpu_sample.watch_has_faces(md)}")

    try:
        res = gpu_sample.sample_visualizer_targets(md)
    except Exception as exc:
        print(f"  sample_visualizer_targets RAISED: {exc!r}")
        import traceback
        traceback.print_exc()
        return
    stats = gpu_sample.buffer_stats(res) if res is not None else None
    print(f"  sample result             : {type(res).__name__}")
    print(f"  buffer_stats              : {stats}")
    for attr in ("positions", "values", "dtype", "domain"):
        val = getattr(res, attr, None)
        if val is None:
            print(f"    {attr:10s}: None")
        elif hasattr(val, "shape"):
            print(f"    {attr:10s}: shape {val.shape}")
        else:
            print(f"    {attr:10s}: {val}")


def main():
    av.register()
    for dt in ("FLOAT_VECTOR", "FLOAT_COLOR"):
        obj = build(dt)
        report(obj, f"Mesh to Points + Store Named Attribute 'Cd' ({dt})")


main()
