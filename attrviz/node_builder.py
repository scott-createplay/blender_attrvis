"""AttrViz engine — the visualizer's GN group, built programmatically.

Architecture (POR 005): a visualizer OBJECT watches its targets via
Object Info / Collection Info, so evaluated attributes arrive through
the depsgraph natively (no Python in the hot loop, watched objects
never touched). This module builds the shared engine group; per-
visualizer config lives in the MODIFIER's socket values.

Axes (Index Switch ints — Menu sockets break on 5.0 modifier ID-props):
  Domain  = which elements localize the read: Point | Edge | Face | Corner
  Style   = how data maps to color: Heat | RGB | Random
  Display = Markers | Surface | Arrows | Tags
  Tags are drawn by a GPU sprite prototype (not GN mesh text).
"""
import bpy

VERSION = "0.5.8"
ENGINE_NAME = "AttrViz Engine"
# Baked on mesh before Mesh to Points — Input Normal is (0,0,0) on points.
AV_NORMAL_ATTR = ".attrviz_normal"

DOMAINS = ("Point", "Edge", "Face", "Corner")
STYLES = ("Heat", "RGB", "Random")
DISPLAYS = ("Markers", "Surface", "Arrows", "Tags")

# GN field intrinsics — not Named Attribute lookups. Always current on
# the evaluated geometry (Index survives Subdiv; authored face_id may not).
INDEX_ATTR = "Index"
POSITION_ATTR = "Position"
NORMAL_ATTR = "Normal"
# (name, data_type, domains). Position also accepts lowercase "position".
INTRINSICS = (
    (INDEX_ATTR, 'INT', DOMAINS),
    (POSITION_ATTR, 'FLOAT_VECTOR', DOMAINS),
    (NORMAL_ATTR, 'FLOAT_VECTOR', ("Point", "Face", "Corner")),
)
INTRINSIC_NAMES = frozenset(n for n, _t, _d in INTRINSICS)
# Authored mesh attr names that duplicate an intrinsic — hide from menus.
INTRINSIC_ALIASES = frozenset({"position"})

# Blender attribute domain enum ↔ UI name
DOMAIN_TO_BLENDER = {
    "Point": 'POINT',
    "Edge": 'EDGE',
    "Face": 'FACE',
    "Corner": 'CORNER',
}
M2P_MODE = {
    "Point": 'VERTICES',
    "Edge": 'EDGES',
    "Face": 'FACES',
    "Corner": 'CORNERS',
}

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


def _sock_by_id(node, identifier):
    for s in node.inputs:
        if s.identifier == identifier:
            return s
    raise KeyError(identifier)


def _str_eq(tree, x, y, a_out, literal):
    """Attribute-string equality → boolean."""
    cmp = _n(tree, "FunctionNodeCompare", x, y,
             data_type='STRING', operation='EQUAL')
    _link(tree, a_out, _sock_by_id(cmp, "A_STR"))
    _sock_by_id(cmp, "B_STR").default_value = literal
    return cmp.outputs["Result"]


def _switch(tree, x, y, input_type, cond_out, false_out, true_out):
    sw = _n(tree, "GeometryNodeSwitch", x, y, input_type=input_type)
    _link(tree, cond_out, sw.inputs["Switch"])
    _link(tree, false_out, sw.inputs["False"])
    _link(tree, true_out, sw.inputs["True"])
    return sw.outputs["Output"]


def is_intrinsic(name):
    return name in INTRINSIC_NAMES or name in INTRINSIC_ALIASES


def intrinsic_dtype(name):
    if name in INTRINSIC_ALIASES or name == POSITION_ATTR:
        return 'FLOAT_VECTOR'
    for n, dt, _domains in INTRINSICS:
        if n == name:
            return dt
    return None


def _store(tree, x, y, name, data_type, geo_out, value_out,
           domain='POINT'):
    st = _n(tree, "GeometryNodeStoreNamedAttribute", x, y,
            data_type=data_type, domain=domain)
    st.inputs["Name"].default_value = name
    _link(tree, geo_out, st.inputs["Geometry"])
    _link(tree, value_out, st.inputs["Value"])
    return st


def _menu_switch(tree, x, y, data_type, sock_name, items, gi):
    """Index Switch + int socket on the group interface."""
    sw = _n(tree, "GeometryNodeIndexSwitch", x, y, data_type=data_type)
    while len(sw.index_switch_items) < len(items):
        sw.index_switch_items.new()
    while len(sw.index_switch_items) > len(items):
        sw.index_switch_items.remove(sw.index_switch_items[-1])
    sock = _sock(tree, sock_name, "INPUT", "NodeSocketInt",
                 default_value=0, min_value=0, max_value=len(items) - 1)
    try:
        sock.description = " / ".join(items)
    except Exception:
        pass
    _link(tree, gi.outputs[sock_name], sw.inputs["Index"])
    ids = {}
    sockets = {}
    for i, item_name in enumerate(items):
        sockets[item_name] = sw.inputs[str(i)]
        ids[item_name] = i
    tree[f"attrviz_menu_{sock_name}"] = ids
    return sw, sockets


def _menu_value(group, name, value):
    ids = group.get(f"attrviz_menu_{name}")
    if ids is not None and isinstance(value, str) and value in dict(ids):
        return int(dict(ids)[value])
    return value


def _socket_item(group, name):
    for item in group.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == 'INPUT' \
                and item.name == name:
            return item
    raise KeyError(name)


def _coerce_idprop_value(value):
    """ID-properties segfault on bpy_prop_array; pass plain Python values."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bpy.types.Object, bpy.types.Collection,
                          bpy.types.Material)):
        return value
    if hasattr(value, "to_list"):
        try:
            return value.to_list()
        except Exception:
            pass
    if hasattr(value, "__len__") and not isinstance(value, (bytes, bytearray)):
        try:
            return [float(x) for x in value]
        except Exception:
            pass
    return value


def set_input(md, name, value):
    """Write a modifier input by socket name."""
    item = _socket_item(md.node_group, name)
    value = _menu_value(md.node_group, name, value)
    value = _coerce_idprop_value(value)
    props = getattr(md, "properties", None)
    if props is not None and hasattr(props, "inputs"):
        getattr(props.inputs, item.identifier).value = value
    else:
        md[item.identifier] = value


def get_input(md, name):
    item = _socket_item(md.node_group, name)
    props = getattr(md, "properties", None)
    if props is not None and hasattr(props, "inputs"):
        return getattr(props.inputs, item.identifier).value
    return md.get(item.identifier)


def menu_input_name(md, name):
    value = get_input(md, name)
    ids = md.node_group.get(f"attrviz_menu_{name}")
    if ids is not None:
        for item_name, idx in dict(ids).items():
            if idx == value or item_name == value:
                return item_name
    return value


def input_rna_path(md, identifier):
    props = getattr(md, "properties", None)
    if props is not None and hasattr(props, "inputs"):
        return getattr(props.inputs, identifier), "value"
    return md, f'["{identifier}"]'


# vizcol drives an emission-only viewport material. Workbench Solid
# Attribute cannot color geometry created only inside GN (Blender
# limitation); Material Preview / EEVEE can. Viz objects stay
# hide_render — display carriers, not beauty-pass content.
VIZCOL_ATTR = "vizcol"
AV_COL_ATTR = ".attrviz_col"
VIZ_MATERIAL_NAME = "AttrViz Display"


def ensure_viz_material(name=VIZ_MATERIAL_NAME, force=False):
    """Unlit Emission = vizcol (flat data color in Material Preview)."""
    mat = bpy.data.materials.get(name)
    if mat is not None and not force and mat.get("attrviz_shader") == VERSION:
        return mat
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat["attrviz_display"] = True
    mat["attrviz_shader"] = VERSION
    try:
        mat.diffuse_color = (0.9, 0.9, 0.9, 1.0)
    except Exception:
        pass
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    em = nt.nodes.new("ShaderNodeEmission")
    em.location = (0, 0)
    em.inputs["Strength"].default_value = 1.0
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.location = (-360, 80)
    attr.attribute_name = VIZCOL_ATTR
    try:
        attr.attribute_type = 'GEOMETRY'
    except Exception:
        pass
    nt.links.new(attr.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
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
          description="Watched collection (nested ok)")
    _sock(t, "Attribute", "INPUT", "NodeSocketString",
          default_value="position")
    gi = _n(t, "NodeGroupInput", -1600, 0)
    go = _n(t, "NodeGroupOutput", 1800, 0)

    # ── watch targets ───────────────────────────────────────────────
    oi = _n(t, "GeometryNodeObjectInfo", -1420, 160,
            transform_space='RELATIVE')
    _link(t, gi.outputs["Target"], oi.inputs["Object"])
    ci = _n(t, "GeometryNodeCollectionInfo", -1420, 20,
            transform_space='RELATIVE')
    _link(t, gi.outputs["Scope"], ci.inputs["Collection"])
    join = _n(t, "GeometryNodeJoinGeometry", -1280, 100)
    _link(t, ci.outputs["Instances"], join.inputs["Geometry"])
    _link(t, oi.outputs["Geometry"], join.inputs["Geometry"])
    real = _n(t, "GeometryNodeRealizeInstances", -1180, 100)
    _link(t, join.outputs["Geometry"], real.inputs["Geometry"])
    sep = _n(t, "GeometryNodeSeparateComponents", -1060, 100)
    _link(t, real.outputs["Geometry"], sep.inputs["Geometry"])

    # Bake Normal onto every mesh domain BEFORE Mesh to Points.
    # GeometryNodeInputNormal on point-clouds is (0,0,0) → arrows all +Z.
    mesh_geo = sep.outputs["Mesh"]
    for i, dom in enumerate(DOMAINS):
        inn = _n(t, "GeometryNodeInputNormal", -1020, 320 - i * 70)
        st = _n(t, "GeometryNodeStoreNamedAttribute", -900, 320 - i * 70,
                data_type='FLOAT_VECTOR', domain=DOMAIN_TO_BLENDER[dom])
        st.inputs["Name"].default_value = AV_NORMAL_ATTR
        _link(t, mesh_geo, st.inputs["Geometry"])
        _link(t, inn.outputs["Normal"], st.inputs["Value"])
        mesh_geo = st.outputs["Geometry"]

    # Domain: localize sampling to Point / Edge / Face / Corner
    m2p_geos = {}
    for i, dom in enumerate(DOMAINS):
        m2p = _n(t, "GeometryNodeMeshToPoints", -760, 220 - i * 100,
                 mode=M2P_MODE[dom])
        m2p.inputs["Radius"].default_value = 0.002
        _link(t, mesh_geo, m2p.inputs["Mesh"])
        m2p_geos[dom] = m2p.outputs["Points"]
    # Point domain also merges curves + point clouds (Houdini point cloud)
    c2p = _n(t, "GeometryNodeCurveToPoints", -900, -200, mode='EVALUATED')
    _link(t, sep.outputs["Curve"], c2p.inputs["Curve"])
    pjoin = _n(t, "GeometryNodeJoinGeometry", -760, 120)
    _link(t, sep.outputs["Point Cloud"], pjoin.inputs["Geometry"])
    _link(t, c2p.outputs["Points"], pjoin.inputs["Geometry"])
    _link(t, m2p_geos["Point"], pjoin.inputs["Geometry"])
    m2p_geos["Point"] = pjoin.outputs["Geometry"]

    domain_sw, domain_in = _menu_switch(
        t, -620, 100, 'GEOMETRY', "Domain", DOMAINS, gi)
    for dom in DOMAINS:
        _link(t, m2p_geos[dom], domain_in[dom])
    domain_pts = domain_sw.outputs["Output"]

    # density cull (markers/arrows)
    idx = _n(t, "GeometryNodeInputIndex", -560, -60)
    rnd = _n(t, "FunctionNodeRandomValue", -440, -40, data_type='FLOAT')
    rnd.inputs["Min"].default_value = 0.0
    rnd.inputs["Max"].default_value = 1.0
    _link(t, idx.outputs["Index"], rnd.inputs["ID"])
    _sock(t, "Density", "INPUT", "NodeSocketFloat", default_value=1.0,
          min_value=0.0, max_value=1.0,
          description="Markers/Arrows: fraction of elements shown")
    _sock(t, "Seed", "INPUT", "NodeSocketInt", default_value=0,
          description="Random color / density seed")
    _link(t, gi.outputs["Seed"], rnd.inputs["Seed"])
    keep = _n(t, "FunctionNodeCompare", -320, -40, data_type='FLOAT',
              operation='LESS_THAN')
    _link(t, rnd.outputs["Value"], keep.inputs["A"])
    _link(t, gi.outputs["Density"], keep.inputs["B"])
    cull = _n(t, "GeometryNodeSeparateGeometry", -420, 120,
              domain='POINT')
    _link(t, domain_pts, cull.inputs["Geometry"])
    _link(t, keep.outputs["Result"], cull.inputs["Selection"])
    pts = cull.outputs["Selection"]

    # ── typed reads (Named Attribute ⊕ GN field intrinsics) ─────────
    named_f = _n(t, "GeometryNodeInputNamedAttribute", -420, -180,
                 data_type='FLOAT')
    _link(t, gi.outputs["Attribute"], named_f.inputs["Name"])
    named_v = _n(t, "GeometryNodeInputNamedAttribute", -420, -300,
                 data_type='FLOAT_VECTOR')
    _link(t, gi.outputs["Attribute"], named_v.inputs["Name"])
    named_i = _n(t, "GeometryNodeInputNamedAttribute", -420, -420,
                 data_type='INT')
    _link(t, gi.outputs["Attribute"], named_i.inputs["Name"])

    attr_name = gi.outputs["Attribute"]
    is_index = _str_eq(t, -560, -560, attr_name, INDEX_ATTR)
    is_normal = _str_eq(t, -560, -640, attr_name, NORMAL_ATTR)
    is_pos_c = _str_eq(t, -560, -720, attr_name, POSITION_ATTR)
    is_pos_l = _str_eq(t, -560, -780, attr_name, "position")
    is_pos_or = _n(t, "FunctionNodeBooleanMath", -420, -750,
                   operation='OR')
    _link(t, is_pos_c, is_pos_or.inputs[0])
    _link(t, is_pos_l, is_pos_or.inputs[1])
    is_position = is_pos_or.outputs["Boolean"]

    field_idx = _n(t, "GeometryNodeInputIndex", -700, -560)
    field_pos = _n(t, "GeometryNodeInputPosition", -700, -640)
    # Read baked mesh normals (survives Mesh to Points); not Input Normal.
    field_nrm = _n(t, "GeometryNodeInputNamedAttribute", -700, -720,
                   data_type='FLOAT_VECTOR')
    field_nrm.inputs["Name"].default_value = AV_NORMAL_ATTR

    float_f = _switch(t, -280, -180, 'FLOAT', is_index,
                      named_f.outputs["Attribute"],
                      field_idx.outputs["Index"])
    int_f = _switch(t, -280, -420, 'INT', is_index,
                    named_i.outputs["Attribute"],
                    field_idx.outputs["Index"])
    vec_n = _switch(t, -280, -300, 'VECTOR', is_normal,
                    named_v.outputs["Attribute"],
                    field_nrm.outputs["Attribute"])
    vec_f = _switch(t, -140, -300, 'VECTOR', is_position,
                    vec_n, field_pos.outputs["Position"])

    _sock(t, "Auto Range", "INPUT", "NodeSocketBool", default_value=True)
    _sock(t, "Range Min", "INPUT", "NodeSocketFloat", default_value=0.0)
    _sock(t, "Range Max", "INPUT", "NodeSocketFloat", default_value=1.0)
    stat = _n(t, "GeometryNodeAttributeStatistic", -40, -200,
              data_type='FLOAT', domain='POINT')
    _link(t, pts, stat.inputs["Geometry"])
    _link(t, float_f, stat.inputs["Attribute"])
    rmin = _n(t, "GeometryNodeSwitch", 100, -160, input_type='FLOAT')
    _link(t, gi.outputs["Auto Range"], rmin.inputs["Switch"])
    _link(t, gi.outputs["Range Min"], rmin.inputs["False"])
    _link(t, stat.outputs["Min"], rmin.inputs["True"])
    rmax = _n(t, "GeometryNodeSwitch", 100, -260, input_type='FLOAT')
    _link(t, gi.outputs["Auto Range"], rmax.inputs["Switch"])
    _link(t, gi.outputs["Range Max"], rmax.inputs["False"])
    _link(t, stat.outputs["Max"], rmax.inputs["True"])
    nrm = _n(t, "ShaderNodeMapRange", 240, -180)
    _link(t, float_f, nrm.inputs["Value"])
    _link(t, rmin.outputs["Output"], nrm.inputs["From Min"])
    _link(t, rmax.outputs["Output"], nrm.inputs["From Max"])

    # vector -> RGB
    statv = _n(t, "GeometryNodeAttributeStatistic", -40, -400,
               data_type='FLOAT_VECTOR', domain='POINT')
    _link(t, pts, statv.inputs["Geometry"])
    _link(t, vec_f, statv.inputs["Attribute"])
    vsub = _n(t, "ShaderNodeVectorMath", 140, -380, operation='SUBTRACT')
    _link(t, vec_f, vsub.inputs[0])
    _link(t, statv.outputs["Min"], vsub.inputs[1])
    vspan = _n(t, "ShaderNodeVectorMath", 140, -470, operation='SUBTRACT')
    _link(t, statv.outputs["Max"], vspan.inputs[0])
    _link(t, statv.outputs["Min"], vspan.inputs[1])
    vguard = _n(t, "ShaderNodeVectorMath", 260, -470, operation='MAXIMUM')
    _link(t, vspan.outputs["Vector"], vguard.inputs[0])
    vguard.inputs[1].default_value = (1e-6, 1e-6, 1e-6)
    vdiv = _n(t, "ShaderNodeVectorMath", 380, -400, operation='DIVIDE')
    _link(t, vsub.outputs["Vector"], vdiv.inputs[0])
    _link(t, vguard.outputs["Vector"], vdiv.inputs[1])

    # Random / categorical: stable color from int (or float→int) id
    f2i = _n(t, "FunctionNodeFloatToInt", -40, -520)
    _link(t, float_f, f2i.inputs["Float"])
    iadd = _n(t, "FunctionNodeIntegerMath", 100, -520, operation='ADD')
    _link(t, f2i.outputs["Integer"], iadd.inputs[0])
    _link(t, int_f, iadd.inputs[1])
    hashed = _n(t, "FunctionNodeHashValue", 240, -520)
    try:
        hashed.data_type = 'INT'
    except Exception:
        pass
    _link(t, iadd.outputs["Value"], hashed.inputs["Value"])
    _link(t, gi.outputs["Seed"], hashed.inputs["Seed"])
    randc = _n(t, "FunctionNodeRandomValue", 400, -520,
               data_type='FLOAT_VECTOR')
    randc.inputs["Min"].default_value = (0.05, 0.05, 0.05)
    randc.inputs["Max"].default_value = (0.95, 0.95, 0.95)
    _link(t, hashed.outputs["Hash"], randc.inputs["ID"])
    _link(t, gi.outputs["Seed"], randc.inputs["Seed"])

    ramp = _n(t, "ShaderNodeValToRGB", 420, -180)
    ramp.name = "Heat Ramp"
    ramp.label = "Heat Ramp"
    elems = ramp.color_ramp.elements
    elems[0].position, elems[0].color = HEAT[0]
    elems[1].position, elems[1].color = HEAT[-1]
    for pos, col in HEAT[1:-1]:
        e = elems.new(pos)
        e.color = col
    _link(t, nrm.outputs["Result"], ramp.inputs["Fac"])

    style, style_in = _menu_switch(t, 560, -260, 'RGBA', "Style",
                                   STYLES, gi)
    _link(t, ramp.outputs["Color"], style_in["Heat"])
    _link(t, vdiv.outputs["Vector"], style_in["RGB"])
    _link(t, randc.outputs["Value"], style_in["Random"])
    colf = style.outputs["Output"]

    _sock(t, "Scale", "INPUT", "NodeSocketFloat", default_value=0.02,
          min_value=0.0001,
          description="Markers: radius. Arrows: shaft thickness")
    _sock(t, "Length", "INPUT", "NodeSocketFloat", default_value=0.08,
          min_value=0.0001,
          description="Arrows: shaft length (vector magnitude lives in the attr)")
    _sock(t, "Arrow Color", "INPUT", "NodeSocketColor",
          default_value=(0.95, 0.55, 0.10, 1.0),
          description="Arrows: solid tint (per visualizer)")
    _sock(t, "Tag Cap", "INPUT", "NodeSocketInt", default_value=10000,
          min_value=1, max_value=10000,
          description="Tags: max labels drawn (scale budget)")
    _sock(t, "Tag Size", "INPUT", "NodeSocketInt", default_value=14,
          min_value=6, max_value=64,
          description="Tags: font size in pixels (integer steps)")
    _sock(t, "Tag Color", "INPUT", "NodeSocketColor",
          default_value=(0.95, 0.95, 0.95, 1.0),
          description="Tags: label / sprite tint")
    _sock(t, "Decimals", "INPUT", "NodeSocketInt", default_value=2,
          min_value=0, max_value=6,
          description="Tags: float decimals (ints print clean)")
    _sock(t, "Facing Cull", "INPUT", "NodeSocketBool",
          default_value=True,
          description="Tags: skip back-facing elements (Face domain)")

    s_val = _store(t, 40, 120, "vizval", 'FLOAT', pts,
                   nrm.outputs["Result"])
    ptsv = s_val.outputs["Geometry"]

    # ── Markers ─────────────────────────────────────────────────────
    sph = _n(t, "GeometryNodeMeshIcoSphere", 160, 340)
    sph.inputs["Radius"].default_value = 1.0
    sph.inputs["Subdivisions"].default_value = 1
    inst0 = _n(t, "GeometryNodeInstanceOnPoints", 340, 240)
    _link(t, ptsv, inst0.inputs["Points"])
    _link(t, sph.outputs["Mesh"], inst0.inputs["Instance"])
    _link(t, gi.outputs["Scale"], inst0.inputs["Scale"])
    s_col0 = _n(t, "GeometryNodeStoreNamedAttribute", 640, 240,
                data_type='FLOAT_COLOR', domain='INSTANCE')
    s_col0.inputs["Name"].default_value = VIZCOL_ATTR
    _link(t, inst0.outputs["Instances"], s_col0.inputs["Geometry"])
    _link(t, colf, s_col0.inputs["Value"])
    s_val0 = _n(t, "GeometryNodeStoreNamedAttribute", 800, 240,
                data_type='FLOAT', domain='INSTANCE')
    s_val0.inputs["Name"].default_value = "vizval"
    _link(t, s_col0.outputs["Geometry"], s_val0.inputs["Geometry"])
    _link(t, nrm.outputs["Result"], s_val0.inputs["Value"])
    real0 = _n(t, "GeometryNodeRealizeInstances", 940, 240)
    _link(t, s_val0.outputs["Geometry"], real0.inputs["Geometry"])
    # Instance colors land as POINT — also write CORNER for Workbench
    mk_src = _n(t, "GeometryNodeInputNamedAttribute", 1060, 240,
                data_type='FLOAT_COLOR')
    mk_src.inputs["Name"].default_value = VIZCOL_ATTR
    mk_corner = _n(t, "GeometryNodeStoreNamedAttribute", 1180, 240,
                   data_type='FLOAT_COLOR', domain='CORNER')
    mk_corner.inputs["Name"].default_value = VIZCOL_ATTR
    _link(t, real0.outputs["Geometry"], mk_corner.inputs["Geometry"])
    _link(t, mk_src.outputs["Attribute"], mk_corner.inputs["Value"])
    mk_mat = _n(t, "GeometryNodeSetMaterial", 1320, 240)
    mk_mat.inputs["Material"].default_value = ensure_viz_material()
    _link(t, mk_corner.outputs["Geometry"], mk_mat.inputs["Geometry"])

    # ── Surface: inflate mesh, store vizcol on the chosen domain ────
    nrml = _n(t, "GeometryNodeInputNormal", 160, 560)
    infl = _n(t, "ShaderNodeVectorMath", 300, 560, operation='SCALE')
    _link(t, nrml.outputs["Normal"], infl.inputs[0])
    infl.inputs["Scale"].default_value = 0.002
    puff = _n(t, "GeometryNodeSetPosition", 440, 620)
    _link(t, mesh_geo, puff.inputs["Geometry"])
    _link(t, infl.outputs["Vector"], puff.inputs["Offset"])

    surf_geos = {}
    for i, dom in enumerate(DOMAINS):
        # Evaluate color on the chosen domain (Index/Heat correct here)
        st = _n(t, "GeometryNodeStoreNamedAttribute", 620, 700 - i * 80,
                data_type='FLOAT_COLOR',
                domain=DOMAIN_TO_BLENDER[dom])
        st.inputs["Name"].default_value = AV_COL_ATTR
        _link(t, puff.outputs["Geometry"], st.inputs["Geometry"])
        _link(t, colf, st.inputs["Value"])
        sv = _n(t, "GeometryNodeStoreNamedAttribute", 780, 700 - i * 80,
                data_type='FLOAT', domain=DOMAIN_TO_BLENDER[dom])
        sv.inputs["Name"].default_value = "vizval"
        _link(t, st.outputs["Geometry"], sv.inputs["Geometry"])
        _link(t, nrm.outputs["Result"], sv.inputs["Value"])
        # Promote to CORNER Color Attribute for Solid Attribute shading
        src = _n(t, "GeometryNodeInputNamedAttribute", 900, 700 - i * 80,
                 data_type='FLOAT_COLOR')
        src.inputs["Name"].default_value = AV_COL_ATTR
        stc = _n(t, "GeometryNodeStoreNamedAttribute", 1040, 700 - i * 80,
                 data_type='FLOAT_COLOR', domain='CORNER')
        stc.inputs["Name"].default_value = VIZCOL_ATTR
        _link(t, sv.outputs["Geometry"], stc.inputs["Geometry"])
        _link(t, src.outputs["Attribute"], stc.inputs["Value"])
        smat = _n(t, "GeometryNodeSetMaterial", 1180, 700 - i * 80)
        smat.inputs["Material"].default_value = ensure_viz_material()
        _link(t, stc.outputs["Geometry"], smat.inputs["Geometry"])
        surf_geos[dom] = smat.outputs["Geometry"]

    # Same Domain socket drives which domain color is evaluated on
    surf_sw = _n(t, "GeometryNodeIndexSwitch", 1340, 560,
                 data_type='GEOMETRY')
    while len(surf_sw.index_switch_items) < len(DOMAINS):
        surf_sw.index_switch_items.new()
    while len(surf_sw.index_switch_items) > len(DOMAINS):
        surf_sw.index_switch_items.remove(surf_sw.index_switch_items[-1])
    _link(t, gi.outputs["Domain"], surf_sw.inputs["Index"])
    for i, dom in enumerate(DOMAINS):
        _link(t, surf_geos[dom], surf_sw.inputs[str(i)])
    sf_out = surf_sw.outputs["Output"]

    # ── Arrows (per-viz Length + Arrow Color; Scale = thickness) ────
    # Direction is the attribute vector only. Non-vectors → (0,0,0).
    # Align-to-vector treats 0 as +Z, so zero-length also kills scale.
    _sock(t, "Attr Is Vector", "INPUT", "NodeSocketBool",
          default_value=True,
          description="Set by UI: attribute is a vector (else arrows use 0)")
    zero_v = _n(t, "FunctionNodeInputVector", 200, -640)
    zero_v.vector = (0.0, 0.0, 0.0)
    adir = _switch(t, 320, -640, 'VECTOR',
                   gi.outputs["Attr Is Vector"],
                   zero_v.outputs["Vector"], vec_f)
    try:
        align = _n(t, "FunctionNodeAlignRotationToVector", 460, -640,
                   axis='Z')
    except Exception:
        align = _n(t, "FunctionNodeAlignEulerToVector", 460, -640,
                   axis='Z')
    _link(t, adir, align.inputs["Vector"])
    alen = _n(t, "ShaderNodeVectorMath", 460, -720, operation='LENGTH')
    _link(t, adir, alen.inputs[0])
    alive = _n(t, "FunctionNodeCompare", 580, -720, data_type='FLOAT',
               operation='GREATER_THAN')
    _link(t, alen.outputs["Value"], alive.inputs["A"])
    alive.inputs["B"].default_value = 1e-8
    # Drop (0,0,0) points — Align would otherwise invent +Z arrows.
    apts = _n(t, "GeometryNodeSeparateGeometry", 580, -640,
              domain='POINT')
    _link(t, ptsv, apts.inputs["Geometry"])
    _link(t, alive.outputs["Result"], apts.inputs["Selection"])
    cone = _n(t, "GeometryNodeMeshCone", 160, -780)
    cone.inputs["Vertices"].default_value = 6
    cone.inputs["Radius Bottom"].default_value = 1.0
    cone.inputs["Radius Top"].default_value = 0.0
    cone.inputs["Depth"].default_value = 1.0
    cshift = _n(t, "GeometryNodeTransform", 320, -780)
    cshift.inputs["Translation"].default_value = (0.0, 0.0, 0.5)
    _link(t, cone.outputs["Mesh"], cshift.inputs["Geometry"])
    # non-uniform instance scale: (thickness, thickness, length)
    thick = _n(t, "ShaderNodeMath", 340, -520, operation='MULTIPLY')
    _link(t, gi.outputs["Scale"], thick.inputs[0])
    thick.inputs[1].default_value = 0.25
    ascale = _n(t, "ShaderNodeCombineXYZ", 500, -560)
    _link(t, thick.outputs["Value"], ascale.inputs["X"])
    _link(t, thick.outputs["Value"], ascale.inputs["Y"])
    _link(t, gi.outputs["Length"], ascale.inputs["Z"])
    inst1 = _n(t, "GeometryNodeInstanceOnPoints", 700, -680)
    _link(t, apts.outputs["Selection"], inst1.inputs["Points"])
    _link(t, cshift.outputs["Geometry"], inst1.inputs["Instance"])
    _link(t, align.outputs["Rotation"], inst1.inputs["Rotation"])
    _link(t, ascale.outputs["Vector"], inst1.inputs["Scale"])
    # per-visualizer tint via vizcol Color Attribute (no material)
    s_colar = _n(t, "GeometryNodeStoreNamedAttribute", 1000, -680,
                 data_type='FLOAT_COLOR', domain='INSTANCE')
    s_colar.inputs["Name"].default_value = VIZCOL_ATTR
    _link(t, inst1.outputs["Instances"], s_colar.inputs["Geometry"])
    _link(t, gi.outputs["Arrow Color"], s_colar.inputs["Value"])
    real1 = _n(t, "GeometryNodeRealizeInstances", 1140, -680)
    _link(t, s_colar.outputs["Geometry"], real1.inputs["Geometry"])
    ar_src = _n(t, "GeometryNodeInputNamedAttribute", 1260, -680,
                data_type='FLOAT_COLOR')
    ar_src.inputs["Name"].default_value = VIZCOL_ATTR
    ar_corner = _n(t, "GeometryNodeStoreNamedAttribute", 1380, -680,
                   data_type='FLOAT_COLOR', domain='CORNER')
    ar_corner.inputs["Name"].default_value = VIZCOL_ATTR
    _link(t, real1.outputs["Geometry"], ar_corner.inputs["Geometry"])
    _link(t, ar_src.outputs["Attribute"], ar_corner.inputs["Value"])
    ar_mat = _n(t, "GeometryNodeSetMaterial", 1520, -680)
    ar_mat.inputs["Material"].default_value = ensure_viz_material()
    _link(t, ar_corner.outputs["Geometry"], ar_mat.inputs["Geometry"])

    # Tags: empty geometry — GPU sprite prototype draws labels
    tags_empty = _n(t, "GeometryNodePoints", 1000, -200)
    tags_empty.inputs["Count"].default_value = 0

    disp, disp_in = _menu_switch(t, 1700, 0, 'GEOMETRY', "Display",
                                 DISPLAYS, gi)
    _link(t, mk_mat.outputs["Geometry"], disp_in["Markers"])
    _link(t, sf_out, disp_in["Surface"])
    _link(t, ar_mat.outputs["Geometry"], disp_in["Arrows"])
    _link(t, tags_empty.outputs["Points"], disp_in["Tags"])
    _link(t, disp.outputs["Output"], go.inputs["Geometry"])
    t["attrviz_version"] = VERSION
    return t
