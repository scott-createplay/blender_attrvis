"""Build a GPU-overlay probe fixture mesh with authored attributes.

Attrs:
  heat     FLOAT        POINT  — blue→red heat field (Phase 2)
  face_id  INT          FACE   — categorical hash (Phase 3)
  flow     FLOAT_VECTOR POINT  — vector stub (Phase 3+)

Run:
  blender --background --factory-startup --python-exit-code 1 \\
      --python dev_tasks/001_gpu_overlay/probe/build_fixture.py

Writes: dev_tasks/001_gpu_overlay/probe/probe_fixture.blend
"""
from __future__ import annotations

import array
import math
import os

import bmesh
import bpy

PROBE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(PROBE_DIR, "probe_fixture.blend")


def _clear():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                  bpy.data.cameras, bpy.data.collections):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def _make_grid(name="Probe Grid", segments=16, size=2.0):
    """Regular grid so headless tests can assert exact lengths."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(
        bm,
        x_segments=segments,
        y_segments=segments,
        size=size,
    )
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _foreach_set_float(attr, values):
    arr = array.array('f', (float(v) for v in values))
    attr.data.foreach_set("value", arr)


def _foreach_set_vector(attr, values):
    flat = []
    for v in values:
        flat.extend(float(c) for c in v)
    arr = array.array('f', flat)
    attr.data.foreach_set("vector", arr)


def author_attributes(obj):
    """Author heat / face_id / flow on obj.data. Reusable from tests."""
    me = obj.data
    n = len(me.vertices)
    positions = [v.co.copy() for v in me.vertices]

    heat = []
    flow = []
    for co in positions:
        x, y, z = co
        # 0..1 heat: distance from -corner → +corner, plus a soft ridge
        t = 0.5 * ((x / 2.0) + 0.5) + 0.5 * ((y / 2.0) + 0.5)
        ridge = 0.15 * math.sin(x * math.pi * 2.0) * math.sin(y * math.pi)
        heat.append(max(0.0, min(1.0, t + ridge)))
        # planar swirl around Z
        flow.append((-y * 0.5, x * 0.5, 0.1 * math.sin(x + y)))

    for name in ("heat", "flow", "face_id"):
        if name in me.attributes:
            me.attributes.remove(me.attributes[name])

    heat_attr = me.attributes.new("heat", 'FLOAT', 'POINT')
    _foreach_set_float(heat_attr, heat)

    flow_attr = me.attributes.new("flow", 'FLOAT_VECTOR', 'POINT')
    _foreach_set_vector(flow_attr, flow)

    face_attr = me.attributes.new("face_id", 'INT', 'FACE')
    for i, d in enumerate(face_attr.data):
        d.value = i

    print(
        f"[probe] authored heat/flow on {n} verts, "
        f"face_id on {len(me.polygons)} faces"
    )
    return {
        "n_verts": n,
        "n_faces": len(me.polygons),
        "heat_min": min(heat) if heat else 0.0,
        "heat_max": max(heat) if heat else 0.0,
    }


def _setup_view():
    sun_data = bpy.data.lights.new("Key Sun", 'SUN')
    sun_data.energy = 2.0
    sun = bpy.data.objects.new("Key Sun", sun_data)
    sun.rotation_euler = (math.radians(50), math.radians(-15),
                          math.radians(30))
    bpy.context.scene.collection.objects.link(sun)

    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    cam.location = (3.8, -4.2, 3.0)
    cam.rotation_euler = (math.radians(58), 0.0, math.radians(43))
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    nt = world.node_tree
    if nt is not None:
        bg = next((n for n in nt.nodes if n.type == 'BACKGROUND'), None)
        if bg is not None:
            bg.inputs[0].default_value = (0.04, 0.045, 0.05, 1.0)
            bg.inputs[1].default_value = 0.5


def _stash_readme():
    body = """GPU overlay probe fixture
=========================

Select "Probe Grid", then enable the probe addon (see probe/README.md).

Attrs:
  Point → heat   (float)   — Phase 2 heat points
  Point → flow   (vector)  — Phase 3+ arrows stub
  Face  → face_id (int)    — Phase 3 hash regions

Viewport: Solid shading. No materials required.
"""
    text = bpy.data.texts.new("README_Probe")
    text.write(body)


def build(segments=16, size=2.0, out_path=None):
    """Build fixture in the current blend. Returns the grid object."""
    _clear()
    grid = _make_grid(segments=segments, size=size)
    author_attributes(grid)
    _setup_view()
    _stash_readme()

    grid.hide_render = True

    bpy.ops.object.select_all(action='DESELECT')
    grid.select_set(True)
    bpy.context.view_layer.objects.active = grid

    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.type = 'SOLID'
                    space.shading.light = 'FLAT'

    path = out_path or OUT
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=path)
        print(f"[probe] wrote {path}")
    return grid


def main():
    build()


if __name__ == "__main__":
    # Allow `blender --python build_fixture.py` without package import.
    main()
