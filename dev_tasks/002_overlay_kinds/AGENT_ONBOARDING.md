# Agent onboarding — Overlay kinds (task 002)

**Status: Open.** Start at **P0** (stop the Arrows Metal abort).  
**Source of truth:** [`POR.md`](POR.md)  
**History (frozen):** [`../001_gpu_overlay/POR.md`](../001_gpu_overlay/POR.md)

## Start here

1. Read [`POR.md`](POR.md) (Why, Locked product, P0–P5, Acceptance).
2. Paste the prompt below into a **new** agent chat (or `@` this file).
3. Agent executes **P0 first**. City blend is in `examples/attrviz_city.blend` — rebuild with `--dense` if missing.

Do **not** `@` `001_gpu_overlay/AGENT_ONBOARD_TAGS_PERF.md` — its T1 spread Cap is superseded.

---

## Prompt (copy from here)

```text
You are implementing AttrViz overlay kinds in blender_attrvis (dev_tasks/002).
Blender 5.0.1+; AttrViz 0.5.10+. Read dev_tasks/002_overlay_kinds/POR.md first.
Then execute P0. Do not start P2–P5 until P0 is green unless the user says otherwise.

## Why

City flow as Surface, then Type=Arrows, aborts Blender (Metal):
  GPUTexture(size=(n, 1)) with n=19496 (Building_7_7) > 16384 max 2D width.
  ips: ~/Library/Logs/DiagnosticReports/Blender-2026-08-12-193420.ips
  assertion: MTLTextureDescriptor has width (19496) > max 16384.
  try/except cannot catch SIGABRT. --background uses soup so tests never saw it.
  Ten dense-city hulls are 19496 verts; overlay cap 50000 is also over 16384.

001 shipped four Display leaves with separate sample/cap/upload. This POR
keys POLICY on a kind tag (geometric vs surface). Display only presents.

## Locked

1. kind(Surface) = surface. kind(Markers|Arrows|Tags) = geometric.
   Policy (sample, Density, frustum+frame_dist cap, upload pack) dispatches on
   kind — not on Display. Implementation = tag/frozenset in
   attrviz/overlay_kind.py — not a bpy ABC, not leaf ifs in _refresh_arrows.
2. Geometric cull is CPU, after we have region/perspective_matrix, BEFORE upload.
   Under cap: keep all in-view. Over cap: keep smallest Chebyshev frame_dist
   (max(|nx|,|ny|) with nx,ny in [-1,1] vs view center). Not nearest-to-camera.
   Overfull fovea: bin inside the keep rect, not spread across the whole view.
3. Geometric upload: 2D RGBA32F pack, W=min(n,16384), H=ceil(n/W). NEVER
   GPUTexture with a dimension > 16384. Same helper for Tags cards.
   Do NOT "fix" the crash by capping Arrows at 16384 as product policy.
4. L0 sample cache: Density only; cap is NOT in the sample key.
   Upload cache is view-dependent. --background: no region → skip view pass,
   soup fallback, no abort.
5. Surface: identity tris + WIRE mute. No Density, no view-cap.
6. Tags may stay POST_PIXEL; they consume the geometric kept set.
   7c full-frame spread Cap is replaced by this heuristic (P2–P3, not P0).
7. Do NOT: attribute discovery, strangler, watch-collection UX, Tags atlas,
   new Arrows Cap widget, frustum-cull Surface, rewrite 001 POR.
8. Interleave: P0 pack (stop dying) first — may include a small kind().
   Do not migrate Markers+Arrows+Tags in one PR. Commit only if asked.
   Rsync attrviz/ → Blender 5.0 extensions for GUI verify.

## What exists (read these)

- attrviz/gpu_overlay.py
    _float_tex_rgba → GPUTexture(size=(n, 1)); shader texelFetch(id, 0)
    _refresh_arrows / _refresh_markers (leaf present)
    _sample_key includes cap (wrong once view cull exists)
    draw_callback already has context.region / region_data
- attrviz/gpu_sample.py
    sample_visualizer_targets: Density AND positions[::step] cap
    build_surface_tris: identity (keep; do not view-cap)
    watch_meshes_for_visualizer (attrvis if exists)
- attrviz/tags_draw.py
    private sample cache; screen_bin_select full-frame spread
    duplicate N×1 _float_tex_rgba (Tag Cap max 10000 → safe today)
- attrviz/node_builder.py — Display enum, Density, Tag Cap
- tests/test_gpu_sample.py, tests/headless_test.py — keep green
- examples/build_attr_city_scene.py — dense city; `examples/attrviz_city.blend`

## Phases (tick in POR.md)

P0 crash-stop pack → P1 kind() → P2 view cull → P3 presenters consume
kept set → P4 Surface unchanged → P5 closeout.

## Validate always

blender --background --factory-startup --python-exit-code 1 \
  --python tests/headless_test.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_gpu_sample.py

Plus kind/pack/frame_dist unit tests (n=19496 and 50000 pack dims ≤ 16384).

GUI P0: city Building_7_7 flow Surface → Arrows must not quit.
  Rebuild city if needed:
  blender --background --factory-startup --python-exit-code 1 \
    --python examples/build_attr_city_scene.py -- --dense
  rsync -a --delete attrviz/ \
    ~/Library/Application\ Support/Blender/5.0/extensions/user_default/attrviz/

## After finish

Update 002 POR checkboxes/status. Do not reopen 001 except a pointer if needed.
```
