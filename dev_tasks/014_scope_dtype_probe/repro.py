"""014 repro — the dtype probe inspects one arbitrary object, not the scope.

    blender --background --factory-startup --python-exit-code 1 \
      --python dev_tasks/014_scope_dtype_probe/repro.py

Two meshes in the attrvis collection. Only ONE carries a vector attribute, and
it is MODIFIER-generated so it is absent from the original mesh entirely --
that is what defeats _target_attr_meta's fast path and forces the evaluated
fallback, exactly as with grad_z in the report.

Step 1 of the POR's Reproduction is the point of this file: confirm by
measurement that meshes[0] really is the non-carrying object, rather than
inheriting that as inference. Step 5 is the proof: reverse the link order and
nothing about the data changes, only which object the probe lands on.
"""
import os
import sys

import bpy
import bmesh

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import attrviz as av
from attrviz import gpu_sample, gpu_overlay, node_builder

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok    {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}   {detail}")


def grid(name):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=2, y_segments=2, size=1.0)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    # scene root, not context.collection: build() wipes collections and the
    # context's active collection goes None with them.
    bpy.context.scene.collection.objects.link(obj)
    return obj


def add_vector_writer(obj, attr_name):
    """GN modifier writing a Point FLOAT_VECTOR. Absent from the original mesh,
    like grad_z from a Measure node."""
    ng = bpy.data.node_groups.new(f"WriteVec_{attr_name}", 'GeometryNodeTree')
    ng.interface.new_socket("Geometry", in_out='INPUT',
                            socket_type='NodeSocketGeometry')
    ng.interface.new_socket("Geometry", in_out='OUTPUT',
                            socket_type='NodeSocketGeometry')
    gin = ng.nodes.new("NodeGroupInput")
    gout = ng.nodes.new("NodeGroupOutput")
    store = ng.nodes.new("GeometryNodeStoreNamedAttribute")
    store.data_type = 'FLOAT_VECTOR'
    store.domain = 'POINT'
    store.inputs["Name"].default_value = attr_name
    nrm = ng.nodes.new("GeometryNodeInputNormal")
    ng.links.new(gin.outputs[0], store.inputs["Geometry"])
    ng.links.new(nrm.outputs["Normal"], store.inputs["Value"])
    ng.links.new(store.outputs["Geometry"], gout.inputs[0])
    md = obj.modifiers.new("WriteVec", 'NODES')
    md.node_group = ng
    return md


def build(order):
    """Fresh scene with A and B linked into attrvis in the given order."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for ng in list(bpy.data.node_groups):
        bpy.data.node_groups.remove(ng)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    bpy.context.scene.attrviz_active_scope = None

    a = grid("A_NoAttr")
    b = grid("B_HasAttr")
    add_vector_writer(b, "v")
    bpy.context.view_layer.update()

    watch = av.active_scope(bpy.context, create=True)
    av._link_to_watch(bpy.context, [a, b] if order == "A_first" else [b, a])
    viz = av.add_visualizer(bpy.context, scope=watch, attribute="v",
                            domain="Point", style="Heat", display="Arrows")
    return a, b, watch, viz, av.viz_modifier(viz)


bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
av.register()

print("014 repro - the dtype probe sees one object, coverage sees all")
print()

# --- STEP 1: measure, do not infer -----------------------------------------
print("--- step 1: is meshes[0] really the non-carrying object? ---")
a, b, watch, viz, md = build("A_first")

order = [o.name for o in gpu_sample.watch_meshes_for_visualizer(md)]
print(f"  watch_meshes_for_visualizer order : {order}")
check("step1 meshes[0] is the object WITHOUT the attribute",
      order and order[0] == "A_NoAttr", str(order))

by_a, _ = av.attributes_by_domain(a)
by_b, _ = av.attributes_by_domain(b)
names_a = [n for n, _t in by_a.get("Point", [])]
names_b = [n for n, _t in by_b.get("Point", [])]
print(f"  A Point attributes : {names_a}")
print(f"  B Point attributes : {names_b}")
check("step1 A genuinely lacks 'v'", "v" not in names_a, str(names_a))
check("step1 B genuinely has 'v' as FLOAT_VECTOR",
      ("v", 'FLOAT_VECTOR') in by_b.get("Point", []), str(by_b.get("Point")))
check("step1 'v' is absent from B's ORIGINAL mesh (modifier-generated)",
      b.data.attributes.get("v") is None,
      "present - the fast path would hit and mask the bug")

print()
print("--- the two panel lines, computed from different object sets ---")
n_obj, n_draw = gpu_overlay.viz_coverage(md)
dtypes, domain = av._target_attr_meta(md)
dtype = dtypes[0] if len(dtypes) == 1 else None
print(f"  viz_coverage(md)      -> {n_obj} objects, {n_draw} carry 'v'")
print(f"  _target_attr_meta(md) -> dtype={dtype!r} domain={domain!r}")
check("coverage sees the whole scope", (n_obj, n_draw) == (2, 1),
      f"{(n_obj, n_draw)}")
check("FIXED: dtype probe finds the carrier regardless of order",
      dtype == 'FLOAT_VECTOR', f"dtype={dtype!r} dtypes={dtypes!r}")
check("VECTORISH would have accepted it",
      'FLOAT_VECTOR' in av.VECTORISH if hasattr(av, "VECTORISH") else True)

print()
print("--- the invariant the northstar states ---")
check("INVARIANT n_draw > 0 implies a non-None dtype",
      not (n_draw > 0 and dtype is None),
      "violated: coverage says 1 carries it, probe says no dtype")

# --- STEP 5: reverse the order, change nothing else ------------------------
print()
print("--- step 5: same data, carrier linked FIRST ---")
a2, b2, watch2, viz2, md2 = build("B_first")
order2 = [o.name for o in gpu_sample.watch_meshes_for_visualizer(md2)]
n_obj2, n_draw2 = gpu_overlay.viz_coverage(md2)
dtypes2, domain2 = av._target_attr_meta(md2)
dtype2 = dtypes2[0] if len(dtypes2) == 1 else None
print(f"  order                 : {order2}")
print(f"  viz_coverage(md)      -> {n_obj2} objects, {n_draw2} carry 'v'")
print(f"  _target_attr_meta(md) -> dtype={dtype2!r} domain={domain2!r}")
check("step5 coverage is unchanged", (n_obj2, n_draw2) == (2, 1),
      f"{(n_obj2, n_draw2)}")
check("step5 PROOF: dtype now resolves, from identical data",
      dtype2 == 'FLOAT_VECTOR', f"dtype={dtype2!r}")

print()
print(f"== Result: {PASS} passed, {FAIL} failed ==")
print()
print("All checks assert the FIXED contract: the probe finds a carrier whatever")
print("the link order, and the invariant holds.")
sys.exit(1 if FAIL else 0)
