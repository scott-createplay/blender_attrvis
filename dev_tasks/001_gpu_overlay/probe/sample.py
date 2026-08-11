"""Sample evaluated mesh attributes into CPU buffers.

Standalone — do not import attrviz. Patterns inspired by tags_draw.py.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple

import bpy
import numpy as np

DomainName = str  # 'POINT' | 'FACE'
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


def _to_world(positions: np.ndarray, matrix_world) -> np.ndarray:
    """Transform local Nx3 positions by matrix_world → world Nx3."""
    if positions.size == 0:
        return positions
    mw = np.array(matrix_world, dtype=np.float64).reshape(4, 4)
    hom = np.empty((len(positions), 4), dtype=np.float64)
    hom[:, :3] = positions
    hom[:, 3] = 1.0
    out = (hom @ mw.T)[:, :3]
    return out.astype(np.float32)


def sample_evaluated(
    obj: bpy.types.Object,
    attr: str,
    domain: DomainName = 'POINT',
    *,
    world_space: bool = True,
) -> Optional[SampleResult]:
    """Sample an attribute from the depsgraph-evaluated mesh.

    Returns
    -------
    (positions Nx3 float32, values, dtype_str) or None if unavailable.

    domain: 'POINT' or 'FACE' (FACE uses polygon centers).
    values: 1D float/int array, or NxK for vector/color.
    """
    domain = domain.upper()
    if domain not in ('POINT', 'FACE'):
        raise ValueError(f"unsupported domain: {domain}")

    ev, me = _evaluated_mesh(obj)
    if me is None:
        return None

    if domain == 'POINT':
        n = len(me.vertices)
        positions = _point_positions(me)
    else:
        n = len(me.polygons)
        positions = _face_centers(me)

    values, dtype = _read_attr(me, attr, domain, n)
    if values is None:
        return None

    if world_space:
        positions = _to_world(positions, ev.matrix_world)

    return positions, values, dtype


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
        stats["val_mean"] = float(flat.mean()) if flat.size else None
    elif np.issubdtype(values.dtype, np.integer):
        stats["val_min"] = int(values.min()) if values.size else None
        stats["val_max"] = int(values.max()) if values.size else None
        stats["n_unique"] = int(len(np.unique(values)))
    return stats
