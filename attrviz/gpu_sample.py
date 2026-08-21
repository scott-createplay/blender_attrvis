"""AttrViz GPU sampler — depsgraph evaluated attrs → CPU buffers.

Promoted from the Stage A probe. Used by gpu_overlay (Markers/Arrows).
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

import bpy
import mathutils
import numpy as np

from . import node_builder

WATCH_COLLECTION = "attrvis"
WATCH_TYPES = frozenset({"MESH", "POINTCLOUD"})

try:
    from . import perf
except Exception:  # pragma: no cover
    perf = None


def _span(name):
    if perf is None:
        from contextlib import nullcontext
        return nullcontext()
    return perf.span(name)

SampleResult = Tuple[np.ndarray, np.ndarray, str]


def attr_text(val) -> str:
    """STRING attribute → Python str. Blender 5 stores these as bytes."""
    if val is None:
        return ""
    if isinstance(val, (bytes, bytearray)):
        return bytes(val).decode("utf-8", errors="replace")
    return str(val)


def is_visualizer(obj) -> bool:
    """True for an AttrViz visualizer carrier object.

    Lives here rather than only in the package __init__ because is_watchable
    needs it and gpu_sample cannot import the package. Its body touches only
    obj.type and obj.modifiers, so there is no circular dependency.
    """
    return (obj is not None and getattr(obj, "type", None) == 'MESH'
            and any(md.type == 'NODES' and md.node_group is not None
                    and md.node_group.get("attrviz_version")
                    for md in obj.modifiers))


def is_watchable(obj) -> bool:
    """True for an object a visualizer may sample.

    Carriers are excluded: _watch_candidates filters them at *selection* time,
    which a hand-managed scope collection bypasses entirely. Once Scope is
    per-visualizer (011) a carrier can be dragged into a scope in the outliner,
    and sampling a visualizer's own carrier is self-visualization.
    """
    return (obj is not None
            and getattr(obj, "type", None) in WATCH_TYPES
            and not is_visualizer(obj))


def _geom_has_verts(geom) -> bool:
    try:
        return geom is not None and hasattr(geom, "vertices") and len(geom.vertices) > 0
    except Exception:
        return False


def _is_pointcloud_data(geom) -> bool:
    return geom is not None and hasattr(geom, "points") and not hasattr(geom, "vertices")


def _point_count(geom) -> int:
    if geom is None:
        return 0
    try:
        return int(geom.attributes.domain_size('POINT'))
    except Exception:
        pass
    if hasattr(geom, "vertices"):
        return len(geom.vertices)
    pts = getattr(geom, "points", None)
    try:
        return len(pts) if pts is not None else 0
    except Exception:
        return 0


def _geom_has_points(geom) -> bool:
    return _is_pointcloud_data(geom) and _point_count(geom) > 0


def instances_cloud(gs):
    """The evaluated instances component, or None.

    On 5.2 this is ``GeometrySet.instances_pointcloud()`` — a METHOD, not one
    of the ``mesh`` / ``curves`` / ``pointcloud`` properties. That is why
    ``getattr(gs, "instances", None)`` silently returns None and adding
    "instances" to the component tuple does nothing. Tolerates either shape so
    a future rename does not break discovery outright.
    """
    if gs is None:
        return None
    src = getattr(gs, "instances_pointcloud", None)
    if src is None:
        return None
    try:
        pc = src() if callable(src) else src
    except Exception:
        return None
    if pc is None:
        return None
    try:
        return pc if len(pc.points) else None
    except Exception:
        return None


def _instance_transforms(pc):
    """(N, 4, 4) instance matrices, row-major (translation in row 3).

    NOT the ``position`` attribute. On 5.2 that component reads UNINITIALISED
    MEMORY — garbage (9.1e+30) or zeros — on every call but a lucky first one
    in a fresh process, while every other attribute on the same cloud
    (``instance_transform``, ``.reference_index``, user attributes) reads
    correctly and stably. Releasing references and forcing gc does not restore
    it, so the usual "hold the GeometrySet" rule does not apply.
    """
    n = _point_count(pc)
    if n == 0:
        return np.zeros((0, 4, 4), dtype=np.float32)
    xf = np.empty(n * 16, dtype=np.float32)
    if not _attr_into(pc, "instance_transform", "value", xf):
        return np.zeros((n, 4, 4), dtype=np.float32)
    return xf.reshape(-1, 4, 4)


def _instance_reference_index(pc) -> np.ndarray:
    n = _point_count(pc)
    idx = np.zeros(n, dtype=np.int32)
    _attr_into(pc, ".reference_index", "value", idx)
    return idx


def _instance_prototypes(geo):
    """Per-reference prototype geometry: [(verts Vx3, tri_verts Tx3), ...].

    MUST be read while the caller still holds ``geo`` — the referenced Mesh is
    freed with it ("StructRNA of type Mesh has been removed").
    """
    out = []
    try:
        refs = geo.instance_references()
    except Exception:
        return out
    for ref in refs:
        rm = getattr(ref, "mesh", None)
        if rm is None or len(rm.vertices) == 0:
            out.append(None)
            continue
        verts = _point_positions(rm)
        tri_v = np.zeros((0, 3), dtype=np.int32)
        try:
            rm.calc_loop_triangles()
            n_t = len(rm.loop_triangles)
            if n_t:
                buf = np.empty(n_t * 3, dtype=np.int32)
                rm.loop_triangles.foreach_get("vertices", buf)
                tri_v = buf.reshape(-1, 3)
        except Exception:
            pass
        out.append((verts, tri_v))
    return out


def _apply_instance_xform(local, mats):
    """Row-vector transform: (N, K, 3) local → world under (N, 4, 4) mats."""
    return (np.einsum('nkj,njm->nkm', local, mats[:, :3, :3])
            + mats[:, None, 3, :3])


def _instance_positions(pc, geo) -> np.ndarray:
    """One sample point per instance — the CENTROID of its geometry.

    Not the instance pivot. The pivot is an artifact of how the prototype was
    authored: for a building box it sits on the base, so a marker there lands
    inside the bottom face and is occluded by the very geometry it describes.
    The meaningful point is the middle of the instanced geometry.

    Uses the prototype's bounding-box centre rather than the vertex mean,
    which would drift toward finely subdivided regions.
    """
    n = _point_count(pc)
    if n == 0:
        return np.zeros((0, 3), dtype=np.float32)
    mats = _instance_transforms(pc)
    ridx = _instance_reference_index(pc)
    protos = _instance_prototypes(geo)
    centres = np.zeros((max(len(protos), 1), 3), dtype=np.float32)
    for i, proto in enumerate(protos):
        if proto is None:
            continue
        verts = proto[0]
        if len(verts):
            centres[i] = (verts.min(axis=0) + verts.max(axis=0)) * 0.5
    np.clip(ridx, 0, len(centres) - 1, out=ridx)
    local = centres[ridx][:, None, :]                     # (N, 1, 3)
    return np.ascontiguousarray(
        _apply_instance_xform(local, mats)[:, 0, :])


def _evaluated_source(obj: bpy.types.Object):
    """Evaluated mesh and/or point-cloud components.

    Prefer a mesh with vertices (no same-object mesh+cloud concat). If there
    is no mesh, take ``evaluated_geometry().pointcloud`` or evaluated
    PointCloud data. Keep the returned GeometrySet alive while using
    components taken from it (Blender GC gotcha).
    """
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    gs = None
    try:
        gs = ev.evaluated_geometry()
    except Exception:
        pass
    data = getattr(ev, "data", None)
    me = data if _geom_has_verts(data) else None
    if me is None and gs is not None:
        gs_me = getattr(gs, "mesh", None)
        if _geom_has_verts(gs_me):
            me = gs_me
    pc = None
    if me is None:
        if gs is not None:
            gs_pc = getattr(gs, "pointcloud", None)
            if _geom_has_points(gs_pc):
                pc = gs_pc
        if pc is None and _geom_has_points(data):
            pc = data
    return ev, me, pc, gs


def _evaluated_mesh(obj: bpy.types.Object):
    ev, me, _pc, _hold = _evaluated_source(obj)
    if not _geom_has_verts(me):
        return None, None
    return ev, me


def _read_attr(me, name: str, domain: str, n: int):
    attr = me.attributes.get(name)
    if attr is None or attr.domain != domain:
        return None, None
    dt = attr.data_type
    if dt == 'FLOAT':
        a = np.empty(n, dtype=np.float32)
        attr.data.foreach_get("value", a)
        return a, dt
    if dt in ('INT', 'BOOLEAN', 'INT8'):
        a = np.empty(n, dtype=np.int32)
        try:
            attr.data.foreach_get("value", a)
        except Exception:
            a = np.array([int(d.value) for d in attr.data], dtype=np.int32)
        return a, dt
    if dt in ('FLOAT_VECTOR', 'FLOAT2'):
        width = 3 if dt == 'FLOAT_VECTOR' else 2
        a = np.empty(n * width, dtype=np.float32)
        attr.data.foreach_get("vector", a)
        return a.reshape(-1, width), dt
    if dt in ('FLOAT_COLOR', 'BYTE_COLOR'):
        a = np.empty(n * 4, dtype=np.float32)
        attr.data.foreach_get("color", a)
        return a.reshape(-1, 4), dt
    if dt == 'STRING':
        # No foreach_get for strings. Blender 5 STRING values are bytes.
        return np.array([attr_text(d.value) for d in attr.data], dtype=object), dt
    return None, dt


# ── bulk accessors ──────────────────────────────────────────────────
#
# NEVER read geometry per element. Blender stores mesh data as contiguous
# typed arrays; the `vertices` / `polygons` / `loops` collections are legacy
# views over them, so a Python loop (or even `foreach_get` on the collection)
# re-resolves RNA per item. Measured at 160k verts / 637k loops:
#
#   Point positions   0.1 ms (attribute)   vs   16.4 ms at 1M via vertices.co
#   Face centers      9.3 ms (bulk)        vs   90.8 ms per-element
#   Face normals      0.1 ms (cache)       vs   93.1 ms per-element
#   Edge centers     23.0 ms (bulk+numpy)  vs  504.9 ms per-element
#   Corner positions 21.6 ms (bulk+numpy)  vs  518.7 ms per-element
#
# Everything below routes through _attr_into / _bulk_into. Both share one
# contract: fill the buffer and return True, or touch nothing and return
# False so the caller can fall back. Add a reader here, not inline.


def _attr_into(geom, name: str, prop: str, out, data_type=None) -> bool:
    """Fill ``out`` from a named attribute's backing array."""
    attrs = getattr(geom, "attributes", None)
    if attrs is None:
        return False
    try:
        attr = attrs.get(name)
        if attr is None:
            return False
        if data_type is not None and attr.data_type != data_type:
            return False
        attr.data.foreach_get(prop, out)
        return True
    except Exception:
        return False


def _bulk_into(coll, prop: str, out) -> bool:
    """Fill ``out`` from a collection via ``foreach_get``."""
    if coll is None:
        return False
    try:
        coll.foreach_get(prop, out)
        return True
    except Exception:
        return False


def _attr_vec3(geom, name: str, out) -> bool:
    """FLOAT_VECTOR attribute → ``out``. Kept for the position/cloud paths."""
    return _attr_into(geom, name, "vector", out, data_type='FLOAT_VECTOR')


def _point_positions(me) -> np.ndarray:
    cos = np.empty(len(me.vertices) * 3, dtype=np.float32)
    if not _attr_vec3(me, "position", cos):
        _bulk_into(me.vertices, "co", cos)
    return cos.reshape(-1, 3)


def _point_normals(me, n: int) -> np.ndarray:
    a = np.empty(n * 3, dtype=np.float32)
    if not _bulk_into(getattr(me, "vertex_normals", None), "vector", a):
        _bulk_into(me.vertices, "normal", a)
    return a.reshape(-1, 3)


def _face_normals(me, n: int) -> np.ndarray:
    a = np.empty(n * 3, dtype=np.float32)
    if not _bulk_into(getattr(me, "polygon_normals", None), "vector", a):
        _bulk_into(me.polygons, "normal", a)
    return a.reshape(-1, 3)


def _corner_vert_index(me) -> np.ndarray:
    """Vertex index per corner — the loop→vert map, bulk."""
    idx = np.empty(len(me.loops), dtype=np.int32)
    if not _attr_into(me, ".corner_vert", "value", idx):
        _bulk_into(me.loops, "vertex_index", idx)
    return idx


def _edge_vert_index(me) -> np.ndarray:
    """(N, 2) vertex indices per edge, bulk."""
    ev = np.empty(len(me.edges) * 2, dtype=np.int32)
    if not _attr_into(me, ".edge_verts", "value", ev):
        _bulk_into(me.edges, "vertices", ev)
    return ev.reshape(-1, 2)


def _cloud_positions(pc) -> np.ndarray:
    n = _point_count(pc)
    if n == 0:
        return np.zeros((0, 3), dtype=np.float32)
    cos = np.empty(n * 3, dtype=np.float32)
    if _attr_vec3(pc, "position", cos):
        return cos.reshape(-1, 3)
    pts = getattr(pc, "points", None)
    if pts is not None:
        try:
            pts.foreach_get("co", cos)
            return cos.reshape(-1, 3)
        except Exception:
            pass
    return np.zeros((0, 3), dtype=np.float32)


def _face_centers(me) -> np.ndarray:
    n = len(me.polygons)
    centers = np.empty(n * 3, dtype=np.float32)
    if _bulk_into(me.polygons, "center", centers):
        return centers.reshape(-1, 3)
    out = np.empty((n, 3), dtype=np.float32)
    for i, poly in enumerate(me.polygons):
        out[i] = poly.center
    return out


def _edge_centers(me) -> np.ndarray:
    if len(me.edges) == 0:
        return np.zeros((0, 3), dtype=np.float32)
    pos = _point_positions(me)
    ev = _edge_vert_index(me)
    return ((pos[ev[:, 0]] + pos[ev[:, 1]]) * 0.5).astype(np.float32)


def _corner_positions(me) -> np.ndarray:
    if len(me.loops) == 0:
        return np.zeros((0, 3), dtype=np.float32)
    return _point_positions(me)[_corner_vert_index(me)]


def _to_world(positions: np.ndarray, matrix_world) -> np.ndarray:
    if positions.size == 0:
        return positions
    mw = np.array(matrix_world, dtype=np.float64).reshape(4, 4)
    hom = np.empty((len(positions), 4), dtype=np.float64)
    hom[:, :3] = positions
    hom[:, 3] = 1.0
    return (hom @ mw.T)[:, :3].astype(np.float32)


def _normal_matrix(mw):
    try:
        return mw.inverted_safe().transposed().to_3x3()
    except Exception:
        return mw.to_3x3()


def _read_intrinsic(me, name: str, domain_ui: str, cos=None):
    """Index / Position / Normal from evaluated mesh APIs."""
    n_map = {
        "Point": len(me.vertices),
        "Edge": len(me.edges),
        "Face": len(me.polygons),
        "Corner": len(me.loops),
    }
    n = n_map.get(domain_ui, 0)
    if n == 0:
        return None, None

    if name == node_builder.INDEX_ATTR:
        return np.arange(n, dtype=np.int32), 'INT'

    if name in (node_builder.POSITION_ATTR, "position"):
        if domain_ui == "Point":
            if cos is None:
                cos = _point_positions(me)
            return cos.copy(), 'FLOAT_VECTOR'
        if domain_ui == "Face":
            return _face_centers(me), 'FLOAT_VECTOR'
        if domain_ui == "Edge":
            return _edge_centers(me), 'FLOAT_VECTOR'
        if domain_ui == "Corner":
            return _corner_positions(me), 'FLOAT_VECTOR'

    if name == node_builder.NORMAL_ATTR:
        if domain_ui == "Point":
            return _point_normals(me, n), 'FLOAT_VECTOR'
        if domain_ui == "Face":
            return _face_normals(me, n), 'FLOAT_VECTOR'
        if domain_ui == "Corner":
            # Smooth vertex normal indexed per corner — NOT me.corner_normals,
            # which are split normals and would change what Arrows draw on a
            # sharp-edged mesh. Behaviour preserved deliberately; switching to
            # split normals is a product call, not a perf one.
            return (_point_normals(me, len(me.vertices))[_corner_vert_index(me)],
                    'FLOAT_VECTOR')
    return None, None


def _read_cloud_intrinsic(pc, name: str, cos=None):
    """Index / Position on a Point Cloud. Normal is empty (no vertex normals)."""
    n = _point_count(pc)
    if n == 0:
        return None, None
    if name == node_builder.INDEX_ATTR:
        return np.arange(n, dtype=np.int32), 'INT'
    if name in (node_builder.POSITION_ATTR, "position"):
        if cos is None:
            cos = _cloud_positions(pc)
        return cos.copy(), 'FLOAT_VECTOR'
    return None, None


def sample_evaluated(
    obj: bpy.types.Object,
    attr: str,
    domain_ui: str = "Point",
    *,
    world_space: bool = True,
) -> Optional[SampleResult]:
    """Sample one watchable object. domain_ui is Point/Edge/Face/Corner."""
    with _span("sample.evaluated"):
        return _sample_evaluated_impl(
            obj, attr, domain_ui, world_space=world_space,
        )


def _sample_evaluated_impl(
    obj: bpy.types.Object,
    attr: str,
    domain_ui: str = "Point",
    *,
    world_space: bool = True,
) -> Optional[SampleResult]:
    domain_ui = domain_ui if domain_ui in node_builder.UI_DOMAINS else "Point"

    with _span("sample.depsgraph_source"):
        ev, me, pc, _hold = _evaluated_source(obj)

    if domain_ui == node_builder.INSTANCE_DOMAIN:
        # Un-realized instances. The component is a PointCloud whose
        # attributes self-report POINT; `position` is the instance origin in
        # object space (verified against depsgraph.object_instances), so the
        # normal _to_world step applies. Reading here is strictly more
        # faithful than realizing: Realize DUPLICATES each instance value onto
        # every vertex of its prototype, so realized Markers draw N coincident
        # markers per instance where this draws one.
        inst = instances_cloud(_hold)
        if inst is None:
            return None
        with _span("sample.positions.Instance"):
            positions = _instance_positions(inst, _hold)
        with _span("sample.read_attr"):
            if node_builder.is_intrinsic(attr):
                values, dtype = _read_cloud_intrinsic(inst, attr, cos=positions)
            else:
                values, dtype = _read_attr(inst, attr, 'POINT', len(positions))
        if values is None:
            return None
        if world_space:
            with _span("sample.to_world"):
                positions = _to_world(positions, ev.matrix_world)
        return positions, values, dtype

    blender_dom = node_builder.DOMAIN_TO_BLENDER[domain_ui]

    if _geom_has_verts(me):
        with _span(f"sample.positions.{domain_ui}"):
            if domain_ui == "Point":
                positions = _point_positions(me)
            elif domain_ui == "Face":
                positions = _face_centers(me)
            elif domain_ui == "Edge":
                positions = _edge_centers(me)
            else:
                positions = _corner_positions(me)

        with _span("sample.read_attr"):
            if node_builder.is_intrinsic(attr):
                values, dtype = _read_intrinsic(me, attr, domain_ui, cos=positions)
            else:
                values, dtype = _read_attr(me, attr, blender_dom, len(positions))
        if values is None:
            return None

        if world_space:
            with _span("sample.to_world"):
                if attr == node_builder.NORMAL_ATTR and dtype == 'FLOAT_VECTOR':
                    nmat = _normal_matrix(ev.matrix_world)
                    out = np.empty_like(values, dtype=np.float32)
                    for i in range(len(values)):
                        out[i] = nmat @ mathutils.Vector(values[i])
                    values = out
                positions = _to_world(positions, ev.matrix_world)
        return positions, values, dtype

    if pc is None or domain_ui != "Point":
        return None

    with _span("sample.positions.PointCloud"):
        positions = _cloud_positions(pc)
    with _span("sample.read_attr"):
        if node_builder.is_intrinsic(attr):
            values, dtype = _read_cloud_intrinsic(pc, attr, cos=positions)
        else:
            values, dtype = _read_attr(pc, attr, blender_dom, len(positions))
    if values is None:
        return None
    if world_space:
        with _span("sample.to_world"):
            positions = _to_world(positions, ev.matrix_world)
    return positions, values, dtype


def iter_watch_meshes(target, scope) -> List[bpy.types.Object]:
    """Resolve Target object + Scope collection → watchable objects."""
    seen = set()
    out: List[bpy.types.Object] = []

    def add(obj):
        if not is_watchable(obj):
            return
        key = obj.as_pointer()
        if key in seen:
            return
        seen.add(key)
        out.append(obj)

    add(target)
    if scope is not None:
        # nested collections
        stack = [scope]
        while stack:
            coll = stack.pop()
            for obj in coll.objects:
                add(obj)
            stack.extend(list(coll.children))
    return out


def scene_watch_collection():
    return bpy.data.collections.get(WATCH_COLLECTION)


def watch_meshes_for_visualizer(md) -> List[bpy.types.Object]:
    """Watchable objects this viz should sample (meshes and point clouds).

    Resolved from the visualizer's OWN Target and Scope sockets. The scene
    ``attrvis`` collection is the default Scope handed to new visualizers, not
    a global override -- it used to shadow every visualizer's own Scope, which
    made per-visualizer scoping impossible. See dev_tasks/011_viz_scope/POR.md.

    A visualizer with neither socket set watches nothing. migrate_viz_scope()
    backfills ``attrvis`` into those on load so pre-011 files keep working.
    """
    try:
        target = node_builder.get_input(md, "Target")
        scope = node_builder.get_input(md, "Scope")
    except Exception:
        return []
    return iter_watch_meshes(target, scope)


# ── change detection ────────────────────────────────────────────────
#
# The overlay draws from a Python-side snapshot, which lives outside the
# dependency graph, so it has to reconstruct the dirty signal the graph
# already computes. Counting elements off the ORIGINAL mesh (what this used
# to do) cannot see any of it: a GN scatter can drop a building and the
# counts never move, because they describe pre-modifier data.
#
# Measured on 5.2 — which signal actually reports what:
#
#   attribute values / vertex move / GN input   depsgraph_update_post, geometry
#   object transform                            depsgraph_update_post, transform
#   edit-mode vertex move (while IN edit mode)  depsgraph_update_post, geometry
#   frame change on an animated source          NOTHING — depsgraph_update_post
#                                               does not fire at all
#
# Hence two counters. Per-object epochs where the graph tells us which
# object changed, and one scene epoch for frame changes, where it does not:
# frame_change_post carries no per-object update list, so the honest move is
# to invalidate everything rather than guess.
_epochs: dict = {}
_scene_epoch: int = 0


def _epoch_key(obj) -> int:
    """Pointer of the ORIGINAL datablock — depsgraph updates may report the
    evaluated copy, while watch sets always hold originals."""
    return getattr(obj, "original", obj).as_pointer()


def note_depsgraph_updates(depsgraph) -> None:
    """Bump the epoch of every object the graph says changed. Hot path —
    this runs on every depsgraph update, so it only reads flags."""
    for update in depsgraph.updates:
        idb = update.id
        if not isinstance(idb, bpy.types.Object):
            continue
        if update.is_updated_geometry or update.is_updated_transform:
            key = _epoch_key(idb)
            _epochs[key] = _epochs.get(key, 0) + 1


def note_frame_change() -> None:
    global _scene_epoch
    _scene_epoch += 1


def reset_epochs() -> None:
    """File load: pointers are meaningless across files, and a reused
    pointer could otherwise mask a change."""
    global _scene_epoch
    _epochs.clear()
    _scene_epoch += 1


def watch_fingerprint(md) -> tuple:
    """Watch-set identity + change epochs. No geometry read, no counts.

    Identity (which objects, which datablocks) still belongs here: adding or
    removing a target need not fire a geometry update on anything. Element
    counts and matrix_world do not — they were a walk of every watched mesh
    on every redraw, and the epochs supersede them.
    """
    parts = []
    for obj in watch_meshes_for_visualizer(md):
        me = getattr(obj, "data", None)
        key = _epoch_key(obj)
        parts.append((
            key,
            me.as_pointer() if me is not None else 0,
            _epochs.get(key, 0),
        ))
    return (_scene_epoch, tuple(parts))


def watch_has_faces(md) -> bool:
    """True if any watched object has polygons (unevaluated mesh data)."""
    for obj in watch_meshes_for_visualizer(md):
        data = getattr(obj, "data", None)
        polys = getattr(data, "polygons", None)
        if polys is not None and len(polys) > 0:
            return True
    return False


def sample_visualizer_targets(
    md,
    *,
    world_space: bool = True,
    density: float = 1.0,
    seed: int = 0,
    cap: int = 50000,
) -> Optional[SampleResult]:
    """Sample Target∪Scope for a viz modifier; apply density + cap.

    Concatenates all watched meshes and point clouds. Density uses a stable hash cull
    (same spirit as GN Random Value < Density).
    """
    with _span("sample.visualizer_targets"):
        return _sample_visualizer_targets_impl(
            md, world_space=world_space, density=density, seed=seed, cap=cap,
        )


def _sample_visualizer_targets_impl(
    md,
    *,
    world_space: bool = True,
    density: float = 1.0,
    seed: int = 0,
    cap: int = 50000,
) -> Optional[SampleResult]:
    try:
        attr = node_builder.get_input(md, "Attribute") or ""
        domain_ui = node_builder.menu_input_name(md, "Domain") or "Point"
    except Exception:
        return None
    if not attr:
        return None

    meshes = watch_meshes_for_visualizer(md)
    if not meshes:
        return None
    if perf is not None:
        perf.note("watch_mesh_count", len(meshes))

    pos_parts = []
    val_parts = []
    dtype = None
    for obj in meshes:
        result = sample_evaluated(obj, attr, domain_ui, world_space=world_space)
        if result is None:
            continue
        p, v, dt = result
        pos_parts.append(p)
        val_parts.append(v)
        dtype = dt

    if not pos_parts or dtype is None:
        return None

    with _span("sample.concat_density_cap"):
        positions = np.concatenate(pos_parts, axis=0)
        # values may be 1D or 2D
        if val_parts[0].ndim == 1:
            values = np.concatenate(val_parts, axis=0)
        else:
            values = np.concatenate(val_parts, axis=0)

        n = len(positions)
        if n == 0:
            return positions, values, dtype

        # Density cull (stable). density≤0 → empty (keep real 0.0 from UI).
        density = float(max(0.0, min(1.0, density)))
        if density <= 1e-12:
            empty_pos = positions[:0]
            empty_val = values[:0]
            return empty_pos, empty_val, dtype
        if density < 1.0 - 1e-6:
            keep = np.empty(n, dtype=bool)
            for i in range(n):
                # xorshift-ish from index+seed
                x = (i * 747796405 + int(seed) * 2891336453) & 0xFFFFFFFF
                x = ((x >> ((x >> 28) + 4)) ^ x) * 277803737
                x = (x ^ (x >> 22)) & 0xFFFFFFFF
                keep[i] = (x / 0xFFFFFFFF) < density
            positions = positions[keep]
            values = values[keep]
            n = len(positions)

        # Cap stride removed — view cull (overlay_kind.view_cull_geometric)
        # handles budget after projection. L0 is Density-only.

    return positions, values, dtype


def _domain_element_colors(
    values: np.ndarray,
    dtype: str,
    style: str,
    *,
    vmin=None,
    vmax=None,
    seed: int = 0,
):
    from . import gpu_color
    return gpu_color.values_to_colors(
        values, dtype, style, vmin=vmin, vmax=vmax, seed=seed,
    )


def build_surface_tris(
    md,
    *,
    style: str = "Heat",
    vmin=None,
    vmax=None,
    seed: int = 0,
) -> Optional[Tuple[np.ndarray, np.ndarray, str, int]]:
    """Identity Surface pack: evaluated mesh loop-tris + domain corner values.

    Returns (positions Mx3, corner_values, dtype, n_tris) where M = 3 * n_tris.
    ``corner_values`` are raw attr samples at each tri corner (colormap in overlay).
    Edge domain is weakly supported (skipped).

    Positions are an **identity** copy of the evaluated mesh triangulation in
    world space (no inflate, face stride, or outlier cull). Only false-color
    changes at present time; topology matches ``len(me.loop_triangles)``.
    """
    with _span("sample.build_surface_tris"):
        return _build_surface_tris_impl(
            md,
            style=style,
            vmin=vmin,
            vmax=vmax,
            seed=seed,
        )


def _build_surface_tris_impl(
    md,
    *,
    style: str = "Heat",
    vmin=None,
    vmax=None,
    seed: int = 0,
) -> Optional[Tuple[np.ndarray, np.ndarray, str, int]]:
    # style/vmin/vmax/seed unused for packing; kept for API compat with overlay.
    _ = (style, vmin, vmax, seed)
    try:
        attr = node_builder.get_input(md, "Attribute") or ""
        domain_ui = node_builder.menu_input_name(md, "Domain") or "Point"
    except Exception:
        return None
    if not attr or domain_ui == "Edge":
        return None

    meshes = watch_meshes_for_visualizer(md)
    if not meshes:
        return None

    pos_chunks = []
    col_chunks = []
    dtype = None
    n_tris_total = 0

    if domain_ui == node_builder.INSTANCE_DOMAIN:
        # Surface on the instance domain paints each instance's REFERENCED
        # geometry with that instance's value — the useful reading of
        # "surface" here, and the reason not to make the user add a Realize
        # node. Realize would give the same picture at 8x the samples and the
        # wrong granularity; this transforms the prototype in numpy instead,
        # mutating nothing.
        for obj in meshes:
            ev, _me, _pc, hold = _evaluated_source(obj)
            inst = instances_cloud(hold)
            if inst is None:
                continue
            res = sample_evaluated(obj, attr, domain_ui, world_space=False)
            if res is None:
                continue
            _p, values, dt = res
            dtype = dt
            values = np.asarray(values)
            mats = _instance_transforms(inst)
            ridx = _instance_reference_index(inst)
            protos = _instance_prototypes(hold)   # read while `hold` is alive
            if not protos:
                continue
            np.clip(ridx, 0, len(protos) - 1, out=ridx)
            for r, proto in enumerate(protos):
                if proto is None:
                    continue
                verts, tri_v = proto
                if len(tri_v) == 0:
                    continue
                sel = np.flatnonzero(ridx == r)
                if sel.size == 0:
                    continue
                corners = verts[tri_v].reshape(-1, 3)          # (T*3, 3)
                local = np.broadcast_to(
                    corners, (sel.size, corners.shape[0], 3))
                world = _apply_instance_xform(local, mats[sel])
                world = world.reshape(-1, 3)
                world = _to_world(world, ev.matrix_world)
                pos_chunks.append(world.astype(np.float32))
                col_chunks.append(
                    np.repeat(values[sel], corners.shape[0], axis=0))
                n_tris_total += sel.size * len(tri_v)
        if not pos_chunks or dtype is None:
            return None
        return (np.concatenate(pos_chunks, axis=0),
                np.concatenate(col_chunks, axis=0), dtype, n_tris_total)

    for obj in meshes:
        ev, me, _pc, _hold = _evaluated_source(obj)
        if not _geom_has_verts(me):
            continue
        try:
            me.calc_loop_triangles()
        except Exception:
            pass
        tris = me.loop_triangles
        n_tris = len(tris)
        if n_tris == 0:
            continue

        # Sample domain values on this mesh
        result = sample_evaluated(obj, attr, domain_ui, world_space=False)
        if result is None:
            continue
        _local_pos, values, dt = result
        dtype = dt
        # Domain values — expanded to corners below; colormap applied in overlay
        # so Range/Style scrub can recolor without re-packing tris.
        values = np.asarray(values)

        cos = _point_positions(me)

        with _span("sample.surface_tri_pack"):
            vert_ids = np.empty(n_tris * 3, dtype=np.int32)
            poly_ids = np.empty(n_tris, dtype=np.int32)
            loop_ids = np.empty(n_tris * 3, dtype=np.int32)
            tris.foreach_get("vertices", vert_ids)
            tris.foreach_get("polygon_index", poly_ids)
            tris.foreach_get("loops", loop_ids)
            vert_ids = vert_ids.reshape(n_tris, 3)
            loop_ids = loop_ids.reshape(n_tris, 3)

            m = n_tris * 3
            flat_vi = vert_ids.reshape(-1)
            out_pos = cos[flat_vi]

            if domain_ui == "Point":
                out_val = values[flat_vi]
            elif domain_ui == "Face":
                out_val = values[poly_ids].repeat(3, axis=0)
            elif domain_ui == "Corner":
                out_val = values[loop_ids.reshape(-1)]
            else:
                out_val = np.broadcast_to(
                    values[0], (m,) + (() if values.ndim == 1 else values.shape[1:]),
                ).copy()

            out_pos = _to_world(out_pos, ev.matrix_world)

        pos_chunks.append(out_pos)
        col_chunks.append(out_val)
        n_tris_total += n_tris

    if not pos_chunks or dtype is None:
        return None
    positions = np.concatenate(pos_chunks, axis=0)
    corner_values = np.concatenate(col_chunks, axis=0)
    return positions, corner_values, dtype, n_tris_total


def buffer_stats(result: SampleResult) -> dict[str, Any]:
    positions, values, dtype = result
    stats: dict[str, Any] = {
        "n": int(len(positions)),
        "dtype": dtype,
        "pos_shape": tuple(positions.shape),
        "val_shape": tuple(getattr(values, "shape", ())),
    }
    if np.issubdtype(values.dtype, np.floating):
        # min/max are reshape-invariant, so the (N, -1) reshape bought nothing
        # and raised on an empty array -- the guard below was one line too late.
        stats["val_min"] = float(values.min()) if values.size else None
        stats["val_max"] = float(values.max()) if values.size else None
    elif np.issubdtype(values.dtype, np.integer):
        stats["val_min"] = int(values.min()) if values.size else None
        stats["val_max"] = int(values.max()) if values.size else None
        stats["n_unique"] = int(len(np.unique(values)))
    return stats
