"""Headless tests for the scene-level attrvis watch collection.

Run:
  blender --background --factory-startup --python-exit-code 1 \\
      --python tests/test_watch_collection.py
"""
from __future__ import annotations

import os
import sys

import bpy
import bmesh

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import attrviz as av  # noqa: E402
from attrviz import gpu_overlay, gpu_sample, node_builder  # noqa: E402

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


def make_grid(name, segments=2, size=2.0):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(
        bm, x_segments=segments, y_segments=segments, size=size,
    )
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    return obj


print("\n== Watch collection attrvis ==")
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
av.register()

check("API add_visualizer(target=) does not create attrvis",
      bpy.data.collections.get(av.WATCH_COLLECTION) is None)
grid = make_grid("APIGrid")
av.add_visualizer(
    bpy.context, target=grid, attribute="position",
    domain="Point", style="Heat", display="Markers")
check("API target= still does not create attrvis",
      bpy.data.collections.get(av.WATCH_COLLECTION) is None)

watch = av._ensure_watch_collection(bpy.context)
viz_coll = bpy.data.collections.get(av.VIZ_COLLECTION)
check("attrvis exists", watch is not None)
check("attrvis ≠ Visualizers",
      viz_coll is not None and watch != viz_coll)
check("attrvis linked under scene",
      watch.name in bpy.context.scene.collection.children)

a = make_grid("WatchA")
b = make_grid("WatchB")
c = make_grid("WatchC")
for o in (a, b, c):
    heat = o.data.attributes.new("heat", 'FLOAT', 'POINT')
    for d in heat.data:
        d.value = 0.5

for o in list(bpy.context.view_layer.objects):
    o.select_set(False)
a.select_set(True)
b.select_set(True)
c.select_set(True)
bpy.context.view_layer.objects.active = a

viz_w = av.add_visualizer_from_selection(
    bpy.context, attribute="heat", domain="Point",
    style="Heat", display="Markers")
md_w = av.viz_modifier(viz_w)
scope_w = node_builder.get_input(md_w, "Scope")
target_w = node_builder.get_input(md_w, "Target")
check("GUI add-viz Scope is attrvis", scope_w == watch)
check("GUI add-viz Target unset", target_w is None)
check("multi-select linked into attrvis",
      all(watch in o.users_collection for o in (a, b, c)))
meshes_w = gpu_sample.iter_watch_meshes(target_w, scope_w)
check("iter_watch_meshes covers all three",
      set(meshes_w) >= {a, b, c},
      f"got={[o.name for o in meshes_w]}")

av._link_to_watch(bpy.context, [a, b, c])
check("re-link is a no-op",
      all(watch in o.users_collection for o in (a, b, c)))

# Surface mute must follow Add/Remove objects (not only add-viz).
bpy.context.scene.attrviz_gpu_markers = True
prev_dt = {o.name: o.display_type for o in (a, b, c)}
viz_surf = av.add_visualizer_from_selection(
    bpy.context, attribute="heat", domain="Point",
    style="Heat", display="Surface")
check("add Surface viz mutes watch set to BOUNDS",
      all(o.display_type == "BOUNDS" for o in (a, b, c)),
      str({o.name: o.display_type for o in (a, b, c)}))
av._unlink_from_watch(bpy.context, [c])
check("remove objects restores mute on C",
      c.display_type == prev_dt["WatchC"],
      f"display_type={c.display_type} expected={prev_dt['WatchC']}")
check("remove objects keeps mute on remaining",
      a.display_type == "BOUNDS" and b.display_type == "BOUNDS",
      f"A={a.display_type} B={b.display_type}")
av._link_to_watch(bpy.context, [c])
check("add objects mutes newly watched mesh",
      c.display_type == "BOUNDS", f"display_type={c.display_type}")

# File reopen: in-memory mute set is gone; newly added meshes load Solid.
gpu_overlay._muted_ptrs.clear()
a.display_type = prev_dt["WatchA"]
b.display_type = prev_dt["WatchB"]
c.display_type = prev_dt["WatchC"]
gpu_overlay._on_load_post(None)
check("load_post re-mutes watch set to BOUNDS",
      all(o.display_type == "BOUNDS" for o in (a, b, c)),
      str({o.name: o.display_type for o in (a, b, c)}))

av._unlink_from_watch(bpy.context, [c])
check("second remove restores C again",
      c.display_type == prev_dt["WatchC"],
      f"display_type={c.display_type}")
bpy.data.objects.remove(viz_surf, do_unlink=True)
av._sync_watch_draw(bpy.context)
check("remove Surface viz restores remaining mutes",
      a.display_type == prev_dt["WatchA"]
      and b.display_type == prev_dt["WatchB"],
      f"A={a.display_type} B={b.display_type}")

child = bpy.data.collections.new("attrvis_nested")
watch.children.link(child)
nested = make_grid("WatchNested")
for coll in list(nested.users_collection):
    coll.objects.unlink(nested)
child.objects.link(nested)
meshes_n = gpu_sample.iter_watch_meshes(None, watch)
check("nested collection meshes included",
      nested in meshes_n, f"got={[o.name for o in meshes_n]}")

av._unlink_from_watch(bpy.context, [c])
check("remove unlinks from attrvis", watch not in c.users_collection)
check("remove does not delete the object",
      bpy.data.objects.get(c.name) is c)
check("removed object still in some collection",
      len(c.users_collection) >= 1)

for o in list(bpy.context.view_layer.objects):
    o.select_set(False)
viz_w.select_set(True)
bpy.context.view_layer.objects.active = viz_w
cands = av._watch_candidates(bpy.context)
check("viz carrier skipped as watch candidate",
      viz_w not in cands)

scol = bpy.data.collections.new("ScopeOverride")
bpy.context.scene.collection.children.link(scol)
solo = make_grid("ScopeSolo")
for coll in list(solo.users_collection):
    coll.objects.unlink(solo)
scol.objects.link(solo)
viz_s = av.add_visualizer(
    bpy.context, scope=scol, attribute="heat", domain="Point",
    style="Heat", display="Markers")
md_s = av.viz_modifier(viz_s)
check("API scope= override is not attrvis",
      node_builder.get_input(md_s, "Scope") == scol)
check("API scope= does not force attrvis membership",
      watch not in solo.users_collection)

heat_s = solo.data.attributes.new("heat", 'FLOAT', 'POINT')
for d in heat_s.data:
    d.value = 0.5
bpy.context.view_layer.update()

def _drain_coll(coll):
    for obj in list(coll.objects):
        coll.objects.unlink(obj)
    for ch in list(coll.children):
        _drain_coll(ch)

_drain_coll(watch)
check("drained attrvis has no meshes",
      gpu_sample.iter_watch_meshes(None, watch) == [])
r_empty = gpu_sample.sample_visualizer_targets(md_s, cap=50000)
# 011 Phase 1: attrvis no longer shadows a visualizer's own Scope, so an
# empty attrvis says nothing about a visualizer scoped somewhere else.
check("011 empty attrvis does NOT suppress per-viz Scope",
      r_empty is not None and len(r_empty[0]) > 0,
      str(None if r_empty is None else len(r_empty[0])))

bpy.data.collections.remove(watch)
r_fb = gpu_sample.sample_visualizer_targets(md_s, cap=50000)
check("011 no attrvis - per-viz Scope still samples",
      r_fb is not None and len(r_fb[0]) > 0,
      str(None if r_fb is None else len(r_fb[0])))

print("\n== 006: POINTCLOUD watch candidates ==")


def make_pointcloud(name, n=8):
    me = bpy.data.meshes.new(name + "_mesh")
    me.vertices.add(n)
    for i in range(n):
        me.vertices[i].co = (float(i), 0.0, 0.0)
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    for o in list(bpy.context.view_layer.objects):
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.convert(target='POINTCLOUD')
    return bpy.context.view_layer.objects.active


# Recreate attrvis — previous block removed it for the Scope fallback test.
watch = av._ensure_watch_collection(bpy.context)
pc_w = make_pointcloud("WatchCloud", n=8)
heat_w = pc_w.data.attributes.new("heat", 'FLOAT', 'POINT')
for d in heat_w.data:
    d.value = 0.5
bpy.context.view_layer.update()
av._link_to_watch(bpy.context, [pc_w])
check("cloud linked into attrvis", watch in pc_w.users_collection)
watched = gpu_sample.iter_watch_meshes(None, watch)
check("iter_watch_meshes includes POINTCLOUD",
      pc_w in watched, f"got={[o.name for o in watched]}")

for o in list(bpy.context.view_layer.objects):
    o.select_set(False)
pc_w.select_set(True)
bpy.context.view_layer.objects.active = pc_w
cands_pc = av._watch_candidates(bpy.context)
check("_watch_candidates includes POINTCLOUD", pc_w in cands_pc)

print("\n== 006 P4: attrvis point-cloud mute ==")
bpy.context.scene.attrviz_gpu_markers = True
for v in list(av.visualizers(bpy.context.scene)):
    v.hide_viewport = True
gpu_overlay.suppress_gn_carriers(bpy.context.scene)

mesh_p4 = make_grid("P4WatchMesh")
heat_m4 = mesh_p4.data.attributes.new("heat", 'FLOAT', 'POINT')
for d in heat_m4.data:
    d.value = 0.5
av._link_to_watch(bpy.context, [mesh_p4])
prev_pc_w = pc_w.display_type
prev_mesh_p4 = mesh_p4.display_type
check("P4 isolated: cloud not muted", gpu_overlay._MUTE_PROP not in pc_w)
check("P4 isolated: mesh not muted", gpu_overlay._MUTE_PROP not in mesh_p4)

viz_mk = av.add_visualizer(
    bpy.context, scope=watch, attribute="heat",
    domain="Point", style="Heat", display="Markers")
check("P4 Markers only: cloud BOUNDS", pc_w.display_type == "BOUNDS",
      pc_w.display_type)
check("P4 Markers only: cloud mute prop", gpu_overlay._MUTE_PROP in pc_w)
check("P4 Markers only: mesh original",
      mesh_p4.display_type == prev_mesh_p4, mesh_p4.display_type)

viz_sf = av.add_visualizer(
    bpy.context, scope=watch, attribute="heat",
    domain="Point", style="Heat", display="Surface")
check("P4 both on: cloud BOUNDS", pc_w.display_type == "BOUNDS",
      pc_w.display_type)
check("P4 both on: mesh BOUNDS", mesh_p4.display_type == "BOUNDS",
      mesh_p4.display_type)

viz_mk.hide_viewport = True
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("P4 Surface only: mesh BOUNDS", mesh_p4.display_type == "BOUNDS",
      mesh_p4.display_type)
check("P4 Surface only: cloud restored",
      pc_w.display_type == prev_pc_w, pc_w.display_type)

viz_sf.hide_viewport = True
viz_mk.hide_viewport = False
gpu_overlay.suppress_gn_carriers(bpy.context.scene)
check("P4 Markers again: cloud BOUNDS", pc_w.display_type == "BOUNDS",
      pc_w.display_type)
check("P4 Markers again: mesh restored",
      mesh_p4.display_type == prev_mesh_p4, mesh_p4.display_type)

av._unlink_from_watch(bpy.context, [pc_w])
check("P4 unlink cloud restores",
      pc_w.display_type == prev_pc_w, pc_w.display_type)
av._link_to_watch(bpy.context, [pc_w])
check("P4 relink cloud mutes", pc_w.display_type == "BOUNDS",
      pc_w.display_type)

gpu_overlay._muted_ptrs.clear()
pc_w.display_type = prev_pc_w
mesh_p4.display_type = prev_mesh_p4
gpu_overlay._on_load_post(None)
check("P4 load_post remutes cloud", pc_w.display_type == "BOUNDS",
      pc_w.display_type)
check("P4 load_post does not mute mesh (Markers only)",
      mesh_p4.display_type == prev_mesh_p4, mesh_p4.display_type)


# === 010: mute only what a visualizer can actually draw on ==================
# Muting means "the overlay replaces the original". An object the visualizer
# cannot draw on must stay visible, or it is hidden with nothing in its place.
# See dev_tasks/010_mute_scope/POR.md.
print(chr(10) + "== 010: mute scope follows drawability ==")

for _v in list(av.visualizers(bpy.context.scene)):
    _v.hide_viewport = True
gpu_overlay.suppress_gn_carriers(bpy.context.scene)

m_has = make_grid("M010HasAttr")
m_not = make_grid("M010NoAttr")
_a = m_has.data.attributes.new("curv", 'FLOAT', 'POINT')
for _d in _a.data:
    _d.value = 0.25
av._link_to_watch(bpy.context, [m_has, m_not])
_orig_has, _orig_not = m_has.display_type, m_not.display_type

viz_010 = av.add_visualizer(
    bpy.context, scope=gpu_sample.scene_watch_collection(),
    attribute="curv", domain="Point", style="Heat", display="Surface")

check("010 object carrying the attribute is muted",
      m_has.display_type == "BOUNDS", m_has.display_type)
check("010 object lacking the attribute stays visible",
      m_not.display_type == _orig_not,
      f"muted to {m_not.display_type} with nothing drawn in its place")

_targets = gpu_overlay._active_surface_watch_meshes(bpy.context.scene)
_names = {o.name for o, _w in _targets}
check("010 mute target set excludes the attribute-less object",
      "M010NoAttr" not in _names and "M010HasAttr" in _names, str(_names))

# Intrinsics are GN field sources and never appear in mesh.attributes, so a
# naive obj.data.attributes probe would wrongly unmute every Normal viz.
viz_010.attrviz_enabled = False
viz_nrm = av.add_visualizer(
    bpy.context, scope=gpu_sample.scene_watch_collection(),
    attribute=node_builder.NORMAL_ATTR, domain="Point",
    style="Heat", display="Surface")
check("010 intrinsic Normal still mutes the attribute-less object",
      m_not.display_type == "BOUNDS", m_not.display_type)
check("010 intrinsic Normal mutes the other mesh too",
      m_has.display_type == "BOUNDS", m_has.display_type)

viz_nrm.attrviz_enabled = False
check("010 disabling restores the attribute-less object",
      m_not.display_type == _orig_not, m_not.display_type)
check("010 disabling restores the attribute-carrying object",
      m_has.display_type == _orig_has, m_has.display_type)


# === 011 Phase 1: un-shadowed Scope + migration backfill ====================
print(chr(10) + "== 011 Phase 1: per-viz Scope and migration ==")

watch011 = av._ensure_watch_collection(bpy.context)
m011 = make_grid("M011Watched")
_h011 = m011.data.attributes.new("heat", 'FLOAT', 'POINT')
for _d in _h011.data:
    _d.value = 0.5
av._link_to_watch(bpy.context, [m011])

# A visualizer with NEITHER Target nor Scope: the shape a pre-011 file leaves
# behind, which used to be rescued by the attrvis shadow.
viz_orphan = av.add_visualizer(
    bpy.context, attribute="heat", domain="Point",
    style="Heat", display="Markers")
md_orphan = av.viz_modifier(viz_orphan)
check("011 unscoped viz watches nothing before migration",
      gpu_sample.watch_meshes_for_visualizer(md_orphan) == [],
      str([o.name for o in gpu_sample.watch_meshes_for_visualizer(md_orphan)]))

_n_mig = av.migrate_viz_scope(bpy.context)
check("011 migrate_viz_scope backfills it", _n_mig >= 1, f"n={_n_mig}")
check("011 backfilled Scope is attrvis",
      node_builder.get_input(md_orphan, "Scope") == watch011)
check("011 backfilled viz now watches attrvis contents",
      m011 in gpu_sample.watch_meshes_for_visualizer(md_orphan))
check("011 migrate_viz_scope is idempotent",
      av.migrate_viz_scope(bpy.context) == 0)

# A Target-only visualizer must be left alone: broadening it to
# Target u attrvis would be wider than the old behaviour or the new one.
m011t = make_grid("M011Target")
_h011t = m011t.data.attributes.new("heat", 'FLOAT', 'POINT')
for _d in _h011t.data:
    _d.value = 0.5
viz_t = av.add_visualizer(
    bpy.context, target=m011t, attribute="heat", domain="Point",
    style="Heat", display="Markers")
md_t = av.viz_modifier(viz_t)
av.migrate_viz_scope(bpy.context)
check("011 target-only viz keeps an unset Scope",
      node_builder.get_input(md_t, "Scope") is None,
      str(node_builder.get_input(md_t, "Scope")))
check("011 target-only viz watches exactly its target",
      [o.name for o in gpu_sample.watch_meshes_for_visualizer(md_t)]
      == ["M011Target"],
      str([o.name for o in gpu_sample.watch_meshes_for_visualizer(md_t)]))

# Two visualizers, two scopes: the capability 011 exists to deliver.
c011a = bpy.data.collections.new("011ScopeA")
c011b = bpy.data.collections.new("011ScopeB")
for _c in (c011a, c011b):
    bpy.context.scene.collection.children.link(_c)
mA = make_grid("M011A")
mB = make_grid("M011B")
for _o, _c in ((mA, c011a), (mB, c011b)):
    _l = _o.data.attributes.new("heat", 'FLOAT', 'POINT')
    for _d in _l.data:
        _d.value = 0.5
    for _old in list(_o.users_collection):
        _old.objects.unlink(_o)
    _c.objects.link(_o)
vizA = av.add_visualizer(bpy.context, scope=c011a, attribute="heat",
                         domain="Point", style="Heat", display="Surface")
vizB = av.add_visualizer(bpy.context, scope=c011b, attribute="heat",
                         domain="Point", style="Heat", display="Surface")
check("011 viz A watches only collection A",
      [o.name for o in gpu_sample.watch_meshes_for_visualizer(
          av.viz_modifier(vizA))] == ["M011A"])
check("011 viz B watches only collection B",
      [o.name for o in gpu_sample.watch_meshes_for_visualizer(
          av.viz_modifier(vizB))] == ["M011B"])
check("011 A and B do not see each other's objects",
      mB not in gpu_sample.watch_meshes_for_visualizer(av.viz_modifier(vizA))
      and mA not in gpu_sample.watch_meshes_for_visualizer(
          av.viz_modifier(vizB)))



# === 011 Phase 2: carriers are never watchable ==============================
# _watch_candidates filters carriers at selection time; a hand-managed scope
# collection bypasses that entirely.
print(chr(10) + "== 011 Phase 2: carriers excluded from watch sets ==")

c012 = bpy.data.collections.new("011CarrierScope")
bpy.context.scene.collection.children.link(c012)
m012 = make_grid("M011Ordinary")
_h012 = m012.data.attributes.new("heat", 'FLOAT', 'POINT')
for _d in _h012.data:
    _d.value = 0.5
for _old in list(m012.users_collection):
    _old.objects.unlink(m012)
c012.objects.link(m012)

viz012 = av.add_visualizer(bpy.context, scope=c012, attribute="heat",
                           domain="Point", style="Heat", display="Markers")
check("011 P2 the carrier IS a visualizer", av.is_visualizer(viz012))
check("011 P2 gpu_sample agrees", gpu_sample.is_visualizer(viz012))
check("011 P2 an ordinary mesh is not a visualizer",
      not av.is_visualizer(m012))

# Drag the carrier into the scope collection, as a user could in the outliner.
c012.objects.link(viz012)
_seen = gpu_sample.iter_watch_meshes(None, c012)
check("011 P2 carrier in a scope is not watched",
      viz012 not in _seen, str([o.name for o in _seen]))
check("011 P2 the ordinary mesh still is",
      m012 in _seen, str([o.name for o in _seen]))
check("011 P2 is_watchable rejects the carrier",
      not gpu_sample.is_watchable(viz012))
check("011 P2 is_watchable accepts the mesh",
      gpu_sample.is_watchable(m012))
c012.objects.unlink(viz012)



# === 011 Phase 3: the active scope =========================================
print(chr(10) + "== 011 Phase 3: active scope ==")

# Lazy creation: a file with no attrvis is a legal state (D2a).
for _c in list(bpy.data.collections):
    if _c.name == av.WATCH_COLLECTION:
        bpy.data.collections.remove(_c)
bpy.context.scene.attrviz_active_scope = None
check("011 P3 no attrvis is a legal state - read does not create one",
      av.active_scope(bpy.context) is None
      and bpy.data.collections.get(av.WATCH_COLLECTION) is None)
_lazy = av.active_scope(bpy.context, create=True)
check("011 P3 first use creates attrvis and makes it active",
      _lazy is not None and _lazy.name == av.WATCH_COLLECTION
      and bpy.context.scene.attrviz_active_scope == _lazy)

# Switching active retargets Add objects.
cP3 = bpy.data.collections.new("011P3Other")
bpy.context.scene.collection.children.link(cP3)
mP3 = make_grid("M011P3")
_hP3 = mP3.data.attributes.new("heat", 'FLOAT', 'POINT')
for _d in _hP3.data:
    _d.value = 0.5
for _old in list(mP3.users_collection):
    _old.objects.unlink(mP3)
bpy.context.scene.collection.objects.link(mP3)

av.set_active_scope(bpy.context, cP3)
check("011 P3 set_active_scope takes effect",
      av.active_scope(bpy.context) == cP3)
av._link_to_watch(bpy.context, [mP3])
check("011 P3 Add objects lands in the active scope, not attrvis",
      cP3 in mP3.users_collection and _lazy not in mP3.users_collection,
      str([c.name for c in mP3.users_collection]))

# A new visualizer defaults its Scope to the active scope.
for _o in list(bpy.context.view_layer.objects):
    _o.select_set(False)
mP3.select_set(True)
bpy.context.view_layer.objects.active = mP3
vizP3 = av.add_visualizer_from_selection(
    bpy.context, attribute="heat", domain="Point",
    style="Heat", display="Markers")
check("011 P3 new visualizer scopes to the active collection",
      node_builder.get_input(av.viz_modifier(vizP3), "Scope") == cP3,
      str(node_builder.get_input(av.viz_modifier(vizP3), "Scope")))

# Discovery by use, not by name (D8).
_names = [c.name for c in av.scope_collections(bpy.context.scene)]
check("011 P3 scope list holds attrvis + collections in use",
      av.WATCH_COLLECTION in _names and "011P3Other" in _names, str(_names))
_unused = bpy.data.collections.new("011P3NeverScoped")
bpy.context.scene.collection.children.link(_unused)
check("011 P3 an unused collection is NOT listed",
      "011P3NeverScoped" not in
      [c.name for c in av.scope_collections(bpy.context.scene)])

# Deleting the active collection falls back without error (S6 auto-null).
bpy.data.collections.remove(cP3)
_after = av.active_scope(bpy.context)
check("011 P3 deleting the active scope auto-nulls the pointer",
      bpy.context.scene.attrviz_active_scope is None)
check("011 P3 active scope falls back to attrvis",
      _after is not None and _after.name == av.WATCH_COLLECTION,
      str(_after))

# The visualizer that pointed at the deleted collection is still reachable.
check("011 P3 viz with a nulled Scope is listed under attrvis",
      av.viz_scope(av.viz_modifier(vizP3)) is not None
      and av.viz_scope(av.viz_modifier(vizP3)).name == av.WATCH_COLLECTION)



# === 011 Phase 4: New collection from selection (ADDITIVE) =================
# Collections are additive, never exclusive (011 D4). Adding an object to a
# second scope must NOT take it out of the first: an object legitimately
# belongs to several scopes when they visualize different attributes.
print(chr(10) + "== 011 Phase 4: new scope is additive ==")

_watchP4 = av.active_scope(bpy.context, create=True)
av.set_active_scope(bpy.context, _watchP4)
mStay = make_grid("M011Stay")
mGo1 = make_grid("M011Go1")
mGo2 = make_grid("M011Go2")
for _o in (mStay, mGo1, mGo2):
    _l = _o.data.attributes.new("heat", 'FLOAT', 'POINT')
    for _d in _l.data:
        _d.value = 0.5
av._link_to_watch(bpy.context, [mStay, mGo1, mGo2])

vizStay = av.add_visualizer(bpy.context, scope=_watchP4, attribute="heat",
                            domain="Point", style="Heat", display="Surface")
mdStay = av.viz_modifier(vizStay)
_before = {o.name for o in gpu_sample.watch_meshes_for_visualizer(mdStay)}
check("011 P4 the first viz covers all three",
      {"M011Stay", "M011Go1", "M011Go2"} <= _before, str(_before))

_new = av.new_scope_collection(bpy.context, "011P4Second")
av._link_to_watch(bpy.context, [mGo1, mGo2], _new)
av.set_active_scope(bpy.context, _new)

check("011 P4 new collection is a SIBLING under the scene collection",
      _new.name in bpy.context.scene.collection.children
      and _new.name not in _watchP4.children,
      "child of attrvis" if _new.name in _watchP4.children else "sibling")
check("011 P4 ADDITIVE - objects stay in the original scope",
      _watchP4 in mGo1.users_collection and _watchP4 in mGo2.users_collection,
      str([c.name for c in mGo1.users_collection]))
check("011 P4 and are also in the new scope",
      _new in mGo1.users_collection and _new in mGo2.users_collection)
check("011 P4 nothing was orphaned from the scene",
      all(len(o.users_collection) >= 1 for o in (mGo1, mGo2))
      and mGo1.name in bpy.context.scene.objects)
check("011 P4 an unselected object is untouched",
      _watchP4 in mStay.users_collection and _new not in mStay.users_collection)

_after = {o.name for o in gpu_sample.watch_meshes_for_visualizer(mdStay)}
check("011 P4 the original visualizer STILL covers all three",
      _after == _before, f"{_after} was {_before}")

vizNew = av.add_visualizer(bpy.context, scope=_new, attribute="heat",
                           domain="Point", style="Heat", display="Markers")
check("011 P4 a viz on the new scope covers only the two added",
      {o.name for o in gpu_sample.watch_meshes_for_visualizer(
          av.viz_modifier(vizNew))} == {"M011Go1", "M011Go2"},
      str({o.name for o in gpu_sample.watch_meshes_for_visualizer(
          av.viz_modifier(vizNew))}))
check("011 P4 the new scope is now active",
      av.active_scope(bpy.context) == _new)

# Subtraction stays available, but only when asked for explicitly.
av.set_active_scope(bpy.context, _watchP4)
av._unlink_from_watch(bpy.context, [mGo1])
check("011 P4 Remove objects is the explicit subtractive half",
      _watchP4 not in mGo1.users_collection
      and _new in mGo1.users_collection,
      str([c.name for c in mGo1.users_collection]))
av.set_active_scope(bpy.context, _new)

check("011 P4 flat topology - the new scope is not nested",
      av.collection_parent(_new) is None
      or av.collection_parent(_new).name != _watchP4.name)

# === 011 Phase 5: coverage readout matches what is drawn ===================
# The panel number must never disagree with the viewport -- the invariant 009
# and 010 broke in opposite directions.
print(chr(10) + "== 011 Phase 5: coverage readout ==")

cP5 = av.new_scope_collection(bpy.context, "011P5Scope")
mCarry = make_grid("M011Carry")
mBare = make_grid("M011Bare")
_lc = mCarry.data.attributes.new("curv", 'FLOAT', 'POINT')
for _d in _lc.data:
    _d.value = 0.5
for _o in (mCarry, mBare):
    for _old in list(_o.users_collection):
        _old.objects.unlink(_o)
    cP5.objects.link(_o)
av.set_active_scope(bpy.context, cP5)

vizP5 = av.add_visualizer(bpy.context, scope=cP5, attribute="curv",
                          domain="Point", style="Heat", display="Surface")
mdP5 = av.viz_modifier(vizP5)
_n_obj, _n_draw = gpu_overlay.viz_coverage(mdP5)
check("011 P5 coverage counts every object in scope", _n_obj == 2, str(_n_obj))
check("011 P5 coverage counts only carriers of the attribute",
      _n_draw == 1, str(_n_draw))

_muted = {o.name for o, _w in
          gpu_overlay._active_surface_watch_meshes(bpy.context.scene)}
check("011 P5 the readout agrees with the mute set (010 consistency)",
      _muted & {"M011Carry", "M011Bare"} == {"M011Carry"}, str(_muted))
check("011 P5 the non-carrier is visible, not hidden with nothing drawn",
      mBare.display_type != "BOUNDS", mBare.display_type)

# Nesting must be visible, and counts must include inherited objects.
cChild = bpy.data.collections.new("011P5Child")
cP5.children.link(cChild)
mInh = make_grid("M011Inherited")
_li = mInh.data.attributes.new("curv", 'FLOAT', 'POINT')
for _d in _li.data:
    _d.value = 0.5
for _old in list(mInh.users_collection):
    _old.objects.unlink(mInh)
cChild.objects.link(mInh)

check("011 P5 collection_parent finds a hand-made nesting",
      av.collection_parent(cChild) == cP5,
      str(av.collection_parent(cChild)))
_n_obj2, _n_draw2 = gpu_overlay.viz_coverage(mdP5)
check("011 P5 counts include inherited objects (recursion is real)",
      _n_obj2 == 3 and _n_draw2 == 2, f"{_n_obj2}/{_n_draw2}")
check("011 P5 a flat sibling scope has no parent to report",
      av.collection_parent(cP5) is None
      or av.collection_parent(cP5).name != cP5.name)



# === 011 Phase 5a: collection enable semantics =============================
# The gate that matters: a disabled collection must RESTORE display_type, not
# leave its objects muted with nothing drawn. That is the 010 bug reintroduced.
print(chr(10) + "== 011 Phase 5a: collection enable ==")

c5a = av.new_scope_collection(bpy.context, "011P5aScope")
m5a = make_grid("M011P5a")
_l5a = m5a.data.attributes.new("curv", 'FLOAT', 'POINT')
for _d in _l5a.data:
    _d.value = 0.5
for _old in list(m5a.users_collection):
    _old.objects.unlink(m5a)
c5a.objects.link(m5a)
av.set_active_scope(bpy.context, c5a)
_orig5a = m5a.display_type

vizA5 = av.add_visualizer(bpy.context, scope=c5a, attribute="curv",
                          domain="Point", style="Heat", display="Surface")
vizB5 = av.add_visualizer(bpy.context, scope=c5a, attribute="curv",
                          domain="Point", style="Heat", display="Markers")
check("011 P5a default is enabled", gpu_overlay.scope_enabled(c5a))
check("011 P5a objects muted while enabled",
      m5a.display_type == "BOUNDS", m5a.display_type)

# Per-viz state that must survive the collection round trip.
vizB5.attrviz_enabled = False
check("011 P5a per-viz disable took effect", not vizB5.attrviz_enabled)

c5a.attrviz_scope_enabled = False
check("011 P5a scope_enabled reports False",
      not gpu_overlay.scope_enabled(c5a))
check("011 P5a disabled scope draws nothing",
      not [r for r in gpu_overlay._gpu_visualizers(bpy.context.scene)
           if r[0] in (vizA5, vizB5)],
      str([r[0].name for r in gpu_overlay._gpu_visualizers(bpy.context.scene)]))
check("011 P5a THE GATE - disabled scope RESTORES display_type",
      m5a.display_type == _orig5a,
      f"{m5a.display_type!r} expected {_orig5a!r} - 010 reintroduced")
check("011 P5a disabled scope drops out of the mute target set",
      "M011P5a" not in {o.name for o, _w in
                        gpu_overlay._active_surface_watch_meshes(
                            bpy.context.scene)})

c5a.attrviz_scope_enabled = True
check("011 P5a re-enabling re-mutes", m5a.display_type == "BOUNDS",
      m5a.display_type)
check("011 P5a per-viz enable states survived the round trip",
      not vizB5.attrviz_enabled and vizA5.attrviz_enabled,
      f"A={vizA5.attrviz_enabled} B={vizB5.attrviz_enabled}")
check("011 P5a the enabled viz draws again",
      vizA5 in [r[0] for r in gpu_overlay._gpu_visualizers(bpy.context.scene)])

# Another collection is unaffected.
c5b = av.new_scope_collection(bpy.context, "011P5bScope")
m5b = make_grid("M011P5b")
_l5b = m5b.data.attributes.new("curv", 'FLOAT', 'POINT')
for _d in _l5b.data:
    _d.value = 0.5
for _old in list(m5b.users_collection):
    _old.objects.unlink(m5b)
c5b.objects.link(m5b)
vizC5 = av.add_visualizer(bpy.context, scope=c5b, attribute="curv",
                          domain="Point", style="Heat", display="Surface")
c5a.attrviz_scope_enabled = False
check("011 P5a disabling one collection leaves the other alone",
      m5b.display_type == "BOUNDS"
      and vizC5 in [r[0] for r in gpu_overlay._gpu_visualizers(
          bpy.context.scene)],
      m5b.display_type)
c5a.attrviz_scope_enabled = True



# === 011 Phase 5b: panel groups by collection ==============================
print(chr(10) + "== 011 Phase 5b: collection tree grouping ==")

c5x = av.new_scope_collection(bpy.context, "011P5bX")
c5y = av.new_scope_collection(bpy.context, "011P5bY")
mx = make_grid("M011P5bX")
my = make_grid("M011P5bY")
for _o, _c in ((mx, c5x), (my, c5y)):
    _l = _o.data.attributes.new("curv", 'FLOAT', 'POINT')
    for _d in _l.data:
        _d.value = 0.5
    for _old in list(_o.users_collection):
        _old.objects.unlink(_o)
    _c.objects.link(_o)
vx = av.add_visualizer(bpy.context, scope=c5x, attribute="curv",
                       domain="Point", style="Heat", display="Surface")
vy = av.add_visualizer(bpy.context, scope=c5y, attribute="curv",
                       domain="Point", style="Heat", display="Markers")

_groups = av.visualizers_by_scope(bpy.context.scene)
_by_name = {c.name: vs for c, vs in _groups if c is not None}
check("011 P5b every scope collection has a group",
      "011P5bX" in _by_name and "011P5bY" in _by_name, str(list(_by_name)))
check("011 P5b viz X is grouped under X only",
      vx in _by_name["011P5bX"] and vx not in _by_name["011P5bY"])
check("011 P5b viz Y is grouped under Y only",
      vy in _by_name["011P5bY"] and vy not in _by_name["011P5bX"])

_all_listed = [o for _c, vs in _groups for o in vs]
_all_viz = list(av.visualizers(bpy.context.scene))
check("011 P5b EVERY visualizer appears exactly once",
      sorted(o.name for o in _all_listed) == sorted(o.name for o in _all_viz),
      f"listed={len(_all_listed)} total={len(_all_viz)}")

# A disabled collection is still listed -- nothing draws without a visible row.
c5x.attrviz_scope_enabled = False
_groups2 = av.visualizers_by_scope(bpy.context.scene)
check("011 P5b a DISABLED collection is still listed",
      "011P5bX" in {c.name for c, _v in _groups2 if c is not None})
check("011 P5b its visualizer is still listed",
      vx in [o for c, vs in _groups2 if c is not None
             and c.name == "011P5bX" for o in vs])
c5x.attrviz_scope_enabled = True

# Switching active is targeting only -- it must not change what is drawn.
_drawn_before = sorted(r[0].name for r in
                       gpu_overlay._gpu_visualizers(bpy.context.scene))
_muted_before = sorted(o.name for o, _w in
                       gpu_overlay._active_surface_watch_meshes(
                           bpy.context.scene))
av.set_active_scope(bpy.context, c5y)
_drawn_after = sorted(r[0].name for r in
                      gpu_overlay._gpu_visualizers(bpy.context.scene))
_muted_after = sorted(o.name for o, _w in
                      gpu_overlay._active_surface_watch_meshes(
                          bpy.context.scene))
check("011 P5b THE GATE - switching active changes nothing drawn",
      _drawn_before == _drawn_after, f"{_drawn_before} vs {_drawn_after}")
check("011 P5b switching active changes nothing muted",
      _muted_before == _muted_after, f"{_muted_before} vs {_muted_after}")
check("011 P5b but it does retarget new actions",
      av.active_scope(bpy.context) == c5y)



# === S10: objects outside the view layer are not watched ===================
# A Collection is scene-independent data. Discovery spike S10 found
# iter_watch_meshes returning an object that view_layer.objects did not have --
# no evaluated state here, so sampling it describes geometry nobody can see.
print(chr(10) + "== S10: view-layer filter ==")

_floating = bpy.data.collections.new("S10FloatingScope")   # NOT linked to scene
_ghost_me = bpy.data.meshes.new("S10Ghost")
_ghost = bpy.data.objects.new("S10Ghost", _ghost_me)       # NOT linked to scene
_floating.objects.link(_ghost)
_real = make_grid("S10Real")
_floating.objects.link(_real)

check("S10 the ghost belongs to no scene collection",
      not any(c.name in bpy.context.scene.collection.children
              or c == bpy.context.scene.collection
              for c in _ghost.users_collection),
      str([c.name for c in _ghost.users_collection]))
check("S10 the real object IS linked into the scene",
      any(c == bpy.context.scene.collection
          or c.name in bpy.context.scene.collection.children
          for c in _real.users_collection),
      str([c.name for c in _real.users_collection]))
_seen = gpu_sample.iter_watch_meshes(None, _floating)
check("S10 iter_watch_meshes drops the out-of-view-layer object",
      _ghost not in _seen, str([o.name for o in _seen]))
check("S10 and still returns the one that is in it",
      _real in _seen, str([o.name for o in _seen]))
check("S10 is_watchable alone still accepts it (context-free predicate)",
      gpu_sample.is_watchable(_ghost))


print(f"\n== Result: {PASS} passed, {FAIL} failed ==")
if FAIL:
    sys.exit(1)
print("ALL WATCH COLLECTION TESTS PASSED")
