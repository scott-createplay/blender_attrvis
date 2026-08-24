"""Unit tests for the overlay draw loop's failure containment.

One misbehaving visualizer must not blank every other object's overlay.
Before dev_tasks/009, _draw_callback_view_impl called _refresh_viz
unguarded: a single raise — e.g. an off-screen object culled to zero
samples — propagated out of the draw handler and killed the whole pass,
so the object you were looking at lost its overlay because a sibling
went off-screen.

_draw_rows takes its refresh/draw callables as arguments precisely so
this rule is testable without a GPU draw context, the same reason
_split_geometric_depth was split out.

    blender --background --factory-startup --python-exit-code 1 \
      --python tests/test_draw_guard.py
"""
from __future__ import annotations

import sys


def _draw_rows():
    """Load gpu_overlay._draw_rows, tolerating a missing bpy."""
    sys.path.insert(0, ".")
    try:
        from attrviz import gpu_overlay
        return gpu_overlay._draw_rows
    except ImportError:
        # No bpy (plain python): exec just the helper against a stub logger.
        src = open("attrviz/gpu_overlay.py", encoding="utf-8").read()
        start = src.index("def _draw_rows(")
        end = src.index("\ndef ", start + 1)
        ns = {"_note_viz_error": lambda *a: None}
        exec(compile(src[start:end], "gpu_overlay", "exec"), ns)
        return ns["_draw_rows"]


_BOOM = "cannot reshape array of size 0 into shape (0,newaxis)"


def _rows(*names):
    return [(n, None, "Markers") for n in names]


def test_failure_does_not_block_later_rows():
    """A raising visualizer is skipped; the rest of the pass still draws."""
    draw_rows = _draw_rows()
    drawn = []

    def refresh(obj, md, display):
        if obj == "bad":
            raise ValueError(_BOOM)
        return obj

    ok = draw_rows(_rows("before", "bad", "after"), refresh, drawn.append)
    assert drawn == ["before", "after"], f"drew {drawn}"
    assert ok is False, "expected _draw_rows to report the failure"
    print(f"  one bad row of three: drew {drawn}, ok={ok}  OK")


def test_every_row_failing_is_survivable():
    """All rows raising is contained too — nothing drawn, nothing escapes."""
    draw_rows = _draw_rows()
    drawn = []

    def refresh(obj, md, display):
        raise ValueError(_BOOM)

    ok = draw_rows(_rows("a", "b", "c"), refresh, drawn.append)
    assert drawn == [], f"expected nothing drawn, got {drawn}"
    assert ok is False
    print("  all rows bad: contained, nothing escaped  OK")


def test_clean_pass_reports_success():
    """No failures: everything draws in order and ok is True."""
    draw_rows = _draw_rows()
    drawn = []
    ok = draw_rows(_rows("a", "b", "c"),
                   lambda o, m, d: o, drawn.append)
    assert drawn == ["a", "b", "c"], f"drew {drawn}"
    assert ok is True
    print(f"  clean pass: drew {drawn}, ok={ok}  OK")


def test_draw_side_failure_is_contained():
    """A raise in the draw step, not just the refresh step, is contained."""
    draw_rows = _draw_rows()
    drawn = []

    def draw(entry):
        if entry == "bad":
            raise RuntimeError("GPU batch draw failed")
        drawn.append(entry)

    ok = draw_rows(_rows("before", "bad", "after"),
                   lambda o, m, d: o, draw)
    assert drawn == ["before", "after"], f"drew {drawn}"
    assert ok is False
    print(f"  bad draw (not refresh): drew {drawn}  OK")


def test_gpu_state_restore_is_in_finally():
    """The GPU state restore must not be skippable by an escaping raise.

    Structural check: gpu_overlay imports bpy and gpu, so the draw handler
    itself cannot run headless. What is checkable is that the restore sits
    in a finally rather than falling off the end of the function.
    """
    src = open("attrviz/gpu_overlay.py", encoding="utf-8").read()
    start = src.index("def _draw_callback_view_impl():")
    end = src.index("\ndef ", start + 1)
    body = src[start:end]
    assert "finally:" in body, (
        "_draw_callback_view_impl has no finally: an escaping exception "
        "leaves depth mask / depth test / face culling dirty for the "
        "rest of the frame")
    tail = body[body.index("finally:"):]
    for call in ("depth_mask_set(True)", "depth_test_set('NONE')",
                 "face_culling_set('NONE')"):
        assert call in tail, f"{call} is not restored in the finally block"
    print("  depth mask / depth test / face culling restored in finally  OK")


if __name__ == "__main__":
    print("test_draw_guard: failure_does_not_block_later_rows")
    test_failure_does_not_block_later_rows()
    print("test_draw_guard: every_row_failing_is_survivable")
    test_every_row_failing_is_survivable()
    print("test_draw_guard: clean_pass_reports_success")
    test_clean_pass_reports_success()
    print("test_draw_guard: draw_side_failure_is_contained")
    test_draw_side_failure_is_contained()
    print("test_draw_guard: gpu_state_restore_is_in_finally")
    test_gpu_state_restore_is_in_finally()
    print("\nAll test_draw_guard passed.")
