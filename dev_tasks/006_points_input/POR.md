# POR: Point-only geometries (point clouds)

**Parent / history:** GPU overlay is THE path ([`../002_overlay_kinds/POR.md`](../002_overlay_kinds/POR.md)). ColorRamp 003 / hash 005 apply to Markers already — they never see point clouds because the watch/sampler is mesh-only.  
**Pickup:** [`AGENT_ONBOARDING.md`](AGENT_ONBOARDING.md)  
**Status:** In progress (`006-points-input`). Northstar: adding AttrViz to a mesh or a point cloud should feel the same.  
**Next pickup: P2 leftover (curves) only if wanted.** P0–P4 landed; GUI confirmed.

AttrViz **0.6.x**. Blender **5.0.1+**.

---

## Why this POR exists

Some inputs are **points only**: a Point Cloud object, a mesh with verts and no faces, GN output that is a point cloud. AttrViz’s tools (watch set, RMB Visualize, Markers, Arrows, Tags, ColorRamp, id hash) must work on those the same way they work on a building mesh.

Today they do not. The GPU overlay samples `Mesh.vertices`. The watch set (`attrvis`, Add objects) skips anything that is not `obj.type == 'MESH'`. Surface packing needs `loop_triangles`. A selected point cloud can open Visualize Attribute (attribute discovery already walks `evaluated_geometry().pointcloud`) and still link **nothing** into `attrvis`.

The GN engine (GPU-off) already joins Point Cloud + Curve-to-Points into the Point domain (`node_builder.py`: “Point domain also merges curves + point clouds”). The overlay never took that path.

Blender treats mesh verts and Point Cloud points as **separate types**. AttrViz must not: same watch set, same Visualize, same Markers/Arrows/Tags, same ramp/hash. Internally we branch on evaluated source; the user should not feel that branch.

### What “points only” means

| Input | Blender | Faces | Overlay today |
|-------|---------|-------|----------------|
| Mesh, verts only | `MESH` | no | Watch yes. Point sample yes. Surface empty. Markers should work. |
| Point Cloud | `POINTCLOUD` | no | Watch **yes**. Sample **yes**. Markers draw. Native point spheres still draw → overlay loses depth test (P4). |
| Curves / hair | `CURVES` / `CURVE` | no | Watch no. GN converts on GPU-off Point domain. Overlay does not. |

P0 is POINTCLOUD + vert-only MESH. Curves are P2 so we do not paint “points = mesh verts” into the sampler. Volumes are the same *product* story (expand inputs) and a different *data* story — out of 006.

---

## Locked product

A visualizer watches **the same attrvis set**, which may include meshes **and** point clouds. Display still picks the carrier:

| Display | Point-only input |
|---------|------------------|
| **Markers** | Default. ColorRamp (003) or hash (005) on the points. Density / view cull unchanged (geometric kind). |
| **Arrows** | Vector attrs on points (same honesty: non-vector → empty). |
| **Tags** | Text at point positions. |
| **Surface** | Requires faces. On point-only: do not invent a mesh. Empty / disabled with a one-line reason. |

Do **not** mesh the cloud as the GPU path (no Mesh from Points just to draw Surface). Markers *are* the surface analog for points.

`auto_pick(Point, …, has_faces=False)` already returns Markers. Keep that.

Color tools do not change: scalars → ramp LUT; INT/BOOLEAN/INT8 → hash + Seed. They already run on Markers. This POR feeds them positions.

004 (`hide_select` on viz carriers) stays a separate task. Source pick for muted clouds is **this** POR (P4): BOUNDS source + overlay not in the select ray — the mesh Surface mechanism, not 004. Do not start 004 unless asked.

GPU overlay stays THE path. GPU-off GN Point-domain join is not the acceptance path; do not regress it.

### Implementation locks (from plan)

1. **One watchable set.** `WATCH_TYPES = {MESH, POINTCLOUD}`. Skip viz carriers. Mixed `attrvis` concatenates Point-domain samples the same way multi-mesh already does.
2. **Sampler branches on evaluated source, not Display.** Vert-only meshes keep `vertices`. Native clouds use Point Cloud `points` / `attributes`. Edge / Face / Corner on a cloud return empty — do not fake them.
3. **GeometrySet fallback (P0).** If `_evaluated_mesh` fails but `evaluated_geometry().pointcloud` exists, sample that (native `POINTCLOUD`, or a mesh whose GN output is only a point cloud — the case where RMB already lists attrs). Do **not** concat mesh verts + cloud points from the *same* object (double-count). Concat is across objects in `attrvis`.
4. **Point-cloud mute is the Surface analog (P4).** Native point spheres *are* the competing solid. Mute `POINTCLOUD` to `BOUNDS` while an enabled **geometric** viz (Markers / Arrows / Tags) is drawing them. Do **not** mute meshes for Markers. Do **not** `hide_viewport` / `hide_select` the source — BOUNDS stays pickable so a viewport click selects the real cloud (attributes stay in context). Overlay ink is not in the select ray (same as mesh Surface today). 004 (`hide_select` on the viz *carrier*) stays parked.
5. **Normal intrinsic on clouds is empty.** Do not invent vertex normals.
6. **Do not** rename every `*_meshes*` symbol in P0. Do not sample via GPU-off GN Join.

---

## Progressive plan

### P0 — Watch + sample point clouds

- [x] Fixture probe: how Blender 5.0.1 allocates Point Cloud points from Python (`convert`, GN Points + copy evaluated, …). Lock as `make_pointcloud(name, n)` in tests.
- [x] Shared `WATCH_TYPES`; `_watch_candidates` / `iter_watch_meshes` accept `MESH` **and** `POINTCLOUD` (skip viz carriers). Mute stays MESH-only.
- [x] `_evaluated_source(obj) → (ev, mesh, cloud)`. Mesh with verts → existing path. Else `gs.pointcloud` / `ev.data` with `.points`.
- [x] Point-cloud Point domain: positions (`points.co` or `position` attr) + `_read_attr`. Index = `arange`; Position = pos buffer; Normal = empty. Non-Point → `None`.
- [x] `sample_evaluated` / `sample_visualizer_targets` return the same `(pos, values, dtype)` shape as mesh Point.
- [x] `watch_fingerprint`: point count for clouds (not `len(vertices)` → 0).
- [x] `_domain_has_elements`: Point true if cloud has points; Edge/Face/Corner false (RMB already hides empty domain menus).
- [x] Tests: a POINTCLOUD with a float attr samples n points; linking it into `attrvis` is a watch candidate.

### P1 — Overlay Markers / Arrows / Tags

- [x] Markers on a watched point cloud: ramp LUT (float) and hash (int) — same present path as mesh Markers (`_refresh_viz`).
- [x] Arrows on a vector point attr; non-vector → empty.
- [x] Tags at point positions (watch + sample; `_author_attr_sig` uses `.attributes`).
- [x] Surface on a point-only watch set: empty, no crash, no fake tris (`build_surface_tris` already skips `n_tris == 0`).
- [x] Mixed watch: one viz, mesh + cloud, concat n.

### P2 — UI honesty + curves (optional)

- [x] RMB / Add objects work with POINTCLOUD selected (falls out of `_watch_candidates`).
- [x] Panel: Surface on point-only → label, not a silent blank (same pattern as “Surface on Edge”).
- [ ] Curves → points (evaluate `CURVES` / `CURVE` like GN Curve-to-Points). Only if the user wants it. Not P4.

### P3 — Closeout (partial)

- [x] Headless tests green (`headless_test.py`, `test_gpu_sample.py`, `test_watch_collection.py`).
- [x] GUI: rsync + reopen `examples/attrviz_pointclouds.blend` — Markers draw on clouds (after extension sync). Depth fight remains (P4).
- [x] Commit only if asked.

### P4 — Point-cloud mute (Surface analog)

- [x] Mute `POINTCLOUD` in the watch set while any enabled geometric viz is on (`BOUNDS`, same `_MUTE_PROP` / restore as Surface).
- [x] Do not mute MESH for Markers. Do not mute clouds when only Surface is on.
- [x] Mixed: Surface mutes meshes; geometric mutes clouds; both on → both muted.
- [x] Source stays pickable (no `hide_select` / `hide_viewport` on the cloud). Do not implement 004 carrier `hide_select`.
- [x] Tests: mute/restore + mixed independence. Regression suites green.
- [x] GUI: rsync, restart, `attrviz_pointclouds.blend` — markers in front; click selects the cloud.

Native point clouds draw as spheres (`radius`) at the sample centers. Overlay Markers are screen-space `POINTS` at those same centers, `POST_VIEW`, `LESS_EQUAL`, depth-mask off. The sphere front is closer → markers sit **behind** the points.

Mesh Surface already solved this class of problem: hide the original draw (`display_type = BOUNDS`), overlay *is* the thing you look at, click hits the still-pickable source.

**Locked for P4**

| | Mesh + Surface (now) | Point cloud + Markers/Arrows/Tags |
|---|---|---|
| Competing draw | Workbench solid | Native point spheres |
| Mute | `display_type = BOUNDS` (WIRE if Show Wireframe) | Same on `POINTCLOUD` |
| Overlay | Identity tris | Geometric at `points.co` |
| Click | Hits BOUNDS mesh | Hits BOUNDS cloud — attributes on that object |
| Do not | `hide_select` / `hide_viewport` the source | Same |
| Viz carrier | Registry in `Visualizers`; GN `show_viewport=False` | Unchanged. Do **not** implement 004 `hide_select` on the carrier. |

**When to mute**

- Mute **only** `POINTCLOUD` objects in the resolved watch set.
- Mute while **any enabled geometric viz** (Markers / Arrows / Tags, `hide_viewport=False`) exists — same “any Surface viz → mute all watch meshes” shape, but typed: geometric → clouds, Surface → meshes (existing).
- Do **not** mute MESH for Markers (buildings stay solid).
- Do **not** mute clouds if the only enabled viz is Surface (overlay empty on points; native draw is fine).
- Mixed `attrvis` (HeatCube + clouds): Surface viz mutes the cube; Markers viz mutes the clouds. Independent.

**Implementation (reuse, do not fork a second mute system)**

- `gpu_overlay.py`: generalize `_active_surface_watch_meshes` / `_sync_surface_target_mute` (or add a sibling `_active_geometric_watch_clouds` that feeds the **same** `_mute_target_solid` / `_restore_target_solid` / `_MUTE_PROP`).
- Stash/restore `display_type` exactly as Surface. `BOUNDS` default; WIRE only if we later want a cloud wire analog — not required for P4.
- Call the sync from the same places Surface mute already runs (`suppress_gn_carriers` / `_sync_watch_draw` / load_post). One extra “desired set” union is enough.
- Tests: POINTCLOUD in `attrvis` + enabled Markers viz → `display_type == "BOUNDS"` and `_MUTE_PROP` set; disable that viz → restore. Mesh + Markers only → mesh **not** muted. Mixed independence:
  - only Markers → clouds BOUNDS, mesh original
  - only Surface → mesh BOUNDS, clouds original
  - both on → mesh BOUNDS **and** clouds BOUNDS
- Do not skip depth test. Do not bias sample positions. Do not `hide_viewport` the cloud.

**Validate P4**

Headless: extend `tests/test_gpu_sample.py` and/or `tests/test_watch_collection.py` — cloud mute/restore, mesh Markers does not mute a mesh, mixed independence. Plus the three regression suites.

GUI (rsync first — repo ≠ extension):

```bash
rsync -a --delete attrviz/ \
  ~/Library/Application\ Support/Blender/5.0/extensions/user_default/attrviz/
```

Restart Blender. Open `examples/attrviz_pointclouds.blend` (rebuild with `examples/build_attr_pointcloud_scene.py` if missing). GPU Overlay on, Display=Markers: native spheres gone, colored markers in front. Click a cloud in the viewport → that `POINTCLOUD` is active (RMB Visualize Attribute lists its attrs). Outliner still selects viz objects. Toggle viz eye off → native points return.

---

## Out of scope

- Turning a point cloud into a Surface mesh.
- Volumes, Grease Pencil. Curves (P2 leftover — not this pickup).
- 004 `hide_select` on the **viz carrier**. Source pick for muted clouds is P4 (BOUNDS + overlay not in ray), same as mesh Surface today.
- Skipping overlay depth test / depth bias / moving sample positions to “fix” z-order.
- `hide_viewport` or `hide_select` on the source cloud.
- 003/005 colormap changes.
- Attribute discovery by name across the scene.
- Same-object concat of mesh verts + cloud points.
- Renaming `iter_watch_meshes` / `watch_meshes_for_visualizer`.

---

## Current code (read first)

| File | Relevant state |
|------|----------------|
| `attrviz/gpu_sample.py` | `WATCH_TYPES`; `_evaluated_source`; Point Cloud Point path; `watch_has_faces`. `iter_watch_meshes` name kept. |
| `attrviz/__init__.py` | `_watch_candidates` MESH+POINTCLOUD. `_domain_has_elements` Point on clouds. Panel Surface honesty label. Hide Normal intrinsic on clouds. |
| `attrviz/gpu_overlay.py` | **P4 done.** `_active_geometric_watch_clouds` unions into `_sync_surface_target_mute`. Same `_mute_target_solid` / `_MUTE_PROP` / BOUNDS. Geometric draw unchanged: `POST_VIEW`, `LESS_EQUAL`, depth-mask off. |
| `examples/build_attr_pointcloud_scene.py` | GN POINTCLOUD demo; writes `examples/attrviz_pointclouds.blend`. All clouds share `heat` / `cluster_id` / `flow` / `strand_id`. |
| `attrviz/node_builder.py` | GPU-off Point Cloud join. Unchanged. |
| `attrviz/tags_draw.py` | Watch + sample; no type filter. |
| Tests | `make_pointcloud` via `object.convert`; 006 section in `test_gpu_sample.py` + `test_watch_collection.py`. |

---

## Design constraints

| Constraint | Note |
|------------|------|
| Point Cloud API | Blender 5: `Object.type == 'POINTCLOUD'`, `data.points`, attributes on POINT domain. Evaluated geometry may wrap this in a GeometrySet. Python often cannot `points.add()` — fixture uses convert or GN spawn. |
| Domain | Point-only inputs have Point domain. Edge/Face/Corner menus should be empty or hidden, not fake. |
| Kind | Markers/Arrows/Tags = geometric (Density, view cull, cap). Surface stays surface-kind and stays empty without faces. |
| Perf | Same L0 sample cache as mesh Markers. Do not resample on ramp/Seed (003/005 rules). |
| Mute | Surface → MESH BOUNDS. P4: geometric viz → POINTCLOUD BOUNDS. Same stash/restore. Source stays pickable. |
| Mixed watch set | `attrvis` may hold buildings **and** a cloud. Mute types independently (Surface vs geometric). |

---

## Acceptance

1. A Point Cloud in `attrvis` draws Markers for a float attr (ColorRamp) and an int attr (hash / Seed).
2. Vert-only mesh behaves the same (Markers default; Surface empty).
3. Arrows work on a vector stored on points.
4. RMB Visualize / Edit → Add objects accept a selected POINTCLOUD.
5. Surface on point-only does not crash and does not invent triangles.
7. Enabled Markers on a POINTCLOUD: native draw muted (`BOUNDS`); overlay markers in front; viewport click selects the cloud, not the viz carrier.
8. Mesh Surface mute / 003 / 005 stay green. Mesh + Markers does not mute the mesh.

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

GPU-off GN Point-domain join must stay green (`headless_test.py`). Do not “fix” overlay by routing through that tree.

New headless fixture (`make_pointcloud` in `tests/test_gpu_sample.py` + watch checks in `tests/test_watch_collection.py`):

1. Named `heat` FLOAT, `id` INT, `flow` FLOAT_VECTOR on POINT.
2. `sample_evaluated(pc, "heat", "Point")` → `len(pos)==n`, dtype FLOAT, world-space applied.
3. Edge/Face/Corner sample → `None`.
4. `_watch_candidates` with cloud selected includes it.
5. Link into `attrvis`; `iter_watch_meshes` includes it.
6. `sample_visualizer_targets` + `_refresh_viz(..., "Markers")` → `n==n_points`.
7. INT Markers → hash path; Arrows on `flow` non-empty; Arrows on `heat` empty.
8. `build_surface_tris` on cloud-only watch → `None` / `n_tris==0`.
9. Mixed mesh + cloud → concat counts.
10. Vert-only mesh: Markers work; Surface empty.

**GUI (P4):** rsync `attrviz/` → Blender 5.0 extensions (repo ≠ install). Restart Blender. `examples/attrviz_pointclouds.blend`: Markers in front of (not inside) native points; viewport click selects the `POINTCLOUD`. Mesh Surface mute still works on HeatCube if Display=Surface.
