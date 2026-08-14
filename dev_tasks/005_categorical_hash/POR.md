# POR: Categorical hash color (ID-like attributes)

**Parent / history:** [`../003_per_viz_colorramp/POR.md`](../003_per_viz_colorramp/POR.md) (ramp is the scalar colormap).  
**Pickup:** [`AGENT_ONBOARDING.md`](AGENT_ONBOARDING.md)

AttrViz **0.6.x**. Blender **5.0.1+**.

---

## Why this POR exists

003 made Surface/Markers color a ColorRamp. That is correct for **scalars** (neighboring values look neighboring). It is wrong for **IDs**: `face_id` 5 and 6 must not look like two temperatures.

P3 currently sends `INT` / `BOOLEAN` / `INT8` through the same LUT (`mix` on a normalized scalar). Adjacent ids become a gradient.

The leftover Style **Random** (`hash_colors` / GN hash) already knew this. The GPU overlay no longer uses it.

---

## Locked product

This is a **mapper**, not a Display. Surface/Markers stay the carrier.

| Attr | Color |
|------|--------|
| float / vector-length | ColorRamp LUT (003) |
| int / bool / int8 | Stable **hash per value**. Same id → same color. Neighbors look unrelated. Seed reshuffles. |
| later: semantic legend | Ramp / swatch lookup **overrides** hash. Not this POR. |

The user does not manually map ids. Hash is automatic.

**Do not interpolate ids** in the LUT shader. Categorical skips `heat_lut`. Face-domain IDs share a color on all three corners of a tri (no seam). Point-domain INT on Surface may still blend vertex *colors* — same as old Random; not a P0 blocker.

Keep `ensure_viz_ramp` on every viz. Hide the ramp **in the panel** for categorical dtypes; do not delete the tree. Dispatch is one function (`color_mapper(dtype) → "hash" | "ramp"`) so a later `if legend: return "ramp"` is a one-liner. Do not bake “INT can never read the ramp.”

Do **not** add a Display, a Style enum value, or a Random *preset that fills the ramp*. GPU-off materials path already hashes INT via leftover Style Random — leave it.

---

## Progressive plan

### P0 — Overlay hash for IDs

- [x] `gpu_color.color_mapper(dtype)` → `"hash"` | `"ramp"`. Hash dtypes: `INT`, `BOOLEAN`, `INT8`.
- [x] Surface/Markers overlay: hash path uses `hash_colors` + existing color batch. **Not** `heat_lut` / `ramp_colors`.
- [x] Float Surface still LUT / CPU ramp (003).
Seed scrub on GPU-on id attrs must not resample or depsgraph-evaluate. Overlay Seed is `Object.attrviz_seed` (redraw only). L0 sample key ignores Seed on Surface. Viewport hashes in a shader (seed uniform); `--background` still uses CPU `hash_colors`.
- [x] Unit tests: same id → same rgba; seed changes palette; nearby ints not ramp-similar; Face `face_id` Surface is not `heat_lut`.

### P1 — Panel

- [x] GPU-on + categorical: hide Heat/RGB/BnW, ColorRamp, Auto Range. Show Seed + “Hash color per id”.
- [x] GPU-on + float: unchanged ramp row.
- [x] Ramp tree still created (future legend).

### P2 — GUI / closeout

- [ ] Face id as Surface: quilt, not a heat gradient. Seed reshuffles. Switch to a float attr → ramp row returns.
- [x] Tests green. Commit only if asked.

---

## Out of scope

- Stepped ramp / semantic legend (door is `color_mapper`).
- STRING → color.
- 004 viewport pick.
- New Display. Random as a ColorRamp preset.
- Interpolated-id shader (flat `round(id)` hash) unless Face-id GUI is wrong.

---

## Current code (read first)

| File | Relevant state |
|------|----------------|
| `attrviz/gpu_color.py` | `hash_colors(ids, seed)`. `values_to_colors` still hashes INT (CPU / GPU-off). Overlay P3 bypasses that for LUT. **Add `color_mapper`.** |
| `attrviz/gpu_overlay.py` | `_dtype_heat_lut` allows INT. `_refresh_surface_from_sample` / `_refresh_markers` take LUT when stops exist. **Skip LUT when mapper is hash.** |
| `attrviz/__init__.py` | GPU-on Color row is always ramp presets. **P1: categorical → Seed.** `CATEGORICAL` already used for a subdiv hint. |
| `tests/test_gpu_sample.py` | P3 ramp tests. **Add hash / face_id Surface checks.** |
| `tests/headless_test.py` | V12 Face Random (GPU-off) — keep green. |

---

## Acceptance

1. ID-like Surface/Markers: stable hash per value, not a ramp gradient.
2. Scalar Surface/Markers: ColorRamp unchanged (003).
3. Seed reshuffles hash; same id stays consistent for a given seed.
4. Panel: categorical shows Seed, not ramp presets. Float still shows the ramp.
5. Ramp tree still exists on the viz (future legend).
6. Tests green.

---

## Validation

```bash
blender --background --factory-startup --python-exit-code 1 \
  --python tests/headless_test.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_gpu_sample.py
```

**GUI:** rsync `attrviz/` → Blender 5.0 extensions. Face-id Surface = quilt. Seed. Toggle a float attr → ramp.

**Sibling (parked):** point-only inputs — [`../006_points_input/POR.md`](../006_points_input/POR.md). Hash/ramp already work on Markers; 006 feeds them point-cloud positions.
