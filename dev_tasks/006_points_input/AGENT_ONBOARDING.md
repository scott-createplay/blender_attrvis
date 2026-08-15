# Agent onboarding — Point-only geometries (task 006)

**Status: In progress** (`006-points-input`). Source of truth: [`POR.md`](POR.md).  
**P0–P4 landed** (GUI confirmed). Curves (P2 leftover) only if asked.  
**Parent:** overlay kinds [`../002_overlay_kinds/POR.md`](../002_overlay_kinds/POR.md).

## Start here

1. P4 code is done. **GUI confirm:** rsync (already run this session), restart Blender, open `examples/attrviz_pointclouds.blend`.
2. Tick the remaining P4 GUI checkbox in [`POR.md`](POR.md) after visual confirm.
3. Commit only if asked. Do not reopen P0–P3. Do not start 004.

---

## Prompt (copy from here)

```text
You are implementing P4 of AttrViz point-only input (dev_tasks/006)
on branch 006-points-input. Blender 5.0.1+; AttrViz 0.6.x.
Read dev_tasks/006_points_input/POR.md — section P4 — first.
Do not redo P0–P3. Do not start 004. Do not commit unless asked.

## Why

Watch + sample + Markers on POINTCLOUD already work. Native point
clouds still draw as spheres at the sample centers. Overlay Markers
are POST_VIEW GPU POINTS at those same centers, LESS_EQUAL, depth-mask
off. The sphere front is closer → markers sit behind the points.

Mesh Surface already solved this: mute the original draw
(display_type = BOUNDS). Overlay IS the thing you look at. Overlay ink
is not in the select ray, so a click hits the still-pickable BOUNDS
source — attributes stay on the real object.

Point-cloud Markers are the Surface analog. Mute the spheres the same
way. Do not skip depth test. Do not hide_select the source.

## Locked

1. Mute only POINTCLOUD in the watch set, while any enabled geometric
   viz (Markers / Arrows / Tags, hide_viewport=False) is on.
2. Reuse _mute_target_solid / _restore_target_solid / _MUTE_PROP.
   BOUNDS default. Do not fork a second mute system.
3. Do NOT mute MESH for Markers. Do NOT mute clouds if the only
   enabled viz is Surface.
4. Mixed attrvis: Surface mutes meshes; geometric mutes clouds;
   both on → both muted. Independent.
5. Do NOT hide_viewport or hide_select the source cloud.
6. Do NOT implement 004 hide_select on the viz carrier.
7. Do NOT skip overlay depth test or bias sample positions.
8. Do NOT: 003/005, volumes, curves, commit unless asked.

## What exists (read these)

- attrviz/gpu_overlay.py
    _active_surface_watch_meshes — MESH only, any Surface viz
    _mute_target_solid / _restore_target_solid / _MUTE_PROP
    _sync_surface_target_mute — called from suppress_gn_carriers,
      _sync_watch_draw, load_post
    geometric draw: POST_VIEW, LESS_EQUAL, depth-mask False
- attrviz/gpu_sample.py — WATCH_TYPES, watch_meshes_for_visualizer
- tests/test_gpu_sample.py — 006 section; Surface mute → BOUNDS on mesh
- tests/test_watch_collection.py — watch mute restore
- examples/build_attr_pointcloud_scene.py — GUI fixture

## Implement

Sibling or generalization: _active_geometric_watch_clouds → union into
the same desired mute set as Surface (or two desired sets, one restore
loop). POINTCLOUD + geometric; MESH + Surface stays as today.

## Validate always

blender --background --factory-startup --python-exit-code 1 \
  --python tests/headless_test.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_gpu_sample.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_watch_collection.py

New checks: cloud + Markers → BOUNDS + prop; disable viz → restore;
mesh + Markers → mesh not muted; only Surface → cloud not muted;
both vizs on → mesh and cloud muted.

GUI (repo ≠ extension — rsync then restart Blender):

rsync -a --delete attrviz/ \
  ~/Library/Application\ Support/Blender/5.0/extensions/user_default/attrviz/

Open examples/attrviz_pointclouds.blend. Markers in front. Click a
cloud → that POINTCLOUD is active. Outliner still picks viz objects.
Viz eye off → native points return.

## After finish

Tick P4 in POR.md. Do not reopen 001–005 except a pointer. Commit
only if asked.
```
