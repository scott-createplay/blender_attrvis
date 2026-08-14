"""AttrViz GPU sampler — depsgraph evaluated attrs → CPU buffers.

Promoted from the Stage A probe. Used by gpu_overlay (Markers/Arrows).
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

import bpy
import mathutils
import numpy as np

from . import node_builder

WATCH_COLLECTION = "attrvis"

try:
    from . import perf
except Exception:  # pragma: no cover
    perf = None


def _span(name):
    if perf is None:
        from contextlib import nullcontext
        return nullcontext()
    return perf.span(name)

SampleResult = Tuple[np.ndarray, np.ndarray, str]


def attr_text(val) -> str:
    """STRING attribute → Python str. Blender 5 stores these as bytes."""
    if val is None:
        return ""
    if isinstance(val, (bytes, bytearray)):
        return bytes(val).decode("utf-8", errors="replace")
    return str(val)


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
        # No foreach_get for strings. Blender 5 STRING values are bytes.
        return np.array([attr_text(d.value) for d in attr.data], dtype=object), dt
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
    with _span("sample.evaluated"):
        return _sample_evaluated_impl(
            obj, attr, domain_ui, world_space=world_space,
        )


def _sample_evaluated_impl(
    obj: bpy.types.Object,
    attr: str,
    domain_ui: str = "Point",
    *,
    world_space: bool = True,
) -> Optional[SampleResult]:
    domain_ui = domain_ui if domain_ui in node_builder.DOMAINS else "Point"
    blender_dom = node_builder.DOMAIN_TO_BLENDER[domain_ui]

    with _span("sample.depsgraph_mesh"):
        ev, me = _evaluated_mesh(obj)
    if me is None:
        return None

    with _span(f"sample.positions.{domain_ui}"):
        if domain_ui == "Point":
            positions = _point_positions(me)
        elif domain_ui == "Face":
            positions = _face_centers(me)
        elif domain_ui == "Edge":
            positions = _edge_centers(me)
        else:
            positions = _corner_positions(me)

    with _span("sample.read_attr"):
        if node_builder.is_intrinsic(attr):
            values, dtype = _read_intrinsic(me, attr, domain_ui, cos=positions)
        else:
            values, dtype = _read_attr(me, attr, blender_dom, len(positions))
    if values is None:
        return None

    # Transform normals to world when sampling Normal intrinsic
    if world_space:
        with _span("sample.to_world"):
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


def scene_watch_collection():
    return bpy.data.collections.get(WATCH_COLLECTION)


def watch_meshes_for_visualizer(md) -> List[bpy.types.Object]:
    """Meshes this viz should sample.

    If scene collection ``attrvis`` exists, it is the watch set for every
    visualizer (empty → nothing draws). Otherwise fall back to the
    modifier Target ∪ Scope sockets (tests, files without attrvis).
    """
    coll = scene_watch_collection()
    if coll is not None:
        return iter_watch_meshes(None, coll)
    try:
        target = node_builder.get_input(md, "Target")
        scope = node_builder.get_input(md, "Scope")
    except Exception:
        return []
    return iter_watch_meshes(target, scope)


def watch_fingerprint(md) -> tuple:
    """Cheap watch-set topology + transform signature (no attr read).

    Used by the GPU overlay to decide cache hits *before* sampling.
    """
    parts = []
    for obj in watch_meshes_for_visualizer(md):
        me = getattr(obj, "data", None)
        mw = obj.matrix_world
        tw = tuple(mw[i][j] for i in range(4) for j in range(4))
        nv = len(me.vertices) if me is not None else 0
        ne = len(me.edges) if me is not None else 0
        np_ = len(me.polygons) if me is not None else 0
        parts.append((
            obj.as_pointer(),
            me.as_pointer() if me is not None else 0,
            nv, ne, np_, tw,
        ))
    return tuple(parts)


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
    with _span("sample.visualizer_targets"):
        return _sample_visualizer_targets_impl(
            md, world_space=world_space, density=density, seed=seed, cap=cap,
        )


def _sample_visualizer_targets_impl(
    md,
    *,
    world_space: bool = True,
    density: float = 1.0,
    seed: int = 0,
    cap: int = 50000,
) -> Optional[SampleResult]:
    try:
        attr = node_builder.get_input(md, "Attribute") or ""
        domain_ui = node_builder.menu_input_name(md, "Domain") or "Point"
    except Exception:
        return None
    if not attr:
        return None

    meshes = watch_meshes_for_visualizer(md)
    if not meshes:
        return None
    if perf is not None:
        perf.note("watch_mesh_count", len(meshes))

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

    with _span("sample.concat_density_cap"):
        positions = np.concatenate(pos_parts, axis=0)
        # values may be 1D or 2D
        if val_parts[0].ndim == 1:
            values = np.concatenate(val_parts, axis=0)
        else:
            values = np.concatenate(val_parts, axis=0)

        n = len(positions)
        if n == 0:
            return positions, values, dtype

        # Density cull (stable). density≤0 → empty (keep real 0.0 from UI).
        density = float(max(0.0, min(1.0, density)))
        if density <= 1e-12:
            empty_pos = positions[:0]
            empty_val = values[:0]
            return empty_pos, empty_val, dtype
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

        # Cap stride removed — view cull (overlay_kind.view_cull_geometric)
        # handles budget after projection. L0 is Density-only.

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
) -> Optional[Tuple[np.ndarray, np.ndarray, str, int]]:
    """Identity Surface pack: evaluated mesh loop-tris + domain corner values.

    Returns (positions Mx3, corner_values, dtype, n_tris) where M = 3 * n_tris.
    ``corner_values`` are raw attr samples at each tri corner (colormap in overlay).
    Edge domain is weakly supported (skipped).

    Positions are an **identity** copy of the evaluated mesh triangulation in
    world space (no inflate, face stride, or outlier cull). Only false-color
    changes at present time; topology matches ``len(me.loop_triangles)``.
    """
    with _span("sample.build_surface_tris"):
        return _build_surface_tris_impl(
            md,
            style=style,
            vmin=vmin,
            vmax=vmax,
            seed=seed,
        )


def _build_surface_tris_impl(
    md,
    *,
    style: str = "Heat",
    vmin=None,
    vmax=None,
    seed: int = 0,
) -> Optional[Tuple[np.ndarray, np.ndarray, str, int]]:
    # style/vmin/vmax/seed unused for packing; kept for API compat with overlay.
    _ = (style, vmin, vmax, seed)
    try:
        attr = node_builder.get_input(md, "Attribute") or ""
        domain_ui = node_builder.menu_input_name(md, "Domain") or "Point"
    except Exception:
        return None
    if not attr or domain_ui == "Edge":
        return None

    meshes = watch_meshes_for_visualizer(md)
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
        n_tris = len(tris)
        if n_tris == 0:
            continue

        # Sample domain values on this mesh
        result = sample_evaluated(obj, attr, domain_ui, world_space=False)
        if result is None:
            continue
        _local_pos, values, dt = result
        dtype = dt
        # Domain values — expanded to corners below; colormap applied in overlay
        # so Range/Style scrub can recolor without re-packing tris.
        values = np.asarray(values)

        n_verts = len(me.vertices)
        cos = np.empty(n_verts * 3, dtype=np.float32)
        me.vertices.foreach_get("co", cos)
        cos = cos.reshape(-1, 3)

        with _span("sample.surface_tri_pack"):
            # Vectorized identity expand: all loop-tris, no mutate/filter.
            vert_ids = np.empty((n_tris, 3), dtype=np.int32)
            poly_ids = np.empty(n_tris, dtype=np.int32)
            loop_ids = np.empty((n_tris, 3), dtype=np.int32)
            for i, tri in enumerate(tris):
                vert_ids[i] = tri.vertices
                poly_ids[i] = tri.polygon_index
                loop_ids[i] = tri.loops

            m = n_tris * 3
            flat_vi = vert_ids.reshape(-1)
            out_pos = cos[flat_vi]

            if domain_ui == "Point":
                out_val = values[flat_vi]
            elif domain_ui == "Face":
                out_val = values[poly_ids].repeat(3, axis=0)
            elif domain_ui == "Corner":
                out_val = values[loop_ids.reshape(-1)]
            else:
                out_val = np.broadcast_to(
                    values[0], (m,) + (() if values.ndim == 1 else values.shape[1:]),
                ).copy()

            out_pos = _to_world(out_pos, ev.matrix_world)

        pos_chunks.append(out_pos)
        col_chunks.append(out_val)
        n_tris_total += n_tris

    if not pos_chunks or dtype is None:
        return None
    positions = np.concatenate(pos_chunks, axis=0)
    corner_values = np.concatenate(col_chunks, axis=0)
    return positions, corner_values, dtype, n_tris_total


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
