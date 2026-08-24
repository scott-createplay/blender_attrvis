"""Build examples/attrviz_docs.blend — the fixture the documentation is shot from.

Run:
    blender --background --factory-startup \
        --python examples/build_attr_docs_scene.py

Generated, never hand-saved. A hand-saved .blend rots into an opaque binary
that drifts from the addon; this script is the source of truth and prints the
assertions a scenario should make.

Designed to exercise the axes rather than to be pretty. Objects are spread
along X so a scenario can frame one and hide the collections it does not need.

  Suzanne_Measured   curv (float, Point) + grad (vector, Point)
                     the hero: Heat/Surface reads as data on real curvature,
                     and Arrows have somewhere interesting to point
  Torus_Flow         grad (vector, Point) — unambiguous normals for Arrows
  Grid_Plates        plate_id (int, Face) — Face domain and categorical colour
  Cylinder_Bare      nothing at all — proves partial coverage is honest.
                     Deliberately NOT a cube: a grey cube in a Blender
                     screenshot reads as "the default cube nobody deleted",
                     which is not the claim this object is making
  Instanced_Cloud    Instance domain only, mesh domains empty — the
                     "add Realize Instances" guidance, which has no test
                     and no doc today

Instanced_Cloud can share this scene because the menu reads
`context.active_object`: the empty-mesh-domains condition is per object, not
per scene.
"""
from __future__ import annotations

import os
import sys

import bmesh
import bpy

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import attrviz as av  # noqa: E402

OUT = os.path.join(REPO, "examples", "attrviz_docs.blend")


def clear():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for ng in list(bpy.data.node_groups):
        bpy.data.node_groups.remove(ng)


def mesh_obj(name, builder, location):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    builder(bm)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _tree(name):
    ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    ng.interface.new_socket("Geometry", in_out='INPUT',
                            socket_type='NodeSocketGeometry')
    ng.interface.new_socket("Geometry", in_out='OUTPUT',
                            socket_type='NodeSocketGeometry')
    gin = ng.nodes.new("NodeGroupInput")
    gin.location = (-700, 0)
    gout = ng.nodes.new("NodeGroupOutput")
    gout.location = (700, 0)
    return ng, gin, gout


def add_measure(obj, scalar=True):
    """Write grad (vector) and optionally curv (float) on Point.

    Both are modifier-generated, so neither exists on the original mesh — the
    case that defeats anything reading obj.data instead of evaluated geometry.
    """
    ng, gin, gout = _tree(f"Measure_{obj.name}")

    nrm = ng.nodes.new("GeometryNodeInputNormal")
    nrm.location = (-450, -200)
    st_v = ng.nodes.new("GeometryNodeStoreNamedAttribute")
    st_v.location = (-150, 0)
    st_v.data_type = 'FLOAT_VECTOR'
    st_v.domain = 'POINT'
    st_v.inputs["Name"].default_value = "grad"
    ng.links.new(gin.outputs[0], st_v.inputs["Geometry"])
    ng.links.new(nrm.outputs["Normal"], st_v.inputs["Value"])
    tail = st_v

    if scalar:
        # curv: distance from the object's own origin. On Suzanne that varies
        # over the whole form, so a Heat ramp reads as data rather than as
        # shading — which a sphere could never show.
        pos = ng.nodes.new("GeometryNodeInputPosition")
        pos.location = (-450, -420)
        length = ng.nodes.new("ShaderNodeVectorMath")
        length.location = (-250, -420)
        length.operation = 'LENGTH'
        st_f = ng.nodes.new("GeometryNodeStoreNamedAttribute")
        st_f.location = (200, 0)
        st_f.data_type = 'FLOAT'
        st_f.domain = 'POINT'
        st_f.inputs["Name"].default_value = "curv"
        ng.links.new(pos.outputs["Position"], length.inputs[0])
        ng.links.new(st_v.outputs["Geometry"], st_f.inputs["Geometry"])
        ng.links.new(length.outputs["Value"], st_f.inputs["Value"])
        tail = st_f

    ng.links.new(tail.outputs["Geometry"], gout.inputs[0])
    md = obj.modifiers.new("Measure", 'NODES')
    md.node_group = ng
    return md


def add_face_ids(obj, name="plate_id"):
    """An INT on the FACE domain — categorical, so the overlay colours it by
    hash rather than through a ramp.

    Suzanne gets one too, so the docs can show Point and Face on the SAME
    object: a face attribute is flat per facet, a point attribute is smooth.
    Two objects side by side would not prove that.
    """
    ng, gin, gout = _tree(f"Faces_{name}_{obj.name}")
    idx = ng.nodes.new("GeometryNodeInputIndex")
    idx.location = (-450, -220)
    st = ng.nodes.new("GeometryNodeStoreNamedAttribute")
    st.location = (0, 0)
    st.data_type = 'INT'
    st.domain = 'FACE'
    st.inputs["Name"].default_value = name
    ng.links.new(gin.outputs[0], st.inputs["Geometry"])
    ng.links.new(idx.outputs["Index"], st.inputs["Value"])
    ng.links.new(st.outputs["Geometry"], gout.inputs[0])
    md = obj.modifiers.new(f"Faces_{name}", 'NODES')
    md.node_group = ng
    return md


def add_wear(obj, boost=1.0):
    """`wear`: a FLOAT on Point, scaled per object.

    The batch exists for one claim — one visualizer over many objects puts them
    all on a SHARED ramp, so the odd one out is visible without clicking
    through them. That only reads if one object's values genuinely sit outside
    the others'.
    """
    ng, gin, gout = _tree(f"Wear_{obj.name}")
    pos = ng.nodes.new("GeometryNodeInputPosition")
    pos.location = (-450, -300)
    sep = ng.nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-280, -300)
    add = ng.nodes.new("ShaderNodeMath")
    add.location = (-120, -300)
    add.operation = 'ADD'
    add.inputs[1].default_value = 0.42
    mul = ng.nodes.new("ShaderNodeMath")
    mul.location = (30, -300)
    mul.operation = 'MULTIPLY'
    mul.inputs[1].default_value = float(boost)
    st = ng.nodes.new("GeometryNodeStoreNamedAttribute")
    st.location = (220, 0)
    st.data_type = 'FLOAT'
    st.domain = 'POINT'
    st.inputs["Name"].default_value = "wear"
    ng.links.new(gin.outputs[0], st.inputs["Geometry"])
    ng.links.new(pos.outputs["Position"], sep.inputs["Vector"])
    ng.links.new(sep.outputs["Z"], add.inputs[0])
    ng.links.new(add.outputs["Value"], mul.inputs[0])
    ng.links.new(mul.outputs["Value"], st.inputs["Value"])
    ng.links.new(st.outputs["Geometry"], gout.inputs[0])
    md = obj.modifiers.new("Wear", 'NODES')
    md.node_group = ng
    return md


def add_instancer(obj):
    """Output ONLY instances, so the mesh domains are genuinely empty.

    This is the un-realized instances case: Point/Edge/Face/Corner have no
    elements and the menu says so, rather than offering four missing domains.
    """
    ng, gin, gout = _tree(f"Instancer_{obj.name}")
    cube = ng.nodes.new("GeometryNodeMeshCube")
    cube.location = (-450, -260)
    cube.inputs["Size"].default_value = (0.18, 0.18, 0.18)
    iop = ng.nodes.new("GeometryNodeInstanceOnPoints")
    iop.location = (0, 0)
    ng.links.new(gin.outputs[0], iop.inputs["Points"])
    ng.links.new(cube.outputs["Mesh"], iop.inputs["Instance"])
    ng.links.new(iop.outputs["Instances"], gout.inputs[0])
    md = obj.modifiers.new("Instancer", 'NODES')
    md.node_group = ng
    return md


def torus(bm, major=0.85, minor=0.3, major_seg=28, minor_seg=14):
    """bmesh.ops has no create_torus, and the old fixture's 'Torus_Measured'
    was in fact a cone. Build a real one by spinning a circle."""
    bmesh.ops.create_circle(bm, cap_ends=False, segments=minor_seg,
                            radius=minor)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(major, 0.0, 0.0))
    bmesh.ops.rotate(bm, verts=bm.verts,
                     cent=(major, 0.0, 0.0),
                     matrix=__import__("mathutils").Matrix.Rotation(
                         1.5707963, 3, 'Y'))
    bmesh.ops.spin(bm, geom=bm.verts[:] + bm.edges[:],
                   cent=(0, 0, 0), axis=(0, 0, 1), dvec=(0, 0, 0),
                   angle=6.2831853, steps=major_seg, use_merge=True)


def main():
    clear()
    av.register()
    bpy.context.scene.attrviz_gpu_markers = True

    suzanne = mesh_obj("Suzanne_Measured",
                       lambda bm: bmesh.ops.create_monkey(bm),
                       (0.0, 0.0, 0.0))
    torus_obj = mesh_obj("Torus_Flow", torus, (3.4, 0.0, 0.0))
    grid = mesh_obj("Grid_Plates",
                    lambda bm: bmesh.ops.create_grid(
                        bm, x_segments=6, y_segments=6, size=1.1),
                    (-3.4, 0.0, 0.0))
    bare = mesh_obj("Cylinder_Bare",
                    lambda bm: bmesh.ops.create_cone(
                        bm, cap_ends=True, cap_tris=False, segments=24,
                        radius1=0.62, radius2=0.62, depth=1.5),
                    (0.0, 3.2, 0.0))
    cloud = mesh_obj("Instanced_Cloud",
                     lambda bm: bmesh.ops.create_icosphere(
                         bm, subdivisions=1, radius=0.9),
                     (3.4, 3.2, 0.0))

    # Suzanne carries BOTH a Point and a Face attribute, so one object can
    # demonstrate what changing domain does.
    add_measure(suzanne, scalar=True)
    add_face_ids(suzanne, name="face_id")

    # The batch: six tiles on one shelf. Four ordinary, one worn well past the
    # rest, one that never got the attribute at all.
    batch = []
    for i in range(6):
        obj = mesh_obj(f"Batch_{i + 1:02d}",
                       lambda bm: bmesh.ops.create_icosphere(
                           bm, subdivisions=2, radius=0.42),
                       (-3.9 + i * 1.35, -3.6, 0.0))
        batch.append(obj)
    for i, obj in enumerate(batch):
        if i == 5:
            continue          # Batch_06 carries nothing: the coverage story.
        add_wear(obj, boost=2.4 if i == 3 else 1.0)
    add_measure(torus_obj, scalar=False)
    add_face_ids(grid)
    add_instancer(cloud)
    # Cylinder_Bare deliberately gets no modifier and no attributes.
    bpy.context.view_layer.update()

    # --- scope 1: the default bucket, deliberately mixed coverage ----------
    watch = av.active_scope(bpy.context, create=True)
    # Link the NON-carrier first: before the 014 fix, meshes[0] decided the
    # dtype and the panel reported none.
    av._link_to_watch(bpy.context, [bare, suzanne, torus_obj], watch)
    viz_arrows = av.add_visualizer(
        bpy.context, scope=watch, attribute="grad", domain="Point",
        style="RGB", display="Arrows")
    viz_arrows.name = "VIZ_grad_arrows"

    # --- scope 2: the hero — same object, a second appearance --------------
    curv_coll = av.new_scope_collection(bpy.context, "attrvis_curvature")
    av._link_to_watch(bpy.context, [suzanne], curv_coll)
    viz_surface = av.add_visualizer(
        bpy.context, scope=curv_coll, attribute="curv", domain="Point",
        style="Heat", display="Surface")
    viz_surface.name = "VIZ_curv_surface"

    # --- scope 3: a different domain and a categorical colour -------------
    plate_coll = av.new_scope_collection(bpy.context, "attrvis_plates")
    av._link_to_watch(bpy.context, [grid], plate_coll)
    viz_plates = av.add_visualizer(
        bpy.context, scope=plate_coll, attribute="plate_id", domain="Face",
        style="Random", display="Surface")
    viz_plates.name = "VIZ_plate_random"

    # --- scope 4: the batch, one visualizer over all of them --------------
    batch_coll = av.new_scope_collection(bpy.context, "attrvis_batch")
    av._link_to_watch(bpy.context, batch, batch_coll)
    viz_wear = av.add_visualizer(
        bpy.context, scope=batch_coll, attribute="wear", domain="Point",
        style="Heat", display="Surface")
    viz_wear.name = "VIZ_wear_batch"

    # A second visualizer on Suzanne's FACE attribute, for the domain shot.
    face_coll = av.new_scope_collection(bpy.context, "attrvis_faces")
    av._link_to_watch(bpy.context, [suzanne], face_coll)
    viz_face = av.add_visualizer(
        bpy.context, scope=face_coll, attribute="face_id", domain="Face",
        style="Random", display="Surface")
    viz_face.name = "VIZ_faceid_surface"

    av.set_active_scope(bpy.context, watch)
    bpy.context.view_layer.update()

    print()
    print("=" * 70)
    print("SCENE BUILT — what a scenario should assert")
    print("=" * 70)
    for obj in (suzanne, torus_obj, grid, bare, cloud) + tuple(batch[:1]):
        by, _ = av.attributes_by_domain(obj)
        populated = {d: [n for n, _t in v] for d, v in by.items() if v}
        print(f"  {obj.name:18s} {populated or 'no attributes'}")
    print()
    groups = av.visualizers_by_scope(bpy.context.scene)
    items = groups.items() if hasattr(groups, "items") else groups
    for coll, vizzes in items:
        name = getattr(coll, "name", str(coll))
        n = len(av.gpu_sample.iter_watch_meshes(None, coll)) \
            if coll is not None else 0
        print(f"  {name:20s} {n} obj / {len(vizzes)} viz")
    print()
    print("  Suzanne is in TWO scopes: grad Arrows and curv Surface at once.")
    print("  Cylinder_Bare carries neither and is FIRST in attrvis.")
    print("  Instanced_Cloud is in NO scope — it exists for the menu shot.")
    print("=" * 70)

    bpy.ops.wm.save_as_mainfile(filepath=OUT)
    print(f"saved {OUT}")


main()
