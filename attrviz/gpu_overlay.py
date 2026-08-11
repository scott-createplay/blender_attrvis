"""AttrViz GPU overlay — Solid-mode unlit Markers + Arrows (Stage B).

POST_VIEW draw handler. Behind scene.attrviz_gpu_markers (default off)
so GN+materials remain the default until validated.

Markers → colored points. Arrows → short lines from vector attrs
(non-vector → draw nothing; honesty rule from 0.5.x).
"""
from __future__ import annotations

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from . import gpu_color, gpu_sample, node_builder

_handle = None
# cache keyed per visualizer object pointer
_caches: dict = {}

VECTORISH = frozenset({'FLOAT_VECTOR', 'FLOAT2'})
GPU_DISPLAYS = frozenset({"Markers", "Arrows"})


def _scene_gpu_on(scene=None) -> bool:
    scene = scene or bpy.context.scene
    return bool(getattr(scene, "attrviz_gpu_markers", False))


def invalidate_all():
    _caches.clear()


def _gpu_visualizers(scene):
    from . import visualizers, viz_modifier
    rows = []
    for obj in visualizers(scene):
        if obj.hide_viewport:
            continue
        md = viz_modifier(obj)
        if md is None:
            continue
        try:
            display = node_builder.menu_input_name(md, "Display")
        except Exception:
            continue
        if display not in GPU_DISPLAYS:
            continue
        rows.append((obj, md, display))
    return rows


def _suppress_gn_carriers(scene):
    """When GPU overlay on, hide GN carrier mesh for Markers/Arrows."""
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
        if display not in GPU_DISPLAYS:
            continue
        enabled = not obj.hide_viewport
        if use_gpu and enabled:
            if md.show_viewport:
                md.show_viewport = False
        elif enabled and not md.show_viewport:
            md.show_viewport = True


# Back-compat alias
_suppress_gn_markers = _suppress_gn_carriers


def _build_batch(positions, colors, prim='POINTS'):
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
        batch = batch_for_shader(
            shader, prim, {"pos": pos_list},
        )
        return batch, shader, "uniform"


def _arrow_line_geometry(positions, values, length: float):
    """Interleaved line endpoints from vector field. Drops near-zero."""
    v = np.asarray(values, dtype=np.float32)
    if v.ndim != 2 or v.shape[1] < 2:
        return None, None
    # pad FLOAT2 to 3
    if v.shape[1] == 2:
        v3 = np.zeros((len(v), 3), dtype=np.float32)
        v3[:, :2] = v
        v = v3
    else:
        v = v[:, :3]
    norms = np.linalg.norm(v, axis=1)
    alive = norms > 1e-8
    if not np.any(alive):
        return None, None
    positions = positions[alive]
    v = v[alive]
    norms = norms[alive]
    dirs = v / norms[:, None]
    n = len(positions)
    starts = positions
    ends = positions + dirs * float(length)
    line_pos = np.empty((n * 2, 3), dtype=np.float32)
    line_pos[0::2] = starts
    line_pos[1::2] = ends
    return line_pos, n


def _viz_cache_key(obj, md, display, n, extra=()):
    try:
        attr = node_builder.get_input(md, "Attribute")
        domain = node_builder.menu_input_name(md, "Domain")
        style = node_builder.menu_input_name(md, "Style")
        density = float(node_builder.get_input(md, "Density") or 1.0)
        seed = int(node_builder.get_input(md, "Seed") or 0)
        auto = bool(node_builder.get_input(md, "Auto Range"))
        rmin = float(node_builder.get_input(md, "Range Min") or 0.0)
        rmax = float(node_builder.get_input(md, "Range Max") or 1.0)
        length = float(node_builder.get_input(md, "Length") or 0.08)
        acol = node_builder.get_input(md, "Arrow Color")
        if acol is not None:
            acol = tuple(float(c) for c in acol[:4])
        else:
            acol = (0.2, 0.6, 1.0, 1.0)
    except Exception:
        attr, domain, style = "", "Point", "Heat"
        density, seed, auto, rmin, rmax = 1.0, 0, True, 0.0, 1.0
        length, acol = 0.08, (0.2, 0.6, 1.0, 1.0)
    target = None
    try:
        target = node_builder.get_input(md, "Target")
    except Exception:
        pass
    tw = ()
    if target is not None:
        mw = target.matrix_world
        tw = tuple(mw[i][j] for i in range(4) for j in range(4))
    return (
        obj.as_pointer(), display, attr, domain, style, density, seed,
        auto, rmin, rmax, length, acol, n, tw, extra,
    )


def _refresh_markers(obj, md, positions, values, dtype, density, seed,
                     style, rmin, rmax, cap_key_n):
    colors = gpu_color.values_to_colors(
        values, dtype, style, vmin=rmin, vmax=rmax, seed=seed,
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
    }
    try:
        scale = float(node_builder.get_input(md, "Scale") or 0.02)
        entry["point_size"] = max(2.0, min(24.0, scale * 250.0))
    except Exception:
        pass
    return entry


def _refresh_arrows(obj, md, positions, values, dtype):
    # Honesty: non-vector → nothing
    if dtype not in VECTORISH:
        return {"batch": None, "n": 0, "prim": "LINES", "empty": True}
    try:
        length = float(node_builder.get_input(md, "Length") or 0.08)
        acol = node_builder.get_input(md, "Arrow Color")
        if acol is not None and len(acol) >= 3:
            color = (
                float(acol[0]), float(acol[1]), float(acol[2]),
                float(acol[3]) if len(acol) > 3 else 1.0,
            )
        else:
            color = (0.25, 0.65, 1.0, 1.0)
    except Exception:
        length, color = 0.08, (0.25, 0.65, 1.0, 1.0)

    line_pos, n_alive = _arrow_line_geometry(positions, values, length)
    if line_pos is None:
        return {"batch": None, "n": 0, "prim": "LINES", "empty": True}

    colors = np.tile(np.array(color, dtype=np.float32), (len(line_pos), 1))
    try:
        batch, shader, mode = _build_batch(line_pos, colors, prim='LINES')
    except Exception:
        # Headless / no GPU context — geometry still valid
        return {
            "batch": None,
            "n": n_alive,
            "prim": "LINES",
            "uniform_color": color,
            "line_verts": len(line_pos),
        }
    return {
        "batch": batch,
        "shader": shader,
        "mode": mode,
        "colors": colors,
        "n": n_alive,
        "prim": "LINES",
        "uniform_color": color,
    }


def _refresh_viz(obj, md, display, cap=50000):
    try:
        density = float(node_builder.get_input(md, "Density") or 1.0)
        seed = int(node_builder.get_input(md, "Seed") or 0)
        style = node_builder.menu_input_name(md, "Style") or "Heat"
        auto = bool(node_builder.get_input(md, "Auto Range"))
        rmin = None if auto else float(
            node_builder.get_input(md, "Range Min") or 0.0)
        rmax = None if auto else float(
            node_builder.get_input(md, "Range Max") or 1.0)
        length = float(node_builder.get_input(md, "Length") or 0.08)
    except Exception:
        density, seed, style = 1.0, 0, "Heat"
        rmin, rmax, length = None, None, 0.08

    result = gpu_sample.sample_visualizer_targets(
        md, density=density, seed=seed, cap=cap,
    )
    if result is None:
        return None
    positions, values, dtype = result
    n = len(positions)
    if n == 0:
        return None

    key = _viz_cache_key(obj, md, display, n, extra=(dtype,))
    cached = _caches.get(obj.as_pointer())
    if cached and cached.get("key") == key and (
            cached.get("batch") is not None or cached.get("empty")):
        return cached

    if display == "Arrows":
        entry = _refresh_arrows(obj, md, positions, values, dtype)
    else:
        entry = _refresh_markers(
            obj, md, positions, values, dtype, density, seed,
            style, rmin, rmax, n,
        )
    entry["key"] = key
    _caches[obj.as_pointer()] = entry
    return entry


def draw_callback_view():
    context = bpy.context
    if context.region is None or context.region_data is None:
        return
    scene = context.scene
    if not _scene_gpu_on(scene):
        return

    _suppress_gn_carriers(scene)

    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(False)

    for obj, md, display in _gpu_visualizers(scene):
        entry = _refresh_viz(obj, md, display)
        if entry is None or entry.get("batch") is None:
            continue
        if entry.get("prim") == "POINTS":
            try:
                gpu.state.point_size_set(float(entry.get("point_size", 5.0)))
            except Exception:
                pass
        shader = entry["shader"]
        shader.bind()
        if entry.get("mode") == "uniform":
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

    gpu.state.depth_mask_set(True)
    gpu.state.depth_test_set('NONE')


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
                "Draw Markers (points) and Arrows (lines) as unlit GPU ink "
                "in Solid mode; hides GN carrier meshes. Materials path "
                "remains for other Displays and when this is off"
            ),
            default=False,
            update=_on_gpu_flag_update,
        )
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback_view, (), 'WINDOW', 'POST_VIEW',
        )


def unregister():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
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
