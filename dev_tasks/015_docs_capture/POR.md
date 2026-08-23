# POR: a Playwright for Blender — scripted scenarios that document the addon

**Parent / history:** no single parent. Prompted by the README rewrite for
[`../011_viz_scope/POR.md`](../011_viz_scope/POR.md), where the panel became a
collection tree and every screenshot and prose description in the docs silently
went stale. Also by a support round-trip in which "we lost the nested
collections in the panel" turned out to be a stale module — a baseline image
would have answered it in one command.
**Status:** designed, **nothing built**. Phase D not yet run.
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
cropping mechanism.

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
| **C3** | Does `--factory-startup` + `av.register()` give a reachable Viz tab? | sidebar opens, Viz tab selectable from script |
| **C4** | Is window geometry settable and stable? | two runs produce identical pixel dimensions |
| **C5** | Does an explicit `view_matrix` reproduce framing exactly? | two runs frame identically |
| **C6** | Does Blender exit cleanly with a status we can gate on? | non-zero on failure, zero on success |
| **C7** | **Are two runs of the same scenario byte-identical?** | hash match |

**C7 decides whether Phase 6 exists.** Deterministic images mean real
assertions; non-deterministic means this is a generator only and drift is
caught by eye. Do not design the regression mode before C7 answers.

### Phase 1 — `examples/docs_demo.blend`, built by script

Generated, **never hand-saved**, or it rots into an opaque binary that drifts
from the addon. `examples/build_attr_scope_scene.py` is the template and the
existing convention.

### Phase 2 — the runner

Scenario registry, setup → wait → assert → capture → teardown. Small.

### Phase 3 — the first three scenarios

The surfaces that changed most recently and that were hand-documented wrongly:

- **Viz panel** with collection groups, per-collection toggles, counts
- **Outliner** showing `attrvis` / `attrvis_curvature` / `Visualizers`
- **Viewport** with arrows on two objects and the non-carrier untouched

### Phase 4 — the text generator

Marker-delimited blocks, headless.

### Phase 5 — wire into the docs

README sections plus a gallery page.

### Phase 6 — regression mode

`--check` fails on drift. **Conditional on C7.**

---

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
- **The RMB menu is the hard case.** Menus are transient. `wm.call_menu` opens
  one but the screenshot may fire after it closes. **Leave that shot manual
  initially** rather than pretending it is solved.
- **Theme/DPI leakage** is why `--factory-startup` is not optional.
- **Determinism is unproven.** Antialiasing, GPU driver differences and font
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
| `docs/` | currently one hand-made `cube_position.png` and `explorations.md` |

---

## Not in scope

- Replacing the headless test suites. This harness covers the draw boundary
  they cannot reach; it does not replace them.
- Video or animation capture.
- Automating the RMB menu shot (see Risks).
