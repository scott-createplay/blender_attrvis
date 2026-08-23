"""M1e/M1g spike — is the menu cascade STEERABLE and DETERMINISTIC?

M1 proved a popup can be opened and captured. Two questions remain before the
cascade is a real capability rather than an accident of where the cursor landed:

  M1g  can cursor_warp move the highlight to a CHOSEN row after the menu is
       open, so we pick which submenu expands?
  M1e  with open_sublevel_delay forced to 0, are two runs byte-identical?
       (run1 vs run2 of the first probe differed by 10.3% — a race on the
       submenu opening, not render nondeterminism.)

One shot per run, the way a real scenario works. Driven by env:

  ATTRVIZ_PROBE_RUN   output subdir            (default run1)
  ATTRVIZ_MENU        menu bl_idname           (default ATTRVIZ_MT_visualize)
  ATTRVIZ_MENU_ROW    row index to hover       (default 0)

Run:
  blender --factory-startup -p 60 60 1600 900 examples/attrviz_scope.blend \
      --python dev_tasks/015_docs_capture/probe_menu2.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback

import bpy

REPO = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import attrviz as av  # noqa: E402

HERE = os.path.join(REPO, "dev_tasks", "015_docs_capture")
RUN = os.environ.get("ATTRVIZ_PROBE_RUN", "run1")
MENU = os.environ.get("ATTRVIZ_MENU", "ATTRVIZ_MT_visualize")
ROW = int(os.environ.get("ATTRVIZ_MENU_ROW", "0"))
OUT = os.path.join(HERE, "out", RUN)
TARGET_OBJ = "Sphere_Measured"

# Tick plan. Every number here is a measurement from the first probe, not a
# guess: the toplevel menu was present at +1 tick, and with the sublevel delay
# forced to 0 the submenu should not need the ~4 ticks it took at delay=2.
WARMUP = 14
T_OPEN = WARMUP + 1
T_HOVER = T_OPEN + 2
# Blender holds the parent row while the cursor moves *towards* an open
# submenu (the "safety triangle"). A single warp to the target row is
# therefore ignored — measured: rows 1 and 2 kept Point open, row 3 broke
# out. So nudge repeatedly, approaching from the LEFT edge of the menu so the
# motion vector points away from the submenu, and dwell before capturing.
T_NUDGES = (T_HOVER, T_HOVER + 2, T_HOVER + 4, T_HOVER + 6)
T_SHOT = T_HOVER + 14

report = {"run": RUN, "menu": MENU, "row": ROW, "errors": [], "findings": {}}


def fail(step, exc):
    report["errors"].append({"step": step, "error": repr(exc),
                             "trace": traceback.format_exc()})
    print(f"[probe2] ERROR in {step}: {exc!r}")


def find_view3d():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        return win, area, region
    return None, None, None


class Probe:
    def __init__(self, win, area, region, pitch):
        self.win, self.area, self.region = win, area, region
        self.pitch = pitch
        self.tick = 0
        # Open the cascade left-of-centre: the submenu expands rightwards and
        # must stay inside the area or screenshot_area clips it.
        self.cx = area.x + area.width // 3
        self.cy = area.y + (2 * area.height) // 3

    def warp(self, x, y, label):
        self.win.cursor_warp(x, y)
        report["findings"][f"cursor_{label}"] = [x, y]
        print(f"[probe2] warp {label} -> ({x}, {y})")

    def __call__(self):
        t = self.tick
        self.tick += 1
        try:
            if t == T_OPEN:
                self.warp(self.cx, self.cy, "open")
                with bpy.context.temp_override(
                        window=self.win, area=self.area, region=self.region):
                    res = bpy.ops.wm.call_menu(name=MENU)
                report["findings"]["call_menu_result"] = list(res)
            elif t in T_NUDGES:
                # y decreases downward in window coords (origin bottom-left).
                # Approach from inside the menu's left half; jitter by a pixel
                # so each nudge is a distinct motion event rather than a
                # coalesced no-op.
                # Straight down, same x as the open point: a vertical path is
                # not "towards" the submenu, so the safety check releases.
                # (Approaching from the left kept Point locked for every row.)
                jitter = 1 if T_NUDGES.index(t) % 2 else 0
                self.warp(self.cx + 12 + jitter,
                          self.cy - ROW * self.pitch,
                          f"hover{T_NUDGES.index(t)}")
            elif t == T_SHOT:
                name = f"{MENU}_row{ROW}"
                path = os.path.join(OUT, name + ".png")
                with bpy.context.temp_override(
                        window=self.win, area=self.area, region=self.region):
                    bpy.ops.screen.screenshot_area(filepath=path)
                report["findings"]["shot"] = path
                report["findings"]["shot_exists"] = os.path.exists(path)
                print(f"[probe2] shot {name} exists={os.path.exists(path)}")
            elif t == T_SHOT + 1:
                self.finish()
                return None
        except Exception as exc:  # noqa: BLE001
            fail(f"tick_{t}", exc)
        return 0.05

    def finish(self):
        with open(os.path.join(OUT, f"report_{MENU}_row{ROW}.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        for key, val in report["findings"].items():
            print(f"  {key}: {val}")
        bpy.ops.wm.quit_blender()


def main():
    os.makedirs(OUT, exist_ok=True)
    try:
        av.register()

        # The determinism lever. Units are 1/10 s; at the factory default of 2
        # the submenu opens ~200ms after hover, which is what raced between
        # run1 and run2. Zero makes the expansion immediate.
        view = bpy.context.preferences.view
        view.open_toplevel_delay = 0
        view.open_sublevel_delay = 0
        # Tooltips are transient, timing-dependent, and would land in the shot.
        view.show_tooltips = False
        report["findings"]["prefs_forced"] = {
            "open_toplevel_delay": view.open_toplevel_delay,
            "open_sublevel_delay": view.open_sublevel_delay,
            "show_tooltips": view.show_tooltips,
        }

        ui_scale = bpy.context.preferences.system.ui_scale
        pitch = int(round(20 * ui_scale))
        report["findings"]["ui_scale"] = ui_scale
        report["findings"]["row_pitch_px"] = pitch
        print(f"[probe2] ui_scale={ui_scale} row_pitch={pitch}")

        win, area, region = find_view3d()
        if area is None:
            raise RuntimeError("no VIEW_3D area")

        obj = bpy.data.objects[TARGET_OBJ]
        for other in bpy.context.view_layer.objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        by, _ = av.attributes_by_domain(obj)
        report["findings"]["assert_domains"] = sorted(
            d for d, v in by.items() if v)

        bpy.app.timers.register(Probe(win, area, region, pitch),
                                first_interval=0.1)
    except Exception as exc:  # noqa: BLE001
        fail("setup", exc)
        bpy.ops.wm.quit_blender()


main()
