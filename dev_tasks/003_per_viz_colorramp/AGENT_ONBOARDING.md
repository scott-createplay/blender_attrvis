# Agent onboarding — Per-Visualizer Color Ramp (task 003)

**Status: Open.** P0–P3 done. Next: **P4** (tests green + GUI: 3 Surface vizs, distinct ramps/presets, toggle + drag).  
**Source of truth:** [`POR.md`](POR.md)  
**History (frozen):** [`../002_overlay_kinds/POR.md`](../002_overlay_kinds/POR.md)

## Start here

1. Read [`POR.md`](POR.md) (Why, Locked product, P0–P4, Acceptance).
2. Paste the prompt below into a **new** agent chat (or `@` this file).
3. Agent executes **P0 first**.

---

## Prompt (copy from here)

```text
You are implementing per-visualizer color ramps for AttrViz in blender_attrvis
(dev_tasks/003). Blender 5.0.1+; AttrViz 0.6.x. Read
dev_tasks/003_per_viz_colorramp/POR.md first. Then execute P0. Do not start P2+
until P0 is green unless the user says otherwise.

## Why

The GPU overlay (task 002) is THE path for all visualization types. Scalar
Surface/Markers color is a per-viz ColorRamp — always editable. Heat, RGB,
and Monochrome (BnW) are presets that fill that ramp. They are not Displays
and not mapping algorithms. The old Style enum (Heat/RGB/Random as three
algorithms) is leftover and must not drive the Color row.

They need per-visualizer color ramps so each attribute has its own palette
(e.g. blue-red diverging for temperature, green-yellow sequential for
pressure). Editing one ramp must not affect others.

Dragging a ColorRamp stop must stay interactive. Present-miss recolor +
_build_batch is ~33 ms on 33k tris — too slow for mouse-move. The Heat path
is a shader LUT (256-texel texture + vmin/vmax uniforms), not a mesh rebuild.

## Locked

1. Each visualizer gets its own ramp state OFF the engine GN tree
   (ensure_viz_ramp(obj) → node tree with ShaderNodeValToRGB, pointer on
   the viz object). GPU-on keeps the shared ensure_viz_group() datablock.
   Do NOT per-viz .copy() the engine. Editing one ramp does not touch others
   and must not dirty the engine tree.
2. Viewport Heat: custom shader. Positions + scalars uploaded on sample miss
   only. Ramp/range change uploads a 256-entry LUT + uniforms — no
   overlay.build_batch / overlay.present spike. Do NOT put ramp hash in
   _present_key in a way that rebuilds the mesh batch.
3. CPU fallback: gpu_color.ramp_colors(values, stops, vmin, vmax) and
   extract_ramp for unit tests and --background. values_to_colors gains
   optional ramp=; when style="Heat" and ramp is provided, use ramp_colors.
4. Panel UI: template_color_ramp always shown for Surface/Markers (GPU on),
   off-engine ValToRGB. Always editable.
5. Presets: Heat, RGB, Monochrome (BnW) write stops into that ramp. They
   do not lock it. They are not Displays and not mapping algorithms.
   The old Style enum (Heat/RGB/Random as three algorithms) is leftover;
   P3 replaces that Color-row behavior with ramp + preset buttons.
6. Do not keep RGB/Random as modes that hide the ramp.
7. Tags and Arrows uniform tint are NOT affected.
8. Do NOT: attribute discovery, strangler, watch-collection UX, Tags atlas,
   kind dispatch changes, view cull changes, engine .copy() on GPU-on.
9. Commit only if asked.

## What exists (read these)

- attrviz/gpu_color.py
    heat_colors: hardcoded 5-stop ramp (blue→red)
    values_to_colors(values, dtype, style, vmin, vmax, seed): style dispatch
    ADD (P1): ramp_colors(), extract_ramp()
- attrviz/gpu_overlay.py
    _refresh_surface_from_sample / _refresh_markers call values_to_colors
    then _build_batch. Heat must become LUT shader (P1).
- attrviz/__init__.py
    _assign_viz_engine: GPU-on → shared engine; GPU-off → .copy()
    Panel: template_color_ramp guarded by (not _gpu_overlay_on())
    KEEP shared engine. P0: ensure_viz_ramp on add/migrate. P2: widget.
- attrviz/node_builder.py
    ensure_viz_group() builds GN tree with ShaderNodeValToRGB
    ADD: ensure_viz_ramp(obj), ramp_node_for_viz(obj)
- tests/test_gpu_sample.py — keep green; P0: shared engine + distinct ramps
- tests/headless_test.py — keep green (GPU-off; V11 still engine copies)

## Phases (tick in POR.md)

P0 per-viz ramp tree (off-engine) → P1 Heat shader LUT + CPU fallback
→ P2 panel UI enables ramp editing → P3 preset ramps → P4 closeout.

## Validate always

blender --background --factory-startup --python-exit-code 1 \
  --python tests/headless_test.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_gpu_sample.py

Plus unit tests for ramp_colors (2-stop, 5-stop, edge values) at P1.

GUI P2+:
  rsync -a --delete attrviz/ \
    ~/Library/Application\ Support/Blender/5.0/extensions/user_default/attrviz/
  3 Surface vizs on different attrs, each with a distinct ramp → toggle shows
  instant palette shift. Dragging a stop is interactive. Editing one ramp
  does not affect others.

## After finish

Update 003 POR checkboxes/status. Do not reopen 001/002.
```
