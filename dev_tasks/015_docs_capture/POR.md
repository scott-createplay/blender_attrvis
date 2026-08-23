# POR: a Playwright for Blender — scripted scenarios that document the addon

**Parent / history:** no single parent. Prompted by the README rewrite for
[`../011_viz_scope/POR.md`](../011_viz_scope/POR.md), where the panel became a
collection tree and every screenshot and prose description in the docs silently
went stale. Also by a support round-trip in which "we lost the nested
collections in the panel" turned out to be a stale module — a baseline image
would have answered it in one command.
**Status:** **M1 (menus) and C3 (panel) run and passed** — see
[`FINDINGS_M1.md`](FINDINGS_M1.md). Both surfaces capture deterministically,
natively, with no image-library dependency. The rest is designed, not built.
**Revised 2026-08-23:** the RMB menu is **in scope and designed** (see *The RMB
menu*, below). Phase D gains M1-M3; C7 splits.
**Northstar:** **the docs are generated from a scene we can assert about.**
Never hand-typed, never hand-cropped.

AttrViz **0.5.12**. Blender **5.2.0**.

---

## TL;DR

Build a Playwright-shaped harness for Blender: launch, drive the UI into a
known state, wait for a real redraw, assert on it, capture the editor, and
regenerate the doc section that describes it.

The mapping is close to exact:

| Playwright | Blender |
|---|---|
| `browser.newPage()` | launch Blender **non-background** with a `.blend` |
| `page.goto()` | open scene, set UI state |
| `page.click()` | set properties / call operators |
| `waitForSelector` | `bpy.app.timers` until a redraw actually lands |
| `page.screenshot({clip})` | `bpy.ops.screen.screenshot_area` on one editor |
| `page.hover()` | synthesised OS input, to walk a submenu cascade (M3) |
| `expect(locator)` | assert on introspected state *before* capturing |
| `toHaveScreenshot()` | diff against a committed baseline |

---

## Why this is not only a docs chore

Playwright's real value is not producing screenshots — it is
`toHaveScreenshot()` catching UI changes nobody intended.

**Everything in `tests/` stops at the draw boundary.** 009 established that the
GPU overlay is not headless-testable, and 011 Phase 5b shipped a panel layout
that no test covers. The panel is the least-tested surface in the project and
the one that changed most recently.

So the same harness buys two things at once: current documentation, and the
first regression coverage the panel has ever had.

---

## The constraint that shapes everything — measured

```
render.opengl in --background: RuntimeError:
    Cannot use OpenGL render in background mode (no opengl context)
```

**Capture requires a real Blender window.** `blender scene.blend --python
capture.py`, *without* `--background`.

Headless Blender does expose a window and screen — `windows: 1`, areas
`['PROPERTIES', 'OUTLINER', 'DOPESHEET_EDITOR', 'VIEW_3D']` — but with no GL
context nothing ever draws. This is the same wall as 009: the overlay needs a
real viewport.

Consequence: this harness cannot run in the same `--background` sweep as the
test suites. It is a separate command that opens a window.

## What the API gives us — measured on 5.2

| Call | Status |
|---|---|
| `bpy.ops.screen.screenshot(filepath=...)` | **exists** — whole window |
| `bpy.ops.screen.screenshot_area(filepath=...)` | **exists** — *"Capture a picture of an editor"* |
| `bpy.ops.render.opengl` | exists, **fails in background** |
| `bpy.ops.wm.call_menu` | exists — the transient case, see Risks |
| `bpy.ops.view3d.view_axis` / `view_selected` / `view_camera` | exist |
| `bpy.ops.screen.area_split` | exists |
| `bpy.app.timers` | available |

Both screenshot ops take `filepath` plus the standard file-select properties.
Note neither documents a clip/crop argument — `screenshot_area` **is** the
cropping mechanism — **including for popups**. This was measured against a
written-down hypothesis that it would *not* be: a menu is a temporary region
overlaying the areas, so it looked like it should be clipped out. It is not.
`screenshot_area` captures the full menu cascade cropped to the editor, with no
window chrome. **No external crop, no Pillow dependency.**

### Measured by M1 on 5.2

| Call | Result |
|---|---|
| `bpy.types.Window.cursor_warp(x, y)` | **works** — sets where the menu opens; the menu's *first row* lands under the cursor |
| `bpy.context.temp_override(window=, area=, region=)` | **works** — satisfies `ATTRVIZ_MT_visualize.poll` |
| `bpy.app.timers` **during an open popup** | **fire normally** — the pivot risk did not materialise |
| `wm.call_menu(name=<bl_idname>)` | returns `{'INTERFACE'}`; popup persists into the event loop |
| `preferences.view.open_sublevel_delay` | **clamps to a minimum of 1** (1/10 s) — `0` is silently refused |
| `wm.invoke_popup` / `wm.call_panel` | **not needed** — M2 dropped |

---

## Design

Three pieces. Keep them separable; the second two are worthless if Phase D
sinks the first.

### 1. Capture (needs a window)

A script that, per scenario:

- sets **window geometry** so pixel dimensions are stable
- forces the screen layout: which editors, sidebar open, Viz tab active,
  which collection groups expanded
- sets the 3D view by **explicit `view_matrix`**, not `view_selected` — the
  latter depends on selection and saved state, which is exactly the drift we
  are trying to kill
- **asserts** the state it is about to photograph (e.g. `visualizers_by_scope`
  returns 2 groups with the expected counts)
- waits on `bpy.app.timers` for a real redraw
- `screenshot_area` on the target editor → `docs/img/<name>.png`
  (**menus are the exception** — whole-window capture then crop; see *The RMB
  menu*)
- quits with a gate-able exit status

**Run under `--factory-startup` with the script calling `av.register()`**, the
same way every suite in `tests/` does. Otherwise the operator's theme, UI scale
and saved layout leak into every image and no two machines agree.

### 2. Generate (headless is fine)

Introspect the same scene, emit markdown between markers:

```
<!-- attrviz:begin scope-panel -->
…generated from live state…
<!-- attrviz:end scope-panel -->
```

**This half catches the errors that actually happened.** The README shipped
`3 objects · 2 carry grad` when the panel renders a hyphen; it was hand-typed
from memory and caught only by re-reading the format string. Generated from the
format string, it cannot drift.

`dev_tasks/013_offset_probe/probe.py` and the panel-dump scratch scripts are
the prior art for the introspection style.

### 3. The manifest

Each scenario declares: source scene, UI state, target editor, output path, the
assertions that must hold, and which doc section it feeds. That is what makes
this a tool rather than a pile of one-off scripts.

---

## The RMB menu — load-bearing, and solvable

**Revised 2026-08-23.** Previously deferred as "leave that shot manual". It is
not deferrable: the RMB tree **is** the primary interaction surface of the
addon, and it is exactly the surface the stale-module support round-trip was
about.

### What is actually there

Not one menu — a **three-deep tree**, attached in `attrviz/__init__.py`
`register()` via
`bpy.types.VIEW3D_MT_object_context_menu.append(_context_menu)`:

```
VIEW3D_MT_object_context_menu
└── ATTRVIZ_MT_root                    "AttrViz"
    ├── ATTRVIZ_MT_visualize           "Visualize Attribute"
    │   └── ATTRVIZ_MT_domain_{point,edge,face,corner,instance}
    │       └── the attribute entries
    └── ATTRVIZ_MT_edit                "Edit"
        ├── "Add objects to {scope}"       ← label is live state
        └── "Remove objects from {scope}"
ATTRVIZ_MT_scope                       "Active Scope" — radio list, live counts
```

The load-bearing content sits at **depth 2-3**, and all of it is
**state-derived** — which is precisely why it must be generated, not typed:

- `ATTRVIZ_MT_visualize.draw` calls `attributes_by_domain(context.active_object)`
  and **skips empty domains**. The shot proves which domains an object really
  carries.
- The instanced-geometry guidance ("Geometry is instanced — add Realize
  Instances to unpack") renders **only** when Instance is populated and the
  mesh domains are not. Documented behaviour, no test.
- `ATTRVIZ_MT_edit` interpolates the destination scope into the label;
  `ATTRVIZ_MT_scope` lists collections with live counts and a radio marker.
- `ATTRVIZ_MT_visualize.poll` requires an active object that is **not** a
  visualizer — the 004 failure mode. A capture asserts that precondition
  instead of trusting it.

Hand-typing any of this is the same class of drift as the
`3 objects · 2 carry grad` error the generator exists to kill.

### Two deliverables, not one

| | Shows | Mechanism | Determinism |
|---|---|---|---|
| **A. Leaf content** | what is *in* a menu, given scene state | native `wm.call_menu(name=<bl_idname>)` — **any** menu opens directly by id, no traversal | **byte-identical, measured** |
| **B. Cascade, first row** | `Visualize Attribute` + the expanded `Point` child | native — `cursor_warp` then `call_menu`, no steering | **not deterministic** — docs only |
| **B'. Cascade, arbitrary row** | a cascade on a row that is not the first | needs real OS input (M3) | unsolved |

This split is what makes the problem tractable, and **M1 confirmed it**:
`wm.call_menu` takes a `bl_idname`, so A needs no hover chain at all, and
nearly all the regression value is in A. The first-row cascade came free.

**Steering to an arbitrary row does not work.** Blender holds the parent row
highlighted while the cursor moves toward an open submenu (the "safety
triangle"); three hover strategies each produced different, non-repeatable
results. B' is the only thing left that would need an external driver, and it
is avoidable by ordering doc shots so the interesting row is first.

### The ladder — cheapest rung first

**M1 — native leaf capture. RUN, AND IT PASSED.** `cursor_warp` →
`temp_override` on the VIEW3D area → `wm.call_menu` → timer ticks →
`screenshot_area`. Timers fire during popups, the popup survives the script
returning, and the area shot crops to the editor with the menu intact. Four
menus captured **byte-identical across runs**. Details in
[`FINDINGS_M1.md`](FINDINGS_M1.md).

**M2 — persistent-dialog fallback. DROPPED.** It existed only in case popups
proved untimeable. They did not, so the dialog-chrome compromise is
unnecessary.

**M3 — external driver. NARROWED, and possibly unnecessary.** Needed only for
**B'** — a cascade on a row that is not the first. Everything else is native.
Keep the design on file; do not build it until a doc shot genuinely demands a
non-first-row cascade.

- launch Blender → poll for a sentinel the scene script writes once state is
  asserted and stable
- `FindWindow` → window rect → `SendInput` right-click at a computed coord →
  hover-walk the chain with dwell
- capture via `BitBlt` from the screen DC over the window rect

Two things make this better than it first looks. It is a **separate OS
process**, so it does not care whether Blender's main thread is busy inside a
popup handler — the M1a question dissolves. And it generalises past menus to
**tooltips, popovers, dropdowns and hover states**, all equally transient and
all equally undocumentable today.

If it is ever built, Windows traps to pre-commit to — each costs a day if
found late:

- `PrintWindow` (even `PW_RENDERFULLCONTENT`) commonly returns **black** on
  OpenGL windows. Expect `BitBlt`-from-screen to be the working path — which
  means the window must be **foreground and unoccluded**.
- Capture needs an **active, unlocked desktop session**. Locked screen or
  disconnected RDP yields black frames.
- The driver must be **per-monitor DPI aware** or every coordinate is silently
  scaled.
- `BitBlt` excludes the cursor by default — good for determinism, but verify
  rather than assume.


---

## Annotation — derive the box, never place it

Boxes, arrows and callouts are load-bearing: "point at the Arrows row" is how a
reader finds a control. Drawing them is trivial — numpy already crops, so
rectangles, leader lines and dim-outside-spotlight are array writes.

**The hard part is *where*.** A hand-placed box is the same failure as a
hand-typed `3 objects · 2 carry grad`: right today, silently wrong after the
next panel change. Annotation coordinates must be **derived**, or this feature
undermines the northstar it is being added to.

### Three tiers of anchor

| Tier | Target | Mechanism | Status |
|---|---|---|---|
| **Region** | sidebar, viewport, outliner | `region.x/y/width/height` | exact, free — already used for the panel crop |
| **Popup** | a menu, the cascade | differential capture: baseline vs with-popup, bbox of changed pixels | **built** — returned `[9, 4, 1136, 539]` in M1 |
| **Widget** | the `Arrows` row, the `GPU Overlay` button | Blender exposes **no per-button rect** to Python | needs differential localization |

### Differential localization

To point at a widget, **change it and diff**. Toggle `attrviz_display` from
Surface to Arrows, capture both, and the changed-pixel bbox *is* the Arrows
row. Flip `attrviz_ui_expand` and the bbox is that sub-panel.

This is the M1 oracle generalised from "did it render" to "where is it". Its
virtue: the box is derived from **the same state change the caption
describes**, so reordering the panel moves the box with it.

Limits, to design for rather than discover:

- two captures per annotated widget
- crop to the region first, or viewport redraw pollutes the diff
- works only for widgets whose appearance can change without side effects. A
  static label (`Color`) has no toggle — fall back to row arithmetic from the
  measured 30px pitch (`ui_scale` 1.5), which is grounded but fragile
- **assert every derived rect**: non-empty, plausibly sized, inside its region.
  A silent empty bbox draws an annotation pointing at nothing.

### Text is the one dependency decision

numpy cannot render glyphs. Three options:

1. **BLF into a GPU offscreen**, composited — native, no dependency, and a
   window already exists.
2. **Pillow** — reintroduces the dependency M1 and C3 just eliminated.
3. **Do not bake text into pixels at all.** Draw shapes and numbered markers;
   put the legend in the **generated markdown** beneath the image.

**Recommend 3.** Baked text is unsearchable, cannot be corrected without
re-rendering, and drags in cross-machine font determinism — the exact risk C7
already warns about. It also puts the words back under the generator where they
can be asserted. Callout numerals need only a ~20-line 5x7 bitmap font.

### One primitive, three jobs

The same differential capture proves a popup drew (M1c), anchors an annotation,
and proves overlay ink exists (below). Build it once, properly.

---

## The hero shot — geometry, and several types at once

**The default cube is the wrong hero.** Four flat normals; nothing for a
curvature ramp to say. **Suzanne** — recognisably Blender at a glance, with
enough curvature variation to make `curv` legible. Keep a torus for a gallery
arrows shot, where unambiguous normals matter more than recognisability.

**`Torus_Measured` in `examples/attrviz_scope.blend` is not a torus.** It is
`bmesh.ops.create_cone(radius1=1.1, radius2=0.35)` — a frustum, plainly so in
the captures. Fixture naming drift, and it would reach a doc caption.

### Multiple visualizers at once: supported; legibility is the problem

Already true in the fixture — `Torus_Measured` is in **both** scopes, so it
carries `grad · Point · Arrows` and `curv · Point · Surface` simultaneously.

But in the captures the Heat surface reads clearly and **the arrows do not**:
sub-pixel at that framing, and drawn over the surface that is their own
background. Surface + Arrows on one object fight each other. Levers: tighter
framing, the arrow-length control, or the two types on adjacent objects rather
than one.

### The dangerous failure mode

An overlay shot captured **too early** shows a clean surface with no arrows and
**looks correct**. A plausible wrong image is worse than a crash, because
nothing flags it.

So the assertion cannot be "did the viewport draw". It must be **"is there
arrow ink"** — and the differential primitive answers it: capture with the
arrows visualizer disabled, then enabled, and require a non-empty diff over the
object's screen bbox. **This is what C2 must deliver, and why C2 blocks the
hero.**

---

## Sequencing

### Phase D — spike the capture mechanics **first**

Nothing else can be designed until these are answered, and 011's discovery
phase earned its keep twice by refuting assumptions before implementation
(D7 withdrawn entirely; S1 collapsed a whole case).

Use the **existing** `examples/attrviz_scope.blend` — no new scene needed to
answer any of this.

| Spike | Question | Pass |
|---|---|---|
| **C1** | Does `screenshot_area` capture the editor I targeted, or the whole window? | file contains only that editor |
| **C2** | How many timer ticks before the GPU overlay has actually drawn? | overlay ink visible in the image; the tick count is **measured, not assumed** |
| **C3** | Does `--factory-startup` + `av.register()` give a reachable Viz tab? | **PASS** — `av._reveal_viz_panel()` opens the sidebar, category reads `Viz`, panel captured and cropped |
| **C4** | Is window geometry settable and stable? | two runs produce identical pixel dimensions |
| **C5** | Does an explicit `view_matrix` reproduce framing exactly? | two runs frame identically |
| **C6** | Does Blender exit cleanly with a status we can gate on? | non-zero on failure, zero on success |
| **C7a** | **Are two runs of the same *editor* scenario byte-identical?** | **PASS** — panel shot md5-identical; viewport-only shot 0 changed px |

Menu mechanics — run **alongside C1/C2, not after**. If M1a fails, the external
driver is mandatory for every menu shot rather than for the cascade only, and
that is a sequencing fact worth knowing before Phase 1.

| Spike | Question | Pass |
|---|---|---|
| **M1a** | Do `bpy.app.timers` fire while a popup handler is active? | **PASS** |
| **M1b** | Does a `wm.call_menu` popup survive the calling script returning? | **PASS** — open 0.65s later |
| **M1c** | Does whole-window `screen.screenshot` contain the popup pixels? | **PASS** |
| **M1d** | Does `screenshot_area` contain them? | **PASS — hypothesis refuted.** It crops to the editor *and* keeps the menu. The better shot. |
| **M1e** | Does `cursor_warp` place the menu deterministically? | **PASS** |
| **M1f** | Can `temp_override` satisfy `ATTRVIZ_MT_visualize.poll`? | **PASS** |
| **M1g** | Can `cursor_warp` steer to a *chosen* row after opening? | **FAIL — racy.** Safety triangle; 3 strategies, none repeatable |
| **M2** | `invoke_popup` fallback | **not run — dropped**, M1 passed |
| **M3** | External driver for the cascade | **not run — narrowed** to non-first-row cascades only |
| **C7b** | Are two runs of a *cascade* shot byte-identical? | **NO, confirmed** — do not gate on it |

**C7 splits, and the split was the right call.** Measured rule: **a menu with
no auto-opening submenu is byte-identical across runs; a menu whose first row
expands a child is racy**, because `open_sublevel_delay` cannot go below 0.1s
and the capture tick falls either side of it. A viewport-only area shot came
back with **0 changed pixels**.

So C7a (leaf menus + editor shots) **passes and gates Phase 6**. C7b (cascades)
**fails and is generator-only**, exactly as predicted — no regression
infrastructure was built on top of it.

### Phase 1 — the fixtures, built by script

Generated, **never hand-saved**, or they rot into opaque binaries that drift
from the addon. `examples/build_attr_scope_scene.py` is the template and the
existing convention.

**Three fixtures, not one** — the single `docs_demo.blend` assumption did not
survive the doc map:

1. `attrviz_scope.blend` — **exists**; feeds the panel, menu and scope shots.
2. a **Suzanne** hero scene — surface + arrows, framed for legibility.
3. an **instanced-geometry** scene — the un-realized instances guidance at
   `__init__.py:1216` needs the mesh domains to be *empty*, so it structurally
   cannot share a fixture with the others. No test and no doc today.

### Phase 2 — the runner

Scenario registry, setup → wait → assert → capture → teardown. Small.

### Phase 3 — the first three scenarios

The surfaces that changed most recently and that were hand-documented wrongly:

- **Viz panel** with collection groups, per-collection toggles, counts
- **Outliner** showing `attrvis` / `attrvis_curvature` / `Visualizers`
- **Viewport** with arrows on two objects and the non-carrier untouched

**Panel height is a scenario parameter.** The Viz panel is taller than the
sidebar and the region does not scroll for a screenshot — at 1600x900 the
Display list is cut off; 1600x1250 reaches the ColorRamp. A scenario must
assert that what it claims to show actually fits, and full-panel shots are
capped by the operator's physical screen. Sidebar *width* has no clean API,
so `Cube_No...ed` truncation stands — **open**.

### Phase 3b — the menu scenarios (**A**, native)

One leaf shot per menu in the tree, each asserted before capture:
`ATTRVIZ_MT_root`, `ATTRVIZ_MT_visualize`, the populated
`ATTRVIZ_MT_domain_*`, `ATTRVIZ_MT_edit` (scope name in the label),
`ATTRVIZ_MT_scope` (counts + radio), and the **instanced-geometry case**, which
needs an object whose mesh domains are empty — a fixture requirement for
Phase 1 that would otherwise be missed.

### Phase 4 — the text generator

Marker-delimited blocks, headless.

### Phase 5 — wire into the docs

README sections plus a gallery page.

### Phase 6 — regression mode

`--check` fails on drift. **Conditional on C7a**, and covering editor and leaf
shots only — cascades are excluded by construction.

### Phase 7 — the arbitrary-row cascade driver (**B'**, external)

**Probably never.** M1 delivered the first-row cascade natively, and doc shots
can be ordered so the interesting row is first. Build only if a specific shot
genuinely needs a non-first row; it carries the whole external-input dependency
and returns docs value but no regression value.

---

---

## Progressive plan — build order, and what proves each step

Every stage ships something runnable and is **gated by a validation that can
fail**. Do not start a stage whose gate depends on an unmeasured primitive.
Shot inventory and doc placement live in [`DOC_MAP.md`](DOC_MAP.md).

### Stage 1 — the runner (Phase 2)

Collapse `probe_menu.py`, `probe_menu2.py`, `probe_panel.py` into one scenario
registry: setup → assert → wait → capture → teardown.

**Gate:** re-produce the six existing shots **byte-identically** from the
registry. Their md5s are already recorded, so this is a real regression test on
day one rather than a smoke test.

### Stage 2 — the unmeasured primitives

| | Question | Gate |
|---|---|---|
| **C2** | how many ticks until overlay ink lands? | ink-diff non-empty at tick N and empty at tick 0 — the count is **measured** |
| **C5** | does an explicit `view_matrix` reproduce framing? | two runs frame identically |
| **C6** | is the exit status gate-able? | forced failure exits non-zero, success zero |

C2 blocks Stages 4 and 6. C6 blocks Stage 9.

### Stage 3 — validate the validator

Before trusting any assertion, **break things on purpose**: disable a
visualizer, empty a scope, point a viz at a missing attribute.

**Gate:** every deliberate break makes the scenario **fail**. An assertion
layer that has never failed is not known to work — and given that the headline
failure mode here is a *plausible wrong image*, this stage is not optional.

### Stage 4 — hero fixture: Suzanne, surface + arrows

**Gate:** arrow ink present *and legible* — a minimum changed-pixel count, not
merely non-zero. Fix the `Torus_Measured` misnomer while in there.

### Stage 5 — annotation, region tier

Boxes from `region.x/y/width/height`. Cheapest, exact, no new primitive.

**Gate:** the drawn box coincides with the region rect to the pixel.

### Stage 6 — annotation, differential widget tier

**Gate:** a derived rect for a known widget matches an independently measured
one, and every derived rect is asserted non-empty, plausibly sized, and inside
its region.

### Stage 7 — callout legend in generated markdown

Numbered markers in the image, words in the generated block.

**Gate:** legend text is generated from the same format strings the panel
draws, never hand-typed.

### Stage 8 — the text generator (Phase 4)

`axes-table`, `panel-tree`, `coverage-line` — see [`DOC_MAP.md`](DOC_MAP.md).

**Gate:** the generated `coverage-line` matches the string in the **captured
panel image** for the same scene. Text and pixels cross-check each other, which
is the strongest check available here.

### Stage 9 — wire into the docs (Phase 5), then regression mode (Phase 6)

**Gate:** `--check` fails on a deliberately edited baseline and passes on a
clean re-run. Editor and leaf-menu shots only — cascades excluded by C7b.

### Kill criteria

- Stage 3 cannot make assertions fail → stop; fix the assertion layer first.
- C2 yields no stable tick count → the arrows shot stays manual and Stage 4
  ships surface-only.
- Derived rects are not reproducible → annotation stops at the region tier,
  which is still worth shipping on its own.

## Open design decision — settle before Phase 1

**One evolving scene with many scenarios, or several small scenes?**

*Recommendation: one scene, many scenarios* — the Playwright fixture model. One
thing to maintain; scenarios isolate by framing, selection and panel state.
Features needing distinct geometry (point clouds, instances, Tags) live in the
same scene, spatially separated and framed individually.

*Argument against:* a scene that must show every Display × Domain × Color
combination gets crowded, and crowded scenes make bad documentation images.

*Middle ground:* one scene, but a scenario may **hide collections it does not
need**. One fixture, clean shots. This is probably the answer, but it is the
next agent's call to make explicitly rather than drift into.

---

## Risks and known-awkward

- **A window opens on the operator's desktop.** Unavoidable. Mitigate with
  fixed geometry and auto-quit. This will never be as silent as the test sweep.
- **Timing is fiddly.** The capture must land *after* a redraw, not at
  script-run time. C2 measures it; do not hardcode a guess.
- **The RMB menu is transient by nature** — now addressed rather than deferred;
  see *The RMB menu*. The residual risk is **M1a**: if `bpy.app.timers` do not
  fire while a popup handler is active, every menu shot needs the external
  driver, not merely the cascade. That is a cost multiplier, not a blocker.
- **Popups die on mouse-move.** A stray hand on the mouse kills a menu shot
  mid-capture. `cursor_warp` puts the real cursor inside the popup to mitigate;
  it cannot fully prevent it. Menu shots are the flakiest thing here.
- **The external driver needs a real, unlocked desktop.** Not CI-able on a
  headless runner — though neither is anything else in this harness.
- **Theme/DPI leakage** is why `--factory-startup` is not optional.
- **A too-early overlay capture is a plausible *wrong* image.** It shows a
  clean surface with no arrows and looks correct; nothing flags it. This is the
  worst failure mode in the project and the reason Stage 3 exists.
- **`_update_ui_expand` is an accordion** — expanding one visualizer closes the
  others, so **no shot can show two expanded at once**. Do not write doc prose
  that implies otherwise.
- **Determinism is unproven** for cascades. Antialiasing, GPU driver differences and font
  hinting may make byte-identical images impossible across machines even if
  they are stable on one. C7 tests one machine; cross-machine is a further
  question and may cap regression mode at "same machine only".

---

## What already exists to build on

| Path | Why |
|---|---|
| `examples/build_attr_scope_scene.py` | scene-built-by-script convention, and prints the assertions a scenario would make |
| `examples/attrviz_scope.blend` | the scene Phase D should use — no new fixture needed |
| `dev_tasks/013_offset_probe/probe.py` | introspection/reporting style for the generate half |
| `tests/test_watch_collection.py` | `--factory-startup` + `av.register()` pattern |
| `attrviz/__init__.py` `visualizers_by_scope`, `active_scope`, `viz_scope` | the panel-state introspection the assertions need |
| `attrviz/gpu_overlay.py` `viz_coverage` | the coverage numbers the generated prose should quote |
| `docs/` | one hand-made `cube_position.png` (to be replaced) and `explorations.md` |
| `docs/img/` | **three generated shots already promoted** — panel, cascade, scope menu |
| `dev_tasks/015_docs_capture/probe_menu*.py`, `probe_panel.py` | the working capture code; Stage 1 collapses them into the runner |
| `dev_tasks/015_docs_capture/DOC_MAP.md` | shot inventory and which doc section each feeds |
| `dev_tasks/015_docs_capture/FINDINGS_M1.md` | measured API behaviour; read before assuming anything about popups |
| `obj.attrviz_ui_expand` / `coll.attrviz_scope_expand` | panel expansion is **property-backed**, so panel state is scriptable and assertable |

---

## Not in scope

- Replacing the headless test suites. This harness covers the draw boundary
  they cannot reach; it does not replace them.
- Video or animation capture.
- ~~Automating the RMB menu shot~~ — **moved into scope 2026-08-23.** Leaf
  content is Phase 3b; the cascade is Phase 7.
- Cross-machine image determinism. C7a tests one machine; regression mode may
  be capped at "same machine only".
