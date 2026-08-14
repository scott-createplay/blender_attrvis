"""Build a denser AttrViz stress .blend (icosphere, ~10k verts at subdiv 6).

Same point attrs as the test cube (height / flow / …) so Tags, Markers,
Arrows, and Surface can be pushed past the tiny cube.

Run:
  blender --background --factory-startup --python-exit-code 1 \\
      --python examples/build_attr_stress_scene.py

  blender --background --factory-startup --python-exit-code 1 \\
      --python examples/build_attr_stress_scene.py -- --subdiv 7

Writes: examples/attrviz_stress.blend
"""
from __future__ import annotations

import argparse
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "examples", "attrviz_stress.blend")


def _argv_after_dd():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return []


def _parse():
    p = argparse.ArgumentParser(description="AttrViz stress scene")
    p.add_argument("--subdiv", type=int, default=6,
                   help="Icosphere subdivisions (5 ≈ 2.5k verts, 6 ≈ 10k, 7 ≈ 40k)")
    p.add_argument("--radius", type=float, default=2.0)
    return p.parse_args(_argv_after_dd())


def _clear():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                  bpy.data.cameras, bpy.data.collections):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def _make_ico(name="Attr Stress", subdivisions=5, radius=2.0):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(
        bm, subdivisions=max(1, int(subdivisions)), radius=radius,
    )
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _foreach_set(attr, values, field="value", width=1):
    import array
    flat = []
    for v in values:
        if width == 1:
            flat.append(float(v))
        else:
            flat.extend(float(c) for c in v)
    arr = array.array("f", flat)
    attr.data.foreach_set(field, arr)


def _author_attributes(obj):
    me = obj.data
    n = len(me.vertices)
    positions = [v.co.copy() for v in me.vertices]

    height, radius, wave, checker, cluster, flow, stretch = (
        [], [], [], [], [], [], [],
    )
    for co in positions:
        x, y, z = co
        height.append(z)
        radius.append(math.sqrt(x * x + y * y + z * z))
        wave.append(0.5 + 0.5 * math.sin(x * math.pi) * math.sin(y * math.pi))
        cx = 1 if x >= 0 else 0
        cy = 1 if y >= 0 else 0
        cz = 1 if z >= 0 else 0
        checker.append(float((cx + cy + cz) % 2))
        d = (co - Vector((0.7, 0.7, 0.7))).length
        cluster.append(max(0.0, 1.0 - d / 1.2))
        flow.append((-y * 0.6, x * 0.6, 0.15 * math.sin(x + y)))
        stretch.append((x, y, z))

    specs = (
        ("height", "FLOAT", "POINT", height, "value", 1),
        ("radius", "FLOAT", "POINT", radius, "value", 1),
        ("wave", "FLOAT", "POINT", wave, "value", 1),
        ("checker", "FLOAT", "POINT", checker, "value", 1),
        ("cluster", "FLOAT", "POINT", cluster, "value", 1),
        ("flow", "FLOAT_VECTOR", "POINT", flow, "vector", 3),
        ("stretch", "FLOAT_VECTOR", "POINT", stretch, "vector", 3),
    )
    for name, dtype, domain, values, field, width in specs:
        if name in me.attributes:
            me.attributes.remove(me.attributes[name])
        attr = me.attributes.new(name, dtype, domain)
        _foreach_set(attr, values, field=field, width=width)

    if "face_id" in me.attributes:
        me.attributes.remove(me.attributes["face_id"])
    face_attr = me.attributes.new("face_id", "INT", "FACE")
    for i, d in enumerate(face_attr.data):
        d.value = i

    print(f"[attrviz] stress mesh: {n} verts / {len(me.polygons)} faces")


def _setup_view(radius):
    sun_data = bpy.data.lights.new("Key Sun", "SUN")
    sun_data.energy = 2.5
    sun = bpy.data.objects.new("Key Sun", sun_data)
    sun.rotation_euler = (math.radians(50), math.radians(-15),
                          math.radians(30))
    bpy.context.scene.collection.objects.link(sun)

    dist = radius * 3.4
    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    cam.location = (dist, -dist, dist * 0.7)
    cam.rotation_euler = (math.radians(58), 0.0, math.radians(43))
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    nt = world.node_tree
    if nt is not None:
        bg = next((n for n in nt.nodes if n.type == "BACKGROUND"), None)
        if bg is not None:
            bg.inputs[0].default_value = (0.04, 0.045, 0.05, 1.0)
            bg.inputs[1].default_value = 0.6


def main():
    args = _parse()
    _clear()
    obj = _make_ico(subdivisions=args.subdiv, radius=args.radius)
    _author_attributes(obj)
    _setup_view(args.radius)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=OUT)
    print(f"[attrviz] wrote {OUT}")


if __name__ == "__main__":
    main()
