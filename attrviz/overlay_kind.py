"""Overlay kind policy — geometric vs surface dispatch + Metal-safe pack.

Kind is a tag, not a class hierarchy. Display picks the presenter;
kind picks the sample/cull/upload policy.

    kind("Arrows")  -> "geometric"
    kind("Surface") -> "surface"

Geometric upload uses a 2D RGBA32F texture so no dimension exceeds 16384
(Metal hard limit). Surface uses identity mesh tris — no instance texture.
"""
from __future__ import annotations

import math

import numpy as np

GEOMETRIC_DISPLAYS = frozenset({"Markers", "Arrows", "Tags"})
SURFACE_DISPLAYS = frozenset({"Surface"})

_MAX_TEX_DIM = 16384


def kind(display: str) -> str:
    """Return 'surface' or 'geometric' for a Display name."""
    if display in SURFACE_DISPLAYS:
        return "surface"
    return "geometric"


def pack_dims(n: int) -> tuple[int, int]:
    """Compute (W, H) for a 2D texture packing n rows.

    W = min(n, 16384), H = ceil(n / W). Both <= 16384 for n <= 16384^2.
    Raises ValueError if n would require H > 16384 (268M+ instances — impossible).
    """
    if n <= 0:
        return (1, 1)
    w = min(n, _MAX_TEX_DIM)
    h = math.ceil(n / w)
    if h > _MAX_TEX_DIM:
        raise ValueError(
            f"pack_dims: n={n} requires H={h} > {_MAX_TEX_DIM}; "
            f"reduce instance count before upload"
        )
    return (w, h)


# ---------------------------------------------------------------------------
# Geometric view cull — frustum + frame-center budget
# ---------------------------------------------------------------------------

def frame_dist(sx: np.ndarray, sy: np.ndarray,
               rw: float, rh: float) -> np.ndarray:
    """Chebyshev frame distance: 0 = center, 1 = edge, >1 = off-screen."""
    nx = (sx - rw * 0.5) / (rw * 0.5)
    ny = (sy - rh * 0.5) / (rh * 0.5)
    return np.maximum(np.abs(nx), np.abs(ny))


def project_to_screen(positions: np.ndarray, mat, rw: float, rh: float):
    """Project world positions → screen coords via a 4x4 perspective matrix.

    Returns (sx, sy, valid_mask) where valid_mask marks w>0 (in front of cam).
    mat should be region_data.perspective_matrix (combined view+proj).
    """
    n = len(positions)
    hom = np.ones((n, 4), dtype=np.float64)
    hom[:, :3] = positions

    m = np.array(mat, dtype=np.float64).reshape(4, 4)
    clip = hom @ m.T  # Nx4

    w = clip[:, 3]
    valid = w > 1e-7
    w_safe = np.where(valid, w, 1.0)

    ndc_x = clip[:, 0] / w_safe
    ndc_y = clip[:, 1] / w_safe

    sx = (ndc_x * 0.5 + 0.5) * rw
    sy = (ndc_y * 0.5 + 0.5) * rh
    return sx, sy, valid


_CULL_POWER = 2.0
_CULL_FLOOR = 0.05


def _stable_hash_array(indices: np.ndarray) -> np.ndarray:
    """Deterministic [0,1) hash per sample index (no frame-to-frame flicker)."""
    x = (indices.astype(np.uint64) * 747796405 + 2891336453) & 0xFFFFFFFF
    x = ((x >> ((x >> 28) + 4)) ^ x) * 277803737
    x = (x ^ (x >> 22)) & 0xFFFFFFFF
    return x.astype(np.float64) / 0xFFFFFFFF


def view_cull_geometric(positions: np.ndarray, values: np.ndarray,
                        mat, rw: float, rh: float,
                        cap: int, pad: float = 0.05):
    """Frustum + stochastic weighted budget cull for geometric overlays.

    Over budget: samples near view center have higher keep probability,
    edges are thinned but not zeroed. Smooth density falloff instead of
    a hard spatial cutoff.

    Args:
        positions: Nx3 world-space sample positions (L0, post-Density).
        values: Nx? corresponding attribute values.
        mat: 4x4 perspective matrix (region_data.perspective_matrix).
        rw, rh: region pixel width/height.
        cap: maximum instances to upload.
        pad: fractional screen padding for frustum (0.05 = 5% outside edge kept).

    Returns:
        (kept_positions, kept_values, n_kept). Never returns more than cap rows.
    """
    n = len(positions)
    if n == 0:
        return positions, values, 0
    if cap <= 0:
        empty_p = positions[:0]
        empty_v = values[:0]
        return empty_p, empty_v, 0

    sx, sy, valid = project_to_screen(positions, mat, rw, rh)

    # Frustum: keep samples that project inside the frame (+ pad)
    pad_px_x = rw * pad
    pad_py_y = rh * pad
    in_frustum = (
        valid
        & (sx >= -pad_px_x) & (sx <= rw + pad_px_x)
        & (sy >= -pad_py_y) & (sy <= rh + pad_py_y)
    )

    in_view_idx = np.where(in_frustum)[0]
    n_in_view = len(in_view_idx)

    if n_in_view == 0:
        empty_p = positions[:0]
        empty_v = values[:0]
        return empty_p, empty_v, 0

    if n_in_view <= cap:
        return positions[in_view_idx], values[in_view_idx], n_in_view

    # --- Stochastic weighted budget ---
    fd = frame_dist(sx[in_view_idx], sy[in_view_idx], rw, rh)

    # Weight: center-biased with a floor so edges aren't starved
    weight = np.maximum((1.0 - np.minimum(fd, 1.0)) ** _CULL_POWER, _CULL_FLOOR)

    # Scale so expected kept ≈ cap
    scale = cap / weight.sum()
    keep_prob = np.minimum(1.0, weight * scale)

    # Deterministic per-sample decision (stable across frames)
    hashes = _stable_hash_array(in_view_idx)
    keep_mask = hashes < keep_prob
    kept_local = np.where(keep_mask)[0]

    # Hard cap guarantee: if rounding pushes over, trim highest fd
    if len(kept_local) > cap:
        fd_kept = fd[kept_local]
        trim_order = np.argsort(fd_kept)[:cap]
        kept_local = kept_local[trim_order]

    keep_idx = in_view_idx[kept_local]
    n_kept = len(keep_idx)

    return positions[keep_idx], values[keep_idx], n_kept


def view_signature(mat, rw: float, rh: float) -> tuple:
    """Cheap hashable token for the current view state (cache key component)."""
    m_tuple = tuple(float(x) for row in mat for x in row)
    return (int(rw), int(rh)) + m_tuple


def pack_texture_2d(rows: np.ndarray):
    """Upload Nx3 float rows as a 2D RGBA32F texture (Metal-safe).

    Returns (GPUTexture, W) where W is needed for shader indexing:
        texelFetch(tex, ivec2(id % W, id / W), 0)
    """
    import array
    import gpu

    n = len(rows)
    if n == 0:
        n = 1
        rows = np.zeros((1, 3), dtype=np.float32)

    w, h = pack_dims(n)
    total = w * h

    rgba = np.zeros((total, 4), dtype=np.float32)
    cols = min(rows.shape[1], 4) if rows.ndim == 2 else 1
    if rows.ndim == 2:
        rgba[:n, :cols] = rows[:, :cols]
    else:
        rgba[:n, 0] = rows

    arr = array.array('f')
    arr.frombytes(rgba.tobytes())
    buf = gpu.types.Buffer('FLOAT', total * 4, arr)
    tex = gpu.types.GPUTexture(size=(w, h), format='RGBA32F', data=buf)
    return tex, w
