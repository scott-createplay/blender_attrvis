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

**Probes resolved (5.2.0).** Three unknowns closed before implementation:

1. **⚠️ `position` on the instances cloud is UNRELIABLE — use `instance_transform`.** The first read in this POR matched the depsgraph exactly, and that was luck. On 5.2 the `position` attribute of the instances pointcloud reads **uninitialised memory** — `9.1e+30` or zeros — on every call except a lucky first `evaluated_geometry()` in a fresh process. Every *other* attribute on the same cloud (`instance_transform`, `id`, and user attributes like `height`) reads correctly and stably, so the bug is specific to `position`, which is presumably synthesised per call into a buffer that is not always filled.

   Releasing references and forcing `gc.collect()` does **not** restore it — this is not a lifetime/GC issue, so the usual "hold the GeometrySet" rule does not help.

   **Fix:** derive origins from `instance_transform` (FLOAT4X4, stored **row-major** → translation is row 3). Verified stable across repeated calls and equal to `depsgraph.object_instances[].matrix_world` translations. Values are object-local, so the existing `_to_world` step applies as for meshes and clouds.

   **Testing lesson:** a single-shot test cannot see this — the first read is the one that works. The regression test samples **twice** and compares against the depsgraph's own matrices rather than against the `position` attribute it is meant to replace.
2. **The Domain "menu socket" wrinkle does not exist.** `_menu_switch` builds a plain `NodeSocketInt` (min 0, max 3) plus a name→index dict on the tree (`attrviz_menu_Domain` = `{Point:0, Edge:1, Face:2, Corner:3}`). Setting `Domain = 4` stores and reads back fine; `menu_input_name` just returns the raw `4` for lack of a map entry. **The int round-trips through the .blend for free** — no ID-prop or menu-socket problem to solve.
3. **The values are the real values.** Un-realized instance-domain `height` is byte-identical to what Realize duplicates onto 8 verts per building (`realized per-building values == instance-domain values: True`). Realize *duplicates*; it does not compute. Reading the instance domain is strictly more faithful.

- [ ] **Version floor — undecided, cannot be tested here.** Only Blender 5.2 is installed; no 5.0/5.1 binary on the machine. `blender_version_min = "5.0.0"` is therefore unverified for `instances_pointcloud()`. Either raise the floor to what is actually tested, or ship and document the risk. **Decision required before release, not before implementation.**
- [ ] `evaluated_attributes`: add the instances component via a `_instances_cloud(gs)` helper that tolerates method-or-property and returns `None` on failure. Tag its rows with a synthetic `INSTANCE` domain so `attributes_by_domain` can route them.
- [ ] `attributes_by_domain`: source `_domain_has_elements` from the **geometry set**, not `ev.data`. This alone restores intrinsics on any GN object whose top-level mesh is empty (a bug wider than instances).
- [ ] `_domain_has_elements`: Instance true iff the instances cloud has points; Point/Edge/Face/Corner unaffected by its presence.
- [ ] Tests: headless fixture reproducing `city_seed_scatter` (Grid → Distribute → Store ×3 → Instance on Points, no Realize) — `attributes_by_domain` returns `height`/`width`/`depth` under Instance and nothing under Point.

### P1 — Menu + sampling ✅

- [x] `ATTRVIZ_MT_domain_instance` menu class + one entry in the `menus` tuple. Skip-empty was already generic, so a plain mesh never grows a spurious Instance row.
- [x] **Domain plumbing.** `node_builder.DOMAINS` stays four; `UI_DOMAINS = DOMAINS + ("Instance",)` added *in node_builder* so `__init__` and `gpu_sample` share one definition. `attrviz_menu_Domain` extended with `Instance: 4`, socket `max_value` bumped, and a fifth Index Switch item on **both** the Domain and Surface switches wired to empty geometry.
- [x] Intrinsics on Instance: Index and Position. **No Normal** (006 precedent).
- [x] Attribute filter: `instance_transform` hidden; **`id` kept** for the 005 hash path.
- [x] Instances read as a fourth component via `gpu_sample.instances_cloud()`.
- [x] `watch_fingerprint` unchanged — 008's epochs already cover it.
- [x] Markers / Arrows / Tags on Instance; Surface implemented properly (below).

**Three bugs found in the process, all worth remembering:**

1. **The UI holds its own copies of the domain list.** `ATTRVIZ_OT_add.domain`, `_DOMAIN_ITEMS`, and the `attrviz_domain` get/set pair were each built from `DOMAINS`. Assigning `op.domain = "Instance"` raised *after* `layout.operator()` had already created the button, so the menu drew "Intrinsic → Index" and then silently truncated — looking exactly like "no attributes found". All now use `UI_DOMAINS`. **Tests must cover the operator enum, not just `attributes_by_domain`**: every 007 data-layer test passed while the menu was broken, because they call `add_visualizer()` and bypass the operator entirely.
2. **The engine cache key must encode graph SHAPE, not just version.** A `.blend` saved mid-development carried a correctly-stamped `AttrViz Engine 0.5.11` built by older code with four domains; it passed the stamp check and was reused. `engine_signature()` now folds in the axis lengths, so a shape change invalidates without relying on someone remembering to bump.
3. **Instance `position` reads uninitialised memory** — see P0.

### P1b — Surface, centroids, depth ✅

- [x] **Surface on Instance paints the instanced geometry.** First wired to empty geometry on the reasoning "instances have no faces" — true at the top level, wrong for the user's need. It now transforms each instance's referenced prototype into the overlay's own numpy buffers and paints it with that instance's value: 33 instances × 12 tris → 396 tris, 33 distinct values. Same picture Realize gives, at the right granularity, mutating nothing. The existing Surface mute already handles the source (`TEXTURED` → `BOUNDS` → restore).
- [x] **Sample point is the CENTROID, not the pivot.** The pivot is an authoring artifact — `base_shift` puts it on the building's base, so every marker sat at z=0 *inside* the geometry it described. Now the prototype's bounding-box centre, transformed: z spans 4.09–34.36 instead of 0. Bbox centre rather than vertex mean, which would drift toward subdivided regions.
- [x] **Instance geometric ink draws with the depth test OFF.** A centroid is inside its geometry by construction, so depth-testing always hides it. Mesh domains keep the depth test — their ink sits *on* the surface and occlusion is meaningful. Split into `_split_geometric_depth()` so the rule is testable without a GPU context.

### P2 — UI honesty ✅ (partial)

- [x] Menu explains why mesh domains are absent on un-realized instances: *"Point / Edge / Face / Corner: no elements — geometry is instanced, add Realize Instances to unpack, or read it on Instance."* Guarded by tests on the triggering condition, and asserted **not** to fire for ordinary meshes.
- [ ] Surface on Instance-only → now builds real geometry, so the empty-label case no longer applies. Revisit if a prototype has no faces.
- [ ] Nested instances: detectable (below) but not yet reported.
- [ ] **Unified-value readout.** Still wanted — see "What survives" below.

### P3 — Closeout

- [x] All five suites green (`headless_test` 34, `test_gpu_sample` 225, `test_watch_collection` 45, `test_overlay_kinds`, `test_surface_direct` 11).
- [x] GUI confirmed on `mock_city.blend` with Realize removed: Instance menu lists `Index, Position, depth, height, id, width`; Surface paints the buildings; markers sit at centroids over the geometry.
- [ ] Example scene (`examples/build_attr_instances_scene.py`) — `mock_city` serves as the fixture for now (below).

---

## Packed vs realized — the semantics, measured

The two states hold attributes in genuinely different places:

```
PACKED   <GeometrySet: 0 verts, 33 instances>
  instance-domain : id, height, width, depth      ← readable now, correct granularity
  prototype POINT : wear, facade_z                ← inside the reference, not on this object
  top-level mesh  : 0 verts

REALIZED <GeometrySet: 1848 verts, 1782 faces>
  POINT: depth, facade_z, height, id, sharp_face, wear, width
    height    n=1848  distinct=33    constant-within-building=True
    wear      n=1848  distinct=11    constant-within-building=False
    facade_z  n=1848  distinct=4     constant-within-building=False
```

Realize does two different things at once and the result cannot tell them apart: it **promotes and duplicates** instance attributes (`height` → 33 real values smeared over 1,848 points) and **copies** prototype attributes per instance (`wear`, genuinely per-vertex). Afterwards both sit on `Point` as identical-looking floats.

Consequences: Surface-on-Point of a promoted attribute looks *correct* (colouring faces by a smeared value is the picture you want), but Markers draws 56 coincident markers per building and Tags labels each one 56 times.

**Realize destroys scope, and Blender gives it nowhere to go.** An attribute is `(name, domain, data_type)` and nothing else — `data_type`, `domain`, `is_internal`, `is_required` are all read-only, and attributes **reject** custom ID properties (`TypeError: id properties not supported for this type`). `name` is the only writable field, so the only native tagging mechanism is a naming convention, which is what Blender itself uses for internals (`.corner_vert`). Contrast Houdini, where scope is structural (point / vertex / prim / detail are separate containers) and therefore cannot be lost.

---

## Rejected: recovering scope after Realize

Three routes were explored and all are rejected. **Do not re-propose without reading this.**

**Value inference (per-shell constancy).** If every element of a shell carries one value, the attribute was instance-scope. Measured and it works — at detail=32 / 190,344 verts: `height` per-shell **True** in 0.60 ms, `wear` **False**, `facade_z` **False**. But a cardinality shortcut gets it backwards: `facade_z` has 32 distinct in 190k (ratio 0.0002) versus `height`'s 33 (0.0002) — *lower*, despite being genuinely per-vertex. Only a true per-shell test separates them, and that needs shell identity, which is not free: after Realize the promoted `id` is **unique per point** (190,340 distinct), so there is no grouping attribute. It requires a topology/island pass.

**Static graph analysis.** More deterministic, and the branch split is clean — traced on `city_seed_scatter`:

```
iop.Points   -> depth, width, height     (become instance-scope)
iop.Instance -> facade_z, wear           (stay element-scope)
```

Note **all five are upstream of Realize and all five are `domain=POINT`**, so "upstream of Realize" is *not* the rule — the rule is which input of Instance on Points the path traverses. It degrades on nested node groups, Join Geometry giving two paths, Switch nodes, muted nodes, and attributes that were never stored by a node at all. Its saving grace is that it can answer *unknown*; value inference always answers confidently.

**Sidecar metadata cache** (`obj["attrviz_scope"]`). Rejected hardest, because it is state with a lifecycle we cannot win:

| Question | Answer |
|---|---|
| Persists across save? | Yes — ID props save with the .blend, so stale claims outlive the graph and travel on append |
| Realize added/removed? | Scope depends on graph *topology*; our epochs report only "geometry changed", which fires every scrub tick |
| Attribute deleted? | Stale entry pointing at nothing |
| Creating node deleted? | Attribute may still exist, now carrying provenance that is no longer true |
| Attribute renamed? | `name` is the only writable field — the cache key is a mutable string; a rename orphans the entry or hands its claim to a different attribute |

Keyed on a mutable string, invalidated at the wrong granularity, persisted beyond the facts that produced it, and its failure mode is a *confident wrong answer*.

### The principle

**Do not reconstruct information the data model destroyed — read it where it still exists.**

Every route above starts *after* Realize and is therefore archaeology. The two things that work do not: **Instance domain** reads scope while it is structural and true, and **P4 unpack** gets element data without destroying scope. Neither needs detection, state, or a lifecycle.

### Stay Blender-native — the API moves under you

The deeper reason the rejected routes are rejected: every one of them is **derived state that has to be maintained against a moving API**. Blender's surface changed six times in ways that broke working code *during this one task*:

| Surprise | Cost |
|---|---|
| `FunctionNodeCompare` `A_STR` → `A` (5.0.x → 5.2) | Engine build died mid-tree; masked as `KeyError: 'Style'` |
| `FunctionNodeRandomValue` outputs collapsed to one dynamic socket | Benchmark harness crashed |
| `GeometrySet.instances_pointcloud()` is a **method**, not a property | `getattr(gs, "instances", None)` silently returns None — the naive fix no-ops |
| Instance `position` reads **uninitialised memory** after the first call | Would have shipped markers at garbage coordinates |
| Modifier inputs moved to `properties.inputs` (an `IDPropertyGroup`) | Three RNA driver paths failed; old ID-prop access gone |
| Referenced `Mesh` freed with its `GeometrySet` | `StructRNA of type Mesh has been removed`, three separate times |

Anything that caches, tags, or re-categorises on top of that surface inherits all of it, plus its own invalidation lifecycle. The native reads — `attributes`, `domain`, the evaluated GeometrySet — are the parts most likely to survive, because they are what Blender itself is built on.

**Rule for this POR and its successors:** prefer reading what Blender already models over anything AttrViz has to derive and keep in step. When a native read is unavailable, say so in the UI rather than reconstructing it. Every fallback we add is a thing that breaks quietly on the next release.

### What survives

One stateless idea, which passes every lifecycle question because it has no state: a **display-time cardinality readout** — *"`height`: 33 distinct across 190,344 points"* — computed fresh in ~0.6 ms and discarded after drawing. It describes what is in front of you without claiming provenance. If someone realized their scatter and their markers look wrong, this says why. Same mechanism covers the global-constant case (`np.ptp == 0` → report the single value instead of N identical markers).

---

### P4 — Unpack mode (proposed, not built)

**Why.** Telling the user to add a Realize node asks them to mutate a production graph for a debug view — the exact thing "zero mutation, watched objects never touched" exists to prevent. It also changes what renders, and a scatter that legitimately ships un-realized (the normal case, since instancing is why it is cheap) cannot be inspected at element level at all without changing the scene.

**What it is NOT:** no nodes are added to the graph. AttrViz reconstructs the realized geometry in its **own numpy buffers** at draw time — the same mechanism Surface-on-Instance already ships. This is distinct from the parked graph-instrumentation idea, which *would* modify the tree.

**Honest scope of the win.** Narrower than first argued. With Realize on you *can* already see both kinds of attribute simultaneously — they all land on Point. What Realize-on costs is granularity (56 coincident markers per building) and the graph mutation itself. Unpack wins for scatters that ship un-realized; if the working style keeps Realize on, it buys comparatively little.

- [ ] Per-visualizer, **auto-on when a mesh domain is picked on an instanced object** — no mode to discover, no re-opening the menu. Panel toggle exists to turn it off and to show cost.
- [ ] Realize parity: promote instance attributes onto unpacked elements **and** carry the prototype's own per-vertex attributes. Realize does both; users will expect it.
- [ ] `Index` global over unpacked elements, matching Realize, not repeating per prototype.
- [ ] Normals via inverse-transpose so non-uniform instance scale does not skew them.
- [ ] Group by `.reference_index` (the Surface path already does this).
- [ ] **Nested instances are detectable** — a reference that is itself instanced reports its own instance count and has **no mesh** (`ref_has_instances=[4], ref_mesh=[False]` versus `[0]/[True]` when flat). v1 may be depth-1 with an honest label; recursion with composed transforms makes it fully correct. Never silently truncate.
- [ ] Surface unpacked element count in the panel — cost visibility (786k at detail 64 on the fixture).
- [ ] Label unpacked domains as unpacked, so it is never ambiguous whether geometry exists in the stream or was reconstructed.

---

## Fixture: `mock_city.blend`

Extended for this work (backup at `mock_city_backup_pre_detail.blend`; that repo has no commits):

- **`Building Detail`** (int 2–64) drives the prototype cube's `Vertices X/Y/Z`
- **`Wear Scale`** drives a noise frequency
- **`wear`** — Noise Texture at local position, genuinely irregular per vertex
- **`facade_z`** — local Z, a clean 0→1 gradient up each building, easy to eyeball

| Detail | proto verts | unpacked total |
|---:|---:|---:|
| 4 | 56 | 1,848 |
| 16 | 1,352 | 44,616 |
| 32 | 5,768 | 190,344 |
| 64 | 23,816 | **785,928** |

One knob spans 1.8k → 786k verts on a real scene, which also serves 008's stress-scene need. **Prototype attributes are identical on every instance by construction** — city-wide per-vertex variation cannot exist before instancing, since the prototype is evaluated once and knows nothing about where its copies land. That is not a fixture limitation; it is why unpack matters.

⚠️ `tools/build_seed_scatter.py` in the city repo builds the seeding half only and **deletes the object and node group** before rebuilding. Running it destroys all of this. See that repo's backlog items **SD** and **GD**.

---

## Parked — graph instrumentation (adjacent, POR-sized if it graduates)

Recorded so the research is not repeated. **Build nothing here until the instance-domain
work above is landed and tested.**

**The insight.** Mid-graph values are not missing from Blender — they are *unaddressed*.
Wire any field into a `Store Named Attribute` and it appears in `evaluated_attributes()`,
lists in the RMB menu, and visualizes like anything else. **AttrViz already supports this
today with zero changes.** The gap is that someone must declare the tap. Houdini makes
every SOP output implicitly addressable; Blender makes you name what you want inspectable.
Automate the tap and the two converge.

**It closes the "detail" question natively.** A tapped *field* becomes a per-element
attribute — ordinary visualization. A tapped *constant* is stamped to every element, and
the unified-value readout collapses it back to one number. So instrumentation + `ptp == 0`
gives detail-style inspection without ever leaving the attribute system, and without the
product drift that reading datablock ID properties would mean.

**Three separable pieces, only two of which are ours:**

1. **Nothing** — manual taps work today.
2. **Tap helper** — insert/remove `Store Named Attribute` on a chosen socket + domain,
   marked (`attrviz_tap_*`) and reversible.
3. **Viewer-node passthrough** — Blender's Viewer node is already an instrumentation tap.
   If its geometry is reachable from Python, this is strictly better than (2): no graph
   mutation, no cleanup, no ownership. **Probe this before designing (2).**

**Four real constraints on (2):**

- **A tap mutates the user's node graph.** Different from touching watched geometry, but
  still user data. Must be explicit, owned, and cleanly removable or it leaves debris in
  someone's asset.
- **Domain choice is not inferable.** A field is domain-agnostic until it lands; `Store
  Named Attribute` forces a pick, and POINT vs FACE differ by implicit interpolation. A
  tap is a *measurement decision*, and a wrong domain shows something plausible and wrong.
- **A field needs geometry present to be stored.** `Store Named Attribute` takes a
  Geometry input, so a pure-math branch upstream of any geometry cannot be tapped where it
  is computed. Not every point in the graph is tappable.
- **Taps cost evaluation** — an attribute write across every element. Opt-in per socket;
  never a "tap everything" default.

### Parked — datablock "detail" (deliberately not now)

ID properties on Object / Mesh / Collection / Scene all work — floats, strings, vectors,
keyframeable, with `id_properties_ui` metadata. AttrViz *could* read them tomorrow because
its read path is Python. Deferred on **product identity**, not capability: they are not
attributes, and the tagline is "see any attribute, natively."

Findings worth keeping:

- **No GN node reads or writes ID properties** — all 330 `GeometryNode*` / `FunctionNode*`
  types checked. `ObjectInfo` gives transform and geometry only.
- **A non-geometry GN group output has exactly one destination**, `attribute_name`. A value
  leaving a graph can only land as an attribute on geometry — never on a datablock.
- **Unresolved:** the ID-prop → driver → GN-input bridge. Three RNA paths failed on 5.2
  (`md.properties.inputs[…]` is an `IDPropertyGroup`, not animatable the way pre-5.x
  modifier ID-props were). The UI offers "Add Driver" on GN inputs, so it is probably
  reachable. **This decides whether datablock detail could ever be a real control rather
  than decoration** — worth resolving before the detail question is reopened.

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
