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
  viewport **eye icon** toggles each one; delete the object, the
  visualizer is gone. They save with your .blend.
- **RMB → Visualize Attribute** lists every attribute on the object's
  *evaluated* geometry (so attributes created by Geometry Nodes
  modifiers show up too) and creates a visualizer with sensible
  defaults in one click.
- **A "Viz" tab in the 3D viewport sidebar** lists all visualizers:
  toggle, remove, edit the color ramp, and tune attribute / style /
  display / range / density / scale per visualizer.

## Why it's fast (and safe)

A visualizer never touches the object it watches. It *watches* it:
the visualizer's own Geometry Nodes modifier pulls the target's
evaluated geometry through the depsgraph (Object Info / Collection
Info) and generates marker geometry from it. Everything in the hot
path is native C++ — no Python draw handlers, no per-frame re-reads.
Animation and simulations visualize live for free, and toggling a
visualizer never re-evaluates the watched object.

## Visualization axes

| Axis | Options | Notes |
| --- | --- | --- |
| **Domain** | `Point` \| `Edge` \| `Face` \| `Corner` | Localizes the read — Houdini-style. Face attrs draw on faces, not smeared to points. |
| **Color** | `Heat` \| `RGB` \| `Random` | Heat = scalar through a ramp. RGB = vector channels. Random = stable hash color per element id (ints / categorical). |
| **Type** | `Markers` \| `Surface` \| `Arrows` \| `Tags` | Markers / Surface / Arrows are GN carriers. **Tags** = GPU sprite+text prototype (capped; path toward a compiled display plugin). |

**RMB → Visualize Attribute** opens **domain submenus**, then attributes
on that domain. Auto-pick is domain-aware (e.g. Face + int → Random +
Surface). Overridable in the Viz panel; each visualizer owns its engine
copy. Use **Enabled** to show one at a time — no compositing.

Scope: a visualizer can watch a single object, or a whole collection
through its `Scope` socket — one visualizer covering many objects.

## Install

Grab a release zip (or build one, below), then:
**Edit → Preferences → Get Extensions → ⌄ → Install from Disk…**

Build from source:

```
blender --command extension build --source-dir attrviz --output-dir build
blender --command extension install-file --repo user_default --enable build/attrviz-<version>.zip
```

Developed and tested on **Blender 5.2 LTS**; requires 5.0+.

## Tests

Analytic headless suite (no UI, exact assertions):

```
blender --background --factory-startup --python-exit-code 1 --python tests/headless_test.py
```

## Roadmap

- Tags: digit-atlas shader + depth occlusion (compiled display plugin)
- HUD overlay for non-geometry data (custom properties, transforms)
- VDB / volume grid visualization
- Stronger Edge surface / wire display

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
