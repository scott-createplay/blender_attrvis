"""AttrViz — first-class attribute visualizers for Blender.

Houdini's visualizer model on native constructs (POR 005):
- a visualizer is an ordinary OBJECT in the visible "Visualizers"
  collection — the outliner is the registry UI; Enabled / viewport
  eye toggles draw (no compositing of overlapping viz);
- Domain localizes the read (Point / Edge / Face / Corner);
- ColorRamp maps the value (Heat / RGB / BnW presets); Type chooses carriers
  (Markers / Surface / Arrows);
- GN pulls evaluated geometry through the depsgraph — zero mutation;
- Display-only: emission material reads vizcol (Workbench cannot color
  GN-only geometry). Viz objects use hide_render (skip F12) but keep
  visible_camera so Material Preview can see them.
"""
import bpy

from bpy.app.handlers import persistent

from . import node_builder
from . import tags_draw
from . import gpu_overlay
from . import gpu_sample
from . import gpu_color

VIZ_COLLECTION = "Visualizers"
WATCH_COLLECTION = gpu_sample.WATCH_COLLECTION
VIZ_PANEL_CATEGORY = "Viz"
_WATCH_NAME_CAP = 8
VECTORISH = {'FLOAT_VECTOR', 'FLOAT2'}
CATEGORICAL = {'INT', 'BOOLEAN', 'INT8', 'INT16_2D', 'INT32_2D'}

# Blender attribute domain → UI Domain name
_BLENDER_TO_DOMAIN = {
    'POINT': "Point",
    'EDGE': "Edge",
    'FACE': "Face",
    'CORNER': "Corner",
    'INSTANCE': "Instance",
}

# UI-level domain list. node_builder.DOMAINS stays FOUR — it drives the GN
# tree (Normal bake loop, DOMAIN_TO_BLENDER, Separate Components) and
# appending to it breaks the tree builder. Instance is GPU-overlay-only.
UI_DOMAINS = node_builder.UI_DOMAINS

# Instance-domain internals that are not user data. `.reference_index` is
# already dropped by the leading-dot rule. `id` is deliberately NOT hidden —
# it is an INT, so the 005 hash path gives per-instance categorical colour.
INSTANCE_HIDDEN = frozenset({"instance_transform"})


def _geom_has_any(geom):
    """True if this component has any element at all."""
    if geom is None:
        return False
    try:
        if hasattr(geom, "vertices"):
            return len(geom.vertices) > 0
        return geom.attributes.domain_size('POINT') > 0
    except Exception:
        return False


def _ensure_collection(context):
    coll = bpy.data.collections.get(VIZ_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(VIZ_COLLECTION)
    if coll.name not in context.scene.collection.children:
        context.scene.collection.children.link(coll)
    return coll


def _ensure_watch_collection(context):
    """Scene-level watch set. Distinct from the Visualizers registry."""
    coll = bpy.data.collections.get(WATCH_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(WATCH_COLLECTION)
    if coll.name not in context.scene.collection.children:
        context.scene.collection.children.link(coll)
    return coll


def migrate_viz_scope(context=None):
    """Backfill ``attrvis`` into visualizers that watch nothing (011 Phase 1).

    Before 011 the scene ``attrvis`` collection shadowed every visualizer's own
    Scope socket, so a visualizer with both sockets unset still sampled the
    watch set. Now that the shadow is gone, such a visualizer would silently
    draw nothing. Give it the default scope.

    Only touches visualizers with **both** Target and Scope unset. A visualizer
    with an explicit Target keeps sampling exactly that -- broadening it to
    Target u attrvis would be wider than either the old or the new behaviour.

    Idempotent by construction: once Scope is set the visualizer no longer
    matches, so this needs no version stamp and is safe to call on every load.
    Returns the number of visualizers repointed.
    """
    ctx = context or bpy.context
    scene = getattr(ctx, "scene", None) or bpy.context.scene
    if scene is None:
        return 0
    coll = bpy.data.collections.get(WATCH_COLLECTION)
    if coll is None:
        return 0
    n = 0
    for obj in visualizers(scene):
        md = viz_modifier(obj)
        if md is None:
            continue
        try:
            if node_builder.get_input(md, "Scope") is not None:
                continue
            if node_builder.get_input(md, "Target") is not None:
                continue
            node_builder.set_input(md, "Scope", coll)
        except Exception:
            continue
        n += 1
    if n:
        print(f"AttrViz: repointed {n} visualizer(s) with no watch set "
              f"to the default {WATCH_COLLECTION!r} collection")
    return n


def _watch_candidates(context):
    """Selected ∪ active MESH / POINTCLOUD objects, excluding viz carriers."""
    seen = set()
    out = []
    objs = list(getattr(context, "selected_objects", None) or [])
    active = getattr(context, "active_object", None)
    if active is not None and active not in objs:
        objs.append(active)
    for obj in objs:
        if obj is None or obj.type not in gpu_sample.WATCH_TYPES or is_visualizer(obj):
            continue
        key = obj.as_pointer()
        if key in seen:
            continue
        seen.add(key)
        out.append(obj)
    return out


def _sync_watch_draw(context=None):
    """Watch-set or viz-set changed: caches, Surface mute, viewport redraw.

    Call from Add/Remove objects and after removing a visualizer. Overlay
    fingerprint would eventually miss, but mute must run *now* or new
    Surface targets stay Solid and z-fight.
    """
    ctx = context or bpy.context
    scene = getattr(ctx, "scene", None) or bpy.context.scene
    try:
        gpu_overlay.invalidate_all()
    except Exception:
        pass
    try:
        tags_draw.invalidate_cache()
    except Exception:
        pass
    try:
        gpu_overlay.suppress_gn_carriers(scene)
    except Exception:
        pass
    try:
        screen = getattr(ctx, "screen", None)
        if screen is not None:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:
        pass


def active_scope(context=None, create=False):
    """The collection new actions target (011 D3).

    Falls back to ``attrvis``, creating it only when ``create`` is set: a file
    with no attrvis is a legal state (D2a), so a read must not manufacture one.

    There is no dangling-pointer case to handle. Blender nulls an ID pointer
    when its target is deleted -- verified by discovery spike S6 -- so a stale
    active scope simply reads as None and falls through.
    """
    ctx = context or bpy.context
    scene = getattr(ctx, "scene", None) or bpy.context.scene
    if scene is None:
        return None
    coll = getattr(scene, "attrviz_active_scope", None)
    if coll is not None:
        return coll
    if create:
        coll = _ensure_watch_collection(ctx)
        try:
            scene.attrviz_active_scope = coll
        except Exception:
            pass
        return coll
    return bpy.data.collections.get(WATCH_COLLECTION)


def set_active_scope(context, coll):
    """Point new actions at ``coll``. Presentational plus targeting only --
    never enables, disables or mutes anything (D9)."""
    ctx = context or bpy.context
    scene = getattr(ctx, "scene", None) or bpy.context.scene
    if scene is None:
        return None
    scene.attrviz_active_scope = coll
    return coll


def scope_collections(scene=None):
    """Collections AttrViz knows about, discovered by USE not by name (D8).

    ``attrvis`` plus every collection currently referenced by some visualizer's
    Scope. No naming convention is imposed: scoping a visualizer to an existing
    ``Buildings`` collection is legal and it shows up here.

    Guarantees every visualizer is reachable from exactly one entry, except one
    with no Scope at all -- those belong to ``attrvis`` in the UI (D9).
    """
    scene = scene or bpy.context.scene
    out = []
    seen = set()

    def add(coll):
        if coll is None or coll.name in seen:
            return
        seen.add(coll.name)
        out.append(coll)

    add(bpy.data.collections.get(WATCH_COLLECTION))
    if scene is not None:
        for obj in visualizers(scene):
            md = viz_modifier(obj)
            if md is None:
                continue
            try:
                add(node_builder.get_input(md, "Scope"))
            except Exception:
                continue
    return out


def viz_scope(md):
    """The collection a visualizer belongs to in the UI. None Scope -> attrvis
    so nothing is ever orphaned from the panel (D9)."""
    try:
        coll = node_builder.get_input(md, "Scope")
    except Exception:
        coll = None
    if coll is not None:
        return coll
    return bpy.data.collections.get(WATCH_COLLECTION)


def collection_parent(coll):
    """The collection that holds ``coll`` as a child, or None.

    AttrViz never creates nested scopes (D2), but the user may nest by hand,
    and iter_watch_meshes recurses -- so inheritance must be shown, never
    silent. A panel count that disagrees with what is drawn is the 010 bug.
    """
    if coll is None:
        return None
    for cand in bpy.data.collections:
        if cand is coll:
            continue
        try:
            if coll.name in cand.children:
                return cand
        except Exception:
            continue
    return None


def new_scope_collection(context, name=None):
    """Create a scope collection as a SIBLING under the scene collection.

    Never a child of the active scope. Nesting means inheritance -- because
    iter_watch_meshes recurses -- so a nested "split out" would not actually
    split anything: a visualizer scoped to the parent would still cover the
    objects the user just separated. Topology stays flat unless the user nests
    by hand in the outliner (011 D2).
    """
    ctx = context or bpy.context
    scene = getattr(ctx, "scene", None) or bpy.context.scene
    base = (name or "").strip() or f"{WATCH_COLLECTION}_group"
    coll = bpy.data.collections.new(base)
    scene.collection.children.link(coll)
    return coll


def move_to_scope(context, objects, coll, source=None):
    """MOVE objects into ``coll``, out of ``source`` (default: active scope).

    Migrate means move, not link (011 D4). Leaving them in the old collection
    would keep the old visualizers covering them, which is the thing the user
    is trying to stop.

    Only the source scope is unlinked -- never the user's own scene
    organisation. Link first, unlink second, so an object is never momentarily
    homeless.
    """
    ctx = context or bpy.context
    if source is None:
        source = active_scope(ctx)
    moved = 0
    for obj in objects:
        if obj is None:
            continue
        if coll not in obj.users_collection:
            coll.objects.link(obj)
        if (source is not None and source is not coll
                and source in obj.users_collection):
            source.objects.unlink(obj)
        moved += 1
    _sync_watch_draw(ctx)
    return moved


def _link_to_watch(context, objects, coll=None):
    """Link objects into ``coll``, defaulting to the active scope (D3)."""
    if coll is None:
        coll = active_scope(context, create=True)
    for obj in objects:
        if obj is None:
            continue
        if coll not in obj.users_collection:
            coll.objects.link(obj)
    _sync_watch_draw(context)
    return coll


def _unlink_from_watch(context, objects, coll=None):
    """Unlink objects from ``coll``, defaulting to the active scope (D3)."""
    if coll is None:
        coll = active_scope(context)
    if coll is None:
        return None
    scene_coll = context.scene.collection
    for obj in objects:
        if obj is None or coll not in obj.users_collection:
            continue
        # Unlink from attrvis only — never delete. Keep a scene link if
        # attrvis was the last collection so the object does not vanish.
        if (len(obj.users_collection) == 1
                and scene_coll not in obj.users_collection):
            scene_coll.objects.link(obj)
        coll.objects.unlink(obj)
    _sync_watch_draw(context)
    return coll


def add_visualizer_from_selection(context, **kwargs):
    """GUI add-viz: link selection into attrvis, Scope = that collection."""
    objs = _watch_candidates(context)
    coll = _link_to_watch(context, objs)   # active scope, attrvis by default
    kwargs.setdefault("target", None)
    kwargs.setdefault("scope", coll)
    return add_visualizer(context, **kwargs)


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
    if scene is not None and getattr(scene, "attrviz_gpu_markers", True):
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
    if scene is not None and getattr(scene, "attrviz_gpu_markers", True):
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
    """Public alias -- the implementation lives in gpu_sample (011 Phase 2),
    because is_watchable needs it and cannot import this package."""
    return gpu_sample.is_visualizer(obj)


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


def _gpu_overlay_on(scene=None):
    """True when GPU Overlay (default display path) is enabled."""
    scene = scene or bpy.context.scene
    return bool(getattr(scene, "attrviz_gpu_markers", True))


def _assign_viz_engine(md, label, scene=None):
    """Bind AttrViz engine tree to a Nodes modifier.

    GPU Overlay on (default): share one ``ensure_viz_group()`` datablock —
    config lives on modifier sockets, not a per-viz deep copy. Heat
    ColorRamp lives off-engine via ``ensure_viz_ramp`` (task 003).

    GPU Overlay off: keep an isolated ``.copy()`` so materials-path Heat
    ColorRamp stays per-viz until that path is wired to the off-engine ramp.
    """
    engine = node_builder.ensure_viz_group(force=False)
    if _gpu_overlay_on(scene):
        md.node_group = engine
        return engine
    grp = engine.copy()
    grp.name = f"AttrViz · {label}"
    md.node_group = grp
    return grp


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
    shared = _gpu_overlay_on()
    grp = _assign_viz_engine(md, obj.name)
    # Point Set Material nodes at the shared display material.
    # Only safe to retarget nodes on an isolated (copied) tree.
    if not shared:
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
            node_builder.ensure_viz_ramp(obj)
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
    _assign_viz_engine(md, label, scene=context.scene)
    node_builder.ensure_viz_ramp(obj)
    # GPU Overlay is the default draw path — suppress GN before wiring
    # Target so create does not evaluate the engine graph.
    if display in ("Markers", "Surface", "Arrows"):
        _suppress_new_viz_carrier(md, scene=context.scene)
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
    # Open this viz's layout panel (accordion closes others).
    try:
        obj.attrviz_ui_expand = True
    except Exception:
        pass
    try:
        gpu_overlay.suppress_gn_carriers(context.scene)
        gpu_overlay.invalidate(obj)
    except Exception:
        pass
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
        # Instances: a GN tree ending in Instance on Points with no Realize
        # has ZERO mesh elements and all its attributes on the instance
        # domain. The component is a PointCloud whose attributes self-report
        # POINT, so retag as INSTANCE — the UI domain is a presentation layer
        # over it, never a rewrite of what Blender reports.
        inst = gpu_sample.instances_cloud(gs)
        if inst is not None:
            for a in inst.attributes:
                if a.name.startswith(".") or a.name in INSTANCE_HIDDEN:
                    continue
                infos[(a.name, 'INSTANCE')] = a.data_type
        rows = sorted((n, d, t) for (n, d), t in infos.items())
        return rows, has_faces
    except Exception:
        return [], False


def _domain_has_elements(geom, domain_ui, inst=None):
    """Does this domain have anything to sample?

    ``inst`` is the evaluated instances cloud, which lives beside ``geom``
    rather than inside it — an object can legitimately offer Point (its mesh)
    and Instance (its instances) at once.
    """
    if domain_ui == "Instance":
        return inst is not None and len(inst.points) > 0
    if geom is None:
        return False
    if hasattr(geom, "vertices"):
        if domain_ui == "Point":
            return len(geom.vertices) > 0
        if domain_ui == "Edge":
            return len(geom.edges) > 0
        if domain_ui == "Face":
            return len(geom.polygons) > 0
        if domain_ui == "Corner":
            return len(geom.loops) > 0
        return False
    if domain_ui != "Point":
        return False
    try:
        return geom.attributes.domain_size('POINT') > 0
    except Exception:
        pts = getattr(geom, "points", None)
        return pts is not None and len(pts) > 0


def attributes_by_domain(obj):
    """{DomainUI: [(name, data_type), ...], ...}, has_faces.

    Intrinsics (Index / Position / Normal) are prepended per domain —
    GN field sources, always current on evaluated topology.
    """
    rows, has_faces = evaluated_attributes(obj)
    by = {d: [] for d in node_builder.UI_DOMAINS}
    for name, bdom, dtype in rows:
        if (name in node_builder.INTRINSIC_NAMES
                or name in node_builder.INTRINSIC_ALIASES):
            continue
        ui = _BLENDER_TO_DOMAIN.get(bdom)
        if ui is not None:
            by[ui].append((name, dtype))
    # Source from the evaluated GEOMETRY SET, not ev.data. A GN object whose
    # top-level mesh is empty (everything is instances, or the tree outputs a
    # cloud) has a valid ev.data with zero elements, which used to suppress
    # even Index / Position — a bug wider than instances.
    me = None
    inst = None
    gs = None
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        gs = ev.evaluated_geometry()          # hold — GC gotcha
        me = getattr(gs, "mesh", None)
        if not _geom_has_any(me):
            me = getattr(gs, "pointcloud", None) or getattr(ev, "data", None)
        inst = gpu_sample.instances_cloud(gs)
    except Exception:
        if me is None:
            try:
                me = getattr(obj.evaluated_get(
                    bpy.context.evaluated_depsgraph_get()), "data", None)
            except Exception:
                me = None
    for domain in node_builder.UI_DOMAINS:
        if not _domain_has_elements(me, domain, inst):
            continue
        intrinsics = []
        for name, dtype, domains in node_builder.INTRINSICS:
            if domain not in domains and domain != "Instance":
                continue
            # Instances have no normal, and neither do point clouds — do not
            # invent one (006 precedent).
            if name == node_builder.NORMAL_ATTR:
                if domain == "Instance" or not hasattr(me, "vertices"):
                    continue
            if domain == "Instance" and name not in (
                    node_builder.INDEX_ATTR, node_builder.POSITION_ATTR):
                continue
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
    if not attr:
        return None, domain
    if target is None:
        try:
            meshes = gpu_sample.watch_meshes_for_visualizer(md)
            target = meshes[0] if meshes else None
        except Exception:
            target = None
    if target is None:
        return None, domain
    dt = node_builder.intrinsic_dtype(attr)
    if dt is not None:
        return dt, domain
    # Fast path: authored attribute on the original mesh (no depsgraph).
    # Avoids evaluating the viz GN tree just to flip Attr Is Vector.
    me = getattr(target, "data", None)
    if me is not None and hasattr(me, "attributes"):
        a = me.attributes.get(attr)
        if a is not None:
            return a.data_type, domain
    # Fallback: evaluated geometry (modifier-generated attrs).
    by, _ = attributes_by_domain(target)
    for name, dtype in by.get(domain, []):
        if name == attr:
            return dtype, domain
    return None, domain


def _attr_available_on_domain(target, attr, domain):
    """True if attr is an intrinsic or authored attribute on domain."""
    if not attr or target is None or not domain:
        return False
    if node_builder.is_intrinsic(attr) or attr == "position":
        return True
    # Fast path: original mesh (no GeometrySet eval — that is ~300ms on
    # DistLook signs and ran from the Viz panel every redraw).
    me = getattr(target, "data", None)
    if me is not None and hasattr(me, "attributes"):
        a = me.attributes.get(attr)
        if a is not None:
            ui = _BLENDER_TO_DOMAIN.get(a.domain)
            if ui is None or ui == domain:
                return True
            return False
    by, _ = attributes_by_domain(target)
    names = {n for n, _t in by.get(domain, [])}
    if attr in names:
        return True
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


def _suppress_new_viz_carrier(md, scene=None):
    """Hide GN carrier immediately on create when GPU Overlay draws ink.

    Must run before Target/Scope sockets are set — otherwise the first
    depsgraph touch evaluates the full AttrViz engine on the watched mesh
    (hundreds of ms … tens of seconds on heavy scenes).
    """
    if not _gpu_overlay_on(scene):
        return
    try:
        if md.show_viewport:
            md.show_viewport = False
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
        # Cache key includes Domain/Style/Display; next draw rebuilds on miss.
        # Display also switches GN carrier visibility (never from draw handler).
        if socket == "Display":
            try:
                gpu_overlay.suppress_gn_carriers(bpy.context.scene)
            except Exception:
                pass
        self.update_tag()
    return setter


# UI_DOMAINS, not DOMAINS: the enum must accept every domain the RMB menu
# can offer, or assigning op.domain = "Instance" raises mid-draw and the
# menu silently truncates at whatever was drawn before it.
_DOMAIN_ITEMS = [(d, d, "", i)
                 for i, d in enumerate(node_builder.UI_DOMAINS)]
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
        items=[(d, d, "") for d in node_builder.UI_DOMAINS])
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
        add_visualizer_from_selection(
            context, attribute=self.attribute, domain=self.domain,
            style=self.style, display=self.display)
        if first:
            _reveal_viz_panel(context)
        return {'FINISHED'}


class ATTRVIZ_OT_watch_add(bpy.types.Operator):
    bl_idname = "attrviz.watch_add"
    bl_label = "Add objects"
    bl_description = "Add selected objects to the attrvis watch collection"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(_watch_candidates(context))

    def execute(self, context):
        objs = _watch_candidates(context)
        coll = _link_to_watch(context, objs)
        name = coll.name if coll is not None else WATCH_COLLECTION
        self.report({'INFO'}, f"Added {len(objs)} to {name}")
        return {'FINISHED'}


class ATTRVIZ_OT_watch_remove(bpy.types.Operator):
    bl_idname = "attrviz.watch_remove"
    bl_label = "Remove objects"
    bl_description = (
        "Remove selected objects from attrvis (does not delete them)")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        coll = bpy.data.collections.get(WATCH_COLLECTION)
        if coll is None:
            return False
        return any(coll in o.users_collection
                   for o in _watch_candidates(context))

    def execute(self, context):
        coll = bpy.data.collections.get(WATCH_COLLECTION)
        objs = [o for o in _watch_candidates(context)
                if coll is not None and coll in o.users_collection]
        _unlink_from_watch(context, objs)
        self.report({'INFO'}, f"Removed {len(objs)} from attrvis")
        return {'FINISHED'}


class ATTRVIZ_OT_remove(bpy.types.Operator):
    bl_idname = "attrviz.remove"
    bl_label = "Remove Visualizer"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.name)
        if obj is not None and is_visualizer(obj):
            node_builder.release_viz_ramp(obj)
            bpy.data.objects.remove(obj, do_unlink=True)
        _sync_watch_draw(context)
        return {'FINISHED'}


class ATTRVIZ_OT_ramp_preset(bpy.types.Operator):
    bl_idname = "attrviz.ramp_preset"
    bl_label = "Ramp Preset"
    bl_description = (
        "Fill this visualizer's ColorRamp with Heat, RGB, or monochrome "
        "(BnW) stops. The ramp stays editable."
    )
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty()
    preset: bpy.props.StringProperty(default="heat")

    @classmethod
    def poll(cls, context):
        return _gpu_overlay_on(getattr(context, "scene", None))

    def execute(self, context):
        obj = bpy.data.objects.get(self.name)
        if obj is None or not is_visualizer(obj):
            return {'CANCELLED'}
        try:
            node = node_builder.ensure_viz_ramp(obj)
            node_builder.apply_ramp_preset(node, self.preset)
        except Exception as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        try:
            gpu_overlay._tag_view3d_redraw()
        except Exception:
            pass
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


class ATTRVIZ_MT_domain_instance(bpy.types.Menu):
    bl_idname = "ATTRVIZ_MT_domain_instance"
    bl_label = "Instance"

    def draw(self, context):
        _draw_domain_menu(self.layout, context, "Instance")


class ATTRVIZ_MT_domain_corner(bpy.types.Menu):
    bl_idname = "ATTRVIZ_MT_domain_corner"
    bl_label = "Corner"

    def draw(self, context):
        _draw_domain_menu(self.layout, context, "Corner")


class ATTRVIZ_MT_visualize(bpy.types.Menu):
    bl_idname = "ATTRVIZ_MT_visualize"
    bl_label = "Visualize Attribute"

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and not is_visualizer(context.active_object))

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
            ("Instance", ATTRVIZ_MT_domain_instance.bl_idname),
        )
        for domain, menu_id in menus:
            if by.get(domain):
                layout.menu(menu_id, text=domain)
        # Un-realized instances: the mesh domains are genuinely empty, and
        # that is the correct Blender/Houdini semantic — element data of the
        # instanced geometry needs Realize Instances (Houdini's unpack). Say
        # so rather than silently offering four missing domains, and rather
        # than faking an unpack in the overlay: the prototype's points are
        # not this object's points.
        if by.get(node_builder.INSTANCE_DOMAIN) and not any(
                by.get(d) for d in node_builder.DOMAINS):
            layout.separator()
            col = layout.column()
            col.enabled = False
            col.label(text="Point / Edge / Face / Corner: no elements")
            col.label(text="Geometry is instanced — add Realize Instances")
            col.label(text="to unpack, or read it on Instance.")


class ATTRVIZ_OT_set_active_scope(bpy.types.Operator):
    bl_idname = "attrviz.set_active_scope"
    bl_label = "Set Active Scope"
    bl_description = ("Point Add/Remove objects and new visualizers at this "
                      "collection. Does not change what is drawn")
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty()

    def execute(self, context):
        coll = bpy.data.collections.get(self.name)
        if coll is None:
            self.report({'WARNING'}, f"No collection named {self.name!r}")
            return {'CANCELLED'}
        set_active_scope(context, coll)
        # Targeting only -- never touches enable state or mute (011 D9).
        try:
            gpu_overlay._tag_view3d_redraw()
        except Exception:
            pass
        return {'FINISHED'}


class ATTRVIZ_OT_scope_new(bpy.types.Operator):
    bl_idname = "attrviz.scope_new"
    bl_label = "New collection from selection"
    bl_description = ("Move the selected objects into a new scope collection "
                      "and make it active")
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty(
        name="Name",
        description="Name for the new scope collection",
        default="attrvis_group",
    )

    @classmethod
    def poll(cls, context):
        return bool(_watch_candidates(context))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        objs = _watch_candidates(context)
        if not objs:
            self.report({'WARNING'}, "No watchable objects selected")
            return {'CANCELLED'}
        coll = new_scope_collection(context, self.name)
        n = move_to_scope(context, objs, coll)
        set_active_scope(context, coll)
        self.report({'INFO'}, f"Moved {n} to {coll.name}")
        return {'FINISHED'}


class ATTRVIZ_MT_scope(bpy.types.Menu):
    bl_idname = "ATTRVIZ_MT_scope"
    bl_label = "Active Scope"

    def draw(self, context):
        layout = self.layout
        active = active_scope(context)
        colls = scope_collections(context.scene)
        if not colls:
            layout.label(text="none yet - Add objects creates attrvis")
            return
        for coll in colls:
            n = len(gpu_sample.iter_watch_meshes(None, coll))
            noun = "object" if n == 1 else "objects"
            op = layout.operator(
                ATTRVIZ_OT_set_active_scope.bl_idname,
                text=f"{coll.name}    ({n} {noun})",
                icon='RADIOBUT_ON' if coll == active else 'RADIOBUT_OFF')
            op.name = coll.name
        layout.separator()
        layout.operator(ATTRVIZ_OT_scope_new.bl_idname,
                        icon='COLLECTION_NEW')


class ATTRVIZ_MT_edit(bpy.types.Menu):
    bl_idname = "ATTRVIZ_MT_edit"
    bl_label = "Edit"

    def draw(self, context):
        layout = self.layout
        layout.operator(ATTRVIZ_OT_watch_add.bl_idname, icon='ADD')
        layout.operator(ATTRVIZ_OT_watch_remove.bl_idname, icon='REMOVE')
        layout.separator()
        layout.operator(ATTRVIZ_OT_scope_new.bl_idname,
                        icon='OUTLINER_COLLECTION')


class ATTRVIZ_MT_root(bpy.types.Menu):
    bl_idname = "ATTRVIZ_MT_root"
    bl_label = "AttrViz"

    def draw(self, context):
        layout = self.layout
        layout.menu(ATTRVIZ_MT_visualize.bl_idname, icon='HIDE_OFF')
        layout.menu(ATTRVIZ_MT_edit.bl_idname, icon='OUTLINER_COLLECTION')


def _context_menu(self, context):
    self.layout.separator()
    self.layout.menu(ATTRVIZ_MT_root.bl_idname, icon='HIDE_OFF')


def _draw_watch_readout(layout, context=None):
    """Active scope + its coverage (011 D3).

    Names which collection the number describes. Before 011 this line read
    "attrvis  N meshes", which meant "everything AttrViz watches"; with scopes
    that would be a lie the moment anyone splits one out (D2a).
    """
    ctx = context or bpy.context
    active = active_scope(ctx)
    row = layout.row(align=True)
    row.label(text="Scope")
    row.menu(ATTRVIZ_MT_scope.bl_idname,
             text=active.name if active is not None else "none",
             icon='OUTLINER_COLLECTION')
    if active is None:
        layout.label(text="none - AttrViz > Edit > Add objects")
        return
    meshes = gpu_sample.iter_watch_meshes(None, active)
    if not meshes:
        layout.label(text="empty - AttrViz > Edit > Add objects")
        return
    names = [o.name for o in meshes]
    n = len(names)
    noun = "object" if n == 1 else "objects"
    if n <= _WATCH_NAME_CAP:
        detail = ", ".join(names)
    else:
        detail = (", ".join(names[:_WATCH_NAME_CAP])
                  + f"  +{n - _WATCH_NAME_CAP} more")
    layout.label(text=f"{n} {noun} - {detail}")


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
        scene = context.scene
        migrate_all_visualizers(scene)
        vizzes = visualizers(scene)
        if not vizzes:
            _draw_watch_readout(layout)
            layout.label(text="RMB → AttrViz → Visualize Attribute")
            layout.label(text="Viewport: Material Preview (emission viz)")
            return

        space = context.space_data
        gpu_on = bool(getattr(scene, "attrviz_gpu_markers", True))
        if not _viz_display_shading_ok(space):
            _ensure_viz_display_shading(context)
        row = layout.row(align=True)
        row.prop(scene, "attrviz_gpu_markers", text="GPU Overlay",
                 toggle=True)
        if gpu_on:
            row.label(text="Solid OK", icon='SHADING_SOLID')
        else:
            row.label(text="Material Preview", icon='SHADING_RENDERED')
            row.operator("attrviz.use_viz_display_shading", text="",
                         icon='FILE_REFRESH')

        _draw_watch_readout(layout)

        # Heal sessions where every viz was left expanded.
        opened = [o for o in vizzes if o.attrviz_ui_expand]
        if len(opened) > 1:
            for o in opened[:-1]:
                o.attrviz_ui_expand = False

        # A collection tree, not a filtered list (011 D9). Every collection is
        # always shown: a filter that hides visualizers which are still drawing
        # puts ink on screen with no control for it.
        #
        # Collection headers are plain full-width rows rather than nested
        # layout panels, because panel_prop nesting is unverified (D10) and the
        # per-viz panels must stay on the ROOT layout regardless -- panel_prop
        # cannot sit inside a box, column or split.
        active = active_scope(context)
        for coll, members in visualizers_by_scope(scene):
            _draw_scope_header(layout, coll, members, active)
            if coll is not None and not _scope_expanded(coll):
                continue
            _draw_viz_rows(layout, members)


def _scope_expanded(coll):
    return bool(getattr(coll, "attrviz_scope_expand", True))


def _draw_scope_header(layout, coll, members, active):
    """One collection group heading: collapse, enable, activate, count."""
    row = layout.row(align=True)
    if coll is None:
        row.label(text=f"{WATCH_COLLECTION} (missing)", icon='ERROR')
        return
    row.prop(coll, "attrviz_scope_expand", text="", emboss=False,
             icon='TRIA_DOWN' if _scope_expanded(coll) else 'TRIA_RIGHT')
    # Checking this box changes what is drawn. Clicking the name does not.
    row.prop(coll, "attrviz_scope_enabled", text="")
    op = row.operator(ATTRVIZ_OT_set_active_scope.bl_idname,
                      text=coll.name, emboss=False,
                      depress=(coll == active))
    op.name = coll.name
    n_obj = len(gpu_sample.iter_watch_meshes(None, coll))
    n_viz = len(members)
    sub = row.row()
    sub.alignment = 'RIGHT'
    sub.label(text=f"{n_obj} obj  /  {n_viz} viz")


def _draw_viz_rows(layout, vizzes):
    """One layout panel per visualizer, on the ROOT layout only."""
    for obj in vizzes:
        md = viz_modifier(obj)
        attr_name = ""
        domain = ""
        display = ""
        if md is not None:
            try:
                attr_name = node_builder.get_input(md, "Attribute") or ""
                domain = node_builder.menu_input_name(md, "Domain") or ""
                display = node_builder.menu_input_name(md, "Display") or ""
            except Exception:
                pass
        # Headline: attr · domain · type — so two viz on the same
        # attr (e.g. flow Surface vs flow Arrows) stay distinct when collapsed.
        parts = [p for p in (attr_name or obj.name, domain, display) if p]
        title = "  ·  ".join(parts) if parts else obj.name

        header, body = layout.panel_prop(obj, "attrviz_ui_expand")
        # text="" required for checkbox-in-header (Blender layout panels).
        header.prop(obj, "attrviz_enabled", text="")
        header.label(text=title)
        op = header.operator(ATTRVIZ_OT_remove.bl_idname, text="",
                             icon='X')
        op.name = obj.name
        if body is None:
            continue
        if md is None:
            body.label(text="Missing AttrViz modifier", icon='ERROR')
            continue
        _draw_viz_body(body, obj, md, attr_name)


def _panel_heat_ramp_node(obj, md):
    """ValToRGB shown in the Viz panel for the ramp colormap.

    GPU overlay: off-engine per-viz ramp (never the shared engine).
    Materials path (GPU off): engine-copy ValToRGB.
    """
    if _gpu_overlay_on():
        try:
            return node_builder.ensure_viz_ramp(obj)
        except Exception:
            return None
    try:
        return next(
            (n for n in md.node_group.nodes
             if n.bl_idname == "ShaderNodeValToRGB"),
            None,
        )
    except Exception:
        return None


def visualizers_by_scope(scene=None):
    """[(collection, [viz objects]), ...] in scope-list order (011 D9).

    Membership is by IDENTITY -- viz.Scope is this collection -- not by
    coverage. An object may live in several collections; listing a visualizer
    under every collection it happens to touch would make the mapping fuzzy.
    A visualizer with no Scope is grouped under attrvis so it is never orphaned
    from the panel.
    """
    scene = scene or bpy.context.scene
    if scene is None:
        return []
    groups = {}
    order = []
    for coll in scope_collections(scene):
        groups[coll.name] = (coll, [])
        order.append(coll.name)
    for obj in visualizers(scene):
        md = viz_modifier(obj)
        coll = viz_scope(md) if md is not None else None
        key = coll.name if coll is not None else None
        if key is None or key not in groups:
            # No Scope and no attrvis in the file: make a home rather than
            # dropping the visualizer out of the UI entirely.
            if coll is None:
                key = WATCH_COLLECTION
                if key not in groups:
                    groups[key] = (None, [])
                    order.append(key)
            else:
                groups[key] = (coll, [])
                order.append(key)
        groups[key][1].append(obj)
    return [groups[k] for k in order]


def _draw_scope_row(body, md, attr_name):
    """Scope selector + honest coverage (011 D3/D5).

    Reads "4 objects - 3 carry K". That line is the diagnostic that would have
    made the original vanishing-boxes report self-explanatory: an object in
    scope carrying none of the attribute is drawn on by nothing, and 010 leaves
    it unmuted rather than hiding it with nothing in its place.
    """
    col = body.column(align=True)
    _draw_socket(col, md, "Scope")

    coll = viz_scope(md)
    if coll is None:
        col.label(text="no scope - nothing is drawn", icon='ERROR')
        return
    n_obj, n_draw = gpu_overlay.viz_coverage(md)
    if n_obj == 0:
        col.label(text=f"{coll.name}: empty - nothing is drawn", icon='INFO')
    else:
        noun = "object" if n_obj == 1 else "objects"
        label = f"{n_obj} {noun}"
        if attr_name:
            label += f"  -  {n_draw} carry {attr_name}"
        icon = 'INFO' if n_draw < n_obj else 'NONE'
        col.label(text=label, icon=icon)

    parent = collection_parent(coll)
    if parent is not None:
        # Nesting is inheritance. Never let it be silent (D2).
        col.label(text=f"inside {parent.name} - counts include inherited",
                  icon='OUTLINER_COLLECTION')


def _draw_viz_body(body, obj, md, attr_name):
    """Controls for one visualizer — parented under ``body`` only."""
    body.active = bool(obj.attrviz_enabled)

    _draw_scope_row(body, md, attr_name)
    body.separator()

    # Domain localizes; Type / Color follow.
    body.prop(obj, "attrviz_domain", text="Domain", expand=True)
    _draw_socket(body, md, "Attribute")
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
    if display == "Surface":
        if domain == "Edge":
            body.label(text="Surface on Edge is weakly supported",
                       icon='INFO')
        if not gpu_sample.watch_has_faces(md):
            body.label(text="Surface needs faces — use Markers",
                       icon='INFO')
        else:
            _draw_socket(body, md, "Show Wireframe")

    if colored:
        if _gpu_overlay_on():
            if gpu_color.color_mapper(dtype) == "hash":
                body.label(text="Color")
                body.label(text="Hash color per id")
                body.prop(obj, "attrviz_seed", text="Seed")
            else:
                body.label(text="Color")
                prow = body.row(align=True)
                for key, label in (
                    ("heat", "Heat"),
                    ("rgb", "RGB"),
                    ("bnw", "BnW"),
                ):
                    op = prow.operator(
                        ATTRVIZ_OT_ramp_preset.bl_idname, text=label,
                    )
                    op.name = obj.name
                    op.preset = key
                ramp = _panel_heat_ramp_node(obj, md)
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
        else:
            body.prop(obj, "attrviz_style", text="Color", expand=True)
            if style == "RGB" and dtype not in VECTORISH:
                body.label(text="RGB expects a vector attribute",
                           icon='INFO')
            if style == "Random":
                body.label(text="Stable hash color per element id")
                _draw_socket(body, md, "Seed")
            if style == "Heat":
                ramp = _panel_heat_ramp_node(obj, md)
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
            text="BLF labels · Cap spreads across the view",
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
    ATTRVIZ_OT_watch_add,
    ATTRVIZ_OT_watch_remove,
    ATTRVIZ_OT_remove,
    ATTRVIZ_OT_ramp_preset,
    ATTRVIZ_OT_use_viz_display_shading,
    ATTRVIZ_OT_set_active_scope,
    ATTRVIZ_OT_scope_new,
    ATTRVIZ_MT_domain_point,
    ATTRVIZ_MT_domain_edge,
    ATTRVIZ_MT_domain_face,
    ATTRVIZ_MT_domain_corner,
    ATTRVIZ_MT_domain_instance,
    ATTRVIZ_MT_visualize,
    ATTRVIZ_MT_scope,
    ATTRVIZ_MT_edit,
    ATTRVIZ_MT_root,
    ATTRVIZ_PT_panel,
)


def _update_scope_enabled(self, context):
    """Collection toggle changed: resync carriers, mute and the viewport.

    suppress_gn_carriers also calls _sync_surface_target_mute, which is what
    restores display_type on the objects of a collection just switched off.
    """
    try:
        scene = getattr(context, "scene", None) or bpy.context.scene
        gpu_overlay.invalidate_all()
        gpu_overlay.suppress_gn_carriers(scene)
        gpu_overlay._tag_view3d_redraw()
    except Exception:
        pass


def _update_hash_seed(self, context):
    """Seed is overlay presentation — redraw only, no mesh rebuild."""
    try:
        gpu_overlay._tag_view3d_redraw()
    except Exception:
        pass


def _update_ui_expand(self, context):
    """Accordion: only one visualizer settings block open at a time."""
    if not self.attrviz_ui_expand:
        return
    scene = context.scene if context is not None else bpy.context.scene
    if scene is None:
        return
    for obj in visualizers(scene):
        if obj != self and obj.attrviz_ui_expand:
            # Assigning False re-enters update; early-return above avoids loops.
            obj.attrviz_ui_expand = False


def _get_enabled(self):
    return not self.hide_viewport


def _set_enabled(self, value):
    enabled = bool(value)
    self.hide_viewport = not enabled
    md = viz_modifier(self)
    if md is not None:
        use_gpu = bool(getattr(bpy.context.scene, "attrviz_gpu_markers", True))
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
    # Do NOT invalidate GPU caches here — hide_viewport already skips draw.
    # Re-enable must reuse Surface L0 caches (hundreds of ms to rebuild).
    try:
        gpu_overlay.suppress_gn_carriers(bpy.context.scene)
        screen = getattr(bpy.context, "screen", None)
        if screen is not None:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:
        pass


@persistent
def _note_depsgraph_epochs(scene, depsgraph):
    """Record which watched objects the depsgraph says changed.

    Kept separate from _sync_vizcol_active and registered FIRST: this is the
    overlay's only correct invalidation signal, and it must not be skipped
    because some unrelated vizcol sync raised.
    """
    try:
        gpu_sample.note_depsgraph_updates(depsgraph)
    except Exception:
        pass


@persistent
def _note_frame_change(scene, depsgraph=None):
    """Frame changes do not fire depsgraph_update_post at all (measured on
    5.2), so animated sources need this second signal or they go stale."""
    try:
        gpu_sample.note_frame_change()
    except Exception:
        pass


@persistent
def _sync_vizcol_active(scene, depsgraph):
    """Workbench Attribute shading needs active Color Attribute on eval mesh."""
    try:
        # Pass the handler's own depsgraph: the mute probe reads evaluated
        # attributes, and calling evaluated_depsgraph_get() from inside a
        # depsgraph handler resyncs the view layer mid-iteration.
        gpu_overlay.sync_surface_target_mute(scene, dg=depsgraph)
    except Exception:
        pass
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


@persistent
def _on_load_migrate(_dummy):
    """File open: pre-011 files may hold visualizers with no watch set.

    Registered on load_post rather than folded into gpu_overlay's handler so
    migration lives with the code that owns WATCH_COLLECTION and visualizers().
    """
    try:
        migrate_viz_scope()
    except Exception:
        pass


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    # Epoch bump goes first — invalidation must not depend on anything after it.
    if _note_depsgraph_epochs not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.insert(0, _note_depsgraph_epochs)
    if _note_frame_change not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(_note_frame_change)
    if _sync_vizcol_active not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_sync_vizcol_active)
    bpy.types.Collection.attrviz_scope_expand = bpy.props.BoolProperty(
        name="Expand",
        description="Show the visualizers scoped to this collection",
        default=True,
    )
    bpy.types.Collection.attrviz_scope_enabled = bpy.props.BoolProperty(
        name="Enabled",
        description=("Draw the visualizers scoped to this collection. "
                     "Individual visualizer toggles are preserved"),
        default=True,
        update=_update_scope_enabled,
    )
    bpy.types.Scene.attrviz_active_scope = bpy.props.PointerProperty(
        name="Active Scope",
        description=("Collection that Add/Remove objects and new visualizers "
                     "target. Does not change what is drawn"),
        type=bpy.types.Collection,
    )
    bpy.types.Object.attrviz_ui_expand = bpy.props.BoolProperty(
        name="Expand",
        description="Show this visualizer's settings (one open at a time)",
        default=False,
        update=_update_ui_expand,
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
        get=_enum_get("Domain", node_builder.UI_DOMAINS),
        set=_enum_set("Domain", node_builder.UI_DOMAINS),
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
    bpy.types.Object.attrviz_seed = bpy.props.IntProperty(
        name="Seed",
        description="Hash color seed (does not rebuild the overlay mesh)",
        default=0,
        min=0,
        update=_update_hash_seed,
    )
    if _on_load_migrate not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_migrate)
    bpy.types.VIEW3D_MT_object_context_menu.append(_context_menu)
    tags_draw.register()
    gpu_overlay.register()
    # Enabling the add-on with a pre-011 file already open must migrate too.
    try:
        migrate_viz_scope()
    except Exception:
        pass


def unregister():
    gpu_overlay.unregister()
    tags_draw.unregister()
    if _on_load_migrate in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_migrate)
    if _sync_vizcol_active in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_sync_vizcol_active)
    if _note_depsgraph_epochs in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_note_depsgraph_epochs)
    if _note_frame_change in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(_note_frame_change)
    bpy.types.VIEW3D_MT_object_context_menu.remove(_context_menu)
    for attr in ("attrviz_ui_expand", "attrviz_enabled", "attrviz_domain",
                 "attrviz_style", "attrviz_display", "attrviz_seed"):
        if hasattr(bpy.types.Object, attr):
            delattr(bpy.types.Object, attr)
    if hasattr(bpy.types.Scene, "attrviz_active_scope"):
        delattr(bpy.types.Scene, "attrviz_active_scope")
    for _attr in ("attrviz_scope_enabled", "attrviz_scope_expand"):
        if hasattr(bpy.types.Collection, _attr):
            delattr(bpy.types.Collection, _attr)
    # Drop leftover from the abandoned UIList experiment.
    if hasattr(bpy.types.Scene, "attrviz_viz_index"):
        delattr(bpy.types.Scene, "attrviz_viz_index")
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
