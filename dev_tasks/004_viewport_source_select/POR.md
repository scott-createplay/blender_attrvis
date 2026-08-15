# POR: Viewport pick selects the source mesh

**Parent / history:** [`../001_gpu_overlay/AGENT_ONBOARD_SCOPE_PANEL.md`](../001_gpu_overlay/AGENT_ONBOARD_SCOPE_PANEL.md) (watch collection landed). Surface mute already says the overlay *is* the mesh.  
**Pickup:** [`AGENT_ONBOARDING.md`](AGENT_ONBOARDING.md)  
**Parked while:** [`../003_per_viz_colorramp/POR.md`](../003_per_viz_colorramp/POR.md) closeout / Surface follow-ups. Do not start unless asked.

AttrViz **0.6.x**. Blender **5.0.1+**.

---

## Why this POR exists

A visualizer is a separate OBJECT in `Visualizers` (registry). The GPU overlay (or GN carrier, GPU off) is what the user *sees* on the watched mesh. As far as the user is concerned, **that drawing is the original mesh**. Selecting it in the viewport should mean selecting the source (`Alley_1` in `attrvis`) and its attributes.

Today the RMB menu keys off `context.active_object`. If that is the viz carrier, Visualize Attribute is `poll`ed off (no attribute list) and Edit → Add/Remove objects is grey (candidates skip viz carriers). The attributes never left `Alley_1`. The menu asked the wrong object.

### Repro (sample_scene_3, 2026-08-14)

Split 3D views. GPU Overlay on. `Alley_1` in `attrvis`. Create one Surface viz (`dist_sign_val · Point · Surface`). Second RMB → AttrViz:

- **Visualize Attribute** gone / disabled.
- **Edit** only has Add objects / Remove objects, both grey.

Two viewports are a red herring. They share one view layer and one active object. They make the trap easier to hit; they are not a separate code path.

### Why the second pass fails

1. **Visualize Attribute** lists attributes on `context.active_object`. `poll`: active exists and `not is_visualizer(active)`. Viz carrier → no list.
2. **Edit** is watch-set membership only (`attrvis` link/unlink). It never lists attributes and never shows the ColorRamp.
3. **RMB does not select** (left-click select). The menu uses whatever is already active. Looking at the colored building and right-clicking it does not retarget to `Alley_1`.
4. **GPU Surface mute** sets the source to `BOUNDS` so the overlay is the thing you look at (`gpu_overlay._mute_target_solid`: “The GPU overlay IS the mesh from the user's perspective”). Selection / menus never got that memo.
5. GPU-off: the colored mesh *is* the viz object's evaluated geometry occupying the source's space — clicking it selects the carrier. GPU-on: overlay ink is not in the select ray; empty viz origins and outliner clicks still leave the carrier active.

ColorRamp (003) lives on the N-panel viz body. Out of scope here.

---

## Locked product

**Viewport:** picking a viz carrier selects the source mesh(es). The user is selecting the mesh they see.

**Outliner:** still selects viz objects. They are the registry (`Visualizers` collection). Do not dissolve them. Do not `hide_select` in a way that blocks the outliner.

### Chosen mechanism (P0)

| Piece | Choice |
|-------|--------|
| Viewport unpickable | `hide_select = True` on viz carriers. Viewport cannot pick them. Outliner still can. Click on the drawing hits the source behind it (BOUNDS when GPU Surface is on; original under the GN copy when GPU off). |
| After create | `add_visualizer` / `ATTRVIZ_OT_add` must **restore** the watched mesh(es) as selected + active. Do not leave the new viz as active. |
| Menu | Still lists attributes of `active_object`. After P0, viewport + second RMB should see the source. |

`Object.hide_select` is viewport-only. That is the outliner split. Do not invent a select-callback until P0 is proven insufficient.

### Rejected / fallback

| Option | Why not P0 |
|--------|------------|
| Redirect callback (viz stays pickable; depsgraph/msgbus then selects source) | Needs “was this click in VIEW_3D vs OUTLINER?” (mouse-over-area). Re-entry guard. **Does not run on RMB** (no new pick). Use only if `hide_select` still leaves the carrier as the hit. |
| Menu remap only (if active is viz, list watch-set attrs) | Small, but Properties / Spreadsheet / X still operate on the empty viz. Incomplete as the only fix. Optional **P1** for: outliner selected the viz, then RMB in the 3D view without clicking the source. |
| Custom overlay picking (ray/depth on GPU ink → select source) | Fights Blender selection; split views, overlap, depth. Only if BOUNDS + `hide_select` still miss clicks. |
| Dissolve viz objects | Conflicts with POR 005: a visualizer *is* an object in `Visualizers`. |

### N meshes in `attrvis` (decide at P1 if needed)

GUI vizs have Target unset, Scope = `attrvis`.

| n | Restore / pick |
|---|----------------|
| 1 | That mesh. The sample_scene_3 case. |
| >1 | **Default:** select all watch meshes, active = the last non-viz that was active (else first). Union-of-names in the attribute menu is a later product call, not P0. |

---

## What does NOT change

- Watch collection model (`attrvis` vs `Visualizers`). Edit → Add/Remove objects stays membership, not a second attribute list.
- ColorRamp / presets (003). Not on this RMB menu.
- Kind dispatch, Surface mute, GPU overlay as THE draw path.
- `add_visualizer(target=, scope=)` API for tests / city `--viz`.
- Attribute discovery (gather meshes by attr name) — still a different axis.

---

## Progressive plan

### P0 — Viewport identity

- [ ] `hide_select = True` on viz create (`_ensure_display_only_flags` or equivalent) and migrate.
- [ ] GUI add-viz restores source selection: watched candidates stay selected; active is a source mesh, not the new viz.
- [ ] Existing tests green (selection restore must not break headless add_visualizer that never had a mesh selected).
- [ ] GUI: sample_scene_3 — viz `dist_sign_val`, left-click the colored building, RMB → Visualize Attribute lists `Alley_1` attrs again. Outliner click on the viz object still selects the viz.

### P1 — Leftover menu hole (only if P0 GUI still fails)

Outliner-selected viz + RMB in the 3D view (RMB does not pick). Options, pick one if needed:

- [ ] Menu: if active is a viz, list attributes from the watch set (do not `poll` off Visualize Attribute), **or**
- [ ] Viewport-only redirect: if mouse over VIEW_3D and active is viz, retarget to source (re-entry guard). Do not retarget when mouse over OUTLINER.

### P2 — N-mesh restore policy

- [ ] Lock and test the >1 watch-mesh restore rule from Locked product.

### P3 — Closeout

- [ ] Tests green. GUI: one-mesh + outliner-still-selects-viz. Commit only if asked.

---

## Current code (read first)

| File | Relevant state |
|------|----------------|
| `attrviz/__init__.py` | `ATTRVIZ_MT_visualize.poll` requires `not is_visualizer(active)`. `_draw_domain_menu` / `attributes_by_domain(active)`. `ATTRVIZ_OT_add.poll` same. `_watch_candidates` skips viz carriers. `add_visualizer` does **not** set `view_layer.objects.active` (Blender / later clicks still leave the viz active). `_ensure_display_only_flags`: `hide_render`, not `hide_select`. |
| `attrviz/gpu_overlay.py` | `_mute_target_solid`: source → `BOUNDS` (or `WIRE`). `_suppress_gn_carriers`: GPU-on hides GN carrier `show_viewport`. Overlay draw is not in the select ray. |
| `attrviz/gpu_sample.py` | `watch_meshes_for_visualizer` / `scene_watch_collection`. |
| `tests/test_watch_collection.py` | Watch add/remove / mute. Add selection-identity checks at P0. |

---

## Design constraints

| Constraint | Note |
|------------|------|
| One active object | Shared across split 3D views in the same window. Not per-viewport. |
| RMB ≠ select | Left-click select. Menu context is current active, not “object under cursor.” |
| `hide_select` | Viewport only. Outliner can still activate the viz. |
| Depsgraph | A select-redirect handler must guard re-entry. Prefer not to write one in P0. |
| Registry | Viz objects stay in `Visualizers`. Enabled / N-panel still address the viz. |

---

## Acceptance

1. **Viewport.** Clicking the visualized drawing selects the source mesh, not the viz carrier.
2. **Second RMB.** After creating a viz, Visualize Attribute still lists the source's attributes without hunting the outliner for `Alley_1`.
3. **Outliner.** Clicking a viz in `Visualizers` still selects that viz object.
4. **Edit.** Add/Remove objects stay watch membership. Grey is correct when the selection is not a non-viz mesh.
5. **No dissolve.** Viz objects remain the registry.
6. **Tests.** Existing tests green. New checks: `hide_select` on viz; GUI add restores a source as active when candidates existed.

---

## Validation

```bash
blender --background --factory-startup --python-exit-code 1 \
  --python tests/headless_test.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_gpu_sample.py
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_watch_collection.py
```

**GUI (sample_scene_3 or cube):**

```text
rsync -a --delete attrviz/ \
  ~/Library/Application\ Support/Blender/5.0/extensions/user_default/attrviz/
```

1. Visualize one attr (Surface). Overlay on.
2. Left-click the colored mesh → source is active (bright), not `Viz · …`.
3. RMB → AttrViz → Visualize Attribute still lists Point/Face/… attrs.
4. Outliner → `Visualizers` → click the viz → viz is active; N-panel still addresses it.
5. Split views must not be required; if used, they still share one active.
