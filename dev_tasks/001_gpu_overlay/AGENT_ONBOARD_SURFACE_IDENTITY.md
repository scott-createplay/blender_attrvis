# Agent onboard — Surface = reference + colors only

**Parent:** [`POR.md`](POR.md) Phase 7 amendment (locked 2026-08-12)  
**Do not start yet:** Phase 7b Arrows instancing (blocked on this)  
**Related:** [`POR_strangle_gn_backbone.md`](POR_strangle_gn_backbone.md) (create-path; separate)

Paste the prompt below into a new agent chat (or `@` this file).

---

## Prompt (copy from here)

```text
You are implementing AttrViz’s Surface GPU display fix in blender_attrvis.

## Locked product model

| Display | Geometry | What changes |
|---------|----------|--------------|
| Surface | Reference the target’s evaluated mesh (same verts/faces) | False-color only |
| Markers | Construct NEW points | Sample → POINTS batch |
| Arrows  | Construct NEW cones | Sample → cone carriers (today: expanded soup) |
| Tags    | Construct NEW labels | BLF |

Surface must NOT invent a parallel mesh. Markers/Arrows/Tags are the Displays that construct.

## What is wrong today

Surface is wired like Markers: build a triangle soup and draw it.

Call chain:
  gpu_overlay._sample_surface
    → gpu_sample.build_surface_tris   # NEW out_pos, inflate, optional filter
    → _refresh_surface_from_sample
    → _build_batch(..., prim='TRIS')  # anonymous GPU mesh
    → POST_VIEW draw

Wrong sites:
- attrviz/gpu_sample.py — build_surface_tris / _build_surface_tris_impl
  (inflate, face-normal offset, outlier cull hooks, face_cap stride)
- attrviz/gpu_overlay.py — _sample_surface, _refresh_surface_from_sample,
  drawing Surface as a constructed TRI batch

User-verified symptom on sample_scene_3 (dist_sign_hue / emission_strength,
Point · Surface · Heat): floating giant tris / starbursts / wrong hull —
broken constructed geometry, NOT “z-fighting to fix with more inflate.”

## Goal (this initiative only)

Make GPU Overlay Surface = identity topology of the evaluated target mesh + colormap.

Recommended approach (POR option S1):
1. Positions = evaluated mesh loop_triangles verts × matrix_world ONLY.
2. inflate = 0; no outlier face cull; no default face striding.
3. Keep domain→corner value expansion + gpu_color colormap (that’s the allowed change).
4. Still may upload a GPUBatch for POST_VIEW (Blender Python overlay cannot
   literally recolor Blender’s object draw) — but buffers must be an identity
   copy of the mesh, not a mutated/reconstructed surface.
5. Do NOT start Arrows instancing (Phase 7b) or strangler Phase 2 in this pass.
6. Do NOT “fix” visuals with inflate, outlier drops, or more construction.

If identity Surface fails Solid depth with evidence, document and propose S2
(hybrid GN reference for Surface only) or escalate — do not silently reintroduce inflate.

## Read first

1. dev_tasks/001_gpu_overlay/POR.md — Status “Next”, Phase 7 amendment, Phase 7b (out of scope now)
2. This file
3. attrviz/gpu_sample.py (build_surface_tris)
4. attrviz/gpu_overlay.py (Surface sample/present/draw)
5. Contrast: node_builder.py GN Surface (Object Info → vizcol) — topology reference

## Validate

Automated:
- tests/test_gpu_sample.py: Surface positions == evaluated loop-tri world positions
  within epsilon (no inflate delta); n_tris == len(mesh.loop_triangles)
- tests/headless_test.py green (GPU off for GN path)
- Keep Markers/Arrows behavior unchanged

Harness (optional but useful):
  blender --background --python-exit-code 1 \
    --python dev_tasks/001_gpu_overlay/tests/profile_overlay_harness.py -- \
    --max-targets 1 --displays Markers,Surface --warm 2 \
    --json /tmp/attrviz_surface_identity.json

Visual (gate):
- sample_scene_3 AOV blend (path in profile_overlay_harness.DEFAULT_BLEND)
- GPU Overlay ON, viz: dist_sign_hue or emission_strength, Point · Surface · Heat
- Must read as the sign’s surface false-colored — not a second constructed hull
- Screenshot → dev_tasks/001_gpu_overlay/references/attrviz_surface_identity_sign.png
- Sync install: ~/Library/Application Support/Blender/5.0/extensions/user_default/attrviz/
  then disable/enable addon or restart Blender for user verify

## After you finish

- Update POR.md Phase 7 checkboxes / Status Next
- Bump version if appropriate
- Do NOT implement Phase 7b Arrows instancing unless the user asks
- Commit only if asked

Blender: 5.0.1+ · AttrViz currently 0.5.5+
```

---

## Extra context for the agent (not required in the paste)

### Efficiency note (out of scope for this initiative)

Arrows today expand N samples → 12N world verts (no instancing). Phase 7b will move to `GPUBatch.draw_instanced` + unit cone **after** Surface lands. Markers are already POINTS.

### Create-path note (out of scope)

GPU Overlay create was sped up (shared engine, suppress before Target, cheap Attr Is Vector). Strangler Phase 2 (lazy GN) is separate — see `POR_strangle_gn_backbone.md`.

### Install ≠ repo

Always rsync `attrviz/` → Blender extensions `user_default/attrviz/` for interactive verify.
