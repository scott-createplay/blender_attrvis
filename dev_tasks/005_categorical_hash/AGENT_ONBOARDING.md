# Agent onboarding — Categorical hash color (task 005)

**Status: Open.** P0–P1 done (tests green). Next: **P2** GUI (Face-id Surface quilt; Seed; float attr brings the ramp back).  
**Source of truth:** [`POR.md`](POR.md)  
**Parent:** [`../003_per_viz_colorramp/POR.md`](../003_per_viz_colorramp/POR.md)

## Start here

1. Read [`POR.md`](POR.md).
2. Paste the prompt below into a **new** agent chat (or `@` this file).
3. Agent executes **P0**, then **P1**. GUI is P2.

---

## Prompt (copy from here)

```text
You are implementing categorical hash color for AttrViz in blender_attrvis
(dev_tasks/005). Blender 5.0.1+; AttrViz 0.6.x. Read
dev_tasks/005_categorical_hash/POR.md first. Then execute P0 then P1.

## Why

003 ColorRamp is the scalar colormap. ID-like attrs (INT / BOOLEAN / INT8)
must not interpolate along it — nearby ids are not nearby temperatures.
P3 currently sends them through the Heat LUT. Leftover Style Random
(hash_colors) already did the right thing; the overlay stopped using it.

## Locked

1. Mapper, not a Display. color_mapper(dtype) → "hash" | "ramp".
   Hash: INT, BOOLEAN, INT8. Ramp: floats / vector length.
   Do NOT add a Display or a Random ramp preset.
2. Hash is automatic (stable per value, Seed reshuffles). No manual
   id→color UI. Semantic legend (ramp override) is later — keep
   ensure_viz_ramp; do not make INT unable to read a ramp.
3. Overlay: hash uses hash_colors + color batch. Skip heat_lut /
   ramp_colors for those dtypes. Float Surface stays 003 LUT.
4. Panel GPU-on categorical: Seed + "Hash color per id". Hide ramp
   presets / ColorRamp / Auto Range. Float row unchanged.
5. Do NOT: 004 pick identity, STRING color, stepped ramp, GPU-off
   Style rewrite, commit unless asked.

## What exists

- attrviz/gpu_color.py — hash_colors; values_to_colors hashes INT
- attrviz/gpu_overlay.py — _dtype_heat_lut allows INT (wrong)
- attrviz/__init__.py — GPU-on Color row is always ramp presets
- tests/test_gpu_sample.py, tests/headless_test.py (V12 keep green)

## Phases

P0 overlay hash → P1 panel Seed → P2 GUI / closeout.

## Validate

blender --background --factory-startup --python-exit-code 1 \
  --python tests/headless_test.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_gpu_sample.py

GUI: Face-id Surface is a quilt, not a heat gradient. Seed. Float
attr brings the ramp back. rsync attrviz/ to Blender 5.0 extensions.
```
