# POR: Strangle GN display backbone behind GPU-first registry

**Parent:** `dev_tasks/001_gpu_overlay/POR.md`  
**Status:** Ready for next agent — design locked; not implemented  
**Blender:** 5.0.1+ · AttrViz `0.5.3`+  
**Date:** 2026-08-11

---

## Why this exists

GPU Overlay **draws** Markers / Surface / Arrows in Python (`gpu_sample` → `gpu_overlay`). Users with **GPU Overlay on** still pay a large **create** cost because every visualizer still:

1. Allocates a mesh + object  
2. Adds a Nodes modifier  
3. **`ensure_viz_group().copy()`** — deep-copies the entire AttrViz Engine tree  

Harness signal (`profile_overlay_harness.py` on sample_scene_3): `harness.add.*` ≈ **300–400ms** per viz even when GPU is on and GN `show_viewport=False`.

Orbit/scrub got cheaper (split sample/presentation cache). **Init did not** — GN is vestigial for GPU-on display but still constructed.

---

## Mental model (do not confuse)

| Path | Who computes ink | Who holds config today |
|------|------------------|------------------------|
| **GPU Overlay ON** | Python (`gpu_overlay` / `tags_draw`) | GN modifier sockets + copied engine tree |
| **GPU Overlay OFF** | GN (Object Info → fields → instances / `vizcol`) | Same |

Target geometry is already a **pointer** (Object Info / `evaluated_get`). We do **not** duplicate scene meshes. We **do** duplicate the **engine graph** per viz — that is the init tax.

---

## Goal

**Strangler fig:** introduce a GPU-first visualizer create path behind config, keep GN fallback intact until proven, then **deprecate and delete** the dead create/copy path so we do not accumulate permanent dual branches.

Success:

1. With GPU Overlay on, adding a viz is **cheap** (no per-viz engine `.copy()`).  
2. With GPU Overlay off (or explicit fallback), GN display still works.  
3. After validation gates, GN-copy-on-add and unused branches are **removed**, not left as `#ifdef` forever.

---

## Non-goals

- Rewriting DistLook / AOV cook  
- Compiled Blender Overlay engine (escalate only with evidence)  
- Keeping both create paths indefinitely “just in case”  
- Changing panel UX (`panel_prop`) except as needed for props

---

## Design principles

### 1. Config-gated strangler (temporary dual path)

Every new path ships behind an explicit flag, defaulting so current users keep behavior until we flip:

| Flag | Suggested home | Meaning |
|------|----------------|---------|
| `Scene.attrviz_gpu_markers` | already exists | Draw path: GPU vs materials |
| `Scene.attrviz_gpu_registry` (new) | Scene BoolProperty, default **True** when GPU overlay default is on — or default False for one release then flip | Create path: lightweight registry vs full GN copy |

**Rule:** draw flag and create flag may differ during migration (e.g. GPU draw + still-GN create). Document the matrix in the Status table when you change defaults.

### 2. Prefer shared pointer over copy

Blender allows **many modifiers → one `NodeTree`**. Per-viz config lives on **modifier sockets**, not unique trees.

Minimum strangler step (often enough for init):

```text
# BAD (today)
grp = ensure_viz_group().copy()

# GOOD (shared engine)
grp = ensure_viz_group()   # single datablock
md.node_group = grp
```

Do **not** mutate the shared tree’s nodes per viz — only modifier inputs.

### 3. GPU-first registry (full strangler)

Longer term when GPU-on:

```text
Visualizer = object (or Empty) in "Visualizers" collection
  + RNA props / PropertyGroup mirroring sockets
      Target, Scope, Attribute, Domain, Style, Display, Length, …
  + NO Nodes modifier until fallback demanded
GPU overlay reads props the same way it reads modifier sockets today
```

Attach GN only when:

- user turns GPU Overlay **off**, or  
- Display/feature still requires GN (none for Markers/Surface/Arrows/Tags if GPU parity holds)

### 4. Deprecate → remove (no false branches)

Strangler without removal = permanent `#if GPU` spaghetti.

For each migrated piece, use this lifecycle:

| Stage | Requirement |
|-------|-------------|
| **A Ship behind flag** | Old path still callable; new path default or opt-in |
| **B Validate** | Harness + user: create time, Solid draw, GPU off fallback, migrate old files |
| **C Deprecate** | Log once / UI note; flag becomes “legacy only” |
| **D Delete** | Remove old function, dead sockets wiring, and flag if unused; bump version; note in README |

**Definition of done for this POR:** Stage D for “per-viz `ensure_viz_group().copy()` on add”, not merely Stage A.

**Forbidden:** leaving `if gpu: … else: …` copies of the same logic in three files with no removal ticket.

---

## Suggested implementation phases

### Phase 0 — Measure baseline (½ day)

- Run:

```bash
blender --background --python-exit-code 1 \
  --python dev_tasks/001_gpu_overlay/tests/profile_overlay_harness.py -- \
  --max-targets 1 --displays Markers,Surface --warm 3 --scrub \
  --json /tmp/attrviz_perf_baseline.json
```

- Record `harness.add.*` totals. This is the init KPI.  
- Confirm GPU-on still calls `.copy()` in `add_visualizer` (`attrviz/__init__.py`).

### Phase 1 — Shared engine group (small, high win)

**Author**

- Change `add_visualizer` / `_migrate_visualizer` to assign **shared** `ensure_viz_group()` (no `.copy()`), unless a flag forces isolated trees.  
- Audit: anything that edits `md.node_group.nodes` per viz must stop or fork only then.  
- Color ramp: today panel may touch a ramp node inside the group — **shared tree breaks per-viz ramps**. Mitigate before sharing:
  - GPU Heat uses Python ramp / Range Min-Max (already), or  
  - keep a *tiny* per-viz override for materials-only Heat ramp, or  
  - copy group only when GPU Overlay is **off**.

**Recommended Phase 1 policy:**  

```text
if GPU Overlay on:
    shared engine, no copy
else:
    keep .copy() until Phase 2/3
```

**Validate:** `harness.add.Markers` drops sharply; GPU Solid still draws; two viz with different Attributes work (sockets are per-modifier).

**Exit:** KPI table in this file; version note `0.5.4` or similar.

### Phase 2 — Lazy GN attach (strangler)

**Author**

- `attrviz_gpu_registry` (or reuse GPU flag): create viz object + props **without** Nodes modifier when GPU-on.  
- Centralize config read: `viz_config(obj) -> namespace` that reads PropertyGroup **or** modifier sockets.  
- `gpu_overlay` / panel / operators use only `viz_config`.  
- On GPU Overlay → off: `ensure_gn_modifier(obj)` builds/attaches shared or copied group and syncs props → sockets.

**Validate:**  

- GPU-on add ≪ Phase 1 (no modifier / no tree).  
- Toggle GPU off → ink via materials path for Markers/Surface.  
- Toggle GPU on → suppress GN carriers again.

**Exit:** User-verified on sample_scene_3; harness JSON checked in under `dev_tasks/001_gpu_overlay/references/perf/`.

### Phase 3 — Deprecate GN-copy create

**Author**

- Mark `.copy()`-on-add as deprecated; only used for legacy migration of old files if needed.  
- Migration: existing viz with unique `AttrViz · …` trees can be re-pointed to shared engine on load (optional one-shot).  
- Remove dead code paths that assumed unique trees.

**Validate:** headless suite green; no double registry.

### Phase 4 — Remove false branches (mandatory)

Checklist before closing POR:

- [ ] `add_visualizer` has **one** create story for GPU-on (no leftover `.copy()`).  
- [ ] Grep clean: no unused `ensure_viz_group().copy` in hot path.  
- [ ] Config read goes through one helper (`viz_config` / equivalent).  
- [ ] Temporary flags removed or reduced to a single “Force GN materials path”.  
- [ ] README: GPU Overlay = display + create; materials = fallback.  
- [ ] POR Status table updated; parent GPU overlay POR linked.

---

## Code map

| Area | Path |
|------|------|
| Create / copy | `attrviz/__init__.py` — `add_visualizer`, `_migrate_visualizer` |
| Engine tree | `attrviz/node_builder.py` — `ensure_viz_group` |
| GPU draw | `attrviz/gpu_overlay.py`, `gpu_sample.py`, `gpu_color.py` |
| Tags | `attrviz/tags_draw.py` |
| Suppress GN when GPU on | `gpu_overlay.suppress_gn_carriers` |
| Perf harness | `dev_tasks/001_gpu_overlay/tests/profile_overlay_harness.py` |
| Install ≠ repo | `~/Library/Application Support/Blender/5.0/extensions/user_default/attrviz/` |

---

## Risk: shared group + Heat ramp

Materials path stores a `ColorRamp` **inside** the node group. Sharing one group ⇒ one ramp for all viz.

| Mode | Policy |
|------|--------|
| GPU on | Prefer Range Min/Max + Python Heat (`gpu_color`); ignore group ramp |
| GPU off | Per-viz `.copy()` **or** move ramp to a per-viz mechanism later |

Do not share the engine for GPU-off until ramp ownership is solved.

---

## Acceptance

1. GPU Overlay on: create viz on sample_scene_3 feels usable; `harness.add.*` **≪** baseline (target: **&lt; 50ms** add after Phase 2, or **&lt; 100ms** after Phase 1 shared group — update with measured numbers).  
2. GPU Overlay off: Markers/Surface still work via materials/GN.  
3. ≥2 viz, different attrs/domains, independent Enabled / Length / Range.  
4. Dead `.copy()`-always path removed (Phase 4).  
5. Harness before/after JSON under `references/perf/`.

---

## Handoff for the next agent

1. Read this POR + parent GPU overlay Status.  
2. Run harness baseline; paste `harness.add.*` into Status.  
3. Implement **Phase 1** (shared group when GPU on) first — smallest fix, real init win.  
4. Only then Phase 2 lazy registry.  
5. Do not ship Phase 1/2 without a written Phase 4 removal plan in the PR.  
6. Commit when asked; sync install path for user verify.  
7. Update this Status table as phases complete.

---

## Status

| Phase | State |
|-------|--------|
| 0 Baseline harness | **Done** 2026-08-11 — see KPI below |
| 1 Shared engine when GPU on | **Done** 2026-08-11 (+ suppress-before-Target + cheap Attr Is Vector) |
| 2 Lazy GN / GPU registry | Pending |
| 3 Deprecate copy-on-add | Pending |
| 4 Remove false branches | Pending — removal plan below |

**Current bug/oversight (partially fixed):** GPU Overlay toggled **draw** but create still paid GN. Phase 1: shared engine when GPU on; suppress carrier **before** Target; `_target_attr_meta` fast-path on original mesh attrs.

### KPI (sample_scene_3 AOV test, SIGN / 3× SIGN)

Harness: `profile_overlay_harness.py --displays Markers,Surface --warm …`  
JSON under `references/perf/`.

| Run | `harness.add.Markers` | `harness.add.Surface` |
|-----|----------------------|------------------------|
| Phase 0 baseline · 1 target | **393.3 ms** | **303.5 ms** |
| Phase 1 after · 1 target | **62.9 ms** (first = engine build) / **~0.5 ms** steady | **0.9 ms** |
| Phase 0 baseline · 3 targets | **969.1 ms** total (mean 323) | **925.4 ms** total (mean 308) |
| Phase 1 after · 3 targets | **59.0 ms** total (mean 20) | **1.1 ms** total |

Steady-state add (engine already built): **~0.3–0.6 ms** per viz (microbench on SIGN).

Files: `baseline_phase0.json`, `phase1_after.json`, `baseline_phase0_3targets.json`, `phase1_after_3targets.json`.

### Phase 4 removal plan (required before closing POR)

1. After Phase 2 registry: delete `_assign_viz_engine` copy branch and any `ensure_viz_group().copy()` on add/migrate hot path.  
2. Collapse suppress-before-Target into “no Nodes modifier until fallback”.  
3. Single `viz_config(obj)` reader; panel/GPU/operators stop reaching into `md.node_group.nodes` for Heat ramp when GPU on (already skipped).  
4. Grep-clean; README: GPU Overlay = display + create; materials = fallback only.  
5. Drop temporary flags; keep at most one “Force GN materials path”.

---