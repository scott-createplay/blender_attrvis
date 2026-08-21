"""Baseline repro for 009 — an empty sample must draw nothing, not raise.

Pure numpy: no bpy, no GPU context, no Blender. Run with plain python.

    python dev_tasks/009_empty_sample_crash/baseline_repro.py

RED before the fix, GREEN after. Four checks, one per defect:

  1. heat_scalar on a zero-row vector sample        -> ValueError today
  2. heat_scalar on a flat (3N,) vector sample      -> wrong numbers today
  3. no `reshape(len(x), -1)` left anywhere         -> 2 sites today
  4. the draw loop contains a per-row failure       -> no such guard today

Check 4 imports attrviz.gpu_overlay._draw_rows, which does not exist yet.
That absence IS the baseline: there is no containment, so one raising
visualizer blanks every overlay drawn after it.
"""
from __future__ import annotations

import importlib.util
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(modname):
    """Import attrviz/<modname>.py directly, bypassing the bpy-importing package."""
    path = os.path.join(ROOT, "attrviz", f"{modname}.py")
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RESULTS = []


def check(name, fn):
    try:
        fn()
    except Exception as exc:
        RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"))
        print(f"  FAIL  {name}\n          {type(exc).__name__}: {exc}")
    else:
        RESULTS.append((name, True, ""))
        print(f"  ok    {name}")


# --- 1. empty vector sample ------------------------------------------------

def check_heat_scalar_empty():
    gpu_color = _load("gpu_color")
    for dtype, ncomp in (("FLOAT_VECTOR", 3), ("FLOAT2", 2)):
        out = gpu_color.heat_scalar(np.zeros((0, ncomp), np.float32), dtype)
        assert out.shape == (0,), f"{dtype}: expected (0,), got {out.shape}"
    out = gpu_color.heat_scalar(np.zeros((0,), np.float32), "FLOAT")
    assert out.shape == (0,), f"FLOAT: expected (0,), got {out.shape}"


# --- 2. flat input silently produces wrong numbers -------------------------

def check_heat_scalar_flat():
    gpu_color = _load("gpu_color")
    want = np.array([5.0, 5.0], np.float32)
    two_d = gpu_color.heat_scalar(
        np.array([[3, 4, 0], [0, 0, 5]], np.float32), "FLOAT_VECTOR")
    assert np.allclose(two_d, want), f"2-D: expected {want}, got {two_d}"
    flat = gpu_color.heat_scalar(
        np.array([3, 4, 0, 0, 0, 5], np.float32), "FLOAT_VECTOR")
    assert np.allclose(flat, want), f"flat: expected {want}, got {flat}"


# --- 3. buffer_stats' reshape (gpu_sample imports bpy; test the expression) -

def check_no_ambiguous_reshape():
    """No `reshape(len(x), -1)` anywhere: ambiguous at 0, wrong on flat input.

    Guards the defect class, not just the two known sites. This is the grep
    that found buffer_stats in the first place.
    """
    import glob
    hits = []
    for path in glob.glob(os.path.join(ROOT, "attrviz", "*.py")):
        for i, line in enumerate(open(path, encoding="utf-8"), 1):
            if "reshape(len(" in line:
                hits.append(f"{os.path.basename(path)}:{i}: {line.strip()}")
    sep = chr(10) + "    "
    assert not hits, "ambiguous reshape(len(x), -1):" + sep + sep.join(hits)
    assert not hits, "ambiguous reshape(len(x), -1):" + sep + sep.join(hits)


# --- 4. one raising visualizer must not blank the rest of the pass ---------

def check_draw_loop_contained():
    path = os.path.join(ROOT, "attrviz", "gpu_overlay.py")
    spec = importlib.util.spec_from_file_location("gpu_overlay_probe", path)
    src = open(path, encoding="utf-8").read()
    if "_draw_rows" not in src:
        raise AssertionError(
            "gpu_overlay has no _draw_rows containment helper: the draw loop "
            "calls _refresh_viz unguarded, so one raise kills the whole pass"
        )
    # Re-exec just the helper against fakes (module-level bpy import is skipped
    # by extracting the function source).
    ns = {"_note_viz_error": lambda *a: None}
    start = src.index("def _draw_rows(")
    end = src.index("\ndef ", start + 1)
    exec(compile(src[start:end], "gpu_overlay", "exec"), ns)
    drawn = []

    def refresh(obj, md, display):
        if obj == "bad":
            raise ValueError("cannot reshape array of size 0 into shape (0,newaxis)")
        return obj

    rows = [("good_before", None, "Arrows"),
            ("bad", None, "Markers"),
            ("good_after", None, "Arrows")]
    ns["_draw_rows"](rows, refresh, drawn.append)
    assert drawn == ["good_before", "good_after"], (
        f"containment failed: drew {drawn}, expected both good rows")


if __name__ == "__main__":
    print("009 baseline repro — empty sample must draw nothing, not raise\n")
    check("heat_scalar accepts a zero-row vector sample", check_heat_scalar_empty)
    check("heat_scalar handles flat (3N,) input", check_heat_scalar_flat)
    check("no ambiguous reshape(len(x), -1) in attrviz/", check_no_ambiguous_reshape)
    check("draw loop contains a per-visualizer raise", check_draw_loop_contained)
    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail}/{len(RESULTS)} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)
