"""The capture engine — runs ONE scenario, inside a real Blender window.

  setup -> assert -> wait for a real redraw -> capture -> teardown

One scenario per launch, deliberately: that is the shape that proved
deterministic in M1, and it keeps a scenario's preference changes from leaking
into the next one.

Invoked by `run_captures.py`, which is the thing you actually run. Directly:

  ATTRVIZ_SCENARIO=menu_scope blender --factory-startup -p 60 60 1600 900 \
      examples/attrviz_scope.blend --python dev_tasks/015_docs_capture/capture.py

Exit code is meaningful (C6): 0 on success, 1 on any assertion or capture
failure. `os._exit` is used because a timer callback cannot influence
Blender's own exit status — see `_finish`.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback

import bpy
import numpy as np

REPO = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.join(REPO, "dev_tasks", "015_docs_capture")
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

import attrviz as av  # noqa: E402
from attrviz import node_builder  # noqa: E402

import bitfont  # noqa: E402
import scenarios  # noqa: E402

NAME = os.environ["ATTRVIZ_SCENARIO"]
OUT_DIR = os.environ.get("ATTRVIZ_OUT", os.path.join(HERE, "out", "stage1"))

# Settle policy: poll every SETTLE_EVERY ticks, require SETTLE_NEEDED
# consecutive identical frames, give up after SETTLE_MAX_POLLS.
SETTLE_EVERY = 3
SETTLE_NEEDED = 2
SETTLE_MAX_POLLS = 40

# Blender draws a 1px outline around the editor area, and its colour depends on
# which area is active at capture time — the ONLY thing that differed between
# two runs of menu_edit (4138 changed px vs a 4146px perimeter). It is chrome
# no doc image wants. Trim it.
INSET = 1

report = {"scenario": NAME, "ok": False, "assertions": {}, "errors": []}


def fail(step, exc):
    report["errors"].append({"step": step, "error": repr(exc),
                             "trace": traceback.format_exc()})
    print(f"[capture] FAIL {step}: {exc!r}")


def find_view3d():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                return win, area, {r.type: r for r in area.regions}
    raise RuntimeError("no VIEW_3D area in the loaded screen")


def apply_prefs(prefs):
    view = bpy.context.preferences.view
    applied = {}
    for key, val in prefs.items():
        setattr(view, key, val)
        # Read back: open_sublevel_delay clamps to a minimum of 1, so what we
        # asked for is not necessarily what we got.
        applied[key] = getattr(view, key)
    return applied


# --------------------------------------------------------------------------
# image helpers
# --------------------------------------------------------------------------
def load_rgba(path):
    img = bpy.data.images.load(path, check_existing=False)
    width, height = img.size
    buf = np.empty(width * height * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return buf.reshape(height, width, 4), (width, height)


def save_rgba(arr, path):
    height, width = arr.shape[0], arr.shape[1]
    img = bpy.data.images.new("out", width=width, height=height, alpha=True)
    img.pixels.foreach_set(arr.reshape(-1))
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


def inset_image(path, px):
    """Trim px from every edge — removes the unstable active-area outline."""
    frame, (iw, ih) = load_rgba(path)
    if iw <= 2 * px or ih <= 2 * px:
        raise ValueError(f"image {(iw, ih)} too small to inset by {px}")
    sub = frame[px:ih - px, px:iw - px, :]
    save_rgba(sub, path)
    return [sub.shape[1], sub.shape[0]]


def ink_pixels(path, min_sat=0.15):
    """Count saturated pixels — the overlay's own ink.

    C2 in a form that needs no second capture: Blender's viewport, its grid
    and untouched geometry are all grey (saturation ~0), while a Heat ramp or
    an RGB normal field is vivid. A too-early capture shows a clean grey frame
    and *looks correct*, so counting ink is what separates "drew" from
    "drew nothing".
    """
    frame, _size = load_rgba(path)
    rgb = frame[:, :, :3]
    sat = rgb.max(axis=2) - rgb.min(axis=2)
    return int((sat > min_sat).sum())


def content_pixels(rgb, thresh=0.06):
    """Pixels that differ from the cell's own background.

    Saturation alone is the wrong oracle for a tableau: Tags draws BLF text
    that may be near-white, i.e. unsaturated. Comparing against the median
    colour catches both vivid ink and pale text.
    """
    median = np.median(rgb.reshape(-1, 3), axis=0)
    return int((np.abs(rgb - median).max(axis=2) > thresh).sum())


def compose_tableau(cell_paths, labels, gutter=6, label_scale=3, cols=None):
    """Grid the cells. Columns are derived, never hardcoded — adding a Display
    type must change this image without anyone editing a layout constant."""
    import math
    frames = [load_rgba(p)[0] for p in cell_paths]
    height, width = frames[0].shape[0], frames[0].shape[1]
    count = len(frames)
    if cols is None:
        cols = int(math.ceil(math.sqrt(count)))
    rows = int(math.ceil(count / float(cols)))

    canvas_h = rows * height + (rows + 1) * gutter
    canvas_w = cols * width + (cols + 1) * gutter
    canvas = np.zeros((canvas_h, canvas_w, 4), dtype=np.float32)
    canvas[:, :, :3] = 0.10
    canvas[:, :, 3] = 1.0

    placed = []
    for i, frame in enumerate(frames):
        r, c = divmod(i, cols)
        x0 = gutter + c * (width + gutter)
        # Rows count from the top for a reader; arrays are bottom-up.
        y0 = gutter + (rows - 1 - r) * (height + gutter)
        canvas[y0:y0 + height, x0:x0 + width, :] = frame
        placed.append((labels[i], r, c))

    for i, (label, r, c) in enumerate(placed):
        x0 = gutter + c * (width + gutter)
        y_top = gutter + r * (height + gutter)
        bitfont.draw_text(canvas, label.upper(), x0 + 14, y_top + 14,
                          scale=label_scale)
    return canvas, (rows, cols)


def apply_view(ctx, view):
    """C5: frame by explicit numbers, never by view_selected.

    view_selected depends on selection and saved state — exactly the drift
    this harness exists to kill. location / rotation / distance fully
    determine the view and are readable in the registry.
    """
    import math
    from mathutils import Euler, Vector
    space = next(s for s in ctx["area"].spaces if s.type == 'VIEW_3D')
    r3d = space.region_3d
    r3d.view_perspective = 'PERSP'
    r3d.view_location = Vector(view["location"])
    r3d.view_rotation = Euler(
        [math.radians(a) for a in view["rotation_deg"]], 'XYZ').to_quaternion()
    r3d.view_distance = float(view["distance"])
    return {"view_location": list(view["location"]),
            "view_rotation_deg": list(view["rotation_deg"]),
            "view_distance": float(view["distance"])}


def apply_overlays(ctx, flags):
    """Turn off the studio furniture — grid, cursor, gizmos, text."""
    space = next(s for s in ctx["area"].spaces if s.type == 'VIEW_3D')
    for key, val in flags.items():
        target = space.overlay if hasattr(space.overlay, key) else space
        setattr(target, key, val)
    return dict(flags)


def crop_to_region(src, dst, region, area):
    """Crop by the region rect. Origin is bottom-left, Blender's pixel order."""
    frame, (iw, ih) = load_rgba(src)
    x0 = max(0, region.x - area.x)
    y0 = max(0, region.y - area.y)
    x1 = min(iw, x0 + region.width)
    y1 = min(ih, y0 + region.height)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"empty crop rect for region in image {(iw, ih)}")
    sub = frame[y0:y1, x0:x1, :]
    save_rgba(sub, dst)
    return sub.shape[1], sub.shape[0]


# --------------------------------------------------------------------------
# the tick machine
# --------------------------------------------------------------------------
class Capture:
    def __init__(self, scen, ctx):
        self.scen = scen
        self.ctx = ctx
        self.shot = scen["shot"]
        self.ticks = self.shot["ticks"]
        self.pitch = int(round(20 * bpy.context.preferences.system.ui_scale))
        self.tick = 0
        self.last_hash = None
        self.stable = 0
        self.settle_polls = 0
        self.settle_from = self.ticks["shot"]
        if self.shot["kind"] in ("tableau", "filmstrip"):
            self.steps = ([lbl for lbl, _fn in self.shot["stages"]]
                          if self.shot["kind"] == "filmstrip"
                          else list(node_builder.DISPLAYS))
            self.cell_idx = 0
            self.cell_paths = []
            self.pending_set = True
            self.pre_hash = None
        area = ctx["area"]
        if self.shot.get("cursor") == "center":
            self.cx = area.x + area.width // 2
            self.cy = area.y + area.height // 2
        else:  # "third" — opens left of centre so a cascade stays in the area
            self.cx = area.x + area.width // 3
            self.cy = area.y + (2 * area.height) // 3

    def _override(self):
        return bpy.context.temp_override(
            window=self.ctx["window"], area=self.ctx["area"],
            region=self.ctx["regions"].get("WINDOW"))

    def open_menu(self):
        self.ctx["window"].cursor_warp(self.cx, self.cy)
        with self._override():
            res = bpy.ops.wm.call_menu(name=self.shot["menu"])
        report["call_menu"] = list(res)

    def nudge(self, index):
        jitter = 1 if index % 2 else 0
        self.ctx["window"].cursor_warp(self.cx + 12 + jitter, self.cy)

    def tableau_step(self, t):
        """One cell per Display type, then composite.

        The cell list comes from node_builder.DISPLAYS, so a new visualizer
        type joins the tableau on its own — and fails the shot if it draws
        nothing.
        """
        if self.pending_set:
            name = self.steps[self.cell_idx]
            # Hash the frame BEFORE the switch. Settling alone is not enough
            # here: immediately after setting the property nothing has
            # redrawn yet, so two identical polls read as "settled" and the
            # cell captures the PREVIOUS display. That is exactly what
            # happened — cell 0 came back byte-identical to cell 2.
            pre = os.path.join(OUT_DIR, f"_pre_{self.scen['name']}.png")
            with self._override():
                bpy.ops.screen.screenshot_area(filepath=pre)
            with open(pre, "rb") as fh:
                self.pre_hash = hashlib.md5(fh.read()).hexdigest()
            self.apply_step(self.cell_idx)
            self.ctx["area"].tag_redraw()
            self.pending_set = False
            self.last_hash, self.stable, self.settle_polls = None, 0, 0
            self.settle_from = t + 1
            print(f"[capture] cell {self.cell_idx}: {name}")
            return
        if (t - self.settle_from) % SETTLE_EVERY:
            return
        probe = os.path.join(OUT_DIR,
                             f"_cell_{self.scen['name']}_{self.cell_idx}.png")
        with self._override():
            bpy.ops.screen.screenshot_area(filepath=probe)
        with open(probe, "rb") as fh:
            digest = hashlib.md5(fh.read()).hexdigest()
        self.stable = self.stable + 1 if digest == self.last_hash else 0
        self.last_hash = digest
        self.settle_polls += 1

        if digest == self.pre_hash:
            # The switch has not landed yet. Keep waiting rather than
            # photographing the display we just left.
            self.stable = 0
        elif self.stable >= SETTLE_NEEDED:
            inset_image(probe, INSET)
            self.cell_paths.append(probe)
            self.cell_idx += 1
            self.pending_set = True
            if self.cell_idx >= len(self.steps):
                self.finish_tableau()
            return
        if self.settle_polls > SETTLE_MAX_POLLS:
            raise RuntimeError(
                f"cell {self.steps[self.cell_idx]!r} never settled, or "
                "renders identically to the display before it")

    def apply_step(self, index):
        if self.shot["kind"] == "filmstrip":
            _label, fn = self.shot["stages"][index]
            report["assertions"].update(fn(self.ctx) or {})
            # A stage may change the editor type, which invalidates regions.
            self.ctx["regions"] = {
                r.type: r for r in self.ctx["area"].regions}
        else:
            bpy.data.objects[self.shot["viz"]].attrviz_display =                 self.steps[index]

    def finish_tableau(self):
        cols = len(self.steps) if self.shot["kind"] == "filmstrip" else None
        canvas, grid = compose_tableau(self.cell_paths, self.steps, cols=cols)
        raw = os.path.join(OUT_DIR, self.scen["name"] + ".png")
        save_rgba(canvas, raw)
        report["grid"] = list(grid)
        report["cells"] = list(self.steps)

        min_ink = self.shot.get("min_cell_px", 0)
        per_cell = {}
        for name, path in zip(self.steps, self.cell_paths):
            rgb = load_rgba(path)[0][:, :, :3]
            per_cell[name] = content_pixels(rgb)
        report["cell_content_px"] = per_cell
        empty = [k for k, v in per_cell.items() if v < min_ink]
        if empty:
            raise AssertionError(
                f"these Display types drew nothing: {empty} "
                f"(counts {per_cell}, floor {min_ink})")
        report["assertions"].update(
            self.scen["assertions"](self.ctx) or {})
        report["image"] = raw
        report["ok"] = True
        print(f"[capture] tableau {grid[0]}x{grid[1]} {per_cell}")

    def settle(self, t):
        """Wait until the frame stops changing, then shoot.

        A fixed tick count is a guess, and it was wrong: the viewport uses
        temporal antialiasing, so an early shutter catches a partly-converged
        frame. Two scenarios were byte-stable only by luck of where their tick
        landed. Poll instead — capture, hash, and require SETTLE_NEEDED
        consecutive identical frames. This is `waitForLoadState('networkidle')`
        for a viewport, and it also gives the overlay time to actually draw.
        """
        if (t - self.shot["ticks"]["shot"]) % SETTLE_EVERY:
            return
        probe = os.path.join(OUT_DIR, "_settle_" + self.scen["name"] + ".png")
        with self._override():
            bpy.ops.screen.screenshot_area(filepath=probe)
        with open(probe, "rb") as fh:
            digest = hashlib.md5(fh.read()).hexdigest()

        if digest == self.last_hash:
            self.stable += 1
        else:
            self.stable = 0
        self.last_hash = digest
        self.settle_polls += 1

        if self.stable >= SETTLE_NEEDED:
            report["settle_polls"] = self.settle_polls
            report["settle_tick"] = t
            # Re-read regions: the UI region only exists once the sidebar has
            # been revealed, so anything cached at setup is stale.
            self.ctx["regions"] = {
                r.type: r for r in self.ctx["area"].regions}
            # Assert immediately before the shutter: the state that matters is
            # the state being photographed, not the state at script-run time.
            report["assertions"].update(
                self.scen["assertions"](self.ctx) or {})
            self.capture(probe)
            report["ok"] = True
            return

        if self.settle_polls > SETTLE_MAX_POLLS:
            raise RuntimeError(
                f"frame never settled after {self.settle_polls} polls — "
                "something is animating, or the overlay never finished")

    def capture(self, settled_png):
        raw = os.path.join(OUT_DIR, self.scen["name"] + ".png")
        os.replace(settled_png, raw)
        crop = self.shot.get("crop")
        if crop:
            region = self.ctx["regions"].get(crop)
            if region is None or region.width <= 1:
                raise RuntimeError(f"no {crop} region to crop to")
            w, h = crop_to_region(raw, raw, region, self.ctx["area"])
            report["crop"] = [w, h]
        report["inset"] = inset_image(raw, INSET)
        min_ink = self.shot.get("min_ink_px")
        if min_ink:
            ink = ink_pixels(raw)
            report["ink_px"] = ink
            if ink < min_ink:
                raise AssertionError(
                    f"only {ink} saturated px, need {min_ink} — the overlay "
                    "did not draw, and a grey frame looks correct")
            print(f"[capture] ink={ink} px (min {min_ink})")
        report["image"] = raw
        print(f"[capture] wrote {raw}")

    def __call__(self):
        t = self.tick
        self.tick += 1
        try:
            plan = self.ticks
            if t == 0 and self.shot.get("view"):
                report["assertions"].update(
                    apply_view(self.ctx, self.shot["view"]))
                if self.shot.get("overlays"):
                    report["assertions"].update(
                        apply_overlays(self.ctx, self.shot["overlays"]))
                self.ctx["area"].tag_redraw()
            elif "reveal" in plan and t == plan["reveal"]:
                report["assertions"].update(
                    self.scen["setup"](self.ctx) or {})
            elif "open" in plan and t == plan["open"]:
                self.open_menu()
            elif t in plan.get("nudges", ()):
                self.nudge(plan["nudges"].index(t))
            elif t >= plan["shot"] and self.shot["kind"] in (
                    "tableau", "filmstrip"):
                self.tableau_step(t)
                if report["ok"]:
                    _finish()
                    return None
            elif t >= plan["shot"]:
                self.settle(t)
                if report["ok"]:
                    _finish()
                    return None
        except Exception as exc:  # noqa: BLE001
            fail(f"tick_{t}", exc)
            _finish()
            return None
        return 0.05


def _finish():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, NAME + ".json"), "w",
              encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    status = "ok" if report["ok"] else "FAILED"
    print(f"[capture] {NAME}: {status}")
    sys.stdout.flush()
    sys.stderr.flush()
    # C6: a timer callback cannot set Blender's exit status, and
    # wm.quit_blender() always exits 0. os._exit gives a gate-able code. The
    # PNG and the report are already flushed to disk, so skipping Blender's
    # own teardown costs nothing here.
    os._exit(0 if report["ok"] else 1)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    try:
        scen = scenarios.by_name(NAME)
        av.register()
        report["prefs"] = apply_prefs(scen.get("prefs", {}))

        win, area, regions = find_view3d()
        ctx = {"window": win, "area": area, "regions": regions, "scen": scen}
        report["area"] = [area.x, area.y, area.width, area.height]

        # Panel scenarios reveal on a tick (the sidebar must exist before the
        # regions are re-read); everything else sets up now.
        if "reveal" not in scen["shot"]["ticks"]:
            report["assertions"].update(scen["setup"](ctx) or {})

        bpy.app.timers.register(Capture(scen, ctx), first_interval=0.1)
    except Exception as exc:  # noqa: BLE001
        fail("setup", exc)
        _finish()


main()
