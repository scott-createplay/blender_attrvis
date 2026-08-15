# These baselines are history, not targets

The JSON/log captures in this folder were taken against a **`to_mesh()`-based
sampler** that no longer exists. Their dominant span, `sample.depsgraph_mesh`
(60–342 ms), has no counterpart in current code: `gpu_sample._evaluated_source`
now uses `obj.evaluated_get(deps)` and reads `ev.data` / `gs.mesh` directly,
with no mesh copy (`attrviz/gpu_sample.py:86`).

They therefore report **114–342 ms for work that now costs ~15 ms**. Do not
read them as a performance target or a regression threshold.

What is still useful here:

- `overlay.build_batch` (~13 ms) and `overlay.present.*` — the GPU upload and
  present costs, which later work has not re-measured.
- The `harness.add.*` init-tax numbers behind
  [`../../POR_strangle_gn_backbone.md`](../../POR_strangle_gn_backbone.md)
  (~300–400 ms per viz from the per-viz engine `.copy()`).

Current sampler numbers, plus the GPU-overlay vs GN comparison that settled
the architecture question, live in
[`../../../008_overlay_invalidation/references/perf/`](../../../008_overlay_invalidation/references/perf/),
with the harness at
`dev_tasks/008_overlay_invalidation/tests/bench_invalidation.py`.

One methodology note learned the hard way, worth keeping: Blender evaluates
**lazily**, on access rather than on `dg.update()`. Any harness that does not
explicitly force evaluation will report ~0 ms for it and silently attribute
that cost to whichever column touches the data first.
