"""Build examples/attrviz_scope.blend — per-visualizer Scope, honestly reported.

    blender --background --factory-startup \
      --python examples/build_attr_scope_scene.py

Demonstrates, in one scene, what 010/011/014 changed:

  * a scope whose objects do NOT all carry the attribute (014). The object
    that lacks it is deliberately linked FIRST, which is the exact condition
    that used to make the panel say "Non-vector -> no arrows" while arrows
    were on screen.
  * that object stays VISIBLE rather than being muted to BOUNDS with nothing
    drawn in its place (010).
  * two collections, two visualizers, different attributes and displays (011),
    with one object deliberately in BOTH to show membership is additive (D4).

Open it and read the Viz panel: every number should match what you see.
"""
import os
import sys

import bpy
import bmesh

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import attrviz as av
from attrviz import gpu_sample, gpu_overlay

OUT = os.path.join(REPO, "examples", "attrviz_scope.blend")


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


def add_measure(obj):
    """A stand-in for a Measure node group: writes a Point vector AND scalar.

    Both are modifier-generated, so neither exists on the original mesh --
    the case that defeats a probe reading obj.data instead of the evaluated
    geometry.
    """
    ng = bpy.data.node_groups.new(f"Measure_{obj.name}", 'GeometryNodeTree')
    ng.interface.new_socket("Geometry", in_out='INPUT',
                            socket_type='NodeSocketGeometry')
    ng.interface.new_socket("Geometry", in_out='OUTPUT',
                            socket_type='NodeSocketGeometry')
    gin = ng.nodes.new("NodeGroupInput")
    gin.location = (-600, 0)
    gout = ng.nodes.new("NodeGroupOutput")
    gout.location = (600, 0)

    # grad : FLOAT_VECTOR  (the surface normal)
    nrm = ng.nodes.new("GeometryNodeInputNormal")
    nrm.location = (-400, -200)
    st_v = ng.nodes.new("GeometryNodeStoreNamedAttribute")
    st_v.location = (-100, 0)
    st_v.data_type = 'FLOAT_VECTOR'
    st_v.domain = 'POINT'
    st_v.inputs["Name"].default_value = "grad"

    # curv : FLOAT  (height, as a cheap scalar field)
    pos = ng.nodes.new("GeometryNodeInputPosition")
    pos.location = (-400, -400)
    sep = ng.nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-250, -400)
    st_f = ng.nodes.new("GeometryNodeStoreNamedAttribute")
    st_f.location = (250, 0)
    st_f.data_type = 'FLOAT'
    st_f.domain = 'POINT'
    st_f.inputs["Name"].default_value = "curv"

    ng.links.new(gin.outputs[0], st_v.inputs["Geometry"])
    ng.links.new(nrm.outputs["Normal"], st_v.inputs["Value"])
    ng.links.new(st_v.outputs["Geometry"], st_f.inputs["Geometry"])
    ng.links.new(pos.outputs["Position"], sep.inputs["Vector"])
    ng.links.new(sep.outputs["Z"], st_f.inputs["Value"])
    ng.links.new(st_f.outputs["Geometry"], gout.inputs[0])

    md = obj.modifiers.new("Measure", 'NODES')
    md.node_group = ng
    return md


def main():
    clear()
    av.register()
    bpy.context.scene.attrviz_gpu_markers = True

    # --- geometry ----------------------------------------------------------
    sphere = mesh_obj(
        "Sphere_Measured",
        lambda bm: bmesh.ops.create_uvsphere(
            bm, u_segments=24, v_segments=12, radius=1.0),
        (-2.6, 0.0, 0.0))
    plain = mesh_obj(
        "Cube_NoAttributes",
        lambda bm: bmesh.ops.create_cube(bm, size=1.6),
        (0.0, 0.0, 0.0))
    torus = mesh_obj(
        "Torus_Measured",
        lambda bm: bmesh.ops.create_cone(
            bm, cap_ends=True, cap_tris=False, segments=24,
            radius1=1.1, radius2=0.35, depth=1.4),
        (2.6, 0.0, 0.0))

    add_measure(sphere)
    add_measure(torus)
    # Cube_NoAttributes deliberately gets NO modifier and NO attributes.
    bpy.context.view_layer.update()

    # --- scope 1: attrvis, mixed coverage ----------------------------------
    watch = av.active_scope(bpy.context, create=True)
    # Link the NON-carrier first. This is the exact 014 condition: before the
    # fix, meshes[0] decided the dtype and the panel reported none.
    av._link_to_watch(bpy.context, [plain, sphere, torus], watch)

    viz_arrows = av.add_visualizer(
        bpy.context, scope=watch, attribute="grad", domain="Point",
        style="Heat", display="Arrows")
    viz_arrows.name = "VIZ_grad_arrows"

    # --- scope 2: a second collection, one object shared -------------------
    curv = av.new_scope_collection(bpy.context, "attrvis_curvature")
    # Additive (011 D4): torus stays in attrvis as well.
    av._link_to_watch(bpy.context, [torus], curv)

    viz_surface = av.add_visualizer(
        bpy.context, scope=curv, attribute="curv", domain="Point",
        style="Heat", display="Surface")
    viz_surface.name = "VIZ_curv_surface"

    av.set_active_scope(bpy.context, watch)
    bpy.context.view_layer.update()

    # --- report what the panel should say ----------------------------------
    print()
    print("=" * 70)
    print("SCENE BUILT — what the Viz panel should report")
    print("=" * 70)
    for viz, label in ((viz_arrows, "grad · Point · Arrows"),
                       (viz_surface, "curv · Point · Surface")):
        md = av.viz_modifier(viz)
        scope = av.viz_scope(md)
        n_obj, n_draw = gpu_overlay.viz_coverage(md)
        dtypes, domain = av._target_attr_meta(md)
        names = [o.name for o in gpu_sample.watch_meshes_for_visualizer(md)]
        print(f"\n  {label}")
        print(f"    scope     : {scope.name}")
        print(f"    objects   : {names}")
        print(f"    coverage  : {n_obj} objects · {n_draw} carry")
        print(f"    dtype(s)  : {dtypes}  on {domain}")
    print()
    print("  mute state (010 — nothing is hidden with nothing in its place):")
    for o in (sphere, plain, torus):
        print(f"    {o.name:<20} display_type={o.display_type}")
    print()
    print("  Cube_NoAttributes carries neither attribute, is FIRST in attrvis,")
    print("  and must stay visible while the other two draw.")

    bpy.ops.wm.save_as_mainfile(filepath=OUT)
    print(f"\nsaved -> {OUT}")


if __name__ == "__main__":
    main()
