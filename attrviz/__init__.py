"""AttrViz — first-class attribute visualizers for Blender.

Houdini's visualizer model on native constructs (POR 005):
- a visualizer is an ordinary OBJECT in the visible "Visualizers"
  collection — the outliner is the registry UI, the viewport EYE is
  the active toggle (a hidden visualizer evaluates nothing; the
  watched object is never re-cooked either way);
- its GN modifier is the engine: Object/Collection Info pulls the
  target's EVALUATED geometry through the depsgraph in C++ — no
  Python in the hot loop, timeline/simulation safe, zero mutation of
  watched objects;
- the modifier's sockets are the persisted parameters; the RMB menu
  and the N-panel "Viz" tab are views over them.
"""
import bpy

from . import node_builder

VIZ_COLLECTION = "Visualizers"


def _ensure_collection(context):
    coll = bpy.data.collections.get(VIZ_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(VIZ_COLLECTION)
    if coll.name not in context.scene.collection.children:
        context.scene.collection.children.link(coll)
    return coll


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


def add_visualizer(context, target=None, scope=None,
                   attribute="position", style="Heat",
                   display="Markers", name=None):
    """Create one registry entry: a visualizer object watching
    target/scope. Object sockets are wired BEFORE first eval (the 5.2
    object-socket gotcha). style/display take enum item NAMES."""
    coll = _ensure_collection(context)
    label = name or f"Viz · {attribute}"
    obj = bpy.data.objects.new(label, bpy.data.meshes.new(label))
    coll.objects.link(obj)
    obj.hide_render = True          # inspection by default; flip for docs
    md = obj.modifiers.new("AttrViz", 'NODES')
    # per-visualizer engine COPY (the Shadow-Ramp pattern): the Heat
    # Ramp inside is then editable per visualizer, not shared
    grp = node_builder.ensure_viz_group().copy()
    grp.name = f"AttrViz · {label}"
    md.node_group = grp
    if target is not None:
        node_builder.set_input(md, "Target", target)
    if scope is not None:
        node_builder.set_input(md, "Scope", scope)
    node_builder.set_input(md, "Attribute", attribute)
    node_builder.set_input(md, "Style", style)
    node_builder.set_input(md, "Display", display)
    return obj


VECTORISH = {'FLOAT_VECTOR', 'FLOAT2'}


def auto_pick(data_type, has_faces):
    """The Houdini reflex, pinned: how an attribute should visualize
    when the user hasn't said otherwise."""
    style = "RGB" if data_type in VECTORISH else "Heat"
    display = "Surface" if has_faces else "Markers"
    return style, display


def evaluated_attributes(obj):
    """The RMB menu's source of truth: the EVALUATED GeometrySet —
    GN-made attributes never exist on the original datablock.
    Returns (sorted [(name, domain, data_type)], has_faces)."""
    if obj is None:
        return [], False
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        gs = ev.evaluated_geometry()    # hold — GC gotcha
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
                infos.setdefault(a.name, (a.domain, a.data_type))
        return ([(n, d, t) for n, (d, t) in sorted(infos.items())],
                has_faces)
    except Exception:
        return [], False


class ATTRVIZ_OT_add(bpy.types.Operator):
    bl_idname = "attrviz.add"
    bl_label = "Add Visualizer"
    bl_description = ("Create a visualizer object watching the active "
                      "object's named attribute (toggle it with the "
                      "outliner eye)")
    bl_options = {'REGISTER', 'UNDO'}

    attribute: bpy.props.StringProperty(name="Attribute",
                                        default="position")
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
        add_visualizer(context, target=context.active_object,
                       attribute=self.attribute, style=self.style,
                       display=self.display)
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


class ATTRVIZ_MT_visualize(bpy.types.Menu):
    bl_idname = "ATTRVIZ_MT_visualize"
    bl_label = "Visualize Attribute"

    def draw(self, context):
        layout = self.layout
        infos, has_faces = evaluated_attributes(context.active_object)
        if not infos:
            layout.label(text="No attributes on evaluated geometry")
            return
        for aname, _domain, dtype in infos:
            style, display = auto_pick(dtype, has_faces)
            op = layout.operator(ATTRVIZ_OT_add.bl_idname, text=aname)
            op.attribute = aname
            op.style = style
            op.display = display


def _context_menu(self, context):
    if context.active_object is not None \
            and not is_visualizer(context.active_object):
        self.layout.separator()
        self.layout.menu(ATTRVIZ_MT_visualize.bl_idname,
                         icon='HIDE_OFF')


class ATTRVIZ_PT_panel(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Viz"
    bl_label = "Visualizers"

    def draw(self, context):
        layout = self.layout
        vizzes = visualizers(context.scene)
        if not vizzes:
            layout.label(text="RMB an object → Visualize Attribute")
            return
        for obj in vizzes:
            md = viz_modifier(obj)
            box = layout.box()
            row = box.row(align=True)
            row.prop(obj, "hide_viewport", text="", emboss=False)
            row.label(text=obj.name)
            op = row.operator(ATTRVIZ_OT_remove.bl_idname, text="",
                              icon='X')
            op.name = obj.name
            if md is not None:
                ramp = next(
                    (n for n in md.node_group.nodes
                     if n.bl_idname == 'ShaderNodeValToRGB'), None)
                if ramp is not None:
                    box.template_color_ramp(ramp, "color_ramp",
                                            expand=False)
                col = box.column(align=True)
                for sock in ("Attribute", "Style", "Display",
                             "Auto Range", "Range Min", "Range Max",
                             "Density", "Scale"):
                    for item in md.node_group.interface.items_tree:
                        if (item.item_type == 'SOCKET'
                                and item.in_out == 'INPUT'
                                and item.name == sock):
                            col.prop(
                                getattr(md.properties.inputs,
                                        item.identifier),
                                "value", text=sock)
                            break


CLASSES = (
    ATTRVIZ_OT_add,
    ATTRVIZ_OT_remove,
    ATTRVIZ_MT_visualize,
    ATTRVIZ_PT_panel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_object_context_menu.append(_context_menu)


def unregister():
    bpy.types.VIEW3D_MT_object_context_menu.remove(_context_menu)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
