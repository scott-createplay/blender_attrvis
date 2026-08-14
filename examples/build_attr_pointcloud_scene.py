"""GN-authored point-cloud demo scene for AttrViz task 006.

Several native POINTCLOUD objects; Geometry Nodes spawn the points and
store named attrs. AttrViz samples evaluated_geometry().pointcloud.

Clouds (2×3, ~count verts each):
  HeatGrid       grid → Mesh to Points     heat FLOAT (radial)
  ClusterIDs     ico → Mesh to Points      cluster_id INT + heat
  FlowSwirl      UV sphere → Points        flow VECTOR + heat
  Helix          spiral → Curve to Points  strand_id INT + heat
  VolumeScatter  volume distribute         density FLOAT + heat
  WavePlane      grid + sine Set Position  wave FLOAT + heat

All clouds also store ``heat`` so one Markers viz can color the whole set.
A small GN mesh cube sits in the mix (northstar: mesh + clouds in attrvis).

Run:
  blender --background --factory-startup --python-exit-code 1 \\
      --python examples/build_attr_pointcloud_scene.py

  blender --background --factory-startup --python-exit-code 1 \\
      --python examples/build_attr_pointcloud_scene.py -- --no-viz

Writes: examples/attrviz_pointclouds.blend
"""
from __future__ import annotations

import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "examples", "attrviz_pointclouds.blend")


def _argv_after_dd():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return []


def _parse():
    p = argparse.ArgumentParser(description="AttrViz GN point-cloud demo")
    p.add_argument("--count", type=int, default=40,
                   help="Grid / sphere resolution (default 40 → ~1.6k pts)")
    p.add_argument("--viz", dest="viz", action="store_true", default=True,
                   help="Pre-create AttrViz visualizers (default on)")
    p.add_argument("--no-viz", dest="viz", action="store_false")
    return p.parse_args(_argv_after_dd())


def _clear():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.pointclouds, bpy.data.materials,
                  bpy.data.lights, bpy.data.cameras, bpy.data.collections,
                  bpy.data.node_groups, bpy.data.worlds):
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


def _link_obj(obj, coll):
    if obj.name not in coll.objects:
        coll.objects.link(obj)
    sc = bpy.context.scene.collection
    if obj.name in sc.objects and coll != sc:
        sc.objects.unlink(obj)


def _n(tree, idname, x, y, **props):
    node = tree.nodes.new(idname)
    node.location = (x, y)
    for key, value in props.items():
        setattr(node, key, value)
    return node


def _ln(tree, a, b):
    tree.links.new(a, b)


def _sock_id(node, identifier):
    for s in list(node.inputs) + list(node.outputs):
        if s.identifier == identifier:
            return s
    raise KeyError(identifier)


def _rand_int(tree, x, y, lo, hi, id_out, seed=0):
    rnd = _n(tree, "FunctionNodeRandomValue", x, y, data_type="INT")
    _sock_id(rnd, "Min_002").default_value = int(lo)
    _sock_id(rnd, "Max_002").default_value = int(hi)
    _ln(tree, id_out, rnd.inputs["ID"])
    rnd.inputs["Seed"].default_value = int(seed)
    return _sock_id(rnd, "Value_002")


def _new_tree(name):
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.interface.new_socket(
        name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket(
        name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    return ng


def _store(tree, x, y, name, data_type, geo_out, value_out):
    st = _n(tree, "GeometryNodeStoreNamedAttribute", x, y,
            data_type=data_type, domain="POINT")
    st.inputs["Name"].default_value = name
    _ln(tree, geo_out, st.inputs["Geometry"])
    _ln(tree, value_out, st.inputs["Value"])
    return st.outputs["Geometry"]


def _store_common_viz_attrs(tree, geo, x=700):
    """Every cloud gets the attrs the pre-made vizs read.

    Unique per-cloud attrs (density, wave, …) stay; these four are what
    the Viz panel toggles, so enabling any viz must draw on every cloud.
    """
    pos = _pos(tree, x - 200, 240)
    idx = _idx(tree, x - 200, 40)
    cid = _rand_int(tree, x, 80, 0, 6, idx, seed=3)
    sid = _rand_int(tree, x, -80, 0, 4, idx, seed=5)
    zaxis = _n(tree, "FunctionNodeInputVector", x - 200, 160)
    zaxis.vector = (0.0, 0.0, 1.0)
    cross = _n(tree, "ShaderNodeVectorMath", x, 160, operation="CROSS_PRODUCT")
    _ln(tree, pos, cross.inputs[0])
    _ln(tree, zaxis.outputs["Vector"], cross.inputs[1])
    geo = _store(tree, x + 220, 120, "cluster_id", "INT", geo, cid)
    geo = _store(tree, x + 420, 120, "strand_id", "INT", geo, sid)
    geo = _store(tree, x + 620, 120, "flow", "FLOAT_VECTOR", geo,
                 cross.outputs["Vector"])
    return geo


def _set_radius(tree, x, y, geo_out, radius=0.08):
    sr = _n(tree, "GeometryNodeSetPointRadius", x, y)
    sr.inputs["Radius"].default_value = radius
    _ln(tree, geo_out, sr.inputs["Points"])
    return sr.outputs["Points"]


def _finish(tree, geo_out, x=700):
    geo_out = _store_common_viz_attrs(tree, geo_out, x)
    go = _n(tree, "NodeGroupOutput", x + 1100, 0)
    geo = _set_radius(tree, x + 900, 0, geo_out)
    _ln(tree, geo, go.inputs["Geometry"])
    _n(tree, "NodeGroupInput", -900, -200)


def _pos(tree, x, y):
    return _n(tree, "GeometryNodeInputPosition", x, y).outputs["Position"]


def _idx(tree, x, y):
    return _n(tree, "GeometryNodeInputIndex", x, y).outputs["Index"]


def _sep_z(tree, x, y, vec_out):
    sep = _n(tree, "ShaderNodeSeparateXYZ", x, y)
    _ln(tree, vec_out, sep.inputs["Vector"])
    return sep.outputs["Z"]


def _length(tree, x, y, vec_out):
    vm = _n(tree, "ShaderNodeVectorMath", x, y, operation="LENGTH")
    _ln(tree, vec_out, vm.inputs[0])
    return vm.outputs["Value"]


def _math(tree, x, y, op, a_out, b=None, b_out=None):
    m = _n(tree, "ShaderNodeMath", x, y, operation=op)
    _ln(tree, a_out, m.inputs[0])
    if b_out is not None:
        _ln(tree, b_out, m.inputs[1])
    elif b is not None:
        m.inputs[1].default_value = float(b)
    return m.outputs["Value"]


def _mesh_to_points(tree, x, y, mesh_out):
    m2p = _n(tree, "GeometryNodeMeshToPoints", x, y, mode="VERTICES")
    m2p.inputs["Radius"].default_value = 0.03
    _ln(tree, mesh_out, m2p.inputs["Mesh"])
    return m2p.outputs["Points"]


def _pc_object(name, loc, ng):
    pc = bpy.data.pointclouds.new(name)
    obj = bpy.data.objects.new(name, pc)
    obj.location = loc
    bpy.context.scene.collection.objects.link(obj)
    md = obj.modifiers.new("Spawn", "NODES")
    md.node_group = ng
    return obj


# --- per-cloud trees -------------------------------------------------------

def tree_heat_grid(n):
    t = _new_tree("PC · HeatGrid")
    grid = _n(t, "GeometryNodeMeshGrid", -500, 0)
    grid.inputs["Size X"].default_value = 4.0
    grid.inputs["Size Y"].default_value = 4.0
    grid.inputs["Vertices X"].default_value = n
    grid.inputs["Vertices Y"].default_value = n
    pts = _mesh_to_points(t, -280, 0, grid.outputs["Mesh"])
    dist = _length(t, -80, 160, _pos(t, -280, 200))
    heat = _math(t, 80, 160, "DIVIDE", dist, b=2.2)
    geo = _store(t, 280, 0, "heat", "FLOAT", pts, heat)
    return t, geo


def tree_cluster_ico(n):
    t = _new_tree("PC · ClusterIDs")
    ico = _n(t, "GeometryNodeMeshIcoSphere", -500, 0)
    ico.inputs["Radius"].default_value = 1.6
    ico.inputs["Subdivisions"].default_value = 3 if n >= 24 else 2
    pts = _mesh_to_points(t, -280, 0, ico.outputs["Mesh"])
    cid = _rand_int(t, 0, 80, 0, 6, _idx(t, -200, 80), seed=3)
    dist = _length(t, -80, -80, _pos(t, -280, -80))
    heat = _math(t, 80, -80, "DIVIDE", dist, b=1.6)
    geo = _store(t, 280, 0, "cluster_id", "INT", pts, cid)
    geo = _store(t, 480, 0, "heat", "FLOAT", geo, heat)
    return t, geo


def tree_flow_sphere(n):
    t = _new_tree("PC · FlowSwirl")
    sph = _n(t, "GeometryNodeMeshUVSphere", -520, 0)
    sph.inputs["Segments"].default_value = max(8, n)
    sph.inputs["Rings"].default_value = max(6, n // 2)
    sph.inputs["Radius"].default_value = 1.5
    pts = _mesh_to_points(t, -280, 0, sph.outputs["Mesh"])
    pos = _pos(t, -280, 200)
    zaxis = _n(t, "FunctionNodeInputVector", -280, 80)
    zaxis.vector = (0.0, 0.0, 1.0)
    cross = _n(t, "ShaderNodeVectorMath", -40, 160, operation="CROSS_PRODUCT")
    _ln(t, pos, cross.inputs[0])
    _ln(t, zaxis.outputs["Vector"], cross.inputs[1])
    heat = _math(t, -40, -40, "MULTIPLY",
                 _sep_z(t, -200, -40, pos), b=0.35)
    heat = _math(t, 140, -40, "ADD", heat, b=0.5)
    geo = _store(t, 280, 0, "flow", "FLOAT_VECTOR", pts, cross.outputs["Vector"])
    geo = _store(t, 500, 0, "heat", "FLOAT", geo, heat)
    return t, geo


def tree_helix(n):
    t = _new_tree("PC · Helix")
    sp = _n(t, "GeometryNodeCurveSpiral", -520, 0)
    sp.inputs["Resolution"].default_value = max(16, n * 4)
    sp.inputs["Rotations"].default_value = 5.0
    sp.inputs["Start Radius"].default_value = 0.4
    sp.inputs["End Radius"].default_value = 1.6
    sp.inputs["Height"].default_value = 3.2
    c2p = _n(t, "GeometryNodeCurveToPoints", -280, 0, mode="COUNT")
    c2p.inputs["Count"].default_value = max(80, n * 8)
    _ln(t, sp.outputs["Curve"], c2p.inputs["Curve"])
    pts = c2p.outputs["Points"]
    z = _sep_z(t, -80, 160, _pos(t, -280, 200))
    heat = _math(t, 80, 160, "DIVIDE", z, b=3.2)
    sid = _rand_int(t, 80, -40, 0, 4, _idx(t, -80, -40), seed=5)
    geo = _store(t, 300, 0, "strand_id", "INT", pts, sid)
    geo = _store(t, 520, 0, "heat", "FLOAT", geo, heat)
    return t, geo


def tree_volume(n):
    t = _new_tree("PC · VolumeScatter")
    cube = _n(t, "GeometryNodeVolumeCube", -560, 0)
    cube.inputs["Density"].default_value = 1.0
    for key, val in (("Min", (-1.4, -1.4, -1.4)),
                     ("Max", (1.4, 1.4, 1.4))):
        try:
            cube.inputs[key].default_value = val
        except Exception:
            pass
    for key in ("Resolution X", "Resolution Y", "Resolution Z"):
        if key in cube.inputs:
            cube.inputs[key].default_value = max(8, n // 3)
    dist = _n(t, "GeometryNodeDistributePointsInVolume", -280, 0)
    try:
        dist.inputs["Mode"].default_value = "DENSITY_RANDOM"
    except Exception:
        pass
    dist.inputs["Density"].default_value = 40.0
    dist.inputs["Seed"].default_value = 7
    _ln(t, cube.outputs["Volume"], dist.inputs["Volume"])
    pts = dist.outputs["Points"]
    noise = _n(t, "ShaderNodeTexNoise", -40, 160)
    noise.inputs["Scale"].default_value = 2.4
    _ln(t, _pos(t, -280, 200), noise.inputs["Vector"])
    fac = noise.outputs["Fac"] if "Fac" in noise.outputs else noise.outputs[0]
    geo = _store(t, 280, 0, "density", "FLOAT", pts, fac)
    geo = _store(t, 500, 0, "heat", "FLOAT", geo, fac)
    return t, geo


def tree_wave(n):
    t = _new_tree("PC · WavePlane")
    grid = _n(t, "GeometryNodeMeshGrid", -620, 0)
    grid.inputs["Size X"].default_value = 4.0
    grid.inputs["Size Y"].default_value = 4.0
    grid.inputs["Vertices X"].default_value = n
    grid.inputs["Vertices Y"].default_value = n
    pos = _pos(t, -620, 200)
    sep = _n(t, "ShaderNodeSeparateXYZ", -420, 200)
    _ln(t, pos, sep.inputs["Vector"])
    sine = _math(t, -240, 240, "SINE",
                 _math(t, -400, 280, "MULTIPLY", sep.outputs["X"], b=2.2))
    wave = _math(t, -80, 240, "MULTIPLY", sine, b=0.45)
    comb = _n(t, "ShaderNodeCombineXYZ", -80, 80)
    comb.inputs["X"].default_value = 0.0
    comb.inputs["Y"].default_value = 0.0
    _ln(t, wave, comb.inputs["Z"])
    sp = _n(t, "GeometryNodeSetPosition", -80, 0)
    _ln(t, grid.outputs["Mesh"], sp.inputs["Geometry"])
    _ln(t, comb.outputs["Vector"], sp.inputs["Offset"])
    pts = _mesh_to_points(t, 140, 0, sp.outputs["Geometry"])
    heat = _math(t, 140, 200, "ADD",
                 _math(t, 0, 200, "MULTIPLY", wave, b=0.5), b=0.5)
    geo = _store(t, 360, 0, "wave", "FLOAT", pts, heat)
    geo = _store(t, 560, 0, "heat", "FLOAT", geo, heat)
    return t, geo


def tree_mesh_cube():
    """MESH (faces) so mixed attrvis has a Surface carrier next to clouds."""
    t = _new_tree("Mesh · HeatCube")
    cube = _n(t, "GeometryNodeMeshCube", -400, 0)
    cube.inputs["Size"].default_value = (1.6, 1.6, 1.6)
    try:
        cube.inputs["Vertices X"].default_value = 6
        cube.inputs["Vertices Y"].default_value = 6
        cube.inputs["Vertices Z"].default_value = 6
    except Exception:
        pass
    z = _sep_z(t, -180, 160, _pos(t, -400, 200))
    heat = _math(t, 0, 160, "ADD",
                 _math(t, -180, 80, "MULTIPLY", z, b=0.4), b=0.5)
    geo = _store(t, 200, 0, "heat", "FLOAT", cube.outputs["Mesh"], heat)
    geo = _store_common_viz_attrs(t, geo, 400)
    go = _n(t, "NodeGroupOutput", 1400, 0)
    _ln(t, geo, go.inputs["Geometry"])
    _n(t, "NodeGroupInput", -700, -120)
    return t


def _mesh_object(name, loc, ng):
    me = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, me)
    obj.location = loc
    bpy.context.scene.collection.objects.link(obj)
    md = obj.modifiers.new("Spawn", "NODES")
    md.node_group = ng
    return obj


def _setup_view():
    sun_data = bpy.data.lights.new("Key Sun", "SUN")
    sun_data.energy = 2.2
    sun = bpy.data.objects.new("Key Sun", sun_data)
    sun.rotation_euler = (math.radians(48), math.radians(-20),
                          math.radians(25))
    bpy.context.scene.collection.objects.link(sun)

    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    cam.location = (11.0, -18.0, 12.0)
    cam.rotation_euler = (math.radians(58), 0.0, math.radians(18))
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    nt = world.node_tree
    if nt is not None:
        bg = next((n for n in nt.nodes if n.type == "BACKGROUND"), None)
        if bg is not None:
            bg.inputs[0].default_value = (0.035, 0.04, 0.045, 1.0)
            bg.inputs[1].default_value = 0.55


def _add_vizs(clouds, mesh):
    sys.path.insert(0, REPO)
    import attrviz as av
    from attrviz import node_builder

    av.register()
    bpy.context.scene.attrviz_gpu_markers = True
    ctx = bpy.context
    for o in list(ctx.view_layer.objects):
        o.select_set(False)
    for obj in list(clouds) + ([mesh] if mesh else []):
        obj.select_set(True)
    ctx.view_layer.objects.active = clouds[0]
    av.add_visualizer_from_selection(
        ctx, attribute="heat", domain="Point",
        style="Heat", display="Markers", name="Viz · heat · Markers")
    watch = bpy.data.collections.get(av.WATCH_COLLECTION)
    heat_viz = next((o for o in av.visualizers(ctx.scene)
                     if "heat" in o.name.lower()), None)
    if heat_viz is not None:
        md_h = av.viz_modifier(heat_viz)
        if md_h is not None:
            node_builder.set_input(md_h, "Scale", 0.06)
    extras = []
    extras.append(av.add_visualizer(
        ctx, target=None, scope=watch,
        attribute="cluster_id", domain="Point",
        style="Random", display="Markers",
        name="Viz · cluster_id · Markers"))
    extras.append(av.add_visualizer(
        ctx, target=None, scope=watch,
        attribute="flow", domain="Point",
        style="RGB", display="Arrows",
        name="Viz · flow · Arrows"))
    viz_tags = av.add_visualizer(
        ctx, target=None, scope=watch,
        attribute="strand_id", domain="Point",
        style="Heat", display="Tags",
        name="Viz · strand_id · Tags")
    extras.append(viz_tags)
    md = av.viz_modifier(viz_tags)
    if md is not None:
        node_builder.set_input(md, "Tag Cap", 200)
        node_builder.set_input(md, "Tag Size", 12)
        node_builder.set_input(md, "Facing Cull", False)
    for viz in extras:
        if viz is not None:
            viz.hide_viewport = True
            md_e = av.viz_modifier(viz)
            if md_e is not None:
                try:
                    node_builder.set_input(md_e, "Scale", 0.06)
                    node_builder.set_input(md_e, "Length", 0.25)
                except Exception:
                    pass
    print("[attrviz] pre-created 4 visualizers on attrvis "
          "(heat Markers visible; cluster_id / flow / Tags hidden)")
    print("  enable extras with the viewport eye in the Viz panel")


def _eval_point_count(obj):
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    try:
        gs = ev.evaluated_geometry()
        pc = getattr(gs, "pointcloud", None)
        if pc is not None:
            return pc.attributes.domain_size("POINT")
        me = getattr(gs, "mesh", None)
        if me is not None:
            return len(me.vertices)
    except Exception:
        pass
    data = getattr(ev, "data", None)
    if data is not None and hasattr(data, "points"):
        return len(data.points)
    if data is not None and hasattr(data, "vertices"):
        return len(data.vertices)
    return 0


def main():
    args = _parse()
    n = max(8, int(args.count))
    _clear()

    root = _coll("PointClouds")
    meshes_c = _coll("Meshes", root)

    layouts = [
        ("HeatGrid", tree_heat_grid, Vector((0.0, 0.0, 0.0))),
        ("ClusterIDs", tree_cluster_ico, Vector((8.0, 0.0, 0.0))),
        ("FlowSwirl", tree_flow_sphere, Vector((16.0, 0.0, 0.0))),
        ("Helix", tree_helix, Vector((0.0, 8.0, 0.0))),
        ("VolumeScatter", tree_volume, Vector((8.0, 8.0, 0.0))),
        ("WavePlane", tree_wave, Vector((16.0, 8.0, 0.0))),
    ]

    clouds = []
    for name, builder, loc in layouts:
        try:
            ng, geo = builder(n)
            _finish(ng, geo)
            obj = _pc_object(name, loc, ng)
            _link_obj(obj, root)
            clouds.append(obj)
            print(f"  built {name}")
        except Exception as exc:
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")

    mesh = None
    try:
        ng = tree_mesh_cube()
        mesh = _mesh_object("HeatCube", Vector((8.0, -5.5, 0.8)), ng)
        _link_obj(mesh, meshes_c)
        print("  built HeatCube (MESH)")
    except Exception as exc:
        print(f"  FAIL HeatCube: {type(exc).__name__}: {exc}")

    _setup_view()
    bpy.context.view_layer.update()

    for obj in clouds:
        npt = _eval_point_count(obj)
        print(f"[attrviz] {obj.name}: type={obj.type} evaluated_points={npt}")
    if mesh is not None:
        print(f"[attrviz] {mesh.name}: type={mesh.type} "
              f"evaluated_verts={_eval_point_count(mesh)}")

    if args.viz and clouds:
        _add_vizs(clouds, mesh)

    if clouds:
        bpy.ops.object.select_all(action="DESELECT")
        clouds[0].select_set(True)
        bpy.context.view_layer.objects.active = clouds[0]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=OUT)
    print(f"[attrviz] wrote {OUT}")
    print("  open in Blender 5 → GPU Overlay on → Viz panel")


if __name__ == "__main__":
    main()
