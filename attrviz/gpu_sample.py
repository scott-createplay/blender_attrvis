"""AttrViz GPU sampler — depsgraph evaluated attrs → CPU buffers.

Promoted from the Stage A probe. Used by gpu_overlay (Markers/Arrows).
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

import bpy
import mathutils
import numpy as np

from . import node_builder

SampleResult = Tuple[np.ndarray, np.ndarray, str]


def _evaluated_mesh(obj: bpy.types.Object):
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    me = getattr(ev, "data", None)
    if me is None or not hasattr(me, "vertices"):
        return None, None
    return ev, me


def _read_attr(me, name: str, domain: str, n: int):
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
    if dt == 'STRING':
        # No foreach_get for strings — materialize Python strings.
        return np.array([str(d.value) for d in attr.data], dtype=object), dt
    return None, dt


def _point_positions(me) -> np.ndarray:
    n = len(me.vertices)
    cos = np.empty(n * 3, dtype=np.float32)
    me.vertices.foreach_get("co", cos)
    return cos.reshape(-1, 3)


def _face_centers(me) -> np.ndarray:
    n = len(me.polygons)
    centers = np.empty((n, 3), dtype=np.float32)
    for i, poly in enumerate(me.polygons):
        centers[i] = poly.center
    return centers


def _edge_centers(me) -> np.ndarray:
    n = len(me.edges)
    centers = np.empty((n, 3), dtype=np.float32)
    for i, e in enumerate(me.edges):
        centers[i] = (
            me.vertices[e.vertices[0]].co + me.vertices[e.vertices[1]].co
        ) * 0.5
    return centers


def _corner_positions(me) -> np.ndarray:
    n = len(me.loops)
    pos = np.empty((n, 3), dtype=np.float32)
    for i, loop in enumerate(me.loops):
        pos[i] = me.vertices[loop.vertex_index].co
    return pos


def _to_world(positions: np.ndarray, matrix_world) -> np.ndarray:
    if positions.size == 0:
        return positions
    mw = np.array(matrix_world, dtype=np.float64).reshape(4, 4)
    hom = np.empty((len(positions), 4), dtype=np.float64)
    hom[:, :3] = positions
    hom[:, 3] = 1.0
    return (hom @ mw.T)[:, :3].astype(np.float32)


def _normal_matrix(mw):
    try:
        return mw.inverted_safe().transposed().to_3x3()
    except Exception:
        return mw.to_3x3()


def _read_intrinsic(me, name: str, domain_ui: str, cos=None):
    """Index / Position / Normal from evaluated mesh APIs."""
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
                cos = _point_positions(me)
            return cos.copy(), 'FLOAT_VECTOR'
        if domain_ui == "Face":
            return _face_centers(me), 'FLOAT_VECTOR'
        if domain_ui == "Edge":
            return _edge_centers(me), 'FLOAT_VECTOR'
        if domain_ui == "Corner":
            return _corner_positions(me), 'FLOAT_VECTOR'

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
            vn = np.empty(len(me.vertices) * 3, dtype=np.float32)
            me.vertices.foreach_get("normal", vn)
            vn = vn.reshape(-1, 3)
            a = np.empty((n, 3), dtype=np.float32)
            for i, loop in enumerate(me.loops):
                a[i] = vn[loop.vertex_index]
            return a, 'FLOAT_VECTOR'
    return None, None


def sample_evaluated(
    obj: bpy.types.Object,
    attr: str,
    domain_ui: str = "Point",
    *,
    world_space: bool = True,
) -> Optional[SampleResult]:
    """Sample one mesh object. domain_ui is Point/Edge/Face/Corner."""
    domain_ui = domain_ui if domain_ui in node_builder.DOMAINS else "Point"
    blender_dom = node_builder.DOMAIN_TO_BLENDER[domain_ui]

    ev, me = _evaluated_mesh(obj)
    if me is None:
        return None

    if domain_ui == "Point":
        positions = _point_positions(me)
    elif domain_ui == "Face":
        positions = _face_centers(me)
    elif domain_ui == "Edge":
        positions = _edge_centers(me)
    else:
        positions = _corner_positions(me)

    if node_builder.is_intrinsic(attr):
        values, dtype = _read_intrinsic(me, attr, domain_ui, cos=positions)
    else:
        values, dtype = _read_attr(me, attr, blender_dom, len(positions))
    if values is None:
        return None

    # Transform normals to world when sampling Normal intrinsic
    if world_space:
        if attr == node_builder.NORMAL_ATTR and dtype == 'FLOAT_VECTOR':
            nmat = _normal_matrix(ev.matrix_world)
            out = np.empty_like(values, dtype=np.float32)
            for i in range(len(values)):
                out[i] = nmat @ mathutils.Vector(values[i])
            values = out
        positions = _to_world(positions, ev.matrix_world)

    return positions, values, dtype


def iter_watch_meshes(target, scope) -> List[bpy.types.Object]:
    """Resolve Target object + Scope collection → mesh objects."""
    seen = set()
    out: List[bpy.types.Object] = []

    def add(obj):
        if obj is None or obj.type != 'MESH':
            return
        key = obj.as_pointer()
        if key in seen:
            return
        seen.add(key)
        out.append(obj)

    add(target)
    if scope is not None:
        # nested collections
        stack = [scope]
        while stack:
            coll = stack.pop()
            for obj in coll.objects:
                add(obj)
            stack.extend(list(coll.children))
    return out


def sample_visualizer_targets(
    md,
    *,
    world_space: bool = True,
    density: float = 1.0,
    seed: int = 0,
    cap: int = 50000,
) -> Optional[SampleResult]:
    """Sample Target∪Scope for a viz modifier; apply density + cap.

    Concatenates all watched meshes. Density uses a stable hash cull
    (same spirit as GN Random Value < Density).
    """
    try:
        target = node_builder.get_input(md, "Target")
        scope = node_builder.get_input(md, "Scope")
        attr = node_builder.get_input(md, "Attribute") or ""
        domain_ui = node_builder.menu_input_name(md, "Domain") or "Point"
    except Exception:
        return None
    if not attr:
        return None

    meshes = iter_watch_meshes(target, scope)
    if not meshes:
        return None

    pos_parts = []
    val_parts = []
    dtype = None
    for obj in meshes:
        result = sample_evaluated(obj, attr, domain_ui, world_space=world_space)
        if result is None:
            continue
        p, v, dt = result
        pos_parts.append(p)
        val_parts.append(v)
        dtype = dt

    if not pos_parts or dtype is None:
        return None

    positions = np.concatenate(pos_parts, axis=0)
    # values may be 1D or 2D
    if val_parts[0].ndim == 1:
        values = np.concatenate(val_parts, axis=0)
    else:
        values = np.concatenate(val_parts, axis=0)

    n = len(positions)
    if n == 0:
        return positions, values, dtype

    # Density cull (stable)
    density = float(max(0.0, min(1.0, density)))
    if density < 1.0 - 1e-6:
        keep = np.empty(n, dtype=bool)
        for i in range(n):
            # xorshift-ish from index+seed
            x = (i * 747796405 + int(seed) * 2891336453) & 0xFFFFFFFF
            x = ((x >> ((x >> 28) + 4)) ^ x) * 277803737
            x = (x ^ (x >> 22)) & 0xFFFFFFFF
            keep[i] = (x / 0xFFFFFFFF) < density
        positions = positions[keep]
        values = values[keep]
        n = len(positions)

    if n > cap > 0:
        step = int(np.ceil(n / cap))
        positions = positions[::step]
        values = values[::step]

    return positions, values, dtype


def _domain_element_colors(
    values: np.ndarray,
    dtype: str,
    style: str,
    *,
    vmin=None,
    vmax=None,
    seed: int = 0,
):
    from . import gpu_color
    return gpu_color.values_to_colors(
        values, dtype, style, vmin=vmin, vmax=vmax, seed=seed,
    )


def build_surface_tris(
    md,
    *,
    style: str = "Heat",
    vmin=None,
    vmax=None,
    seed: int = 0,
    inflate: float = 0.002,
    face_cap: int = 200000,
) -> Optional[Tuple[np.ndarray, np.ndarray, str, int]]:
    """Build world-space TRI vertex arrays for GPU Surface ink.

    Returns (positions Mx3, colors Mx4, dtype, n_tris) where M = 3 * n_tris,
    or None if unavailable. Edge domain is weakly supported (skipped).
    """
    try:
        target = node_builder.get_input(md, "Target")
        scope = node_builder.get_input(md, "Scope")
        attr = node_builder.get_input(md, "Attribute") or ""
        domain_ui = node_builder.menu_input_name(md, "Domain") or "Point"
    except Exception:
        return None
    if not attr or domain_ui == "Edge":
        return None

    meshes = iter_watch_meshes(target, scope)
    if not meshes:
        return None

    pos_chunks = []
    col_chunks = []
    dtype = None
    n_tris_total = 0

    for obj in meshes:
        ev, me = _evaluated_mesh(obj)
        if me is None:
            continue
        try:
            me.calc_loop_triangles()
        except Exception:
            pass
        tris = me.loop_triangles
        if not tris:
            continue

        # Sample domain values on this mesh
        result = sample_evaluated(obj, attr, domain_ui, world_space=False)
        if result is None:
            continue
        _local_pos, values, dt = result
        dtype = dt
        colors = _domain_element_colors(
            values, dt, style, vmin=vmin, vmax=vmax, seed=seed,
        )

        # Local positions + normals for inflate
        n_verts = len(me.vertices)
        cos = np.empty(n_verts * 3, dtype=np.float32)
        me.vertices.foreach_get("co", cos)
        cos = cos.reshape(-1, 3)
        nrms = np.empty(n_verts * 3, dtype=np.float32)
        me.vertices.foreach_get("normal", nrms)
        nrms = nrms.reshape(-1, 3)

        # Cap faces if huge
        tri_list = list(tris)
        if len(tri_list) > face_cap:
            step = int(np.ceil(len(tri_list) / face_cap))
            tri_list = tri_list[::step]

        m = len(tri_list) * 3
        out_pos = np.empty((m, 3), dtype=np.float32)
        out_col = np.empty((m, 4), dtype=np.float32)
        k = 0
        for tri in tri_list:
            verts = tri.vertices  # 3 vert indices
            poly_i = tri.polygon_index
            loops = tri.loops
            for j in range(3):
                vi = verts[j]
                p = cos[vi] + nrms[vi] * float(inflate)
                out_pos[k] = p
                if domain_ui == "Point":
                    out_col[k] = colors[vi]
                elif domain_ui == "Face":
                    out_col[k] = colors[poly_i]
                elif domain_ui == "Corner":
                    out_col[k] = colors[loops[j]]
                else:
                    out_col[k] = colors[0] if len(colors) else (0.7, 0.7, 0.7, 1.0)
                k += 1

        # to world
        out_pos = _to_world(out_pos, ev.matrix_world)
        pos_chunks.append(out_pos)
        col_chunks.append(out_col)
        n_tris_total += len(tri_list)

    if not pos_chunks or dtype is None:
        return None
    positions = np.concatenate(pos_chunks, axis=0)
    colors = np.concatenate(col_chunks, axis=0)
    return positions, colors, dtype, n_tris_total


def buffer_stats(result: SampleResult) -> dict[str, Any]:
    positions, values, dtype = result
    stats: dict[str, Any] = {
        "n": int(len(positions)),
        "dtype": dtype,
        "pos_shape": tuple(positions.shape),
        "val_shape": tuple(getattr(values, "shape", ())),
    }
    if np.issubdtype(values.dtype, np.floating):
        flat = values.reshape(len(values), -1)
        stats["val_min"] = float(flat.min()) if flat.size else None
        stats["val_max"] = float(flat.max()) if flat.size else None
    elif np.issubdtype(values.dtype, np.integer):
        stats["val_min"] = int(values.min()) if values.size else None
        stats["val_max"] = int(values.max()) if values.size else None
        stats["n_unique"] = int(len(np.unique(values)))
    return stats
