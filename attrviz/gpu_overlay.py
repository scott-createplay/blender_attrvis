"""AttrViz GPU overlay — Solid-mode unlit Markers / Surface / Arrows.

POST_VIEW draw handler. Behind scene.attrviz_gpu_markers (default off)
so GN+materials remain the default until validated.

Markers → points. Surface → false-color mesh tris.
Arrows → batched 4-sided cones (non-vector → draw nothing).
Tags stay on the BLF prototype.
"""
from __future__ import annotations

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from . import gpu_color, gpu_sample, node_builder

_handle = None
_caches: dict = {}

VECTORISH = frozenset({'FLOAT_VECTOR', 'FLOAT2'})
GPU_DISPLAYS = frozenset({"Markers", "Surface", "Arrows"})


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
    """When GPU overlay on, hide GN carrier mesh for Markers/Surface/Arrows."""
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


def _arrow_cone_geometry(positions, values, length: float, radius: float,
                         sides: int = 4):
    """Batched N-sided cones: base at sample, tip along vector.

    Returns (tri_verts Mx3, n_arrows) with M = n_arrows * sides * 3.
    """
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
        scale = float(node_builder.get_input(md, "Scale") or 0.02)
        acol = node_builder.get_input(md, "Arrow Color")
        if acol is not None:
            acol = tuple(float(c) for c in acol[:4])
        else:
            acol = (0.2, 0.6, 1.0, 1.0)
    except Exception:
        attr, domain, style = "", "Point", "Heat"
        density, seed, auto, rmin, rmax = 1.0, 0, True, 0.0, 1.0
        length, scale, acol = 0.08, 0.02, (0.2, 0.6, 1.0, 1.0)
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
        auto, rmin, rmax, length, scale, acol, n, tw, extra,
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
        return {"batch": None, "n": 0, "prim": "TRIS", "empty": True}
    try:
        length = float(node_builder.get_input(md, "Length") or 0.08)
        scale = float(node_builder.get_input(md, "Scale") or 0.02)
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

    cone_pos, n_alive = _arrow_cone_geometry(
        positions, values, length, radius, sides=4,
    )
    if cone_pos is None or n_alive == 0:
        return {"batch": None, "n": 0, "prim": "TRIS", "empty": True}

    colors = np.tile(np.array(color, dtype=np.float32), (len(cone_pos), 1))
    try:
        batch, shader, mode = _build_batch(cone_pos, colors, prim='TRIS')
    except Exception:
        return {
            "batch": None,
            "n": n_alive,
            "prim": "TRIS",
            "uniform_color": color,
            "cone_verts": len(cone_pos),
        }
    return {
        "batch": batch,
        "shader": shader,
        "mode": mode,
        "colors": colors,
        "n": n_alive,
        "prim": "TRIS",
        "uniform_color": color,
    }


def _refresh_surface(obj, md, style, rmin, rmax, seed):
    built = gpu_sample.build_surface_tris(
        md, style=style, vmin=rmin, vmax=rmax, seed=seed,
    )
    if built is None:
        return {"batch": None, "n": 0, "prim": "TRIS", "empty": True}
    positions, colors, dtype, n_tris = built
    if n_tris == 0:
        return {"batch": None, "n": 0, "prim": "TRIS", "empty": True}
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
    except Exception:
        density, seed, style = 1.0, 0, "Heat"
        rmin, rmax = None, None

    if display == "Surface":
        # Cache key from attr/domain/style; n from built tris
        key = _viz_cache_key(obj, md, display, 0, extra=("surface", style))
        cached = _caches.get(obj.as_pointer())
        if cached and cached.get("key") == key and (
                cached.get("batch") is not None or cached.get("empty")):
            return cached
        entry = _refresh_surface(obj, md, style, rmin, rmax, seed)
        # Rebuild key with real tri count
        entry["key"] = _viz_cache_key(
            obj, md, display, entry.get("n", 0), extra=("surface", style))
        _caches[obj.as_pointer()] = entry
        return entry

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

    rows = _gpu_visualizers(scene)
    # Surfaces first (write depth), then points/lines (test only)
    surfaces = [(o, m, d) for o, m, d in rows if d == "Surface"]
    others = [(o, m, d) for o, m, d in rows if d != "Surface"]

    gpu.state.depth_test_set('LESS_EQUAL')

    gpu.state.depth_mask_set(True)
    for obj, md, display in surfaces:
        entry = _refresh_viz(obj, md, display)
        if entry is None or entry.get("batch") is None:
            continue
        shader = entry["shader"]
        shader.bind()
        if entry.get("mode") == "uniform":
            cols = entry.get("colors")
            if cols is not None and len(cols):
                mean = cols.mean(axis=0)
                shader.uniform_float("color", tuple(float(c) for c in mean))
        entry["batch"].draw(shader)

    gpu.state.depth_mask_set(False)
    for obj, md, display in others:
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
                "Draw Markers / Surface / Arrows as unlit GPU ink in Solid "
                "mode; hides GN carrier meshes. Tags stay on the text "
                "prototype. Materials path remains when this is off"
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
