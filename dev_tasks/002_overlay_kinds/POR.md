# POR: Overlay kinds — Surface vs Geometric

**Parent / history:** [`../001_gpu_overlay/POR.md`](../001_gpu_overlay/POR.md) (frozen Stage B).  
**Pickup:** [`AGENT_ONBOARDING.md`](AGENT_ONBOARDING.md)

AttrViz **0.5.10**. Blender **5.0.1+**.

---

## Why this POR exists

001 shipped GPU ink as four Display leaves: Markers, Surface, Arrows, Tags. Each grew its own sample / cap / upload path. That does not scale, and it just crashed the app.

### The crash (2026-08-12)

On the dense city (`examples/attrviz_city.blend`, ~1171 meshes / ~816k verts):

1. Visualize `flow` as **Surface** (works — identity mesh tris).
2. Switch Type to **Arrows**.
3. Blender quits immediately. No Python traceback.

**Report:** `~/Library/Logs/DiagnosticReports/Blender-2026-08-12-193420.ips`  
Blender 5.0.1, `SIGABRT` / Abort trap 6, main thread, viewport draw (`cb_region_draw` → `pygpu_texture__tp_new`).

**Metal:**

```text
-[MTLTextureDescriptorInternal validateWithDevice:]:1416: failed assertion
MTLTextureDescriptor has width (19496) greater than the maximum allowed size of 16384.
```

Reproduced in-process: `GPUTexture(size=(19496, 1), format='RGBA32F')` → exit 134. Ten city hulls sit above that limit (`Building_7_7` and siblings = **19496** verts). Overlay sample cap is **50000**, also above 16384.

**Code:** `attrviz/gpu_overlay.py` `_float_tex_rgba` uploads each arrow as one pixel of an **N×1** texture. The instanced shader does `texelFetch(..., ivec2(gl_InstanceID, 0), 0)`. Surface never hits this path (vertex batch). `--background` never hits it (CreateInfo missing → soup). The `try/except` around `_refresh_arrows` cannot catch a C++ `abort`.

Tags use the same N×1 upload for cards (`tags_draw._float_tex_rgba`). Safe today only because Tag Cap max is 10000.

### The direction

Two problems, one cut:

| Problem | Not solved by | Solved by |
|---------|----------------|-----------|
| Process dies | View cull alone (a 19k-vert hull in the fovea still uploads 19496×1) | Geometric **upload pack** (2D texture, never a dimension > 16384) + hard cap |
| 50k random arrows / Tags spread across the whole shot | Packing alone | Geometric **view cull** before upload: frustum, then frame-center budget |

Policy belongs on a **kind tag**, not on Display. Display only presents a kept sample. A new geometric Display must not grow a fifth sampler or a sixth cap.

001 leftovers that are *symptoms of this gap* (Arrows abort, Tags Cap policy, Markers stride) fold into this POR. 001 GUI confirms (watch collection, Surface identity, Tags-as-shipped) stay 001 closeout — do not block P0.

---

## Locked product

### Kind tag (not a class hierarchy)

`Display` stays `Markers | Surface | Arrows | Tags`. That picks the **presenter**.

`Kind` is two values:

| Kind | Displays | Owns |
|------|----------|------|
| **surface** | Surface | Identity evaluated mesh; false-color; solid mute (`WIRE`). No Density, no frustum-cap, no “which N.” |
| **geometric** | Markers, Arrows, Tags | Watch-set sample, Density, view cull, cap, safe upload. Then present. |

Dispatch is a tag (`kind(display) -> "surface" | "geometric"`). Home: **`attrviz/overlay_kind.py`** (`kind()`, `GEOMETRIC_DISPLAYS`, `SURFACE_DISPLAYS`; later the shared pack + `frame_dist` keep). Overlay and Tags import that module. Frozenset / enum / `isinstance` — same rule: **policy keys off kind, not Display.** Do not add leaf cull/upload inside `_refresh_arrows` / `_refresh_markers` / `_labels_for_md`.

Tags may stay `POST_PIXEL` (text is 2D). They still consume the geometric sample + cull. Two handlers, one policy.

### Geometric view cull (unified heuristic)

Runs on the CPU, **after** we know the 3D region, **before** any instance/point upload.

1. **L0** — world samples from the watch set (`attrvis` if it exists, else Target∪Scope). **Density** thins here (view-agnostic, cacheable). Do **not** stride-to-cap here.
2. **Facing** — Tags chrome only (optional). Backfaces never take budget.
3. **Project** — `region` + `region_data.perspective_matrix`. Drop off-screen (small pad OK).
4. **Budget** — if `n_in_view ≤ cap`, keep all (including corners). If over cap, keep the `cap` samples with smallest **frame distance**.
5. **Hard stop** — never upload more than `cap`. Pack so that set cannot abort Metal.

**Frame distance** (Chebyshev / the rectangle, not a circle):

```text
nx = (sx - rw/2) / (rw/2)     # -1…1 at left/right edge
ny = (sy - rh/2) / (rh/2)     # -1…1 at top/bottom
frame_dist = max(|nx|, |ny|)  # 0 = view center, 1 = frame edge, >1 off-screen
```

Equivalent: sort in-view samples by `frame_dist`, take the first `cap`. `keep_t` is `frame_dist` of the last kept sample — it tracks how over-budget the view is. Wide city shot → only the middle of the window. Tight on a doorway → almost everything is already near center; keep them until cap bites.

**Overfull fovea:** zoomed on a dense wall, shrink cannot save you (`n ≫ cap` even at `frame_dist ≈ 0`). Then bin **inside the keep rect** (anti-clump), not across the whole view. That replaces Tags’ current default (spread bins on the full frame).

**Cap 0** (Tags): draw nothing. **Density 0**: empty geometric sample.

Cap *value* may still differ per Display for now (hidden overlay 50k vs Tag Cap socket). The **ranker** is shared. Do not invent a second Arrows Cap widget in this POR unless the user asks.

Not nearest-to-camera. A close sample in the corner still loses to one at the crosshair.

### Geometric upload (Metal-safe)

Do not upload `GPUTexture(size=(n, 1))` when `n` can exceed **16384**.

Pack instance rows as a 2D `RGBA32F` texture: `W = min(n, 16384)`, `H = ceil(n / W)`, fetch `ivec2(id % W, id / W)` (`textureSize` or a push constant for `W`). One origin tex + one dir tex + one `draw_instanced` is enough for the 50k cap (16384×4). Same helper for Tags cards.

**Hard rule:** never call `GPUTexture` with a dimension > 16384. That assert is uncatchable.

Soup fallback stays for `--background` / missing CreateInfo (no region, no Metal).

### Surface (unchanged class)

`build_surface_tris` identity pack. No Density, no view-cap. Mute watched solids while GPU Surface is on. Do not frustum-thin the mesh.

### Cache

- **L0** (world positions/values): view-agnostic. Key = watch fingerprint + attr/domain + Density/seed. **Cap is not part of this key.**
- **Upload / present** (instance textures, point batches, tag cards): view-dependent. Rebuild when the region / perspective matrix changes. Length / Arrow Color / Tag Size stay cheap uniforms or presenter-only.
- `--background` / `region is None`: skip the view pass; do not abort; tests stay on soup / unculled L0.

---

## Interleave with 001

001 is **frozen** as the history of how we got pixels. This POR does not re-author probe, panel_prop, watch collection, or identity Surface.

Remaining 001 overlay work **is** this POR’s first phases (symptoms of missing kinds). Do not run a second “finish 001 Displays” stream in parallel.

| 001 leftover | Lands here |
|--------------|------------|
| Arrows Metal abort / N×1 textures | **P0** (pack) — first slice, do not wait for a full kind refactor |
| Arrows/Markers stride cap in the sampler | **P2** (geometric view cull) |
| Tags screen-bin *spread* as default Cap | **P2–P3** (same ranker; Tags presenter only) |
| Tags N×1 card texture | **P0** helper shared |
| Arrows instancing GUI confirm | **P0 + P5** (must not quit; cones still look like cones) |
| Surface identity / mute | Already 001. **P4** only: prove Surface did not pick up geometric cull |
| Watch-collection GUI confirm | **001 closeout**, not this POR |
| Tags glyph atlas | **001 backlog**, not this POR |
| Strangler / attribute discovery / DistLook | **001 backlog** / [`POR_strangle_gn_backbone.md`](../001_gpu_overlay/POR_strangle_gn_backbone.md) |

**Sequencing rule:** P0 (stop dying) may land with a 10-line `kind()` and a shared pack helper. Do not rewrite Tags, Markers, and Arrows in one PR in the name of the tag. Do not skip the tag and keep putting pack/cull in `_refresh_arrows` only.

---

## Progressive plan

Tick as you go. **Start at P0.** Do not merge P0–P3 in one pass.

### P0 — Crash stop (geometric upload pack)

- [ ] Shared pack helper (overlay + tags): 2D `RGBA32F`, `W = min(n, 16384)`, `H = ceil(n / W)`, refuse any dimension > 16384.
- [ ] Arrows shader `texelFetch` uses `ivec2(id % W, id / W)`.
- [ ] Tags cards call the same helper (even while Cap ≤ 10000).
- [ ] Tests: pack `W,H` for `n ∈ {1, 16384, 16385, 19496, 50000}` all dims ≤ 16384.
- [ ] GUI: `Building_7_7` `flow` Surface → Arrows does not quit; cube cones still 4-side.
- [ ] `--background` soup still green.

**Hard stop:** if CreateInfo cannot fetch 2D instance data, escalate — do not “fix” by capping at 16384 as the product policy.

### P1 — Kind tag

- [ ] `attrviz/overlay_kind.py`: `kind()`, `GEOMETRIC_DISPLAYS`, `SURFACE_DISPLAYS`.
- [ ] Overlay draw split and Tags entry use `kind()`, not a growing Display if-ladder.
- [ ] Unit tests on the mapping.

No behavior change required if P0 already shipped pack.

### P2 — Geometric view cull

- [ ] Shared project + `frame_dist` + cap in `overlay_kind` (or equivalent), used before upload.
- [ ] Remove `positions[::step]` as the geometric budget. L0 = Density only. Cap **not** in `_sample_key`.
- [ ] Present/upload cache includes a view signature (region size + perspective).
- [ ] Headless: `n ≤ cap` keep all in-view; `n > cap` drop high `frame_dist`; off-screen skipped; no `region` → skip view pass.
- [ ] GUI: city `flow` Arrows — no quit; window edges thin when over cap; framed doorway keeps arrows.

### P3 — Presenters consume the kept set

- [ ] Markers / Arrows / Tags draw **only** geometric kept indices.
- [ ] Tags: drop full-frame spread as default; facing + Cap 0 + decimals stay chrome.
- [ ] Overfull fovea → bin inside keep rect.
- [ ] Tag Cap 0 empty; Facing on/off; Markers Density 0 empty; Arrows non-vector empty.
- [ ] GUI: Tags on a busy attr concentrate toward view center when over Cap (intentional vs 7c).

### P4 — Surface stays surface

- [ ] No view-cap on `build_surface_tris`. Mute still applies.
- [ ] Surface → Arrows on a 19k hull uses geometric P0–P2, not a Surface path.
- [ ] Existing identity tri-count checks in `test_gpu_sample.py` still pass.

### P5 — Closeout

- [ ] POR checkboxes; rsync for GUI verify.
- [ ] Version bump / harness JSON only if the user wants a release.
- [ ] Commit only if asked.

---

## Out of scope

- Attribute discovery, DistLook cook, strangler Phase 2.
- Watch-collection UX changes, per-viz Target/Scope pickers, `bl_parent_id` / UIList.
- Tags glyph atlas; removing BLF.
- Removing soup fallback; compiled Overlay engine.
- New Arrows Cap socket (unless asked).
- Python ABC / wrapping `bpy.types.Object`. Kind is a tag.
- Capping Arrows at 16384 as the UX “fix.”
- Frustum-culling Surface.

---

## Acceptance

1. **Kind is real.** `kind(Display)` is the only switch for sample / view-cull / upload policy. Display files only present. A fifth geometric Display would not need a new sampler.
2. **No Metal abort.** Geometric instance textures never request a dimension > 16384. City `flow` Surface → Arrows on a 19k-vert hull does not quit. Overlay cap 50000 is pack-legal.
3. **Cull before upload.** Geometric uploads are the post-cull set. Frustum + frame-center heuristic; under cap keep all in-view; over cap drop from the frame edge inward.
4. **Tags share it.** Same ranker as Arrows/Markers. Cap 0 still empty. Spread-across-the-whole-view is no longer the default.
5. **Surface untouched as a class.** Identity pack + mute; no Density/cap.
6. **Tests.** `tests/headless_test.py` and `tests/test_gpu_sample.py` green. New tests for `kind()`, pack sizes, and the frame-distance keep/drop cases (no GUI required for those).
7. **Background.** `--background` does not abort; soup / skip-view-pass as today.
8. **Agent pickup.** A new chat can start from [`AGENT_ONBOARDING.md`](AGENT_ONBOARDING.md) without this conversation.

---

## Validation approach

**Headless (every slice):**

```bash
blender --background --factory-startup --python-exit-code 1 \
  --python tests/headless_test.py

blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_gpu_sample.py
```

Add tests next to those (or `tests/test_overlay_kinds.py`) for: `kind()` map; 2D pack `W,H` for n in `{1, 16384, 16385, 19496, 50000}` all dims ≤ 16384; frame_dist keep-all vs drop-edges.

**Pack / crash (GUI GPU context — P0 gate):**

A short `--python` timer that builds `GPUTexture` with n=19496 via the shared helper must **not** SIGABRT. Direct `size=(19496, 1)` is the known abort; the helper must not do that.

**Product GUI (P2–P5, rsync then Blender 5.0 extension):**

```text
rsync -a --delete attrviz/ \
  ~/Library/Application Support/Blender/5.0/extensions/user_default/attrviz/
```

1. Open `examples/attrviz_city.blend` (rebuild `--dense` if missing). GPU Overlay on.
2. Select `Building_7_7` (19496 verts). AttrViz → Visualize Attribute → Point, attr `flow`, Type **Surface**. Confirm color on the hull.
3. Switch Type to **Arrows**. Blender stays up. Cones on the hull.
4. Frame a small region of the hull, then view the whole city with many buildings in `attrvis`. Over cap: corners/edge of the *window* thin first, not a random mesh stride.
5. Tags on a busy attr: Cap 0 clears; over Cap concentrates toward view center; Facing still works.
6. Surface on buildings still matches the mesh (no missing faces from a geometric cull).

**Harness (optional, `--background` = soup, not the instanced hot path):**

```bash
blender --background --python-exit-code 1 \
  --python dev_tasks/001_gpu_overlay/tests/profile_overlay_harness.py -- \
  --blend examples/attrviz_test_cube.blend \
  --attr flow --displays Arrows --max-targets 1 --warm 3
```

---

## Current code (read first)

| File | What is wrong / what to reuse |
|------|-------------------------------|
| `attrviz/overlay_kind.py` | **Create here.** `kind()`, display sets, later pack + frame_dist keep |
| `attrviz/gpu_overlay.py` | `_float_tex_rgba` N×1; `_sample_key` includes `cap`; `_refresh_arrows` / `_refresh_markers` leaf present+cull; draw already has `region` / `region_data` |
| `attrviz/gpu_sample.py` | `sample_visualizer_targets` Density **and** `::step` cap; `build_surface_tris` identity (keep) |
| `attrviz/tags_draw.py` | Private sample cache; `screen_bin_select` full-frame spread; duplicate N×1 upload |
| `attrviz/node_builder.py` | Display enum; Tag Cap; Density |
| `tests/test_gpu_sample.py` | Arrows honesty / soup oracle — keep green |
| `examples/build_attr_city_scene.py` | Dense city; `flow` on hulls; `examples/attrviz_city.blend` |

Watch collection and panel: 001, do not reopen.

---

## Design constraints

| Constraint | Note |
|------------|------|
| Blender | 5.0.1+; Metal 2D max dimension 16384 on this machine (treat as the portable cap) |
| Install | Repo ≠ extension — rsync for GUI |
| Hot path | NumPy cull then one upload; no per-sample `gpu.imm` |
| Tests | Geometry-only tests cannot catch Metal abort; pack shape tests + one GUI GPU create |
| UX | Existing Visualizers / Display menu; no second registry |
| License | GPL-3.0-or-later in `attrviz/` |
