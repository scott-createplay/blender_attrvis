"""Unit tests for gpu_color — empty samples, component-count reshape.

Zero samples is a legal state: the view culler returns nothing for an
off-screen object, so every colour mapper downstream must survive it.
See dev_tasks/009_empty_sample_crash/POR.md.

gpu_color is pure numpy, so these need no GPU context and no Blender.
Runs either way:

    python tests/test_gpu_color.py

    blender --background --factory-startup --python-exit-code 1 \
      --python tests/test_gpu_color.py
"""
from __future__ import annotations

import sys


def _gpu_color():
    """Import attrviz.gpu_color, falling back to a direct load without bpy."""
    sys.path.insert(0, ".")
    try:
        from attrviz import gpu_color
        return gpu_color
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gpu_color", "attrviz/gpu_color.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


def test_heat_scalar_empty():
    """Zero-row samples map to a zero-length scalar array, not a raise."""
    import numpy as np
    gpu_color = _gpu_color()

    for dtype, ncomp in (("FLOAT_VECTOR", 3), ("FLOAT2", 2)):
        out = gpu_color.heat_scalar(np.zeros((0, ncomp), np.float32), dtype)
        assert out.shape == (0,), f"{dtype}: expected (0,), got {out.shape}"
        print(f"  heat_scalar (0,{ncomp}) {dtype:<13} -> {out.shape}  OK")

    out = gpu_color.heat_scalar([], "FLOAT")
    assert out.shape == (0,), f"FLOAT: expected (0,), got {out.shape}"
    print(f"  heat_scalar []      FLOAT         -> {out.shape}  OK")


def test_heat_scalar_vector_norm():
    """Non-empty regression: vector samples map to their length."""
    import numpy as np
    gpu_color = _gpu_color()

    out = gpu_color.heat_scalar(
        np.array([[3, 4, 0], [0, 0, 5]], np.float32), "FLOAT_VECTOR")
    assert np.allclose(out, [5.0, 5.0]), f"expected [5, 5], got {out}"
    print(f"  heat_scalar 2-D  -> {out}  OK")


def test_heat_scalar_flat_input():
    """A flat (3N,) buffer is reshaped by component count, not by len().

    reshape(len(v), -1) turned this into (3N, 1) and the norm degenerated
    to per-component abs() — wrong numbers with no error.
    """
    import numpy as np
    gpu_color = _gpu_color()

    out = gpu_color.heat_scalar(
        np.array([3, 4, 0, 0, 0, 5], np.float32), "FLOAT_VECTOR")
    assert np.allclose(out, [5.0, 5.0]), f"flat: expected [5, 5], got {out}"
    print(f"  heat_scalar flat -> {out}  OK")


def test_heat_scalar_ragged_raises():
    """A buffer that is not a whole number of components is an error.

    Previously reshaped into the wrong component count and returned
    plausible-looking garbage.
    """
    import numpy as np
    gpu_color = _gpu_color()

    try:
        gpu_color.heat_scalar(np.array([1, 2, 3, 4], np.float32),
                              "FLOAT_VECTOR")
    except ValueError:
        print("  heat_scalar ragged (4,) as FLOAT_VECTOR -> ValueError  OK")
    else:
        raise AssertionError(
            "ragged buffer silently accepted; expected ValueError")


def test_colour_mappers_accept_empty():
    """Every mapper downstream of the cull handles a zero-row sample."""
    import numpy as np
    gpu_color = _gpu_color()

    ef = np.zeros((0,), np.float32)
    ev = np.zeros((0, 3), np.float32)
    ei = np.zeros((0,), np.int32)
    stops = gpu_color.HEAT_STOPS

    cases = [
        ("hash_colors", lambda: gpu_color.hash_colors(ei)),
        ("ramp_colors", lambda: gpu_color.ramp_colors(ef, stops)),
        ("heat_colors FLOAT", lambda: gpu_color.heat_colors(ef, "FLOAT")),
        ("heat_colors VECTOR",
         lambda: gpu_color.heat_colors(ev, "FLOAT_VECTOR")),
        ("rgb_colors", lambda: gpu_color.rgb_colors(ev)),
        ("values_to_colors FLOAT",
         lambda: gpu_color.values_to_colors(ef, "FLOAT")),
        ("values_to_colors VECTOR",
         lambda: gpu_color.values_to_colors(ev, "FLOAT_VECTOR")),
        ("values_to_colors INT",
         lambda: gpu_color.values_to_colors(ei, "INT")),
    ]
    for label, fn in cases:
        out = fn()
        assert out.shape == (0, 4), f"{label}: expected (0,4), got {out.shape}"
        print(f"  {label:<24} (0 rows) -> {out.shape}  OK")


if __name__ == "__main__":
    print("test_gpu_color: heat_scalar_empty")
    test_heat_scalar_empty()
    print("test_gpu_color: heat_scalar_vector_norm")
    test_heat_scalar_vector_norm()
    print("test_gpu_color: heat_scalar_flat_input")
    test_heat_scalar_flat_input()
    print("test_gpu_color: heat_scalar_ragged_raises")
    test_heat_scalar_ragged_raises()
    print("test_gpu_color: colour_mappers_accept_empty")
    test_colour_mappers_accept_empty()
    print("\nAll test_gpu_color passed.")
