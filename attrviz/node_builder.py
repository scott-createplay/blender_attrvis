"""AttrViz engine — the visualizer's GN group, built programmatically.

Architecture (POR 005): a visualizer OBJECT watches its targets via
Object Info / Collection Info, so evaluated attributes arrive through
the depsgraph natively (no Python in the hot loop, watched objects
never touched). This module builds the shared engine group; per-
visualizer config lives in the MODIFIER's socket values.

The visualizer's two axes are real ENUM (menu) sockets — never
opaque ints (user-ratified):
  Style   = how data maps to color:  Heat (ramped float) | RGB (vector)
  Display = what geometry carries it: Markers | Surface | Arrows

Vendored node helpers (attrviz is standalone by design).
"""
import bpy

VERSION = "0.1.2"
ENGINE_NAME = "AttrViz Engine"

STYLES = ("Heat", "RGB")
DISPLAYS = ("Markers", "Surface", "Arrows")

# heat ramp: blue -> cyan -> green -> yellow -> red
HEAT = ((0.0, (0.05, 0.12, 0.90, 1.0)),
        (0.25, (0.00, 0.80, 0.90, 1.0)),
        (0.5, (0.10, 0.85, 0.20, 1.0)),
        (0.75, (0.95, 0.85, 0.10, 1.0)),
        (1.0, (0.95, 0.10, 0.05, 1.0)))


def _tree(name):
    existing = bpy.data.node_groups.get(name)
    if existing is not None:
        existing.name = name + ".old"
    return bpy.data.node_groups.new(name, "GeometryNodeTree")


def _sock(tree, name, in_out, socket_type, **props):
    s = tree.interface.new_socket(name, in_out=in_out,
                                  socket_type=socket_type)
    for key, value in props.items():
        try:
            setattr(s, key, value)
        except Exception:
            pass
    return s


def _n(tree, idname, x, y, **props):
    node = tree.nodes.new(idname)
    node.location = (x, y)
    for key, value in props.items():
        setattr(node, key, value)
    return node


def _link(tree, a, b):
    tree.links.new(a, b)


def _store(tree, x, y, name, data_type, geo_out, value_out,
           domain='POINT'):
    st = _n(tree, "GeometryNodeStoreNamedAttribute", x, y,
            data_type=data_type, domain=domain)
    st.inputs["Name"].default_value = name
    _link(tree, geo_out, st.inputs["Geometry"])
    _link(tree, value_out, st.inputs["Value"])
    return st


def _menu_switch(tree, x, y, data_type, sock_name, items, gi):
    """Menu Switch + a real enum socket on the group interface.
    Item-name -> identifier map rides the tree as an idprop so
    set_input can resolve string values."""
    ms = _n(tree, "GeometryNodeMenuSwitch", x, y, data_type=data_type)
    ms.enum_definition.enum_items.clear()
    ids = {}
    for i, item_name in enumerate(items):
        item = ms.enum_definition.enum_items.new(item_name)
        ids[item_name] = int(getattr(item, "identifier", i))
    _sock(tree, sock_name, "INPUT", "NodeSocketMenu")
    _link(tree, gi.outputs[sock_name], ms.inputs["Menu"])
    tree[f"attrviz_menu_{sock_name}"] = ids
    return ms


def set_input(md, name, value):
    """RNA attribute write (fires updates — the 5.2 path). Menu
    sockets take item NAMES directly (string enum); the idprop map is
    only a fallback for builds expecting int identifiers."""
    group = md.node_group
    for item in group.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == 'INPUT' \
                and item.name == name:
            prop = getattr(md.properties.inputs, item.identifier)
            try:
                prop.value = value
            except TypeError:
                ids = group.get(f"attrviz_menu_{name}")
                if ids is not None and isinstance(value, str) \
                        and value in dict(ids):
                    prop.value = int(dict(ids)[value])
                else:
                    raise
            return
    raise KeyError(name)


def ensure_heat_material(name="AttrViz Heat"):
    """Viz material: color from the 'vizcol' attribute (markers get it
    via instance-attr realize propagation — the lseed pattern; surface
    tint stores it per vertex), slight emission for dim viewports."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "vizcol"
    attr.location = (-320, 220)
    nt.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
    try:
        nt.links.new(attr.outputs["Color"],
                     bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 0.35
    except Exception:
        pass
    return mat


def ensure_arrow_material(name="AttrViz Arrow"):
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.95, 0.55, 0.10, 1.0)
    try:
        bsdf.inputs["Emission Color"].default_value = \
            (0.95, 0.55, 0.10, 1.0)
        bsdf.inputs["Emission Strength"].default_value = 0.3
    except Exception:
        pass
    return mat


def ensure_viz_group(force=False):
    name = f"{ENGINE_NAME} {VERSION}"
    existing = bpy.data.node_groups.get(name)
    if existing is not None and not force:
        return existing
    t = _tree(name)
    _sock(t, "Geometry", "OUTPUT", "NodeSocketGeometry")
    _sock(t, "Target", "INPUT", "NodeSocketObject",
          description="Single watched object (merged with Scope)")
    _sock(t, "Scope", "INPUT", "NodeSocketCollection",
          description="Watched collection (nested ok) — one "
                      "visualizer can cover many objects")
    _sock(t, "Attribute", "INPUT", "NodeSocketString",
          default_value="position")
    gi = _n(t, "NodeGroupInput", -1400, 0)
    go = _n(t, "NodeGroupOutput", 1600, 0)

    # watch targets natively: evaluated geometry through the depsgraph
    oi = _n(t, "GeometryNodeObjectInfo", -1220, 160,
            transform_space='RELATIVE')
    _link(t, gi.outputs["Target"], oi.inputs["Object"])
    ci = _n(t, "GeometryNodeCollectionInfo", -1220, 20,
            transform_space='RELATIVE')
    _link(t, gi.outputs["Scope"], ci.inputs["Collection"])
    join = _n(t, "GeometryNodeJoinGeometry", -1080, 100)
    _link(t, ci.outputs["Instances"], join.inputs["Geometry"])
    _link(t, oi.outputs["Geometry"], join.inputs["Geometry"])
    real = _n(t, "GeometryNodeRealizeInstances", -980, 100)
    _link(t, join.outputs["Geometry"], real.inputs["Geometry"])

    sep = _n(t, "GeometryNodeSeparateComponents", -860, 100)
    _link(t, real.outputs["Geometry"], sep.inputs["Geometry"])
    m2p = _n(t, "GeometryNodeMeshToPoints", -720, 220,
             mode='VERTICES')
    m2p.inputs["Radius"].default_value = 0.002
    _link(t, sep.outputs["Mesh"], m2p.inputs["Mesh"])
    c2p = _n(t, "GeometryNodeCurveToPoints", -720, 80,
             mode='EVALUATED')
    _link(t, sep.outputs["Curve"], c2p.inputs["Curve"])
    pjoin = _n(t, "GeometryNodeJoinGeometry", -560, 120)
    _link(t, sep.outputs["Point Cloud"], pjoin.inputs["Geometry"])
    _link(t, c2p.outputs["Points"], pjoin.inputs["Geometry"])
    _link(t, m2p.outputs["Points"], pjoin.inputs["Geometry"])

    # density cull (markers/arrows; surface tint is whole-surface)
    idx = _n(t, "GeometryNodeInputIndex", -560, -60)
    rnd = _n(t, "FunctionNodeRandomValue", -440, -40,
             data_type='FLOAT')
    rnd.inputs["Min"].default_value = 0.0
    rnd.inputs["Max"].default_value = 1.0
    _link(t, idx.outputs["Index"], rnd.inputs["ID"])
    _sock(t, "Density", "INPUT", "NodeSocketFloat", default_value=1.0,
          min_value=0.0, max_value=1.0,
          description="Markers/Arrows: fraction of elements shown")
    _sock(t, "Seed", "INPUT", "NodeSocketInt", default_value=0)
    _link(t, gi.outputs["Seed"], rnd.inputs["Seed"])
    keep = _n(t, "FunctionNodeCompare", -320, -40, data_type='FLOAT',
              operation='LESS_THAN')
    _link(t, rnd.outputs["Value"], keep.inputs["A"])
    _link(t, gi.outputs["Density"], keep.inputs["B"])
    cull = _n(t, "GeometryNodeSeparateGeometry", -420, 120,
              domain='POINT')
    _link(t, pjoin.outputs["Geometry"], cull.inputs["Geometry"])
    _link(t, keep.outputs["Result"], cull.inputs["Selection"])
    pts = cull.outputs["Selection"]

    # ── the value, both typed reads ─────────────────────────────────
    named_f = _n(t, "GeometryNodeInputNamedAttribute", -420, -180,
                 data_type='FLOAT')
    _link(t, gi.outputs["Attribute"], named_f.inputs["Name"])
    named_v = _n(t, "GeometryNodeInputNamedAttribute", -420, -300,
                 data_type='FLOAT_VECTOR')
    _link(t, gi.outputs["Attribute"], named_v.inputs["Name"])

    _sock(t, "Auto Range", "INPUT", "NodeSocketBool",
          default_value=True)
    _sock(t, "Range Min", "INPUT", "NodeSocketFloat",
          default_value=0.0)
    _sock(t, "Range Max", "INPUT", "NodeSocketFloat",
          default_value=1.0)
    stat = _n(t, "GeometryNodeAttributeStatistic", -280, -200,
              data_type='FLOAT', domain='POINT')
    _link(t, pts, stat.inputs["Geometry"])
    _link(t, named_f.outputs["Attribute"], stat.inputs["Attribute"])
    rmin = _n(t, "GeometryNodeSwitch", -120, -160,
              input_type='FLOAT')
    _link(t, gi.outputs["Auto Range"], rmin.inputs["Switch"])
    _link(t, gi.outputs["Range Min"], rmin.inputs["False"])
    _link(t, stat.outputs["Min"], rmin.inputs["True"])
    rmax = _n(t, "GeometryNodeSwitch", -120, -260,
              input_type='FLOAT')
    _link(t, gi.outputs["Auto Range"], rmax.inputs["Switch"])
    _link(t, gi.outputs["Range Max"], rmax.inputs["False"])
    _link(t, stat.outputs["Max"], rmax.inputs["True"])
    nrm = _n(t, "ShaderNodeMapRange", 20, -180)
    _link(t, named_f.outputs["Attribute"], nrm.inputs["Value"])
    _link(t, rmin.outputs["Output"], nrm.inputs["From Min"])
    _link(t, rmax.outputs["Output"], nrm.inputs["From Max"])

    # vector -> RGB: per-component auto normalize over the scope
    statv = _n(t, "GeometryNodeAttributeStatistic", -280, -400,
               data_type='FLOAT_VECTOR', domain='POINT')
    _link(t, pts, statv.inputs["Geometry"])
    _link(t, named_v.outputs["Attribute"], statv.inputs["Attribute"])
    vsub = _n(t, "ShaderNodeVectorMath", -80, -380,
              operation='SUBTRACT')
    _link(t, named_v.outputs["Attribute"], vsub.inputs[0])
    _link(t, statv.outputs["Min"], vsub.inputs[1])
    vspan = _n(t, "ShaderNodeVectorMath", -80, -470,
               operation='SUBTRACT')
    _link(t, statv.outputs["Max"], vspan.inputs[0])
    _link(t, statv.outputs["Min"], vspan.inputs[1])
    vguard = _n(t, "ShaderNodeVectorMath", 40, -470,
                operation='MAXIMUM')
    _link(t, vspan.outputs["Vector"], vguard.inputs[0])
    vguard.inputs[1].default_value = (1e-6, 1e-6, 1e-6)
    vdiv = _n(t, "ShaderNodeVectorMath", 160, -400,
              operation='DIVIDE')
    _link(t, vsub.outputs["Vector"], vdiv.inputs[0])
    _link(t, vguard.outputs["Vector"], vdiv.inputs[1])

    ramp = _n(t, "ShaderNodeValToRGB", 200, -180)
    ramp.name = "Heat Ramp"
    ramp.label = "Heat Ramp"
    elems = ramp.color_ramp.elements
    elems[0].position, elems[0].color = HEAT[0]
    elems[1].position, elems[1].color = HEAT[-1]
    for pos, col in HEAT[1:-1]:
        e = elems.new(pos)
        e.color = col
    _link(t, nrm.outputs["Result"], ramp.inputs["Fac"])

    # Style enum: how data becomes color
    style = _menu_switch(t, 480, -260, 'RGBA', "Style", STYLES, gi)
    _link(t, ramp.outputs["Color"], style.inputs["Heat"])
    _link(t, vdiv.outputs["Vector"], style.inputs["RGB"])
    colf = style.outputs["Output"]

    _sock(t, "Scale", "INPUT", "NodeSocketFloat", default_value=0.02,
          min_value=0.0001)

    s_val = _store(t, 40, 120, "vizval", 'FLOAT', pts,
                   nrm.outputs["Result"])
    ptsv = s_val.outputs["Geometry"]

    # ── Display: Markers ────────────────────────────────────────────
    sph = _n(t, "GeometryNodeMeshIcoSphere", 160, 340)
    sph.inputs["Radius"].default_value = 1.0
    sph.inputs["Subdivisions"].default_value = 1
    inst0 = _n(t, "GeometryNodeInstanceOnPoints", 340, 240)
    _link(t, ptsv, inst0.inputs["Points"])
    _link(t, sph.outputs["Mesh"], inst0.inputs["Instance"])
    _link(t, gi.outputs["Scale"], inst0.inputs["Scale"])
    s_col0 = _n(t, "GeometryNodeStoreNamedAttribute", 640, 240,
                data_type='FLOAT_COLOR', domain='INSTANCE')
    s_col0.inputs["Name"].default_value = "vizcol"
    _link(t, inst0.outputs["Instances"], s_col0.inputs["Geometry"])
    _link(t, colf, s_col0.inputs["Value"])
    s_val0 = _n(t, "GeometryNodeStoreNamedAttribute", 800, 240,
                data_type='FLOAT', domain='INSTANCE')
    s_val0.inputs["Name"].default_value = "vizval"
    _link(t, s_col0.outputs["Geometry"], s_val0.inputs["Geometry"])
    _link(t, nrm.outputs["Result"], s_val0.inputs["Value"])
    real0 = _n(t, "GeometryNodeRealizeInstances", 940, 240)
    _link(t, s_val0.outputs["Geometry"], real0.inputs["Geometry"])
    mk_mat = _n(t, "GeometryNodeSetMaterial", 1060, 240)
    mk_mat.inputs["Material"].default_value = ensure_heat_material()
    _link(t, real0.outputs["Geometry"], mk_mat.inputs["Geometry"])

    # ── Display: Surface (tint — the default expectation on meshes) ─
    nrml = _n(t, "GeometryNodeInputNormal", 160, 560)
    infl = _n(t, "ShaderNodeVectorMath", 300, 560, operation='SCALE')
    _link(t, nrml.outputs["Normal"], infl.inputs[0])
    infl.inputs["Scale"].default_value = 0.002
    puff = _n(t, "GeometryNodeSetPosition", 440, 620)
    _link(t, sep.outputs["Mesh"], puff.inputs["Geometry"])
    _link(t, infl.outputs["Vector"], puff.inputs["Offset"])
    s_cols = _n(t, "GeometryNodeStoreNamedAttribute", 620, 620,
                data_type='FLOAT_COLOR', domain='POINT')
    s_cols.inputs["Name"].default_value = "vizcol"
    _link(t, puff.outputs["Geometry"], s_cols.inputs["Geometry"])
    _link(t, colf, s_cols.inputs["Value"])
    s_vals = _n(t, "GeometryNodeStoreNamedAttribute", 780, 620,
                data_type='FLOAT', domain='POINT')
    s_vals.inputs["Name"].default_value = "vizval"
    _link(t, s_cols.outputs["Geometry"], s_vals.inputs["Geometry"])
    _link(t, nrm.outputs["Result"], s_vals.inputs["Value"])
    sf_mat = _n(t, "GeometryNodeSetMaterial", 940, 620)
    sf_mat.inputs["Material"].default_value = ensure_heat_material()
    _link(t, s_vals.outputs["Geometry"], sf_mat.inputs["Geometry"])

    # ── Display: Arrows (vector direction) ──────────────────────────
    try:
        align = _n(t, "FunctionNodeAlignRotationToVector", 320, -560,
                   axis='Z')
    except Exception:
        align = _n(t, "FunctionNodeAlignEulerToVector", 320, -560,
                   axis='Z')
    _link(t, named_v.outputs["Attribute"], align.inputs["Vector"])
    cone = _n(t, "GeometryNodeMeshCone", 160, -700)
    cone.inputs["Vertices"].default_value = 6
    cone.inputs["Radius Bottom"].default_value = 0.16
    cone.inputs["Radius Top"].default_value = 0.0
    cone.inputs["Depth"].default_value = 1.0
    cshift = _n(t, "GeometryNodeTransform", 320, -700)
    cshift.inputs["Translation"].default_value = (0.0, 0.0, 0.5)
    _link(t, cone.outputs["Mesh"], cshift.inputs["Geometry"])
    sc3 = _n(t, "ShaderNodeMath", 340, -440, operation='MULTIPLY')
    _link(t, gi.outputs["Scale"], sc3.inputs[0])
    sc3.inputs[1].default_value = 4.0
    inst1 = _n(t, "GeometryNodeInstanceOnPoints", 520, -600)
    _link(t, ptsv, inst1.inputs["Points"])
    _link(t, cshift.outputs["Geometry"], inst1.inputs["Instance"])
    _link(t, align.outputs["Rotation"], inst1.inputs["Rotation"])
    _link(t, sc3.outputs["Value"], inst1.inputs["Scale"])
    real1 = _n(t, "GeometryNodeRealizeInstances", 700, -600)
    _link(t, inst1.outputs["Instances"], real1.inputs["Geometry"])
    ar_mat = _n(t, "GeometryNodeSetMaterial", 820, -600)
    ar_mat.inputs["Material"].default_value = ensure_arrow_material()
    _link(t, real1.outputs["Geometry"], ar_mat.inputs["Geometry"])

    # Display enum: what geometry carries the read
    disp = _menu_switch(t, 1360, 0, 'GEOMETRY', "Display", DISPLAYS,
                        gi)
    _link(t, mk_mat.outputs["Geometry"], disp.inputs["Markers"])
    _link(t, sf_mat.outputs["Geometry"], disp.inputs["Surface"])
    _link(t, ar_mat.outputs["Geometry"], disp.inputs["Arrows"])
    _link(t, disp.outputs["Output"], go.inputs["Geometry"])
    t["attrviz_version"] = VERSION
    return t
