# POR: an empty sample must draw nothing, not raise

**Parent / history:** the sample→present split lives in
[`../001_gpu_overlay/POR.md`](../001_gpu_overlay/POR.md) (frozen) and
[`../002_overlay_kinds/POR.md`](../002_overlay_kinds/POR.md).
**Status:** **fixed and validated** (2026-08-21). Northstar: **zero samples is
a legal state.** The frustum culler is allowed to return nothing, and every
consumer downstream of it has to survive that.

AttrViz **0.5.12**. Blender **5.2.0**.

> **Revision note.** The first draft of this POR diagnosed the raise correctly
> but framed the user-facing failure wrongly — as "an off-screen object draws
> nothing," which sounds local and benign. It is not local. The section
> "Layer 2 — why the array is empty" has been rewritten; the original's
> suspicion that "off-screen culling is the trigger" was right about the
> mechanism and wrong about the blast radius. See **Layer 3**.

---

## TL;DR

`gpu_color.heat_scalar` raises on an empty value array, reached whenever the
view culler legitimately culls a visualizer's samples to zero.

The raise itself is a one-line class of bug (`gpu_sample.buffer_stats` carried
the twin). **The severity is not in the raise — it is in the containment.**
The draw loop called `_refresh_viz` with no `try`/`except`, so one visualizer
raising killed the entire overlay pass and left Blender's GPU state dirty for
the rest of the frame. An object you are looking at loses its overlay because
a *different* object went off-screen.

---

## The failure

```
File "attrviz/gpu_overlay.py", line 1281, in draw_callback_view
  _draw_callback_view_impl()
File "attrviz/gpu_overlay.py", line 1423, in _draw_callback_view_impl
  _draw_gpu_entry(_refresh_viz(obj, md, display))
File "attrviz/gpu_overlay.py", line 1264, in _refresh_viz_impl
  entry = _refresh_markers(...)
File "attrviz/gpu_overlay.py", line 891, in _refresh_markers
  scalars = gpu_color.heat_scalar(values, dtype)
File "attrviz/gpu_color.py", line 172, in heat_scalar
  return np.linalg.norm(v.reshape(len(v), -1), axis=1).astype(
ValueError: cannot reshape array of size 0 into shape (0,newaxis)
```

Line numbers are pre-fix. Reported while visualizing `Normal` on a mesh.
**`Normal` is a red herring** — see "What is not the problem".

---

## Layer 1 — why it raises

`reshape(len(v), -1)` is **ambiguous at size 0**: numpy cannot infer the free
dimension when the total element count is zero.

```
>>> np.asarray([], dtype=np.float32).reshape(0, -1)
ValueError: cannot reshape array of size 0 into shape (0,newaxis)

>>> np.asarray([], dtype=np.float32).reshape(-1, 3).shape
(0, 3)
```

Nothing about this is attribute-specific. **Any** `FLOAT_VECTOR` or `FLOAT2`
visualizer with zero surviving samples hits it.

### A second, quieter problem in the same line

`reshape(len(v), -1)` silently depended on `values` arriving **already 2-D**
`(N, 3)`. Handed a flat `3N` array it produced `(3N, 1)` and the norm became
`abs()` of each individual component — wrong numbers, no error. Deriving the
component count from the dtype fixes the empty case *and* closes that hole.

---

## Layer 2 — why the array is empty

`view_cull_geometric` ([`overlay_kind.py:98`](../../attrviz/overlay_kind.py))
returns an empty slice **by design** when an object leaves the frustum. That is
correct behaviour producing an input the presenter could not handle.

### The cull policy is not at fault — measured, not read

A recurring instinct is to fix this in the cull: "don't return nothing, use the
frustum score to keep samples near screen centre under the cap." **That is
already exactly what the culler does**, and it is not implicated. Measured by
running `view_cull_geometric` standalone against a synthetic perspective matrix
(it imports only `math` and `numpy` — no `bpy`):

| case | in frustum | cap | kept |
|---|---|---|---|
| 1k pts, centered | 940 | 50000 | **940** |
| 200k pts, centered | 185,563 | 50000 | **50,000** |
| 200k pts | 185,563 | 1000 | **1,000** |
| 200k pts | 185,563 | 10 | **10** |
| cloud off to +X | 0 | 50000 | **0** |
| cloud behind camera | 0 | 50000 | **0** |

Over the cap it returns *exactly* the cap, never nothing, and the survivors are
centre-biased:

```
fd [0.00,0.25)  all=  8098  kept=  8098  survival=100.0%
fd [0.25,0.50)  all= 19462  kept= 18079  survival= 92.9%
fd [0.50,0.75)  all= 23253  kept=  9406  survival= 40.5%
fd [0.75,1.00)  all= 21482  kept=  3008  survival= 14.0%
```

Two structural reasons the scoring stage cannot be the cause:

1. **It cannot produce zero.** `scale = cap / weight.sum()` normalises expected
   survivors to `cap`, and `weight` has a hard floor of `_CULL_FLOOR = 0.05`,
   so no sample's keep probability can reach zero. The floor is deliberate
   ("edges are thinned but not zeroed").
2. **It does not run.** `if n_in_view <= cap: return everything` short-circuits
   below 50,000 in-frame samples on a *single* visualizer. In ordinary scenes
   the weighted-budget block never executes at all.

The only reachable path to zero rows is the binary `in_frustum` test, and
returning zero there is the right answer. **No correct culler has a
postcondition better than `n >= 0`** — so this can never be fixed in the cull
policy. It is a contract mismatch at the boundary: producer postcondition
`n >= 0`, consumer precondition `n >= 1`.

---

## Layer 3 — why the blast radius is the whole viewport

This is the part the first draft missed, and the part that matters.

`_draw_callback_view_impl` iterated visualizers with **no per-object guard**:

```python
for obj, md, display in depth_tested:
    _draw_gpu_entry(_refresh_viz(obj, md, display))
```

The traceback confirms it — the exception escapes all the way to
`draw_callback_view` before Blender catches it at the handler boundary. So:

- **One visualizer raising kills the pass.** Every overlay after it in the loop
  never draws. The object under your cursor loses its arrows because a sibling
  five metres away left the frustum.
- **It is orbit-dependent, not off-screen-dependent** from the user's seat. As
  you orbit, siblings cross the frustum boundary; the moment one leaves, the
  pass dies. Orbit back and everything returns. Symptom: identical framing,
  overlay present at one camera angle and absent at a slightly different one.
- **The reporter's own traceback proves the raiser is not the object they were
  watching.** It routes through `_refresh_markers`, but `display == "Arrows"`
  dispatches to `_refresh_arrows` — the `_refresh_markers` branch is reachable
  only from **Markers or Tags**. They were watching Arrows vanish.
- **GPU state leaked.** The raise happened after `depth_mask_set(False)` /
  `face_culling_set('NONE')` and before the restore at the bottom of the
  function, so a crashed frame left Blender's own drawing with AttrViz's depth
  mask and face culling for the remainder of that frame.

Also ruled out as a cause of the on-screen object culling itself to zero:
sampled positions are genuinely world-space — `_to_world(positions,
ev.matrix_world)` is applied at every return path in `gpu_sample.py`. There is
no projection bug.

---

## What is *not* the problem

Ruled out with measurements, so nobody re-treads it:

| Suspicion | Verdict |
|---|---|
| The mesh has no normals | **False.** `mesh.vertex_normals` = 1060 entries, all unit length. |
| `mesh.attributes` should contain `normal` | **No — and it never will.** Normals are *derived* data: fully determined by positions + topology + sharp flags, cached in `vert_normals()` / `face_normals()` / `corner_normals()`. `mesh.attributes` holds only authored data. Treating `Normal` as a GN field intrinsic is the **correct** design. |
| The `Normal` intrinsic reads garbage | **False.** A `GeometryNodeInputNormal` → `Store Named Attribute` round trip returned 1060 unit vectors byte-identical to `mesh.vertex_normals`. |
| The object was broken / empty | **False.** It evaluated to 1060 verts / 1054 faces. |
| The cull policy zeroes on-screen objects | **False.** Measured — see Layer 2. Over-cap returns exactly `cap`, centre-biased. |
| Sampled positions are in the wrong space | **False.** `_to_world` is applied at every return path in `gpu_sample.py`. |
| Lowercase `normal` vs `Normal` | Not the cause here (the menu only ever offers the capitalised intrinsic), but note `INTRINSIC_ALIASES` aliases lowercase `position` only. If a mesh ever *does* carry an authored `normal` attribute, the two paths will collide. **Still open** — see "Still open". |

The bounding-box display people report alongside this is **not this bug** —
`gpu_overlay.py` deliberately stashes `display_type` and sets `BOUNDS`/`WIRE` so
markers are not buried inside the solid surface. Combined with a dead overlay
pass it just *looks* like a broken object: muted geometry, nothing drawn.

> **Amended.** That is true of the mute *mechanism* and false of its *scope*.
> Validating this fix surfaced a real defect: enabling any Surface visualizer
> muted every mesh in `attrvis`, including objects whose attribute it did not
> carry, hiding them with nothing drawn in their place. Fixed separately in
> [`../010_mute_scope/POR.md`](../010_mute_scope/POR.md).

---

## The fix (implemented)

Four changes, applied in dependency order, each validated before the next.

### 1. `heat_scalar` accepts zero rows — `gpu_color.py:168`

```python
if dtype in ("FLOAT_VECTOR", "FLOAT2"):
    ncomp = 3 if dtype == "FLOAT_VECTOR" else 2
    return np.linalg.norm(v.reshape(-1, ncomp), axis=1).astype(
        np.float32, copy=False,
    )
```

Correct for `(0,)`, `(N, 3)` and flat `(3N,)` alike, and now *raises* on a
genuinely wrong-length buffer instead of reshaping into the wrong component
count. Verified: `heat_scalar([1,2,3,4], "FLOAT_VECTOR")` → `ValueError:
cannot reshape array of size 4 into shape (3)`.

### 2. `buffer_stats` guard hoisted above the reshape — `gpu_sample.py:976`

```python
stats["val_min"] = float(values.min()) if values.size else None
stats["val_max"] = float(values.max()) if values.size else None
```

min/max are reshape-invariant, so the `(N, -1)` reshape bought nothing and only
raised. The emptiness case *was* anticipated — the guard was one line too late.
This also makes the float branch match the integer branch directly below it.

`grep -rn "reshape(len(" attrviz/` now returns nothing. The defect class is
gone, not just its two known sites, and a test asserts it stays gone.

### 3. Zero samples is a first-class state — `gpu_overlay.py:1270`

A shared `_empty_entry(skey, pkey, bkey)` helper (`gpu_overlay.py:1087`), used
both by the existing empty-sample early return and by a new one immediately
after the cull:

```python
if len(positions) == 0:
    entry = _empty_entry(skey, pkey, bkey)
    _caches[ptr] = entry
    return entry
```

Presenters are never handed a zero-row buffer at all. This caches safely:
`bkey` already folds in the view signature, so the empty entry invalidates the
moment the view moves — no stickiness once the object orbits back into frame.

### 4. Containment — `gpu_overlay.py:1440`

The change that actually matters. `_draw_rows(rows, refresh, draw)` wraps each
visualizer, and takes its callables as arguments so the containment rule is
testable without a GPU draw context — the same reason `_split_geometric_depth`
was split out.

```python
def _draw_rows(rows, refresh, draw):
    ok = True
    for obj, md, display in rows:
        try:
            draw(refresh(obj, md, display))
        except Exception:
            ok = False
            _note_viz_error(obj, display)
    return ok
```

All three draw loops (surfaces, depth-tested, on-top) route through it.
`_note_viz_error` (`gpu_overlay.py:1421`) reports one traceback per
`(object, display)` rather than one per redraw — the handler runs every frame,
so an unguarded `print` floods the console at refresh rate and buries the first,
most useful traceback. `reset_viz_errors()` re-arms it.

The GPU state restore moved into a **`finally`**: depth mask, depth test and
face culling are now restored even if something escapes the body.

---

## Validation

A standalone baseline harness reproduces all four defects with no Blender and
no GPU: [`baseline_repro.py`](baseline_repro.py).

```
python dev_tasks/009_empty_sample_crash/baseline_repro.py
```

Before the fix — check 1 reproduces the reported `ValueError` verbatim:

```
  FAIL  heat_scalar accepts a zero-row vector sample
          ValueError: cannot reshape array of size 0 into shape (0,newaxis)
  FAIL  heat_scalar handles flat (3N,) input
          ValueError: operands could not be broadcast together with shapes (6,) (2,)
  FAIL  no ambiguous reshape(len(x), -1) in attrviz/
  FAIL  draw loop contains a per-visualizer raise
0/4 passed, 4 failed
```

After: `4/4 passed, 0 failed`.

### Regression tests added

| File | Covers |
|---|---|
| `tests/test_gpu_color.py` (new) | `heat_scalar` empty / flat / 2-D / ragged-raises; every colour mapper on a zero-row sample |
| `tests/test_draw_guard.py` (new) | `_draw_rows` containment (refresh-side and draw-side raises, all-rows-failing, clean pass); GPU state restored in a `finally` |
| `tests/test_overlay_kinds.py` | `test_view_cull_offscreen_feeds_present` — cull to empty, then hand the result straight to the colour mappers |
| `tests/test_gpu_sample.py` | `buffer_stats` on empty and non-empty; no `reshape(len(` remains |

The producer contract (off-screen → zero rows) was *already* tested by
`test_view_cull_offscreen_skipped`. What was never tested is that a consumer
survives it. That join is the actual regression guard.

### Full suite, Blender 5.2.0 headless — all green

```
test_gpu_color        exit=0
test_draw_guard       exit=0
test_overlay_kinds    exit=0    (incl. cull -> present on empty)
test_gpu_sample       exit=0    228 passed, 0 failed
test_watch_collection exit=0     45 passed, 0 failed
test_surface_direct   exit=0
```

```
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_gpu_color.py
```

Note the GPU overlay itself is **not** headless-testable — the draw handler
needs a real viewport, and every visualizer object evaluates to 0 elements in
`--background` regardless of health. Do not treat "0 elements headless" as a
symptom; it is normal. That is precisely why `_draw_rows` takes its callables
as arguments.

### Empty-input audit (the original POR's follow-up list) — all clean

`heat_scalar` was the only defect in `gpu_color`. Confirmed handling zero rows
correctly and returning `(0, 4)`: `hash_colors`, `ramp_colors`, `heat_colors`
(FLOAT and VECTOR), `rgb_colors`, `values_to_colors` (FLOAT / VECTOR / INT).
Locked in by `test_colour_mappers_accept_empty`.

---

## Reproduction (in-app)

**No custom Blender needed** — stock 5.2 reproduces it.

1. New scene. Add ~6 cubes spread far apart along X, e.g. at x = 0, 20, 40, 60,
   80, 100.
2. On each, add a Geometry Nodes modifier that writes a **vector** attribute.
3. Visualize it on **all** of them. Give at least two objects *different*
   displays — e.g. **Arrows** on the one you will watch, **Markers** on the
   rest. This matters: it is what surfaces the containment bug rather than a
   single object's own crash.
4. Frame one object so it fills the view, then orbit slightly so the others
   leave the frustum.

Before the fix: the **on-screen** object's overlay vanishes and a `ValueError`
prints on every redraw. Orbiting back restores it. Watch the object that is
*still in frame* — that is the observable, not the off-screen ones.

After the fix: off-screen objects draw nothing, the on-screen object keeps its
overlay, no exception.

Run Blender from a terminal so the traceback is visible — draw-handler
exceptions do not surface in the UI.

---

## Still open

Neither blocks this fix; both were surfaced by it.

- **The instance budget is per-object, not global.** `cap` is hardcoded to
  50000 at `_refresh_viz` and never overridden, and applies to each visualizer
  independently — a 15-object scene can upload 750k instances with nothing
  noticing. If the cap exists to bound GPU cost, it is bounding the wrong
  quantity. This is also why the centre-bias weighting is effectively dead code
  in ordinary scenes (Layer 2). Fixing it is a real design change: a global
  budget divided across visualizers by projected screen area.
- **Centeredness is the wrong control variable for a density budget.** The
  docstring promises "smooth density falloff," but `frame_dist` measures
  distance from frame centre, not screen-space density. A fully visible object
  off to one side has *all* its samples down-weighted together, so its arrow
  density breathes as you orbit. If the goal is a draw budget, the honest
  variable is projected screen density.
- **The frustum test uses the sample point, not the drawn extent.** An arrow
  whose base is just outside the frame but whose head points inward is culled,
  so arrows pop at the frame edge. `pad=0.05` is a constant fudge for a
  quantity that actually depends on arrow scale and distance.
- **`INTRINSIC_ALIASES` aliases lowercase `position` only.** If a mesh carries
  an authored lowercase `normal` attribute it will collide with the `Normal`
  intrinsic. Separate work.

---

## Files

| Path | Why |
|---|---|
| `attrviz/gpu_color.py:168` | `heat_scalar` — **fixed**, reshape by component count |
| `attrviz/gpu_sample.py:976` | `buffer_stats` — **fixed**, guard hoisted above the reshape |
| `attrviz/gpu_overlay.py:1087` | `_empty_entry` — shared draws-nothing cache entry |
| `attrviz/gpu_overlay.py:1270` | post-cull early return — zero samples as a first-class state |
| `attrviz/gpu_overlay.py:1421` | `_note_viz_error` — rate-limited per-visualizer reporting |
| `attrviz/gpu_overlay.py:1440` | `_draw_rows` — **the containment**; one bad visualizer no longer blanks the pass |
| `attrviz/gpu_overlay.py:1459` | `_draw_callback_view_impl` — GPU state restore moved into `finally` |
| `attrviz/overlay_kind.py:98` | `view_cull_geometric` — **unchanged**; measured correct, see Layer 2 |
| `attrviz/node_builder.py:39` | `INTRINSICS` — why `Normal` is a field, not a lookup |
| `dev_tasks/009_empty_sample_crash/baseline_repro.py` | standalone red/green harness |
