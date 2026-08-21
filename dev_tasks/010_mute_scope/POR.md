# POR: mute only what a visualizer can actually draw on

**Parent / history:** surfaced while validating
[`../009_empty_sample_crash/POR.md`](../009_empty_sample_crash/POR.md), which
records the `BOUNDS`/`WIRE` display mute as "not a bug". That was true of the
mute *mechanism* and false of its *scope*.
**Status:** **fixed and validated** (2026-08-21).
**Northstar:** **muting means the overlay replaces the original.** An object no
enabled visualizer can draw on must stay visible — hiding it puts nothing in
its place.

AttrViz **0.5.12**. Blender **5.2.0**.

---

## TL;DR

Enabling *any* Surface visualizer muted *every* mesh in `attrvis` to `BOUNDS`,
regardless of whether that visualizer's attribute existed on each object. An
object without the attribute got hidden with nothing drawn where it was — it
simply vanished.

Reported as "disabling a visualizer doesn't bring the objects back". The
restore path was never broken; the mute set was too wide.

---

## The symptom

Four visualizers on a 5-mesh `attrvis`: `Normal · Point · Arrows`,
`grad_z · Point · Surface`, `lap_z · Point · Surface`, `K · Point · Surface`.
Two of the meshes carry none of `grad_z` / `lap_z` / `K`.

Turning `lap_z` off changed nothing — the two boxes stayed invisible. It read
as a broken restore. It was not: `grad_z` and `K` were still enabled, and each
independently muted all five meshes. Untick all three and everything returns.

---

## The bug

`gpu_overlay._active_watch_targets`, before:

```python
coll = gpu_sample.scene_watch_collection()
if coll is not None:
    out = []
    seen = set()
    for obj in coll.objects:
        _append(obj, out, seen)
    return out
```

Three defects in eight lines:

1. **No drawability test.** `_append` filtered on `obj.type` alone. Nothing
   checked whether the visualizer's attribute exists on the object.
2. **`kind_mds` discarded.** The per-visualizer watch sets collected thirty
   lines above were thrown away whenever an `attrvis` collection existed.
3. **`coll.objects` does not recurse.** `gpu_sample.iter_watch_meshes` walks
   nested sub-collections; this did not. Objects in `attrvis` sub-collections
   were sampled and drawn but never muted — a silent double-draw.

### Measured, before the fix

[`mute_scope_repro.py`](mute_scope_repro.py) — two meshes in `attrvis`, only
one carrying `K`, one Surface visualizer on `K`:

```
after enabling ONE Surface viz on 'K':
  HasK display_type = BOUNDS
  NoK  display_type = BOUNDS        <- muted, but nothing can be drawn on it

  visualizer watch set: ['HasK', 'NoK']
  mute target set:      ['HasK', 'NoK']
```

Note the restore rows in that same run passed. **This was never a restore
bug.**

### Why per-visualizer targeting alone would not have fixed it

The obvious repair — use `kind_mds` instead of `coll.objects` — does not help
on its own. The repro shows `watch_meshes_for_visualizer(md)` also returned
*both* objects, because the visualizer's scope **is** the whole collection. The
discriminator is not targeting, it is attribute availability.

---

## The fix

### 1. A drawability predicate — `gpu_overlay._viz_draws_on`

```python
if not attr or not domain:
    return False        # nothing selected -> nothing drawn
...
names = avail.get(domain, ())
if attr in names:
    return True
if attr in node_builder.INTRINSIC_ALIASES:
    return node_builder.POSITION_ATTR in names
return False
```

**Undeterminable → `True`.** Only a confident "the attribute is absent here"
unmutes, so a flaky probe cannot regress the scene into double-drawn
originals — the failure mode is the previous behaviour, not a new one.

### 2. Unified watch-target resolution

Both branches now go through `gpu_sample.watch_meshes_for_visualizer(md)`,
which applies whichever scoping is in force *and* recurses nested
sub-collections — closing defect 3 as a side effect.

```python
for md in kind_mds:
    for obj in gpu_sample.watch_meshes_for_visualizer(md):
        if obj is None or obj.type != blender_type:
            continue
        ...
        if not _viz_draws_on(md, obj, attr_cache, dg):
            continue
        seen.add(key)
        out.append((obj, show_wire))
```

### 3. The intrinsics trap

The obvious probe — "is the attribute in `obj.data.attributes`?" — is **wrong**,
and 009 already documents why: `Normal` is derived data and never appears in
`mesh.attributes` by design. A naive presence check unmutes every object under
a `Normal` visualizer.

`_eval_attr_names` therefore adds `node_builder.INTRINSICS` (Index / Position /
Normal) per domain, and withholds `Normal` where it genuinely does not exist
(no `vertices` — point clouds). Lowercase `position` is accepted as an alias of
the `Position` intrinsic. Locked in by
`010 intrinsic Normal still mutes the attribute-less object`.

Instance-domain visualizers return `True` (undeterminable): instance attributes
live on the instances cloud rather than `obj.data`, and reading them needs the
full geometry-set probe this deliberately avoids.

### 4. The handler-safety constraint — the non-obvious part

The first implementation used `attributes_by_domain()`, which is the richer and
more obviously correct probe. **It broke `test_watch_collection` immediately:**

```
AttributeError: 'NoneType' object has no attribute 'select_set'
  File "tests/test_watch_collection.py", line 163, in <module>
    o.select_set(False)
```

`attributes_by_domain()` calls `bpy.context.evaluated_depsgraph_get()` and
`ev.evaluated_geometry()`. But `_sync_surface_target_mute` is reached from
`_sync_vizcol_active`, a `@persistent` **depsgraph handler** that fires on every
update. Forcing an evaluation from inside one resyncs the view layer underneath
whatever is iterating it — hence `view_layer.objects` yielding `None`.

Isolated by short-circuiting the probe: 45/45 passed with it stubbed, so the
restructure was sound and the probe was the fault.

The fix is `_eval_attr_names`, a lean read of `evaluated_get(dg).data
.attributes` using **the depsgraph the caller already has**.
`_sync_vizcol_active` now threads its own `depsgraph` through
`sync_surface_target_mute(scene, dg=depsgraph)`; `evaluated_depsgraph_get()` is
called only when no depsgraph was supplied, i.e. outside handler context.

> **Rule for anyone touching this path:** `_sync_surface_target_mute` and
> everything it calls run inside a depsgraph handler. Do not force an
> evaluation there. `attributes_by_domain()` is UI-menu-weight and is not safe
> to call from it.

---

## Validation

```
blender --background --factory-startup --python-exit-code 1 \
  --python dev_tasks/010_mute_scope/mute_scope_repro.py
```

Before: `3 passed, 1 failed`. After: `4 passed, 0 failed`, and the mute target
set narrows to exactly the drawable object:

```
  HasK display_type = BOUNDS
  NoK  display_type = TEXTURED
  mute target set:      ['HasK']
```

### Regression tests — `tests/test_watch_collection.py`

```
== 010: mute scope follows drawability ==
  ok   010 object carrying the attribute is muted
  ok   010 object lacking the attribute stays visible
  ok   010 mute target set excludes the attribute-less object
  ok   010 intrinsic Normal still mutes the attribute-less object
  ok   010 intrinsic Normal mutes the other mesh too
  ok   010 disabling restores the attribute-less object
  ok   010 disabling restores the attribute-carrying object
```

### Full suite, Blender 5.2.0 headless — all green

```
test_watch_collection  exit=0    52 passed, 0 failed   (was 45)
test_gpu_sample        exit=0   228 passed, 0 failed
test_surface_direct    exit=0    11 passed, 0 failed
test_overlay_kinds     exit=0
test_gpu_color         exit=0
test_draw_guard        exit=0
009 baseline_repro     exit=0     4/4
```

---

## What this does *not* fix

**Deliberate exclusion.** An object that *has* the attribute is still muted by
any enabled visualizer that reaches it. There is no way to say "visualize `K`
on these three meshes but not that one" — the drawability test is automatic,
not a user control.

That is the case for per-visualizer collection scoping, filed as **011**. The
mechanism already exists: every visualizer carries `Target ∪ Scope` sockets and
`Scope` is a collection, but `gpu_sample.watch_meshes_for_visualizer` shadows
them whenever a collection literally named `attrvis` exists —
"it is the watch set for every visualizer", per its own docstring.

011 is un-shadowing that, not building it. The open design decision is
migration: `attrvis` should become the **default value** of `Scope` for new
visualizers rather than a global override, so existing files behave the same
until someone repoints a `Scope`. Three current tests assert the shadowing
(`empty attrvis suppresses per-viz Scope`, `no attrvis → Scope fallback
samples`, `GUI add-viz Scope is attrvis`) and would need revisiting.

---

## Files

| Path | Why |
|---|---|
| `attrviz/gpu_overlay.py` `_eval_attr_names` | lean, handler-safe evaluated-attribute read; intrinsics folded in |
| `attrviz/gpu_overlay.py` `_viz_draws_on` | the drawability predicate; undeterminable → mute |
| `attrviz/gpu_overlay.py` `_active_watch_targets` | unified resolution; drops the `coll.objects` special case |
| `attrviz/gpu_overlay.py` `_sync_surface_target_mute` | accepts `dg`; only calls `evaluated_depsgraph_get()` outside handlers |
| `attrviz/__init__.py` `_sync_vizcol_active` | threads the handler's own depsgraph through |
| `attrviz/gpu_sample.py:600` | `watch_meshes_for_visualizer` — the `attrvis` shadowing that 011 addresses |
| `dev_tasks/010_mute_scope/mute_scope_repro.py` | red/green repro |
