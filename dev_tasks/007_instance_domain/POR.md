# POR: Instance-domain attributes (un-realized instances)

**Parent / history:** GPU overlay is THE path ([`../002_overlay_kinds/POR.md`](../002_overlay_kinds/POR.md)). 006 taught the sampler to read point clouds ([`../006_points_input/POR.md`](../006_points_input/POR.md)) — this POR reuses that path almost wholesale, because the instances component **is** a point cloud.
**Pickup:** `AGENT_ONBOARDING.md` (not written yet).
**Status:** Not started. Northstar: if the attribute is on the evaluated geometry, AttrViz lists it — instanced or not.

AttrViz **0.5.10+**. Blender **5.0+** (instances API verified on **5.2.0** only — see P0 probe).

---

## Why this POR exists

A GN network that ends in **Instance on Points** with no Realize node produces a geometry set with **zero mesh elements and N instances**. Every attribute stored before the instancing lives on the instance domain. AttrViz shows `No attributes on evaluated geometry` and offers nothing.

Repro, from `blender_camera_distribution_pkg/scenes/mock_city.blend` (`city_seeds`, GN group `city_seed_scatter`: Grid → Distribute Points on Faces → Store Named Attribute ×3 → Instance on Points):

```
evaluated_geometry() → <GeometrySet: 0 verts, 0 edges, 0 faces, 0 corners, 26 instances>

gs.instances_pointcloud().attributes:
  position, .reference_index, instance_transform, id,
  height (FLOAT), width (FLOAT), depth (FLOAT)        # 26 points
gs.instance_references() → [<GeometrySet: 8 verts, 12 edges, 6 faces, 24 corners>]
```

Two independent causes, both in `attrviz/__init__.py`:

1. **Discovery is blind.** `evaluated_attributes` walks exactly `gs.mesh`, `gs.curves`, `gs.pointcloud` (`__init__.py:489-491`). There is no branch for the instances component. In Blender 5.2 that component is reached by **`gs.instances_pointcloud()`** — a *method*, not one of the sibling properties — so a naive `getattr(gs, "instances", None)` returns `None` and adding `"instances"` to that tuple would silently do nothing.
2. **Intrinsics are gated on the wrong object.** `attributes_by_domain` sources `_domain_has_elements` from `me = getattr(ev, "data", None)` (`__init__.py:545-552`) — the top-level mesh, empty here — so even Index / Position / Normal are suppressed and `not any(by.values())` fires.

**Not a regression.** 0.1.2 (`9700920`) shipped the byte-identical three-component loop. AttrViz has never read the instances component.

**The scene is not at fault.** Instance on Points without Realize is the idiomatic, performant way to scatter. Requiring Realize as the price of visualization is the wrong trade: it is exactly the cost instancing exists to avoid, and it changes what you are looking at (below).

### The silent case is the dangerous one

`mock_city` is the loud failure — empty mesh, empty menu, obvious. The quiet failure is a graph that outputs **mesh *and* instances**: the mesh attributes populate the menu normally and the instance-domain attributes are dropped with no warning. The user sees a working menu that is missing half their data. Fixing discovery fixes both; the honesty label (P2) is what keeps the quiet case from recurring.

### Realize is a workaround, not the fix

| | Un-realized (26 instances) | After Realize Instances |
|---|---|---|
| Geometry | 0 verts | 208 verts, 156 faces |
| `height` lives on | 26 instance points | 208 mesh points (8 per building) |
| Markers | one per building | **8 coincident per building** |
| Cost | free | full scatter realized every eval |

Same attribute, different granularity. One value per building is the honest read; realizing turns it into a per-vertex smear that happens to look right under a color ramp and is wrong under Markers and Tags.

---

## Locked product

**Instance is a first-class domain in the RMB menu**, alongside Point / Edge / Face / Corner. Selecting `Instance → height` draws one sample per instance, at the instance origin.

| Display | Instance domain |
|---------|-----------------|
| **Markers** | Default. One marker per instance. ColorRamp (003) / hash (005) unchanged — they consume `(pos, values, dtype)`. |
| **Arrows** | Vector attr on instances, at instance origins. Non-vector → empty (same honesty). |
| **Tags** | Text at instance origins. This is the domain Tags are *best* at — one label per building. |
| **Surface** | Requires faces. Instances have none at this level. Empty + one-line reason, same as point-only in 006. |

Do **not** fold instance attributes into the Point domain. If an object has both a real mesh and instances, `height` on each is a *different attribute with a different element count*; collapsing them into one menu entry makes the sample ambiguous and silently picks one.

Do **not** realize instances to sample them. The whole point is reading the cheap representation.

### Implementation locks

1. **`node_builder.DOMAINS` stays four.** It drives the GPU-off GN tree (Normal bake loop, `DOMAIN_TO_BLENDER`, Separate Components). Adding `"Instance"` to it will ripple into the tree builder and break it. Introduce a **UI-level** list (`UI_DOMAINS = DOMAINS + ("Instance",)`) used by discovery, the RMB menus, and the sampler only.
2. **Instance domain is GPU-overlay-only.** The GN viz tree calls `GeometryNodeRealizeInstances` at `node_builder.py:420` before Separate Components — by construction it cannot express instance-domain sampling without a restructure. GPU-off keeps today's realize semantics. Do not restructure the GN tree in this POR; do not regress `headless_test.py`'s GPU-off coverage.
3. **Reuse 006's point path.** `instances_pointcloud()` returns a `PointCloud` whose attributes report domain `POINT`. `_read_attr` and the 006 Point-cloud sampling branch work on it unchanged. Extend `_evaluated_source` to return the instances cloud as a fourth component — do **not** fork a second sampler.
4. **Component precedence, not concat.** `_evaluated_source` already refuses same-object mesh+cloud concat. Same rule: the instances cloud is a *separate domain*, never concatenated into Point. An object may legitimately offer Point (mesh) and Instance (instances) simultaneously; they are independent menu entries.
5. **Domain reported as `POINT`, presented as Instance.** The UI domain is a presentation layer over a cloud whose attributes self-report `POINT`. Map at the boundary; do not rewrite Blender's reported domain.
6. **Depth-1 only.** Nested instances (instances of instances) are out of scope for P0. Read the top-level instances component; do not recurse `instance_references()`.
7. **Skip internals.** `.reference_index` is already filtered by the leading-`.` rule. `instance_transform` (FLOAT4X4) and `id` are *not* dotted — decide explicitly (P1) whether they surface; `instance_transform` has no ramp meaning and should be hidden.

---

## Progressive plan

### P0 — Probe + discovery

- [ ] **API probe across versions.** `instances_pointcloud()` / `instance_references()` verified on 5.2.0 only. Manifest floor is `blender_version_min = "5.0.0"`. Confirm the spelling and the method-vs-property shape on 5.0/5.1, or raise the floor. Lock findings in the POR table. Everything below assumes the 5.2 shape.
- [ ] Probe whether `position` on the instances cloud is the instance **origin** in object space, and whether it agrees with `depsgraph.object_instances[].matrix_world`. If `position` is not sufficient, derive from `instance_transform` translation. Do not guess — markers land wrong and it looks like a depth bug.
- [ ] `evaluated_attributes`: add the instances component via a `_instances_cloud(gs)` helper that tolerates method-or-property and returns `None` on failure. Tag its rows with a synthetic `INSTANCE` domain so `attributes_by_domain` can route them.
- [ ] `attributes_by_domain`: source `_domain_has_elements` from the **geometry set**, not `ev.data`. This alone restores intrinsics on any GN object whose top-level mesh is empty (a bug wider than instances).
- [ ] `_domain_has_elements`: Instance true iff the instances cloud has points; Point/Edge/Face/Corner unaffected by its presence.
- [ ] Tests: headless fixture reproducing `city_seed_scatter` (Grid → Distribute → Store ×3 → Instance on Points, no Realize) — `attributes_by_domain` returns `height`/`width`/`depth` under Instance and nothing under Point.

### P1 — Menu + sampling

- [ ] `ATTRVIZ_MT_domain_instance` menu class; `ATTRVIZ_MT_visualize` lists Instance when non-empty (skip-empty behaviour already generic).
- [ ] Intrinsics on Instance: Index and Position yes. **Normal no** — instances have no normal; do not invent one (006 precedent for clouds).
- [ ] Decide and implement the `instance_transform` / `id` filter (lock 7).
- [ ] `_evaluated_source` returns the instances cloud; `sample_evaluated(obj, name, "Instance")` returns the same `(pos, values, dtype)` shape, world-space applied.
- [ ] **Resolve the viz-object Domain input.** The visualizer's GN modifier stores Domain as a menu socket with four entries; Instance needs to round-trip through it (or be stored beside it) so a saved .blend reopens correctly. Mechanism unknown — probe before designing. This is the one place the overlay-only lock leaks into the GN group.
- [ ] `watch_fingerprint`: instance count, so adding/removing instances re-samples.
- [ ] Markers / Arrows / Tags on Instance. Surface on Instance → empty, no crash.

### P2 — UI honesty

- [ ] Panel label when a watched object has instance-domain attributes and the chosen domain has none — the quiet-case guard.
- [ ] Surface on Instance-only → label with reason, not a silent blank (same pattern as Surface-on-Edge and 006's point-only).
- [ ] Nested instances: if depth > 1 is detected, say so rather than silently reading only the top level.

### P3 — Closeout

- [ ] Three regression suites green (`headless_test.py`, `test_gpu_sample.py`, `test_watch_collection.py`).
- [ ] GUI: `mock_city.blend` with the Realize node **removed** — RMB → Instance → height draws 26 markers, one per building; Tags label each building once.
- [ ] Example scene committed (`examples/build_attr_instances_scene.py`), matching the 006 pattern.
- [ ] Commit only if asked.

---

## Out of scope

- Restructuring the GPU-off GN tree to express instance-domain sampling (lock 2).
- Recursing nested instances (P2 reports, does not read).
- Realizing instances anywhere in the sampler to make this easier.
- Object/collection dupli-instancing on Empties (`instance_type`) — different mechanism, no attributes; separate task if wanted.
- Volumes, Grease Pencil, curves (006 P2 leftover).
- 003/005 colormap changes — they consume `(pos, values, dtype)` and should need no edit.
- Adding `"Instance"` to `node_builder.DOMAINS`.

---

## Current code (read first)

| File | Relevant state |
|------|----------------|
| `attrviz/__init__.py:478-506` | `evaluated_attributes` — the three-component loop. Cause #1. |
| `attrviz/__init__.py:508-528` | `_domain_has_elements` — already tolerates a PointCloud (006). Caller is the problem, not this. |
| `attrviz/__init__.py:530-563` | `attributes_by_domain` — intrinsics gated on `ev.data`. Cause #2. |
| `attrviz/__init__.py:901-926` | `ATTRVIZ_MT_visualize` — skip-empty domain menus, already generic over the menu tuple. |
| `attrviz/gpu_sample.py:77-106` | `_evaluated_source` → `(ev, me, pc, gs)`, holds the GeometrySet (GC gotcha). Extend here. |
| `attrviz/gpu_sample.py:116` | `_read_attr` — works on any datablock with `.attributes`. Reusable as-is. |
| `attrviz/node_builder.py:22` | `DOMAINS` — four. Leave it. |
| `attrviz/node_builder.py:420` | `GeometryNodeRealizeInstances` in the viz tree — why GPU-off cannot do this domain. |

---

## Design constraints

| Constraint | Note |
|------------|------|
| Instances API | Blender 5.2: `gs.instances_pointcloud()` is a **method** returning `PointCloud`; `gs.instance_references()` returns `[GeometrySet]`. There is no `gs.instances`. Version floor unverified — P0. |
| Reported domain | Instance attributes self-report `POINT` on that cloud. UI-side mapping only (lock 5). |
| Element count | Instance count ≠ vertex count. `watch_fingerprint` must track it or the overlay goes stale. |
| Normal | Instances have none. Hide the intrinsic (006 precedent). |
| Perf | Reading the instances cloud is O(instances), not O(realized verts) — cheaper than today's GPU-off realize. Same L0 cache rules. |
| Mute | Instanced source draw is the competing solid, same class as 006 P4. **Deferred** — decide only after Markers land; do not bundle. |
| GC | Hold the GeometrySet while using the instances cloud, exactly as `_evaluated_source` already documents. |

---

## Acceptance

1. `mock_city.blend` with **no** Realize node: RMB → Visualize Attribute lists **Instance → height / width / depth**.
2. Selecting it draws **26** markers — one per building, at building origins — not 208.
3. Tags on Instance label each building exactly once.
4. Arrows on a vector instance attr work; on a scalar → empty, no crash.
5. Surface on Instance-only → empty with a reason, no invented triangles.
6. An object with mesh **and** instances lists both Point and Instance, with the correct element count on each.
7. Intrinsics (Index / Position) appear on any GN object whose top-level mesh is empty — the cause-#2 fix, independent of instances.
8. 003 ramp / 005 hash / 006 point clouds / mesh Surface all stay green. GPU-off GN path unchanged.

---

## Validation

Regression (every phase):

```bash
blender --background --factory-startup --python-exit-code 1 \
  --python tests/headless_test.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_gpu_sample.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_watch_collection.py
```

New headless fixture (`make_instanced(name, n)` in `tests/test_gpu_sample.py`) — Grid → Distribute Points on Faces → Store Named Attribute (`heat` FLOAT, `cluster` INT, `flow` FLOAT_VECTOR) → Instance on Points, **no Realize**:

1. `evaluated_geometry()` reports `0 verts, n instances`.
2. `attributes_by_domain` → `heat`/`cluster`/`flow` under **Instance**, none under Point.
3. `sample_evaluated(obj, "heat", "Instance")` → `len(pos) == n`, dtype FLOAT, world-space applied.
4. Sample positions match `depsgraph.object_instances[].matrix_world` translations (the P0 probe, asserted).
5. Point/Edge/Face/Corner sample on an instances-only object → `None`.
6. Mesh **and** instances on one object → Point count and Instance count both correct, independently.
7. INT on Instance → hash path; Arrows on `flow` non-empty, on `heat` empty.
8. `build_surface_tris` on an Instance-only watch → `None` / `n_tris == 0`.
9. Intrinsics present on an empty-top-level-mesh GN object (cause #2, no instances involved).

**GUI:** rsync `attrviz/` → the 5.2 extension dir (repo ≠ install; see README build/install), restart Blender, open `mock_city.blend` with the Realize node removed. One marker per building. Compare against the realized version — 8× marker count is the regression signal.
