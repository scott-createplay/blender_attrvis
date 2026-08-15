"""Probe Blender 5 PointCloud allocation + RNA. Headless.

blender --background --factory-startup --python-exit-code 1 \
  --python dev_tasks/006_points_input/probe_pointcloud.py
"""
from __future__ import annotations

import traceback

import bpy
import numpy as np


def dump(label, obj):
    print(f"\n== {label} ==")
    print(f"  type={obj.type!r} data={type(obj.data).__name__}")
    data = obj.data
    print(f"  dir points: {[a for a in dir(data) if 'point' in a.lower() or a in ('attributes',)]}")
    pts = getattr(data, "points", None)
    print(f"  points={pts} len={len(pts) if pts is not None else None}")
    attrs = getattr(data, "attributes", None)
    if attrs is not None:
        names = [a.name for a in attrs]
        print(f"  attributes={names}")
        try:
            print(f"  domain_size POINT={attrs.domain_size('POINT')}")
        except Exception as e:
            print(f"  domain_size failed: {e}")
    try:
        gs = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
        pc = getattr(gs, "pointcloud", None)
        me = getattr(gs, "mesh", None)
        print(f"  gs.mesh={me} verts={len(me.vertices) if me else None}")
        print(f"  gs.pointcloud={pc} points={len(pc.points) if pc and hasattr(pc, 'points') else None}")
        if pc is not None:
            print(f"  gs.pc attrs={[a.name for a in pc.attributes]}")
    except Exception as e:
        print(f"  evaluated_geometry failed: {e}")


def try_new_empty():
    print("\n-- bpy.data.pointclouds.new --")
    pc = bpy.data.pointclouds.new("ProbeEmpty")
    obj = bpy.data.objects.new("ProbeEmpty", pc)
    bpy.context.collection.objects.link(obj)
    dump("empty new()", obj)
    # try add
    for meth in ("add", "new", "foreach_set"):
        fn = getattr(pc.points, meth, None)
        print(f"  points.{meth}={fn}")
    try:
        pc.points.add(8)
        print(f"  points.add(8) -> len={len(pc.points)}")
    except Exception as e:
        print(f"  points.add failed: {type(e).__name__}: {e}")
    return obj


def try_convert():
    print("\n-- convert vert mesh → POINTCLOUD --")
    me = bpy.data.meshes.new("VertOnly")
    me.vertices.add(8)
    for i, v in enumerate(me.vertices):
        v.co = (i % 4, i // 4, 0.0)
    heat = me.attributes.new("heat", 'FLOAT', 'POINT')
    for i, d in enumerate(heat.data):
        d.value = i / 7.0
    obj = bpy.data.objects.new("VertOnly", me)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    try:
        bpy.ops.object.convert(target='POINTCLOUD')
        dump("after convert", bpy.context.view_layer.objects.active)
        return bpy.context.view_layer.objects.active
    except Exception:
        print("  convert failed:")
        traceback.print_exc()
        return None


def try_ops():
    print("\n-- object operators with pointcloud in name --")
    names = [op for op in dir(bpy.ops.object) if "point" in op.lower() or "cloud" in op.lower()]
    print(f"  {names}")
    print("  mesh ops:", [op for op in dir(bpy.ops.mesh) if "point" in op.lower()])


def try_random_add():
    print("\n-- bpy.ops.object.pointcloud_random_add --")
    try:
        bpy.ops.object.pointcloud_random_add()
        obj = bpy.context.view_layer.objects.active
        dump("random_add", obj)
        return obj
    except Exception:
        print("  random_add failed:")
        traceback.print_exc()
        return None


def try_gn_points(n=8):
    print("\n-- GN Points node spawn + copy evaluated --")
    pc = bpy.data.pointclouds.new("GNCloud")
    obj = bpy.data.objects.new("GNCloud", pc)
    bpy.context.collection.objects.link(obj)
    ng = bpy.data.node_groups.new("ProbePoints", 'GeometryNodeTree')
    ng.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nodes = ng.nodes
    links = ng.links
    out = nodes.new("NodeGroupOutput")
    pts = nodes.new("GeometryNodePoints")
    # count socket
    for inp in pts.inputs:
        print(f"  Points input: {inp.name} {inp.type} default={getattr(inp, 'default_value', None)}")
    try:
        pts.inputs["Count"].default_value = n
    except Exception as e:
        print(f"  Count set failed: {e}")
        try:
            pts.inputs[0].default_value = n
        except Exception as e2:
            print(f"  inputs[0] failed: {e2}")
    links.new(pts.outputs["Points" if "Points" in pts.outputs else pts.outputs[0].name],
              out.inputs["Geometry"])
    md = obj.modifiers.new("spawn", 'NODES')
    md.node_group = ng
    bpy.context.view_layer.update()
    dump("GN evaluated (modifier on)", obj)
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    try:
        obj.data = ev.data.copy()
        print(f"  copied ev.data type={type(obj.data).__name__} points={len(getattr(obj.data, 'points', []) or [])}")
        obj.modifiers.remove(md)
        dump("after copy+remove modifier", obj)
    except Exception:
        print("  copy evaluated failed:")
        traceback.print_exc()
    return obj


def try_read_positions(obj):
    print(f"\n-- read positions from {obj.name} --")
    data = obj.data
    pts = getattr(data, "points", None)
    if pts is None or len(pts) == 0:
        print("  no points on data")
        return
    n = len(pts)
    sample = pts[0]
    print(f"  Point RNA: {[a for a in dir(sample) if not a.startswith('_')][:40]}")
    if hasattr(sample, "co"):
        cos = np.empty(n * 3, dtype=np.float32)
        try:
            pts.foreach_get("co", cos)
            print(f"  foreach_get co ok first={cos[:3]}")
        except Exception as e:
            print(f"  foreach_get co failed: {e}")
            print(f"  pts[0].co={sample.co}")
    attr = data.attributes.get("position")
    print(f"  position attr={attr}")
    if attr is not None:
        a = np.empty(n * 3, dtype=np.float32)
        try:
            attr.data.foreach_get("vector", a)
            print(f"  position foreach_get ok first={a[:3]}")
        except Exception as e:
            print(f"  position foreach_get failed: {e}")


def main():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    print("Blender", bpy.app.version_string)
    try_ops()
    empty = try_new_empty()
    converted = try_convert()
    gn = try_gn_points(8)
    for obj in (empty, converted, gn):
        if obj is not None:
            try_read_positions(obj)
    print("\nPROBE DONE")


if __name__ == "__main__":
    main()
