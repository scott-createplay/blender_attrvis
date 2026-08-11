# GPU Overlay Probe — Stage A

Standalone probe for AttrViz task `001_gpu_overlay`. Proves:

**evaluated attr → CPU buffers → GPU batch → Solid viewport unlit ink**

No AttrViz import. No materials. F12 must stay clean of overlay ink.

## Layout

```text
probe/
  __init__.py          # tiny addon entry (bl_info + register)
  sample.py            # sample_evaluated()
  color_map.py         # heat / hash false-color
  overlay_probe.py     # POST_VIEW draw handler + N-panel
  build_fixture.py     # synthetic grid .blend
  probe_fixture.blend  # generated
  README.md            # this file
tests/
  test_probe_sample.py
```

## Build fixture

```bash
cd /Users/scott.peters/dev/blender_attrvis

blender --background --factory-startup --python-exit-code 1 \
  --python dev_tasks/001_gpu_overlay/probe/build_fixture.py
```

Writes `probe/probe_fixture.blend` — grid with `heat` (POINT float),
`face_id` (FACE int), `flow` (POINT vector). Object has `hide_render=True`.

## Headless sample tests (Phase 1)

```bash
blender --background --factory-startup --python-exit-code 1 \
  --python dev_tasks/001_gpu_overlay/tests/test_probe_sample.py
```

## Enable probe in GUI (Phase 2)

### Option A — path insert (fastest for agents / dev)

1. Open Blender 5.0.1+ (GUI).
2. File → Open → `dev_tasks/001_gpu_overlay/probe/probe_fixture.blend`
3. Scripting workspace → new text, paste and Run Script:

```python
import sys
sys.path.insert(0, "/Users/scott.peters/dev/blender_attrvis/dev_tasks/001_gpu_overlay")
import importlib
import probe
importlib.reload(probe)
probe.register()
```

4. 3D View → Sidebar (`N`) → **Probe** tab.
5. Set Attribute `heat`, Domain `Point`, check **Enabled**.
6. Or keymap: **Alt+Shift+P** to toggle.

### Option B — Install as addon

Zip the `probe/` folder (so zip root contains `__init__.py`), then
Preferences → Add-ons → Install → enable **GPU Overlay Probe**.

## Interactive validation checklist (Gate A)

Viewport shading: **Solid** · Flat or Studio.

| # | Check | Pass |
|---|--------|------|
| 1 | Enable probe on Probe Grid / `heat` | Colored points visible (blue→red heat) |
| 2 | Toggle Enabled off | Ink disappears |
| 3 | Target has `hide_render=True` | Overlay still draws |
| 4 | F12 render | Beauty has **no** overlay points |
| 5 | Material Preview | Still visible, or note Solid-only here |
| 6 | Screenshot | Save as `../references/probe_phase2_points.png` |

Ask: “If this were an AOV panel for `heat`, would a human trust it?”

## Switch attrs

- `heat` + Point — heat map (default Phase 2)
- `face_id` + Face — hash colors at face centers (Phase 3 depth/faces)
- `flow` + Point — RGB-ish from vector abs (stub)

## Phase 3 extras

| Control | Use |
|---------|-----|
| Domain **Face** + Attribute `face_id` | Hash colors at face centers (entity_id spirit) |
| Attribute `flow` + **Vector Lines** | Short line segments (arrows-lite) |
| Point Cap | Default **50000**; stride subsample above |

**Depth:** draw uses `LESS_EQUAL`. Orbit the mesh — points behind the
surface should hide. If occlusion is wrong on your GPU, note it for
`ESCALATE.md` (do not invent fake scene meshes).

## AttrViz Stage B (product path)

Once AttrViz is installed/loaded from this repo:

1. Viz panel → toggle **GPU Markers**
2. Create a Markers visualizer (RMB → Visualize Attribute)
3. Switch viewport to **Solid** — unlit points, no Material Preview required
4. GN marker meshes are hidden while the flag is on (no double ink)

GPU Markers default **off** so existing materials/GN behaviour stays stable.
