# Agent onboard — Tags Cap policy + draw perf

**Parent:** [`POR.md`](POR.md) Phase 7c  
**STOP — do not execute the prompt below.** Cap policy is superseded. Geometric view cull (frame-center) is [`../../002_overlay_kinds/POR.md`](../../002_overlay_kinds/POR.md). Do not re-land T1 spread. Atlas / BLF leftovers stay 001 backlog. Pickup: [`../../002_overlay_kinds/AGENT_ONBOARDING.md`](../../002_overlay_kinds/AGENT_ONBOARDING.md).

**Related:** Arrows instancing (reuse CreateInfo + `draw_instanced`); watch collection: [`AGENT_ONBOARD_SCOPE_PANEL.md`](AGENT_ONBOARD_SCOPE_PANEL.md)  

Paste the prompt below into a new agent chat (or `@` this file).

---

## Prompt (copy from here)

```text
You are implementing AttrViz Tags performance + Cap policy in blender_attrvis
(Phase 7c). Blender 5.0.1+; AttrViz 0.5.8+.

## Locked constraints

1. There is NO free “visible verts” list from Workbench/GPU backface cull.
   Facing today = CPU dot(normal, toward_camera). Do not invent ID-buffer
   depth readback unless T0–T4 still fail with evidence.
2. Nearest-to-camera Cap is a POOR default for inspection — replace default
   with screen-space binning (spread labels across the view).
3. Tag cards today expand N quads on CPU (same *shape* as old Arrows soup).
   Instanced unit quad is the Arrows-pattern fix for cards.
4. Text today = N × blf.draw — main draw cliff; glyph atlas is the real text win.
5. Tag Cap 0 = show nothing (already fixed: no `or 10000` / max(1,…)).
6. Density-on-Tags is OPTIONAL product sugar — not required for T0–T4.
7. Do NOT start Scope UX / attribute discovery / strangler / Surface inflate.
8. Commit only if the user asks. Rsync attrviz/ → Blender extensions for GUI verify.

## What exists today (read these)

Call chain (POST_PIXEL):
  tags_draw.draw_callback_px
    → _labels_for_md
         → _collect_tags (sample all Target∪Scope, facing, sort by distance, [:cap])
         → cache world (wco, text); project each frame
    → _draw_cards_batched  # Python loop → 4N verts → one TRI batch
    → blf.dimensions + blf.draw per label

Files:
- attrviz/tags_draw.py          # collect + cards + BLF (primary)
- attrviz/gpu_sample.py         # sample_evaluated / iter_watch_meshes
- attrviz/gpu_overlay.py        # Arrows CreateInfo + draw_instanced pattern to reuse
- attrviz/__init__.py           # Tags panel sockets (Tag Cap, Size, Color, Facing Cull)
- tests/test_gpu_sample.py      # keep green; add Tags collect/Cap tests where feasible
- dev_tasks/001_gpu_overlay/tests/profile_overlay_harness.py

Facing math (keep unless replacing with something better + tested):
  toward = normalize(cam - wco)
  drop if dot(normal, toward) <= 0.05

## Progressive plan (execute in order)

### T0 — Baseline
Harness Tags cold/warm; note tags.collect + draw cost; optional screenshot of
nearest pile.
  blender --background --python-exit-code 1 \
    --python dev_tasks/001_gpu_overlay/tests/profile_overlay_harness.py -- \
    --blend examples/attrviz_test_cube.blend \
    --attr heat --displays Tags --max-targets 1 --warm 3 \
    --json dev_tasks/001_gpu_overlay/references/perf/tags_before.json

### T1 — Cap policy (product + quality)
Replace DEFAULT Cap selection:
  sample → optional facing → project to screen → screen-space bins
  → at most one label per cell → ≤ Tag Cap, spread across view
Keep nearest as optional later mode only if cheap; do not default it.
Cap 0 → []. Validate GUI: labels spread on cube/mesh; Facing on/off; Cap scrub.

### T2 — Collect CPU
Vectorize facing where practical; harden world-label cache; early-outs.
Validate: tags.collect ↓ vs T0; Cap policy visuals unchanged.

### T3 — Instanced card quads (Arrows pattern)
Unit quad (once) + instance rows (sx, sy, w, h[, color])
  → GPUShaderCreateInfo + draw_instanced
  → soup/_draw_cards_batched fallback when --background (no CreateInfo GPU)
Validate: card visual parity; headless still green via fallback.

### T4 — Glyph atlas
Bake glyphs; draw labels as textured quads (instanced or batched).
BLF fallback for atlas miss / odd strings.
Validate: Cap ~1k without BLF cliff; screenshot vs prior BLF look.

### T5 — Closeout
Harness tags_after.json; POR Phase 7c checkboxes; version bump if appropriate;
rsync for user verify. Commit only if asked.

## Validate always
- tests/test_gpu_sample.py + tests/headless_test.py green
- Tag Cap 0 empty; Density 0 on Markers still empty
- Markers/Arrows/Surface regressions unchanged
- Install: rsync attrviz/ → ~/Library/Application Support/Blender/5.0/extensions/user_default/attrviz/

## After finish
Update POR.md Phase 7c Status/checkboxes. Do not implement Scope UX here.
```
