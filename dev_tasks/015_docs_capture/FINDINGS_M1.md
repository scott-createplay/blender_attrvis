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
