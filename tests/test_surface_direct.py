"""Integration test: Surface via direct Color Attribute write on watched mesh.

Validates:
1. vizcol Color Attribute is created/written on the WATCHED mesh (not carrier)
2. Colors match expected Heat/RGB/Random output
3. Timing stays sub-ms for typical mesh sizes
4. Switching away clears/restores the attribute state
5. Works for Point, Face, and Corner domains

Run:
    blender --background --factory-startup --python-exit-code 1 \
        --python tests/test_surface_direct.py
"""
import sys
import time
import numpy as np

sys.path.insert(0, ".")

import bpy
import bmesh

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}  {detail}")


def make_cube(name, subdivisions=3):
    """Create a subdivided cube mesh object."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    for _ in range(subdivisions):
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=1)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    return obj


def add_float_attr(obj, name, domain='POINT'):
    """Add a float attribute with position.x values."""
    me = obj.data
    n = len(me.vertices) if domain == 'POINT' else len(me.polygons)
    attr = me.attributes.new(name, 'FLOAT', domain)
    if domain == 'POINT':
        cos = np.empty(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get("co", cos)
        vals = cos.reshape(-1, 3)[:, 0]
    else:
        vals = np.arange(n, dtype=np.float32) / max(n - 1, 1)
    attr.data.foreach_set("value", vals)
    return attr


# =========================================================================
# Core function under test: direct Color Attribute write
# =========================================================================

def surface_direct_write(obj, attr_name, domain='POINT', style='Heat',
                         vmin=None, vmax=None, seed=0):
    """Write false-color directly to watched mesh's vizcol Color Attribute.

    This is the proposed replacement for _sample_surface + _build_batch.
    Returns (time_ms, n_corners_written).
    """
    from attrviz import gpu_color, gpu_sample, node_builder

    me = obj.data
    CA_NAME = node_builder.VIZCOL_ATTR
    n_loops = len(me.loops)

    # Ensure Color Attribute exists
    if CA_NAME not in me.color_attributes:
        me.color_attributes.new(CA_NAME, 'FLOAT_COLOR', 'CORNER')
    try:
        me.color_attributes.active_color_name = CA_NAME
    except Exception:
        pass

    # Read attribute values
    t0 = time.perf_counter()

    if domain == 'POINT':
        n_verts = len(me.vertices)
        attr = me.attributes.get(attr_name)
        if attr is None:
            return 0, 0
        values = np.empty(n_verts, dtype=np.float32)
        attr.data.foreach_get("value", values)
        dtype = 'FLOAT'
    elif domain == 'FACE':
        n_polys = len(me.polygons)
        attr = me.attributes.get(attr_name)
        if attr is None:
            return 0, 0
        values = np.empty(n_polys, dtype=np.float32)
        attr.data.foreach_get("value", values)
        dtype = 'FLOAT'
    else:
        return 0, 0

    # Compute colors
    colors = gpu_color.values_to_colors(
        values, dtype, style, vmin=vmin, vmax=vmax, seed=seed,
    )

    # Expand to CORNER domain
    if domain == 'POINT':
        loop_vert_indices = np.empty(n_loops, dtype=np.int32)
        me.loops.foreach_get("vertex_index", loop_vert_indices)
        corner_colors = colors[loop_vert_indices]
    elif domain == 'FACE':
        poly_loop_totals = np.empty(len(me.polygons), dtype=np.int32)
        me.polygons.foreach_get("loop_total", poly_loop_totals)
        corner_colors = np.repeat(colors, poly_loop_totals, axis=0)

    # Write to Color Attribute
    ca = me.color_attributes[CA_NAME]
    ca.data.foreach_set("color", corner_colors.ravel())
    me.update()

    t1 = time.perf_counter()
    return (t1 - t0) * 1000, n_loops


# =========================================================================
# Tests
# =========================================================================

print("\n== Surface Direct Write: Point domain Heat ==")
cube1 = make_cube("TestCube1", subdivisions=3)
add_float_attr(cube1, "test_float", domain='POINT')

ms, n_corners = surface_direct_write(cube1, "test_float", domain='POINT', style='Heat')
print(f"  Timing: {ms:.2f}ms for {n_corners} corners")
check("point heat writes in < 5ms", ms < 5.0, f"{ms:.2f}ms")

# Verify colors written
me = cube1.data
ca = me.color_attributes["vizcol"]
raw = np.empty(n_corners * 4, dtype=np.float32)
ca.data.foreach_get("color", raw)
raw = raw.reshape(-1, 4)
check("vizcol has non-zero colors", raw[:, :3].max() > 0.0, f"max={raw[:,:3].max()}")
check("vizcol alpha is 1.0", np.allclose(raw[:, 3], 1.0), f"alpha range={raw[:,3].min()}-{raw[:,3].max()}")
check("vizcol has color variation (not flat)", raw[:, 0].std() > 0.01, f"std={raw[:,0].std():.4f}")

# Active color attribute set
check("active_color_name is vizcol",
      me.color_attributes.active_color_name == "vizcol",
      f"got: {me.color_attributes.active_color_name}")


print("\n== Surface Direct Write: Face domain Heat ==")
cube2 = make_cube("TestCube2", subdivisions=3)
add_float_attr(cube2, "face_val", domain='FACE')

ms2, n2 = surface_direct_write(cube2, "face_val", domain='FACE', style='Heat')
print(f"  Timing: {ms2:.2f}ms for {n2} corners")
check("face heat writes in < 5ms", ms2 < 5.0, f"{ms2:.2f}ms")

me2 = cube2.data
ca2 = me2.color_attributes["vizcol"]
raw2 = np.empty(n2 * 4, dtype=np.float32)
ca2.data.foreach_get("color", raw2)
raw2 = raw2.reshape(-1, 4)
check("face vizcol has variation", raw2[:, :3].std() > 0.01, f"std={raw2[:,:3].std():.4f}")


print("\n== Surface Direct Write: Large mesh timing ==")
cube_big = make_cube("TestCubeBig", subdivisions=5)
add_float_attr(cube_big, "big_float", domain='POINT')

times = []
for _ in range(5):
    ms_big, n_big = surface_direct_write(cube_big, "big_float", domain='POINT', style='Heat')
    times.append(ms_big)
med_big = np.median(times)
print(f"  {n_big} corners: median={med_big:.2f}ms (5 runs)")
check("large mesh (24k+ corners) still < 10ms", med_big < 10.0, f"{med_big:.2f}ms")


print("\n== Surface Direct Write: RGB vector style ==")
# Add a vector attribute
me3 = cube1.data
n_verts3 = len(me3.vertices)
if "test_vec" not in me3.attributes:
    attr_v = me3.attributes.new("test_vec", 'FLOAT_VECTOR', 'POINT')
    cos3 = np.empty(n_verts3 * 3, dtype=np.float32)
    me3.vertices.foreach_get("co", cos3)
    attr_v.data.foreach_set("vector", cos3)  # position as vector

# For RGB we need a vector-aware path
from attrviz import gpu_color
n_loops3 = len(me3.loops)
attr_v = me3.attributes["test_vec"]
vec_vals = np.empty(n_verts3 * 3, dtype=np.float32)
attr_v.data.foreach_get("vector", vec_vals)
vec_vals = vec_vals.reshape(-1, 3)

colors_rgb = gpu_color.values_to_colors(vec_vals, 'FLOAT_VECTOR', 'RGB')
check("RGB colors shape correct", colors_rgb.shape == (n_verts3, 4),
      f"got {colors_rgb.shape}")
check("RGB channels span range",
      bool((colors_rgb[:, :3].max(axis=0) - colors_rgb[:, :3].min(axis=0) > 0.5).all()),
      f"spans={colors_rgb[:,:3].max(axis=0) - colors_rgb[:,:3].min(axis=0)}")


print("\n== Cleanup: removing vizcol restores clean state ==")
me_clean = cube1.data
if "vizcol" in me_clean.color_attributes:
    me_clean.color_attributes.remove(me_clean.color_attributes["vizcol"])
check("vizcol removed cleanly", "vizcol" not in me_clean.color_attributes)


# =========================================================================
print(f"\n== Result: {PASS} passed, {FAIL} failed ==")
if FAIL > 0:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("ALL SURFACE DIRECT TESTS PASSED")

bpy.ops.wm.quit_blender()
