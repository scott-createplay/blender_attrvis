# POR: GPU overlay — probe first, then AttrViz display path

## Overview

Build a **viewport GPU attribute overlay** for AttrViz: unlit data ink in **Solid** mode, no materials / Material Preview / Workbench Attribute hacks, no beauty-pass pollution.

**Execution shape (locked):**

1. **Start with a standalone probe** under this folder — prove sample → upload → draw.
2. **As the probe lands, immediately start the real overlay** inside `attrviz/` — do not wait for a follow-up POR.
3. Keep the materials/`vizcol` path working until GPU Displays are at parity; then prefer GPU and thin or retire GN carriers per Display.

If Python draw-handler depth/color cannot meet the bar, **escalate** mid-task to a compiled Overlay-engine path — with evidence — rather than papering over with scene meshes.

## Status: Stage B started — GPU Markers behind scene flag

| Piece | State |
|-------|--------|
| AttrViz 0.5.2 materials path (emission + `vizcol`) | Working; keep as fallback until GPU Displays land |
| Tags GPU prototype (`attrviz/tags_draw.py`) | Exists (`POST_PIXEL` text); reuse sampling ideas, not as the geometry ink path |
| Standalone probe (`dev_tasks/001_gpu_overlay/probe/`) | **Gate A met**; Phase 3 depth/FACE/vectors in probe |
| Real AttrViz GPU overlay module | **Markers + Surface + Arrows GPU**; Tags (text) deferred |

**Current AttrViz commit (context):** `61309c5` — AttrViz 0.5.2.

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
- [ ] Tags: keep BLF labels but prefer depth-aware placement / `POST_VIEW` where possible; share sampler with Markers. **Deferred** — BLF `POST_PIXEL` prototype remains; depth-aware Tags is follow-on.
- [x] Style sockets (Heat / RGB / Random) applied in GPU color map (parity with GN intent, not pixel-identical ramp required in v1).

**Validate**

- [x] Normal / `flow` arrows in Solid (user: two viz, independent Arrow Colors).
- [x] Tags still capped; no Material Preview required for Markers/Arrows.
- [ ] Screenshots in `references/` — Markers saved; Arrows screenshot optional if user pastes one.

**Exit:** Markers + Arrows GPU done; Tags depth deferred (listed above).

---

#### Phase 7 — Surface strategy + DistLook live + cleanup (2–4 days)

**Author**

- [x] Surface: choose approach — (a) GPU face tint / mesh batch, (b) hybrid keep GN mesh + GPU color, or (c) defer with written rationale. Prefer (a) if Phase 3 face path scaled. **Done: (a) TRIS batch + domain colors + inflate.**
- [ ] Live DistLook: `entity_id` / `dist_*` via AttrViz on sample_scene_3 mesh (Solid), side-by-side sheet language.
- [ ] Thin probe to a thin wrapper or README pointing at `attrviz` module; avoid permanent duplicate stacks.
- [ ] EEVEE/pixel or buffer tests where meaningful; **do not** rely only on “vizcol exists.”
- [ ] Update README roadmap: GPU overlay Displays; materials as fallback.
- [ ] Bump addon version; migrate path for existing viz.

**Validate**

- [ ] DistLook qualitative match to sheet row-2 language.
- [ ] Full `tests/headless_test.py` green + any new overlay tests.
- [ ] User-verified Solid workflow.

**Exit:** POR complete — or escalate note if Surface needs compiled plugin.

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
- Digit-atlas shader v1 (nice follow-on; Tags BLF OK meanwhile).

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
```

Visual bar:

```text
dev_tasks/001_gpu_overlay/references/sample_scene_3_distlook_aov_sheet.png  # row 2
```

Ask: “If this were an AOV panel for the attr I’m sampling, would a human trust it?”

---

## Handoff checklist for the next agent

1. Read this POR end-to-end.
2. Open both reference sheets; internalize **row 2** as the bar.
3. Read Blender GPU overview + GPUViewport docs.
4. **Start Stage A Phase 0** — probe only; do not edit `attrviz/` yet.
5. Land Phase 2 pixels, then **immediately begin Stage B Phase 5** while finishing Phase 3.
6. Update Status table as phases complete.
7. Install into Blender when asking the user to click-test.
