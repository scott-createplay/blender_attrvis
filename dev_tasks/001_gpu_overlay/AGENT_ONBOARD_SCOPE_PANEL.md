# Agent onboard — Watch collection (`attrvis`)

**Parent:** [`POR.md`](POR.md) · [`backlog.md`](backlog.md) Scoping UX  
**Status:** Landed in **0.5.10**. GUI confirm still open.  
**Not this pass:** attribute discovery, strangler Phase 2, Tags atlas, Surface inflate, per-viz Target/Scope pickers

---

## Product (locked)

A visualizer watches Target ∪ Scope (`gpu_sample.iter_watch_meshes`). The **GUI** path is stricter:

- One scene collection named `attrvis` (nested children included).
- If `attrvis` **exists**, it is the watch set for **every** visualizer — including GPU overlay / Tags. Empty → nothing draws (per-viz Scope sockets are ignored).
- If `attrvis` is absent, fall back to modifier Target ∪ Scope (tests, city `--viz`, old files).
- Membership **is** the scope. Objects may also live in `Buildings` / the scene / etc.
- Distinct from `Visualizers` (viz-object registry).
- Meshes are **not** discovered by attribute name.

```
RMB → AttrViz
        Visualize Attribute → Point / Face / …   (create viz; selection → attrvis)
        Edit
          Add objects                             (link into attrvis)
          Remove objects                          (unlink; do not delete)
```

N-panel **root** (not inside `_draw_viz_body`): `attrvis    N meshes · names…` (first 8 + `+N more`). Empty: `none — AttrViz → Edit → Add objects`.

`add_visualizer(target=, scope=)` stays for tests and city `--viz`.

---

## What landed

- `WATCH_COLLECTION`, `_ensure_watch_collection`, `_watch_candidates`, `_link_to_watch`, `_unlink_from_watch`, `add_visualizer_from_selection` in `attrviz/__init__.py`
- `ATTRVIZ_MT_root` / `ATTRVIZ_MT_edit` / `ATTRVIZ_OT_watch_add` / `ATTRVIZ_OT_watch_remove`
- `ATTRVIZ_OT_add` → `add_visualizer_from_selection` (`Scope=attrvis`, `Target` unset)
- `_draw_watch_readout` on the panel root; `panel_prop` still root-only
- Tests in `tests/test_gpu_sample.py`

## Validate (GUI)

Rsync `attrviz/` → `~/Library/Application Support/Blender/5.0/extensions/user_default/attrviz/`

- Cube: AttrViz → Visualize Attribute → object in `attrvis`, overlay on the cube
- Multi-select → Add objects → coverage grows; same viz; both draw
- Multi-select → new visualizer → both in `attrvis`
- Remove objects → unlinked, not deleted; still in other collections
- Accordion still one-open; Tag Cap 0 / Density 0 still empty
