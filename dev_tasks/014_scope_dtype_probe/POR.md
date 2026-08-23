# POR: the dtype probe must see the whole scope, not just its first object

**Parent / history:** falls out of
[`../011_viz_scope/POR.md`](../011_viz_scope/POR.md), which introduced
per-visualizer Scope. Scope made a visualizer watch *many* objects; the panel's
dtype probe was never updated and still inspects exactly one.
**Status:** **diagnosed and confirmed by measurement**, not fixed. Step 1 of the
Reproduction has been run — see "Step 1, measured".
**Severity: cosmetic.** The overlay draws correctly. The panel contradicts it.
**Northstar:** **the panel's two lines must describe the same object set.**
`viz_coverage`'s own docstring already states the invariant — "the number the
panel shows cannot disagree with what is drawn". This is that disagreement, one
line lower in the same panel.

AttrViz **0.5.12**. Blender **5.2.0**.

---

## TL;DR

With a multi-object Scope, the Viz panel says both of these at once:

```
2 objects  ·  1 carry grad_z          <- viz_coverage, iterates ALL objects
⚠ Non-vector → direction (0,0,0); no arrows   <- _target_attr_meta, probes meshes[0]
```

`grad_z` **is** a `FLOAT_VECTOR` on the Point domain, and `FLOAT_VECTOR` is in
`VECTORISH`. The dtype probe just looked at the wrong object.

The arrows draw anyway. The warning is false.

---

## Step 1, measured

The original draft marked "`meshes[0]` is specifically the non-carrying object"
as *inference*. [`repro.py`](repro.py) settles it:

```
watch_meshes_for_visualizer order : ['A_NoAttr', 'B_HasAttr']
A Point attributes : ['Index', 'Position', 'Normal']
B Point attributes : ['Index', 'Position', 'Normal', 'v']
'v' absent from B's ORIGINAL mesh (modifier-generated)   ok

viz_coverage(md)      -> 2 objects, 1 carry 'v'
_target_attr_meta(md) -> dtype=None domain='Point'
FAIL  INVARIANT n_draw > 0 implies a non-None dtype
```

And step 5 — identical data, carrier linked **first**:

```
order: ['B_HasAttr', 'A_NoAttr']
_target_attr_meta(md) -> dtype='FLOAT_VECTOR' domain='Point'
```

Nothing about the attribute changed. Only which object the probe landed on.
The inference is confirmed.

`watch_meshes_for_visualizer` order follows collection link order, so which
object is `meshes[0]` is an authoring accident with no relationship to the data.

---

## What is *not* the problem

Measured, so nobody re-treads it.

**The draw path is already correct.** `_sample_visualizer_targets_impl` is
already the "prepass then visualize" shape — it walks every object, skips the
ones that do not carry the attribute, and concatenates the rest:

```python
for obj in meshes:
    result = sample_evaluated(obj, attr, domain_ui, ...)
    if result is None:
        continue                 # skip non-carriers, do NOT abort
    pos_parts.append(p); val_parts.append(v); dtype = dt
```

Measured on the mixed scope:

```
A_NoAttr     -> None (skipped)
B_HasAttr    -> 9 pts, dtype=FLOAT_VECTOR
combined sample: 9 points, dtype=FLOAT_VECTOR
_arrow_alive_frames -> 9 arrows
```

**There is no fall-through on the first missing object.** The visualizer fires
on exactly the objects that carry the attribute, which is the expected
behaviour. Only the panel disagrees.

**The Arrows warning is a label, not a gate.** `__init__.py:1595` is
`body.label(...)` inside `_draw_viz_body`. It cannot stop anything drawing.

**`Attr Is Vector` is irrelevant here.** `_sync_attr_is_vector` does propagate
the bad probe into the GN tree — measured, `Attr Is Vector` flips False when the
non-carrier sorts first — and that *would* zero arrow directions in the engine
path. But `grep` confirms the socket is referenced **nowhere** in
`gpu_overlay`, `gpu_sample` or `tags_draw`: the GPU arrows path gates on the
actual array shape (`v.ndim != 2 or v.shape[1] < 2`) in `_arrow_alive_frames`.
**This project uses GPU mode only**, so the functional half does not apply.
Recorded because it makes the same bug functional for anyone using the
materials path.

---

## Attribute identity: what Blender actually guarantees

Measured, because the fix hinged on it:

```
created foo: name='foo' type=FLOAT domain=POINT
created foo again: name='foo.001' type=FLOAT_VECTOR domain=POINT
  -> Blender RENAMED the second one

point 'bar' -> 'bar'   face 'bar' -> 'bar.001'   (even across domains)
```

**Attribute names are unique per mesh, enforced by renaming.** On one object,
`foo` is exactly one dtype on exactly one domain. There is no overloading, and
numpy has nothing to do with attribute identity — it only appears downstream,
where a `(9,)` and a `(9,3)` refuse to stack.

The only place a name can carry two dtypes is **across two meshes**, because
Blender has no cross-object attribute registry:

```
M  foo -> FLOAT
M3 foo -> FLOAT_VECTOR      both legal
```

That becomes AttrViz's business only because Scope points one visualizer at
many meshes. It is a rare authoring accident — e.g. a `Measure` node group
duplicated and edited so its output changes type while keeping its name, with
the two variants on different objects in the same scope.

**It is not this bug.** This bug is **absence**: object `A` does not carry
`grad_z` at all. That is the common everyday case and what the report shows.

---

## The two paths that disagree

**Correct — `gpu_overlay.py`, `viz_coverage`:**

```python
objs = gpu_sample.watch_meshes_for_visualizer(md)
for obj in objs:            # every object in scope
    ...                     # via _viz_draws_on, the same predicate that mutes
```

**Wrong — `__init__.py:801-818`, `_target_attr_meta`:**

```python
if target is None:
    try:
        meshes = gpu_sample.watch_meshes_for_visualizer(md)
        target = meshes[0] if meshes else None      # <-- one arbitrary object
    except Exception:
        target = None
if target is None:
    return None, domain
```

`Target` is None whenever the visualizer is scoped to a collection rather than
a single object — **the normal case since 011**. If `meshes[0]` does not carry
the attribute, both the fast path (`me.attributes.get(attr)`) and the fallback
(`attributes_by_domain(target)`) miss, and `None` fails open at every
downstream test:

- `__init__.py:1595` — Arrows gate → the reported warning
- `__init__.py:1641` — RGB style gate → the same false negative
- `__init__.py:1580` — the `elif dtype:` branch that prints the dtype label is
  skipped, so the panel also stops telling the user the type at all

---

## Reproduction

[`repro.py`](repro.py) automates this. By hand, stock Blender 5.2:

1. Two meshes, `A` and `B`, both in the `attrvis` collection.
2. On **`B` only**, a Geometry Nodes modifier writing a vector attribute:
   `Store Named Attribute`, type Vector, domain Point, name `v`.
3. A visualizer scoped to `attrvis`, Attribute `v`, Domain Point, Display
   **Arrows**.
4. Panel reads `2 objects · 1 carry v` **and** `Non-vector → direction
   (0,0,0); no arrows` — while arrows draw.
5. Reorder so `B` links first. The warning disappears. Same data.

Step 5 is the proof: nothing about the data changed, only which object the
probe happened to land on.

---

## The fix

**Return the set of dtypes actually found in scope, and let the caller decide.**

```python
def _target_attr_meta(md):
    """(distinct dtypes carried in scope, domain)."""
```

Scan `watch_meshes_for_visualizer(md)`, collect each carrier's dtype, return
the distinct set. Domain is unchanged — it comes off the modifier, not the
objects.

The probe then **decides nothing**, which is the point. Downstream:

| `len(dtypes)` | Panel |
|---|---|
| 0 | existing "`attr` is not on `<domain>`" path, unchanged |
| 1 | today's behaviour exactly — label, Arrows/RGB gates, CATEGORICAL note |
| >1 | say so: `v: FLOAT on 1, FLOAT_VECTOR on 2`. Warn for Arrows only if **none** are vectorish — if some objects carry vectors, arrows genuinely draw there |

In every realistic scene `len(dtypes)` is 0 or 1 and behaviour is identical to
today. The `>1` branch is three lines that surface an authoring mistake instead
of letting the sampler raise (see "Known rough edge").

### Both paths must read the same map

This is what makes the invariant structural rather than asserted.

`viz_coverage` → `_viz_draws_on` → `_eval_attr_names`, which returns
`{domain: {names}}`. Extend it to `{domain: {name: dtype}}` — backward
compatible, because `_viz_draws_on` only does membership tests and dict
membership hits keys.

Then "carries it" is `attr in avail[domain]` and the dtype is
`avail[domain][attr]`: **the same lookup in the same structure**. The two panel
lines cannot drift apart, because they are reading one map built by one walk of
one list.

### Both original caveats dissolve

The first draft flagged two things to weigh. Measurement removed both.

1. **Cost — it goes *down*.** `_eval_attr_names` is the lean probe written for
   010: one `evaluated_get`, no `evaluated_geometry()`, no
   `evaluated_depsgraph_get()` per object, already cached per object per call.
   Today's fallback calls the UI-menu-weight `attributes_by_domain`, which is
   the source of the `~300ms on DistLook signs` note at `__init__.py:846`.
   Scanning N objects with the cheap probe is cheaper than probing one object
   with the expensive one.
2. **Disagreement — no policy needed.** Returning the set means never picking a
   winner. "First carrier wins" was a policy invented to resolve a collision
   that Blender's own uniqueness rules make rare and that the panel is better
   placed to report than to resolve.

### Rejected: pinning the dtype on the visualizer

Considered storing the dtype as a socket at pick time, making attribute
identity `(name, domain, dtype)` so a mismatched object counts as absent. It is
coherent and it would make the sampler's `ValueError` structurally impossible.
Rejected as disproportionate: it adds stored state, a migration, and a new
staleness mode ("`v` is now FLOAT_VECTOR — re-pick") to defend against a case
Blender's per-mesh uniqueness already makes rare.

---

## Known rough edge, out of scope

When two objects genuinely disagree, the sampler raises rather than degrading:

```
A_Float      -> 9 pts, dtype=FLOAT,        val.shape=(9,)
B_Vector     -> 9 pts, dtype=FLOAT_VECTOR, val.shape=(9, 3)
combined sample RAISED: ValueError: all the input arrays must have same
    number of dimensions, but the array at index 0 has 1 dimension(s) and
    the array at index 1 has 2 dimension(s)
```

`_sample_visualizer_targets_impl` concatenates across dtypes without checking.
009's `_draw_rows` contains the raise, so the viewport does not blank — that
visualizer logs once and draws nothing.

With this fix the panel warns *before* you hit it. Guarding the sampler itself
(skip objects whose dtype differs from the first carrier's) is two lines and a
separate decision; deliberately left out so it stays a decision.

---

## Testing

```
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_watch_collection.py
```

`_target_attr_meta` needs a real modifier, so the natural level is a scene test
alongside `tests/test_watch_collection.py`:

- scope of two objects, **only the second** carrying a Point `FLOAT_VECTOR` →
  dtypes == `['FLOAT_VECTOR']`, **not** empty
- same, with the carrying object **first** → identical result (guards against a
  fix that merely reverses the arbitrary choice)
- neither object carries it → empty, and the panel's existing "not on
  `<domain>`" path still fires
- both carry it with **different** dtypes → both reported, asserted explicitly
  so it is a decision rather than an accident

**The invariant test, because it is the northstar:** `viz_coverage(md)`
reporting `n_draw > 0` **⟹** `_target_attr_meta(md)` returns a non-empty dtype
set. That single assertion would have caught this.

---

## Files

| Path | Why |
|---|---|
| `attrviz/__init__.py:814` | `_target_attr_meta` — the `meshes[0]` probe. The bug. |
| `attrviz/gpu_overlay.py` | `_eval_attr_names` — extend to carry dtypes; the shared map |
| `attrviz/gpu_overlay.py` | `viz_coverage` — the correct whole-scope walk, and the invariant being violated |
| `attrviz/__init__.py:1565` | `_draw_viz_body` — the panel caller |
| `attrviz/__init__.py:1595` | Arrows gate — where the false negative surfaces (a label, not a gate) |
| `attrviz/__init__.py:1641` | RGB style gate — same false negative |
| `attrviz/__init__.py:1580` | the `elif dtype:` label branch, silently skipped |
| `attrviz/__init__.py:862` | `_sync_attr_is_vector` — the second caller; engine-path only |
| `attrviz/gpu_sample.py` | `watch_meshes_for_visualizer`, `_sample_visualizer_targets_impl` |
| `dev_tasks/014_scope_dtype_probe/repro.py` | step 1 + step 5, automated |

---

## Not in scope here

- The `grad_z` attribute itself is correct: a `FLOAT_VECTOR` on Point from a
  Geometry Nodes `Measure` node. Verified against the evaluated mesh.
- **Correction to the first draft:** it listed the `Normal`/`normal` casing
  collision as "still open". It is **closed** — verified in commit `d2bfa83`
  that no collision exists. A mesh carrying an authored lowercase `normal`
  offers both entries; visualizing `normal` reads the authored data and
  `Normal` reads the intrinsic, because the GN tree compares the name exactly.
  Three regression tests in `tests/test_gpu_sample.py` lock it in.
