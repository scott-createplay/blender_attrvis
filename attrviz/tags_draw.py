"""Tags display prototype — GPU sprites + text (not GN mesh text).

Direction of travel: compiled display plugin (atlas shader, depth
occlusion). This prototype validates domain sampling / cap / facing
cull / screen-space sprite cards via Blender's gpu + blf modules.

Hot path is still Python here — acceptable for a capped prototype only.
"""
from __future__ import annotations

import blf
import bpy
import gpu
import mathutils
import numpy as np
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader

from . import node_builder

_handle = None
_shader = None


def _get_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _shader


def _fmt_value(value, dtype, decimals):
    if dtype in ('INT', 'BOOLEAN', 'INT8'):
        try:
            return str(int(value))
        except Exception:
            return str(value)
    if dtype in ('FLOAT_VECTOR', 'FLOAT2'):
        try:
            comps = tuple(float(c) for c in value)
            return "(" + ", ".join(f"{c:.{decimals}f}" for c in comps) + ")"
        except Exception:
            return str(value)
    try:
        return f"{float(value):.{decimals}f}"
    except Exception:
        return str(value)


def _read_attr_values(me, name, domain, n):
    attr = me.attributes.get(name)
    if attr is None or attr.domain != domain:
        return None, None
    dt = attr.data_type
    if dt == 'FLOAT':
        a = np.empty(n, dtype=np.float32)
        attr.data.foreach_get("value", a)
        return a, dt
    if dt in ('INT', 'BOOLEAN', 'INT8'):
        a = np.empty(n, dtype=np.int32)
        try:
            attr.data.foreach_get("value", a)
        except Exception:
            a = np.array([int(d.value) for d in attr.data], dtype=np.int32)
        return a, dt
    if dt in ('FLOAT_VECTOR', 'FLOAT2'):
        width = 3 if dt == 'FLOAT_VECTOR' else 2
        a = np.empty(n * width, dtype=np.float32)
        attr.data.foreach_get("vector", a)
        return a.reshape(-1, width), dt
    if dt in ('FLOAT_COLOR', 'BYTE_COLOR'):
        a = np.empty(n * 4, dtype=np.float32)
        attr.data.foreach_get("color", a)
        return a.reshape(-1, 4), dt
    return None, dt


def _read_intrinsic_values(me, name, domain_ui, cos=None):
    """Index / Position / Normal from evaluated mesh APIs (not attributes)."""
    n_map = {
        "Point": len(me.vertices),
        "Edge": len(me.edges),
        "Face": len(me.polygons),
        "Corner": len(me.loops),
    }
    n = n_map.get(domain_ui, 0)
    if n == 0:
        return None, None

    if name == node_builder.INDEX_ATTR:
        return np.arange(n, dtype=np.int32), 'INT'

    if name in (node_builder.POSITION_ATTR, "position"):
        if domain_ui == "Point":
            if cos is None:
                cos = np.empty(n * 3, dtype=np.float32)
                me.vertices.foreach_get("co", cos)
                cos = cos.reshape(-1, 3)
            return cos, 'FLOAT_VECTOR'
        if domain_ui == "Face":
            a = np.empty((n, 3), dtype=np.float32)
            for i, poly in enumerate(me.polygons):
                a[i] = poly.center
            return a, 'FLOAT_VECTOR'
        if domain_ui == "Edge":
            a = np.empty((n, 3), dtype=np.float32)
            for i, e in enumerate(me.edges):
                a[i] = (me.vertices[e.vertices[0]].co
                        + me.vertices[e.vertices[1]].co) * 0.5
            return a, 'FLOAT_VECTOR'
        if domain_ui == "Corner":
            a = np.empty((n, 3), dtype=np.float32)
            for i, loop in enumerate(me.loops):
                a[i] = me.vertices[loop.vertex_index].co
            return a, 'FLOAT_VECTOR'

    if name == node_builder.NORMAL_ATTR:
        if domain_ui == "Point":
            a = np.empty(n * 3, dtype=np.float32)
            me.vertices.foreach_get("normal", a)
            return a.reshape(-1, 3), 'FLOAT_VECTOR'
        if domain_ui == "Face":
            a = np.empty((n, 3), dtype=np.float32)
            for i, poly in enumerate(me.polygons):
                a[i] = poly.normal
            return a, 'FLOAT_VECTOR'
        if domain_ui == "Corner":
            a = np.empty((n, 3), dtype=np.float32)
            # loop normals aren't foreach-exposed; use vertex normal
            vn = np.empty(len(me.vertices) * 3, dtype=np.float32)
            me.vertices.foreach_get("normal", vn)
            vn = vn.reshape(-1, 3)
            for i, loop in enumerate(me.loops):
                a[i] = vn[loop.vertex_index]
            return a, 'FLOAT_VECTOR'
    return None, None


def _normal_matrix(mw):
    """World-space normal transform (handles non-uniform scale)."""
    try:
        return mw.inverted_safe().transposed().to_3x3()
    except Exception:
        return mw.to_3x3()


def _collect(target, attr_name, domain_ui, facing_cull, cam_pos, cap):
    """All facing-visible elements, nearest-first, truncated to cap.

    No stride/subsampling — that punched holes in faces. Cap is applied
    after cull by distance-to-camera priority.
    """
    deps = bpy.context.evaluated_depsgraph_get()
    ev = target.evaluated_get(deps)
    me = getattr(ev, "data", None)
    if me is None or not hasattr(me, "vertices"):
        return []
    mw = ev.matrix_world
    nmat = _normal_matrix(mw)
    rows = []  # (dist_sq, wco, value, dtype)
    intrinsic = node_builder.is_intrinsic(attr_name)

    if domain_ui == "Point":
        n = len(me.vertices)
        cos = np.empty(n * 3, dtype=np.float32)
        me.vertices.foreach_get("co", cos)
        cos = cos.reshape(-1, 3)
        if intrinsic:
            vals, dtype = _read_intrinsic_values(
                me, attr_name, domain_ui, cos=cos)
        else:
            vals, dtype = _read_attr_values(me, attr_name, 'POINT', n)
        if vals is None:
            return []
        # vertex normals for facing (optional)
        nrms = None
        if facing_cull:
            nrms = np.empty(n * 3, dtype=np.float32)
            me.vertices.foreach_get("normal", nrms)
            nrms = nrms.reshape(-1, 3)
        for i in range(n):
            wco = mw @ mathutils.Vector(cos[i])
            if facing_cull and nrms is not None:
                nrm = (nmat @ mathutils.Vector(nrms[i])).normalized()
                toward = (cam_pos - wco).normalized()
                if nrm.dot(toward) <= 0.05:
                    continue
            d2 = (wco - cam_pos).length_squared
            rows.append((d2, wco, vals[i], dtype))

    elif domain_ui == "Face":
        n = len(me.polygons)
        if intrinsic:
            vals, dtype = _read_intrinsic_values(me, attr_name, domain_ui)
        else:
            vals, dtype = _read_attr_values(me, attr_name, 'FACE', n)
        if vals is None:
            return []
        for i, poly in enumerate(me.polygons):
            wco = mw @ poly.center
            if facing_cull:
                nrm = (nmat @ poly.normal).normalized()
                toward = (cam_pos - wco).normalized()
                if nrm.dot(toward) <= 0.05:
                    continue
            d2 = (wco - cam_pos).length_squared
            rows.append((d2, wco, vals[i], dtype))

    elif domain_ui == "Edge":
        n = len(me.edges)
        if intrinsic:
            vals, dtype = _read_intrinsic_values(me, attr_name, domain_ui)
        else:
            vals, dtype = _read_attr_values(me, attr_name, 'EDGE', n)
        if vals is None:
            return []
        for i, e in enumerate(me.edges):
            mid = (me.vertices[e.vertices[0]].co
                   + me.vertices[e.vertices[1]].co) * 0.5
            wco = mw @ mid
            d2 = (wco - cam_pos).length_squared
            rows.append((d2, wco, vals[i], dtype))

    elif domain_ui == "Corner":
        n = len(me.loops)
        if intrinsic:
            vals, dtype = _read_intrinsic_values(me, attr_name, domain_ui)
        else:
            vals, dtype = _read_attr_values(me, attr_name, 'CORNER', n)
        if vals is None:
            return []
        for i, loop in enumerate(me.loops):
            co = me.vertices[loop.vertex_index].co
            wco = mw @ co
            d2 = (wco - cam_pos).length_squared
            rows.append((d2, wco, vals[i], dtype))

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
        rows.append(md)
    return rows


def _draw_sprite_card(shader, cx, cy, w, h):
    x0, y0 = cx - w * 0.5, cy - h * 0.5
    x1, y1 = cx + w * 0.5, cy + h * 0.5
    coords = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    indices = ((0, 1, 2), (0, 2, 3))
    batch = batch_for_shader(shader, 'TRIS', {"pos": coords},
                             indices=indices)
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

    for md in _tag_visualizers():
        try:
            target = node_builder.get_input(md, "Target")
            attr = node_builder.get_input(md, "Attribute")
            domain = node_builder.menu_input_name(md, "Domain")
            cap = max(1, int(node_builder.get_input(md, "Tag Cap") or 10000))
            size = float(node_builder.get_input(md, "Tag Size") or 14.0)
            color = node_builder.get_input(md, "Tag Color")
            decimals = int(node_builder.get_input(md, "Decimals") or 2)
            facing = bool(node_builder.get_input(md, "Facing Cull"))
        except Exception:
            continue
        if target is None or not attr:
            continue

        elements = _collect(target, attr, domain, facing, cam_pos, cap)
        if not elements:
            continue

        blf.size(font_id, max(6, int(size)))
        blf.color(font_id, float(color[0]), float(color[1]),
                  float(color[2]), 1.0)

        for wco, value, dt in elements:
            pt = location_3d_to_region_2d(region, rv3d, wco)
            if pt is None:
                continue
            label = _fmt_value(value, dt, decimals)
            tw, th = blf.dimensions(font_id, label)
            pad_x, pad_y = 6.0, 4.0
            _draw_sprite_card(shader, pt.x, pt.y,
                              tw + pad_x * 2, th + pad_y * 2)
            blf.position(font_id, pt.x - tw * 0.5, pt.y - th * 0.35, 0)
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
