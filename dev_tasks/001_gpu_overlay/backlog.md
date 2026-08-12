# GPU overlay backlog

Small follow-ons deferred from Phase 7 Surface identity / Solid depth work.

## Scoping UX gap (after Arrows instancing)

**Today:** A visualizer covers **Target ∪ Scope** only. Meshes are not auto-discovered by attribute name. Putting objects in a collection does nothing until that collection is set as the viz **Scope**.

**User expectation gap:** “I have 5 meshes with `flow` → AttrViz should cover all of them” sounds attribute-scoped; product is watch-scoped. Controls exist (`Target` / `Scope`) but are easy to miss; add-viz usually wires the active object only.

**Do not solve in Surface mute / z-fight work.** Mute must follow existing `iter_watch_meshes(Target, Scope)` — same set Surface already samples. No scene-wide attr scan, no second mesh picker.

**Later (after Phase 7b Arrows):**

- [ ] Make Scope / “objects covered” obvious in the Viz panel (count + names, or empty-Scope hint).
- [ ] Optional: “Add selection to Scope” / “Create Scope from selection”.
- [ ] Optional (larger): attribute-discovery mode — gather meshes that own the named attr. Separate product axis from Target∪Scope; don’t break the watch model.

## Surface Solid mute (z-fight) — done (0.5.7)

Identity Surface + Workbench solid → coplanar shred. Fix: AttrViz-owned
`display_type` → `WIRE` for meshes in the active GPU Surface **Target∪Scope**
watch set (same as sampling). Synced via `suppress_gn_carriers` / depsgraph.
No attr discovery; scoping UX remains backlog above.
