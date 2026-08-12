"""AttrViz — first-class attribute visualizers for Blender.

Houdini's visualizer model on native constructs (POR 005):
- a visualizer is an ordinary OBJECT in the visible "Visualizers"
  collection — the outliner is the registry UI; Enabled / viewport
  eye toggles draw (no compositing of overlapping viz);
- Domain localizes the read (Point / Edge / Face / Corner);
- Color maps the value (Heat / RGB / Random); Type chooses carriers
  (Markers / Surface / Arrows);
- GN pulls evaluated geometry through the depsgraph — zero mutation;
- Display-only: emission material reads vizcol (Workbench cannot color
  GN-only geometry). Viz objects use hide_render (skip F12) but keep
  visible_camera so Material Preview can see them.
"""
import bpy

from . import node_builder
from . import tags_draw
from . import gpu_overlay

VIZ_COLLECTION = "Visualizers"
VIZ_PANEL_CATEGORY = "Viz"
VECTORISH = {'FLOAT_VECTOR', 'FLOAT2'}
CATEGORICAL = {'INT', 'BOOLEAN', 'INT8', 'INT16_2D', 'INT32_2D'}

# Blender attribute domain → UI Domain name
_BLENDER_TO_DOMAIN = {
    'POINT': "Point",
    'EDGE': "Edge",
    'FACE': "Face",
    'CORNER': "Corner",
}


def _ensure_collection(context):
    coll = bpy.data.collections.get(VIZ_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(VIZ_COLLECTION)
    if coll.name not in context.scene.collection.children:
        context.scene.collection.children.link(coll)
    return coll


def _prepare_viz_mesh(me):
    """Mark vizcol as the active Color Attribute for Workbench display."""
    name = node_builder.VIZCOL_ATTR
    if name not in me.color_attributes:
        # CORNER matches engine output (Face colors are not Color Attributes)
        me.color_attributes.new(name, 'FLOAT_COLOR', 'CORNER')
    try:
        me.color_attributes.active_color_name = name
    except Exception:
        pass
    try:
        me.color_attributes.default_color_name = name
    except Exception:
        pass


def _ensure_viz_display_shading(context):
    """Material Preview + emission viz mat (Workbench cannot color GN geo).

    Skipped when GPU Markers are on — Solid is the acceptance path.
    """
    scene = getattr(context, "scene", None)
    if scene is not None and getattr(scene, "attrviz_gpu_markers", False):
        return
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for space in area.spaces:
            if space.type != 'VIEW_3D':
                continue
            sh = space.shading
            sh.type = 'MATERIAL'
            # Prefer the emission color, not scene HDRI/lights
            try:
                sh.use_scene_lights = False
            except Exception:
                pass
            try:
                sh.use_scene_world = False
            except Exception:
                pass


def _viz_display_shading_ok(space):
    if space is None or space.type != 'VIEW_3D':
        return True
    scene = getattr(bpy.context, "scene", None)
    if scene is not None and getattr(scene, "attrviz_gpu_markers", False):
        return True  # Solid OK for GPU Markers
    return space.shading.type in ('MATERIAL', 'RENDERED')


def _set_viz_panel_category():
    """Apply Viz tab after the UI region has drawn (categories are runtime)."""
    wm = bpy.context.window_manager
    if wm is None:
        return None
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.show_region_ui = True
            for region in area.regions:
                if region.type != 'UI':
                    continue
                try:
                    region.tag_refresh_ui()
                except Exception:
                    pass
                try:
                    region.active_panel_category = VIZ_PANEL_CATEGORY
                except Exception:
                    pass
            area.tag_redraw()
    return None


def _reveal_viz_panel(context):
    """Open the N-panel and switch to the Viz tab (first visualizer UX)."""
    _ensure_viz_display_shading(context)
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for space in area.spaces:
            if space.type == 'VIEW_3D':
                space.show_region_ui = True
        for region in area.regions:
            if region.type == 'UI':
                try:
                    region.tag_refresh_ui()
                except Exception:
                    pass
        area.tag_redraw()
    # Categories exist only after a UI draw — set on the next tick.
    _set_viz_panel_category()
    try:
        bpy.app.timers.register(_set_viz_panel_category, first_interval=0.05)
    except Exception:
        pass
    try:
        bpy.app.timers.register(_set_viz_panel_category, first_interval=0.2)
    except Exception:
        pass


def is_visualizer(obj):
    return (obj is not None and obj.type == 'MESH'
            and any(md.type == 'NODES' and md.node_group is not None
                    and md.node_group.get("attrviz_version")
                    for md in obj.modifiers))


def visualizers(scene):
    coll = bpy.data.collections.get(VIZ_COLLECTION)
    if coll is None:
        return []
    return [o for o in coll.objects if is_visualizer(o)]


def viz_modifier(obj):
    for md in obj.modifiers:
        if (md.type == 'NODES' and md.node_group is not None
                and md.node_group.get("attrviz_version")):
            return md
    return None


def _migrate_visualizer(obj):
    """Rebuild engine group + display material when version drifts."""
    md = viz_modifier(obj)
    if md is None or md.node_group is None:
        return False
    ver = md.node_group.get("attrviz_version")
    if ver == node_builder.VERSION:
        return False
    # Preserve socket config (coerce for safe ID-prop restore)
    saved = {}
    for key in ("Target", "Scope", "Attribute", "Domain", "Style", "Display",
                "Attr Is Vector", "Scale", "Length", "Density", "Seed",
                "Arrow Color", "Auto Range", "Range Min", "Range Max",
                "Tag Cap", "Tag Size", "Tag Color", "Decimals", "Facing Cull"):
        try:
            saved[key] = node_builder._coerce_idprop_value(
                node_builder.get_input(md, key))
        except Exception:
            pass
    old = md.node_group
    grp = node_builder.ensure_viz_group(force=False).copy()
    grp.name = f"AttrViz · {obj.name}"
    md.node_group = grp
    # Point Set Material nodes at the shared display material
    mat = node_builder.ensure_viz_material(force=True)
    for node in grp.nodes:
        if node.bl_idname == "GeometryNodeSetMaterial":
            try:
                node.inputs["Material"].default_value = mat
            except Exception:
                pass
    for key, value in saved.items():
        if value is None and key in ("Target", "Scope"):
            continue
        # Tag Size became int in 0.5.3 (BLF pixel steps).
        if key == "Tag Size":
            try:
                value = int(round(float(value)))
            except Exception:
                value = 14
        try:
            node_builder.set_input(md, key, value)
        except Exception:
            pass
    _sync_attr_is_vector(md)
    if old is not None and old.users == 0:
        try:
            bpy.data.node_groups.remove(old)
        except Exception:
            pass
    return True


def _ensure_display_only_flags(obj):
    """Skip beauty-pass (hide_render) without killing Material Preview.

    ``visible_camera=False`` also blanks EEVEE / Material Preview — those
    paths use camera rays. Keep camera visibility; only hide_render.
    """
    obj.hide_render = True
    try:
        obj.hide_viewport = False
        obj.visible_camera = True
        obj.visible_shadow = False
    except Exception:
        pass


def migrate_all_visualizers(scene=None):
    scene = scene or bpy.context.scene
    n = 0
    try:
        node_builder.ensure_viz_material(force=False)
    except Exception:
        pass
    for obj in visualizers(scene):
        try:
            _ensure_display_only_flags(obj)
            if _migrate_visualizer(obj):
                n += 1
        except Exception:
            pass
    return n


def add_visualizer(context, target=None, scope=None,
                   attribute="position", domain="Point",
                   style="Heat", display="Markers", name=None):
    """Create one registry entry. domain/style/display take item NAMES."""
    coll = _ensure_collection(context)
    label = name or f"Viz · {domain} · {attribute}"
    me = bpy.data.meshes.new(label)
    _prepare_viz_mesh(me)
    obj = bpy.data.objects.new(label, me)
    coll.objects.link(obj)
    _ensure_display_only_flags(obj)
    md = obj.modifiers.new("AttrViz", 'NODES')
    grp = node_builder.ensure_viz_group().copy()
    grp.name = f"AttrViz · {label}"
    md.node_group = grp
    if target is not None:
        node_builder.set_input(md, "Target", target)
    if scope is not None:
        node_builder.set_input(md, "Scope", scope)
    node_builder.set_input(md, "Attribute", attribute)
    node_builder.set_input(md, "Domain", domain)
    node_builder.set_input(md, "Style", style)
    node_builder.set_input(md, "Display", display)
    _sync_attr_is_vector(md)
    _ensure_viz_display_shading(context)
    return obj


def auto_pick(domain, data_type, has_faces=False, attribute=None):
    """Domain-aware defaults for the RMB menu."""
    if data_type in VECTORISH:
        style = "RGB"
    elif data_type in CATEGORICAL:
        style = "Random"
    else:
        style = "Heat"
    if attribute == node_builder.NORMAL_ATTR:
        return style, "Arrows"
    if domain == "Edge":
        display = "Markers"
    elif domain == "Face":
        display = "Surface"
    elif domain == "Corner":
        display = "Markers"
    else:  # Point
        display = "Surface" if has_faces else "Markers"
    return style, display


def _dtype_label(data_type):
    """Short UI label for Blender attribute data_type enums."""
    return {
        'FLOAT': "float",
        'INT': "int",
        'BOOLEAN': "bool",
        'FLOAT_VECTOR': "vector",
        'FLOAT2': "vector2",
        'FLOAT_COLOR': "color",
        'BYTE_COLOR': "color",
        'QUATERNION': "quat",
        'FLOAT4X4': "matrix",
        'INT8': "int8",
        'STRING': "string",
    }.get(data_type, data_type.lower() if data_type else "?")


def evaluated_attributes(obj):
    """Evaluated GeometrySet attributes.
    Returns (sorted [(name, domain, data_type)], has_faces)."""
    if obj is None:
        return [], False
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        gs = ev.evaluated_geometry()
        infos = {}
        has_faces = False
        for comp in (getattr(gs, "mesh", None),
                     getattr(gs, "curves", None),
                     getattr(gs, "pointcloud", None)):
            if comp is None:
                continue
            if hasattr(comp, "polygons") and len(comp.polygons):
                has_faces = True
            for a in comp.attributes:
                if a.name.startswith("."):
                    continue
                # Prefer first-seen domain; same name on multiple domains
                # is rare — key by (name, domain).
                infos[(a.name, a.domain)] = a.data_type
        rows = sorted((n, d, t) for (n, d), t in infos.items())
        return rows, has_faces
    except Exception:
        return [], False


def _domain_has_elements(me, domain_ui):
    if me is None or not hasattr(me, "vertices"):
        return False
    if domain_ui == "Point":
        return len(me.vertices) > 0
    if domain_ui == "Edge":
        return len(me.edges) > 0
    if domain_ui == "Face":
        return len(me.polygons) > 0
    if domain_ui == "Corner":
        return len(me.loops) > 0
    return False


def attributes_by_domain(obj):
    """{DomainUI: [(name, data_type), ...], ...}, has_faces.

    Intrinsics (Index / Position / Normal) are prepended per domain —
    GN field sources, always current on evaluated topology.
    """
    rows, has_faces = evaluated_attributes(obj)
    by = {d: [] for d in node_builder.DOMAINS}
    for name, bdom, dtype in rows:
        if (name in node_builder.INTRINSIC_NAMES
                or name in node_builder.INTRINSIC_ALIASES):
            continue
        ui = _BLENDER_TO_DOMAIN.get(bdom)
        if ui is not None:
            by[ui].append((name, dtype))
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        me = getattr(ev, "data", None)
    except Exception:
        me = None
    for domain in node_builder.DOMAINS:
        if not _domain_has_elements(me, domain):
            continue
        intrinsics = []
        for name, dtype, domains in node_builder.INTRINSICS:
            if domain in domains:
                intrinsics.append((name, dtype))
        by[domain] = intrinsics + by[domain]
    return by, has_faces


def _target_attr_meta(md):
    """(data_type, domain_ui) for the watched attribute, best-effort."""
    try:
        target = node_builder.get_input(md, "Target")
        attr = node_builder.get_input(md, "Attribute")
        domain = node_builder.menu_input_name(md, "Domain")
    except Exception:
        return None, None
    if target is None or not attr:
        return None, domain
    dt = node_builder.intrinsic_dtype(attr)
    if dt is not None:
        return dt, domain
    by, _ = attributes_by_domain(target)
    for name, dtype in by.get(domain, []):
        if name == attr:
            return dtype, domain
    return None, domain


def _attr_available_on_domain(target, attr, domain):
    """True if attr is an intrinsic or authored attribute on domain."""
    if not attr or target is None or not domain:
        return False
    by, _ = attributes_by_domain(target)
    names = {n for n, _t in by.get(domain, [])}
    if attr in names:
        return True
    # lowercase position alias (engine accepts both)
    if attr == "position" and node_builder.POSITION_ATTR in names:
        return True
    return False


def _sync_attr_is_vector(md):
    """Keep engine Arrow path honest: non-vectors → direction (0,0,0)."""
    try:
        dtype, _domain = _target_attr_meta(md)
        is_vec = dtype in VECTORISH
        cur = node_builder.get_input(md, "Attr Is Vector")
        if bool(cur) != bool(is_vec):
            node_builder.set_input(md, "Attr Is Vector", bool(is_vec))
    except Exception:
        pass


# ── Object enums (get/set → modifier sockets) ───────────────────────

def _enum_get(socket, items):
    def getter(self):
        md = viz_modifier(self)
        if md is None:
            return 0
        name = node_builder.menu_input_name(md, socket)
        try:
            return items.index(name)
        except ValueError:
            return 0
    return getter


def _enum_set(socket, items):
    def setter(self, value):
        md = viz_modifier(self)
        if md is None:
            return
        value = max(0, min(int(value), len(items) - 1))
        node_builder.set_input(md, socket, items[value])
        if socket == "Domain":
            _sync_attr_is_vector(md)
        self.update_tag()
    return setter


_DOMAIN_ITEMS = [(d, d, "", i) for i, d in enumerate(node_builder.DOMAINS)]
_STYLE_ITEMS = [(s, s, "", i) for i, s in enumerate(node_builder.STYLES)]
_DISPLAY_ITEMS = [(d, d, "", i) for i, d in enumerate(node_builder.DISPLAYS)]


class ATTRVIZ_OT_add(bpy.types.Operator):
    bl_idname = "attrviz.add"
    bl_label = "Add Visualizer"
    bl_description = ("Create a visualizer on a domain-localized attribute")
    bl_options = {'REGISTER', 'UNDO'}

    attribute: bpy.props.StringProperty(name="Attribute",
                                        default="position")
    domain: bpy.props.EnumProperty(
        name="Domain", default="Point",
        items=[(d, d, "") for d in node_builder.DOMAINS])
    style: bpy.props.EnumProperty(
        name="Style", default="Heat",
        items=[(s, s, "") for s in node_builder.STYLES])
    display: bpy.props.EnumProperty(
        name="Display", default="Markers",
        items=[(d, d, "") for d in node_builder.DISPLAYS])

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and not is_visualizer(context.active_object))

    def execute(self, context):
        first = len(visualizers(context.scene)) == 0
        add_visualizer(context, target=context.active_object,
                       attribute=self.attribute, domain=self.domain,
                       style=self.style, display=self.display)
        if first:
            _reveal_viz_panel(context)
        return {'FINISHED'}


class ATTRVIZ_OT_remove(bpy.types.Operator):
    bl_idname = "attrviz.remove"
    bl_label = "Remove Visualizer"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.name)
        if obj is not None and is_visualizer(obj):
            bpy.data.objects.remove(obj, do_unlink=True)
        return {'FINISHED'}


class ATTRVIZ_OT_use_viz_display_shading(bpy.types.Operator):
    bl_idname = "attrviz.use_viz_display_shading"
    bl_label = "Use Material Preview (viz)"
    bl_description = (
        "Material Preview — required to see GN vizcol (emission display mat). "
        "Viz objects stay hide_render.")
    bl_options = {'INTERNAL'}

    def execute(self, context):
        _ensure_viz_display_shading(context)
        return {'FINISHED'}


def _draw_attr_op(layout, domain, aname, dtype, has_faces, intrinsic=False):
    style, display = auto_pick(domain, dtype, has_faces, attribute=aname)
    kind = "intrinsic" if intrinsic else _dtype_label(dtype)
    if intrinsic:
        label = (f"{aname}   {_dtype_label(dtype)} · intrinsic  →  "
                 f"{style} / {display}")
    else:
        label = (f"{aname}   {kind}  →  {style} / {display}")
    op = layout.operator(ATTRVIZ_OT_add.bl_idname, text=label)
    op.attribute = aname
    op.domain = domain
    op.style = style
    op.display = display


def _draw_domain_menu(layout, context, domain):
    by, has_faces = attributes_by_domain(context.active_object)
    attrs = by.get(domain, [])
    if not attrs:
        layout.label(text="(none)")
        return
    intrinsics = [(n, t) for n, t in attrs
                  if n in node_builder.INTRINSIC_NAMES]
    authored = [(n, t) for n, t in attrs
                if n not in node_builder.INTRINSIC_NAMES]
    if intrinsics:
        layout.label(text="Intrinsic")
        for aname, dtype in intrinsics:
            _draw_attr_op(layout, domain, aname, dtype, has_faces,
                          intrinsic=True)
    if authored:
        if intrinsics:
            layout.separator()
            layout.label(text="Attributes")
        for aname, dtype in authored:
            _draw_attr_op(layout, domain, aname, dtype, has_faces)


class ATTRVIZ_MT_domain_point(bpy.types.Menu):
    bl_idname = "ATTRVIZ_MT_domain_point"
    bl_label = "Point"

    def draw(self, context):
        _draw_domain_menu(self.layout, context, "Point")


class ATTRVIZ_MT_domain_edge(bpy.types.Menu):
    bl_idname = "ATTRVIZ_MT_domain_edge"
    bl_label = "Edge"

    def draw(self, context):
        _draw_domain_menu(self.layout, context, "Edge")


class ATTRVIZ_MT_domain_face(bpy.types.Menu):
    bl_idname = "ATTRVIZ_MT_domain_face"
    bl_label = "Face"

    def draw(self, context):
        _draw_domain_menu(self.layout, context, "Face")


class ATTRVIZ_MT_domain_corner(bpy.types.Menu):
    bl_idname = "ATTRVIZ_MT_domain_corner"
    bl_label = "Corner"

    def draw(self, context):
        _draw_domain_menu(self.layout, context, "Corner")


class ATTRVIZ_MT_visualize(bpy.types.Menu):
    bl_idname = "ATTRVIZ_MT_visualize"
    bl_label = "Visualize Attribute"

    def draw(self, context):
        layout = self.layout
        by, _ = attributes_by_domain(context.active_object)
        if not any(by.values()):
            layout.label(text="No attributes on evaluated geometry")
            return
        # Domain-first submenus; skip empty domains
        menus = (
            ("Point", ATTRVIZ_MT_domain_point.bl_idname),
            ("Edge", ATTRVIZ_MT_domain_edge.bl_idname),
            ("Face", ATTRVIZ_MT_domain_face.bl_idname),
            ("Corner", ATTRVIZ_MT_domain_corner.bl_idname),
        )
        for domain, menu_id in menus:
            if by.get(domain):
                layout.menu(menu_id, text=domain)


def _context_menu(self, context):
    if context.active_object is not None \
            and not is_visualizer(context.active_object):
        self.layout.separator()
        self.layout.menu(ATTRVIZ_MT_visualize.bl_idname,
                         icon='HIDE_OFF')


def _draw_socket(layout, md, name, text=None):
    for item in md.node_group.interface.items_tree:
        if (item.item_type == 'SOCKET' and item.in_out == 'INPUT'
                and item.name == name):
            data, prop = node_builder.input_rna_path(md, item.identifier)
            layout.prop(data, prop, text=text if text is not None else name)
            return True
    return False


class ATTRVIZ_PT_panel(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = VIZ_PANEL_CATEGORY
    bl_label = "Visualizers"

    def draw(self, context):
        layout = self.layout
        # Keep existing viz on the current engine + display material.
        migrate_all_visualizers(context.scene)
        vizzes = visualizers(context.scene)
        if not vizzes:
            layout.label(text="RMB → Visualize Attribute → Domain")
            layout.label(text="Viewport: Material Preview (emission viz)")
            return
        space = context.space_data
        gpu_on = bool(getattr(context.scene, "attrviz_gpu_markers", False))
        # Solid Attribute cannot color GN-only geometry (Blender limit).
        if not _viz_display_shading_ok(space):
            _ensure_viz_display_shading(context)
        row = layout.row(align=True)
        row.prop(context.scene, "attrviz_gpu_markers", text="GPU Overlay",
                 toggle=True)
        if gpu_on:
            row.label(text="Solid OK", icon='SHADING_SOLID')
        else:
            row.label(text="Material Preview", icon='SHADING_RENDERED')
            row.operator("attrviz.use_viz_display_shading", text="",
                         icon='FILE_REFRESH')

        # Flat list under one root column. Do not call layout.box()/split()
        # in a loop on ``layout`` — UILayout nests each child under the
        # previous and shoves headers/controls off the right edge.
        # Parent every header from ``root`` so they stay siblings; indent
        # only that header's controls.
        root = layout.column()
        for i, obj in enumerate(vizzes):
            if i:
                root.separator(factor=0.4)
            md = viz_modifier(obj)
            attr_name = ""
            domain = ""
            if md is not None:
                try:
                    attr_name = node_builder.get_input(md, "Attribute") or ""
                    domain = node_builder.menu_input_name(md, "Domain") or ""
                except Exception:
                    pass
            title = attr_name or obj.name
            if attr_name and domain:
                title = f"{attr_name}  ·  {domain}"

            head = root.row(align=True)
            head.prop(obj, "attrviz_ui_expand", text="", emboss=False,
                      icon=('TRIA_DOWN' if obj.attrviz_ui_expand
                            else 'TRIA_RIGHT'))
            head.label(text=title)
            try:
                head.separator_spacer()
            except Exception:
                head.separator()
            head.prop(obj, "attrviz_enabled", text="Enabled", toggle=True)
            op = head.operator(ATTRVIZ_OT_remove.bl_idname, text="",
                               icon='X')
            op.name = obj.name
            if md is None or not obj.attrviz_ui_expand:
                continue

            indent = root.row()
            split = indent.split(factor=0.03)
            split.separator()
            body = split.column()
            _draw_viz_body(body, obj, md, attr_name)


def _draw_viz_body(body, obj, md, attr_name):
    """Controls for one visualizer — parented under ``body`` only."""
    body.active = bool(obj.attrviz_enabled)

    # Domain localizes; Type / Color follow.
    body.prop(obj, "attrviz_domain", text="Domain", expand=True)
    _draw_socket(body, md, "Attribute")
    _sync_attr_is_vector(md)
    dtype, _ = _target_attr_meta(md)
    try:
        target = node_builder.get_input(md, "Target")
    except Exception:
        target = None
    domain = node_builder.menu_input_name(md, "Domain")
    if attr_name and target is not None \
            and not _attr_available_on_domain(target, attr_name, domain):
        body.label(
            text=f"“{attr_name}” is not on {domain} domain",
            icon='ERROR')
    elif node_builder.is_intrinsic(attr_name):
        body.label(
            text=f"{attr_name} = GN field (always current topology)")
    elif dtype:
        guess_s, guess_d = auto_pick(
            domain, dtype, has_faces=True, attribute=attr_name)
        body.label(
            text=(f"{_dtype_label(dtype)}  ·  default "
                  f"{guess_s} / {guess_d}"))
        if dtype in CATEGORICAL:
            body.label(
                text="IDs before Subdiv interpolate — use Index",
                icon='INFO')
    body.prop(obj, "attrviz_display", text="Type", expand=True)

    display = node_builder.menu_input_name(md, "Display")
    style = node_builder.menu_input_name(md, "Style")
    colored = display in ("Markers", "Surface")

    if display == "Arrows" and dtype not in VECTORISH:
        body.label(
            text="Non-vector → direction (0,0,0); no arrows",
            icon='ERROR')
    if display == "Surface" and domain == "Edge":
        body.label(text="Surface on Edge is weakly supported",
                   icon='INFO')

    if colored:
        body.prop(obj, "attrviz_style", text="Color", expand=True)
        if style == "RGB" and dtype not in VECTORISH:
            body.label(text="RGB expects a vector attribute",
                       icon='INFO')
        if style == "Random":
            body.label(text="Stable hash color per element id")
            _draw_socket(body, md, "Seed")
        if style == "Heat":
            ramp = next(
                (n for n in md.node_group.nodes
                 if n.bl_idname == 'ShaderNodeValToRGB'), None)
            if ramp is not None:
                body.template_color_ramp(ramp, "color_ramp",
                                         expand=False)
            col = body.column(align=True)
            _draw_socket(col, md, "Auto Range")
            sub = col.column(align=True)
            sub.active = not bool(
                node_builder.get_input(md, "Auto Range"))
            _draw_socket(sub, md, "Range Min")
            _draw_socket(sub, md, "Range Max")
    elif display == "Arrows":
        col = body.column(align=True)
        _draw_socket(col, md, "Arrow Color", text="Color")
        _draw_socket(col, md, "Length")
        _draw_socket(col, md, "Scale", text="Thickness")
        _draw_socket(col, md, "Density")
    elif display == "Tags":
        body.label(
            text="BLF tags: shared sampler, capped count; atlas later",
            icon='INFO')
        col = body.column(align=True)
        _draw_socket(col, md, "Tag Color", text="Color")
        _draw_socket(col, md, "Tag Size", text="Size (px)")
        _draw_socket(col, md, "Tag Cap", text="Cap")
        _draw_socket(col, md, "Decimals")
        _draw_socket(col, md, "Facing Cull")

    if display == "Markers":
        col = body.column(align=True)
        _draw_socket(col, md, "Scale")
        _draw_socket(col, md, "Density")


CLASSES = (
    ATTRVIZ_OT_add,
    ATTRVIZ_OT_remove,
    ATTRVIZ_OT_use_viz_display_shading,
    ATTRVIZ_MT_domain_point,
    ATTRVIZ_MT_domain_edge,
    ATTRVIZ_MT_domain_face,
    ATTRVIZ_MT_domain_corner,
    ATTRVIZ_MT_visualize,
    ATTRVIZ_PT_panel,
)


def _get_enabled(self):
    return not self.hide_viewport


def _set_enabled(self, value):
    enabled = bool(value)
    self.hide_viewport = not enabled
    md = viz_modifier(self)
    if md is not None:
        use_gpu = bool(getattr(bpy.context.scene, "attrviz_gpu_markers", False))
        display = None
        try:
            display = node_builder.menu_input_name(md, "Display")
        except Exception:
            pass
        # GPU overlay draws the ink; keep GN carrier hidden to avoid double draw.
        if enabled and use_gpu and display in ("Markers", "Surface", "Arrows"):
            md.show_viewport = False
        else:
            md.show_viewport = enabled
    if enabled:
        try:
            _ensure_viz_display_shading(bpy.context)
        except Exception:
            pass
    try:
        gpu_overlay.invalidate_all()
    except Exception:
        pass


def _sync_vizcol_active(scene, depsgraph):
    """Workbench Attribute shading needs active Color Attribute on eval mesh."""
    name = node_builder.VIZCOL_ATTR
    for obj in visualizers(scene):
        if obj.hide_viewport:
            continue
        md = viz_modifier(obj)
        try:
            # Arrows: also drive Object Color so tint shows even if Color=Object
            if md is not None and node_builder.menu_input_name(
                    md, "Display") == "Arrows":
                col = node_builder.get_input(md, "Arrow Color")
                if col is not None and len(col) >= 3:
                    obj.color = (float(col[0]), float(col[1]),
                                 float(col[2]),
                                 float(col[3]) if len(col) > 3 else 1.0)
        except Exception:
            pass
        try:
            ev = obj.evaluated_get(depsgraph)
            me = getattr(ev, "data", None)
            if me is None or not hasattr(me, "color_attributes"):
                continue
            if name not in me.color_attributes:
                continue
            if me.color_attributes.active_color_name != name:
                me.color_attributes.active_color_name = name
            if getattr(me.color_attributes, "default_color_name", None) != name:
                try:
                    me.color_attributes.default_color_name = name
                except Exception:
                    pass
        except Exception:
            pass


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    if _sync_vizcol_active not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_sync_vizcol_active)
    bpy.types.Object.attrviz_ui_expand = bpy.props.BoolProperty(
        name="Expand",
        description="Show visualizer settings (Enabled stays visible when collapsed)",
        default=True,
    )
    bpy.types.Object.attrviz_enabled = bpy.props.BoolProperty(
        name="Enabled",
        description=("Show this visualizer. Disable others to avoid "
                     "overlap — no compositing"),
        get=_get_enabled,
        set=_set_enabled,
        options={'SKIP_SAVE'},
    )
    bpy.types.Object.attrviz_domain = bpy.props.EnumProperty(
        name="Domain",
        description="Which elements the attribute is read/drawn on",
        items=_DOMAIN_ITEMS,
        get=_enum_get("Domain", node_builder.DOMAINS),
        set=_enum_set("Domain", node_builder.DOMAINS),
        options={'SKIP_SAVE'},
    )
    bpy.types.Object.attrviz_style = bpy.props.EnumProperty(
        name="Color",
        description="Heat / RGB / Random (hash id → solid color)",
        items=_STYLE_ITEMS,
        get=_enum_get("Style", node_builder.STYLES),
        set=_enum_set("Style", node_builder.STYLES),
        options={'SKIP_SAVE'},
    )
    bpy.types.Object.attrviz_display = bpy.props.EnumProperty(
        name="Type",
        description="Markers / Surface / Arrows / Tags",
        items=_DISPLAY_ITEMS,
        get=_enum_get("Display", node_builder.DISPLAYS),
        set=_enum_set("Display", node_builder.DISPLAYS),
        options={'SKIP_SAVE'},
    )
    bpy.types.VIEW3D_MT_object_context_menu.append(_context_menu)
    tags_draw.register()
    gpu_overlay.register()


def unregister():
    gpu_overlay.unregister()
    tags_draw.unregister()
    if _sync_vizcol_active in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_sync_vizcol_active)
    bpy.types.VIEW3D_MT_object_context_menu.remove(_context_menu)
    for attr in ("attrviz_ui_expand", "attrviz_enabled", "attrviz_domain",
                 "attrviz_style", "attrviz_display"):
        if hasattr(bpy.types.Object, attr):
            delattr(bpy.types.Object, attr)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
