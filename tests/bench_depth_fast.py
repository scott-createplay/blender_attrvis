"""Benchmark: faster depth buffer paths — skip to_list().

Tests whether we can bypass the slow to_list() → np.array() path
by using Buffer's raw memory directly.

    blender --python tests/bench_depth_fast.py
"""
import time
import ctypes
import sys
import numpy as np
import bpy
import gpu

ITERATIONS = 20
N_TAGS = 500
_handle = None


def _bench_and_quit():
    global _handle

    viewport = gpu.state.viewport_get()
    w, h = viewport[2], viewport[3]
    if w < 10 or h < 10:
        return

    fb = gpu.state.active_framebuffer_get()
    n_pixels = w * h

    # --- Method 1: pre-allocated Buffer (reuse across frames) ---
    pre_buf = gpu.types.Buffer('FLOAT', n_pixels)
    times_prealloc = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        fb.read_depth(0, 0, w, h, data=pre_buf)
        t1 = time.perf_counter()
        times_prealloc.append(t1 - t0)

    # --- Method 2: Buffer → numpy via memoryview / bytes ---
    times_membuf = []
    for _ in range(ITERATIONS):
        fb.read_depth(0, 0, w, h, data=pre_buf)
        t0 = time.perf_counter()
        try:
            arr = np.frombuffer(bytes(pre_buf), dtype=np.float32).reshape(h, w)
        except Exception:
            arr = np.array(pre_buf.to_list(), dtype=np.float32).reshape(h, w)
        t1 = time.perf_counter()
        times_membuf.append(t1 - t0)

    # --- Method 3: full pipeline with fastest path ---
    times_fast_full = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        fb.read_depth(0, 0, w, h, data=pre_buf)
        try:
            arr = np.frombuffer(bytes(pre_buf), dtype=np.float32).reshape(h, w)
        except Exception:
            arr = np.array(pre_buf.to_list(), dtype=np.float32).reshape(h, w)
        t1 = time.perf_counter()
        times_fast_full.append(t1 - t0)

    # --- Method 4: sparse sampling (only read at tag positions) ---
    tag_sx = np.random.randint(0, w, size=N_TAGS)
    tag_sy = np.random.randint(0, h, size=N_TAGS)
    times_sparse = []
    for _ in range(min(3, ITERATIONS)):
        t0 = time.perf_counter()
        for i in range(N_TAGS):
            fb.read_depth(int(tag_sx[i]), int(tag_sy[i]), 1, 1)
        t1 = time.perf_counter()
        times_sparse.append(t1 - t0)

    # --- Tag lookup on the fast array ---
    fb.read_depth(0, 0, w, h, data=pre_buf)
    try:
        arr = np.frombuffer(bytes(pre_buf), dtype=np.float32).reshape(h, w)
    except Exception:
        arr = np.array(pre_buf.to_list(), dtype=np.float32).reshape(h, w)
    tag_z = np.random.uniform(0.0, 1.0, size=N_TAGS).astype(np.float32)
    times_lookup = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        scene_z = arr[tag_sy, tag_sx]
        visible = tag_z <= scene_z
        t1 = time.perf_counter()
        times_lookup.append(t1 - t0)

    # --- Report ---
    def ms(t): return np.mean(t) * 1000

    full = ms(times_fast_full)
    pct = full / 16.67 * 100

    print("\n" + "=" * 70)
    print(f"FAST DEPTH READBACK BENCHMARK  viewport={w}x{h}")
    print(f"  {ITERATIONS} iterations, {N_TAGS} tags, {n_pixels/1e6:.1f}M pixels")
    print("=" * 70)
    print(f"  read_depth(prealloc): {ms(times_prealloc):8.2f} ms")
    print(f"  bytes→numpy         : {ms(times_membuf):8.2f} ms")
    print(f"  ─────────────────────────────────────")
    print(f"  FAST FULL PIPELINE  : {full:8.2f} ms  ({pct:.1f}% of 16.67ms frame)")
    print(f"  {N_TAGS}-tag lookup       : {ms(times_lookup):8.4f} ms")
    print(f"  {N_TAGS}-tag sparse read  : {ms(times_sparse):8.2f} ms  (per-pixel, for comparison)")
    print("=" * 70)

    verdict = "VIABLE" if pct < 25 else "MARGINAL" if pct < 50 else "TOO SLOW"
    print(f"  VERDICT: {verdict}")
    print("=" * 70 + "\n")

    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None

    def _quit():
        bpy.ops.wm.quit_blender()
        return None
    bpy.app.timers.register(_quit, first_interval=0.1)


_handle = bpy.types.SpaceView3D.draw_handler_add(
    _bench_and_quit, (), "WINDOW", "POST_PIXEL",
)

for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        area.tag_redraw()
        break

print("Fast depth benchmark registered — waiting for viewport draw...")
