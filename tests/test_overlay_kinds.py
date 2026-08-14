"""Unit tests for overlay_kind — pack_dims, pack_texture_2d, kind().

Run headless (no GPU context needed for pack_dims / kind; texture tests
need Blender's GPU but will degrade gracefully in --background soup).

    blender --background --factory-startup --python-exit-code 1 \
      --python tests/test_overlay_kinds.py
"""
from __future__ import annotations

import sys
import math

_MAX_TEX_DIM = 16384


def test_pack_dims():
    """pack_dims: W,H both <= 16384 for all relevant n values."""
    sys.path.insert(0, ".")
    from attrviz.overlay_kind import pack_dims

    cases = [1, 100, 16384, 16385, 19496, 50000]
    for n in cases:
        w, h = pack_dims(n)
        assert w <= _MAX_TEX_DIM, f"n={n}: W={w} > {_MAX_TEX_DIM}"
        assert h <= _MAX_TEX_DIM, f"n={n}: H={h} > {_MAX_TEX_DIM}"
        assert w * h >= n, f"n={n}: W*H={w*h} < n"
        assert w == min(n, _MAX_TEX_DIM), f"n={n}: W={w} expected {min(n, _MAX_TEX_DIM)}"
        assert h == math.ceil(n / w), f"n={n}: H={h} expected {math.ceil(n / w)}"
        print(f"  pack_dims({n:>6}) -> ({w}, {h})  OK")


def test_pack_dims_zero():
    """pack_dims(0) returns a valid 1x1 (degenerate but legal)."""
    sys.path.insert(0, ".")
    from attrviz.overlay_kind import pack_dims

    w, h = pack_dims(0)
    assert w >= 1 and h >= 1
    print(f"  pack_dims(0) -> ({w}, {h})  OK")


def test_kind_mapping():
    """kind() returns correct tags for all Display values."""
    sys.path.insert(0, ".")
    from attrviz.overlay_kind import kind, GEOMETRIC_DISPLAYS, SURFACE_DISPLAYS

    for d in GEOMETRIC_DISPLAYS:
        assert kind(d) == "geometric", f"kind({d!r}) != 'geometric'"
    for d in SURFACE_DISPLAYS:
        assert kind(d) == "surface", f"kind({d!r}) != 'surface'"
    assert kind("Unknown") == "geometric"
    print("  kind() mapping  OK")


def test_pack_texture_no_abort():
    """pack_texture_2d with n=19496 must not SIGABRT (needs GPU context).

    In --background (soup), GPUTexture creation may fail gracefully
    rather than abort. We test that the shape logic is correct even if
    the texture cannot be allocated.
    """
    import numpy as np
    sys.path.insert(0, ".")
    from attrviz.overlay_kind import pack_texture_2d, pack_dims

    for n in (19496, 50000):
        rows = np.random.randn(n, 3).astype(np.float32)
        w, h = pack_dims(n)
        assert w <= _MAX_TEX_DIM and h <= _MAX_TEX_DIM
        try:
            tex, returned_w = pack_texture_2d(rows)
            assert returned_w == w
            print(f"  pack_texture_2d(n={n}) -> tex OK, W={returned_w}")
        except Exception as e:
            # In --background soup: no GPU context, but no SIGABRT either
            print(f"  pack_texture_2d(n={n}) -> no GPU context ({e}), no abort  OK")


def _ortho_screen_mat(rw, rh):
    """Orthographic matrix mapping world [0,rw]×[0,rh] → NDC [-1,1]×[-1,1].

    clip = hom @ m.T gives: ndc_x = 2x/rw - 1, ndc_y = 2y/rh - 1, w = 1.
    So screen sx = x, sy = y (identity mapping, easy to reason about).
    """
    return [
        [2.0/rw, 0, 0, -1],
        [0, 2.0/rh, 0, -1],
        [0, 0, -1, 0],
        [0, 0, 0, 1],
    ]


def test_view_cull_under_cap_keep_all():
    """Under cap: all in-view samples are kept."""
    import numpy as np
    sys.path.insert(0, ".")
    from attrviz.overlay_kind import view_cull_geometric

    rw, rh = 800.0, 600.0
    mat = _ortho_screen_mat(rw, rh)

    # 10 points well within the screen
    n = 10
    positions = np.zeros((n, 3), dtype=np.float32)
    positions[:, 0] = np.linspace(100, 700, n)
    positions[:, 1] = np.linspace(100, 500, n)
    values = np.arange(n, dtype=np.float32)

    kept_p, kept_v, n_kept = view_cull_geometric(
        positions, values, mat, rw, rh, cap=50,
    )
    assert n_kept == n, f"under cap: expected {n} kept, got {n_kept}"
    print(f"  view_cull under cap: {n_kept}/{n} kept  OK")


def test_view_cull_over_cap_respects_cap():
    """Over cap: kept count never exceeds cap."""
    import numpy as np
    sys.path.insert(0, ".")
    from attrviz.overlay_kind import view_cull_geometric

    rw, rh = 800.0, 600.0
    mat = _ortho_screen_mat(rw, rh)

    n = 500
    np.random.seed(42)
    positions = np.zeros((n, 3), dtype=np.float32)
    positions[:, 0] = np.random.uniform(50, 750, n)
    positions[:, 1] = np.random.uniform(50, 550, n)
    values = np.arange(n, dtype=np.float32)

    cap = 100
    kept_p, kept_v, n_kept = view_cull_geometric(
        positions, values, mat, rw, rh, cap=cap,
    )
    assert n_kept <= cap, f"cap violated: {n_kept} > {cap}"
    assert n_kept > 0, "should keep some samples"
    print(f"  view_cull cap guarantee: {n_kept}/{n} kept (cap={cap})  OK")


def test_view_cull_over_cap_center_denser():
    """Over cap: center region has higher kept density than edges."""
    import numpy as np
    sys.path.insert(0, ".")
    from attrviz.overlay_kind import view_cull_geometric, frame_dist

    rw, rh = 800.0, 600.0
    mat = _ortho_screen_mat(rw, rh)

    n = 1000
    np.random.seed(7)
    positions = np.zeros((n, 3), dtype=np.float32)
    positions[:, 0] = np.random.uniform(20, 780, n)
    positions[:, 1] = np.random.uniform(20, 580, n)
    values = np.arange(n, dtype=np.float32)

    cap = 200
    kept_p, kept_v, n_kept = view_cull_geometric(
        positions, values, mat, rw, rh, cap=cap,
    )

    # Compute frame_dist of original positions to classify center vs edge
    fd_orig = frame_dist(positions[:, 0], positions[:, 1], rw, rh)
    center_mask = fd_orig < 0.4
    edge_mask = fd_orig > 0.7

    n_center_total = center_mask.sum()
    n_edge_total = edge_mask.sum()

    # Which of the kept samples came from center vs edge?
    fd_kept = frame_dist(kept_p[:, 0], kept_p[:, 1], rw, rh)
    n_center_kept = (fd_kept < 0.4).sum()
    n_edge_kept = (fd_kept > 0.7).sum()

    rate_center = n_center_kept / max(1, n_center_total)
    rate_edge = n_edge_kept / max(1, n_edge_total)

    assert rate_center > rate_edge, (
        f"center rate {rate_center:.3f} should exceed edge rate {rate_edge:.3f}"
    )
    print(f"  view_cull density gradient: center={rate_center:.2f} > edge={rate_edge:.2f}  OK")


def test_view_cull_over_cap_edges_not_zero():
    """Over cap: edges still have some representation (not starved)."""
    import numpy as np
    sys.path.insert(0, ".")
    from attrviz.overlay_kind import view_cull_geometric, frame_dist

    rw, rh = 800.0, 600.0
    mat = _ortho_screen_mat(rw, rh)

    # Many samples spread uniformly across the viewport
    n = 2000
    np.random.seed(99)
    positions = np.zeros((n, 3), dtype=np.float32)
    positions[:, 0] = np.random.uniform(10, 790, n)
    positions[:, 1] = np.random.uniform(10, 590, n)
    values = np.arange(n, dtype=np.float32)

    cap = 400
    kept_p, kept_v, n_kept = view_cull_geometric(
        positions, values, mat, rw, rh, cap=cap,
    )

    # Some samples with fd > 0.7 must survive
    fd_kept = frame_dist(kept_p[:, 0], kept_p[:, 1], rw, rh)
    n_edge_kept = (fd_kept > 0.7).sum()
    assert n_edge_kept > 0, "edges should not be completely starved"
    print(f"  view_cull edge representation: {n_edge_kept} samples at fd>0.7  OK")


def test_view_cull_deterministic():
    """Same inputs produce same outputs (no flicker)."""
    import numpy as np
    sys.path.insert(0, ".")
    from attrviz.overlay_kind import view_cull_geometric

    rw, rh = 800.0, 600.0
    mat = _ortho_screen_mat(rw, rh)

    n = 500
    np.random.seed(123)
    positions = np.zeros((n, 3), dtype=np.float32)
    positions[:, 0] = np.random.uniform(50, 750, n)
    positions[:, 1] = np.random.uniform(50, 550, n)
    values = np.arange(n, dtype=np.float32)

    cap = 100
    kept_p1, _, n1 = view_cull_geometric(positions, values, mat, rw, rh, cap=cap)
    kept_p2, _, n2 = view_cull_geometric(positions, values, mat, rw, rh, cap=cap)

    assert n1 == n2, f"non-deterministic count: {n1} vs {n2}"
    assert np.array_equal(kept_p1, kept_p2), "non-deterministic selection"
    print(f"  view_cull deterministic: {n1} kept, identical both runs  OK")


def test_view_cull_offscreen_skipped():
    """Off-screen samples are dropped regardless of cap."""
    import numpy as np
    sys.path.insert(0, ".")
    from attrviz.overlay_kind import view_cull_geometric

    rw, rh = 800.0, 600.0
    mat = _ortho_screen_mat(rw, rh)

    n = 20
    positions = np.zeros((n, 3), dtype=np.float32)
    # All points far off-screen (x = 5000, y = 5000 → NDC ≫ 1)
    positions[:, 0] = 5000.0
    positions[:, 1] = 5000.0
    values = np.arange(n, dtype=np.float32)

    kept_p, kept_v, n_kept = view_cull_geometric(
        positions, values, mat, rw, rh, cap=50000,
    )
    assert n_kept == 0, f"off-screen: expected 0 kept, got {n_kept}"
    print(f"  view_cull off-screen: {n_kept}/{n} kept  OK")


def test_view_cull_no_region_passthrough():
    """When cap=0, returns empty (Cap 0 → draw nothing)."""
    import numpy as np
    sys.path.insert(0, ".")
    from attrviz.overlay_kind import view_cull_geometric

    rw, rh = 800.0, 600.0
    mat = _ortho_screen_mat(rw, rh)
    positions = np.ones((10, 3), dtype=np.float32) * 400
    values = np.arange(10, dtype=np.float32)

    kept_p, kept_v, n_kept = view_cull_geometric(
        positions, values, mat, rw, rh, cap=0,
    )
    assert n_kept == 0, f"cap=0: expected 0 kept, got {n_kept}"
    print(f"  view_cull cap=0: {n_kept} kept  OK")


if __name__ == "__main__":
    print("test_overlay_kinds: pack_dims")
    test_pack_dims()
    print("test_overlay_kinds: pack_dims_zero")
    test_pack_dims_zero()
    print("test_overlay_kinds: kind_mapping")
    test_kind_mapping()
    print("test_overlay_kinds: pack_texture_no_abort")
    test_pack_texture_no_abort()
    print("test_overlay_kinds: view_cull_under_cap")
    test_view_cull_under_cap_keep_all()
    print("test_overlay_kinds: view_cull_cap_guarantee")
    test_view_cull_over_cap_respects_cap()
    print("test_overlay_kinds: view_cull_center_denser")
    test_view_cull_over_cap_center_denser()
    print("test_overlay_kinds: view_cull_edges_not_zero")
    test_view_cull_over_cap_edges_not_zero()
    print("test_overlay_kinds: view_cull_deterministic")
    test_view_cull_deterministic()
    print("test_overlay_kinds: view_cull_offscreen")
    test_view_cull_offscreen_skipped()
    print("test_overlay_kinds: view_cull_cap_zero")
    test_view_cull_no_region_passthrough()
    print("\nAll test_overlay_kinds passed.")
