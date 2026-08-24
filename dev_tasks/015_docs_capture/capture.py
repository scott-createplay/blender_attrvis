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
# Ticks allowed per rung of a menu walk: warp, three re-nudges, then room for
# the submenu to animate open before the next rung is located.
WALK_STEP_TICKS = 18

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


def draw_hud(path, lines, scale=2, margin=18, leading=5, corner="bottom"):
    """Stamp a caption into the image, right-aligned.

    The lines are DERIVED from live state by the scenario, never typed here —
    a hand-written caption is the same drift as a hand-written README figure,
    except harder to notice because it is baked into a picture.

    Right-hand side, because every menu and popup in these shots opens toward
    the upper LEFT (the cursor sits a third across), so the right edge is the
    reliably empty one.
    """
    frame, _size = load_rgba(path)
    row_h = bitfont.GLYPH_H * scale
    total = len(lines) * row_h + (len(lines) - 1) * leading
    top = (margin if corner == "top"
           else frame.shape[0] - margin - total)
    for i, line in enumerate(lines):
        width = (len(line) * (bitfont.GLYPH_W + 1) - 1) * scale
        x = frame.shape[1] - margin - width
        bitfont.draw_text(frame, line, x, top + i * (row_h + leading),
                          scale=scale)
    save_rgba(frame, path)
    return list(lines)


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
            if self.shot["kind"] == "filmstrip":
                self.steps = [lbl for lbl, _fn in self.shot["stages"]]
            elif self.shot.get("matrix_styles"):
                self.combos = [(st, d)
                               for st in self.shot["matrix_styles"]
                               for d in node_builder.DISPLAYS]
                self.steps = [f"{st}  {d}" for st, d in self.combos]
            else:
                self.steps = list(node_builder.DISPLAYS)
            self.cell_idx = 0
            self.cell_paths = []
            self.pending_set = True
            self.pre_hash = None
        area = ctx["area"]
        self.walk_prev = None
        self.walk_right = None
        if self.shot.get("cursor") == "highleft":
            # Four menus grow rightward off one row. Start well left, or
            # Blender runs out of room and flips a submenu back to the left,
            # which scrambles the reading order of the breadcrumb.
            self.cx = area.x + area.width // 9
            # Leave headroom. A menu that does not fit gets CLAMPED to the
            # area edge, and a clamped popup stops responding to cursor_warp
            # — the walk computes the right row and Blender ignores it. The
            # object context menu is ~650px tall with a title row above the
            # cursor, so open well below the top.
            self.cy = area.y + area.height - 180
        elif self.shot.get("cursor") == "high":
            # A long context menu hangs DOWN from the cursor, and its
            # submenus open from whichever row is hovered. Opening near the
            # top leaves the AttrViz row high enough that the cascade below it
            # is not reflowed against the window edge.
            self.cx = area.x + area.width // 3
            self.cy = area.y + area.height - 70
        elif self.shot.get("cursor") == "left":
            # A cascade grows right and down: start near the top-left so four
            # menus have somewhere to go.
            self.cx = area.x + 40
            self.cy = area.y + area.height - 90
        elif self.shot.get("cursor") == "center":
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

    def probe_shot(self, tag):
        path = os.path.join(OUT_DIR, f"_{tag}_{self.scen['name']}.png")
        with self._override():
            bpy.ops.screen.screenshot_area(filepath=path)
        return path

    def verify_leaf(self, probe):
        """Did the final hover land on the attribute row?

        No submenu opens from a leaf, so the proof is the highlight moving
        inside that menu's own rect. Without it a failed last rung silently
        reproduces the old picture — the domain category highlighted, which is
        exactly the image this rung exists to replace.
        """
        base, _sb = load_rgba(self.leaf_baseline)
        cur, _sc = load_rgba(probe)
        x0, y0, x1, y1 = self.leaf_rect
        mask = (np.abs(base[:, :, :3] - cur[:, :, :3]) > 0.02).any(axis=2)
        inside = mask[y0:y1 + 1, x0:x1 + 1]
        changed = int(inside.sum())
        report["leaf_highlight_px"] = changed
        if changed < 600:
            raise RuntimeError(
                f"final hover did not land: only {changed}px changed inside "
                "the attribute menu, so no row highlighted")

    def verify_hover(self, probe):
        """Did the hover actually take?

        Without this the failure is SILENT: the shot comes back with the first
        row highlighted and no submenu, exit code 0, and a wrong picture ships.
        Hovering the AttrViz row opens its submenu to the right, so new ink
        past the parent menu's edge is the proof. Loud failure lets the driver
        retry.
        """
        base, _sb = load_rgba(self.hover_baseline)
        cur, _sc = load_rgba(probe)
        mask = (np.abs(base[:, :, :3] - cur[:, :, :3]) > 0.02).any(axis=2)
        mask[:, :self.hover_right + 6] = False
        changed = int(mask.sum())
        report["hover_submenu_px"] = changed
        if changed < 400:
            raise RuntimeError(
                f"hover did not take: only {changed}px of new ink past the "
                "menu, so no submenu opened and the first row is still "
                "highlighted")

    def _diff_bbox(self, prev_path, cur_path, min_x=None):
        """Where did new ink appear between these two frames?

        Restricting to x > min_x isolates the submenu that just opened from
        the parent row's highlight changing at the same moment.
        """
        a, _sa = load_rgba(prev_path)
        b, _sb = load_rgba(cur_path)
        mask = (np.abs(a[:, :, :3] - b[:, :, :3]) > 0.02).any(axis=2)
        if min_x:
            mask[:, :min_x] = False
        if not mask.any():
            raise RuntimeError("no new menu appeared to hover")
        ys, xs = np.nonzero(mask)
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())

    def hover_step(self, index):
        """Hover one rung of the cascade.

        Every menu is located by diffing against the frame before it opened —
        never by counting rows or hardcoding pixels, so the walk survives
        Blender or AttrViz changing what is in these menus.
        """
        sel = self.shot["hover_path"][index]
        cur = self.probe_shot(f"walk{index}")
        x0, y0, _x1, y1 = self._diff_bbox(
            self.walk_prev, cur,
            min_x=(self.walk_right + 6) if self.walk_right else None)
        if index == 0 and y1 >= self.ctx["area"].height - 24:
            # Diagnose the silent failure instead of photographing it.
            raise RuntimeError(
                f"menu is clamped to the area top (top={y1}, area height="
                f"{self.ctx['area'].height}); a clamped popup ignores "
                "cursor_warp. Open it lower or use a taller window.")
        if sel == "last":
            img_y = y0 + int(self.pitch * 0.8)
        elif sel < 0:
            # Counted from the BOTTOM. The attribute list is not uniform rows —
            # "Intrinsic" and "Attributes" section labels sit between the
            # entries, so a top-relative index lands on a header. The real
            # attributes are always the last entries, so -1 and -2 stay
            # correct however many intrinsics appear above them.
            img_y = y0 + int(self.pitch * 0.8) + (abs(sel) - 1) * self.pitch
        else:
            # Rows run downward from the top edge; submenus have no title row.
            img_y = y1 - int((sel + 0.5) * self.pitch)
        area = self.ctx["area"]
        target = (area.x + x0 + int(self.pitch * 1.6), area.y + img_y)
        self.hover_target = target
        self.nudge_index = 0
        self.ctx["window"].cursor_warp(*target)
        self.walk_prev = cur
        self.walk_right = _x1
        if index == len(self.shot["hover_path"]) - 1:
            # The final rung is a LEAF: hovering an attribute opens nothing, so
            # "a submenu appeared" cannot prove it took. Keep the frame and the
            # rect so the highlight moving inside this menu can be checked
            # instead.
            self.leaf_baseline = cur
            self.leaf_rect = (x0, y0, _x1, y1)
        report.setdefault("walk", []).append(
            {"step": index, "select": sel, "cursor": list(target),
             "bbox": [x0, y0, _x1, y1]})
        print(f"[capture] walk {index} -> {sel} at {target}")

    def hover_last_row(self):
        """Put the highlight on the LAST entry of an open menu.

        A menu opens with its FIRST row under the cursor, which is why the
        object context menu photographs with "Shade Smooth" highlighted. The
        row we want is AttrViz, at the bottom.

        The row's position is derived, not guessed: diff the open menu against
        the frame before it opened, and the changed-pixel bbox IS the menu
        rect. Its lower edge plus half a row is the last entry.

        Steering was racy when the highlighted row had a submenu already open
        (Blender holds the parent while the cursor moves toward it). The first
        row here has no submenu, so there is no safety triangle to fight.
        """
        base, (_bw, bh) = load_rgba(self.base_before)
        probe_path = self.probe_shot("menuprobe")
        cur, _size = load_rgba(probe_path)
        mask = (np.abs(base[:, :, :3] - cur[:, :, :3]) > 0.02).any(axis=2)
        if not mask.any():
            raise RuntimeError("menu did not draw; cannot locate its rows")
        ys, xs = np.nonzero(mask)
        # Image rows are bottom-up, so ys.min() is the menu's LOWER edge.
        bottom_img = int(ys.min())
        left_img = int(xs.min())
        area = self.ctx["area"]
        y = area.y + bottom_img + int(self.pitch * 0.55)
        x = area.x + left_img + int(self.pitch * 1.5)
        self.hover_target = (x, y)
        self.nudge_index = 0
        # Store the PATH: verify_hover re-loads it. Storing the decoded array
        # here made every verification throw, which looked exactly like the
        # environmental flake it was meant to diagnose.
        self.hover_baseline = probe_path
        self.hover_right = int(xs.max())
        self.ctx["window"].cursor_warp(x, y)
        report["hover_last_row"] = {"menu_bbox_img": [left_img, bottom_img],
                                    "cursor": [x, y]}
        print(f"[capture] hover last row at ({x}, {y})")

    def walk_tick(self, t, plan):
        """Schedule the walk: one step, then re-nudges, then the next step.

        The re-nudges matter as much here as they did for the single hover —
        the first warp lands while the submenu is still animating open, and a
        cursor that stops moving never asks Blender to re-evaluate the row.
        """
        span = WALK_STEP_TICKS
        start = plan["open"] + 4
        for k in range(len(self.shot["hover_path"])):
            base = start + k * span
            if t == base:
                self.hover_step(k)
                return
            if t in (base + 2, base + 4, base + 6, base + 8, base + 10):
                self.renudge(t)
                return

    # Cursor path for re-nudging, in rows above the target. A one-pixel
    # jitter proved too small to be reliable when several Blender windows are
    # opened back to back: the hover took when run alone and not in a batch.
    # Crossing whole rows and landing back on the target is a motion Blender
    # cannot coalesce away. The sequence ENDS on the target.
    NUDGE_ROWS = (2.0, 0.0, 1.0, 0.0, 0.0)

    def renudge(self, index):
        """Re-warp along a path that ends on the target row.

        One warp is not enough: the menu is still animating open when the
        first move lands, and afterwards a stationary cursor at a new position
        never produces another motion event — so Blender keeps the row it
        highlighted at open time.
        """
        if not getattr(self, "hover_target", None):
            return
        x, y = self.hover_target
        step = self.nudge_index % len(self.NUDGE_ROWS)
        self.nudge_index += 1
        offset = int(self.NUDGE_ROWS[step] * self.pitch)
        self.ctx["window"].cursor_warp(x, y + offset)

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
        elif self.shot.get("matrix_styles"):
            # Type and Colour are independent axes. Varying one while pinning
            # the other taught that Surface *means* Heat, which is false.
            style, display = self.combos[index]
            viz = bpy.data.objects[self.shot["viz"]]
            viz.attrviz_style = style
            viz.attrviz_display = display
        else:
            bpy.data.objects[self.shot["viz"]].attrviz_display =                 self.steps[index]

    def finish_tableau(self):
        if self.shot["kind"] == "filmstrip":
            cols = len(self.steps)
        elif self.shot.get("matrix_styles"):
            # One row per Colour, one column per Type.
            cols = len(node_builder.DISPLAYS)
        else:
            cols = None
        canvas, grid = compose_tableau(self.cell_paths, self.steps, cols=cols)
        raw = os.path.join(OUT_DIR, self.scen["name"] + ".png")
        save_rgba(canvas, raw)
        hud = self.shot.get("hud")
        if hud:
            report["hud"] = draw_hud(
                raw, hud(self.ctx),
                corner=self.shot.get("hud_corner", "bottom"))
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
            if self.shot.get("hover") == "last":
                self.verify_hover(probe)
            elif getattr(self, "leaf_baseline", None):
                self.verify_leaf(probe)
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
        hud = self.shot.get("hud")
        if hud:
            report["hud"] = draw_hud(
                raw, hud(self.ctx),
                corner=self.shot.get("hud_corner", "bottom"))
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
            if t == 0 and self.shot.get("hover") or                     (t == 0 and self.shot.get("hover_path")):
                # Park the pointer inside this window immediately. A scenario
                # that never warps leaves the OS cursor wherever it was, and
                # the next window can come up without the pointer over it —
                # after which its popups ignore cursor_warp entirely. This is
                # why steered menus passed alone and failed in a batch that
                # began with a scenario that does not warp.
                self.ctx["window"].cursor_warp(self.cx, self.cy)
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
            elif "open" in plan and t == plan["open"] - 1:
                # The frame before the menu exists, so its rect can be found.
                self.base_before = self.probe_shot("premenu")
                self.walk_prev = self.base_before
            elif "open" in plan and t == plan["open"]:
                self.open_menu()
            elif self.shot.get("hover") == "last" and                     t == plan["open"] + 4:
                self.hover_last_row()
            elif self.shot.get("hover") == "last" and                     t in (plan["open"] + 7, plan["open"] + 9,
                          plan["open"] + 11, plan["open"] + 13,
                          plan["open"] + 15):
                self.renudge(t)
            elif self.shot.get("hover_path") and t < plan["shot"]:
                self.walk_tick(t, plan)
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
