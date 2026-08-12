"""False-color maps for AttrViz GPU overlay (AOV-panel intent).

Promoted from Stage A probe; Style-aware (Heat / RGB / Random).
"""
from __future__ import annotations

import numpy as np


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


def values_to_colors(
    values: np.ndarray,
    dtype: str,
    style: str = "Heat",
    *,
    vmin=None,
    vmax=None,
    seed: int = 0,
) -> np.ndarray:
    """Map attr values → RGBA using AttrViz Style intent."""
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
        # RGB style on scalar → treat as heat
        return heat_colors(values, vmin=vmin, vmax=vmax)
    # Heat default
    if dtype in ('FLOAT_COLOR', 'BYTE_COLOR'):
        v = np.asarray(values, dtype=np.float32)
        if v.shape[-1] >= 4:
            return v[:, :4].astype(np.float32)
    if dtype in ('FLOAT_VECTOR', 'FLOAT2'):
        # Heat on vectors: use length
        v = np.asarray(values, dtype=np.float32)
        lengths = np.linalg.norm(v.reshape(len(v), -1), axis=1)
        return heat_colors(lengths, vmin=vmin, vmax=vmax)
    return heat_colors(values, vmin=vmin, vmax=vmax)
