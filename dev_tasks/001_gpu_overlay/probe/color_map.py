"""False-color maps for unlit attribute ink (AOV-panel intent)."""
from __future__ import annotations

import numpy as np


def heat_colors(values: np.ndarray, vmin=None, vmax=None) -> np.ndarray:
    """Map float scalars → RGBA blue→cyan→green→yellow→red. Shape Nx4."""
    v = np.asarray(values, dtype=np.float32).reshape(-1)
    if v.size == 0:
        return np.zeros((0, 4), dtype=np.float32)
    lo = float(np.min(v) if vmin is None else vmin)
    hi = float(np.max(v) if vmax is None else vmax)
    if hi <= lo:
        t = np.zeros_like(v)
    else:
        t = np.clip((v - lo) / (hi - lo), 0.0, 1.0)

    # piecewise linear heat (5 stops)
    stops = np.array(
        [
            [0.05, 0.10, 0.55, 1.0],  # blue
            [0.05, 0.55, 0.75, 1.0],  # cyan
            [0.10, 0.70, 0.15, 1.0],  # green
            [0.90, 0.85, 0.10, 1.0],  # yellow
            [0.90, 0.12, 0.08, 1.0],  # red
        ],
        dtype=np.float32,
    )
    edges = np.linspace(0.0, 1.0, len(stops))
    rgba = np.empty((len(t), 4), dtype=np.float32)
    for i, u in enumerate(t):
        # locate segment
        j = int(np.searchsorted(edges, u, side='right') - 1)
        j = max(0, min(j, len(stops) - 2))
        span = edges[j + 1] - edges[j]
        f = 0.0 if span <= 0 else (u - edges[j]) / span
        rgba[i] = stops[j] * (1.0 - f) + stops[j + 1] * f
    return rgba


def hash_colors(ids: np.ndarray) -> np.ndarray:
    """Stable categorical hash → RGBA. Same id → same color."""
    a = np.asarray(ids).reshape(-1)
    rgba = np.empty((len(a), 4), dtype=np.float32)
    for i, raw in enumerate(a):
        x = int(raw) & 0xFFFFFFFF
        # 3-round integer hash
        x = (x ^ (x >> 16)) * 0x45D9F3B
        x = (x ^ (x >> 16)) * 0x45D9F3B
        x = x ^ (x >> 16)
        r = ((x >> 0) & 0xFF) / 255.0
        g = ((x >> 8) & 0xFF) / 255.0
        b = ((x >> 16) & 0xFF) / 255.0
        # lift floors so dark ids stay readable on Solid bg
        rgba[i] = (0.25 + 0.75 * r, 0.25 + 0.75 * g, 0.25 + 0.75 * b, 1.0)
    return rgba


def values_to_colors(values: np.ndarray, dtype: str) -> np.ndarray:
    """Dispatch float→heat, int→hash, vector→RGB abs-normalized."""
    if dtype == 'FLOAT':
        return heat_colors(values)
    if dtype in ('INT', 'BOOLEAN', 'INT8'):
        return hash_colors(values)
    if dtype in ('FLOAT_VECTOR', 'FLOAT2'):
        v = np.asarray(values, dtype=np.float32)
        if v.ndim == 1:
            v = v.reshape(-1, 1)
        # take first 3 comps; abs + normalize per-row for visibility
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
    if dtype in ('FLOAT_COLOR', 'BYTE_COLOR'):
        v = np.asarray(values, dtype=np.float32)
        if v.shape[-1] >= 4:
            return v[:, :4].astype(np.float32)
        rgba = np.ones((len(v), 4), dtype=np.float32)
        rgba[:, : v.shape[-1]] = v
        return rgba
    # fallback: grey
    n = len(np.asarray(values).reshape(-1))
    return np.full((n, 4), (0.7, 0.7, 0.7, 1.0), dtype=np.float32)
