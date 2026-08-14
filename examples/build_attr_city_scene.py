"""Procedural city-block stress scene for AttrViz.

Mirrors sample_scene_3 *structure* (many objects, nested collections, mixed
attrs) without the 548MB asset. Use this to find overlay/Tags/Scope cliffs;
use sample_scene_3 itself when you need the real 1.1k-mesh / 1.5M-vert load.

Layout:
  City/
    Street/          ground
    Buildings/       hulls (height, dirt, entity_id, entity_class, emission)
    Signs/           thin plates (emission, sign_text STRING, dist_sign_hue)
    Props/           AC units, pipes, lights (entity_id, dirt)

Defaults (~sample_scene_3 object count):
  12×8 lots ≈ 1.1k meshes, mixed 1–28 floor skyline.

Run:
  blender --background --factory-startup --python-exit-code 1 \\
      --python examples/build_attr_city_scene.py

  blender --background --factory-startup --python-exit-code 1 \\
      --python examples/build_attr_city_scene.py -- \\
      --blocks-x 6 --blocks-y 4

  blender --background --factory-startup --python-exit-code 1 \\
      --python examples/build_attr_city_scene.py -- --dense --viz

Writes: examples/attrviz_city.blend
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Vector

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "examples", "attrviz_city.blend")

SIGN_NAMES = (
    "SUSHI", "GARAGE", "FLAT", "SHOP", "NEON", "BAR", "HOTEL", "CAFE",
)


def _argv_after_dd():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return []


def _parse():
    p = argparse.ArgumentParser(description="AttrViz city-block stress scene")
    p.add_argument("--blocks-x", type=int, default=12,
                   help="Lots in X (default 12 → ~sample_scene_3 mesh count)")
    p.add_argument("--blocks-y", type=int, default=8,
                   help="Lots in Y (default 8)")
    p.add_argument("--seed", type=int, default=3)
    p.add_argument("--dense", action="store_true",
                   help="Heavier hull subdivision (~1M verts, closer to 1.5M)")
    p.add_argument("--viz", action="store_true",
                   help="Pre-create AttrViz visualizers (Surface/Tags/Markers)")
    return p.parse_args(_argv_after_dd())


def _clear():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                  bpy.data.cameras, bpy.data.collections, bpy.data.worlds):
        for item in list(block):
            if item.users == 0:
                try:
                    block.remove(item)
                except Exception:
                    pass


def _coll(name, parent=None):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
    root = parent or bpy.context.scene.collection
    if c.name not in root.children:
        root.children.link(c)
    return c


def _link(obj, coll):
    if obj.name not in coll.objects:
        coll.objects.link(obj)
    sc = bpy.context.scene.collection
    if obj.name in sc.objects and coll != sc:
        sc.objects.unlink(obj)


def _box(name, size, loc, cuts=0, rot=None):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    sx, sy, sz = size
    bmesh.ops.scale(bm, vec=Vector((sx, sy, sz)), verts=bm.verts)
    if cuts > 0:
        bmesh.ops.subdivide_edges(
            bm, edges=bm.edges[:], cuts=int(cuts), use_grid_fill=True,
        )
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = loc
    if rot is not None:
        obj.rotation_euler = rot
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _foreach_f(attr, values, field="value", width=1):
    import array
    flat = []
    for v in values:
        if width == 1:
            flat.append(float(v))
        else:
            flat.extend(float(c) for c in v)
    arr = array.array("f", flat)
    attr.data.foreach_set(field, arr)


def _set_int(attr, values):
    for i, d in enumerate(attr.data):
        d.value = int(values[i])


def _set_str(attr, values):
    for i, d in enumerate(attr.data):
        s = str(values[i])
        try:
            d.value = s
        except TypeError:
            d.value = s.encode("utf-8")


def _ensure_attr(me, name, dtype, domain):
    if name in me.attributes:
        me.attributes.remove(me.attributes[name])
    return me.attributes.new(name, dtype, domain)


def _lot_massing(rng, dense):
    """Skyline mix: low shops, mid blocks, skinny towers."""
    roll = rng.random()
    if roll < 0.12:
        floors = rng.randint(16, 28)
        w = 2.0 + rng.uniform(0.0, 0.8)
        d = 2.0 + rng.uniform(0.0, 0.8)
        cuts = 56 if dense else 22
        klass = 1  # tower / flat
    elif roll < 0.42:
        floors = rng.randint(6, 13)
        w = 3.0 + rng.uniform(0.0, 1.6)
        d = 3.4 + rng.uniform(0.0, 2.2)
        cuts = 40 if dense else 14
        klass = 0  # shop/office
    else:
        floors = rng.randint(1, 4)
        w = 4.2 + rng.uniform(0.0, 2.4)
        d = 5.0 + rng.uniform(0.0, 2.8)
        cuts = 28 if dense else 10
        klass = 2 if floors <= 2 else 0  # garage / shop
    h = 1.15 * floors + rng.uniform(0.0, 0.4)
    return floors, h, w, d, cuts, klass


def _author_building(obj, entity_id, entity_class, rng):
    me = obj.data
    n = len(me.vertices)
    pos = [v.co.copy() for v in me.vertices]
    height = [p.z for p in pos]
    dirt = []
    emission = []
    flow = []
    for p in pos:
        dirt.append(max(0.0, 0.15 + 0.08 * (p.z < 0.4) + 0.04 * rng.random()))
        # windows-ish: higher emission on a lattice
        on = (int(p.x * 4) + int(p.z * 3)) % 3 == 0 and p.z > 0.3
        emission.append(2.4 * rng.random() if on else 0.02 * rng.random())
        flow.append((-p.y * 0.2, p.x * 0.2, 0.05))
    _foreach_f(_ensure_attr(me, "height", "FLOAT", "POINT"), height)
    _foreach_f(_ensure_attr(me, "dirt_amount", "FLOAT", "POINT"), dirt)
    _foreach_f(_ensure_attr(me, "emission_strength", "FLOAT", "POINT"), emission)
    _foreach_f(_ensure_attr(me, "flow", "FLOAT_VECTOR", "POINT"), flow,
               field="vector", width=3)
    nf = len(me.polygons)
    _set_int(_ensure_attr(me, "entity_id", "INT", "FACE"), [entity_id] * nf)
    _set_int(_ensure_attr(me, "entity_class", "INT", "FACE"),
             [entity_class] * nf)
    _set_int(_ensure_attr(me, "face_id", "INT", "FACE"), list(range(nf)))


def _author_sign(obj, entity_id, text, hue, rng):
    me = obj.data
    n = len(me.vertices)
    emission = [0.8 + 1.6 * rng.random() for _ in range(n)]
    hue_v = [hue + 0.04 * (rng.random() - 0.5) for _ in range(n)]
    _foreach_f(_ensure_attr(me, "emission_strength", "FLOAT", "POINT"), emission)
    _foreach_f(_ensure_attr(me, "dist_sign_hue", "FLOAT", "POINT"), hue_v)
    _set_str(_ensure_attr(me, "sign_text", "STRING", "POINT"), [text] * n)
    _set_int(_ensure_attr(me, "character_id", "INT", "POINT"),
             [hash(text) % 97 for _ in range(n)])
    nf = len(me.polygons)
    _set_int(_ensure_attr(me, "entity_id", "INT", "FACE"), [entity_id] * nf)


def _author_prop(obj, entity_id, rng):
    me = obj.data
    n = len(me.vertices)
    dirt = [0.2 + 0.5 * rng.random() for _ in range(n)]
    _foreach_f(_ensure_attr(me, "dirt_amount", "FLOAT", "POINT"), dirt)
    nf = len(me.polygons)
    _set_int(_ensure_attr(me, "entity_id", "INT", "FACE"), [entity_id] * nf)


def _setup_view(span_x, span_y):
    sun_data = bpy.data.lights.new("Key Sun", "SUN")
    sun_data.energy = 2.5
    sun = bpy.data.objects.new("Key Sun", sun_data)
    sun.rotation_euler = (math.radians(50), math.radians(-15),
                          math.radians(30))
    bpy.context.scene.collection.objects.link(sun)

    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    cam.location = (span_x * 0.12, -span_y * 0.95, max(span_y * 0.55, 36.0))
    cam.rotation_euler = (math.radians(62), 0.0, math.radians(18))
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


def _add_vizs(city, buildings, signs):
    sys.path.insert(0, REPO)
    import attrviz as av
    av.register()
    bpy.context.scene.attrviz_gpu_markers = True
    ctx = bpy.context
    # Surface on all building hulls via Scope
    av.add_visualizer(
        ctx, target=None, scope=buildings,
        attribute="dirt_amount", domain="Point",
        style="Heat", display="Surface", name="Viz · Buildings · dirt",
    )
    # Tags on signs (STRING + emission)
    viz_tags = av.add_visualizer(
        ctx, target=None, scope=signs,
        attribute="sign_text", domain="Point",
        style="Heat", display="Tags", name="Viz · Signs · text",
    )
    md = av.viz_modifier(viz_tags)
    if md is not None:
        from attrviz import node_builder
        node_builder.set_input(md, "Tag Cap", 400)
        node_builder.set_input(md, "Tag Size", 12)
        node_builder.set_input(md, "Facing Cull", True)
    av.add_visualizer(
        ctx, target=None, scope=signs,
        attribute="emission_strength", domain="Point",
        style="Heat", display="Markers", name="Viz · Signs · emission",
    )
    av.add_visualizer(
        ctx, target=None, scope=city,
        attribute="entity_id", domain="Face",
        style="Random", display="Surface", name="Viz · City · entity_id",
    )
    print("[attrviz] pre-created 4 visualizers (disable extras in Viz panel)")


def main():
    args = _parse()
    rng = random.Random(args.seed)
    _clear()

    city = _coll("City")
    street_c = _coll("Street", city)
    buildings_c = _coll("Buildings", city)
    signs_c = _coll("Signs", city)
    props_c = _coll("Props", city)

    bx, by = max(1, args.blocks_x), max(1, args.blocks_y)
    lot_x, lot_y = 6.0, 8.0
    street_w = 4.0
    span_x = bx * lot_x + (bx - 1) * 1.5
    span_y = by * lot_y + street_w

    ground = _box("Street", (span_x + 8.0, span_y + 10.0, 0.15),
                  (span_x * 0.5 - 2.0, span_y * 0.35, -0.08), cuts=2)
    _author_prop(ground, entity_id=0, rng=rng)
    _link(ground, street_c)

    eid = 1
    n_build = n_sign = n_prop = 0
    verts = 0

    for iy in range(by):
        for ix in range(bx):
            cx = ix * (lot_x + 1.5)
            cy = iy * (lot_y + 0.4) + (street_w if iy >= by // 2 else 0.0)
            floors, h, w, d, cuts, klass = _lot_massing(rng, args.dense)
            hull = _box(
                f"Building_{ix}_{iy}",
                (w, d, h),
                (cx, cy, h * 0.5),
                cuts=cuts,
            )
            _author_building(hull, eid, klass, rng)
            _link(hull, buildings_c)
            verts += len(hull.data.vertices)
            n_build += 1
            bid = eid
            eid += 1

            # window plates (separate objects — sample_scene_3 style)
            n_win = 4 if floors < 8 else (6 if floors < 16 else 8)
            for w_i in range(n_win):
                wx = cx + ((w_i % 2) - 0.5) * (w * 0.45)
                t = w_i / max(1, n_win - 1)
                wz = 0.7 + t * max(0.6, h - 1.4)
                win = _box(
                    f"Window_{ix}_{iy}_{w_i}",
                    (0.7, 0.06, 0.9),
                    (wx, cy - d * 0.5 - 0.04, min(wz, h - 0.35)),
                    cuts=1,
                )
                _author_sign(win, eid, "WIN", 0.55, rng)
                _link(win, buildings_c)
                verts += len(win.data.vertices)
                eid += 1

            # two signs on the street facade ( -Y ), mid-ground floor
            for s in range(2):
                label = SIGN_NAMES[(bid + s) % len(SIGN_NAMES)]
                sx = cx + (s - 0.5) * (w * 0.35)
                sign = _box(
                    f"Sign_{ix}_{iy}_{s}",
                    (1.4, 0.08, 0.7),
                    (sx, cy - d * 0.5 - 0.06, min(1.6 + 0.4 * s, h * 0.35)),
                    cuts=1,
                )
                hue = ((bid * 17 + s * 9) % 100) / 100.0
                _author_sign(sign, eid, label, hue, rng)
                _link(sign, signs_c)
                verts += len(sign.data.vertices)
                n_sign += 1
                eid += 1

            # AC units + a pipe
            n_ac = 1 if floors <= 2 else (2 + (bid % 3))
            for p in range(n_ac):
                ac = _box(
                    f"AC_{ix}_{iy}_{p}",
                    (0.45, 0.35, 0.3),
                    (cx + w * 0.4, cy + d * 0.35,
                     min(h - 0.4, 1.0 + 0.9 * p)),
                    cuts=0,
                )
                _author_prop(ac, eid, rng)
                _link(ac, props_c)
                n_prop += 1
                eid += 1
            pipe = _box(
                f"Pipe_{ix}_{iy}",
                (0.12, 0.12, h * 0.85),
                (cx - w * 0.45, cy + d * 0.4, h * 0.4),
                cuts=2,
            )
            _author_prop(pipe, eid, rng)
            _link(pipe, props_c)
            n_prop += 1
            eid += 1

            # streetlight on the curb
            light = _box(
                f"Light_{ix}_{iy}",
                (0.12, 0.12, 3.2),
                (cx, cy - d * 0.5 - 1.2, 1.6),
                cuts=0,
            )
            _author_prop(light, eid, rng)
            _link(light, props_c)
            n_prop += 1
            eid += 1

    _setup_view(span_x, span_y)

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    n_verts = sum(len(o.data.vertices) for o in meshes)
    print(f"[attrviz] city: blocks={bx}x{by}  dense={args.dense}  "
          f"buildings={n_build} signs={n_sign} props={n_prop}  "
          f"meshes={len(meshes)} verts={n_verts} entity_ids={eid - 1}")

    if args.viz:
        _add_vizs(city, buildings_c, signs_c)

    bpy.ops.object.select_all(action="DESELECT")
    if n_build:
        hull = bpy.data.objects.get("Building_0_0")
        if hull is not None:
            hull.select_set(True)
            bpy.context.view_layer.objects.active = hull

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=OUT)
    print(f"[attrviz] wrote {OUT}")
    print("  sample_scene_3 (real city, 548MB) still at:")
    print("  hdr_synthetic_scene_pipeline/.../sample_scene_3_look_seed__aov_test.blend")


if __name__ == "__main__":
    main()
