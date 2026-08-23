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
        report["image"] = raw
        print(f"[capture] wrote {raw}")

    def __call__(self):
        t = self.tick
        self.tick += 1
        try:
            plan = self.ticks
            if "reveal" in plan and t == plan["reveal"]:
                report["assertions"].update(
                    self.scen["setup"](self.ctx) or {})
            elif "open" in plan and t == plan["open"]:
                self.open_menu()
            elif t in plan.get("nudges", ()):
                self.nudge(plan["nudges"].index(t))
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
