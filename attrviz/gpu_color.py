"""False-color maps for AttrViz GPU overlay (AOV-panel intent).

Promoted from Stage A probe; Style-aware (Heat / RGB / Random).
Heat can evaluate a user ColorRamp (``ramp=`` stops) instead of the
hardcoded 5-stop. Viewport Heat uses a shader LUT; this module is the
CPU fallback and the LUT baker.
"""
from __future__ import annotations

import numpy as np

LUT_SIZE = 256

# ID-like attrs: stable hash per value (not the ColorRamp).
CATEGORICAL_DTYPES = frozenset({"INT", "BOOLEAN", "INT8"})


def color_mapper(dtype: str, *, legend: bool = False) -> str:
    """``hash`` for ids, ``ramp`` for scalars.

    ``legend=True`` is the future semantic override (id → ramp / swatches).
    """
    if legend:
        return "ramp"
    if dtype in CATEGORICAL_DTYPES:
        return "hash"
    return "ramp"

# Default Heat stops (position, r, g, b, a) — same as node_builder.HEAT.
HEAT_STOPS = (
    (0.0, 0.05, 0.12, 0.90, 1.0),
    (0.25, 0.00, 0.80, 0.90, 1.0),
    (0.5, 0.10, 0.85, 0.20, 1.0),
    (0.75, 0.95, 0.85, 0.10, 1.0),
    (1.0, 0.95, 0.10, 0.05, 1.0),
)


def heat_colors(values: np.ndarray, vmin=None, vmax=None) -> np.ndarray:
    """Map float scalars → RGBA blue→cyan→green→yellow→red (vectorized)."""
    v = np.asarray(values, dtype=np.float32).reshape(-1)
    if v.size == 0:
        return np.zeros((0, 4), dtype=np.float32)
    lo = float(np.min(v) if vmin is None else vmin)
    hi = float(np.max(v) if vmax is None else vmax)
    if hi <= lo:
        t = np.zeros_like(v)
    else:
        t = np.clip((v - lo) / (hi - lo), 0.0, 1.0)

    stops = np.array(
        [
            [0.05, 0.12, 0.90, 1.0],
            [0.00, 0.80, 0.90, 1.0],
            [0.10, 0.85, 0.20, 1.0],
            [0.95, 0.85, 0.10, 1.0],
            [0.95, 0.10, 0.05, 1.0],
        ],
        dtype=np.float32,
    )
    # 4 segments between 5 stops
    seg = np.clip(t * 4.0, 0.0, 3.999)
    j = np.floor(seg).astype(np.int32)
    f = (seg - j).astype(np.float32)
    rgba = stops[j] * (1.0 - f)[:, None] + stops[j + 1] * f[:, None]
    return rgba.astype(np.float32, copy=False)


def _as_stops(stops) -> np.ndarray:
    """Nx5 float32 array (position, r, g, b, a), sorted by position."""
    arr = np.asarray(stops, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] < 5:
        raise ValueError(f"stops must be Nx5 (pos, rgba), got {arr.shape}")
    arr = arr[:, :5]
    order = np.argsort(arr[:, 0], kind="stable")
    return np.ascontiguousarray(arr[order])


def extract_ramp(src=None) -> tuple:
    """Read ColorRamp stops as ``((pos, r, g, b, a), ...)``.

    ``src`` may be a ``ShaderNodeValToRGB``, a node tree containing one,
    an iterable of stops, or None (default Heat 5-stop).
    """
    if src is None:
        return HEAT_STOPS
    if isinstance(src, (list, tuple, np.ndarray)):
        if len(src) == 0:
            return HEAT_STOPS
        first = src[0]
        if isinstance(first, (list, tuple, np.ndarray)):
            out = []
            for row in src:
                p = float(row[0])
                rgba = tuple(float(c) for c in row[1:5])
                if len(rgba) < 4:
                    rgba = rgba + (1.0,) * (4 - len(rgba))
                out.append((p,) + rgba)
            return tuple(out)
    node = src
    nodes = getattr(src, "nodes", None)
    if nodes is not None:
        node = nodes.get("Heat Ramp") or next(
            (n for n in nodes if n.bl_idname == "ShaderNodeValToRGB"),
            None,
        )
    ramp = getattr(node, "color_ramp", None)
    if ramp is None:
        return HEAT_STOPS
    return tuple(
        (
            float(el.position),
            float(el.color[0]),
            float(el.color[1]),
            float(el.color[2]),
            float(el.color[3]),
        )
        for el in ramp.elements
    )


def ramp_hash(stops) -> tuple:
    """Stable cache key for a stop list (not used as a mesh-batch key)."""
    rows = _as_stops(extract_ramp(stops) if stops is not None else HEAT_STOPS)
    return tuple(
        (round(float(p), 6), round(float(r), 5), round(float(g), 5),
         round(float(b), 5), round(float(a), 5))
        for p, r, g, b, a in rows
    )


def ramp_colors(values, stops, vmin=None, vmax=None) -> np.ndarray:
    """Map scalars through a user ramp (linear lerp between stops)."""
    v = np.asarray(values, dtype=np.float32).reshape(-1)
    if v.size == 0:
        return np.zeros((0, 4), dtype=np.float32)
    rows = _as_stops(stops)
    lo = float(np.min(v) if vmin is None else vmin)
    hi = float(np.max(v) if vmax is None else vmax)
    if hi <= lo:
        t = np.zeros_like(v)
    else:
        t = np.clip((v - lo) / (hi - lo), 0.0, 1.0)

    pos = rows[:, 0]
    col = rows[:, 1:5]
    if len(rows) == 1:
        return np.broadcast_to(col[0], (len(v), 4)).copy()

    t_c = np.clip(t, pos[0], pos[-1])
    idx = np.searchsorted(pos, t_c, side="right") - 1
    idx = np.clip(idx, 0, len(pos) - 2)
    p0 = pos[idx]
    p1 = pos[idx + 1]
    span = np.maximum(p1 - p0, 1e-8)
    f = ((t_c - p0) / span).astype(np.float32)
    rgba = col[idx] * (1.0 - f)[:, None] + col[idx + 1] * f[:, None]
    return rgba.astype(np.float32, copy=False)


def ramp_lut_rgba(stops, n: int = LUT_SIZE) -> np.ndarray:
    """Bake stops to an Nx4 LUT covering t in [0, 1]."""
    n = max(2, int(n))
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    return ramp_colors(t, stops, vmin=0.0, vmax=1.0)


def heat_scalar(values, dtype: str) -> np.ndarray:
    """Scalar Heat samples (vector → length)."""
    v = np.asarray(values, dtype=np.float32)
    if dtype in ("FLOAT_VECTOR", "FLOAT2"):
        # Component count comes from the dtype, never from len(v). reshape(N, -1)
        # is ambiguous at N=0 (numpy cannot infer the free axis with zero
        # elements) and silently wrong on a flat (3N,) buffer, where it yields
        # (3N, 1) and the "norm" degenerates to per-component abs().
        ncomp = 3 if dtype == "FLOAT_VECTOR" else 2
        return np.linalg.norm(v.reshape(-1, ncomp), axis=1).astype(
            np.float32, copy=False,
        )
    return v.reshape(-1)


def hash_colors(ids: np.ndarray, seed: int = 0) -> np.ndarray:
    """Stable categorical hash → RGBA (vectorized)."""
    a = np.asarray(ids).reshape(-1)
    seed = int(seed) & 0xFFFFFFFF
    # Cast via int64 to avoid overflow surprises, then mask
    x = (a.astype(np.int64) ^ seed) & 0xFFFFFFFF
    x = (x ^ (x >> 16)) * 0x45D9F3B
    x = x & 0xFFFFFFFF
    x = (x ^ (x >> 16)) * 0x45D9F3B
    x = x & 0xFFFFFFFF
    x = x ^ (x >> 16)
    r = ((x >> 0) & 0xFF).astype(np.float32) / 255.0
    g = ((x >> 8) & 0xFF).astype(np.float32) / 255.0
    b = ((x >> 16) & 0xFF).astype(np.float32) / 255.0
    rgba = np.empty((len(a), 4), dtype=np.float32)
    rgba[:, 0] = 0.25 + 0.75 * r
    rgba[:, 1] = 0.25 + 0.75 * g
    rgba[:, 2] = 0.25 + 0.75 * b
    rgba[:, 3] = 1.0
    return rgba


def rgb_colors(values: np.ndarray) -> np.ndarray:
    """Vector → RGB from abs-normalized components."""
    v = np.asarray(values, dtype=np.float32)
    if v.ndim == 1:
        v = v.reshape(-1, 1)
    rgb = np.zeros((len(v), 3), dtype=np.float32)
    cols = min(3, v.shape[1])
    rgb[:, :cols] = np.abs(v[:, :cols])
    norms = np.linalg.norm(rgb, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-6)
    rgb = rgb / norms
    rgba = np.empty((len(v), 4), dtype=np.float32)
    rgba[:, :3] = 0.2 + 0.8 * rgb
    rgba[:, 3] = 1.0
    return rgba


def _heat_map(values, vmin, vmax, ramp=None) -> np.ndarray:
    if ramp is not None:
        return ramp_colors(values, ramp, vmin=vmin, vmax=vmax)
    return heat_colors(values, vmin=vmin, vmax=vmax)


def values_to_colors(
    values: np.ndarray,
    dtype: str,
    style: str = "Heat",
    *,
    vmin=None,
    vmax=None,
    seed: int = 0,
    ramp=None,
) -> np.ndarray:
    """Map attr values → RGBA using AttrViz Style intent.

    ``ramp`` is an optional stop list for Style=Heat (overrides hardcoded
    ``heat_colors``). RGB / Random ignore it.
    """
    style = style or "Heat"
    if style == "Random" or dtype in ('INT', 'BOOLEAN', 'INT8'):
        if dtype == 'FLOAT' and style == "Random":
            # quantize floats lightly for hash buckets
            ids = np.round(np.asarray(values, dtype=np.float32) * 1000).astype(np.int32)
            return hash_colors(ids, seed=seed)
        return hash_colors(values, seed=seed)
    if style == "RGB" or dtype in ('FLOAT_VECTOR', 'FLOAT2'):
        if dtype in ('FLOAT_VECTOR', 'FLOAT2', 'FLOAT_COLOR', 'BYTE_COLOR'):
            if dtype in ('FLOAT_COLOR', 'BYTE_COLOR'):
                v = np.asarray(values, dtype=np.float32)
                if v.shape[-1] >= 4:
                    return v[:, :4].astype(np.float32)
                rgba = np.ones((len(v), 4), dtype=np.float32)
                rgba[:, : v.shape[-1]] = v
                return rgba
            return rgb_colors(values)
        # RGB style on scalar → treat as heat (not a user ramp)
        return heat_colors(values, vmin=vmin, vmax=vmax)
    # Heat default
    if dtype in ('FLOAT_COLOR', 'BYTE_COLOR'):
        v = np.asarray(values, dtype=np.float32)
        if v.shape[-1] >= 4:
            return v[:, :4].astype(np.float32)
    if dtype in ('FLOAT_VECTOR', 'FLOAT2'):
        lengths = heat_scalar(values, dtype)
        return _heat_map(lengths, vmin, vmax, ramp)
    return _heat_map(values, vmin, vmax, ramp)
