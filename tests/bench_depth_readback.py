"""Benchmark: depth buffer readback cost from a live viewport.

Requires a real GPU context. Run from terminal:
    blender --python tests/bench_depth_readback.py

Registers a POST_PIXEL handler that benchmarks on the first draw,
prints results, then quits Blender.
"""
import time
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
        return  # viewport not ready yet, wait for next draw

    fb = gpu.state.active_framebuffer_get()

    # --- read_depth ---
    times_read = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        buf = fb.read_depth(0, 0, w, h)
        t1 = time.perf_counter()
        times_read.append(t1 - t0)

    # --- to_list ---
    times_tolist = []
    for _ in range(ITERATIONS):
        buf = fb.read_depth(0, 0, w, h)
        t0 = time.perf_counter()
        lst = buf.to_list()
        t1 = time.perf_counter()
        times_tolist.append(t1 - t0)

    # --- numpy array ---
    times_np = []
    for _ in range(ITERATIONS):
        buf = fb.read_depth(0, 0, w, h)
        lst = buf.to_list()
        t0 = time.perf_counter()
        arr = np.array(lst, dtype=np.float32).reshape(h, w)
        t1 = time.perf_counter()
        times_np.append(t1 - t0)

    # --- full pipeline ---
    times_full = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        buf = fb.read_depth(0, 0, w, h)
        lst = buf.to_list()
        arr = np.array(lst, dtype=np.float32).reshape(h, w)
        t1 = time.perf_counter()
        times_full.append(t1 - t0)

    # --- tag lookup ---
    arr = np.array(fb.read_depth(0, 0, w, h).to_list(),
                   dtype=np.float32).reshape(h, w)
    sx = np.random.randint(0, w, size=N_TAGS)
    sy = np.random.randint(0, h, size=N_TAGS)
    tag_z = np.random.uniform(0.0, 1.0, size=N_TAGS).astype(np.float32)

    times_lookup = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        scene_z = arr[sy, sx]
        visible = tag_z <= scene_z
        t1 = time.perf_counter()
        times_lookup.append(t1 - t0)

    # --- Report ---
    def ms(t): return np.mean(t) * 1000

    total = ms(times_full)
    pct = total / 16.67 * 100

    print("\n" + "=" * 70)
    print(f"DEPTH READBACK BENCHMARK  viewport={w}x{h}")
    print(f"  {ITERATIONS} iterations, {N_TAGS} simulated tags")
    print("=" * 70)
    print(f"  read_depth()       : {ms(times_read):8.2f} ms")
    print(f"  buf.to_list()      : {ms(times_tolist):8.2f} ms")
    print(f"  np.array(reshape)  : {ms(times_np):8.2f} ms")
    print(f"  ─────────────────────────────────────")
    print(f"  FULL PIPELINE      : {total:8.2f} ms  ({pct:.1f}% of 16.67ms frame)")
    print(f"  {N_TAGS}-tag lookup      : {ms(times_lookup):8.4f} ms  (negligible)")
    print("=" * 70)

    verdict = "VIABLE" if pct < 25 else "MARGINAL" if pct < 50 else "TOO SLOW"
    print(f"  VERDICT: {verdict}")
    print("=" * 70 + "\n")

    # Unregister and quit
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

# Force viewport redraw
for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        area.tag_redraw()
        break

print("Depth benchmark registered — waiting for viewport draw...")
