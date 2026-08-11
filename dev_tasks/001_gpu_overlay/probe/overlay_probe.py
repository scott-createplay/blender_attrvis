"""GPU overlay probe — draw handler + sample upload + local toggle.

Phase 2: unlit points in Solid via POST_VIEW. No attrviz imports.
"""
from __future__ import annotations

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from . import color_map, sample

_handle = None
_batch_cache = {
    "key": None,
    "batch": None,
    "shader": None,
    "n": 0,
}


def _prefs(context=None):
    scene = (context or bpy.context).scene
    return scene.probe_gpu_overlay


def _cache_key(obj, attr, domain, n):
    mw = obj.matrix_world
    return (
        obj.as_pointer(), attr, domain, n,
        tuple(mw[i][j] for i in range(4) for j in range(4)),
    )


def _build_batch(positions: np.ndarray, colors: np.ndarray, prim='POINTS'):
    """Vertex-color batch. prim: POINTS or LINES."""
    pos_list = [tuple(p) for p in positions]
    try:
        shader = gpu.shader.from_builtin('SMOOTH_COLOR')
        col_list = [tuple(c) for c in colors]
        batch = batch_for_shader(
            shader, prim, {"pos": pos_list, "color": col_list},
        )
        return batch, shader, "smooth"
    except Exception:
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'POINTS' if prim == 'POINTS' else 'LINES',
                                 {"pos": pos_list})
        return batch, shader, "uniform"


def _vector_line_geometry(positions, values, length=0.15):
    """Build interleaved line endpoints + per-endpoint colors from vectors."""
    v = np.asarray(values, dtype=np.float32)
    if v.ndim == 1 or v.shape[1] < 3:
        return None, None
    n = len(positions)
    norms = np.linalg.norm(v[:, :3], axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-6)
    dirs = v[:, :3] / norms
    starts = positions
    ends = positions + dirs * float(length)
    line_pos = np.empty((n * 2, 3), dtype=np.float32)
    line_pos[0::2] = starts
    line_pos[1::2] = ends
    # color by vector RGB
    cols = color_map.rgb_colors(v) if hasattr(color_map, "rgb_colors") else color_map.values_to_colors(v, 'FLOAT_VECTOR')
    line_cols = np.empty((n * 2, 4), dtype=np.float32)
    line_cols[0::2] = cols
    line_cols[1::2] = cols
    return line_pos, line_cols


def _refresh_cache(context):
    prefs = _prefs(context)
    if not prefs.enabled:
        _batch_cache["batch"] = None
        _batch_cache["key"] = None
        return None

    obj = prefs.target
    if obj is None:
        obj = context.active_object
    if obj is None or obj.type != 'MESH':
        _batch_cache["batch"] = None
        return None

    attr = prefs.attribute or "heat"
    domain = prefs.domain
    result = sample.sample_evaluated(obj, attr, domain)
    if result is None:
        _batch_cache["batch"] = None
        return None

    positions, values, dtype = result
    n = len(positions)
    if n == 0:
        _batch_cache["batch"] = None
        return None

    # Cap for interactive draw (default 50k; stride subsample above)
    cap = max(1, int(prefs.point_cap))
    if n > cap:
        step = int(np.ceil(n / cap))
        positions = positions[::step]
        if values.ndim == 1:
            values = values[::step]
        else:
            values = values[::step, ...]
        n = len(positions)

    draw_vectors = bool(prefs.draw_vectors) and dtype in (
        'FLOAT_VECTOR', 'FLOAT2',
    )
    key = _cache_key(obj, attr, domain, n) + (draw_vectors, prefs.vector_length)
    if key == _batch_cache["key"] and _batch_cache["batch"] is not None:
        return _batch_cache

    if draw_vectors:
        line_pos, line_cols = _vector_line_geometry(
            positions, values, length=prefs.vector_length,
        )
        if line_pos is None:
            draw_vectors = False
        else:
            batch, shader, mode = _build_batch(line_pos, line_cols, prim='LINES')
            _batch_cache.update({
                "key": key,
                "batch": batch,
                "shader": shader,
                "mode": mode,
                "colors": line_cols,
                "n": n,
                "prim": "LINES",
            })
            return _batch_cache

    colors = color_map.values_to_colors(values, dtype)
    batch, shader, mode = _build_batch(positions, colors, prim='POINTS')
    _batch_cache.update({
        "key": key,
        "batch": batch,
        "shader": shader,
        "mode": mode,
        "colors": colors,
        "n": n,
        "prim": "POINTS",
    })
    return _batch_cache


def draw_callback_view():
    context = bpy.context
    if context.region is None or context.region_data is None:
        return
    prefs = _prefs(context)
    if not prefs.enabled:
        return

    cache = _refresh_cache(context)
    if cache is None or cache.get("batch") is None:
        return

    batch = cache["batch"]
    shader = cache["shader"]
    mode = cache.get("mode", "uniform")

    # Phase 3: depth-test against viewport depth (occluded samples hide).
    # Go/no-go: Python LESS_EQUAL is enough for point/line ink on Solid;
    # escalate only if Metal/scale shows systematic Z fighting vs mesh.
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(False)
    try:
        gpu.state.point_size_set(float(prefs.point_size))
    except Exception:
        try:
            gpu.state.point_size = float(prefs.point_size)
        except Exception:
            pass

    shader.bind()
    if mode == "uniform":
        cols = cache.get("colors")
        if cols is not None and len(cols):
            mean = cols.mean(axis=0)
            shader.uniform_float("color", tuple(float(c) for c in mean))
        else:
            shader.uniform_float("color", (1.0, 0.4, 0.1, 1.0))
    batch.draw(shader)

    gpu.state.depth_mask_set(True)
    gpu.state.depth_test_set('NONE')


# ---------------------------------------------------------------------------
# Properties / operators / UI
# ---------------------------------------------------------------------------

class ProbeGPUOverlayProps(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name="Enable Probe Overlay",
        default=False,
        description="Draw unlit attribute points in the 3D View",
        update=lambda self, ctx: _invalidate(),
    )
    target: bpy.props.PointerProperty(
        name="Target",
        type=bpy.types.Object,
        description="Mesh to sample (defaults to active object)",
        update=lambda self, ctx: _invalidate(),
    )
    attribute: bpy.props.StringProperty(
        name="Attribute",
        default="heat",
        update=lambda self, ctx: _invalidate(),
    )
    domain: bpy.props.EnumProperty(
        name="Domain",
        items=(
            ('POINT', "Point", "Vertex domain"),
            ('FACE', "Face", "Face centers"),
        ),
        default='POINT',
        update=lambda self, ctx: _invalidate(),
    )
    point_size: bpy.props.FloatProperty(
        name="Point Size",
        default=6.0,
        min=1.0,
        max=32.0,
    )
    point_cap: bpy.props.IntProperty(
        name="Point Cap",
        default=50000,
        min=100,
        max=2_000_000,
        description="Max points drawn (stride subsample above this)",
        update=lambda self, ctx: _invalidate(),
    )
    draw_vectors: bpy.props.BoolProperty(
        name="Vector Lines",
        default=False,
        description="If attribute is a vector, draw short line segments",
        update=lambda self, ctx: _invalidate(),
    )
    vector_length: bpy.props.FloatProperty(
        name="Vector Length",
        default=0.15,
        min=0.01,
        max=5.0,
        update=lambda self, ctx: _invalidate(),
    )


def _invalidate():
    _batch_cache["key"] = None
    _batch_cache["batch"] = None


class PROBE_OT_toggle(bpy.types.Operator):
    bl_idname = "probe.gpu_overlay_toggle"
    bl_label = "Toggle GPU Overlay Probe"
    bl_description = "Enable/disable unlit attribute point overlay"

    def execute(self, context):
        prefs = context.scene.probe_gpu_overlay
        prefs.enabled = not prefs.enabled
        if prefs.enabled and prefs.target is None and context.active_object:
            prefs.target = context.active_object
        state = "ON" if prefs.enabled else "OFF"
        self.report({'INFO'}, f"Probe overlay {state}")
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'FINISHED'}


class PROBE_OT_use_active(bpy.types.Operator):
    bl_idname = "probe.gpu_overlay_use_active"
    bl_label = "Use Active Object"
    bl_description = "Set probe target to the active mesh"

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'WARNING'}, "Active object is not a mesh")
            return {'CANCELLED'}
        context.scene.probe_gpu_overlay.target = obj
        _invalidate()
        self.report({'INFO'}, f"Probe target → {obj.name}")
        return {'FINISHED'}


class PROBE_PT_panel(bpy.types.Panel):
    bl_label = "GPU Overlay Probe"
    bl_idname = "PROBE_PT_gpu_overlay"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Probe"

    def draw(self, context):
        layout = self.layout
        prefs = context.scene.probe_gpu_overlay
        layout.prop(prefs, "enabled", text="Enabled")
        row = layout.row(align=True)
        row.prop(prefs, "target", text="")
        row.operator("probe.gpu_overlay_use_active", text="", icon='EYEDROPPER')
        layout.prop(prefs, "attribute")
        layout.prop(prefs, "domain")
        layout.prop(prefs, "point_size")
        layout.prop(prefs, "point_cap")
        layout.prop(prefs, "draw_vectors")
        if prefs.draw_vectors:
            layout.prop(prefs, "vector_length")
        if prefs.enabled:
            n = _batch_cache.get("n") or 0
            prim = _batch_cache.get("prim") or "POINTS"
            layout.label(text=f"Drawing {n} ({prim})")


_classes = (
    ProbeGPUOverlayProps,
    PROBE_OT_toggle,
    PROBE_OT_use_active,
    PROBE_PT_panel,
)

addon_keymaps = []


def register():
    global _handle
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.probe_gpu_overlay = bpy.props.PointerProperty(
        type=ProbeGPUOverlayProps,
    )
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback_view, (), 'WINDOW', 'POST_VIEW',
        )
    # keymap: Alt+Shift+P toggle
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
        kmi = km.keymap_items.new(
            PROBE_OT_toggle.bl_idname, 'P', 'PRESS',
            alt=True, shift=True,
        )
        addon_keymaps.append((km, kmi))


def unregister():
    global _handle
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
    if hasattr(bpy.types.Scene, "probe_gpu_overlay"):
        del bpy.types.Scene.probe_gpu_overlay
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    _invalidate()
