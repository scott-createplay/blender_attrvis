"""M1 spike — can we capture an AttrViz RMB menu from a script?

Answers M1a-M1f of 015's Phase D. Needs a REAL window: no --background.

Run:
  blender --factory-startup -p 60 60 1600 900 examples/attrviz_scope.blend \
      --python dev_tasks/015_docs_capture/probe_menu.py

Writes out/<run>/report.json plus the PNGs it reasoned from. Exit code is NOT
meaningful yet (C6 is a separate spike) — read the JSON.

The oracle is pixels, not API state: Blender exposes no "is a popup open"
query, so we capture a baseline with no menu, capture again with the menu
requested, and diff. A large changed region means the popup drew AND the timer
fired AND the capture op saw it — M1a, M1b and M1c at once.
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
RUN = os.environ.get("ATTRVIZ_PROBE_RUN", "run1")
OUT = os.path.join(HERE, "out", RUN)
KEEP = bool(os.environ.get("ATTRVIZ_PROBE_KEEP"))

# The menu we photograph. Sphere_Measured carries grad + curv on Point and is
# not a visualizer, so ATTRVIZ_MT_visualize.poll passes and the draw has real
# attributes to list rather than the "No attributes" label.
TARGET_OBJ = "Sphere_Measured"
TARGET_MENU = "ATTRVIZ_MT_visualize"

# Tick schedule. Warmup lets the file load and the viewport draw once; the
# offsets after the menu opens are what MEASURE the redraw latency rather than
# assuming it (the C2 doctrine, applied to popups).
WARMUP = 12
SHOT_OFFSETS = (1, 2, 3, 5, 8, 13)

report = {
    "run": RUN,
    "blender": bpy.app.version_string,
    "target_obj": TARGET_OBJ,
    "target_menu": TARGET_MENU,
    "steps": [],
    "errors": [],
    "shots": {},
    "findings": {},
}


def note(step, **kw):
    kw["step"] = step
    report["steps"].append(kw)
    detail = " ".join(f"{k}={v!r}" for k, v in kw.items() if k != "step")
    print(f"[probe] {step}: {detail}")


def fail(step, exc):
    report["errors"].append({"step": step, "error": repr(exc),
                             "trace": traceback.format_exc()})
    print(f"[probe] ERROR in {step}: {exc!r}")


# --------------------------------------------------------------------------
# setup
# --------------------------------------------------------------------------
def find_view3d():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for region in area.regions:
                if region.type == 'WINDOW':
                    return win, area, region
    return None, None, None


def setup():
    av.register()

    win, area, region = find_view3d()
    if area is None:
        raise RuntimeError("no VIEW_3D area in the loaded screen")
    note("found_view3d", window_w=win.width, window_h=win.height,
         area_x=area.x, area_y=area.y, area_w=area.width, area_h=area.height,
         region_w=region.width, region_h=region.height)
    report["findings"]["C4_window_wh"] = [win.width, win.height]
    report["findings"]["C4_area_xywh"] = [area.x, area.y,
                                          area.width, area.height]

    obj = bpy.data.objects.get(TARGET_OBJ)
    if obj is None:
        raise RuntimeError(f"{TARGET_OBJ} not in file: "
                           f"{[o.name for o in bpy.data.objects]}")
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    # M1f — the preconditions the menu's own poll/draw depend on.
    by, _ = av.attributes_by_domain(obj)
    populated = {d: list(v) for d, v in by.items() if v}
    is_viz = av.is_visualizer(obj)
    report["findings"]["M1f_attrs_by_domain"] = populated
    report["findings"]["M1f_is_visualizer"] = is_viz
    report["findings"]["M1f_precondition_ok"] = bool(populated) and not is_viz
    note("M1f_precondition", domains=sorted(populated), is_visualizer=is_viz)

    return win, area, region


# --------------------------------------------------------------------------
# capture
# --------------------------------------------------------------------------
def shot(kind, name, win, area, region):
    """kind: 'window' | 'area'. Returns path or None."""
    path = os.path.join(OUT, name + ".png")
    try:
        with bpy.context.temp_override(window=win, area=area, region=region):
            if kind == "window":
                bpy.ops.screen.screenshot(filepath=path)
            else:
                bpy.ops.screen.screenshot_area(filepath=path)
    except Exception as exc:  # noqa: BLE001 - the answer may BE the exception
        fail(f"shot_{name}", exc)
        return None
    ok = os.path.exists(path)
    report["shots"][name] = {"kind": kind, "path": path if ok else None,
                             "exists": ok}
    note("shot", name=name, kind=kind, exists=ok)
    return path if ok else None


def load_rgb(path):
    img = bpy.data.images.load(path, check_existing=False)
    width, height = img.size
    buf = np.empty(width * height * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return buf.reshape(height, width, 4)[:, :, :3], (width, height)


def diff(base_path, other_path, thresh=0.02):
    """Changed-pixel count and bbox, in image coords (origin bottom-left)."""
    a, size_a = load_rgb(base_path)
    b, size_b = load_rgb(other_path)
    if size_a != size_b:
        return {"error": f"size mismatch {size_a} vs {size_b}"}
    mask = (np.abs(a - b) > thresh).any(axis=2)
    n = int(mask.sum())
    out = {"size": list(size_a), "changed_px": n,
           "changed_frac": round(n / float(size_a[0] * size_a[1]), 5)}
    if n:
        ys, xs = np.nonzero(mask)
        out["bbox"] = [int(xs.min()), int(ys.min()),
                       int(xs.max()), int(ys.max())]
        out["bbox_wh"] = [int(xs.max() - xs.min() + 1),
                          int(ys.max() - ys.min() + 1)]
    return out


# --------------------------------------------------------------------------
# the tick machine
# --------------------------------------------------------------------------
class Probe:
    def __init__(self, win, area, region):
        self.win, self.area, self.region = win, area, region
        self.tick = 0
        self.menu_tick = None
        self.base_window = None
        self.base_area = None
        self.menu_shots = []

    def open_menu(self):
        # cursor_warp puts the REAL cursor where the popup will open, which is
        # both M1e (deterministic placement) and the mitigation for
        # popup-dies-on-mouse-move.
        cx = self.area.x + self.area.width // 2
        cy = self.area.y + self.area.height // 2
        try:
            self.win.cursor_warp(cx, cy)
            report["findings"]["M1e_cursor_warp_ok"] = True
        except Exception as exc:  # noqa: BLE001
            fail("cursor_warp", exc)
            report["findings"]["M1e_cursor_warp_ok"] = False
        report["findings"]["M1e_cursor_xy"] = [cx, cy]

        try:
            with bpy.context.temp_override(
                    window=self.win, area=self.area, region=self.region):
                res = bpy.ops.wm.call_menu(name=TARGET_MENU)
            report["findings"]["M1_call_menu_result"] = list(res)
            note("call_menu", result=list(res), at=(cx, cy))
        except Exception as exc:  # noqa: BLE001
            fail("call_menu", exc)
            report["findings"]["M1_call_menu_result"] = None

    def __call__(self):
        t = self.tick
        self.tick += 1
        try:
            if t == WARMUP:
                self.base_window = shot("window", "00_base_window",
                                        self.win, self.area, self.region)
                self.base_area = shot("area", "01_base_area",
                                      self.win, self.area, self.region)
            elif t == WARMUP + 1:
                # M1a: reaching this line at all proves timers still run after
                # the script returned. Whether they run *during* a popup is
                # what the shots below decide.
                report["findings"]["M1a_timer_ran_before_menu"] = True
                self.menu_tick = t
                self.open_menu()
            elif self.menu_tick is not None:
                off = t - self.menu_tick
                if off in SHOT_OFFSETS:
                    name = f"10_menu_window_t{off:02d}"
                    if shot("window", name, self.win, self.area, self.region):
                        self.menu_shots.append((off, name))
                    report["findings"]["M1a_timer_ran_after_menu"] = True
                elif off == max(SHOT_OFFSETS) + 1:
                    shot("area", "20_menu_area", self.win, self.area,
                         self.region)
                elif off == max(SHOT_OFFSETS) + 2:
                    self.finish()
                    return None
        except Exception as exc:  # noqa: BLE001
            fail(f"tick_{t}", exc)
        return 0.05

    def analyse(self):
        found = report["findings"]
        if not self.base_window:
            found["M1c_verdict"] = "no baseline window shot — cannot judge"
            return
        best = None
        per_tick = {}
        for off, name in self.menu_shots:
            path = report["shots"][name]["path"]
            if not path:
                continue
            d = diff(self.base_window, path)
            per_tick[off] = d
            if "changed_px" in d and (
                    best is None or d["changed_px"] > best[1]["changed_px"]):
                best = (off, d)
        found["M1c_window_diff_per_tick"] = per_tick

        # A menu is a solid block of chrome. Anything under ~0.1% of the window
        # is noise (a cursor ghost, a stats overlay), not a popup.
        if best and best[1]["changed_frac"] > 0.001:
            found["M1c_verdict"] = "PASS — popup pixels present in window shot"
            found["M1c_first_tick_with_menu"] = min(
                o for o, d in per_tick.items()
                if d.get("changed_frac", 0) > 0.001)
            found["M1c_best_tick"] = best[0]
            found["M1c_menu_bbox"] = best[1].get("bbox")
            found["M1c_menu_bbox_wh"] = best[1].get("bbox_wh")
            found["M1ab_verdict"] = (
                "PASS — timers fired and the popup survived the script "
                "returning")
        else:
            found["M1c_verdict"] = "FAIL — no popup pixels; see M1ab"
            found["M1ab_verdict"] = (
                "FAIL or UNKNOWN — popup never drew, died early, or timers "
                "are starved while it is up")

        # M1d — does screenshot_area see the popup? Expected NO.
        base_area = self.base_area
        menu_area = report["shots"].get("20_menu_area", {}).get("path")
        if base_area and menu_area:
            d = diff(base_area, menu_area)
            found["M1d_area_diff"] = d
            found["M1d_verdict"] = (
                "area shot CONTAINS popup pixels"
                if d.get("changed_frac", 0) > 0.001
                else "area shot EXCLUDES the popup — menus need window+crop")
        else:
            found["M1d_verdict"] = "inconclusive — missing an area shot"

    def finish(self):
        try:
            self.analyse()
        except Exception as exc:  # noqa: BLE001
            fail("analyse", exc)
        path = os.path.join(OUT, "report.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print("\n" + "=" * 70)
        print("M1 PROBE FINDINGS")
        print("=" * 70)
        for key, val in report["findings"].items():
            print(f"  {key}: {val}")
        print(f"\n  report: {path}")
        print("=" * 70)
        if not KEEP:
            bpy.ops.wm.quit_blender()


def main():
    os.makedirs(OUT, exist_ok=True)
    try:
        win, area, region = setup()
    except Exception as exc:  # noqa: BLE001
        fail("setup", exc)
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, "report.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        if not KEEP:
            bpy.ops.wm.quit_blender()
        return
    bpy.app.timers.register(Probe(win, area, region), first_interval=0.1)


main()
