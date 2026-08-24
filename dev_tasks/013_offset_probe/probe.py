"""Locate an overlay/geometry mismatch on a real object.

Run inside YOUR scene (not --factory-startup), with the object selected:

    blender yourfile.blend --python dev_tasks/013_offset_probe/probe.py

Or paste into Blender's Text Editor and Run Script. Reports, for every
selected object and every visualizer watching it, which representation each
stage read and where it sits in world space. A mismatch between any two rows
localises the problem.

Reads only. Changes nothing.
"""
import os
import sys

import bpy
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import attrviz as av
from attrviz import gpu_sample, gpu_overlay, node_builder


def bounds(a):
    if a is None or len(a) == 0:
        return "empty"
    a = np.asarray(a, dtype=np.float64).reshape(-1, 3)
    lo, hi = a.min(0), a.max(0)
    return (f"n={len(a):<7} min=({lo[0]:8.3f},{lo[1]:8.3f},{lo[2]:8.3f}) "
            f"max=({hi[0]:8.3f},{hi[1]:8.3f},{hi[2]:8.3f})")


def verts_world(mesh_like, mw):
    if mesh_like is None or not hasattr(mesh_like, "vertices"):
        return None
    n = len(mesh_like.vertices)
    if n == 0:
        return None
    co = np.empty(n * 3, dtype=np.float64)
    mesh_like.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    return (np.c_[co, np.ones(len(co))] @ np.asarray(mw).reshape(4, 4).T)[:, :3]


def points_world(pc, mw):
    if pc is None or not hasattr(pc, "points"):
        return None
    n = len(pc.points)
    if n == 0:
        return None
    co = np.empty(n * 3, dtype=np.float64)
    pc.points.foreach_get("position", co)
    co = co.reshape(-1, 3)
    return (np.c_[co, np.ones(len(co))] @ np.asarray(mw).reshape(4, 4).T)[:, :3]


def probe_object(obj):
    print("=" * 78)
    print(f"OBJECT  {obj.name}   type={obj.type}")
    print("=" * 78)
    print("  modifier stack:")
    for m in obj.modifiers:
        extra = ""
        if m.type == 'NODES' and m.node_group is not None:
            tag = m.node_group.get("attrviz_version")
            extra = f"  node_group={m.node_group.name!r}" + (
                "  [ATTRVIZ]" if tag else "")
        print(f"    - {m.name:<22} {m.type:<12} viewport={m.show_viewport}{extra}")
    if not obj.modifiers:
        print("    (none)")

    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    mw = ev.matrix_world
    gs = None
    try:
        gs = ev.evaluated_geometry()
    except Exception as exc:
        print(f"  evaluated_geometry() raised: {exc}")

    print()
    print("  --- what each representation holds, in WORLD space ---")
    print(f"  original obj.data          {bounds(verts_world(obj.data, obj.matrix_world))}")
    print(f"  evaluated ev.data          {bounds(verts_world(getattr(ev, 'data', None), mw))}")
    if gs is not None:
        print(f"  geometry set .mesh         {bounds(verts_world(getattr(gs, 'mesh', None), mw))}")
        print(f"  geometry set .pointcloud   {bounds(points_world(getattr(gs, 'pointcloud', None), mw))}")
        try:
            inst = gpu_sample.instances_cloud(gs)
            print(f"  geometry set instances     {bounds(points_world(inst, mw))}")
        except Exception as exc:
            print(f"  geometry set instances     unavailable ({exc})")

    # Which one does the sampler actually pick?
    try:
        _ev, me, pc, _gs = gpu_sample._evaluated_source(obj)
        picked = ("ev.data / gs.mesh (MESH)" if me is not None
                  else "pointcloud" if pc is not None else "NOTHING")
        print(f"  _evaluated_source picked   {picked}")
    except Exception as exc:
        print(f"  _evaluated_source raised   {exc}")

    print()
    print("  --- visualizers watching this object ---")
    scene = bpy.context.scene
    found = False
    for viz in av.visualizers(scene):
        md = av.viz_modifier(viz)
        if md is None:
            continue
        try:
            targets = gpu_sample.watch_meshes_for_visualizer(md)
        except Exception:
            continue
        if obj not in targets:
            continue
        found = True
        try:
            attr = node_builder.get_input(md, "Attribute")
            domain = node_builder.menu_input_name(md, "Domain")
            display = node_builder.menu_input_name(md, "Display")
            density = node_builder.get_input(md, "Density")
        except Exception:
            attr = domain = display = density = "?"
        scope = av.viz_scope(md)
        enabled = viz.attrviz_enabled and gpu_overlay.scope_enabled(scope)
        print(f"    {attr} . {domain} . {display}   density={density}  "
              f"scope={scope.name if scope else None}  enabled={enabled}")
        try:
            r = gpu_sample.sample_visualizer_targets(md, cap=50000)
        except Exception as exc:
            print(f"        sample raised: {exc}")
            continue
        if r is None:
            print("        sample: None (nothing drawn)")
            continue
        pos, val, dtype = r
        print(f"        sampled positions  {bounds(pos)}")
        print(f"        value dtype={dtype} shape={getattr(val, 'shape', None)}")
        # Do the sampled points lie ON the evaluated mesh?
        ref = verts_world(getattr(ev, "data", None), mw)
        if ref is None and gs is not None:
            ref = verts_world(getattr(gs, "mesh", None), mw)
        if ref is not None and len(pos):
            p = np.asarray(pos, dtype=np.float64).reshape(-1, 3)
            step = max(1, len(p) // 500)          # cap the O(n*m) probe
            d = np.min(np.linalg.norm(ref[None, :, :] - p[::step, None, :],
                                      axis=2), axis=1)
            print(f"        max distance to nearest evaluated vert: {d.max():.6f}"
                  f"   {'ON the surface' if d.max() < 1e-4 else '<-- OFFSET'}")
    if not found:
        print("    (none)")
    print()


if __name__ == "__main__":
    sel = [o for o in bpy.context.selected_objects
           if o.type in gpu_sample.WATCH_TYPES]
    if not sel:
        act = bpy.context.active_object
        sel = [act] if act is not None else []
    if not sel:
        print("Select the object to probe, then run again.")
    else:
        print()
        for o in sel:
            probe_object(o)
        print("Read the '--- what each representation holds ---' block first: if")
        print("ev.data and the geometry set disagree, that is the mismatch. If")
        print("they agree and the sampled positions sit ON the surface, the")
        print("overlay is placed correctly and the offset is in presentation.")
