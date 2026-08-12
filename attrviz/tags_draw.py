"""Tags display — BLF text overlays (semantic strings OK).

Steps 1–2 toward the GPU overlay stack:
  - Shared ``gpu_sample`` for Target∪Scope + STRING attrs
  - Facing cull + distance-priority Tag Cap (count of labels)
  - Screen-bounds cull, label cache, one batched card mesh
  - BLF remains the text path (semantic labels); atlas is Step 3

Still ``POST_PIXEL`` for BLF. Depth awareness here = facing + nearest-N
(true buffer depth needs atlas/compiled follow-on).

Hot path is still Python — acceptable for a capped inspect tool.
Direction of travel: dynamic glyph atlas, then compiled overlay if needed.
"""
from __future__ import annotations

import blf
import bpy
import gpu
import numpy as np
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader

from . import gpu_sample, node_builder

_handle = None
_shader = None

# Soft display truncate for long semantic strings (not Tag Cap).
_MAX_LABEL_CHARS = 48

# Cache: md_ptr -> {key, labels: [(wco, text), ...]}
_label_cache: dict = {}


def _get_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _shader


def invalidate_cache():
    _label_cache.clear()


def _fmt_value(value, dtype, decimals, max_chars=_MAX_LABEL_CHARS):
    if dtype == 'STRING':
        text = str(value)
    elif dtype in ('INT', 'BOOLEAN', 'INT8'):
        try:
            text = str(int(value))
        except Exception:
            text = str(value)
    elif dtype in ('FLOAT_VECTOR', 'FLOAT2'):
        try:
            comps = tuple(float(c) for c in value)
            text = "(" + ", ".join(f"{c:.{decimals}f}" for c in comps) + ")"
        except Exception:
            text = str(value)
    else:
        try:
            text = f"{float(value):.{decimals}f}"
        except Exception:
            text = str(value)
    if max_chars > 0 and len(text) > max_chars:
        return text[: max(1, max_chars - 1)] + "…"
    return text


def _value_at(values, i, dtype):
    v = values[i]
    if dtype in ('FLOAT_VECTOR', 'FLOAT2', 'FLOAT_COLOR', 'BYTE_COLOR'):
        return v
    if dtype == 'STRING':
        return v
    try:
        return v.item() if hasattr(v, "item") else v
    except Exception:
        return v


def _collect_tags(md, cam_pos, cap, facing_cull):
    """Nearest-first capped tags via shared gpu_sample (Target∪Scope)."""
    try:
        target = node_builder.get_input(md, "Target")
        scope = node_builder.get_input(md, "Scope")
        attr_name = node_builder.get_input(md, "Attribute") or ""
        domain_ui = node_builder.menu_input_name(md, "Domain") or "Point"
    except Exception:
        return []
    if not attr_name:
        return []

    meshes = gpu_sample.iter_watch_meshes(target, scope)
    if not meshes:
        return []

    cam = np.array(cam_pos, dtype=np.float64)
    rows = []  # (dist_sq, x, y, z, value_index_pack)
    # Store as list of (d2, wco_tuple, value, dtype) — values may be object

    for obj in meshes:
        result = gpu_sample.sample_evaluated(
            obj, attr_name, domain_ui, world_space=True,
        )
        if result is None:
            continue
        positions, values, dtype = result
        n = len(positions)
        if n == 0:
            continue

        nrms = None
        if facing_cull and domain_ui in ("Point", "Face", "Corner"):
            nr = gpu_sample.sample_evaluated(
                obj, node_builder.NORMAL_ATTR, domain_ui, world_space=True,
            )
            if nr is not None and nr[2] in ('FLOAT_VECTOR', 'FLOAT2'):
                nrms = np.asarray(nr[1], dtype=np.float64)
                if nrms.ndim == 1:
                    nrms = None
                elif nrms.shape[0] != n:
                    nrms = None

        pos = np.asarray(positions, dtype=np.float64)
        for i in range(n):
            wco = pos[i]
            if nrms is not None:
                nrm = nrms[i]
                ln = np.linalg.norm(nrm)
                if ln > 1e-12:
                    nrm = nrm / ln
                    toward = cam - wco
                    tl = np.linalg.norm(toward)
                    if tl > 1e-12:
                        toward = toward / tl
                        if float(nrm.dot(toward)) <= 0.05:
                            continue
            delta = wco - cam
            d2 = float(delta.dot(delta))
            rows.append((d2, wco, _value_at(values, i, dtype), dtype))

    if not rows:
        return []
    rows.sort(key=lambda r: r[0])
    return [(wco, val, dt) for _d, wco, val, dt in rows[:cap]]


def _tag_visualizers():
    from . import visualizers, viz_modifier
    scene = bpy.context.scene
    if scene is None:
        return []
    rows = []
    for obj in visualizers(scene):
        if obj.hide_viewport:
            continue
        md = viz_modifier(obj)
        if md is None:
            continue
        try:
            if node_builder.menu_input_name(md, "Display") != "Tags":
                continue
        except Exception:
            continue
        rows.append((obj, md))
    return rows


def _cache_key(obj, md, cap, decimals, facing, elements):
    try:
        attr = node_builder.get_input(md, "Attribute")
        domain = node_builder.menu_input_name(md, "Domain")
        target = node_builder.get_input(md, "Target")
    except Exception:
        attr, domain, target = "", "Point", None
    tw = ()
    if target is not None:
        mw = target.matrix_world
        tw = tuple(round(mw[i][j], 5) for i in range(4) for j in range(4))
    n = len(elements)
    # Cheap value signature so attr edits invalidate without full hash.
    sig = n
    if n:
        sig = (n, str(elements[0][1]), str(elements[n // 2][1]),
               str(elements[-1][1]))
    return (obj.as_pointer(), attr, domain, cap, decimals, facing, sig, tw)


def _labels_for_md(obj, md, cam_pos, region, rv3d):
    """Return list of (sx, sy, label_text) in screen space."""
    try:
        cap = max(1, int(node_builder.get_input(md, "Tag Cap") or 10000))
        decimals = int(node_builder.get_input(md, "Decimals") or 2)
        facing = bool(node_builder.get_input(md, "Facing Cull"))
    except Exception:
        cap, decimals, facing = 10000, 2, False

    elements = _collect_tags(md, cam_pos, cap, facing)
    key = _cache_key(obj, md, cap, decimals, facing, elements)
    cached = _label_cache.get(obj.as_pointer())

    # Rebuild world labels if config/sample changed; always re-project
    # (camera move) from cached (wco, text) pairs when possible.
    world_labels = None
    if cached and cached.get("key") == key:
        world_labels = cached.get("world")

    if world_labels is None:
        world_labels = []
        for wco, value, dt in elements:
            text = _fmt_value(value, dt, decimals)
            world_labels.append((np.asarray(wco, dtype=np.float64), text))
        _label_cache[obj.as_pointer()] = {
            "key": key,
            "world": world_labels,
        }

    screen = []
    rw, rh = region.width, region.height
    for wco, text in world_labels:
        pt = location_3d_to_region_2d(region, rv3d, wco)
        if pt is None:
            continue
        # Screen-bounds cull (with small pad)
        if pt.x < -40 or pt.y < -40 or pt.x > rw + 40 or pt.y > rh + 40:
            continue
        screen.append((float(pt.x), float(pt.y), text))
    return screen


def _draw_cards_batched(shader, cards):
    """cards: list of (cx, cy, w, h). One GPUBatch for all quads."""
    if not cards:
        return
    # 4 verts per card, 2 tris
    n = len(cards)
    coords = []
    indices = []
    for i, (cx, cy, w, h) in enumerate(cards):
        x0, y0 = cx - w * 0.5, cy - h * 0.5
        x1, y1 = cx + w * 0.5, cy + h * 0.5
        base = i * 4
        coords.extend(((x0, y0), (x1, y0), (x1, y1), (x0, y1)))
        indices.extend(((base, base + 1, base + 2),
                        (base, base + 2, base + 3)))
    batch = batch_for_shader(
        shader, 'TRIS', {"pos": coords}, indices=indices,
    )
    shader.bind()
    shader.uniform_float("color", (0.05, 0.05, 0.05, 0.72))
    batch.draw(shader)


def draw_callback_px():
    context = bpy.context
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return

    cam_pos = rv3d.view_matrix.inverted().translation
    shader = _get_shader()
    gpu.state.blend_set('ALPHA')
    font_id = 0

    for obj, md in _tag_visualizers():
        try:
            size = int(node_builder.get_input(md, "Tag Size") or 14)
            color = node_builder.get_input(md, "Tag Color")
        except Exception:
            continue

        screen = _labels_for_md(obj, md, cam_pos, region, rv3d)
        if not screen:
            continue

        blf.size(font_id, max(6, size))
        blf.color(font_id, float(color[0]), float(color[1]),
                  float(color[2]), 1.0)

        pad_x, pad_y = 6.0, 4.0
        cards = []
        draw_text = []
        for sx, sy, label in screen:
            tw, th = blf.dimensions(font_id, label)
            cards.append((sx, sy, tw + pad_x * 2, th + pad_y * 2))
            draw_text.append((sx, sy, tw, th, label))

        _draw_cards_batched(shader, cards)

        for sx, sy, tw, th, label in draw_text:
            blf.position(font_id, sx - tw * 0.5, sy - th * 0.35, 0)
            blf.draw(font_id, label)

    gpu.state.blend_set('NONE')


def register():
    global _handle
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback_px, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
    invalidate_cache()
