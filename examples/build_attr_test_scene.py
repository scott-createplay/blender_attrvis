"""Build an AttrViz test .blend: subdivided cube with authored attributes.

Attributes (all on POINT domain unless noted):
  height   FLOAT         Z height — Heat / Surface
  radius   FLOAT         distance from origin — Heat / Markers
  wave     FLOAT         sin ridge field — Heat
  checker  FLOAT         0/1 vertex checker — Heat
  cluster  FLOAT         soft blob near +X+Y+Z corner — Heat
  flow     FLOAT_VECTOR  tangential swirl — RGB or Arrows
  stretch  FLOAT_VECTOR  outward from center — RGB or Arrows
  (+ built-in position / normal once evaluated)

Run:
  blender --background --factory-startup --python-exit-code 1 \\
      --python examples/build_attr_test_scene.py

Writes: examples/attrviz_test_cube.blend

Then open the .blend, select the cube, RMB → Visualize Attribute.
"""
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "examples", "attrviz_test_cube.blend")


def _clear():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                  bpy.data.cameras, bpy.data.collections):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def _make_cube(name="Attr Cube", size=2.0, cuts=5):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts,
                              use_grid_fill=True)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _foreach_set(attr, values, field="value", width=1):
    flat = []
    for v in values:
        if width == 1:
            flat.append(float(v))
        else:
            flat.extend(float(c) for c in v)
    import array
    arr = array.array('f', flat)
    attr.data.foreach_set(field, arr)


def _author_attributes(obj):
    me = obj.data
    n = len(me.vertices)
    positions = [v.co.copy() for v in me.vertices]

    height = []
    radius = []
    wave = []
    checker = []
    cluster = []
    flow = []
    stretch = []

    for i, co in enumerate(positions):
        x, y, z = co
        height.append(z)
        radius.append(math.sqrt(x * x + y * y + z * z))
        wave.append(0.5 + 0.5 * math.sin(x * math.pi) * math.sin(y * math.pi))
        # checker on a rough 2×2×2 lattice of the cube
        cx = 1 if x >= 0 else 0
        cy = 1 if y >= 0 else 0
        cz = 1 if z >= 0 else 0
        checker.append(float((cx + cy + cz) % 2))
        # soft blob toward the +X+Y+Z corner
        d = (co - Vector((0.7, 0.7, 0.7))).length
        cluster.append(max(0.0, 1.0 - d / 1.2))
        # swirl around Z
        flow.append((-y * 0.6, x * 0.6, 0.15 * math.sin(x + y)))
        # outward
        stretch.append((x, y, z))

    specs = (
        ("height", 'FLOAT', 'POINT', height, "value", 1),
        ("radius", 'FLOAT', 'POINT', radius, "value", 1),
        ("wave", 'FLOAT', 'POINT', wave, "value", 1),
        ("checker", 'FLOAT', 'POINT', checker, "value", 1),
        ("cluster", 'FLOAT', 'POINT', cluster, "value", 1),
        ("flow", 'FLOAT_VECTOR', 'POINT', flow, "vector", 3),
        ("stretch", 'FLOAT_VECTOR', 'POINT', stretch, "vector", 3),
    )
    for name, dtype, domain, values, field, width in specs:
        if name in me.attributes:
            me.attributes.remove(me.attributes[name])
        attr = me.attributes.new(name, dtype, domain)
        _foreach_set(attr, values, field=field, width=width)

    # Face-domain integer ids — RMB → Face → face_id → Random + Surface
    if "face_id" in me.attributes:
        me.attributes.remove(me.attributes["face_id"])
    face_attr = me.attributes.new("face_id", 'INT', 'FACE')
    for i, d in enumerate(face_attr.data):
        d.value = i

    print(f"[attrviz] authored {len(specs)} point attrs + face_id on "
          f"{n} verts / {len(me.polygons)} faces")


def _setup_view():
    # camera + light so the file opens ready to inspect
    sun_data = bpy.data.lights.new("Key Sun", 'SUN')
    sun_data.energy = 2.5
    sun = bpy.data.objects.new("Key Sun", sun_data)
    sun.rotation_euler = (math.radians(50), math.radians(-15),
                          math.radians(30))
    bpy.context.scene.collection.objects.link(sun)

    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    cam.location = (4.5, -4.8, 3.4)
    cam.rotation_euler = (math.radians(58), 0.0, math.radians(43))
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    # world soft grey (avoid World.use_nodes — deprecated toward 6.0)
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    nt = world.node_tree
    if nt is not None:
        bg = next((n for n in nt.nodes if n.type == 'BACKGROUND'), None)
        if bg is not None:
            bg.inputs[0].default_value = (0.04, 0.045, 0.05, 1.0)
            bg.inputs[1].default_value = 0.6


def _stash_readme_text():
    body = """AttrViz test cube
=================

Select "Attr Cube", then:
  RMB → Visualize Attribute → pick one

RMB → Visualize Attribute → Domain → attribute:
  Point → height / wave / cluster   (Heat + Surface)
  Point → flow / stretch            (RGB / Arrows)
  Face  → face_id                   (Random + Surface)

Viewport: Material shading. Viz panel: Enabled / Domain / Type / Color.
"""
    text = bpy.data.texts.new("README_AttrViz")
    text.write(body)


def main():
    _clear()
    cube = _make_cube()
    _author_attributes(cube)
    _setup_view()
    _stash_readme_text()

    # Make the cube active/selected for a friendly first open
    bpy.ops.object.select_all(action='DESELECT')
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube

    # Prefer Material shading in stored screen (best-effort; UI screens
    # vary under --factory-startup).
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.type = 'MATERIAL'

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=OUT)
    print(f"[attrviz] wrote {OUT}")


if __name__ == "__main__":
    main()
