"""Tags display — screen-binned labels, instanced cards, BLF text.

POST_PIXEL. Facing = CPU dot(normal, toward_camera). Cap policy = screen-space
bins (spread across the view), not nearest-to-camera. Cards use a unit quad ×
draw_instanced when CreateInfo GPU exists; soup fallback otherwise.

Text is ``blf.draw`` per label (Blender's GPU font path). A glyph atlas was
tried and pulled: UV/layout were wrong. Optimize text after labels look right.
"""
from __future__ import annotations

import math

import blf
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from . import gpu_sample, node_builder, overlay_kind

try:
    from . import perf
except Exception:  # pragma: no cover
    perf = None

_handle = None
_shader = None

_MAX_LABEL_CHARS = 48
_FACING_EPS = 0.05
_SCREEN_PAD = 40.0
_CARD_COLOR = (0.05, 0.05, 0.05, 0.72)

# Viz pointer → {key, positions, values, dtype, nrms}
_sample_cache: dict = {}
# Viz pointer → {key, world: [(wco, text), ...]}  (legacy shape unused)
_label_cache: dict = {}

_card_shader = None
_card_batch = None
_card_instancing_ok = None


def _span(name):
    if perf is None:
        from contextlib import nullcontext
        return nullcontext()
    return perf.span(name)


def _get_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _shader


def invalidate_cache():
    _sample_cache.clear()
    _label_cache.clear()


def _fmt_value(value, dtype, decimals, max_chars=_MAX_LABEL_CHARS):
    if dtype == 'STRING':
        text = gpu_sample.attr_text(value)
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


def _int_socket(val, default):
    """Read an int socket; keep real 0 (``or default`` would drop it)."""
    if val is None:
        return int(default)
    try:
        return int(val)
    except (TypeError, ValueError):
        return int(default)


def facing_keep_mask(pos, nrms, cam, eps=_FACING_EPS):
    """Vectorized facing: keep if dot(normalize(N), normalize(cam-p)) > eps.

    Degenerate normals or toward-vectors are kept (same as the scalar path).
    """
    pos = np.asarray(pos, dtype=np.float64)
    if pos.ndim == 1:
        pos = pos.reshape(1, 3)
    n = len(pos)
    if n == 0:
        return np.empty(0, dtype=bool)
    if nrms is None:
        return np.ones(n, dtype=bool)
    nrms = np.asarray(nrms, dtype=np.float64)
    if nrms.ndim != 2 or nrms.shape[0] != n:
        return np.ones(n, dtype=bool)
    if nrms.shape[1] == 2:
        pad = np.zeros((n, 3), dtype=np.float64)
        pad[:, :2] = nrms
        nrms = pad
    elif nrms.shape[1] < 3:
        return np.ones(n, dtype=bool)
    else:
        nrms = nrms[:, :3]
    cam = np.asarray(cam, dtype=np.float64).reshape(3)
    nlen = np.linalg.norm(nrms, axis=1)
    toward = cam[None, :] - pos[:, :3]
    tlen = np.linalg.norm(toward, axis=1)
    valid = (nlen > 1e-12) & (tlen > 1e-12)
    keep = np.ones(n, dtype=bool)
    if not np.any(valid):
        return keep
    nrm_n = nrms[valid] / nlen[valid, None]
    tow_n = toward[valid] / tlen[valid, None]
    dots = np.einsum("ij,ij->i", nrm_n, tow_n)
    keep[valid] = dots > float(eps)
    return keep


def project_world_to_region(pos, persp, rw, rh):
    """Vectorized location_3d_to_region_2d (perspective_matrix path)."""
    pos = np.asarray(pos, dtype=np.float64)
    if pos.ndim == 1:
        pos = pos.reshape(1, 3)
    n = len(pos)
    if n == 0:
        z = np.empty(0, dtype=np.float64)
        return z, z.copy(), np.empty(0, dtype=bool)
    persp = np.asarray(persp, dtype=np.float64).reshape(4, 4)
    hom = np.empty((n, 4), dtype=np.float64)
    hom[:, :3] = pos[:, :3]
    hom[:, 3] = 1.0
    prj = hom @ persp.T
    w = prj[:, 3]
    valid = w > 1e-12
    sx = np.full(n, np.nan, dtype=np.float64)
    sy = np.full(n, np.nan, dtype=np.float64)
    if np.any(valid):
        inv_w = 1.0 / w[valid]
        sx[valid] = float(rw) * (1.0 + prj[valid, 0] * inv_w) * 0.5
        sy[valid] = float(rh) * (1.0 + prj[valid, 1] * inv_w) * 0.5
    return sx, sy, valid


def screen_bin_select(sx, sy, depth, cap, rw, rh):
    """At most one index per screen cell, ≤ cap, spread across the view.

    When n ≤ cap, all indices are kept (no reason to drop under budget).
    When n > cap, a viewport grid with ~cap cells keeps the nearest-in-cell
    representative; extra occupied cells are stride-subsampled spatially.
    """
    sx = np.asarray(sx, dtype=np.float64).reshape(-1)
    sy = np.asarray(sy, dtype=np.float64).reshape(-1)
    depth = np.asarray(depth, dtype=np.float64).reshape(-1)
    n = int(sx.shape[0])
    cap = int(cap)
    if cap <= 0 or n == 0:
        return np.empty(0, dtype=np.int64)
    if n <= cap:
        return np.arange(n, dtype=np.int64)

    rw = max(float(rw), 1.0)
    rh = max(float(rh), 1.0)
    aspect = rw / rh
    cols = max(1, int(round(math.sqrt(cap * max(aspect, 1e-6)))))
    rows = max(1, int(math.ceil(cap / float(cols))))

    ix = np.clip((sx / rw * cols).astype(np.int64), 0, cols - 1)
    iy = np.clip((sy / rh * rows).astype(np.int64), 0, rows - 1)
    cell = iy * cols + ix
    order = np.lexsort((np.arange(n), depth, cell))
    sorted_cell = cell[order]
    first = np.ones(n, dtype=bool)
    if n > 1:
        first[1:] = sorted_cell[1:] != sorted_cell[:-1]
    picked = order[first]
    n_pick = int(picked.shape[0])
    if n_pick <= cap:
        return np.sort(picked)

    porder = np.argsort(cell[picked], kind="mergesort")
    picked_sorted = picked[porder]
    take_at = (np.arange(cap, dtype=np.int64) * n_pick) // cap
    return np.sort(picked_sorted[take_at])


def _author_attr_sig(md, attr_name, domain_ui):
    """Cheap unevaluated first/mid/last peek so attr edits bust the sample cache."""
    if node_builder.is_intrinsic(attr_name):
        return ("intrinsic", attr_name, domain_ui)
    parts = []
    blender_dom = node_builder.DOMAIN_TO_BLENDER.get(domain_ui, "POINT")
    for obj in gpu_sample.watch_meshes_for_visualizer(md):
        me = getattr(obj, "data", None)
        attr = None if me is None else me.attributes.get(attr_name)
        if attr is None or attr.domain != blender_dom:
            parts.append((obj.as_pointer(), 0))
            continue
        n = len(attr.data)
        if n == 0:
            parts.append((obj.as_pointer(), 0))
            continue

        def _peek(i):
            d = attr.data[i]
            if hasattr(d, "value"):
                return str(d.value)
            if hasattr(d, "vector"):
                return str(tuple(d.vector))
            if hasattr(d, "color"):
                return str(tuple(d.color))
            return "?"

        parts.append((obj.as_pointer(), n, _peek(0), _peek(n // 2), _peek(n - 1)))
    return tuple(parts)


def _sample_tag_world(md, facing_cull):
    """Camera-independent sample: world positions, values, optional normals."""
    try:
        attr_name = node_builder.get_input(md, "Attribute") or ""
        domain_ui = node_builder.menu_input_name(md, "Domain") or "Point"
    except Exception:
        return None
    if not attr_name:
        return None
    meshes = gpu_sample.watch_meshes_for_visualizer(md)
    if not meshes:
        return None

    pos_parts = []
    val_parts = []
    nrm_parts = []
    dtype = None
    want_nrms = bool(facing_cull) and domain_ui in ("Point", "Face", "Corner")

    for obj in meshes:
        result = gpu_sample.sample_evaluated(
            obj, attr_name, domain_ui, world_space=True,
        )
        if result is None:
            continue
        positions, values, dt = result
        n = len(positions)
        if n == 0:
            continue
        if dtype is None:
            dtype = dt
        elif dt != dtype:
            continue
        pos_parts.append(np.asarray(positions, dtype=np.float64))
        val_parts.append(values)
        if want_nrms:
            nr = gpu_sample.sample_evaluated(
                obj, node_builder.NORMAL_ATTR, domain_ui, world_space=True,
            )
            nrms = None
            if nr is not None and nr[2] in ("FLOAT_VECTOR", "FLOAT2"):
                nrms = np.asarray(nr[1], dtype=np.float64)
                if nrms.ndim == 1 or nrms.shape[0] != n:
                    nrms = None
            if nrms is None:
                nrms = np.zeros((n, 3), dtype=np.float64)
            nrm_parts.append(nrms)

    if not pos_parts or dtype is None:
        return None
    positions = np.concatenate(pos_parts, axis=0)
    try:
        values = np.concatenate(val_parts, axis=0)
    except Exception:
        values = np.array(
            [v for part in val_parts for v in part], dtype=object,
        )
    nrms = np.concatenate(nrm_parts, axis=0) if nrm_parts else None
    return positions, values, dtype, nrms


def _cached_sample(obj, md, facing_cull):
    try:
        attr = node_builder.get_input(md, "Attribute") or ""
        domain = node_builder.menu_input_name(md, "Domain") or "Point"
    except Exception:
        attr, domain = "", "Point"
    key = (
        obj.as_pointer(),
        attr,
        domain,
        bool(facing_cull),
        gpu_sample.watch_fingerprint(md),
        _author_attr_sig(md, attr, domain),
    )
    ptr = obj.as_pointer()
    cached = _sample_cache.get(ptr)
    if cached is not None and cached.get("key") == key:
        return cached
    packed = _sample_tag_world(md, facing_cull)
    if packed is None:
        entry = {"key": key, "empty": True}
        _sample_cache[ptr] = entry
        return entry
    positions, values, dtype, nrms = packed
    entry = {
        "key": key,
        "empty": False,
        "positions": positions,
        "values": values,
        "dtype": dtype,
        "nrms": nrms,
    }
    _sample_cache[ptr] = entry
    return entry


def _collect_tags(md, cam_pos, cap, facing_cull):
    """Facing-filtered world samples (no nearest Cap). Cap 0 → []."""
    with _span("tags.collect"):
        return _collect_tags_impl(md, cam_pos, cap, facing_cull)


def _collect_tags_impl(md, cam_pos, cap, facing_cull):
    if int(cap) <= 0:
        return []
    packed = _sample_tag_world(md, facing_cull)
    if packed is None:
        return []
    positions, values, dtype, nrms = packed
    if facing_cull:
        with _span("tags.facing"):
            keep = facing_keep_mask(positions, nrms, cam_pos)
        positions = positions[keep]
        values = values[keep]
    n = len(positions)
    if n == 0:
        return []
    rows = []
    for i in range(n):
        rows.append((positions[i], _value_at(values, i, dtype), dtype))
    return rows


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


def _labels_for_md(obj, md, cam_pos, region, rv3d):
    """Return list of (sx, sy, label_text) in screen space.

    Uses the shared geometric view cull (stochastic weighted by frame
    center proximity) — same ranker as Arrows/Markers. No separate
    screen_bin_select spread.
    """
    try:
        cap = max(0, _int_socket(node_builder.get_input(md, "Tag Cap"), 10000))
        decimals = max(0, _int_socket(node_builder.get_input(md, "Decimals"), 2))
        facing = bool(node_builder.get_input(md, "Facing Cull"))
    except Exception:
        cap, decimals, facing = 10000, 2, False

    if cap <= 0:
        return []

    with _span("tags.collect"):
        sample = _cached_sample(obj, md, facing)
    if sample.get("empty"):
        return []
    positions = sample["positions"]
    values = sample["values"]
    dtype = sample["dtype"]
    nrms = sample["nrms"]
    if len(positions) == 0:
        return []

    cam = np.asarray(cam_pos, dtype=np.float64)
    if facing:
        with _span("tags.facing"):
            keep = facing_keep_mask(positions, nrms, cam)
        if not np.any(keep):
            return []
        positions = positions[keep]
        values = values[keep]

    rw, rh = float(region.width), float(region.height)
    persp = rv3d.perspective_matrix

    # Shared geometric view cull — same stochastic ranker as Arrows/Markers
    with _span("tags.view_cull"):
        positions, values, n_kept = overlay_kind.view_cull_geometric(
            positions, values, persp, rw, rh, cap=cap,
        )
    if n_kept == 0:
        return []

    # Project kept set to screen for label placement + depth for occlusion
    with _span("tags.project"):
        persp_np = np.array(persp, dtype=np.float64).reshape(4, 4)
        sx, sy, valid = project_world_to_region(positions, persp_np, rw, rh)

        # Compute NDC depth for occlusion testing
        hom = np.ones((len(positions), 4), dtype=np.float64)
        hom[:, :3] = positions
        prj = hom @ persp_np.T
        w_clip = prj[:, 3]
        w_safe = np.where(w_clip > 1e-12, w_clip, 1.0)
        ndc_z = (prj[:, 2] / w_safe) * 0.5 + 0.5

        # Filter invalid
        if not np.all(valid):
            mask = valid
            sx, sy, ndc_z = sx[mask], sy[mask], ndc_z[mask]
            values = values[mask]

    screen = []
    for i in range(len(sx)):
        text = _fmt_value(_value_at(values, int(i), dtype), dtype, decimals)
        screen.append((float(sx[i]), float(sy[i]), float(ndc_z[i]), text))
    return screen


# --- Instanced card quads -------------------------------------------------

def _mvp_pixel():
    return (
        gpu.matrix.get_projection_matrix()
        @ gpu.matrix.get_model_view_matrix()
    )


def _float_tex_rgba(rows: np.ndarray):
    """Metal-safe 2D pack for card instance data. Delegates to shared helper."""
    tex, _w = overlay_kind.pack_texture_2d(rows)
    return tex


def _get_card_shader():
    global _card_shader
    if _card_shader is not None:
        return _card_shader
    info = gpu.types.GPUShaderCreateInfo()
    info.vertex_in(0, "VEC2", "pos")
    info.sampler(0, "FLOAT_2D", "inst_tex")
    info.push_constant("MAT4", "ModelViewProjectionMatrix")
    info.push_constant("VEC4", "color")
    info.fragment_out(0, "VEC4", "fragColor")
    info.vertex_source(
        "void main()\n"
        "{\n"
        "  int W = textureSize(inst_tex, 0).x;\n"
        "  ivec2 uv = ivec2(gl_InstanceID % W, gl_InstanceID / W);\n"
        "  vec4 inst = texelFetch(inst_tex, uv, 0);\n"
        "  vec2 xy = inst.xy + pos * inst.zw;\n"
        "  gl_Position = ModelViewProjectionMatrix * vec4(xy, 0.0, 1.0);\n"
        "}\n"
    )
    info.fragment_source(
        "void main()\n"
        "{\n"
        "  fragColor = color;\n"
        "}\n"
    )
    _card_shader = gpu.shader.create_from_info(info)
    return _card_shader


def _get_card_batch(shader):
    global _card_batch
    if _card_batch is not None:
        return _card_batch
    pos = (
        (-0.5, -0.5), (0.5, -0.5), (0.5, 0.5),
        (-0.5, -0.5), (0.5, 0.5), (-0.5, 0.5),
    )
    _card_batch = batch_for_shader(shader, "TRIS", {"pos": pos})
    return _card_batch


def _card_instancing_available() -> bool:
    global _card_instancing_ok
    if _card_instancing_ok is not None:
        return bool(_card_instancing_ok)
    try:
        _get_card_shader()
        _card_instancing_ok = True
    except Exception:
        _card_instancing_ok = False
    return bool(_card_instancing_ok)


def _draw_cards_batched(shader, cards):
    """cards: list of (cx, cy, w, h). One GPUBatch for all quads (soup)."""
    if not cards:
        return
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
        shader, "TRIS", {"pos": coords}, indices=indices,
    )
    shader.bind()
    shader.uniform_float("color", _CARD_COLOR)
    batch.draw(shader)


def _draw_cards_instanced(cards):
    n = len(cards)
    rows = np.empty((n, 4), dtype=np.float32)
    for i, (cx, cy, w, h) in enumerate(cards):
        rows[i] = (cx, cy, w, h)
    shader = _get_card_shader()
    batch = _get_card_batch(shader)
    tex = _float_tex_rgba(rows)
    shader.bind()
    shader.uniform_float("ModelViewProjectionMatrix", _mvp_pixel())
    shader.uniform_float("color", _CARD_COLOR)
    shader.uniform_sampler("inst_tex", tex)
    batch.draw_instanced(shader, instance_count=n)


def _draw_cards(cards):
    if not cards:
        return
    with _span("tags.draw_cards"):
        if _card_instancing_available():
            try:
                _draw_cards_instanced(cards)
                return
            except Exception:
                pass
        _draw_cards_batched(_get_shader(), cards)


def draw_callback_px():
    context = bpy.context
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return

    cam_pos = rv3d.view_matrix.inverted().translation
    gpu.state.blend_set("ALPHA")
    font_id = 0

    # Read depth buffer once per frame (fast path: ~2ms)
    with _span("tags.depth_read"):
        depth_arr = overlay_kind.read_depth_buffer()

    for obj, md in _tag_visualizers():
        try:
            size = max(0, _int_socket(node_builder.get_input(md, "Tag Size"), 14))
            color = node_builder.get_input(md, "Tag Color")
        except Exception:
            continue

        screen = _labels_for_md(obj, md, cam_pos, region, rv3d)
        if not screen or size <= 0:
            continue

        # Depth occlusion: skip tags behind scene geometry
        if depth_arr is not None:
            with _span("tags.occlusion"):
                sx_arr = np.array([s[0] for s in screen], dtype=np.float32)
                sy_arr = np.array([s[1] for s in screen], dtype=np.float32)
                z_arr = np.array([s[2] for s in screen], dtype=np.float32)
                visible = overlay_kind.occlusion_filter(
                    sx_arr, sy_arr, z_arr, depth_arr,
                )
                screen = [s for s, v in zip(screen, visible) if v]
            if not screen:
                continue

        blf.size(font_id, max(6, size))
        blf.color(
            font_id,
            float(color[0]), float(color[1]), float(color[2]), 1.0,
        )

        pad_x, pad_y = 6.0, 4.0
        cards = []
        draw_text = []
        for sx, sy, _z, label in screen:
            tw, th = blf.dimensions(font_id, label)
            cards.append((sx, sy, tw + pad_x * 2, th + pad_y * 2))
            draw_text.append((sx, sy, tw, th, label))

        _draw_cards(cards)

        with _span("tags.draw_text"):
            for sx, sy, tw, th, label in draw_text:
                blf.position(font_id, sx - tw * 0.5, sy - th * 0.35, 0)
                blf.draw(font_id, label)

    gpu.state.blend_set("NONE")


def register():
    global _handle
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback_px, (), "WINDOW", "POST_PIXEL")


def unregister():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    invalidate_cache()
