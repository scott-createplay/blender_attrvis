"""AttrViz GPU overlay — Solid-mode unlit Markers / Surface / Arrows.

POST_VIEW draw handler. Behind scene.attrviz_gpu_markers (default on).
GN+materials remain available when the flag is off.

Markers → points. Surface → false-color mesh tris.
Arrows → batched 4-sided cones (non-vector → draw nothing).
Tags stay on the BLF prototype.
"""
from __future__ import annotations

import traceback

import bpy
import gpu
import numpy as np
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader

from . import gpu_color, gpu_sample, node_builder, overlay_kind
from . import perf

_handle = None
_caches: dict = {}
_sample_caches: dict = {}

VECTORISH = frozenset({'FLOAT_VECTOR', 'FLOAT2'})
GPU_DISPLAYS = (overlay_kind.GEOMETRIC_DISPLAYS | overlay_kind.SURFACE_DISPLAYS) - {"Tags"}


def _float_socket(val, default):
    """Read a float socket; keep real 0.0 (``or default`` would drop it)."""
    if val is None:
        return float(default)
    try:
        return float(val)
    except (TypeError, ValueError):
        return float(default)


def _scene_gpu_on(scene=None) -> bool:
    scene = scene or bpy.context.scene
    return bool(getattr(scene, "attrviz_gpu_markers", True))


def invalidate_all():
    _caches.clear()
    _sample_caches.clear()


def invalidate(obj=None):
    """Drop caches for one visualizer, or all if ``obj`` is None."""
    if obj is None:
        invalidate_all()
        return
    ptr = obj.as_pointer()
    _caches.pop(ptr, None)
    _sample_caches.pop(ptr, None)


def _socket_bundle(md, obj=None):
    try:
        attr = node_builder.get_input(md, "Attribute")
        domain = node_builder.menu_input_name(md, "Domain")
        style = node_builder.menu_input_name(md, "Style")
        density = _float_socket(node_builder.get_input(md, "Density"), 1.0)
        seed = int(node_builder.get_input(md, "Seed") or 0)
        auto = bool(node_builder.get_input(md, "Auto Range"))
        rmin = _float_socket(node_builder.get_input(md, "Range Min"), 0.0)
        rmax = _float_socket(node_builder.get_input(md, "Range Max"), 1.0)
        length = _float_socket(node_builder.get_input(md, "Length"), 0.08)
        scale = _float_socket(node_builder.get_input(md, "Scale"), 0.02)
        acol = node_builder.get_input(md, "Arrow Color")
        if acol is not None:
            acol = tuple(float(c) for c in acol[:4])
        else:
            acol = (0.2, 0.6, 1.0, 1.0)
    except Exception:
        attr, domain, style = "", "Point", "Heat"
        density, seed, auto, rmin, rmax = 1.0, 0, True, 0.0, 1.0
        length, scale, acol = 0.08, 0.02, (0.2, 0.6, 1.0, 1.0)
    hash_seed = seed
    if obj is not None:
        try:
            hash_seed = int(obj.attrviz_seed)
        except Exception:
            pass
    return {
        "attr": attr, "domain": domain, "style": style,
        "density": density, "seed": seed, "hash_seed": hash_seed,
        "auto": auto,
        "rmin": rmin, "rmax": rmax, "length": length, "scale": scale,
        "acol": acol,
    }


def _sample_key(obj, display, sock, fp):
    """L0 — what we sample (view-agnostic: Density only, no cap).

    Seed belongs here only when geometric Density cull uses it. Surface
    packing ignores Seed; putting it in this key made Seed scrub rebuild
    the identity mesh.
    """
    dens = sock["density"]
    seed_l0 = 0
    if (overlay_kind.kind(display) == "geometric"
            and dens < 1.0 - 1e-12):
        seed_l0 = sock["seed"]
    return (
        obj.as_pointer(), display, sock["attr"], sock["domain"],
        dens, seed_l0, fp,
    )


def _present_key(display, sock, extra=()):
    """L1/L2 — presentation only (Length / Range / Style / Color / Scale)."""
    return (
        display, sock["style"], sock["auto"], sock["rmin"], sock["rmax"],
        sock["length"], sock["scale"], sock["acol"], sock["seed"],
        sock.get("hash_seed", sock["seed"]), extra,
    )


def _viz_cache_key(obj, md, display, extra=()):
    """Full key (sample + present)."""
    sock = _socket_bundle(md, obj)
    fp = gpu_sample.watch_fingerprint(md)
    return (
        _sample_key(obj, display, sock, fp)
        + _present_key(display, sock, extra=extra)
    )

SCOPE_ENABLED_PROP = "attrviz_scope_enabled"


def scope_enabled(coll) -> bool:
    """Is the group of visualizers scoped to ``coll`` enabled? (011 D9)

    Stored on the Collection and never written onto each visualizer, so
    toggling a collection off and on preserves the individual enable states
    the user set. Unset reads as enabled: collections predating the property,
    and any collection in a file saved before 011, stay on.
    """
    if coll is None:
        return True
    return bool(getattr(coll, SCOPE_ENABLED_PROP, True))


def viz_active(obj, md) -> bool:
    """A visualizer draws iff its own toggle AND its scope's toggle are on.

    Every place that iterates visualizers must use this. In particular
    _active_watch_targets: if the mute path ignored the collection toggle,
    disabling a collection would leave its objects muted to BOUNDS with
    nothing drawn -- exactly the 010 bug, reintroduced.
    """
    if obj is None or obj.hide_viewport:
        return False
    from . import viz_scope
    try:
        return scope_enabled(viz_scope(md))
    except Exception:
        return True


def _gpu_visualizers(scene):
    from . import visualizers, viz_modifier
    rows = []
    for obj in visualizers(scene):
        if obj.hide_viewport:
            continue
        md = viz_modifier(obj)
        if md is None:
            continue
        if not viz_active(obj, md):
            continue
        try:
            display = node_builder.menu_input_name(md, "Display")
        except Exception:
            continue
        if display not in GPU_DISPLAYS:
            continue
        rows.append((obj, md, display))
    return rows


_SUPPRESS_DISPLAYS = overlay_kind.GEOMETRIC_DISPLAYS | overlay_kind.SURFACE_DISPLAYS


def _suppress_gn_carriers(scene):
    """When GPU overlay on, hide GN carrier mesh for all GPU-drawn displays.

    Call from state changes (GPU flag, Enabled, Display) — never from the
    draw handler (writing modifiers there thrashs the depsgraph).
    Also syncs source solid-mute (Surface → meshes, geometric → clouds).
    """
    from . import visualizers, viz_modifier
    use_gpu = _scene_gpu_on(scene)
    for obj in visualizers(scene):
        md = viz_modifier(obj)
        if md is None:
            continue
        try:
            display = node_builder.menu_input_name(md, "Display")
        except Exception:
            continue
        if display not in _SUPPRESS_DISPLAYS:
            continue
        enabled = viz_active(obj, md)
        if use_gpu and enabled:
            if md.show_viewport:
                md.show_viewport = False
        elif enabled and not md.show_viewport:
            md.show_viewport = True
        elif not enabled and md.show_viewport:
            # Scope-disabled: nothing set show_viewport for us, unlike the
            # per-viz toggle which goes through _set_enabled.
            md.show_viewport = False
    _sync_surface_target_mute(scene)


# --- Source solid mute (overlay vs Workbench / native point spheres) ---
# Stash Object.display_type and set BOUNDS (WIRE if Show Wireframe).
# Surface viz → watched MESH. Geometric viz → watched POINTCLOUD.
# Same attrvis / Target∪Scope scoping as sampling. One mute system.
_MUTE_PROP = "attrviz_surface_mute_prev"
_MUTE_DISPLAY = "WIRE"
_muted_ptrs: set = set()


def _eval_attr_names(obj, dg):
    """{domain_ui: {attribute name: dtype}} on the EVALUATED object, or None.

    Deliberately lean. ``attributes_by_domain()`` is the richer probe, but it
    calls ``evaluated_depsgraph_get()`` and ``evaluated_geometry()`` -- and
    _sync_surface_target_mute runs from a depsgraph handler on every update,
    where forcing an evaluation resyncs the view layer underneath whatever is
    iterating it. This reads the depsgraph the caller already has.

    Intrinsics (Index / Position / Normal) are added per domain: they are GN
    field sources and never appear in ``attributes``, so probing attributes
    alone would wrongly unmute every Normal visualizer. Normal is withheld
    where it does not exist (no vertices -- point clouds).

    Carries dtypes as well as names so that _target_attr_meta can answer "what
    type is this attribute in scope?" from the SAME map viz_coverage uses for
    "how many objects carry it". Two panel lines built from one walk of one
    list cannot drift apart -- which is exactly how they drifted in 014.
    Callers doing membership tests are unaffected: ``name in by[domain]`` hits
    dict keys.
    """
    try:
        ev = obj.evaluated_get(dg) if dg is not None else obj
        data = getattr(ev, "data", None)
        attrs = getattr(data, "attributes", None)
        if attrs is None:
            return None
        by = {d: {} for d in node_builder.UI_DOMAINS}
        b2ui = {v: k for k, v in node_builder.DOMAIN_TO_BLENDER.items()}
        for a in attrs:
            ui = b2ui.get(getattr(a, "domain", None))
            if ui is not None:
                by[ui][a.name] = getattr(a, "data_type", None)
        has_verts = hasattr(data, "vertices")
        for name, dtype, domains in node_builder.INTRINSICS:
            if name == node_builder.NORMAL_ATTR and not has_verts:
                continue
            for d in domains:
                if d in by:
                    by[d][name] = dtype
        return by
    except Exception:
        return None


def _viz_draws_on(md, obj, cache, dg=None):
    """Will this visualizer actually put ink on ``obj``?

    Muting means "the GPU overlay replaces the original". If the visualizer's
    attribute is not available on this object at its domain, nothing is drawn
    in its place and muting just leaves a hole -- an object hidden with
    nothing where it was. See dev_tasks/010_mute_scope/POR.md.

    Undeterminable -> True, preserving the previous behaviour. Only a
    confident "the attribute is absent here" unmutes, so a flaky probe cannot
    regress the scene into double-drawn originals.
    """
    try:
        attr = node_builder.get_input(md, "Attribute")
        domain = node_builder.menu_input_name(md, "Domain")
    except Exception:
        return True
    if not attr or not domain:
        return False        # nothing selected -> nothing drawn
    if domain == node_builder.INSTANCE_DOMAIN:
        # Instance attributes live on the instances cloud, not obj.data --
        # reading them needs the full geometry-set probe this deliberately
        # avoids. Undeterminable, so keep the previous behaviour.
        return True

    key = obj.as_pointer()
    if key in cache:
        avail = cache[key]
    else:
        avail = _eval_attr_names(obj, dg)
        cache[key] = avail
    if avail is None:
        return True

    names = avail.get(domain, ())
    if attr in names:
        return True
    # lowercase "position" aliases the Position intrinsic
    if attr in node_builder.INTRINSIC_ALIASES:
        return node_builder.POSITION_ATTR in names
    return False


def viz_coverage(md):
    """(objects in scope, how many the visualizer can actually draw on).

    Uses _viz_draws_on -- the same predicate that decides muting -- so the
    number the panel shows cannot disagree with what is drawn. That invariant
    is what 009 and 010 kept breaking in different directions: a muted object
    with no ink, then ink with no row.

    Safe to call from panel draw (a UI context). NOT safe from a depsgraph
    handler: it asks for a depsgraph. See _eval_attr_names.
    """
    try:
        objs = gpu_sample.watch_meshes_for_visualizer(md)
    except Exception:
        return 0, 0
    try:
        dg = bpy.context.evaluated_depsgraph_get()
    except Exception:
        dg = None
    cache = {}
    n_draw = 0
    for obj in objs:
        try:
            if _viz_draws_on(md, obj, cache, dg):
                n_draw += 1
        except Exception:
            n_draw += 1
    return len(objs), n_draw


def _active_watch_targets(scene, kind_name, blender_type, *,
                          collect_wire=False, dg=None):
    """Watched objects of ``blender_type`` while any enabled viz of ``kind_name``.

    GPU overlay IS the visual representation — originals must be BOUNDS
    to avoid z-fight (meshes vs Surface, point spheres vs Markers).

    Returns list of (obj, show_wire) tuples.
    """
    from . import visualizers, viz_modifier
    if not _scene_gpu_on(scene):
        return []

    show_wire = False
    has_kind = False
    kind_mds = []
    for viz in visualizers(scene):
        if viz.hide_viewport:
            continue
        md = viz_modifier(viz)
        if md is None:
            continue
        if not viz_active(viz, md):
            continue
        try:
            display = node_builder.menu_input_name(md, "Display")
        except Exception:
            continue
        if overlay_kind.kind(display) != kind_name:
            continue
        has_kind = True
        kind_mds.append(md)
        if collect_wire:
            try:
                if bool(node_builder.get_input(md, "Show Wireframe")):
                    show_wire = True
            except Exception:
                pass

    if not has_kind:
        return []

    # Union over enabled visualizers of the objects each can actually draw on.
    # One resolver for both the attrvis and Target-union-Scope cases:
    # watch_meshes_for_visualizer already applies whichever is in force, and
    # unlike the old coll.objects walk it recurses nested sub-collections --
    # which the sampler always did, so those objects were drawn but never
    # muted.
    out = []
    seen = set()
    attr_cache = {}
    for md in kind_mds:
        for obj in gpu_sample.watch_meshes_for_visualizer(md):
            if obj is None or obj.type != blender_type:
                continue
            key = obj.as_pointer()
            if key in seen:
                continue
            if not _viz_draws_on(md, obj, attr_cache, dg):
                continue
            seen.add(key)
            out.append((obj, show_wire))
    return out


def _active_surface_watch_meshes(scene, dg=None):
    """All watched meshes when any Surface visualizer is active."""
    return _active_watch_targets(
        scene, "surface", 'MESH', collect_wire=True, dg=dg)


def _active_geometric_watch_clouds(scene, dg=None):
    """All watched point clouds when any geometric visualizer is active.

    Native POINTCLOUD spheres compete with overlay Markers/Arrows/Tags
    at the same centers. Mute to BOUNDS (same helpers as Surface).
    """
    return _active_watch_targets(
        scene, "geometric", 'POINTCLOUD', collect_wire=False, dg=dg)


def _mute_target_solid(obj, show_wire=False):
    """AttrViz-owned solid mute — hide original so only GPU overlay shows.

    The GPU overlay IS the mesh from the user's perspective.
    Default: BOUNDS (invisible). show_wire=True for optional wireframe.
    """
    if obj is None:
        return
    ptr = obj.as_pointer()
    if _MUTE_PROP not in obj:
        try:
            obj[_MUTE_PROP] = str(obj.display_type)
        except Exception:
            obj[_MUTE_PROP] = "TEXTURED"
    target_dt = "WIRE" if show_wire else "BOUNDS"
    try:
        if obj.display_type != target_dt:
            obj.display_type = target_dt
    except Exception:
        pass
    _muted_ptrs.add(ptr)


def _restore_target_solid(obj):
    """Restore stashed display_type if we muted this object."""
    if obj is None:
        return
    ptr = obj.as_pointer()
    prev = obj.get(_MUTE_PROP) if _MUTE_PROP in obj else None
    if prev is not None:
        try:
            if obj.display_type in ("WIRE", "BOUNDS"):
                obj.display_type = prev
        except Exception:
            pass
        try:
            del obj[_MUTE_PROP]
        except Exception:
            pass
    _muted_ptrs.discard(ptr)


def _rebuild_muted_ptrs():
    """as_pointer() values die across file load — rebuild from ID props."""
    _muted_ptrs.clear()
    for obj in bpy.data.objects:
        if _MUTE_PROP in obj:
            _muted_ptrs.add(obj.as_pointer())


@persistent
def _on_load_post(_dummy):
    """File open: overlay caches are stale; re-apply source solid mute.

    Addon register timers do not run again on File → Open. Non-persistent
    depsgraph handlers are also wiped. Mute must be explicit here — writing
    display_type from depsgraph_update_post often does not stick.
    """
    _rebuild_muted_ptrs()
    invalidate_all()
    try:
        # Epochs are keyed on datablock pointers — meaningless across files,
        # and a reused pointer could mask a change.
        gpu_sample.reset_epochs()
    except Exception:
        pass
    try:
        from . import tags_draw
        tags_draw.invalidate_cache()
    except Exception:
        pass
    try:
        scene = bpy.context.scene
        _suppress_gn_carriers(scene)
    except Exception:
        pass
    try:
        _subscribe_ramp_msgbus()
    except Exception:
        pass


def _sync_surface_target_mute(scene=None, dg=None):
    """Idempotent: mute watch-set solids for active GPU overlay vizs.

    Surface → MESH. Geometric (Markers/Arrows/Tags) → POINTCLOUD.
    Independent; union into one restore loop. Safe to call often.
    Never from attribute-name discovery — only the resolved watch set.
    """
    scene = scene or bpy.context.scene
    if dg is None:
        # Not in a handler: safe to ask for one. Inside a depsgraph handler
        # the caller passes its own -- see _eval_attr_names.
        try:
            dg = bpy.context.evaluated_depsgraph_get()
        except Exception:
            dg = None
    desired = list(_active_surface_watch_meshes(scene, dg))
    desired.extend(_active_geometric_watch_clouds(scene, dg))
    desired_ptrs = {o.as_pointer(): (o, wire) for o, wire in desired}

    # Restore anything we muted that is no longer desired.
    for ptr in list(_muted_ptrs):
        if ptr in desired_ptrs:
            continue
        obj = None
        for candidate in bpy.data.objects:
            if candidate.as_pointer() == ptr:
                obj = candidate
                break
        if obj is not None:
            _restore_target_solid(obj)
        else:
            _muted_ptrs.discard(ptr)

    for ptr, (obj, show_wire) in desired_ptrs.items():
        _mute_target_solid(obj, show_wire=show_wire)


def restore_all_surface_mutes():
    """Unregister / GPU-off cleanup — restore every AttrViz-muted object."""
    for obj in list(bpy.data.objects):
        if _MUTE_PROP in obj:
            _restore_target_solid(obj)
    _muted_ptrs.clear()


# Public alias for callers in __init__.py
suppress_gn_carriers = _suppress_gn_carriers
# Back-compat alias
_suppress_gn_markers = _suppress_gn_carriers
sync_surface_target_mute = _sync_surface_target_mute


def _build_batch(positions, colors, prim='POINTS'):
    with perf.span("overlay.build_batch"):
        # Pass contiguous float32 arrays directly — no Python tuple conversion
        pos_arr = np.ascontiguousarray(positions[:, :3], dtype=np.float32)
        try:
            shader = gpu.shader.from_builtin('SMOOTH_COLOR')
            col_arr = np.ascontiguousarray(colors[:, :4], dtype=np.float32)
            batch = batch_for_shader(
                shader, prim, {"pos": pos_arr, "color": col_arr},
            )
            return batch, shader, "smooth"
        except Exception:
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            batch = batch_for_shader(
                shader, prim, {"pos": pos_arr},
            )
            return batch, shader, "uniform"


# --- Heat LUT shader (positions + scalars; ramp is a 256×1 texture) ----
_heat_lut_shader = None
_heat_lut_ok = None  # None unknown; False in --background


def _dtype_heat_lut(dtype) -> bool:
    """True when the ColorRamp maps a scalar (vector → length).

    FLOAT_COLOR / BYTE_COLOR already are colors. INT/BOOLEAN/INT8 hash
    (task 005) — they must not interpolate along the ramp LUT.
    """
    return (
        dtype is not None
        and gpu_color.color_mapper(dtype) == "ramp"
        and dtype not in ("FLOAT_COLOR", "BYTE_COLOR")
    )


def _ramp_colormap(display, dtype) -> bool:
    """Surface/Markers use the per-viz ColorRamp (presets fill it)."""
    return display in ("Markers", "Surface") and _dtype_heat_lut(dtype)


def _heat_lut_shader_available() -> bool:
    """CreateInfo LUT shader needs a real GPU context (not --background)."""
    global _heat_lut_ok
    if _heat_lut_ok is not None:
        return bool(_heat_lut_ok)
    try:
        _get_heat_lut_shader()
        _heat_lut_ok = True
    except Exception:
        _heat_lut_ok = False
    return bool(_heat_lut_ok)


def _get_heat_lut_shader():
    """pos + scalar → ColorRamp LUT. Range is uniforms; mesh stays uploaded."""
    global _heat_lut_shader
    if _heat_lut_shader is not None:
        return _heat_lut_shader
    info = gpu.types.GPUShaderCreateInfo()
    info.vertex_in(0, "VEC3", "pos")
    info.vertex_in(1, "FLOAT", "value")
    iface = gpu.types.GPUStageInterfaceInfo("attrviz_heat_lut")
    iface.smooth("FLOAT", "fac")
    info.vertex_out(iface)
    info.sampler(0, "FLOAT_2D", "ramp_tex")
    info.push_constant("MAT4", "viewProjectionMatrix")
    info.push_constant("FLOAT", "vmin")
    info.push_constant("FLOAT", "vmax")
    info.push_constant("FLOAT", "pointSize")
    info.fragment_out(0, "VEC4", "fragColor")
    info.vertex_source(
        "void main()\n"
        "{\n"
        "  float lo = vmin;\n"
        "  float hi = vmax;\n"
        "  fac = (hi <= lo) ? 0.0 : clamp((value - lo) / (hi - lo), 0.0, 1.0);\n"
        "  gl_Position = viewProjectionMatrix * vec4(pos, 1.0);\n"
        "  gl_PointSize = pointSize;\n"
        "}\n"
    )
    info.fragment_source(
        "void main()\n"
        "{\n"
        "  float x = fac * 255.0;\n"
        "  int i0 = int(x);\n"
        "  int i1 = min(i0 + 1, 255);\n"
        "  float f = fract(x);\n"
        "  vec4 c0 = texelFetch(ramp_tex, ivec2(i0, 0), 0);\n"
        "  vec4 c1 = texelFetch(ramp_tex, ivec2(i1, 0), 0);\n"
        "  fragColor = mix(c0, c1, f);\n"
        "}\n"
    )
    _heat_lut_shader = gpu.shader.create_from_info(info)
    return _heat_lut_shader


def _heat_batch_key(display, extra=()):
    """Mesh VBO key for Heat LUT — no ramp, no range."""
    return (display, "heat_lut", extra)


def _id_hash_batch_key(display, extra=()):
    """Mesh VBO key for id hash — seed is a uniform, not a VBO."""
    return (display, "id_hash", extra)


_id_hash_shader = None
_id_hash_ok = None


def _id_hash_shader_available() -> bool:
    """CreateInfo id-hash shader needs a real GPU context (not --background)."""
    global _id_hash_ok
    if _id_hash_ok is not None:
        return bool(_id_hash_ok)
    try:
        _get_id_hash_shader()
        _id_hash_ok = True
    except Exception:
        _id_hash_ok = False
    return bool(_id_hash_ok)


def _get_id_hash_shader():
    """pos + id → hash color. Seed is a uniform; mesh stays uploaded."""
    global _id_hash_shader
    if _id_hash_shader is not None:
        return _id_hash_shader
    info = gpu.types.GPUShaderCreateInfo()
    info.vertex_in(0, "VEC3", "pos")
    info.vertex_in(1, "FLOAT", "value")
    iface = gpu.types.GPUStageInterfaceInfo("attrviz_id_hash")
    iface.flat("FLOAT", "vid")
    info.vertex_out(iface)
    info.push_constant("MAT4", "viewProjectionMatrix")
    info.push_constant("INT", "seed")
    info.push_constant("FLOAT", "pointSize")
    info.fragment_out(0, "VEC4", "fragColor")
    info.vertex_source(
        "void main()\n"
        "{\n"
        "  vid = value;\n"
        "  gl_Position = viewProjectionMatrix * vec4(pos, 1.0);\n"
        "  gl_PointSize = pointSize;\n"
        "}\n"
    )
    # Matches gpu_color.hash_colors (uint32 xorshift * 0x45D9F3B).
    info.fragment_source(
        "void main()\n"
        "{\n"
        "  uint x = uint(int(vid)) ^ uint(seed);\n"
        "  x = (x ^ (x >> 16u)) * 0x45D9F3Bu;\n"
        "  x = (x ^ (x >> 16u)) * 0x45D9F3Bu;\n"
        "  x = x ^ (x >> 16u);\n"
        "  float r = float(x & 0xFFu) / 255.0;\n"
        "  float g = float((x >> 8u) & 0xFFu) / 255.0;\n"
        "  float b = float((x >> 16u) & 0xFFu) / 255.0;\n"
        "  fragColor = vec4(0.25 + 0.75 * r, 0.25 + 0.75 * g,\n"
        "                   0.25 + 0.75 * b, 1.0);\n"
        "}\n"
    )
    _id_hash_shader = gpu.shader.create_from_info(info)
    return _id_hash_shader


def _stops_for_viz(obj):
    try:
        node = node_builder.ensure_viz_ramp(obj)
    except Exception:
        node = node_builder.ramp_node_for_viz(obj)
    return gpu_color.extract_ramp(node)


def _heat_vmin_vmax(scalars, sock):
    s = np.asarray(scalars, dtype=np.float32).reshape(-1)
    if sock.get("auto", True):
        if s.size == 0:
            return 0.0, 1.0
        return float(np.min(s)), float(np.max(s))
    return float(sock["rmin"]), float(sock["rmax"])


def _upload_ramp_lut(stops):
    lut = gpu_color.ramp_lut_rgba(stops, n=gpu_color.LUT_SIZE)
    tex, _w = overlay_kind.pack_texture_2d(lut)
    return tex


def _build_value_batch(positions, scalars, prim, shader):
    with perf.span("overlay.build_batch"):
        pos_arr = np.ascontiguousarray(positions[:, :3], dtype=np.float32)
        val_arr = np.ascontiguousarray(
            np.asarray(scalars, dtype=np.float32).reshape(-1),
            dtype=np.float32,
        )
        batch = batch_for_shader(
            shader, prim, {"pos": pos_arr, "value": val_arr},
        )
        return batch, shader


def _build_heat_lut_batch(positions, scalars, prim="TRIS"):
    return _build_value_batch(
        positions, scalars, prim, _get_heat_lut_shader(),
    )


def _apply_heat_lut(entry, sock, stops, scalars):
    """Cheap: rewrite LUT texture + range uniforms. Does not rebuild VBOs."""
    if scalars is None:
        return
    lo, hi = _heat_vmin_vmax(scalars, sock)
    entry["vmin"] = lo
    entry["vmax"] = hi
    entry["ramp_tex"] = _upload_ramp_lut(stops)
    entry["lut_key"] = (
        gpu_color.ramp_hash(stops), sock["auto"], sock["rmin"], sock["rmax"],
    )


def _refresh_heat_lut_entry(positions, values, dtype, prim, sock, stops,
                            point_size=5.0):
    scalars = gpu_color.heat_scalar(values, dtype)
    batch, shader = _build_heat_lut_batch(positions, scalars, prim=prim)
    entry = {
        "batch": batch,
        "shader": shader,
        "mode": "heat_lut",
        "n": len(positions) if prim == "POINTS" else (len(positions) // 3),
        "prim": prim,
        "dtype": dtype,
        "scalars": scalars,
        "point_size": float(point_size),
    }
    _apply_heat_lut(entry, sock, stops, scalars)
    return entry


def _refresh_id_hash_entry(positions, values, dtype, prim, hash_seed,
                           point_size=5.0):
    ids = np.ascontiguousarray(
        np.asarray(values, dtype=np.float32).reshape(-1), dtype=np.float32,
    )
    batch, shader = _build_value_batch(
        positions, ids, prim, _get_id_hash_shader(),
    )
    return {
        "batch": batch,
        "shader": shader,
        "mode": "id_hash",
        "n": len(positions) if prim == "POINTS" else (len(positions) // 3),
        "prim": prim,
        "dtype": dtype,
        "ids": ids,
        "hash_seed": int(hash_seed),
        "point_size": float(point_size),
    }


# --- Arrows instancing (unit cone × N) ---------------------------------
_arrow_shader = None
_unit_cone_cache: dict = {}  # sides -> batch
_instancing_ok = None  # None unknown; False in --background


def _arrow_instancing_available() -> bool:
    """CreateInfo / textures need a real GPU context (not --background)."""
    global _instancing_ok
    if _instancing_ok is not None:
        return bool(_instancing_ok)
    try:
        _get_arrow_shader()
        _instancing_ok = True
    except Exception:
        _instancing_ok = False
    return bool(_instancing_ok)


def _get_arrow_shader():
    """Custom CreateInfo shader: unit cone × gl_InstanceID origin/dir tex."""
    global _arrow_shader
    if _arrow_shader is not None:
        return _arrow_shader
    info = gpu.types.GPUShaderCreateInfo()
    info.vertex_in(0, 'VEC3', "pos")
    info.sampler(0, 'FLOAT_2D', "origin_tex")
    info.sampler(1, 'FLOAT_2D', "dir_tex")
    info.push_constant('MAT4', "viewProjectionMatrix")
    info.push_constant('FLOAT', "length")
    info.push_constant('FLOAT', "radius")
    info.push_constant('VEC4', "color")
    info.fragment_out(0, 'VEC4', "fragColor")
    info.vertex_source(
        "void main()\n"
        "{\n"
        "  int W = textureSize(origin_tex, 0).x;\n"
        "  ivec2 uv = ivec2(gl_InstanceID % W, gl_InstanceID / W);\n"
        "  vec3 origin = texelFetch(origin_tex, uv, 0).xyz;\n"
        "  vec3 dir = texelFetch(dir_tex, uv, 0).xyz;\n"
        "  vec3 helper = (abs(dir.y) > 0.9) ? vec3(1.0, 0.0, 0.0)\n"
        "                                   : vec3(0.0, 1.0, 0.0);\n"
        "  vec3 side = normalize(cross(dir, helper));\n"
        "  vec3 up = cross(side, dir);\n"
        "  vec3 local = vec3(pos.x * radius, pos.y * radius, pos.z * length);\n"
        "  vec3 world = origin + side * local.x + up * local.y + dir * local.z;\n"
        "  gl_Position = viewProjectionMatrix * vec4(world, 1.0);\n"
        "}\n"
    )
    info.fragment_source(
        "void main()\n"
        "{\n"
        "  fragColor = color;\n"
        "}\n"
    )
    _arrow_shader = gpu.shader.create_from_info(info)
    return _arrow_shader


def _unit_cone_tris(sides: int = 4):
    """Unit cone: base ring radius 1 at z=0, tip at (0,0,1)."""
    sides = max(3, int(sides))
    angles = (2.0 * np.pi) * (np.arange(sides, dtype=np.float32) / sides)
    ring = np.stack([np.cos(angles), np.sin(angles), np.zeros(sides)], axis=1)
    tip = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    tris = np.empty((sides * 3, 3), dtype=np.float32)
    k = 0
    for j in range(sides):
        j2 = (j + 1) % sides
        tris[k] = tip
        tris[k + 1] = ring[j]
        tris[k + 2] = ring[j2]
        k += 3
    return tris


def _get_unit_cone_batch(shader, sides: int = 4):
    sides = max(3, int(sides))
    cached = _unit_cone_cache.get(sides)
    if cached is not None:
        return cached
    tris = _unit_cone_tris(sides)
    pos_list = [tuple(p) for p in tris]
    batch = batch_for_shader(shader, 'TRIS', {"pos": pos_list})
    _unit_cone_cache[sides] = batch
    return batch


def _arrow_alive_frames(positions, values):
    """Filter non-zero vectors → (origins Nx3, dirs Nx3, n) or (None, None, 0)."""
    v = np.asarray(values, dtype=np.float32)
    if v.ndim != 2 or v.shape[1] < 2:
        return None, None, 0
    if v.shape[1] == 2:
        v3 = np.zeros((len(v), 3), dtype=np.float32)
        v3[:, :2] = v
        v = v3
    else:
        v = v[:, :3]
    norms = np.linalg.norm(v, axis=1)
    alive = norms > 1e-8
    if not np.any(alive):
        return None, None, 0
    origins = np.asarray(positions, dtype=np.float32)[alive]
    dirs = v[alive] / norms[alive][:, None]
    return origins, dirs, int(len(origins))


def _float_tex_rgba(rows: np.ndarray):
    """Upload Nx3 float rows as a Metal-safe 2D RGBA32F texture.

    Delegates to overlay_kind.pack_texture_2d; returns only the texture
    (W is derived in shader via textureSize).
    """
    tex, _w = overlay_kind.pack_texture_2d(rows)
    return tex


def _arrow_cone_geometry(positions, values, length: float, radius: float,
                         sides: int = 4):
    """Batched N-sided cones: base at sample, tip along vector.

    Returns (tri_verts Mx3, n_arrows) with M = n_arrows * sides * 3.
    Kept as oracle / soup fallback for tests and environments without
    custom-shader instancing.
    """
    with perf.span("overlay.arrow_cones"):
        return _arrow_cone_geometry_impl(
            positions, values, length, radius, sides=sides,
        )


def _arrow_cone_geometry_impl(positions, values, length: float, radius: float,
                              sides: int = 4):
    v = np.asarray(values, dtype=np.float32)
    if v.ndim != 2 or v.shape[1] < 2:
        return None, 0
    if v.shape[1] == 2:
        v3 = np.zeros((len(v), 3), dtype=np.float32)
        v3[:, :2] = v
        v = v3
    else:
        v = v[:, :3]
    norms = np.linalg.norm(v, axis=1)
    alive = norms > 1e-8
    if not np.any(alive):
        return None, 0
    positions = np.asarray(positions, dtype=np.float32)[alive]
    v = v[alive]
    norms = norms[alive]
    dirs = v / norms[:, None]
    n = len(positions)
    sides = max(3, int(sides))
    length = float(length)
    radius = float(max(1e-6, radius))

    # Orthonormal basis perpendicular to each direction
    # Pick a helper axis not parallel to dir
    helpers = np.tile(np.array([0.0, 1.0, 0.0], dtype=np.float32), (n, 1))
    parallel = np.abs(dirs[:, 1]) > 0.9
    helpers[parallel] = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    # side = normalize(cross(dir, helper)); up = cross(side, dir)
    side = np.cross(dirs, helpers)
    side_n = np.linalg.norm(side, axis=1, keepdims=True)
    side_n = np.maximum(side_n, 1e-8)
    side = side / side_n
    up = np.cross(side, dirs)

    tips = positions + dirs * length
    # Base ring: positions + radius * (cos*side + sin*up)
    angles = (2.0 * np.pi) * (np.arange(sides, dtype=np.float32) / sides)
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)

    # tris: sides * 3 verts each
    m = n * sides * 3
    tri_pos = np.empty((m, 3), dtype=np.float32)
    k = 0
    for i in range(n):
        base = positions[i]
        tip = tips[i]
        s = side[i]
        u = up[i]
        ring = np.empty((sides, 3), dtype=np.float32)
        for j in range(sides):
            ring[j] = base + radius * (cos_a[j] * s + sin_a[j] * u)
        for j in range(sides):
            j2 = (j + 1) % sides
            tri_pos[k] = tip
            tri_pos[k + 1] = ring[j]
            tri_pos[k + 2] = ring[j2]
            k += 3
    return tri_pos, n


def _refresh_markers(obj, md, positions, values, dtype, density, seed,
                     style, rmin, rmax, cap_key_n, *, sock=None, stops=None):
    mapper = gpu_color.color_mapper(dtype)
    if mapper == "hash" and _id_hash_shader_available() and sock is not None:
        try:
            scale = _float_socket(node_builder.get_input(md, "Scale"), 0.02)
            point_size = max(2.0, min(24.0, scale * 250.0))
        except Exception:
            point_size = 5.0
        try:
            return _refresh_id_hash_entry(
                positions, values, dtype, "POINTS",
                sock.get("hash_seed", seed),
                point_size=point_size,
            )
        except Exception:
            pass
    if (mapper == "ramp"
            and _dtype_heat_lut(dtype)
            and _heat_lut_shader_available() and sock is not None
            and stops is not None):
        try:
            scale = _float_socket(node_builder.get_input(md, "Scale"), 0.02)
            point_size = max(2.0, min(24.0, scale * 250.0))
        except Exception:
            point_size = 5.0
        try:
            return _refresh_heat_lut_entry(
                positions, values, dtype, "POINTS", sock,
                stops or gpu_color.HEAT_STOPS,
                point_size=point_size,
            )
        except Exception:
            pass
    with perf.span("overlay.colors"):
        if mapper == "hash":
            colors = gpu_color.hash_colors(values, seed=seed)
        elif stops is not None and _dtype_heat_lut(dtype):
            scalars = gpu_color.heat_scalar(values, dtype)
            colors = gpu_color.ramp_colors(
                scalars, stops, vmin=rmin, vmax=rmax,
            )
        else:
            colors = gpu_color.values_to_colors(
                values, dtype, style, vmin=rmin, vmax=rmax, seed=seed,
                ramp=stops,
            )
    try:
        batch, shader, mode = _build_batch(positions, colors, prim='POINTS')
    except Exception:
        return {
            "batch": None,
            "n": len(positions),
            "prim": "POINTS",
            "colors": colors,
            "point_size": 5.0,
        }
    entry = {
        "batch": batch,
        "shader": shader,
        "mode": mode,
        "colors": colors,
        "n": len(positions),
        "prim": "POINTS",
        "point_size": 5.0,
        "dtype": dtype,
    }
    try:
        scale = _float_socket(node_builder.get_input(md, "Scale"), 0.02)
        entry["point_size"] = max(2.0, min(24.0, scale * 250.0))
    except Exception:
        pass
    return entry


def _refresh_arrows(obj, md, positions, values, dtype):
    # Honesty: non-vector → nothing
    if dtype not in VECTORISH:
        return {"batch": None, "n": 0, "prim": "TRIS", "empty": True}
    try:
        length = _float_socket(node_builder.get_input(md, "Length"), 0.08)
        scale = _float_socket(node_builder.get_input(md, "Scale"), 0.02)
        # Match GN spirit: Scale drives thickness; cone radius ~ scale * 0.35
        radius = max(1e-5, scale * 0.35)
        acol = node_builder.get_input(md, "Arrow Color")
        if acol is not None and len(acol) >= 3:
            color = (
                float(acol[0]), float(acol[1]), float(acol[2]),
                float(acol[3]) if len(acol) > 3 else 1.0,
            )
        else:
            color = (0.25, 0.65, 1.0, 1.0)
    except Exception:
        length, radius, color = 0.08, 0.007, (0.25, 0.65, 1.0, 1.0)

    with perf.span("overlay.arrow_instances"):
        origins, dirs, n_alive = _arrow_alive_frames(positions, values)
    if origins is None or n_alive == 0:
        return {"batch": None, "n": 0, "prim": "TRIS", "empty": True}

    # Prefer instanced unit-cone path (needs GPU context; soup in --background).
    if _arrow_instancing_available():
        try:
            shader = _get_arrow_shader()
            batch = _get_unit_cone_batch(shader, sides=4)
            origin_tex = _float_tex_rgba(origins)
            dir_tex = _float_tex_rgba(dirs)
            return {
                "batch": batch,
                "shader": shader,
                "mode": "instanced",
                "instance_count": n_alive,
                "origin_tex": origin_tex,
                "dir_tex": dir_tex,
                "length": length,
                "radius": radius,
                "n": n_alive,
                "prim": "TRIS",
                "uniform_color": color,
            }
        except Exception:
            global _instancing_ok
            _instancing_ok = False

    cone_pos, n_soup = _arrow_cone_geometry(
        positions, values, length, radius, sides=4,
    )
    if cone_pos is None or n_soup == 0:
        return {"batch": None, "n": 0, "prim": "TRIS", "empty": True}
    colors = np.tile(np.array(color, dtype=np.float32), (len(cone_pos), 1))
    try:
        batch, shader, mode = _build_batch(cone_pos, colors, prim='TRIS')
    except Exception:
        return {
            "batch": None,
            "n": n_soup,
            "prim": "TRIS",
            "uniform_color": color,
            "cone_verts": len(cone_pos),
        }
    return {
        "batch": batch,
        "shader": shader,
        "mode": mode,
        "colors": colors,
        "n": n_soup,
        "prim": "TRIS",
        "uniform_color": color,
        "cone_verts": len(cone_pos),
    }


def _refresh_surface_from_sample(sample, style, rmin, rmax, seed,
                                 *, sock=None, stops=None):
    """L2 only — colormap + batch from cached tri positions / corner values."""
    positions = sample["positions"]
    corner_values = sample["values"]
    dtype = sample["dtype"]
    n_tris = sample["n"]
    if n_tris == 0 or positions is None:
        return {"batch": None, "n": 0, "prim": "TRIS", "empty": True}
    mapper = gpu_color.color_mapper(dtype)
    if mapper == "hash" and _id_hash_shader_available() and sock is not None:
        try:
            return _refresh_id_hash_entry(
                positions, corner_values, dtype, "TRIS",
                sock.get("hash_seed", seed),
            )
        except Exception:
            pass
    if (mapper == "ramp"
            and _dtype_heat_lut(dtype)
            and _heat_lut_shader_available() and sock is not None
            and stops is not None):
        try:
            return _refresh_heat_lut_entry(
                positions, corner_values, dtype, "TRIS", sock,
                stops or gpu_color.HEAT_STOPS,
            )
        except Exception:
            pass
    with perf.span("overlay.colors"):
        if mapper == "hash":
            colors = gpu_color.hash_colors(corner_values, seed=seed)
        elif stops is not None and _dtype_heat_lut(dtype):
            scalars = gpu_color.heat_scalar(corner_values, dtype)
            colors = gpu_color.ramp_colors(
                scalars, stops, vmin=rmin, vmax=rmax,
            )
        else:
            colors = gpu_color.values_to_colors(
                corner_values, dtype, style, vmin=rmin, vmax=rmax, seed=seed,
                ramp=stops,
            )
    try:
        batch, shader, mode = _build_batch(positions, colors, prim='TRIS')
    except Exception:
        return {
            "batch": None,
            "n": n_tris,
            "prim": "TRIS",
            "colors": colors,
            "dtype": dtype,
        }
    return {
        "batch": batch,
        "shader": shader,
        "mode": mode,
        "colors": colors,
        "n": n_tris,
        "prim": "TRIS",
        "dtype": dtype,
    }


def _sample_surface(md, style, rmin, rmax, seed):
    """L0 Surface — identity mesh tris + corner values (no colormap)."""
    with perf.span("overlay.surface_build"):
        built = gpu_sample.build_surface_tris(
            md, style=style, vmin=rmin, vmax=rmax, seed=seed,
        )
    if built is None:
        return None
    positions, corner_values, dtype, n_tris = built
    return {
        "positions": positions,
        "values": corner_values,
        "dtype": dtype,
        "n": n_tris,
    }


def _empty_entry(skey, pkey, bkey):
    """A cache entry that draws nothing.

    Zero samples is a legal state, not an error. The view culler is allowed
    to return nothing when an object leaves the frustum, so every consumer
    downstream of it has to survive that -- see dev_tasks/009.
    """
    return {
        "batch": None, "n": 0, "empty": True,
        "sample_key": skey, "present_key": pkey, "key": pkey,
        "batch_key": bkey, "lut_key": None,
    }


def _refresh_viz(obj, md, display, cap=50000):
    with perf.span(f"overlay.refresh.{display}"):
        return _refresh_viz_impl(obj, md, display, cap=cap)


def _refresh_viz_impl(obj, md, display, cap=50000):
    sock = _socket_bundle(md, obj)
    style = sock["style"] or "Heat"
    density = sock["density"]
    seed = sock["seed"]
    hash_seed = sock.get("hash_seed", seed)
    rmin = None if sock["auto"] else sock["rmin"]
    rmax = None if sock["auto"] else sock["rmax"]

    with perf.span("overlay.cache_key"):
        fp = gpu_sample.watch_fingerprint(md)
        k = overlay_kind.kind(display)
        extra = ("surface",) if k == "surface" else ()
        skey = _sample_key(obj, display, sock, fp)

        # View signature for geometric (upload is view-dependent)
        vsig = ()
        if k == "geometric":
            try:
                region = bpy.context.region
                rv3d = bpy.context.region_data
                if region is not None and rv3d is not None:
                    vsig = overlay_kind.view_signature(
                        rv3d.perspective_matrix, region.width, region.height,
                    )
            except Exception:
                pass
        extra_vsig = extra + vsig
        # dtype_peek: skip ramp hash on id attrs (hash mapper ignores the ramp).
        ptr = obj.as_pointer()
        cached = _caches.get(ptr)
        sample_peek = _sample_caches.get(ptr)
        dtype_peek = None
        if cached is not None and cached.get("sample_key") == skey:
            dtype_peek = cached.get("dtype")
        if (dtype_peek is None and sample_peek is not None
                and sample_peek.get("sample_key") == skey):
            dtype_peek = sample_peek.get("dtype")
        use_ramp = (
            display in ("Markers", "Surface")
            and gpu_color.color_mapper(dtype_peek) == "ramp"
        )
        stops = _stops_for_viz(obj) if use_ramp else None
        rh = gpu_color.ramp_hash(stops) if stops is not None else ()
        # Fallback CPU present key includes ramp so --background recolors.
        # Heat LUT path uses batch_key (no ramp) + lut_key instead.
        pkey = _present_key(display, sock, extra=extra_vsig + (rh,))
        if gpu_color.color_mapper(dtype_peek) == "hash":
            bkey = _id_hash_batch_key(display, extra_vsig)
        else:
            bkey = _heat_batch_key(display, extra_vsig)
        lkey = (rh, sock["auto"], sock["rmin"], sock["rmax"])
        hkey = sock.get("hash_seed", sock["seed"])

    use_lut = (
        _ramp_colormap(display, dtype_peek)
        and _heat_lut_shader_available()
    )
    use_hash = (
        display in ("Markers", "Surface")
        and gpu_color.color_mapper(dtype_peek) == "hash"
        and _id_hash_shader_available()
    )
    if (use_lut
            and cached is not None
            and cached.get("sample_key") == skey
            and cached.get("batch_key") == bkey
            and cached.get("mode") == "heat_lut"):
        if cached.get("lut_key") != lkey:
            with perf.span("overlay.lut_update"):
                _apply_heat_lut(
                    cached, sock, stops, cached.get("scalars"),
                )
        try:
            scale = _float_socket(node_builder.get_input(md, "Scale"), 0.02)
            cached["point_size"] = max(2.0, min(24.0, scale * 250.0))
        except Exception:
            pass
        with perf.span("overlay.cache_hit"):
            return cached
    if (use_hash
            and cached is not None
            and cached.get("sample_key") == skey
            and cached.get("batch_key") == bkey
            and cached.get("mode") == "id_hash"):
        if cached.get("hash_seed") != hkey:
            with perf.span("overlay.hash_seed"):
                cached["hash_seed"] = hkey
        try:
            scale = _float_socket(node_builder.get_input(md, "Scale"), 0.02)
            cached["point_size"] = max(2.0, min(24.0, scale * 250.0))
        except Exception:
            pass
        with perf.span("overlay.cache_hit"):
            return cached
    if (not use_lut and not use_hash
            and cached is not None
            and cached.get("sample_key") == skey
            and cached.get("present_key") == pkey):
        with perf.span("overlay.cache_hit"):
            return cached

    # Reuse L0 sample when only presentation changed (Range / Length / …).
    sample = _sample_caches.get(ptr)
    if sample is None or sample.get("sample_key") != skey:
        with perf.span(f"overlay.sample_miss.{display}"):
            if k == "surface":
                sample = _sample_surface(md, style, rmin, rmax, seed)
            else:
                with perf.span("overlay.sample"):
                    result = gpu_sample.sample_visualizer_targets(
                        md, density=density, seed=seed,
                    )
                if result is None:
                    sample = {
                        "sample_key": skey, "positions": None,
                        "values": None, "dtype": None, "n": 0, "empty": True,
                    }
                else:
                    positions, values, dtype = result
                    sample = {
                        "sample_key": skey,
                        "positions": positions,
                        "values": values,
                        "dtype": dtype,
                        "n": len(positions),
                    }
                    perf.note(f"last_sample_n.{display}", sample["n"])
            if sample is not None:
                sample["sample_key"] = skey
                _sample_caches[ptr] = sample
    else:
        with perf.span("overlay.sample_hit"):
            pass

    if sample is None or sample.get("empty") or sample.get("n", 0) == 0:
        entry = _empty_entry(skey, pkey, bkey)
        _caches[ptr] = entry
        return entry

    # --- View cull for geometric (frustum + frame-center budget) ---
    positions = sample["positions"]
    values = sample["values"]

    if k == "geometric":
        with perf.span("overlay.view_cull"):
            try:
                region = bpy.context.region
                rv3d = bpy.context.region_data
                if region is not None and rv3d is not None:
                    positions, values, _n = overlay_kind.view_cull_geometric(
                        positions, values,
                        rv3d.perspective_matrix,
                        float(region.width), float(region.height),
                        cap=cap,
                    )
            except Exception:
                # --background or missing region: skip view pass
                pass

        # The cull legitimately returns nothing for an off-screen object.
        # Cache an empty entry and skip the present step entirely rather than
        # handing a zero-row buffer to a presenter. bkey folds in the view
        # signature, so this invalidates as soon as the view moves.
        if len(positions) == 0:
            entry = _empty_entry(skey, pkey, bkey)
            _caches[ptr] = entry
            return entry

    with perf.span(f"overlay.present.{display}"):
        if k == "surface":
            entry = _refresh_surface_from_sample(
                sample, style, rmin, rmax, hash_seed, sock=sock, stops=stops,
            )
        elif display == "Arrows":
            entry = _refresh_arrows(
                obj, md, positions, values, sample["dtype"],
            )
        else:
            entry = _refresh_markers(
                obj, md, positions, values, sample["dtype"],
                density, hash_seed, style, rmin, rmax, len(positions),
                sock=sock, stops=stops,
            )

    entry["sample_key"] = skey
    entry["present_key"] = pkey
    entry["batch_key"] = bkey
    entry["lut_key"] = lkey if entry.get("mode") == "heat_lut" else None
    entry["key"] = pkey  # back-compat
    _caches[ptr] = entry
    return entry


def draw_callback_view():
    with perf.span("overlay.draw_callback"):
        _draw_callback_view_impl()


def _draw_gpu_entry(entry):
    """Bind + draw one cached overlay entry (points / tris / instanced)."""
    if entry is None or entry.get("batch") is None:
        return
    with perf.span("overlay.gpu_draw"):
        if entry.get("prim") == "POINTS":
            try:
                gpu.state.point_size_set(float(entry.get("point_size", 5.0)))
            except Exception:
                pass
        shader = entry["shader"]
        shader.bind()
        mode = entry.get("mode")
        if mode in ("heat_lut", "id_hash"):
            try:
                rv3d = bpy.context.region_data
                mvp = rv3d.perspective_matrix if rv3d is not None else None
                if mvp is not None:
                    shader.uniform_float("viewProjectionMatrix", mvp)
                else:
                    shader.uniform_float(
                        "viewProjectionMatrix",
                        gpu.matrix.get_projection_matrix()
                        @ gpu.matrix.get_model_view_matrix(),
                    )
            except Exception:
                shader.uniform_float(
                    "viewProjectionMatrix",
                    gpu.matrix.get_projection_matrix()
                    @ gpu.matrix.get_model_view_matrix(),
                )
            shader.uniform_float(
                "pointSize", float(entry.get("point_size", 5.0)),
            )
            if mode == "heat_lut":
                shader.uniform_float("vmin", float(entry.get("vmin", 0.0)))
                shader.uniform_float("vmax", float(entry.get("vmax", 1.0)))
                shader.uniform_sampler("ramp_tex", entry["ramp_tex"])
            else:
                s = int(entry.get("hash_seed", 0)) & 0xFFFFFFFF
                if s >= 0x80000000:
                    s -= 0x100000000
                shader.uniform_int("seed", s)
            entry["batch"].draw(shader)
            return
        if mode == "instanced":
            try:
                rv3d = bpy.context.region_data
                mvp = rv3d.perspective_matrix if rv3d is not None else None
                if mvp is not None:
                    shader.uniform_float("viewProjectionMatrix", mvp)
                else:
                    shader.uniform_float(
                        "viewProjectionMatrix",
                        gpu.matrix.get_projection_matrix()
                        @ gpu.matrix.get_model_view_matrix(),
                    )
            except Exception:
                shader.uniform_float(
                    "viewProjectionMatrix",
                    gpu.matrix.get_projection_matrix()
                    @ gpu.matrix.get_model_view_matrix(),
                )
            shader.uniform_float("length", float(entry.get("length", 0.08)))
            shader.uniform_float("radius", float(entry.get("radius", 0.007)))
            col = entry.get("uniform_color") or (0.25, 0.65, 1.0, 1.0)
            shader.uniform_float("color", tuple(float(c) for c in col[:4]))
            shader.uniform_sampler("origin_tex", entry["origin_tex"])
            shader.uniform_sampler("dir_tex", entry["dir_tex"])
            entry["batch"].draw_instanced(
                shader, instance_count=int(entry.get("instance_count", 0)),
            )
            return
        if mode == "uniform":
            if entry.get("uniform_color"):
                shader.uniform_float("color", entry["uniform_color"])
            else:
                cols = entry.get("colors")
                if cols is not None and len(cols):
                    mean = cols.mean(axis=0)
                    shader.uniform_float(
                        "color", tuple(float(c) for c in mean))
                else:
                    shader.uniform_float("color", (1.0, 0.5, 0.1, 1.0))
        entry["batch"].draw(shader)


def _viz_domain(md):
    try:
        return node_builder.menu_input_name(md, "Domain")
    except Exception:
        return None


def _split_geometric_depth(rows):
    """(depth-tested, always-on-top) — Instance ink is drawn over the top.

    Split out so the rule is testable without a GPU draw context.
    """
    tested, on_top = [], []
    for row in rows:
        target = (on_top
                  if _viz_domain(row[1]) == node_builder.INSTANCE_DOMAIN
                  else tested)
        target.append(row)
    return tested, on_top


_viz_errors = set()


def reset_viz_errors():
    """Re-arm per-visualizer error reporting (call on re-register / file load)."""
    _viz_errors.clear()


def _note_viz_error(obj, display):
    """Report one traceback per (object, display), not one per redraw.

    The draw handler runs every frame, so an unguarded print here floods the
    console at refresh rate and buries the first -- most useful -- traceback.
    """
    try:
        name = obj.name if obj is not None else "?"
    except Exception:
        name = "?"
    key = (name, display)
    if key in _viz_errors:
        return
    _viz_errors.add(key)
    print(f"AttrViz: visualizer failed on {name!r} ({display}); "
          f"its overlay is skipped, the rest of the pass continues:")
    traceback.print_exc()


def _draw_rows(rows, refresh, draw):
    """Refresh + draw each row, containing per-visualizer failures.

    One misbehaving visualizer must not blank every other object's overlay.
    Split out so the containment rule is testable without a GPU draw context
    (same reason as _split_geometric_depth).

    Returns False if any row raised.
    """
    ok = True
    for obj, md, display in rows:
        try:
            draw(refresh(obj, md, display))
        except Exception:
            ok = False
            _note_viz_error(obj, display)
    return ok


def _draw_callback_view_impl():
    context = bpy.context
    if context.region is None or context.region_data is None:
        return
    scene = context.scene
    if not _scene_gpu_on(scene):
        return

    rows = _gpu_visualizers(scene)
    surfaces = [(o, m, d) for o, m, d in rows
                if overlay_kind.kind(d) == "surface"]
    geometric = [(o, m, d) for o, m, d in rows
                 if overlay_kind.kind(d) == "geometric"]

    gpu.state.depth_test_set('LESS_EQUAL')
    try:
        gpu.state.face_culling_set('BACK')
    except Exception:
        pass

    # GPU state is global. Anything that escapes this block leaves Blender's
    # own drawing with our depth mask / test / face culling for the rest of
    # the frame, so the restore belongs in a finally.
    try:
        gpu.state.depth_mask_set(True)
        _draw_rows(surfaces, _refresh_viz, _draw_gpu_entry)

        try:
            gpu.state.face_culling_set('NONE')
        except Exception:
            pass
        gpu.state.depth_mask_set(False)
        depth_tested, on_top = _split_geometric_depth(geometric)
        _draw_rows(depth_tested, _refresh_viz, _draw_gpu_entry)

        # Instance-domain ink samples the CENTROID of each instance, which is
        # inside the instanced geometry by construction — depth-testing it would
        # hide every marker inside the very object it describes. Draw it over the
        # top instead. Mesh domains keep the depth test: their ink sits on the
        # surface and occlusion is meaningful there.
        if on_top:
            gpu.state.depth_test_set('NONE')
            _draw_rows(on_top, _refresh_viz, _draw_gpu_entry)
    finally:
        try:
            gpu.state.face_culling_set('NONE')
        except Exception:
            pass
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set('NONE')


def _tag_view3d_redraw(*_args):
    """Redraw 3D views so Heat LUT picks up ColorRamp drags.

    The off-engine ramp tree is not a modifier, so stop-moves may not
    depsgraph-evaluate. msgbus → tag_redraw is enough: next draw reads
    stops and does overlay.lut_update (no mesh rebuild).
    """
    if not _scene_gpu_on():
        return
    try:
        wm = bpy.context.window_manager
        if wm is None:
            return
        for window in wm.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except Exception:
        pass


_ramp_msgbus = object()


def _subscribe_ramp_msgbus():
    try:
        bpy.msgbus.clear_by_owner(_ramp_msgbus)
    except Exception:
        pass
    for key in (
        (bpy.types.ColorRampElement, "color"),
        (bpy.types.ColorRampElement, "position"),
        (bpy.types.ColorRamp, "interpolation"),
    ):
        try:
            bpy.msgbus.subscribe_rna(
                key=key,
                owner=_ramp_msgbus,
                args=(),
                notify=_tag_view3d_redraw,
            )
        except Exception:
            pass


def _on_gpu_flag_update(self, context):
    invalidate_all()
    _suppress_gn_carriers(context.scene)
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


class ATTRVIZ_OT_toggle_gpu_markers(bpy.types.Operator):
    bl_idname = "attrviz.toggle_gpu_markers"
    bl_label = "Toggle GPU Overlay"
    bl_description = (
        "Draw Markers/Arrows as unlit Solid GPU ink (no Material Preview)"
    )

    def execute(self, context):
        scene = context.scene
        scene.attrviz_gpu_markers = not bool(scene.attrviz_gpu_markers)
        state = "ON" if scene.attrviz_gpu_markers else "OFF"
        self.report({'INFO'}, f"AttrViz GPU Overlay {state}")
        return {'FINISHED'}


_classes = (ATTRVIZ_OT_toggle_gpu_markers,)


def register():
    global _handle
    for cls in _classes:
        bpy.utils.register_class(cls)
    if not hasattr(bpy.types.Scene, "attrviz_gpu_markers"):
        bpy.types.Scene.attrviz_gpu_markers = bpy.props.BoolProperty(
            name="GPU Overlay",
            description=(
                "Draw Markers / Surface / Arrows as unlit GPU ink in Solid "
                "mode; hides GN carrier meshes; mutes watched mesh/cloud "
                "solid draw (BOUNDS) so overlay is what you see. Tags stay "
                "on the text prototype. Turn off to use the materials/GN path"
            ),
            default=True,
            update=_on_gpu_flag_update,
        )
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback_view, (), 'WINDOW', 'POST_VIEW',
        )

    def _boot_suppress():
        try:
            _suppress_gn_carriers(bpy.context.scene)
        except Exception:
            pass
        return None

    try:
        bpy.app.timers.register(_boot_suppress, first_interval=0.1)
    except Exception:
        pass
    _subscribe_ramp_msgbus()
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister():
    global _handle
    try:
        bpy.msgbus.clear_by_owner(_ramp_msgbus)
    except Exception:
        pass
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
    try:
        restore_all_surface_mutes()
    except Exception:
        pass
    try:
        scene = bpy.context.scene
        if hasattr(scene, "attrviz_gpu_markers"):
            scene.attrviz_gpu_markers = False
            _suppress_gn_carriers(scene)
    except Exception:
        pass
    if hasattr(bpy.types.Scene, "attrviz_gpu_markers"):
        delattr(bpy.types.Scene, "attrviz_gpu_markers")
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    invalidate_all()
