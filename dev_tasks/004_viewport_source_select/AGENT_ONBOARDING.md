# Agent onboarding — Viewport pick selects the source (task 004)

**Status: Parked.** Do not start unless the user asks. Source of truth: [`POR.md`](POR.md).  
**Parent:** watch collection [`../001_gpu_overlay/AGENT_ONBOARD_SCOPE_PANEL.md`](../001_gpu_overlay/AGENT_ONBOARD_SCOPE_PANEL.md).  
**Not this task:** ColorRamp (003), kind dispatch, attribute discovery.

## Start here

1. Read [`POR.md`](POR.md) (Why, Locked product, P0–P3, Acceptance).
2. Paste the prompt below into a **new** agent chat (or `@` this file).
3. Agent executes **P0 first**. Do not build a select-redirect callback in P0.

---

## Prompt (copy from here)

```text
You are implementing viewport selection identity for AttrViz in
blender_attrvis (dev_tasks/004). Blender 5.0.1+; AttrViz 0.6.x. Read
dev_tasks/004_viewport_source_select/POR.md first. Then execute P0.
Do not start P1+ until P0 is GUI-green unless the user says otherwise.

## Why

The drawing (GPU overlay / GN carrier) is the original mesh as far as
the user is concerned. Selecting it in the viewport should select the
source in attrvis and its attributes — not the viz carrier in
Visualizers.

Repro (sample_scene_3): create one Surface viz, RMB again → Visualize
Attribute gone; Edit Add/Remove grey. Two viewports are a red herring
(one view layer, one active). RMB does not select (left-click select).
Visualize Attribute polls off when active is a visualizer.
attributes_by_domain(active) then asks the empty viz mesh.

## Locked

1. Viewport: viz carriers are not pickable. Object.hide_select = True
   on create and migrate. Outliner still selects viz objects (registry).
   Do NOT dissolve viz objects.
2. After GUI add-viz: restore watched mesh(es) as selected; active is a
   source mesh, not the new viz. Headless add_visualizer with no mesh
   selected must not break.
3. Do NOT write a depsgraph select-redirect in P0. That is P1 fallback
   if hide_select is insufficient. It must not retarget when the mouse
   is over the Outliner, and it does not run on RMB (no new pick).
4. N-mesh: P0 is the one-mesh case. >1 watch meshes = select all, active
   = last non-viz that was active (else first). Do not invent attribute
   discovery or a union-of-names menu in P0.
5. Edit stays watch membership (Add/Remove objects). ColorRamp stays
   N-panel (003). Do not put ramps or attr lists on Edit.
6. Do NOT: strangler, kind dispatch, Surface mute rewrite, 003 ramp
   work, commit unless asked.

## What exists (read these)

- attrviz/__init__.py
    ATTRVIZ_MT_visualize.poll: not is_visualizer(active)
    attributes_by_domain(context.active_object)
    _watch_candidates skips viz carriers
    _ensure_display_only_flags: hide_render, not hide_select
    add_visualizer does not set view_layer.objects.active
- attrviz/gpu_overlay.py
    _mute_target_solid: source BOUNDS (overlay IS the mesh)
    _suppress_gn_carriers: GPU-on hides GN show_viewport
- tests/test_watch_collection.py — add hide_select + restore-active checks

## Phases (tick in POR.md)

P0 hide_select + restore source after GUI add
→ P1 menu hole / redirect only if P0 GUI still fails
→ P2 N-mesh restore → P3 closeout.

## Validate always

blender --background --factory-startup --python-exit-code 1 \
  --python tests/headless_test.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_gpu_sample.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_watch_collection.py

GUI:
  rsync -a --delete attrviz/ \
    ~/Library/Application\ Support/Blender/5.0/extensions/user_default/attrviz/
  Visualize one attr → left-click colored mesh → source active.
  RMB → Visualize Attribute still lists source attrs.
  Outliner click on viz still selects the viz.

## After finish

Update 004 POR checkboxes/status. Do not reopen 001/002/003 except a pointer.
```
