"""C3 spike — can we capture the AttrViz Viz panel?

The panel is the least-tested surface in the project and the one 011 changed
most recently. M1 settled the menu case; this settles the panel case.

Two shots per run:
  <run>/panel_area.png   the whole VIEW3D, sidebar included
  <run>/panel_only.png   cropped to the UI region, via the region rect

The crop is done with numpy inside Blender — the region rect is known exactly,
so this needs no image library and no guesswork.

Env:
  ATTRVIZ_PROBE_RUN   output subdir (default panel1)

Run:
  blender --factory-startup -p 60 60 1600 900 examples/attrviz_scope.blend \
      --python dev_tasks/015_docs_capture/probe_panel.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback

import bpy
import numpy as np

REPO = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import attrviz as av  # noqa: E402

HERE = os.path.join(REPO, "dev_tasks", "015_docs_capture")
RUN = os.environ.get("ATTRVIZ_PROBE_RUN", "panel1")
OUT = os.path.join(HERE, "out", RUN)

WARMUP = 16
T_REVEAL = WARMUP + 1
T_SHOT = T_REVEAL + 10

report = {"run": RUN, "errors": [], "findings": {}}


def fail(step, exc):
    report["errors"].append({"step": step, "error": repr(exc),
                             "trace": traceback.format_exc()})
    print(f"[panel] ERROR in {step}: {exc!r}")


def find_view3d():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                regions = {r.type: r for r in area.regions}
                return win, area, regions
    return None, None, {}


def crop(src_path, dst_path, x, y, w, h):
    """Crop a PNG by rect, origin bottom-left (Blender's pixel order)."""
    img = bpy.data.images.load(src_path, check_existing=False)
    iw, ih = img.size
    buf = np.empty(iw * ih * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    frame = buf.reshape(ih, iw, 4)

    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(iw, x + w), min(ih, y + h)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"empty crop rect {(x, y, w, h)} in {(iw, ih)}")
    sub = frame[y0:y1, x0:x1, :]

    out = bpy.data.images.new("crop", width=sub.shape[1],
                              height=sub.shape[0], alpha=True)
    out.pixels.foreach_set(sub.reshape(-1))
    out.filepath_raw = dst_path
    out.file_format = 'PNG'
    out.save()
    bpy.data.images.remove(out)
    return sub.shape[1], sub.shape[0]


class Probe:
    def __init__(self, win, area, regions):
        self.win, self.area, self.regions = win, area, regions
        self.tick = 0

    def __call__(self):
        t = self.tick
        self.tick += 1
        try:
            if t == T_REVEAL:
                # Use the addon's OWN helper: the docs should show the panel
                # the same code path the addon opens for a first visualizer,
                # not a hand-rolled imitation of it.
                with bpy.context.temp_override(
                        window=self.win, area=self.area,
                        region=self.regions.get('WINDOW')):
                    av._reveal_viz_panel(bpy.context)
                self.area.tag_redraw()
                print("[panel] _reveal_viz_panel called")
            elif t == T_SHOT:
                self.capture()
            elif t == T_SHOT + 1:
                self.finish()
                return None
        except Exception as exc:  # noqa: BLE001
            fail(f"tick_{t}", exc)
        return 0.05

    def capture(self):
        area, regions = self.area, {r.type: r for r in self.area.regions}
        ui = regions.get('UI')
        space = next(s for s in area.spaces if s.type == 'VIEW_3D')

        report["findings"]["show_region_ui"] = space.show_region_ui
        report["findings"]["ui_region"] = (
            None if ui is None else
            {"x": ui.x, "y": ui.y, "w": ui.width, "h": ui.height,
             "category": getattr(ui, "active_panel_category", None)})
        report["findings"]["area_rect"] = {
            "x": area.x, "y": area.y, "w": area.width, "h": area.height}

        src = os.path.join(OUT, "panel_area.png")
        with bpy.context.temp_override(window=self.win, area=area,
                                       region=regions.get('WINDOW')):
            bpy.ops.screen.screenshot_area(filepath=src)
        report["findings"]["panel_area_png"] = os.path.exists(src)
        print(f"[panel] panel_area.png exists={os.path.exists(src)}")

        if ui is None or ui.width <= 1:
            report["findings"]["crop"] = "skipped — no UI region"
            return
        dst = os.path.join(OUT, "panel_only.png")
        try:
            w, h = crop(src, dst, ui.x - area.x, ui.y - area.y,
                        ui.width, ui.height)
            report["findings"]["crop"] = {"w": w, "h": h}
            print(f"[panel] panel_only.png {w}x{h}")
        except Exception as exc:  # noqa: BLE001
            fail("crop", exc)

    def finish(self):
        with open(os.path.join(OUT, "report.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print("=" * 60)
        for key, val in report["findings"].items():
            print(f"  {key}: {val}")
        print("=" * 60)
        bpy.ops.wm.quit_blender()


def main():
    os.makedirs(OUT, exist_ok=True)
    try:
        av.register()
        view = bpy.context.preferences.view
        view.show_tooltips = False

        win, area, regions = find_view3d()
        if area is None:
            raise RuntimeError("no VIEW_3D area")

        # Assert the panel state we are about to photograph, before the photo.
        groups = av.visualizers_by_scope(bpy.context.scene)
        report["findings"]["assert_groups"] = [
            [getattr(k, "name", str(k)), len(v)] for k, v in
            (groups.items() if hasattr(groups, "items") else groups)]
        print(f"[panel] groups: {report['findings']['assert_groups']}")

        bpy.app.timers.register(Probe(win, area, regions),
                                first_interval=0.1)
    except Exception as exc:  # noqa: BLE001
        fail("setup", exc)
        with open(os.path.join(OUT, "report.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        bpy.ops.wm.quit_blender()


main()
