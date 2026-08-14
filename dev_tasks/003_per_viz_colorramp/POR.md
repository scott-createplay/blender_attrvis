# POR: Per-Visualizer Color Ramp

**Parent / history:** [`../002_overlay_kinds/POR.md`](../002_overlay_kinds/POR.md) (closed).  
**Pickup:** [`AGENT_ONBOARDING.md`](AGENT_ONBOARDING.md)

AttrViz **0.6.x**. Blender **5.0.1+**.

---

## Why this POR exists

002 shipped kind-based dispatch, stochastic view cull, depth occlusion, and fast Surface. The GPU overlay is now THE path for all display types. But the **color pipeline is still a fixed preset**:

```
scalar → normalize [0,1] → fixed colormap (Heat / RGB / Random) → RGBA
```

### The problem

A user with 3+ Surface visualizers on different attributes (`temperature`, `pressure`, `velocity_magnitude`) all using "Heat" gets the same blue→cyan→green→yellow→red ramp on every one. When they switch between visualizers, there's no visual signature — they have to read the panel to know which attribute they're looking at.

Real workflows need **per-visualizer color ramps** so each attribute has a distinct palette:
- `temperature` → blue → white → red (diverging)
- `pressure` → dark green → yellow (sequential)
- `velocity_magnitude` → black → magenta → cyan (perceptual)

The moment they toggle, the entire viewport shifts palette and they instantly know which attribute is active.

### What exists today

| Component | Current state |
|-----------|--------------|
| `gpu_color.py` | `values_to_colors(values, dtype, style, vmin, vmax, seed)` — style selects a fixed function (`heat_colors`, `rgb_colors`, `hash_colors`) |
| `heat_colors` | Hardcoded 5-stop ramp (blue→cyan→green→yellow→red). No user control. |
| `node_builder.py` | GN tree has a `ShaderNodeValToRGB` node per engine copy — used ONLY by the materials path (GPU off). Never read by the GPU overlay. |
| Panel UI | `template_color_ramp` was shown only when GPU overlay is OFF (commented: "one ramp would apply to every viz"). Disabled for the GPU path. |
| `_socket_bundle` | Reads `Style` ("Heat"/"RGB"/"Random"), `Auto Range`, `Range Min`, `Range Max` — no ramp reference |
| Present path | Heat is per-vertex RGBA in a `SMOOTH_COLOR` batch. Present miss rebuilds the whole batch (`overlay.build_batch` ~13–28 ms on 33k tris). |

The materials path (GPU off) already had per-viz ramps via `.copy()` of the engine node group. GPU overlay replaced that — and dropped ramp editability.

### Why the first design would feel sluggish

Measured on identity Surface (~33k tris): `overlay.colors` is ~1.6–2.8 ms; `overlay.build_batch` is ~13–28 ms; `overlay.present.Surface` is **~33 ms**. Warm cache hits are ~0.05 ms.

A ColorRamp widget fires on every mouse-move. Putting a ramp hash in `_present_key` (recolor + rebuild batch) would make dragging a stop as expensive as scrubbing Range. NumPy lerp is not the bottleneck; **re-uploading the mesh is**.

Putting the widget on the viz engine group (P0 Option A) is a second trap: every stop-move dirties the GN tree → `depsgraph_update_post` → `_sync_vizcol_active`. That undoes the shared-engine work from 001.

---

## Locked product

### Terminology

| Word | Means |
|------|--------|
| **Surface** (and Markers) | Display / carrier. The thing drawn. |
| **ColorRamp** | The colormap. Always there, always editable. User can drag stops to any gradient. **This is the definition.** |
| **Presets** | Stop-lists that *fill* the ColorRamp. They do not replace it and they do not lock it. **P3 set:** Heat, RGB, Monochrome (BnW). |

Heat / RGB / BnW are presets of the same ramp — the same way Blender’s ColorRamp has nothing to do with Display type. They are not Displays, not coloring algorithms, and not mutually exclusive modes.

**Why this was confusing:** the existing Style enum (`Heat` / `RGB` / `Random`) is three *different mapping algorithms* from an older design (scalar colormap vs vector-as-RGB vs hash-id). That enum is leftover. It is not the product. P3 does not treat Style-RGB or Style-Random as “modes that don’t use the ramp.”

| Leftover (do not conflate) | Product |
|----------------------------|---------|
| Style `"RGB"` = vector XYZ → RGB channels | Preset **RGB** = a rainbow stop-list written into the ColorRamp |
| Style `"Random"` = hash id → solid color | Preset **Monochrome / BnW** = black→white stop-list |
| Style `"Heat"` = hardcoded 5-stop function | Preset **Heat** = default blue→red stops; then the user edits the ramp |

### Per-visualizer ColorRamp, interactive from the GPU overlay

Each visualizer stores its own ColorRamp **off the engine GN tree**. Surface/Markers scalar color is a **shader LUT**: dragging a stop updates a 256-entry texture, not the mesh batch. The ramp is always editable. Presets only write stops.

### Architecture

| Decision | Choice |
|----------|--------|
| Where ramp lives | A per-viz node tree that is **never** a modifier. Contains one `ShaderNodeValToRGB`. Pointer on the viz object (`attrviz_ramp_tree`). Shared `ensure_viz_group()` stays shared when GPU-on. |
| How GPU overlay uses it | Sample miss: upload **positions + scalar values** once. Ramp/range change: rebuild a **256-entry 1D LUT texture** + `vmin`/`vmax` uniforms. Shader: `t = saturate((v - vmin) / (vmax - vmin)); color = texture(ramp, t)`. |
| CPU fallback | `ramp_colors(values, stops, vmin, vmax)` in `gpu_color.py` for unit tests and `--background` (no CreateInfo). Not the interactive viewport path. |
| UI | `template_color_ramp` always shown for Surface/Markers (GPU on). Preset buttons write stops into that widget. User can then edit freely. Editing this tree must not dirty the engine group. |
| Presets (P3) | **Heat** (default 5-stop), **RGB** (rainbow stops), **Monochrome / BnW** (black→white). More palettes later (viridis, …) are the same mechanism. Applying a preset does not lock the ramp. |
| Range Min / Max | Shader uniforms on the ramp LUT path (same cheap update as the LUT). Do not rebuild the mesh batch. |

### What does NOT change

- Kind dispatch (geometric vs surface) — untouched.
- View cull, depth occlusion, Metal-safe packing — untouched.
- Shared engine when GPU-on — **not** reverted to per-viz `.copy()`.
- Tags, Arrows uniform color — not affected (Arrows use a single tint, not a ramp).
- GPU-off materials path may keep its engine `.copy()` ramp until a later wire-up. GPU overlay is THE consumer.
- Leftover Style enum algorithms (vector-as-RGB, hash Random) are not P3 presets. P3 does not add new Style values for palettes.

---

## Progressive plan

### P0 — Per-viz ramp tree (off-engine)

Do **not** copy the engine group. Shared `ensure_viz_group()` stays.

- [x] `ensure_viz_ramp(obj)` creates/returns a per-viz node tree (never assigned as a modifier) with one `ShaderNodeValToRGB`, seeded with the default Heat 5-stop.
- [x] Viz object holds a pointer (`attrviz_ramp_tree`). Two vizs → two trees. Editing one does not change the other.
- [x] Called from `add_visualizer` and `migrate_all_visualizers` (existing scenes get a ramp on first access).
- [x] Removing a viz frees its ramp tree when unused.
- [x] GPU-on vizs still **share** the engine datablock (001 regression).
- [x] Existing tests pass — overlay still uses hardcoded `heat_colors`. No panel change yet.

### P1 — Heat shader LUT + CPU fallback

- [x] `gpu_color.py`: `ramp_colors(values, stops, vmin, vmax)` and `extract_ramp` (from a ValToRGB / stop list).
- [x] `values_to_colors` gains optional `ramp=` for tests / `--background`. When style="Heat" and ramp is provided, use `ramp_colors` instead of hardcoded `heat_colors`.
- [x] Viewport Heat path: custom shader (CreateInfo, same family as Arrows textures). Positions + scalars uploaded on **sample** miss only. LUT texture + vmin/vmax updated on ramp/range change — **no** `overlay.build_batch` / `overlay.present.*` spike.
- [x] Must **not** put ramp hash in `_present_key` in a way that rebuilds the mesh batch.
- [x] Unit tests: 2-stop (black→white) and 5-stop interpolation; edge values.

### P2 — Panel UI enables ramp editing

- [x] Remove the `if not _gpu_overlay_on()` guard. Widget targets `ensure_viz_ramp(obj)`, not the engine ValToRGB.
- [x] Verify: dragging a stop updates the overlay on the next redraw via LUT upload, not a present rebuild.
- [x] GUI verify: two Surface vizs, different ramps → different colors. Toggle between them → visual palette shift. Drag feels interactive (user: Heat drag is responsive; LUT optimization worked).

### P3 — Preset ramps

The ColorRamp is already the colormap (P0–P2). P3 only fills it. The Color row is **ramp + presets**, not Heat/RGB/Random as algorithms.

- [x] Default Heat 5-stop is seeded when the ramp tree is first created (P0).
- [x] Always show `template_color_ramp` for Surface/Markers (GPU on) — not gated on Style = Heat.
- [x] Preset buttons: **Heat**, **RGB**, **Monochrome (BnW)**. Each writes stops into the existing ColorRamp. Does not change Display. Does not add Style enum values.
- [x] Applying a preset does NOT lock the ramp — user can tweak any stop after.

### P4 — Closeout

- [x] All tests green.
- [ ] GUI: 3 Surface vizs on different attrs, each with distinct ramps, toggling shows instant palette shift; dragging a stop is interactive.
- [ ] Commit only if asked.

---

## Out of scope

- New Style enum values for palettes. Palettes are ColorRamp presets (Heat / RGB / BnW), not Styles.
- Keeping Heat/RGB/Random as mutually exclusive *algorithms* that hide the ramp. That is the leftover enum; P3 replaces that Color-row behavior with ramp + presets.
- Ramp on Arrows (they use uniform tint, not a ramp).
- Ramp on Tags (they show text values, not color).
- Wiring the GPU-off materials GN path to the off-engine ramp (materials path may keep engine `.copy()`).
- Extra disk serialization beyond the ramp node tree Blender already saves.
- **ID-like / enum color** (hash per value, not a ramp gradient) — [`../005_categorical_hash/POR.md`](../005_categorical_hash/POR.md). P3 sending INT through the LUT is the bug 005 fixes. Semantic legend (ramp override) stays future; `ensure_viz_ramp` stays.

---

## Current code (read first)

| File | Relevant state |
|------|----------------|
| `attrviz/gpu_color.py` | `heat_colors` (hardcoded 5-stop), `values_to_colors` (style dispatch). **Add `ramp_colors` / `extract_ramp` (CPU fallback).** |
| `attrviz/gpu_overlay.py` | `_refresh_surface_from_sample`, `_refresh_markers` call `gpu_color.values_to_colors` + `_build_batch`. **Heat: LUT shader; do not rebuild batch on ramp drag.** |
| `attrviz/node_builder.py` | `ensure_viz_group()` builds the GN tree with a `ShaderNodeValToRGB`. **Add `ensure_viz_ramp(obj)` off-engine.** |
| `attrviz/__init__.py` | `_assign_viz_engine`: GPU-on → shared; GPU-off → `.copy()`. Panel: `template_color_ramp` guarded by `not _gpu_overlay_on()`. **Keep shared engine. P0: create ramp tree. P2: point the widget at it.** |
| `tests/test_gpu_sample.py` | Existing surface/markers tests — keep green. **P0: shared engine + distinct ramps.** |

---

## Design constraints

| Constraint | Note |
|------------|------|
| Blender API | `ShaderNodeValToRGB.color_ramp.elements` is the standard ramp access. `template_color_ramp(node, "color_ramp")` renders the UI widget. |
| Interactivity | Dragging a ColorRamp stop must not rebuild the overlay batch. LUT + uniforms only. Same class as a cache hit, not a present miss. |
| Depsgraph | Editing the ramp must not dirty the engine GN tree. Ramp tree is never a modifier. |
| Performance | Sample/upload is per-sample-miss. Ramp eval in the viewport is a 256-texel upload. CPU `ramp_colors` is for tests / background only. |
| Per-viz state | The ramp MUST be per-visualizer. Two vizs on the same attribute with different ramps must show different colors simultaneously (e.g. split view). |
| Backward compat | Existing scenes with the shared engine keep it. `ensure_viz_ramp` creates a missing per-viz tree on first access (default Heat stops). |
| GPU overlay is THE path | No special-casing for materials/GN path. |

---

## Acceptance

1. **Per-viz ramp.** Each visualizer has its own editable ColorRamp off the engine tree. Editing one does not affect others. GPU-on vizs still share `ensure_viz_group()`.
2. **GPU overlay uses it.** Surface/Markers scalar colormap reads the per-viz ColorRamp via the LUT shader (CPU `ramp_colors` in tests / background). Heat is only the default stops.
3. **Interactive drag.** Dragging a ColorRamp stop updates the viewport without an `overlay.present.*` / `overlay.build_batch` spike and without engine GN evaluation.
4. **Panel UI.** `template_color_ramp` is visible and functional for Surface/Markers when GPU overlay is on, bound to the off-engine node. Always editable.
5. **Visual distinction.** Two Surface vizs with different ramps produce different viewport colors when toggled.
6. **Presets.** Heat / RGB / Monochrome (BnW) write stops into that ramp. They do not lock it. They are not Displays and not Style algorithms.
7. **Tests.** All existing tests green. New unit tests for `ramp_colors` (2-stop, 5-stop, edge cases) and P0 shared-engine / distinct-ramp checks.
8. **Range.** Range Min/Max (and Auto Range result) update as uniforms on the ramp LUT path; they do not rebuild the mesh batch.

---

## Validation approach

**Headless (every slice):**

```bash
blender --background --factory-startup --python-exit-code 1 \
  --python tests/headless_test.py

blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_gpu_sample.py
```

**Unit tests (P1):** `ramp_colors` with known stops produces expected gradient values.

**GUI (P2–P4):**

```text
rsync -a --delete attrviz/ \
  ~/Library/Application\ Support/Blender/5.0/extensions/user_default/attrviz/
```

1. Create 3 Surface vizs on different attributes (position.x, position.y, position.z).
2. Each is Surface. The ColorRamp is the colormap. Edit each ramp to a distinct palette — or apply Heat / RGB / BnW presets, then tweak.
3. Toggle between them — viewport color shifts instantly.
4. Drag a stop — viewport follows without hitch; other vizs' ramps unchanged.
5. Applying a preset fills the ramp; the user can still drag stops. Presets are not modes that hide the widget.
