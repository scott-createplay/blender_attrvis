# GPU overlay backlog

Watch collection (`attrvis`) landed in **0.5.10**. Tags 7c text is BLF (atlas deferred). Strangler / DistLook stay here.

**Active overlay work is 002** (kind tag, Arrows Metal pack, geometric view cull): [`../002_overlay_kinds/POR.md`](../002_overlay_kinds/POR.md). Tags full-frame spread Cap is replaced there. Do not add more Display-leaf cull here.

## Scoping UX gap

**Landed (0.5.10):** Scene-level watch collection `attrvis`. Membership is the scope. RMB **AttrViz → Visualize Attribute** (create viz; selection linked) / **Edit → Add objects / Remove objects**. Panel root shows coverage. Sampler is still Target ∪ Scope; GUI vizs set `Scope = attrvis`.

**API override:** `add_visualizer(target=, scope=)` unchanged (tests, city `--viz` per-collection scopes).

- [x] Scene `attrvis` collection (distinct from `Visualizers`); first GUI viz / Add objects creates it.
- [x] Multi-select: new viz **or** Add objects links all selected MESH (skip viz carriers).
- [x] Remove objects unlinks from `attrvis` only (does not delete).
- [x] Coverage readout on panel root (count + capped names); empty hint.
- [x] RMB tree: AttrViz → Visualize Attribute / Edit → Add · Remove.
- [ ] GUI confirm (rsync → Blender 5.0 extensions).
- [ ] Viewport pick selects the source, not the viz carrier — [`../004_viewport_source_select/POR.md`](../004_viewport_source_select/POR.md) (parked).
- [ ] Point-only inputs (POINTCLOUD / vert-only mesh) — [`../006_points_input/POR.md`](../006_points_input/POR.md) (**P4 next**: mute native clouds while Markers on; `006-points-input`).
- [ ] Optional (larger, **not** watch-collection): attribute-discovery mode — gather meshes that own the named attr. Separate product axis from Target∪Scope; don’t break the watch model.

## Surface Solid mute (z-fight) — done (0.5.7)

Identity Surface + Workbench solid → coplanar shred. Fix: AttrViz-owned
`display_type` → `WIRE` for meshes in the active GPU Surface **Target∪Scope**
watch set (same as sampling). Synced via `suppress_gn_carriers` / depsgraph.
No attr discovery.

## Optional / escalate-only

- [ ] Tags: optional Density pre-cull before Cap (Markers spirit) — product sugar, not required for draw perf.
- [ ] Tags: optional “nearest” Cap mode restored as non-default. (Default Cap is 002 frame-center, not 7c spread.)
- [ ] Tags / overlay: depth or ID-buffer visibility (not free; only if facing + 002 view cull fail with evidence).
- [ ] Arrows: remove soup fallback in `--background` if CreateInfo becomes available without a window.
- [ ] DistLook live smoke, probe thinning, README roadmap polish (Phase 7 leftovers).
- [ ] Strangler Phase 2 — [`POR_strangle_gn_backbone.md`](POR_strangle_gn_backbone.md).
