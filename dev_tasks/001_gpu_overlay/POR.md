# POR: GPU overlay — probe first, then AttrViz display path

> **Frozen (Stage B, 0.5.10).** This POR is the history of how AttrViz got GPU ink.
> Overlay-type work (Arrows Metal abort, unified geometric cull, kind tag) lives in
> **[`../002_overlay_kinds/POR.md`](../002_overlay_kinds/POR.md)**.
> Do not add new Display-leaf sample/cap/upload here. GUI confirm of watch collection /
> Surface identity / Tags-as-shipped may still close out on this task; do not block 002 P0.

## Overview

Build a **viewport GPU attribute overlay** for AttrViz: unlit data ink in **Solid** mode, no materials / Material Preview / Workbench Attribute hacks, no beauty-pass pollution.

**Execution shape (locked):**

1. **Start with a standalone probe** under this folder — prove sample → upload → draw.
2. **As the probe lands, immediately start the real overlay** inside `attrviz/` — do not wait for a follow-up POR.
3. Keep the materials/`vizcol` path working until GPU Displays are at parity; then prefer GPU and thin or retire GN carriers per Display.

If Python draw-handler depth/color cannot meet the bar, **escalate** mid-task to a compiled Overlay-engine path — with evidence — rather than papering over with scene meshes.

## Status: Stage B — GPU Overlay + Viz panel fixed (0.5.3)

| Piece | State |
|-------|--------|
| AttrViz materials path (emission + `vizcol`) | Working fallback; GPU Overlay covers Markers/Surface/Arrows |
| Tags (BLF text) | **7c Cap + cards in 0.5.9**; glyph atlas pulled (UV/layout wrong). Text = `blf.draw` until a working atlas. GUI confirm open |
| Standalone probe | Gate A met |
| Real AttrViz GPU overlay | Markers + Surface + 4-sided Arrows; Tags 7c (POST_PIXEL) |
| **Viz N-panel layout** | **Fixed** — `layout.panel_prop` per viz (collapsible; header = Enabled + `attr · domain · type` + remove) |
| **Watch collection (`attrvis`)** | **0.5.10** — scene-level Scope; RMB AttrViz → Visualize Attribute / Edit → Add·Remove objects; panel coverage readout |

**Current AttrViz version:** `0.5.10`.

**Next (ordered):**

1. **Overlay kinds (002)** — crash stop + geometric vs surface policy: [`../002_overlay_kinds/POR.md`](../002_overlay_kinds/POR.md).  
2. GUI confirm (optional closeout): watch collection, Surface identity, Tags-as-shipped if not user-signed.  
3. Deferred: attribute discovery / DistLook / strangler Phase 2 — [`backlog.md`](backlog.md).  

---

## Viz panel layout (resolved)

### Was broken

Manual `column`/`box` loops cascaded-indent headers; `bl_parent_id` subpanels indented by design; a `UIList` attempt overlapped controls. Root cause: nesting `UILayout` children across list rows, or using the wrong Blender list pattern for collapsible per-viz settings.

### Fix (user-verified)

Use Blender 5.0 **`layout.panel_prop(obj, "attrviz_ui_expand")`** on the **root** panel layout only (never inside `column`/`box`/`split`):

- **Header:** Enabled checkbox + title (`attr · domain · type`) + remove — always visible for scanning/toggling.
- **Body:** `_draw_viz_body` only when the layout panel is open (`body is not None`).
- Accordion via existing `attrviz_ui_expand` update (one open at a time).

Code: `attrviz/__init__.py` — `ATTRVIZ_PT_panel.draw`. Abandoned: `ATTRVIZ_UL_visualizers`, `ATTRVIZ_PT_settings` / `bl_parent_id`, `Scene.attrviz_viz_index`.

Install path still ≠ repo — rsync/cp after edits; disable/enable addon or restart Blender.

---

## Watch collection (`attrvis`) — resolved (0.5.10)

**Product:** AttrViz visualizes one scene collection named `attrvis`. Membership **is** the scope. Objects stay in their other collections (Blender multi-membership). Not attribute-discovery (“all meshes that have `flow`”). Distinct from `Visualizers` (viz-object registry).

**RMB**

```
AttrViz
  Visualize Attribute → Point / Face / …   (create a viz; selection → attrvis)
  Edit
    Add objects                             (link selection into attrvis)
    Remove objects                          (unlink from attrvis; do not delete)
```

**Panel:** coverage readout on the **root** layout (`attrvis    N meshes · names…`, cap 8 + `+N more`). No Target/Scope pickers in `_draw_viz_body`. `panel_prop` stays root-only.

**GUI path:** `add_visualizer_from_selection` links selected ∪ active MESH (skip viz carriers), sets `Scope = attrvis`, `Target` unset. Multi-select adds all of them.

**API path unchanged:** `add_visualizer(target=, scope=)` for tests and city `--viz` (per-viz collection override).

**Not this pass:** collection picker, per-viz Scope in the panel, attribute discovery, strangler.

Code: `attrviz/__init__.py` (`WATCH_COLLECTION`, `_link_to_watch` / `_unlink_from_watch`, `ATTRVIZ_MT_root`). Tests: `tests/test_gpu_sample.py`.

### Out of scope leftovers (Phase 7)

- DistLook live smoke, probe thinning, README roadmap — as capacity allows. Tags atlas landed in **Phase 7c** (GUI confirm open).

---

## Why this exists (product context)

### The inspection problem

Downstream work (DistLook / sample_scene_3) produces **beauty ablations** and **user AOV panels** that show per-instance contract attributes as **flat, unlit data colors**. Artists and agents need the **same mental model in the live viewport**: scrub an attribute, see the field on geometry, without lights/textures fighting the readout.

AttrViz today paints via Geometry Nodes + emission material reading `vizcol`. That:

- Requires Material Preview / EEVEE camera rays
- Fought Workbench Solid Attribute (GN-only geo limitation)
- Is the wrong metaphor for “show me `entity_id` like the AOV sheet”

### Reference outputs — what “good” looks like

Copied into this task for offline viewing (also live under the HDR pipeline repo):

| Artifact | Role | Path (this repo) | Source (HDR pipeline) |
|----------|------|------------------|------------------------|
| **DistLook AOV sheet** (seeded variation) | Target visual language: ±2 beauty **plus** flat AOV panels | [`references/sample_scene_3_distlook_aov_sheet.png`](references/sample_scene_3_distlook_aov_sheet.png) | `…/output/diagnostics/distlook_aov_still/output/sample_scene_3_look_seed_exposure_sheet.png` |
| **DistLook identity sheet** | Identity plate: offsets ≈ 0 in AOV row; beauty ≈ pristine | [`references/sample_scene_3_distlook_identity_sheet.png`](references/sample_scene_3_distlook_identity_sheet.png) | `…/output/diagnostics/distlook_identity_still/output/sample_scene_3_look_seed_exposure_sheet.png` |
| Multilayer EXR (AOV job) | Ground-truth layers behind the sheet | *(not copied — large)* | `…/output/diagnostics/distlook_aov_still/output/sample_scene_3_look_seed_beauty.exr` |
| AOV overlay preset | Canonical AOV name list | — | `hdr_synthetic_scene_pipeline/render_presets/overlays/distlook_aovs.json` |

HDR pipeline root (sibling checkout expected):

```text
/Users/scott.peters/dev/hdr_synthetic_scene_pipeline
```

Related sister PORs (read for contract / harness language; do not implement DistLook cook here):

- `dev_tasks/005_distlook_channel_contract/POR.md` — DistLook attrs + user AOV readout
- `dev_tasks/003_scene3_compositor_denoise_aov_sheets/POR.md` — sheet grammar (±2 + AOV row)

### How to read the sheets (for the next agent)

Open the PNGs in `references/`. Sheet grammar:

**Row 1 — Beauty exposure ablation (−2 / 0 / +2)**  
Lit lookdev. **Not** what the GPU overlay must reproduce. Exists to prove the scene still looks right while attributes are inspected.

**Row 2 — User AOVs / attribute panels (the viewport target)**  
Unlit, flat, data-as-color. These panels are the acceptance **look** for overlay drawing:

| Panel | Underlying data | Viewport analogue |
|-------|-----------------|-------------------|
| `entity_id` | Per-instance / expand id (categorical) | Random / hash false-color per id (solid faces or points) |
| `entity_class` | Class label (categorical) | Same; fewer unique colors |
| `dist_sign_hue` | Signed / scalar DistLook channel on signs | Heat or bipolar map on the domain that owns the attr |
| `dist_sign_emission` | Emission delta / field on signs | Heat (often near-zero on identity plate) |
| `dist_section_hue` | Same family on building sections | Heat / bipolar |
| `dist_section_emission` | Emission field on sections | Heat |

On the **identity** sheet, DistLook channel panels are near-empty / zero — that is correct (Std = Variance = 0 → passthrough). On the **seeded** sheet, `dist_*` panels show spatial structure. Overlay success means: **in Solid mode**, AttrViz (and the probe before it) draws with that same “data panel” clarity.

**Do not** require bit-identical Cycles AOV EXR matches. Aim at: **same inspection intent** — attribute → unlit viewport ink.

Preset AOV names (vocabulary when DistLook-wiring):

```text
entity_id, entity_class,
dist_sign_hue, dist_sign_sat, dist_sign_val, dist_sign_emission,
dist_section_hue, dist_section_sat, dist_section_val, dist_section_emission
```

---

## Goal

**One POR, two stages:**

| Stage | What | Where |
|-------|------|--------|
| **A — Probe** | Prove plumbing end-to-end | `dev_tasks/001_gpu_overlay/probe/` (no AttrViz import) |
| **B — Product overlay** | Real AttrViz GPU display path | `attrviz/` — starts **as soon as Stage A Phase 2 exits** |

```text
dev_tasks/001_gpu_overlay/
  POR.md
  AGENT_ONBOARDING.md
  references/                     # AOV sheets + phase screenshots
  probe/                          # Stage A — isolated
  tests/                          # Stage A headless (+ later Stage B)
attrviz/
  gpu_overlay.py                  # Stage B — TO BUILD (name flexible)
  tags_draw.py                    # existing; converge sampling later
  …                               # wire Display modes to GPU path
```

**Stage A success (gate to start B):** Solid-mode unlit points/faces from evaluated attrs; no materials; F12 clean; screenshot in `references/`.

**Stage B success (POR complete):** At least **Markers** (points) and **Arrows** (or lines) drawn via GPU for AttrViz visualizers in Solid mode; materials path still available as fallback; headless tests cover sampling + a non-black / non-empty draw contract where feasible; DistLook-style attrs readable live.

---

## Problem

| Gap | Today | Need |
|-----|--------|------|
| Unlit attr preview | AttrViz needs Material Preview + emission | Solid-mode GPU ink |
| Display-only | Scene geo + materials constrain lookdev | Overlay / handler path; never beauty mesh |
| DistLook inspection | Offline EXR → PNG sheets | Live viewport analogue of row-2 panels |
| Big-bang rewrite risk | Large GN engine | Probe first, then migrate Displays progressively |
| Python vs compiled | Unknown | Probe decides; escalate inside this POR if blocked |

---

## Design principles

1. **Probe first, product next — continuous.** Do not park after the probe. Phase 2 green → begin Stage B in the same effort.
2. **Stage A isolates risk.** Probe must not import `attrviz`. Copy ideas from `tags_draw.py` only.
3. **Stage B reuses probe code.** Promote sampler / color maps / batch helpers into `attrviz/` (shared module); delete or thin duplicate probe logic once promoted.
4. **Sample ≠ display.** Depsgraph sample → GPU buffers → draw. GN may remain for watch/config; display ink should not require Set Material / `vizcol` for GPU Displays.
5. **Solid-first.** Material Preview must not be required for GPU Displays.
6. **Unlit false-color.** Match AOV-panel intent (heat / hash / RGB).
7. **Progressive Displays.** Markers → Arrows → Tags depth → Surface last (Surface is hardest in pure overlay).
8. **Keep fallback.** Do not rip out materials path until a Display is GPU-validated.
9. **Fail honest on depth.** If Python cannot depth-test correctly, escalate (compiled overlay) — do not invent fake scene meshes.
10. Read [GPU/Viewport Module docs](https://developer.blender.org/docs/features/gpu/) — dual buffers, batches vs imm, create-info for any compiled escalate.

---

## Architecture

### Stage A (probe)

```text
Active object / probe target
        → depsgraph evaluated mesh
        → CPU buffers (pos[], value[] / color[])
        → GPUBatch + shader
        → SpaceView3D draw handler (prefer POST_VIEW)
        → Solid viewport unlit ink
```

### Stage B (AttrViz)

```text
Visualizer object (registry) + modifier sockets
        → resolve Target / Scope / Attribute / Domain / Style / Display
        → shared sampler (promoted from probe)
        → per-Display GPU drawers (Markers / Arrows / …)
        → one (or few) View3D draw handlers registered by attrviz
        → Solid viewport; hide_render irrelevant to ink
```

GN engine may still exist for Tags empty geo / future Surface hybrid; **Markers/Arrows GPU path should not depend on realized marker meshes** once Stage B lands those Displays.

### Blender docs map (required reading)

| Doc | Why |
|-----|-----|
| https://developer.blender.org/docs/features/gpu/ | gpu-module vs draw manager |
| https://developer.blender.org/docs/features/gpu/overview/ | Batch / shader / FB; create-info; imm vs batch |
| https://developer.blender.org/docs/features/gpu/abstractions/gpu_viewport/ | Scene `color` vs `color_overlay`; OCIO blit |

---

## Progressive plan

### Stage A — Probe

#### Phase 0 — Onboarding + fixture (½ day)

**Author**

- [x] Read this POR + both reference PNGs; row-2 = visual bar.
- [x] Skim GPU overview + GPUViewport docs.
- [x] Create `probe/` skeleton.
- [x] Synthetic fixture: `heat` (float POINT), `face_id` (int FACE), optional `flow` (vector POINT).

**Validate:** Fixture opens in Blender 5.0.1; Spreadsheet shows attrs.

**Exit:** Builder script or .blend under this task / `examples/` — `probe/build_fixture.py` + `probe/probe_fixture.blend`.

---

#### Phase 1 — Sample plumbing only (½–1 day)

**Author**

- [x] `sample_evaluated(obj, attr, domain) -> (positions, values, dtype)`.
- [x] POINT + FACE centers minimum.
- [x] Headless test on known grid.

**Validate**

```bash
blender --background --factory-startup --python-exit-code 1 \
  --python dev_tasks/001_gpu_overlay/tests/test_probe_sample.py
```

**Exit:** Tests green — **22/22 passed** (2026-08-11).

---

#### Phase 2 — First pixels: unlit points (**gate to Stage B**) (1–2 days)

**Author**

- [x] `POST_VIEW` handler: points or small tris.
- [x] Float → heat; int → stable hash (`entity_id` analogue).
- [x] Probe-local toggle only.

**Validate (manual)**

- [x] Solid: colored points visible.
- [ ] `hide_render=True`; F12 has no ink.
- [x] Screenshot → `references/probe_phase2_points.png`.

**Exit:** Phase 2 screenshot + probe README. **→ Begin Stage B Phase 5 in parallel with Phase 3** (do not wait for DistLook).

---

#### Phase 3 — Depth + domains + vector stub (1–2 days)

Can overlap Stage B scaffolding.

**Author**

- [ ] Depth test / occlusion.
- [ ] FACE domain hash regions.
- [ ] Optional vector lines (`flow`).
- [ ] Cap/stride (document e.g. 50k).

**Validate:** Occlusion proof; face regions; perf note 10k/50k/200k.

**Exit:** `references/probe_phase3_faces.png`. Go/no-go note on Python depth (feeds escalate).

---

#### Phase 4 — DistLook attr smoke (optional, parallel)

- [ ] Point at DistLook-cooked mesh if sibling scene available.
- [ ] `entity_id` + one `dist_*`; compare language to reference sheet row 2.
- [ ] Screenshot → `references/probe_phase4_distlook.png`.

Not a hard gate for Stage B Markers.

---

### Stage B — Real AttrViz GPU overlay (starts after Phase 2)

#### Phase 5 — Promote core into `attrviz/` (1–2 days)

**Author**

- [ ] Add `attrviz/gpu_overlay.py` (or split `gpu_sample.py` + `gpu_draw.py`).
- [ ] Move/adapt sampler, heat/hash coloring, batch draw helpers from probe.
- [ ] Register/unregister draw handler with AttrViz addon lifecycle.
- [ ] Drive from **existing visualizer** objects: respect Enabled / hide_viewport; read Attribute / Domain / Style / Display from modifier.
- [ ] **Markers (GPU points)** first Display behind a clear flag or Display routing (e.g. GPU path when Display=Markers and prefs/flag on — or replace GN markers once validated).
- [ ] Keep GN+material path for Displays not yet migrated; do not break 0.5.2 default scenes without migration note.

**Validate**

- [ ] AttrViz Markers on fixture: Solid shows heat/hash without Material Preview.
- [ ] Existing headless geometry tests still pass; add GPU-path smoke where possible.
- [ ] Screenshot → `references/attrviz_phase5_markers_gpu.png`.
- [ ] Install into user Blender extensions when asking user to verify (do not assume dirty tree = installed).

**Exit:** Markers GPU path usable from Viz panel / RMB-created viz.

---

#### Phase 6 — Arrows GPU + Tags depth (2–3 days)

**Author**

- [x] Arrows: line/cone-lite from vector attrs; non-vector → draw nothing (honesty rule from 0.5.x).
- [x] Tags: keep BLF labels but prefer depth-aware placement / `POST_VIEW` where possible; share sampler with Markers. **Steps 1–2 done:** shared `gpu_sample` (incl. STRING), facing + nearest-N cap, screen cull, label cache, batched cards. Still `POST_PIXEL`+BLF (semantic text). Atlas = Step 3.
- [x] Style sockets (Heat / RGB / Random) applied in GPU color map (parity with GN intent, not pixel-identical ramp required in v1).

**Validate**

- [x] Normal / `flow` arrows in Solid (user: two viz, independent Arrow Colors).
- [x] Tags still capped; no Material Preview required for Markers/Arrows.
- [ ] Screenshots in `references/` — Markers saved; Arrows screenshot optional if user pastes one.

**Exit:** Markers + Arrows GPU done; Tags depth deferred (listed above).

---

#### Phase 7 — Surface strategy + DistLook live + cleanup (2–4 days)

**Author**

- [x] **Viz N-panel layout:** `layout.panel_prop` per viz (collapsible headers; `attr · domain · type`). User-verified.
- [x] Surface: first land — (a) GPU TRI batch + domain colors (**wrong model**: parallel constructed mesh + inflate).  
- [x] **Surface amendment (locked 2026-08-12):** Surface is a **reference to the original evaluated mesh**; only false-color changes. Markers/Arrows/Tags **construct** carriers; Surface must not. S1 identity pack landed in `gpu_sample.build_surface_tris` (0.5.6) — inflate / face_cap / outlier cull removed. **P4 visual gate still open** (user). Onboard: [`AGENT_ONBOARD_SURFACE_IDENTITY.md`](AGENT_ONBOARD_SURFACE_IDENTITY.md).
- [ ] Live DistLook: `entity_id` / `dist_*` via AttrViz on sample_scene_3 mesh (Solid), side-by-side sheet language.
- [ ] Thin probe to a thin wrapper or README pointing at `attrviz` module; avoid permanent duplicate stacks.
- [ ] EEVEE/pixel or buffer tests where meaningful; **do not** rely only on “vizcol exists.”
- [ ] Update README roadmap: GPU overlay Displays; materials as fallback.
- [x] Bump addon version; migrate path for existing viz. (`0.5.6`)

**Validate**

- [ ] DistLook qualitative match to sheet row-2 language.
- [ ] Surface visual: sample_scene_3 sign reads as **the sign’s surface** colored — not floating constructed hull/shards. (**P4 — user**)
- [x] Automated: Surface positions == evaluated loop-tri world positions (no inflate delta); tri count == mesh. (`tests/test_gpu_sample.py`)
- [x] Full `tests/headless_test.py` green + any new overlay tests.
- [x] Harness before/after JSON under `references/perf/` (Surface pack cost down; Markers flat). See P3 notes below.
- [ ] User-verified Solid workflow.

**Exit:** Surface reference model validated — or escalate note if Solid needs compiled plugin.

##### Surface identity progressive plan (P0–P5)

Scope: **S1 identity Surface only.** Markers/Arrows/Tags unchanged. Do **not** start Phase 7b or strangler Phase 2. Do **not** “fix” visuals with inflate / outlier cull / face stride. If identity loses Solid depth with evidence → document and propose S2 (hybrid GN reference) or escalate.

| Step | Work | Validate / hard stop | Status |
|------|------|----------------------|--------|
| **P0 — Baseline** | Inflate/construct perf reference | `references/perf/surface_before_identity.json` (annotated copy of `phase1_after.json` — true P0 mid-run was overwritten by identity) | done |
| **P1 — Identity pack** | Strip inflate / face_cap / outlier; vectorized identity expand | `test_gpu_sample.py` identity + tri-count checks | done |
| **P2 — Overlay hygiene** | `_sample_surface` docs; no inflate knobs; L0/L2 cache unchanged | `headless_test.py` 30/30 | done |
| **P3 — Perf after** | Same harness → `surface_after_identity.json` | SIGN 1-target: `build_surface_tris` **271 → 65 ms**; cold Surface **309 → 98 ms**; Markers cold ~flat (~352–377 ms) | done |
| **P4 — Visual gate** | Sync install (done 0.5.6); sample_scene_3 Point · Surface · Heat | Screenshot → `references/attrviz_surface_identity_sign.png`; depth shred → S2, no inflate | **open** |
| **P5 — Closeout** | Check boxes; Next → DistLook leftovers; commit if asked | Phase 7b stays blocked until visual gate + user ask | partial |

**Perf delta (SIGN / `emission_strength` / Markers+Surface / max-targets 1):**

| Span | Before (inflate) | After (identity) |
|------|------------------|------------------|
| `sample.build_surface_tris` | 271 ms | 65 ms |
| `sample.surface_tri_pack` | 267 ms | 64 ms |
| `harness.cold.Surface` | 309 ms | 98 ms |
| `harness.cold.Markers` | ~377 ms | ~352 ms (flat) |

Harness template:

```bash
blender --background --python-exit-code 1 \
  --python dev_tasks/001_gpu_overlay/tests/profile_overlay_harness.py -- \
  --max-targets 1 --displays Markers,Surface --warm 2 \
  --json dev_tasks/001_gpu_overlay/references/perf/surface_after_identity.json
```

---

#### Phase 7b — Arrows GPU instancing (follow-on; after Surface)

**Blocked on:** Phase 7 Surface identity + solid mute validated (do not interleave with scoping UX).

**Why:** Today Arrows expand every sample into a unique 12-vert cone soup on the CPU (`_arrow_cone_geometry_impl`) and re-upload on Length/Scale scrub. Markers are already light (points). Arrows are the heavy constructed Display.

**Target pipe:**

```text
TODAY
  L0 sample: positions + vectors
  L2 present: expand 4-side cone → 12N world verts (CPU)
  upload full TRI batch + builtin SMOOTH_COLOR

TARGET
  L0 sample: same (unchanged)
  once: unit cone indexed batch (4-side)
  L2 present: N instance rows (origin, basis/dir, length, radius, color)
  custom shader: unit cone × instance transform
  GPUBatch.draw_instanced(shader, instance_count=N)
```

**Instance row layout (draft):**

| Field | Type | Notes |
|-------|------|-------|
| `origin` | vec3 | sample world position (cone base) |
| `dir` | vec3 | unit direction (drop if ‖v‖≈0) |
| `length` | float | socket Length |
| `radius` | float | `Scale * 0.35` (GN spirit) |
| `color` | vec4 | Arrow Color (uniform OK if one color/viz) |

Shader transforms unit cone (base at origin, tip +Z) into world via orthonormal basis from `dir` (same math as today’s CPU expand).

##### Progressive plan (A0–A5)

| Step | Work | Validate / hard stop |
|------|------|----------------------|
| **A0 — Baseline** | Harness Arrows cold + `--scrub` Length before change | `references/perf/arrows_before_instancing.json` |
| **A1 — API spike** | Prove custom shader + `draw_instanced` (or string GLSL fallback) in Blender 5.0.1 | Tiny script draws N dummy cones; if CreateInfo unusable from extension → try `GPUShader(vert, frag)`; escalate only if both dead |
| **A2 — Unit cone** | Build shared indexed unit cone batch once (module cache) | 4-side; tip +Z; base ring at z=0 |
| **A3 — Instance present** | Replace soup in `_refresh_arrows`: L0 → alive filter → instance buffer; Length/Scale/Color update instances only | `overlay.arrow_cones` / present cost ≪ baseline on scrub; visual parity on test grid / `flow` |
| **A4 — Draw path** | Entry carries instanced batch + shader; POST_VIEW calls `draw_instanced` | Markers/Surface unchanged; non-vector → empty |
| **A5 — Closeout** | Drop soup from hot path (keep as optional oracle/test helper); harness after JSON; version bump; POR checkboxes | Scoping UX stays in [`backlog.md`](backlog.md) |

**Author**

- [x] Unit cone mesh + `GPUBatch` (4-side); shared module cache.
- [x] Instance path: origin/dir as RGBA32F textures + `GPUShaderCreateInfo` + `draw_instanced`; Length/Scale/Color as push constants (per-viz uniforms — scrub does not rebuild cone verts when GPU context exists).
- [x] Soup fallback when CreateInfo unavailable (`blender --background`); oracle `_arrow_cone_geometry` kept for tests.
- [x] Non-vector → empty; density/cap unchanged at sample layer.
- [x] Markers stay POINTS; no GN for GPU Overlay Arrows.
- [x] Execute **A0–A4** (A5 visual still open).

**Validate**

- [ ] Visual parity with current 4-side cones on cube `flow` / sample_scene_3 (**GUI** — CreateInfo needs GPU context).
- [x] Harness JSON under `references/perf/arrows_{before,after}_instancing.json` (cube `flow`). Note: `--background` harness still exercises **soup fallback**; instanced hot path is GUI-only until Blender exposes CreateInfo without a window.
- [x] Headless / `test_gpu_sample.py` green (alive frames ↔ soup count; instanced-or-soup).

**Exit:** Arrows = instance transforms in Solid GUI; soup remains background/oracle fallback.

**Impl notes (0.5.8):**
- Instance row = origin + dir textures; Length/radius/color are uniforms (same for all arrows in a viz).
- `overlay.arrow_instances` span = alive filter; soup path still named `overlay.arrow_cones`.

**Out of scope for 7b:** Target/Scope panel UX, attribute discovery, Surface mute changes, strangler Phase 2.

---

#### Phase 7c — Tags Cap policy + draw perf (DONE in code, GUI confirm open)

**Onboard:** [`AGENT_ONBOARD_TAGS_PERF.md`](AGENT_ONBOARD_TAGS_PERF.md).  
**Reuse:** Arrows `GPUShaderCreateInfo` + `draw_instanced` in `gpu_overlay.py`.

##### Context

**Display role:** Tags = construct label carriers (not mesh reference). `POST_PIXEL` cards + atlas text.

**Call chain (0.5.9):**

```text
tags_draw.draw_callback_px
  → _labels_for_md
       → cached sample_evaluated(Target∪Scope) (+ Normal if Facing)
       → vectorized facing: drop if dot(normalize(N), normalize(cam - p)) <= 0.05
       → vectorized project + screen cull
       → screen_bin_select: one label per cell, ≤ Tag Cap, spread in view
  → unit-quad cards × draw_instanced (soup `_draw_cards_batched` fallback)
  → glyph atlas textured quads (BLF fallback on miss / no OffScreen)
```

**Primary file:** `attrviz/tags_draw.py`  
**Also:** `gpu_sample.py` (sample / watch meshes), `gpu_overlay.py` (instancing pattern), `__init__.py` (Tag Cap / Size / Color / Facing Cull sockets).

**Already fixed (keep):**
- Tag Cap `0` → no labels (`_int_socket`; no `or 10000` / `max(1,…)`).
- Markers/Arrows Density `0.0` → empty (`_float_socket` in `gpu_overlay`; early-out in `gpu_sample`).

**Hard constraints (do not violate):**

| Constraint | Why |
|------------|-----|
| No “free visible verts” from Workbench backface cull | GPU cull is ephemeral; no ID list to Python |
| Facing ≠ occlusion | Front-facing behind another mesh still passes |
| Nearest Cap is not the inspect default | Piles labels at camera; starves rest of mesh |
| Card expand = same bottleneck *class* as old Arrows | Fix with unit quad + `draw_instanced` |
| BLF × N is the text cliff | Atlas retires hot-path `blf.draw` |
| `--background` may lack CreateInfo GPU | Soup/BLF fallback required (same as Arrows) |
| Commit / Scope UX / strangler / Surface inflate | Only if user asks; Scope stays in backlog |

**Target pipe:**

```text
sample Target∪Scope
  → facing (optional) + frustum/screen project
  → Cap policy = screen-space bins (default); ≤ Tag Cap, spread in view
  → unit quad cards × draw_instanced (soup fallback in background)
  → glyph atlas textured quads (BLF fallback for misses)
```

##### Progressive plan (T0–T5)

| Step | Work | Validate / hard stop |
|------|------|----------------------|
| **T0 — Baseline** | Before code: Tags harness + optional nearest-pile screenshot | `references/perf/tags_before.json` (cube `height`). Note `tags.collect` / draw-ish spans. |
| **T1 — Cap policy** | Replace **default** nearest sort with **screen-space binning** after project (+ facing). At most one label per cell; fill ≤ Cap across view. Nearest = optional later mode only. Cap 0 → `[]`. | GUI: labels spread on cube / mesh; Facing on/off; Cap scrub; unit test Cap 0 + bin count ≤ Cap. **Stop if Cap still nearest-only.** |
| **T2 — Collect CPU** | Vectorize facing where cheap; harden world-label cache; early-outs. Do not change Cap policy semantics. | `tags.collect` ↓ vs T0; visuals = T1. |
| **T3 — Instanced cards** | Unit quad batch + instance attrs `(sx,sy,w,h[,color])`; CreateInfo shader; `draw_instanced`. Keep `_draw_cards_batched` as `--background` / failure fallback. | Card look parity; headless green via fallback; GUI cards when GPU context exists. |
| **T4 — Glyph atlas** | Atlas for used glyphs (start alnum/punct); labels → textured quads; BLF only on miss. | Cap ~1k without BLF cliff; screenshot vs BLF reference. |
| **T5 — Closeout** | `tags_after.json`; Phase 7c checkboxes; version bump if appropriate; rsync for user verify; commit **only if asked** | Depth/ID readback **out of scope** unless T1–T4 insufficient with evidence. |

##### Author

- [x] **T0** baseline harness JSON (`references/perf/tags_before.json`; cube `height`).
- [x] **T1** screen-bin Cap default; Cap 0 empty; tests.
- [x] **T2** collect CPU wins (vectorized facing + sample cache; cube collect ~0.46→~0.37 ms).
- [x] **T3** instanced card quads + soup fallback.
- [x] **T4** glyph atlas — **reverted to BLF**. Atlas UV/layout were wrong (`hijk` sheet). Revisit after labels look right.
- [x] **T5** POR/version 0.5.9 / `tags_after.json`; rsync for user verify.

##### Validate

- [x] `tests/test_gpu_sample.py` + `tests/headless_test.py` green.
- [x] Tag Cap 0 → no labels (unit); Markers Density 0 still empty.
- [ ] Cap policy: labels spread (not front-pile) on example cube Tags. **GUI**
- [x] Harness before/after under `references/perf/tags_*.json`.
- [ ] GUI: Facing toggle, Cap scrub, Size/Color still work.
- [x] Markers / Surface / Arrows unchanged (headless + gpu_sample).

##### Validation commands

```bash
# Suite
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_gpu_sample.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/headless_test.py

# Tags harness (T0 / T5)
blender --background --python-exit-code 1 \
  --python dev_tasks/001_gpu_overlay/tests/profile_overlay_harness.py -- \
  --blend examples/attrviz_test_cube.blend \
  --attr height --displays Tags --max-targets 1 --warm 3 \
  --json dev_tasks/001_gpu_overlay/references/perf/tags_before.json
```

GUI gate: example cube or sample_scene_3 — Display Tags; confirm Cap spreads labels; Cap 0 clears; cards/text still readable in Solid. `--background` uses soup cards + BLF (no CreateInfo / OffScreen), same class as Arrows.

**Exit:** Default Cap is inspect-useful; cards not CPU soup on GUI hot path; text not N× BLF on hot path (atlas) — or documented fallback with evidence.

**Impl notes (0.5.9):**
- Cap socket `min_value=0` (0 = no labels). Engine rebuilds on version drift.
- `screen_bin_select` / `facing_keep_mask` / `project_world_to_region` are pure numpy (tested headless).
- Sample cache keyed by watch fingerprint + cheap author-mesh value peek (attr edits bust cache without camera in the key).
- Atlas charset = alnum + common punct; unknown glyphs (e.g. arbitrary STRING) → per-label BLF.

**Out of scope for 7c:** Scope panel UX, attribute discovery, Surface mute changes, Arrows background-soup removal, compiled Overlay engine, depth-buffer visibility pass (escalate note only if needed).

---

#### Phase 8 — Escalate branch (only if blocked)

If Phase 3/5 depth or scale fails:

- [ ] Write `ESCALATE.md`: blocker, evidence, proposed Overlay-engine / create-info plugin scope.
- [ ] Keep probe + partial AttrViz GPU as reference implementation.
- [ ] Stop expanding Python Surface; protect Markers if they still work.

---

## Non-goals / out of scope

- Implementing DistLook cook, AOV Output nodes, or diagnostic sheet tools (sister repo).
- Bit-exact OCIO / sheet tone-map parity with EXR panels.
- Vulkan/Metal work inside Blender source (unless escalate explicitly requires a build plugin plan).
- Removing materials path before GPU Markers are user-validated.
- Digit-atlas / Tags draw perf — **in scope as Phase 7c** (not a non-goal anymore).
- Watch collection (`attrvis`) landed in 0.5.10. Attribute discovery stays in [`backlog.md`](backlog.md).

---

## Acceptance

### Gate A (probe — required before calling Stage B “started”)

1. Phases 0–2 done; `references/probe_phase2_points.png` exists.
2. Headless sample tests green.
3. Solid unlit ink; no materials; F12 clean.

### Gate B (POR done)

1. AttrViz **Markers** (and **Arrows**) draw via GPU in Solid without Material Preview.
2. Visualizer registry / panel still drive Attribute · Domain · Style · Display.
3. Materials/`vizcol` fallback remains for unmigrated Displays (or documented removal if fully replaced).
4. Headless suite green; overlay regressions covered where feasible.
5. Reference screenshots for AttrViz GPU Displays in `references/`.
6. Agent can resume from `AGENT_ONBOARDING.md` without this chat.
7. If escalated: `ESCALATE.md` present and Markers status clear.

---

## Design constraints

| Constraint | Note |
|------------|------|
| Blender | 5.0.1+; same as AttrViz |
| License | GPL-3.0-or-later in `attrviz/` |
| Hot path | `GPUBatch` + cached buffers; avoid per-frame imm at scale |
| Install | Repo ≠ installed extension — rsync/install when user must verify |
| Tests | Geometry-only tests are insufficient for display; add pixel/buffer checks for GPU path |
| AttrViz UX | Do not invent a second registry; GPU path serves existing Visualizers |

---

## Suggested validation commands

```bash
# Stage A sample tests
blender --background --factory-startup --python-exit-code 1 \
  --python dev_tasks/001_gpu_overlay/tests/test_probe_sample.py

# AttrViz suite (must stay green through Stage B)
blender --background --factory-startup --python-exit-code 1 \
  --python tests/headless_test.py

# GPU sample / Surface identity contract
blender --background --python-exit-code 1 --python tests/test_gpu_sample.py

# Overlay perf harness
blender --background --python-exit-code 1 \
  --python dev_tasks/001_gpu_overlay/tests/profile_overlay_harness.py -- \
  --max-targets 1 --displays Markers,Surface --warm 2 \
  --json /tmp/attrviz_surface_perf.json

# Tags Phase 7c baseline
blender --background --python-exit-code 1 \
  --python dev_tasks/001_gpu_overlay/tests/profile_overlay_harness.py -- \
  --blend examples/attrviz_test_cube.blend \
  --attr height --displays Tags --max-targets 1 --warm 3 \
  --json /tmp/attrviz_tags_perf.json
```

Visual bar:

```text
dev_tasks/001_gpu_overlay/references/sample_scene_3_distlook_aov_sheet.png  # row 2
dev_tasks/001_gpu_overlay/references/attrviz_surface_identity_sign.png      # Phase 7 Surface gate
```

Ask: “If this were an AOV panel for the attr I’m sampling, would a human trust it?”

---

## Handoff checklist for the next agent

1. Viz panel is fixed (`panel_prop`); do not revive UIList / `bl_parent_id` list experiments without new evidence.
2. **Watch collection landed (0.5.10).** GUI confirm RMB AttrViz → Visualize Attribute / Edit Add·Remove, then Tags / Arrows / Surface if not user-signed. Do not draw per-viz Target/Scope pickers; do not start attribute discovery.
3. Tags Cap default is screen-space bins (`tags_draw.screen_bin_select`); do **not** revert to nearest-distance. `--background` soup/BLF fallbacks stay.
4. Do **not** treat Workbench backface cull as a free visible-vert list.
5. Deferred only in [`backlog.md`](backlog.md): attribute discovery, DistLook leftovers, strangler, optional Density-on-Tags / depth peek.
6. Install into Blender when asking the user to click-test (repo ≠ extensions path).
7. Commit only if asked.
