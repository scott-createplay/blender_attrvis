# Agent onboarding — GPU overlay (task 001)

**Status: Stage B — Markers + Arrows GPU user-verified; Tags/Surface open**

**Source of truth:** [`POR.md`](POR.md)

---

## What this task is

1. **Start** with a standalone GPU **probe** (sample → draw, no AttrViz).
2. **As the probe lands** (Phase 2 pixels), **build the real AttrViz GPU overlay** in the same POR — Markers → Arrows → Tags/Surface.

Visual bar = **row 2** of the DistLook AOV sheets (flat false-color), not the lit beauty row.

## Start here

1. Read `POR.md` (Stage A then Stage B).
2. Open references — study **row 2**:

   - `references/sample_scene_3_distlook_aov_sheet.png`
   - `references/sample_scene_3_distlook_identity_sheet.png`

3. Skim Blender GPU docs linked in the POR.
4. Implement Stage A under `probe/` — **no `attrviz/` edits until Phase 2 exits**.
5. Phase 2 green → start Stage B (`attrviz/gpu_overlay.py` etc.) immediately; finish Phase 3 in parallel.

## Do not

- Stop after the probe and wait for another POR
- Require Material Preview for acceptance
- Rip out materials/`vizcol` before GPU Markers are validated
- Implement DistLook cook / sheet tools (sibling repo)

## Sister context (read-only)

```text
/Users/scott.peters/dev/hdr_synthetic_scene_pipeline
  output/diagnostics/distlook_aov_still/
  output/diagnostics/distlook_identity_still/
  render_presets/overlays/distlook_aovs.json
  dev_tasks/005_distlook_channel_contract/POR.md
```

## Exit

- **Gate A:** Phase 2 screenshot + sample tests  
- **Gate B:** AttrViz Markers + Arrows via GPU in Solid; suite green; screenshots in `references/`
