"""011 discovery — verify every mechanic the plan depends on, in isolation.

Written BEFORE implementing anything, to verify each mechanic in isolation.
S3, S9 and S10 originally characterised PRE-011 behaviour and were re-pointed at
the post-implementation contract once the fixes landed; the original
readings are recorded in POR.md. Each spike is independent and reports
PASS / FAIL / NOTE. A FAIL means the plan needs changing, not that the code
is broken.

    blender --background --factory-startup --python-exit-code 0 \
      --python dev_tasks/011_viz_scope/discovery.py

Exit code is deliberately 0 — this is a probe, not a test suite. Read the
summary table.

Spikes:
  S1  GN Collection socket auto-nulls when its collection is deleted
  S2  Scope socket exists, is a Collection, is readable and writable
  S3  Per-viz Scope resolves (pre-011 this proved the shadow existed)
  S4  GUI-created visualizers already carry Scope = attrvis
  S5  BoolProperty on bpy.types.Collection survives save + reload
  S6  Scene PointerProperty to Collection survives save + reload
  S7  Moving an object between collections changes coverage, orphans nothing
  S8  Linked (library) objects: is display_type writable?
  S9  is_visualizer lives in gpu_sample so is_watchable can use it
  S10 Objects outside the scene are dropped from watch sets
"""
import os
import sys
import traceback

import bpy
import bmesh

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

SCRATCH = os.environ.get("ATTRVIZ_SCRATCH") or os.path.join(REPO, "dev_tasks",
                                                            "011_viz_scope")

RESULTS = []


def report(sid, what, status, detail=""):
    RESULTS.append((sid, what, status, detail))
    print(f"  [{status:<4}] {sid}  {what}")
    if detail:
        for line in str(detail).splitlines():
            print(f"           {line}")


def spike(sid, what):
    def deco(fn):
        print(f"\n--- {sid}: {what}")
        try:
            ok, detail = fn()
            report(sid, what, "PASS" if ok else "FAIL", detail)
        except Exception:
            report(sid, what, "ERR", traceback.format_exc(limit=3))
        return fn
    return deco


def make_grid(name, attrs=()):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=2, y_segments=2, size=1.0)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    for a in attrs:
        layer = me.attributes.new(a, 'FLOAT', 'POINT')
        for d in layer.data:
            d.value = 0.5
    return obj


bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

import attrviz as av
from attrviz import gpu_sample, node_builder, gpu_overlay

av.register()
bpy.context.scene.attrviz_gpu_markers = True

print("Blender", bpy.app.version_string)
print("REPO   ", REPO)


# ---------------------------------------------------------------------------

@spike("S2", "Scope socket exists, is a Collection, readable and writable")
def _s2():
    obj = make_grid("S2Mesh", attrs=("heat",))
    coll = bpy.data.collections.new("S2Scope")
    bpy.context.scene.collection.children.link(coll)
    coll.objects.link(obj)
    viz = av.add_visualizer(bpy.context, scope=coll, attribute="heat",
                            domain="Point", style="Heat", display="Surface")
    md = av.viz_modifier(viz)
    kinds = {}
    for item in md.node_group.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == 'INPUT':
            kinds[item.name] = item.socket_type
    got = node_builder.get_input(md, "Scope")
    detail = (f"Scope socket_type={kinds.get('Scope')!r}  "
              f"Target socket_type={kinds.get('Target')!r}\n"
              f"get_input('Scope') -> {got.name if got else None}")
    ok = (kinds.get("Scope") == "NodeSocketCollection" and got is coll)
    return ok, detail


@spike("S1", "GN Collection socket auto-nulls when its collection is deleted")
def _s1():
    obj = make_grid("S1Mesh", attrs=("heat",))
    coll = bpy.data.collections.new("S1Doomed")
    bpy.context.scene.collection.children.link(coll)
    coll.objects.link(obj)
    viz = av.add_visualizer(bpy.context, scope=coll, attribute="heat",
                            domain="Point", style="Heat", display="Surface")
    md = av.viz_modifier(viz)
    before = node_builder.get_input(md, "Scope")
    before_name = before.name if before else "None"
    bpy.data.collections.remove(coll)
    try:
        after = node_builder.get_input(md, "Scope")
        after_repr = "None" if after is None else after.name
        nulled = after is None
    except ReferenceError as exc:
        after_repr = "ReferenceError: " + str(exc)
        nulled = False
    detail = ("before delete: " + before_name + chr(10)
              + "after delete:  " + after_repr)
    return nulled, detail


@spike("S4", "GUI-created visualizers already carry Scope = attrvis")
def _s4():
    obj = make_grid("S4Mesh", attrs=("heat",))
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    viz = av.add_visualizer_from_selection(
        bpy.context, attribute="heat", domain="Point",
        style="Heat", display="Surface")
    md = av.viz_modifier(viz)
    scope = node_builder.get_input(md, "Scope")
    target = node_builder.get_input(md, "Target")
    detail = (f"Scope  -> {scope.name if scope else None}\n"
              f"Target -> {target.name if target else None}")
    return (scope is not None
            and scope.name == gpu_sample.WATCH_COLLECTION), detail


@spike("S3", "Per-viz Scope resolves once the attrvis override is bypassed")
def _s3():
    """Simulate Phase 1 without editing the module: call iter_watch_meshes
    directly with Target and Scope, the way the un-shadowed path will."""
    a = make_grid("S3InA", attrs=("heat",))
    b = make_grid("S3InB", attrs=("heat",))
    ca = bpy.data.collections.new("S3ScopeA")
    cb = bpy.data.collections.new("S3ScopeB")
    for c in (ca, cb):
        bpy.context.scene.collection.children.link(c)
    ca.objects.link(a)
    cb.objects.link(b)
    # attrvis exists and currently shadows everything
    watch = av._ensure_watch_collection(bpy.context)
    av._link_to_watch(bpy.context, [a, b])

    viz = av.add_visualizer(bpy.context, scope=cb, attribute="heat",
                            domain="Point", style="Heat", display="Surface")
    md = av.viz_modifier(viz)

    shadowed = gpu_sample.watch_meshes_for_visualizer(md)
    unshadowed = gpu_sample.iter_watch_meshes(
        node_builder.get_input(md, "Target"),
        node_builder.get_input(md, "Scope"))
    detail = (f"attrvis holds:            "
              f"{sorted(o.name for o in watch.objects)}\n"
              f"today  (shadowed):        "
              f"{sorted(o.name for o in shadowed)}\n"
              f"phase 1 (Target u Scope): "
              f"{sorted(o.name for o in unshadowed)}")
    # When this spike was written, 'shadowed' returned all three objects --
    # that WAS the bug. Phase 1 removed the override, so both paths now
    # agree. Asserting agreement keeps the spike meaningful post-fix.
    ok = ({o.name for o in unshadowed} == {'S3InB'}
          and {o.name for o in shadowed} == {o.name for o in unshadowed})
    return ok, detail


@spike("S9", "is_visualizer reachable from gpu_sample without circular import")
def _s9():
    """Phase 2 needs is_watchable (gpu_sample) to exclude viz carriers, but
    is_visualizer lives in the package __init__ that imports gpu_sample."""
    src = open(os.path.join(REPO, "attrviz", "__init__.py"),
               encoding="utf-8").read()
    i = src.index("def is_visualizer(obj):")
    body = src[i:src.index("\ndef ", i + 1)]
    # Pre-Phase-2 this checked that the body was self-contained enough to
    # move. Phase 2 moved it, so now assert the move actually happened.
    has_local = hasattr(gpu_sample, 'is_visualizer')
    delegates = 'gpu_sample.is_visualizer' in body
    detail = ('is_visualizer body:' + chr(10) + body.strip() + chr(10)
              + 'gpu_sample.is_visualizer exists: ' + str(has_local) + chr(10)
              + '__init__ delegates to it:      ' + str(delegates))
    return has_local and delegates, detail


@spike("S7", "Moving an object between collections changes coverage")
def _s7():
    o = make_grid("S7Mover", attrs=("heat",))
    src = bpy.data.collections.new("S7Src")
    dst = bpy.data.collections.new("S7Dst")
    for c in (src, dst):
        bpy.context.scene.collection.children.link(c)
    for c in list(o.users_collection):
        c.objects.unlink(o)
    src.objects.link(o)
    before = gpu_sample.iter_watch_meshes(None, src)
    # move: link to dst, unlink from src
    dst.objects.link(o)
    src.objects.unlink(o)
    after_src = gpu_sample.iter_watch_meshes(None, src)
    after_dst = gpu_sample.iter_watch_meshes(None, dst)
    in_scene = o.name in bpy.context.scene.objects
    detail = (f"src before: {[x.name for x in before]}\n"
              f"src after:  {[x.name for x in after_src]}\n"
              f"dst after:  {[x.name for x in after_dst]}\n"
              f"still in scene (not orphaned): {in_scene}\n"
              f"users_collection: {[c.name for c in o.users_collection]}")
    return (not after_src and [x.name for x in after_dst] == ["S7Mover"]
            and in_scene), detail


@spike("S10", "Objects outside the scene are dropped from watch sets")
def _s10():
    me = bpy.data.meshes.new("S10Orphan")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=2, y_segments=2, size=1.0)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("S10Orphan", me)      # never linked to a scene
    floating = bpy.data.collections.new("S10Floating")  # not linked to scene
    floating.objects.link(o)
    seen = gpu_sample.iter_watch_meshes(None, floating)
    in_view_layer = o.name in bpy.context.view_layer.objects
    ev_ok = True
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        ev = o.evaluated_get(dg)
        ev_ok = ev is not None and getattr(ev, "data", None) is not None
    except Exception as exc:
        ev_ok = f"raised {type(exc).__name__}"
    detail = (f"iter_watch_meshes sees it: {[x.name for x in seen]}\n"
              f"in view_layer.objects:     {in_view_layer}\n"
              f"evaluated_get usable:      {ev_ok}")
    # Pre-fix this spike proved the LEAK: iter_watch_meshes returned an
    # object view_layer.objects did not have. The filter now drops it, so
    # assert the fix instead. The original reading is recorded in POR.md.
    return (len(seen) == 0 and not in_view_layer), detail


@spike("S8", "Linked (library) objects: is display_type writable?")
def _s8():
    lib_path = os.path.join(SCRATCH, "_s8_lib.blend")
    # Build a tiny library file in a separate scene state
    cur = os.path.join(SCRATCH, "_s8_host.blend")
    bpy.ops.wm.save_as_mainfile(filepath=cur)

    bpy.ops.wm.read_homefile(use_empty=True)
    lo = bpy.data.objects.new("S8Linked", bpy.data.meshes.new("S8LinkedMesh"))
    lc = bpy.data.collections.new("S8LibColl")
    lc.objects.link(lo)
    bpy.context.scene.collection.children.link(lc)
    bpy.ops.wm.save_as_mainfile(filepath=lib_path)

    bpy.ops.wm.read_homefile(use_empty=True)
    with bpy.data.libraries.load(lib_path, link=True) as (src, dst):
        dst.collections = ["S8LibColl"]
    linked = bpy.data.collections.get("S8LibColl")
    bpy.context.scene.collection.children.link(linked)
    obj = next((o for o in linked.objects), None)
    is_lib = obj.library is not None
    before = obj.display_type
    err = None
    try:
        obj.display_type = 'BOUNDS'
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
    after = obj.display_type
    detail = (f"object: {obj.name}  library={obj.library.filepath if obj.library else None}\n"
              f"obj.library is not None: {is_lib}\n"
              f"display_type before={before!r} after={after!r}\n"
              f"write raised: {err}")
    writable = (after == "BOUNDS" and err is None)
    verdict = ("WRITABLE - D7 premise is WRONG" if writable
               else "refused - D7 premise holds")
    detail = detail + chr(10) + "VERDICT: display_type on library data is " + verdict
    return writable, detail


@spike("S8b", "Linked objects: can _MUTE_PROP custom property be written?")
def _s8b():
    """_mute_target_solid stashes the previous display_type in a custom ID
    property. If that write is refused on library data nothing is stashed and
    _restore_target_solid can never restore -- a permanent mute."""
    linked = bpy.data.collections.get("S8LibColl")
    obj = next((o for o in linked.objects), None) if linked else None
    if obj is None:
        return False, "S8 left no linked object in the file"
    prop = gpu_overlay._MUTE_PROP
    err = None
    try:
        obj[prop] = "TEXTURED"
    except Exception as exc:
        err = type(exc).__name__ + ": " + str(exc)
    stashed = obj.get(prop, "<absent>")
    del_err = None
    if err is None:
        try:
            del obj[prop]
        except Exception as exc:
            del_err = type(exc).__name__ + ": " + str(exc)
    detail = ("obj.library: " + str(obj.library is not None) + chr(10)
              + "write custom prop raised: " + str(err) + chr(10)
              + "read back:                " + repr(stashed) + chr(10)
              + "delete raised:            " + str(del_err))
    return err is None and del_err is None, detail


@spike("S5", "BoolProperty on bpy.types.Collection survives save + reload")
def _s5():
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.types.Collection.attrviz_scope_enabled = bpy.props.BoolProperty(
        name="Enabled", default=True)
    c = bpy.data.collections.new("S5Coll")
    bpy.context.scene.collection.children.link(c)
    c.attrviz_scope_enabled = False
    path = os.path.join(SCRATCH, "_s5.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.wm.open_mainfile(filepath=path)
    c2 = bpy.data.collections.get("S5Coll")
    val = getattr(c2, "attrviz_scope_enabled", "MISSING")
    detail = (f"set False, saved, reloaded -> {val!r}\n"
              f"(default is True, so False proves it persisted)")
    return val is False, detail


@spike("S6", "Scene PointerProperty to Collection survives save + reload")
def _s6():
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.types.Scene.attrviz_active_scope = bpy.props.PointerProperty(
        type=bpy.types.Collection)
    c = bpy.data.collections.new("S6Active")
    bpy.context.scene.collection.children.link(c)
    bpy.context.scene.attrviz_active_scope = c
    path = os.path.join(SCRATCH, "_s6.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.wm.open_mainfile(filepath=path)
    got = getattr(bpy.context.scene, "attrviz_active_scope", "MISSING")
    name = got.name if hasattr(got, "name") else got
    # and auto-null on delete
    bpy.data.collections.remove(bpy.data.collections["S6Active"])
    after = bpy.context.scene.attrviz_active_scope
    detail = (f"saved + reloaded -> {name!r}\n"
              f"after collection deleted -> {after!r}")
    return name == "S6Active" and after is None, detail


# ---------------------------------------------------------------------------

print("\n" + "=" * 72)
print("011 DISCOVERY SUMMARY")
print("=" * 72)
for sid, what, status, _ in RESULTS:
    print(f"  {status:<4}  {sid:<4} {what}")
n_fail = sum(1 for _, _, s, _ in RESULTS if s != "PASS")
print(f"\n{len(RESULTS) - n_fail}/{len(RESULTS)} spikes passed")
for f in ("_s5.blend", "_s6.blend", "_s8_lib.blend", "_s8_host.blend"):
    try:
        os.remove(os.path.join(SCRATCH, f))
    except OSError:
        pass
