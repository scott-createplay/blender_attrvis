# POR: Overlay invalidation — the visualizer must track its source

**Parent / history:** GPU overlay is THE path ([`../001_gpu_overlay/POR.md`](../001_gpu_overlay/POR.md), frozen; [`../002_overlay_kinds/POR.md`](../002_overlay_kinds/POR.md)). The L0/L1 sample-vs-presentation cache split landed there — this POR fixes what L0 never invalidated on.
**Pickup:** `AGENT_ONBOARDING.md` (not written yet).
**Status:** Not started. Northstar: the overlay is ostensibly the source geometry — if the source changes, the ink changes.

AttrViz **0.5.11**. Blender **5.2.0**.

---

## Why this POR exists

A visualizer created before a change keeps drawing the old data forever. Scrub `Seed` on a scatter and the buildings move while the markers stay where the buildings used to be.

`_sample_key` embeds `fp = gpu_sample.watch_fingerprint(md)` (`gpu_overlay.py:1097`), and L0 is only recomputed when that key changes (`gpu_overlay.py:1188`). But `watch_fingerprint` (`gpu_sample.py:401-424`) is built entirely from **unevaluated** data:

```python
(obj.as_pointer(), me.as_pointer(),
 len(me.vertices), len(me.edges), len(me.polygons), matrix_world)
```

Object pointer, mesh pointer, three element counts off `obj.data`, and the world matrix. Nothing evaluated. Measured on 5.2.0:

| Change to the watched object | Sampler returns new data | Fingerprint moves |
|---|---|---|
| Attribute values (same counts) | yes | **no** |
| Vertex positions (same counts) | yes | **no** |
| **A GN modifier added** | yes | **no** |
| Object moved | yes | yes |

`mock_city.blend`, scrubbing `seed_scatter.Seed` 135 → 142 with a Realize node present:

```
BEFORE  n=208  first_pos=[  8.58 -32.96 0.00]  first_height=36.37
AFTER   n=200  first_pos=[-99.14 -107.83 0.00]  first_height= 7.06
SOURCE CHANGED     : True
FINGERPRINT CHANGED: False
```

The scatter dropped a building — **the sample array changed length, 208 → 200** — and the cache still reported a hit. Counting the *original* mesh means even "how many things exist" cannot move the fingerprint.

Nothing else covers it: the only `depsgraph_update_post` handler, `_sync_vizcol_active` (`__init__.py:1280`), syncs vizcol and surface mute and never touches `_caches` / `_sample_caches`.

### Why the GN path does not have this bug

`GeometryNodeObjectInfo` (`node_builder.py:411`) is a real dependency-graph edge — Maya's `shape.outMesh → shape.inMesh`. The viz geometry is a live function of the target's evaluated geometry and the depsgraph owns invalidation. Verified: inverting a source attribute flips the GN path's `vizcol` from the blue end of the ramp to the red end with zero invalidation code.

The GPU overlay is a cache of a connection Blender cannot express — a Python `draw_handler` is outside the graph — so it has to reconstruct the dirty signal the depsgraph already computes. Today it guesses, and guesses wrong.

---

## Locked architecture (decided with evidence — do not re-litigate)

**The GPU overlay is the path, at every scale.** Marginal cost per scrub tick, against a baseline of the same scene with no visualizer (5.2.0, synthetic dense grid + Set Position, compute only):

| verts | baseline | GPU marginal | GN marginal | ratio |
|---:|---:|---:|---:|---:|
| 40,000 | 1.0 ms | **1.3 ms** | 15.2 ms | GPU 11.8× |
| 160,000 | 3.1 ms | **4.8 ms** | 60.2 ms | GPU 12.7× |
| 490,000 | 4.7 ms | **14.1 ms** | 188.2 ms | GPU 13.4× |
| 1,000,000 | 6.3 ms | **33.3 ms** | 375.9 ms | GPU 11.3× |

Three conclusions, all locked:

1. **GN is not the scale path.** 11–13× slower at every size, flat ratio. The Python round-trip is *not* the expensive part — rebuilding real geometry every tick is. The GN engine realizes instances, separates components, bakes Normal across four domains, runs Mesh to Points and assigns materials on every evaluation. 002 chose the overlay on display semantics and got the fast path as well.
2. **A compiled Overlay engine is parked.** POR 001 pre-authorises escalation "with evidence". The evidence now points away: the entire prize is the 33 ms/1M of marshalling, against 6.3 ms of Blender's own evaluation, and the P2 items below plausibly halve it. Do not escalate without numbers that beat an optimised Python path.
3. **A Maya-style custom locator is not available.** Blender object types are a fixed C enum with no registration API, draw engines are wired in at build time, and there is no compiled plugin ABI — addons are Python. `Gizmo`/`GizmoGroup` are registerable but still draw from Python (no marshalling win); `RenderEngine` takes the whole frame. This is not a lighter alternative to a compiled engine; it *is* that work plus shipping a patched Blender. Recorded so it is not re-proposed.

---

## Locked product

The overlay is **always current** by default. Staleness is permitted **only** while a change is actively streaming, and only when a resample exceeds the interactive budget — and it must always be followed by an exact resample when the stream stops.

Correct-but-slow beats fast-but-lying: a stale visualizer is silently wrong, which is the one failure mode this addon cannot have.

### Implementation locks

1. **The depsgraph epoch IS the invalidation.** A `depsgraph_update_post` handler walks `depsgraph.updates` and bumps a counter for each object with `is_updated_geometry` / `is_updated_transform`. That counter goes into the L0 key.
2. **Reduce the fingerprint, do not extend it.** Element counts and `matrix_world` become redundant once the epoch is authoritative, and they cost a walk of every watched mesh on every redraw. What must survive is watch-set **identity** — which objects are watched — because adding or removing a target need not fire a geometry update. Do **not** keep the counts as belt-and-braces.
3. **Per-object epochs**, keyed on `as_pointer()`. A global counter would make a scrub in one corner of the scene resample every unrelated visualizer.
4. **Draw-time coalescing is already inherent.** `_refresh_viz` runs from the draw handler, so N depsgraph updates in one redraw cost one resample. Cost is bounded by frame rate, not update rate. Do not add a second coalescing layer.
5. **Density is NOT a scrub lever.** `sample_evaluated` reads full positions and values per object (`gpu_sample.py:482`); the density cull and cap run afterwards on the concatenated arrays (`gpu_sample.py:493`). Dropping Density shrinks the GPU batch, not the read. The obvious optimisation does not work — do not reach for it.
6. **Presentation cache untouched.** `_present_key` (L1/L2) and the 003/005 rules stay exactly as they are. Ramp, Range, Style, Length, Seed-scrub-on-presentation must still never resample.
7. **The throttle must be self-disarming.** It engages only when the last resample exceeded budget, and it must register a timer guaranteeing one final exact resample when updates stop. A throttle that can leave the viewport permanently stale is worse than the bug.
8. **The GN path stays the semantic fallback**, not the scale path. Do not delete it, do not promote it.

---

## Progressive plan

### P0 — Correctness ✅

Probed first on 5.2 — which signal actually reports what:

| Change | `depsgraph_update_post` | flag |
|---|---|---|
| attribute values | fires | geometry |
| vertex move | fires | geometry |
| GN modifier input (the seed scrub) | fires | geometry |
| object transform | fires | transform |
| **edit-mode vertex move, while IN edit mode** | fires | geometry |
| **frame change on an animated source** | **never fires (0×)** | — |

Edit mode needed no special handling. Frame change did: geometry genuinely moves (Z 7.458 → 1.029) while `depsgraph_update_post` does not fire at all, so only `frame_change_post` sees it.

- [x] `_note_depsgraph_epochs` — `@persistent depsgraph_update_post`, bumps a per-object epoch on `is_updated_geometry` / `is_updated_transform`. Reads flags only; no evaluation.
- [x] `_note_frame_change` — `@persistent frame_change_post`, bumps **one scene epoch**. `frame_change_post` carries no per-object update list, so invalidating everything is the honest option rather than guessing which animated object moved.
- [x] Epochs key on `obj.original.as_pointer()` — depsgraph updates can report the *evaluated* copy while watch sets hold originals, so raw pointers would never match.
- [x] `watch_fingerprint` reduced to `(scene_epoch, [(obj_ptr, data_ptr, epoch), …])`. Counts and `matrix_world` gone.
- [x] Registered with `insert(0, …)`, ahead of `_sync_vizcol_active`: invalidation must not be skippable because an unrelated vizcol sync raised. Test asserts the ordering.
- [x] `reset_epochs()` on `load_post` — pointers are meaningless across files, and a *reused* pointer could mask a change.
- [x] Tests (12): every row above flips stale → fresh; an evaluated element-count change invalidates; **non-regressions** — no-change keeps the fingerprint stable (orbit still caches) and an unrelated object changing does not invalidate; handlers registered and correctly ordered.
- [x] `mock_city` seed scrub confirmed end to end: 264 → 184 buildings, `FINGERPRINT CHANGED: True`.

Cost after P0: 1M scrub tick ~22.7 ms marginal (from 14.5 ms — this is correctness arriving), still below the 30.7 ms it cost before P2. Whether P1's throttle is needed is now a question for real scenes.

### P1 — Interactive throttle

- [ ] Time each resample. Under budget (~8 ms) never throttle — below ~150k verts this must never engage.
- [ ] Over budget: while updates stream, resample at most every N ms; register a timer that guarantees one exact resample once they stop.
- [ ] Tests: throttle never leaves a final stale frame; sub-budget scenes never throttle at all.

### P2 — Sampler cost (ordered: cheapest and largest first)

**Do these in order and re-measure between each.** The first item is most of the win and changes whether the rest are worth doing at all.

- [x] **No per-element geometry reads anywhere in the sampler.** All reads route through two shared primitives with one contract — fill the buffer and return True, or touch nothing and return False so the caller falls back:
  - `_attr_into(geom, name, prop, out, data_type)` — attribute-backed
  - `_bulk_into(coll, prop, out)` — collection-backed
  - composed into `_attr_vec3`, `_point_positions`, `_point_normals`, `_face_normals`, `_corner_vert_index`, `_edge_vert_index`

  The first pass fixed only the Point domain — which was already the *cheapest* path. Face / Edge / Corner were per-element Python loops that had never been on `foreach_get` at all, some with a random-access vertex lookup per iteration. Measured on the addon's own functions at 160k verts / 319k edges / 637k loops:

  | Reader | Before | After |
  |---|---:|---:|
  | `_point_positions` | 16.4 ms @1M | **0.0 ms** |
  | `_point_normals` | 38.4 ms @1M | **0.0 ms** |
  | `_face_centers` | 90.8 ms | **9.4 ms** |
  | `_face_normals` | 92.9 ms | **0.0 ms** |
  | `_edge_centers` | 504.9 ms | **22.6 ms** |
  | `_corner_positions` | 518.7 ms | **20.9 ms** |
  | corner normals | ~520 ms | **21.2 ms** |

  Also: Surface (`:624`) routes through `_point_positions`; `_cloud_positions` reordered to try the attribute *first* (it had been preferring the slow `points.foreach_get("co")`).

  **Display type is not the axis — domain is.** Markers / Arrows / Tags / Surface all reach these through `sample_evaluated` (Tags via `tags_draw.py:267`, `:283`), so one fix covers every visualizer type.

  Two deliberate stops: **face centres reach only 9.4×** because there is no cached centre array — going further means computing from corner verts + polygon offsets in numpy, real work for ~9 ms. And **corner normals stay smooth, not split** — `me.corner_normals` exists and is a single fast read, but returns split normals, which changes what Arrows draw on a sharp-edged mesh. Behaviour preserved with a test asserting it; switching is a product call.
- [x] **Confirmed on evaluated (GN-output) meshes**, not just plain datablocks — byte-identical, and the read reflects the modifier. 14 checks in `tests/test_gpu_sample.py` compare every reader against the original per-element implementation, kept in the test as the reference, plus empty-mesh guards and a negative case per primitive.
- [ ] Move the world transform to a shader uniform instead of a numpy pass over N×3 (7.4 ms at 1M). **Not the one-liner this originally implied.** `_to_world` runs *per watched object* (`gpu_sample.py:404`, `:421`) before the multi-object concat, so a concatenated buffer has no single matrix to hand a uniform. Either add a single-object fast path — the common case, and low risk — or batch per object. Scope it before starting.
- [ ] Reuse preallocated buffers when the element count is unchanged (~12 MB churn per tick at 1M verts).
- [ ] Split the position cache from the value cache with independent epochs — an attribute-only scrub should not re-read positions. **Low priority after item 1**: the attribute read is already 0.1 ms; it is the position read that costs, and item 1 takes it to 0.29 ms.
- [ ] Re-run the harness after each; keep the ones that pay.

Measured primitives at 1M verts (5.2.0) that set the budget:

| Operation | Cost | Thread-safe off main? |
|---|---:|---|
| `vertices.foreach_get("co")` | 16.4 ms | no (bpy) |
| `attributes["position"].foreach_get("vector")` | **0.29 ms** | no (bpy) |
| `vertices.foreach_get("normal")` | 38.4 ms | no (bpy) |
| `vertex_normals.foreach_get("vector")` | **0.30 ms** | no (bpy) |
| attribute value read (FLOAT) | 0.1 ms | no (bpy) |
| numpy world transform | 7.4 ms | yes |
| numpy cull / fancy-index | 3.7 ms | yes |

**Measured after item 1** (GPU marginal cost per scrub tick, median of 2 runs):

| verts | before | after |
|---:|---:|---:|
| 40,000 | 1.2 ms | **0.6 ms** |
| 160,000 | 5.3 ms | **2.0 ms** |
| 490,000 | 13.8 ms | **7.0 ms** |
| 1,000,000 | 30.7 ms | **14.5 ms** |

2.1× at 1M. The projection was ~11 ms — the extra ~3.5 ms is per-sample work the projection did not itemise (concat, dtype handling, the `sample_visualizer_targets` wrapper), not a shortfall in the accessor swap itself. The remaining budget is now dominated by the numpy tail, so the shader-uniform transform is the next real lever. The GPU-vs-GN ratio widened from 11–13× to **20–27×**.

Benchmark hygiene: the 490k and 1M rows swing with machine load — one run under load reported 1M GN marginal at 526 ms against ~385 ms otherwise. Take the median of at least two runs.

**The win is accessor-specific, not a blanket rule.** It tracks whether the RNA property exposes the underlying typed array: `.vector` on FLOAT_VECTOR copies wholesale, while an INT `.value` read still resolves per element. Counter-example measured — `loops.foreach_get("vertex_index")` 165.7 ms vs `attributes[".corner_vert"]` 109.4 ms, only 1.5×. So **the Surface triangle gather (`gpu_sample.py:631-633`) does not get this win**: `loop_triangles` is derived data with no attribute backing. Surface gets the position win only; do not budget 56× for it.

### P2b — Skip occluded Surface visualizers

Two Surface visualizers on the same watch set produce **byte-identical geometry** — `build_surface_tris` is an identity pack of evaluated loop-tris (`gpu_sample.py:544`), and only the colours differ. They are drawn opaque (`depth_mask_set(True)`, `LESS_EQUAL`), so the later-drawn one wins completely and every earlier one is invisible work. `Facing Cull` cannot narrow one relative to another — it is Tags-only (`tags_draw.py:402`).

- [ ] For each watched object, evaluate only the **winning** Surface visualizer covering it; skip the rest.
- [ ] **Per watch set, not global.** A viz watching `{o1, o2}` is only fully occluded by one covering both. Partial overlap still needs the earlier viz evaluated for its uncovered targets.
- [ ] **Surface only. Do NOT extend to geometric.** Markers / Arrows / Tags carry per-viz Density and Seed, so two of them sample *different subsets* — they do not deterministically clobber, and skipping one would drop ink the user asked for.
- [ ] **Make precedence explicit before optimising on it.** Today the winner is an implicit consequence of `visualizers(scene)` iteration order. Skipping evaluation of a viz the user can still see enabled in the panel, with no indication why it shows nothing, trades a perf win for a "my visualizer vanished" bug. Surface the winner in the panel (or define and document the order) as part of this item, not after.
- [ ] Tests: two Surface viz on one target → one sample call, later-drawn colours win; partial-overlap watch sets → both still evaluated; two geometric viz with different Density → both evaluated.

### P3 — Closeout ✅

- [x] Regression suites green — `headless_test` 34, `test_gpu_sample` 188, `test_watch_collection` 45, `test_overlay_kinds`, `test_surface_direct` 11.
- [x] New perf baseline committed (`references/perf/gpu_vs_gn_scrub.txt`); old JSONs marked superseded (`../001_gpu_overlay/references/perf/SUPERSEDED.md`).
- [x] GUI confirmed: `mock_city.blend`, scrub `Seed` — markers track the buildings live.

**Remaining phases are evidence-gated, not scheduled.** P1 must not be built until a real
scene exceeds the budget; at 160k the marginal cost is now ~2 ms, and `mock_city` is ~2k
verts, so nothing observed so far argues for a throttle. Building the stress scene
(`examples/build_attr_stress_scene.py`) is the prerequisite for that evidence — the city
tool cannot yet produce one (see `blender_camera_distribution_pkg` backlog **GD**/**SD**).

---

## Measured and declined (do not re-propose without new numbers)

**Cull to frame centre during sampling** — progressive / Karma-XPU style: sample only what is near frame centre during a scrub, refine later. Blocked twice over. The cull is already an L1/L2 pass over *already-sampled* numpy arrays (`view_cull_geometric`, `gpu_overlay.py:1238`), same position as Density. Moving it earlier is circular — you need positions to compute frame distance, and reading positions *is* the cost. And a subset read is not expressible cheaply: `foreach_get` has no strided or indexed form, and per-element access is ~20× slower per element, so reading 10% costs **twice** what reading 100% in bulk costs (100k per-index vertex reads = 33.2 ms vs 1M bulk = 16.4 ms).

**Threading the sample** — `bpy` is not thread-safe; mesh data cannot be read off the main thread. Only the numpy tail is offloadable: 16.5 ms bpy-bound vs 11.1 ms numpy at 1M. Cooperative chunking via `bpy.app.timers` is the safe alternative if progressive refinement is ever genuinely needed. Both are recorded as available, neither is justified: P2 item 1 removes the cost that motivated them. Progressive refinement is the right tool for an irreducibly expensive workload — this was a constant-factor accessor mistake wearing that costume.

**Shared position cache across visualizers watching one target** — measured, real, and deferred. Caches are keyed on the *viz object* pointer, so N visualizers on one mesh re-read the same positions N times. On one 490k mesh: 14.6 / 30.5 / 44.3 ms for 1 / 2 / 3 visualizers — dead linear, and the only difference between them is a ~0.05 ms attribute read. This is exactly the `mock_city` shape (`height` / `width` / `depth` on one scatter). **Do not build the shared cache yet**: after P2 item 1 the per-viz position read drops to ~0.26 ms, so three visualizers cost ~0.8 ms instead of 44 ms. Re-measure after P2 and decline it explicitly if the numbers stay small — cross-visualizer invalidation, lifetime and eviction is real machinery to buy back under a millisecond.

## Expect a "regression" that is not one

The strangle POR credits the L0/L1 split with making "orbit/scrub cheaper". Orbit legitimately is — no depsgraph change, correct cache hit. Presentation scrubs legitimately are, via `_present_key`. But **driver scrubs were cheap because of this bug**: the cache hit when it should have missed. After P0, driver-scrub cost rises from ~0 to the real sample cost. That is the bug's cost becoming visible, not a new problem. Do not "fix" it by weakening invalidation.

## Stale perf baselines

`../001_gpu_overlay/references/perf/*.json` were captured against a `to_mesh()`-based sampler with a `sample.depsgraph_mesh` span that no longer exists in `gpu_sample.py`. They report 114–342 ms for work that now costs ~15 ms. Treat them as history, not as a target. Superseded by this task's harness — see `references/perf/`.

---

## Out of scope

- Compiled Overlay engine (locked above; escalate only with numbers beating an optimised Python path).
- Custom object type / draw override — not expressible in Blender (locked above).
- Restructuring the GN engine tree to be leaner. It is the fallback; its cost is not on the critical path.
- POR 007 instance-domain attributes — orthogonal, though both touch `watch_fingerprint`.
- Changing `_present_key` / L1 / L2, or any 003 / 005 colour behaviour.
- Reinstating count/matrix terms in the fingerprint.

---

## Current code (read first)

| File | Relevant state |
|------|----------------|
| `attrviz/gpu_sample.py:401-424` | `watch_fingerprint` — unevaluated counts + matrix. The bug. |
| `attrviz/gpu_sample.py:482` | `sample_evaluated` full read per object — before the cull. |
| `attrviz/gpu_sample.py:493` | `concat_density_cap` — why Density is not a scrub lever. |
| `attrviz/gpu_sample.py:147-151` | `_point_positions` — the legacy `vertices.foreach_get("co")`. **P2 item 1.** |
| `attrviz/gpu_sample.py:154-170` | `_cloud_positions` — already uses the attribute accessor (`:168`). The pattern to copy. |
| `attrviz/gpu_sample.py:246, :255` | `vertices.foreach_get("normal")` — the 128× case. |
| `attrviz/gpu_sample.py:544` | `build_surface_tris` — identity pack; why Surface viz clobber (P2b). |
| `attrviz/gpu_sample.py:624` | Surface positions — same accessor swap. |
| `attrviz/gpu_sample.py:631-633` | Surface tri gather — derived data, **no** accessor win. |
| `attrviz/gpu_overlay.py:95-110` | `_sample_key` (L0) — where the epoch lands. |
| `attrviz/gpu_overlay.py:113` | `_present_key` (L1/L2) — do not touch. |
| `attrviz/gpu_overlay.py:131-147` | `_gpu_visualizers` — hidden viz already skipped before sampling. |
| `attrviz/gpu_overlay.py:1180-1218` | Cache-hit early return and the L0 miss path. |
| `attrviz/gpu_overlay.py:1238` | `view_cull_geometric` — L1/L2, post-sample. Why frame-centre culling cannot move earlier. |
| `attrviz/gpu_overlay.py:1386, :1394` | Draw loop — per-visualizer, hence the shared-target re-read. |
| `attrviz/__init__.py:1280` | `_sync_vizcol_active` — the only `depsgraph_update_post` handler today. |
| `attrviz/node_builder.py:411` | `GeometryNodeObjectInfo` — the real DG edge the overlay is imitating. |

---

## Design constraints

| Constraint | Note |
|------------|------|
| No custom DG node | A Python `draw_handler` is outside the graph. The epoch is how it learns what the graph already knows. |
| Handler cost | `depsgraph_update_post` fires constantly. Walking `depsgraph.updates` is cheap; evaluating anything in there is not. |
| Element count changes | A seed scrub changes N (208 → 200). The GPU batch must be **rebuilt**, not refilled — there is no update-in-place fast path. |
| Lazy evaluation | Blender evaluates on access, not on `dg.update()`. Any benchmark must force evaluation or it measures nothing (see harness). |
| Budget | ~8 ms leaves room inside a 60 fps frame alongside Blender's own evaluation and the GPU upload. |
| Unmeasured | Both benchmark paths exclude draw: the overlay's `build_batch` upload (~13 ms in the old baselines) and Blender's drawing of the GN result. |

---

## Acceptance

1. Scrubbing `Seed` on `mock_city`'s scatter moves the markers with the buildings, live.
2. Each row of the change table above resamples: attribute values, vertex positions, added modifier, transform.
3. An element-count change (208 → 200) rebuilds the batch and draws the new count.
4. Orbit / navigate still never resamples.
5. Ramp / Range / Style / Length still never resample (003 / 005 green).
6. Below ~150k verts the throttle never engages; above it, releasing the drag always lands on an exact frame.
7. Two visualizers on unrelated objects: scrubbing one does not resample the other.
8. Positions read through the attribute accessor are byte-identical to the legacy read on evaluated GN meshes, and the 1M sample lands at ~11 ms or better.
9. Two Surface visualizers on one watch set produce one sample call, and the panel makes it clear which one is winning.
10. Two geometric visualizers with different Density on one target still both evaluate.
11. All five suites green.

---

## Validation

```bash
blender --background --factory-startup --python-exit-code 1 \
  --python tests/headless_test.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_gpu_sample.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_watch_collection.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_overlay_kinds.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_surface_direct.py
```

Perf harness (this task) — GPU overlay vs GN marginal cost per scrub tick:

```bash
blender --background --factory-startup \
  --python dev_tasks/008_overlay_invalidation/tests/bench_invalidation.py
```

It must keep asserting `6/6 distinct` per scale: if the sampled values do not change every tick, the "scrub" is a no-op and the numbers are meaningless. It forces lazy evaluation explicitly and measures against a no-visualizer baseline — both were needed to get honest numbers, and an earlier split that skipped them reported a 3.2× gap where the real one is 12×.
