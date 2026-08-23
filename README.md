# blender_attrviz

Houdini-style attribute visualizers for Blender — first-class, native,
and zero-mutation. Right-click any object, pick an attribute, see it.

![position visualized as surface RGB](docs/cube_position.png)

*The default cube, `position`, one click: RMB → Visualize Attribute →
position. Vector attributes auto-map to RGB on the surface.*

## What it is

Blender has no equivalent of Houdini's visualizers — the geometry
spreadsheet shows numbers, the Viewer node is transient, and nothing
gives you persistent, per-object "show me this attribute in the
viewport" workflow. AttrViz adds it:

- **Visualizers are ordinary scene objects** in a visible
  `Visualizers` collection. The outliner is the registry; the
  viewport **eye icon** / **Enabled** toggles each one; delete the
  object, the visualizer is gone. They save with your .blend.
- **RMB → Visualize Attribute** lists every attribute on the object's
  *evaluated* geometry (so attributes created by Geometry Nodes
  modifiers show up too) and creates a visualizer with sensible
  defaults in one click.
- **A "Viz" tab in the 3D viewport sidebar** groups visualizers under
  the collection each one watches, with a per-collection enable
  toggle. Expand any visualizer to tune Scope / Domain / Attribute /
  Type / Color plus per-type controls (scale, density, arrow length,
  tag cap, …).
- **GPU Overlay (default on)** draws Markers, Surface, and Arrows as
  unlit Solid-mode ink — no Material Preview required. Turn it off in
  the Viz panel to fall back to the Geometry Nodes + emission material
  path.

## Why it's fast (and safe)

A visualizer never mutates the object it watches. It *watches* it via
Object Info / Collection Info through the depsgraph.

**GPU Overlay (default):** sample evaluated attributes → upload GPU
batches → `POST_VIEW` draw (points, false-color mesh, 4-sided cones).
Works in **Solid** shading; F12 beauty stays clean (`hide_render` on
viz carriers).

**Materials fallback:** when GPU Overlay is off, the visualizer's own
Geometry Nodes modifier generates marker / surface / arrow carriers
and an emission material reads `vizcol`. Prefer **Material Preview**
for that path.

Tags stay on a capped BLF text path (semantic strings OK); see Roadmap
for atlas work.

## Visualization axes

| Axis | Options | Notes |
| --- | --- | --- |
| **Domain** | `Point` \| `Edge` \| `Face` \| `Corner` | Localizes the read — Houdini-style. Face attrs draw on faces, not smeared to points. |
| **Color** | `Heat` \| `RGB` \| `Random` | Heat = scalar through a ramp. RGB = vector channels. Random = stable hash color per element id (ints / categorical). |
| **Type** | `Markers` \| `Surface` \| `Arrows` \| `Tags` | **GPU Overlay:** Markers = points, Surface = false-color mesh, Arrows = 4-sided cones. **Tags** = BLF labels (Tag Cap = max count; Size = int px). |

**RMB → Visualize Attribute** opens **domain submenus**, then attributes
on that domain. Auto-pick is domain-aware (e.g. Face + int → Random +
Surface). Overridable in the Viz panel; each visualizer owns its engine
copy. Use **Enabled** to show one at a time — no compositing.

Intrinsics **Index**, **Position**, and **Normal** are always available
(GN fields / evaluated topology — not frozen authored ids).

## Scopes — one visualizer, many objects

Every visualizer watches a **collection** through its `Scope` socket.
`attrvis` is the default bucket, created the first time something needs
one — an ordinary collection, not a special case. A file with no
`attrvis` is a perfectly legal state.

From **RMB → AttrViz → Edit**:

- **Add objects to `<scope>`** links the selection into the active
  scope. Additive — objects stay in every collection they already
  belong to.
- **Remove objects from `<scope>`** is the explicit subtractive half.
- **New collection from selection…** creates a sibling collection, adds
  the selection to it, and makes it active.

The Viz panel groups visualizers under their scope:

```
▼ ☑ attrvis                3 obj / 1 viz
     ▶ ☑ grad · Point · Arrows
▼ ☑ attrvis_curvature      1 obj / 1 viz
     ▶ ☑ curv · Point · Surface
```

- The **checkbox on a group** enables or disables every visualizer
  scoped to it. It ANDs with each visualizer's own toggle, so
  individual states survive a group being switched off and on.
- **Clicking a group name** makes that collection active — the target
  for Add / Remove and the default `Scope` for new visualizers. It
  changes nothing on screen.
- Every collection is always listed, so a visualizer that is drawing
  always has a visible row to turn it off with.

This is what lets the **same attribute carry two appearances** at once:
`K` auto-ranged on one collection, `K` fixed-range on another, both
visible.

**Partial coverage is normal.** Objects in a scope that don't carry the
attribute are skipped; the visualizer draws on the ones that do, and
the panel reports it honestly — `3 objects  -  2 carry grad`. Objects
nothing is drawn on stay **visible**, rather than being hidden with
nothing in their place.

Scopes are **flat by default** — AttrViz never nests one inside
another. Nest deliberately in the outliner if you want a parent scope
to cover its children; the panel says so when you do.

[`examples/attrviz_scope.blend`](examples/) demonstrates all of the
above in one scene (rebuild it with
`examples/build_attr_scope_scene.py`).

## Install

Grab a release zip (or build one, below), then:
**Edit → Preferences → Get Extensions → ⌄ → Install from Disk…**

Build from source:

```
blender --command extension build --source-dir attrviz --output-dir build
blender --command extension install-file --repo user_default --enable build/attrviz-<version>.zip
```

Developed against **Blender 5.0+** (tested on 5.0.1 and 5.2.0). Current
addon version: **0.5.12**.

## Tests

All suites run headless. The GPU overlay itself is not
headless-testable — the draw handler needs a real viewport — so the
draw *logic* is factored to take its callables as arguments and tested
without one.

```
blender --background --factory-startup --python-exit-code 1 \
  --python tests/<suite>.py
```

| Suite | Covers |
| --- | --- |
| `headless_test.py` | main suite — GN path + registry |
| `test_gpu_sample.py` | GPU sampler, Surface / Arrows geometry, attribute reads |
| `test_watch_collection.py` | scopes, active scope, group enable, mute scope, coverage |
| `test_overlay_kinds.py` | texture packing, view cull, occlusion filter |
| `test_gpu_color.py` | colour mappers, empty-sample handling |
| `test_draw_guard.py` | per-visualizer failure containment in the draw loop |
| `test_surface_direct.py` | direct Surface construction |

## Design notes

[`docs/explorations.md`](docs/explorations.md) — design work that is settled enough to
remember but not scheduled: the constant/varying readout, Tags collapse, and pointers to
what is parked in the PORs.

## Roadmap

- Tags: dynamic glyph atlas (semantic text at higher caps), then
  compiled overlay if needed
- HUD overlay for non-geometry data (custom properties, transforms)
- VDB / volume grid visualization
- Stronger Edge surface / wire display

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
