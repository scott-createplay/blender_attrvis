# M1 + C3 findings — menu and panel capture, measured on Blender 5.2.0

Run 2026-08-23 against `examples/attrviz_scope.blend`, AttrViz 0.5.12,
`--factory-startup -p 60 60 1600 900`, no `--background`.

Probes: [`probe_menu.py`](probe_menu.py) (open + capture),
[`probe_menu2.py`](probe_menu2.py) (steer + determinism),
[`probe_panel.py`](probe_panel.py) (the Viz panel). Images under `out/`.

**Headline: the RMB menu is solved natively. No external driver is needed for
menu content, and no external driver is needed for a first-row cascade.**

---

## Results

| Spike | Question | Result |
|---|---|---|
| **M1a** | Do `bpy.app.timers` fire while a popup is up? | **PASS** — they fire, and captures taken from them see the popup |
| **M1b** | Does the popup survive the script returning? | **PASS** — still open 13 ticks (0.65s) later |
| **M1c** | Does whole-window `screen.screenshot` contain the popup? | **PASS** |
| **M1d** | Does `screenshot_area` contain it? | **PASS — the hypothesis was wrong.** It captures the popup *and* crops to the editor. This is the better shot. |
| **M1e** | Does `cursor_warp` place the popup deterministically? | **PASS** — menu origin identical across runs |
| **M1f** | Can `temp_override` satisfy `ATTRVIZ_MT_visualize.poll`? | **PASS** — menu drew real attributes |
| **M1g** | Can `cursor_warp` steer to a *chosen* row after opening? | **FAIL — racy.** See *The safety triangle* |
| **C7a** | Are leaf-menu shots byte-identical across runs? | **PASS** — 4/4 menus, md5 match |

## What the API actually does

- **`screenshot_area` captures popups.** The POR assumed a menu, being a
  temporary region overlaying the areas, would be clipped out and that menus
  would need whole-window capture plus an external crop. Measured: the area
  shot contains the full cascade, cropped to the VIEW3D, with no outliner or
  properties chrome. **No external crop step, and no Pillow dependency.**
- **`wm.call_menu` returns `{'INTERFACE'}`** and the popup persists into the
  event loop.
- **`cursor_warp` sets where the menu opens**, and the menu opens with its
  **first row under the cursor**.
- **`open_sublevel_delay` / `open_toplevel_delay` clamp to a minimum of 1**
  (1/10 s). Asking for `0` silently yields `1`. Factory defaults are 5 and 2 —
  the ~200ms submenu delay measured in the first probe.
- `ui_scale` here is **1.5**, so menu row pitch is **30px** (`20 * ui_scale`).

## Determinism has a clean rule

Two runs, md5-compared:

| Menu | Submenu auto-opens? | Byte-identical |
|---|---|---|
| `ATTRVIZ_MT_scope` | no | **yes** |
| `ATTRVIZ_MT_edit` | no | **yes** |
| `ATTRVIZ_MT_domain_face` | no | **yes** |
| `ATTRVIZ_MT_root` | yes | yes (one sample) |
| `ATTRVIZ_MT_visualize` | yes | **no** — differed in 2 of 3 configurations |
| viewport-only area shot | — | **yes** — 0 changed pixels, maxdelta 0.0000 |

**A menu with no auto-opening submenu is deterministic. A menu whose first row
expands a child is racy**, because the sublevel delay cannot be driven below
0.1s and the capture tick may fall either side of it.

This vindicates the C7a/C7b split: gate regression on leaf menus and editor
shots; treat cascades as generator-only.

## The safety triangle — why steering fails

Blender holds the parent row highlighted while the cursor moves *towards* an
open submenu. A `cursor_warp` to another row is therefore often ignored.
Three strategies, none reliable:

| Hover path | Dwell | Outcome |
|---|---|---|
| single warp, straight down (`cx+12`) | 6 ticks | rows 1,2 stuck on Point; row 3 broke out |
| 4 nudges, from the left (`cx-100`) | 14 ticks | **all** rows stuck on Point |
| 4 nudges, straight down (`cx+12`) | 14 ticks | rows 0,1 stuck; rows 2,3 distinct |

Non-repeatable across runs as well as across rows. **Do not build on
cursor-steered rows.**

## The consequence — steering is not needed

`wm.call_menu` takes a `bl_idname`, so **every menu in the tree can be opened
directly**: `ATTRVIZ_MT_domain_face` renders standalone without traversing
`root → visualize → Face`. All four menus tested this way were distinct and
byte-identical across runs.

So the two deliverables resolve as:

| | Mechanism | Status |
|---|---|---|
| **A. Leaf content** — every menu's real content | direct `call_menu` per `bl_idname` | **solved, native, deterministic** |
| **B. Cascade, first row** — parent + expanded child | `cursor_warp` + `call_menu`, no steering | **solved, native, not deterministic** — docs only |
| **B'. Cascade, arbitrary row** | needs real OS input (M3) | **unsolved**; only worth it if a doc shot truly needs a non-first row |

**M2 (the `invoke_popup` fallback) is not needed** — popups timed fine, so the
dialog-chrome compromise can be dropped.

**M3 shrinks from "required for all cascades" to "required only for
non-first-row cascades"**, which may be worth nothing at all: order the doc
shots so the interesting row is first.

## Carried forward

- `-p 60 60 1600 900` gives a stable 1600x900 window — **C4 passes** as a side
  effect. Area was 1309x764 in both runs.
- `show_tooltips = False` is set defensively; tooltips would be transient ink.
- **C6 (exit status) is still unanswered.** `wm.quit_blender()` from a timer
  quits cleanly but the process exit code is not yet gate-able; probes report
  via JSON instead.
- Whether any of this survives the Blender window losing focus is **untested**.
  All runs had it foregrounded.

---

# C3 — the Viz panel

**PASS, and byte-identical across runs.** `probe_panel.py` opens the sidebar,
selects the Viz tab, captures, and crops.

| Question | Result |
|---|---|
| Does `--factory-startup` + `av.register()` give a reachable Viz tab? | **PASS** — `region.active_panel_category == 'Viz'` |
| Is the panel shot deterministic? | **PASS** — `panel_area.png` and `panel_only.png` both md5-identical over two runs |
| Can we crop to the panel without an image library? | **PASS** — the UI region rect is exact; numpy slice inside Blender |

## How

Call the addon's own `av._reveal_viz_panel(context)` rather than hand-rolling
the sidebar setup. The docs then show the panel through the same code path the
addon uses to open it for a first visualizer — if that helper breaks, the shot
breaks, which is the point.

`screenshot_area` captures the whole VIEW3D including the sidebar; the crop to
`UI` uses `region.x/y/width/height` minus `area.x/y`. **No Pillow** — the same
result as the menu case.

## It caught the drift immediately

The captured panel renders:

```
3 objects - Cube_No...ed, Torus_Measured
1 object  -  1 carry curv
```

A **hyphen**. The README shipped `3 objects · 2 carry grad` with a middot. That
is the exact hand-typed error this harness exists to kill, now visible in a
generated image rather than found by re-reading a format string.

## The constraint nobody had written down: panel height

The panel is taller than the sidebar, and **the region does not scroll itself
for a screenshot** — content below the fold is simply absent.

| Window | UI region | Result |
|---|---|---|
| `-p 60 60 1600 900` | 420 x 688 | clipped mid-Display list, `Arrows` cut off |
| `-p 20 20 1600 1250` | 420 x 1012 | reaches the ColorRamp; still a few px short |

So **window height is a scenario parameter, not a constant**, and a scenario
must assert that what it means to show actually fits. A tall window is also
capped by the operator's physical screen, which is a real portability limit on
full-panel shots.

Object names truncate at 420px (`Cube_No...ed`). That is genuine panel UX, but
a docs shot wanting full names needs a wider sidebar — and there is no clean
API to set region width, so this is **open**.

---

# Stage 1 — the runner, and why byte-exactness was the wrong gate

`capture.py` (engine, one scenario per launch), `scenarios.py` (registry),
`run_captures.py` (driver), `compare.py` (pixel diff). The three probes are
superseded.

**Gate: PASS.** All six scenarios capture; the four gated ones match their
baselines at **0 px changed**; both failure paths were verified to actually
fail.

## Byte equality was too strict — and stricter than Playwright

The Stage 1 gate was originally "reproduce byte-identically". It kept failing,
and each fix moved the failure to a different scenario. The measurement that
ended it:

| Pair | Changed px | of |
|---|---|---|
| menu_domain_face, two runs | **36** | 995,934 |
| panel_scope_tree, two runs | **8** | 422,180 |
| menu_scope vs a *different menu* | **4,788** | 995,934 |

Antialiasing noise is ~36px; a real UI change is thousands. Playwright's own
`toHaveScreenshot` compares with `maxDiffPixels`/`threshold`, not byte
equality — the tool being modelled had already settled this. Gate is now
`MAX_DIFF_PX = 200`, roughly 6x the noise floor and 24x below the signal.

## Two real instability sources, found by looking rather than theorising

1. **The 1px active-area outline.** menu_edit differed between runs by exactly
   4138 px — against an area perimeter of 2x(1309+764) = 4146. Blender colours
   that border by which area is active at capture time. It is chrome no doc
   image wants: `INSET = 1` trims it.
2. **Fixed tick counts.** Replaced with a **settle loop** — capture, hash,
   require `SETTLE_NEEDED` consecutive identical frames, then shoot. The
   Playwright analogue is `waitForLoadState('networkidle')`. A tick number is
   a guess; settling is a measurement.

I twice attributed the drift to a wrong cause (viewport TAA convergence, then
assertion perturbation) before rendering a diff image. **Render the diff
first** — it took one look to see the red was only the border.

## `--selfcheck` — new, and it earned its keep immediately

Runs each scenario **twice** and compares. Whether a scenario may be gated is
an empirical question:

- `menu_root` matched its baseline under a single `--check` and was **not**
  stable — one sample is not evidence.
- `menu_edit` did the same thing a run later.

`--check` alone cannot tell "stable" from "lucky". Run `--selfcheck` before
blessing anything.

## C6 — SOLVED

`wm.quit_blender()` always exits 0, and a timer callback cannot set Blender's
exit status. `os._exit(0 if ok else 1)` after flushing gives a gate-able code;
the PNG and report are already on disk, so skipping teardown costs nothing.

Verified both directions: corrupted baseline → exit 1; scene missing the
target object → `KeyError` in setup → exit 1.

## C7a/C7b may collapse — but not on this evidence

Under pixel tolerance the cascades are stable too: `menu_root` 36 px,
`menu_visualize_point` 0 px across two passes. The C7a/C7b split was derived
from *byte* comparison, so it may not survive.

**Left ungated anyway.** The cascade failure mode is bimodal — usually fine,
occasionally the submenu simply is not open, which is a thousands-of-pixels
diff that would fail the gate spuriously. Two samples cannot rule that out.
Re-evaluate with more.

---

# Stage 2 — C5 and C2

## C5 — framing — PASS

Scenarios declare `view: {location, rotation_deg, distance}`, applied to
`region_3d`. **Not `view_selected`**, which depends on selection and saved
state — the drift this harness exists to kill. Both viewport shots are stable
across runs at **0 px changed**.

`CLEAN_OVERLAYS` also turns off floor, axes, cursor, text, stats, gizmos and
selection outlines. Two of those flags are not overlay flags at all:
`show_region_toolbar` / `show_region_header` live on the *space*. With region
overlap on, the toolbar and header **float over the WINDOW region**, so
cropping to that region is not enough to exclude them.

## C2 — overlay ink — PASS, and simpler than designed

The POR designed a differential ink assertion: capture with the visualizer
disabled, then enabled, and require a non-empty diff. **Not needed.** The
viewport, its grid and untouched geometry are all grey; overlay ink is vivid.
So counting **saturated pixels** in the single captured frame answers it with
no second capture:

```
sat = rgb.max(axis=2) - rgb.min(axis=2)
ink = (sat > 0.15).sum()
```

| Shot | Ink | Floor |
|---|---|---|
| `viewport_hero` (Heat surface + RGB arrows) | 127,510 px | 20,000 |
| `viewport_arrows` (arrows only) | 11,213 px | 2,000 |

This is the guard against the project's worst failure mode: a too-early capture
shows a clean grey frame and **looks correct**. `min_ink_px` turns that into an
exit code.

The settle loop from Stage 1 already handles *when* — so C2 never needed a
measured tick count at all. Settling plus an ink floor subsumes it.

## Two behaviours the shots surfaced

**The hero's black box is real.** `gpu_overlay` stashes `display_type` and sets
the watched mesh to `BOUNDS` so it does not z-fight the false-colour surface
(`gpu_overlay.py:223`). Removing it from the hero would misrepresent the addon,
so the framing leaves room for it instead.

**Arrows alone read as a disembodied field.** With the mesh muted to BOUNDS and
no Surface visualizer, `viewport_arrows` shows arrows tracing Suzanne's form
with no form underneath. It is honest, and `Cube_Bare` sitting solid and
untouched beside it is exactly the partial-coverage claim. But **Show
Wireframe** (a modifier socket, `WIRE` instead of `BOUNDS`) would likely read
better — untried.

## Status

Nine scenarios, seven gated, all stable, all at 0 px against baselines.
Remaining from DOC_MAP: `panel_grad_expanded` (S8) and `outliner_registry`
(S10).

---

# The tableau, the spreadsheet, and two things they taught

## `spreadsheet_attributes` — documenting a panel that is not ours

Blender's Spreadsheet, switched in with `area.type = 'SPREADSHEET'`, on the
Evaluated state so GN-authored attributes appear at all.

The caption's claim is **asserted, not trusted to the picture**: the evaluated
mesh stores `['.corner_edge', '.corner_vert', '.edge_verts', 'curv', 'grad',
'position', 'sharp_face']`, while AttrViz offers `['Index', 'Position',
'Normal', 'curv', 'grad']` on Point. So the assertion is exactly:

- `curv` and `grad` **are** stored -> the spreadsheet shows them
- `Normal` is **not** stored -> the spreadsheet cannot show it, and AttrViz
  offers it anyway, computed

The shot reads `Columns: 3` — position, grad, curv. No Normal.

## `tableau_displays` — one attribute, every Type, one image

Cells come from `node_builder.DISPLAYS`, and the grid is
`cols = ceil(sqrt(n))` — **nothing about the layout is hardcoded**, so a new
visualizer type joins the tableau on its own and fails the shot if it draws
nothing (`min_cell_px`).

**The attribute must be a vector.** `Arrows` needs a direction, so a float
would leave that cell empty and the tableau would claim something it cannot
show. `assert_tableau` checks `grad` is `FLOAT_VECTOR` rather than discovering
it as a blank cell.

Labels are baked with `bitfont.py`, a 5x7 font that is *data in the repo*. The
POR argues against baking text into images; a tableau is the exception, since
a grid that does not say which cell is which has failed at its only job. Being
repo data rather than a system font keeps it deterministic.

### Settling can lock onto the frame you just left

The first cell came back **byte-identical to the third**. Setting
`attrviz_display` does not redraw synchronously, so the settle loop found two
identical polls of the *previous* display and called it settled — capturing
Arrows and labelling it Markers.

Fix: hash the frame **before** the switch and refuse to settle until it
differs. Any capture that follows a state change needs this; "the frame stopped
moving" does not imply "the change landed".

### Hiding an object does not remove its overlay ink

`hide_viewport` removed `Torus_Flow`'s mesh from the tableau while its markers,
arrows and tags kept drawing — a floating field of ink beside every cell. To
keep an object out of a shot it must leave the **scope**, not just the
viewport. `_drop_from_scopes` unlinks it.

This is worth knowing outside the harness: hiding a watched object does not
stop AttrViz drawing on it.

### Tags needs a cap to be legible

Default `Tag Cap` is 10000. On 507 points that is a white mass. The scenario
sets 24.
