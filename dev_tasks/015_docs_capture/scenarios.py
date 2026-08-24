"""The scenario registry — what makes this a tool rather than a pile of scripts.

Each scenario declares: source scene, window geometry, preferences, the UI
state to reach, **the assertions that must hold before the shutter opens**, and
where the image lands.

Imported both inside Blender (by `capture.py`) and outside it (by
`run_captures.py`), so `bpy` is optional at module scope.

Tick plans are transcribed from the M1/C3 probes, not invented. Reproducing
those images byte-for-byte is the Stage 1 gate, so the numbers are load-bearing
and must not be "tidied".
"""
from __future__ import annotations

try:
    import bpy
except ImportError:  # imported by the outside-Blender driver
    bpy = None

SCOPE_BLEND = "examples/attrviz_docs.blend"

# Window geometry is a scenario parameter, not a constant: the Viz panel is
# taller than a 900px window and the region does not scroll for a screenshot.
WIN_STD = (60, 60, 1600, 900)
WIN_TALL = (20, 20, 1600, 1250)

# probe_menu2's plan. The nudges exist because Blender holds the parent row
# while the cursor moves toward an open submenu; at row 0 they are no-ops that
# still cost ticks, and removing them would change the pixels.
MENU_TICKS = {"warmup": 14, "open": 15, "nudges": (17, 19, 21, 23), "shot": 37}
# probe_menu's plan — earlier shutter, no nudges, and NO preference changes.
CASCADE_TICKS = {"warmup": 12, "open": 13, "nudges": (), "shot": 27}
PANEL_TICKS = {"warmup": 16, "reveal": 17, "shot": 27}
# Three rungs at 12 ticks each, then room to settle.
# Steered menus wait much longer before opening. Measured: the hover fails
# when another Blender window has just closed — the new window has not taken
# focus yet, so cursor_warp reaches nothing. Two seconds of warmup is the
# difference between "works alone" and "works in a batch".
HOVER_WARMUP = 44
WALK_TICKS = {"warmup": HOVER_WARMUP, "open": HOVER_WARMUP + 1,
              "nudges": (), "shot": HOVER_WARMUP + 96}
HOVER_TICKS = {"warmup": HOVER_WARMUP, "open": HOVER_WARMUP + 1,
               "nudges": (), "shot": HOVER_WARMUP + 24}
# No menu to open; the settle loop decides when the overlay has finished.
VIEW_TICKS = {"warmup": 10, "shot": 12}

# Studio furniture off. A hero image should be the geometry and the ink,
# nothing else.
CLEAN_OVERLAYS = {"show_floor": False, "show_axis_x": False,
                  "show_axis_y": False, "show_cursor": False,
                  "show_text": False, "show_stats": False,
                  "show_gizmo": False, "show_outline_selected": False,
                  # Visualizer carriers are empties drawn as bounds; without
                  # this a black wireframe box sits around the hero.
                  "show_extras": False,
                  # Region overlap floats the toolbar and header OVER the
                  # WINDOW region, so cropping to it is not enough.
                  "show_region_toolbar": False,
                  "show_region_header": False,
                  "show_region_tool_header": False}

# Suzanne sits at the origin; frame her from Blender's habitual three-quarter
# angle so the form reads and the normals fan across the view.
# The black box around the hero is Suzanne's OWN mesh muted to BOUNDS by
# gpu_overlay (it stashes display_type so the real mesh does not z-fight the
# false-colour surface). It is real behaviour, so the shot keeps it; framing
# just has to leave room for it.
HERO_VIEW = {"location": (0.0, 0.0, 0.15), "rotation_deg": (72.0, 0.0, 32.0),
             "distance": 4.4}

# One fixture, clean shots: a scenario hides the collections it does not need
# (the POR's middle ground on the crowded-scene question).
# Every viewport shot is SOLO SUZANNE. A neighbouring object in frame reads as
# scene clutter, and a half-cropped one reads as a mistake. The
# partial-coverage claim lives in the panel's counts (3 objects - 2 carry
# grad), which is where a reader can actually check it.
BATCH = tuple("Batch_%02d" % (i + 1) for i in range(6))
SOLO = (("Torus_Flow", "Grid_Plates", "Cylinder_Bare", "Instanced_Cloud")
        + BATCH)
# Framed on the shelf of tiles, not on Suzanne.
BATCH_VIEW = {"location": (-0.5, -3.6, 0.0), "rotation_deg": (68.0, 0.0, 4.0),
              "distance": 9.0}
NOT_BATCH = ("Suzanne_Measured", "Torus_Flow", "Grid_Plates",
             "Cylinder_Bare", "Instanced_Cloud")
HERO_HIDE = SOLO
ARROWS_HIDE = SOLO

MENU_PREFS = {"open_toplevel_delay": 0, "open_sublevel_delay": 0,
              "show_tooltips": False}
PANEL_PREFS = {"show_tooltips": False}
# The cascade shot was taken before the prefs lever was found. Setting tooltips
# off here would change the image and break its baseline.
CASCADE_PREFS = {}


# --------------------------------------------------------------------------
# setup steps
# --------------------------------------------------------------------------
def _make_active(name):
    obj = bpy.data.objects[name]
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return {"active": obj.name}


def select_hero(ctx):
    """Suzanne_Measured carries grad + curv on Point and is not a visualizer,
    so ATTRVIZ_MT_visualize.poll passes and the menu lists real attributes.

    Pin the visualizer state too: menu shots were inheriting whatever the
    fixture happened to have enabled, so adding a visualizer to the scene
    silently repainted every menu background.
    """
    out = _make_active("Suzanne_Measured")
    out.update(_only_viz(["VIZ_curv_surface", "VIZ_grad_arrows"]))
    return out


def _viz(name):
    return bpy.data.objects[name]


def _hide(names):
    for obj in bpy.data.objects:
        if not obj.name.startswith("VIZ_"):
            obj.hide_viewport = obj.name in names
    return {"hidden": list(names)}


def stage_hero(ctx):
    """Both visualizers on: curv as a Heat surface, grad as RGB arrows, on the
    same object. Nothing selected, so no orange outline in the shot."""
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    bpy.context.view_layer.objects.active = None
    out = _only_viz(["VIZ_curv_surface", "VIZ_grad_arrows"])
    # Drop from scope AND hide: hiding alone leaves the overlay ink drawing.
    out.update(_drop_from_scopes(HERO_HIDE))
    out.update(_hide(HERO_HIDE))
    return out


def stage_arrows_only(ctx):
    """Arrows alone. The surface is their own background, so proving arrow ink
    exists means removing the surface — otherwise a Heat-only frame would
    satisfy any ink count."""
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    bpy.context.view_layer.objects.active = None
    out = _only_viz(["VIZ_grad_arrows"])
    out.update(_drop_from_scopes(ARROWS_HIDE))
    out.update(_hide(ARROWS_HIDE))
    out.update(_unmute("Suzanne_Measured"))
    return out


def _unmute(name):
    """Undo the Surface visualizer's solid mute.

    Arrows are ADDITIVE — they belong on visible geometry, and the tableau
    proves it: its Markers, Arrows and Tags cells all show the grey mesh, only
    Surface goes to BOUNDS. The mute here is left over from the Surface
    visualizer this scenario just switched off, and it is stashed in the
    .blend as an ID property, so it survives the file load.

    Use the addon's OWN restore rather than assigning display_type directly —
    that also clears the stash, which is what a user toggling Enabled gets.
    """
    from attrviz import gpu_overlay
    obj = bpy.data.objects[name]
    gpu_overlay._restore_target_solid(obj)
    return {"display_type": obj.display_type}


def assert_visible_and_enabled(obj_name, names):
    """Arrows must sit ON the geometry. A BOUNDS source mesh means the shot
    shows a floating field of ink and no object — which is not what Arrows
    does, and would misinform every reader."""
    inner = assert_enabled_only(names)

    def check(ctx):
        out = inner(ctx)
        dt = bpy.data.objects[obj_name].display_type
        if dt in ("BOUNDS", "WIRE"):
            raise AssertionError(
                f"{obj_name} is {dt}; the source geometry is hidden, so this "
                "shot would claim Arrows replaces the mesh. It does not.")
        out["display_type"] = dt
        return out
    return check


def assert_enabled_only(names):
    def check(ctx):
        on = [o.name for o in bpy.data.objects
              if getattr(o, "attrviz_enabled", False)
              and o.name.startswith("VIZ_")]
        if sorted(on) != sorted(names):
            raise AssertionError(f"enabled visualizers {on}, expected {names}")
        return {"enabled_asserted": on}
    return check


TABLEAU_HIDE = SOLO
TABLEAU_VIEW = {"location": (0.0, 0.0, 0.15), "rotation_deg": (74.0, 0.0, 26.0),
                "distance": 4.6}


def _drop_from_scopes(names):
    """Hiding an object is NOT enough.

    `hide_viewport` removes the mesh but the overlay keeps drawing its ink —
    measured: Torus_Flow vanished from the tableau while its markers, arrows
    and tags stayed. To keep an object out of a shot it has to leave the
    scope, not just the viewport.
    """
    import attrviz as av
    dropped = []
    for coll in av.scope_collections(bpy.context.scene):
        for name in names:
            obj = bpy.data.objects.get(name)
            if obj is not None and obj.name in coll.objects:
                coll.objects.unlink(obj)
                dropped.append(f"{name}<-{coll.name}")
    return {"dropped_from_scope": dropped}


def _clean(text):
    """The bitmap font has no glyph for punctuation like the panel's middot or
    an underscore; unmapped characters would render as boxes."""
    from bitfont import GLYPHS
    return "".join(c if c.upper() in GLYPHS else " " for c in text)


def _viz_caption(viz_name, omit_display=False):
    """Read the caption off the visualizer itself.

    Every field here is live: rename the attribute, change the domain or the
    Type, and the burnt-in caption follows. A typed caption would not.
    """
    def hud(ctx):
        import attrviz as av
        from attrviz import node_builder
        viz = bpy.data.objects[viz_name]
        md = av.viz_modifier(viz)
        # The same three reads the panel's own header uses, so the burnt-in
        # caption cannot disagree with the panel in the next screenshot.
        attr = node_builder.get_input(md, "Attribute") or viz.name
        domain = node_builder.menu_input_name(md, "Domain") or "?"
        display = node_builder.menu_input_name(md, "Display") or "?"
        dtypes, _dom = av._target_attr_meta(md)
        dtype = "/".join(sorted(dtypes)) if dtypes else "?"
        scope = av.viz_scope(md)
        head = f"{attr}  {domain}" if omit_display else             f"{attr}  {domain}  {display}"
        return [_clean(head)]
    return hud


def _active_caption(extra="", _unused=None):
    """For menu shots: which object's attributes are being listed.

    The menu itself never says. With several objects in the scene a reader
    cannot tell whose attributes these are, which is exactly the ambiguity a
    caption should remove.
    """
    def hud(ctx):
        obj = bpy.context.view_layer.objects.active
        return [_clean(obj.name if obj else "none")]
    return hud


def _only_viz(names):
    """Exactly these visualizers on, everything else off."""
    for obj in bpy.data.objects:
        if obj.name.startswith("VIZ_"):
            obj.attrviz_enabled = obj.name in names
    return {"enabled": list(names)}


def stage_batch(ctx):
    """One visualizer over six objects, all on one shared ramp."""
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    bpy.context.view_layer.objects.active = None
    out = _only_viz(["VIZ_wear_batch"])
    out.update(_drop_from_scopes(NOT_BATCH))
    out.update(_hide(NOT_BATCH))
    return out


def _solo_suzanne():
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    bpy.context.view_layer.objects.active = None
    out = _drop_from_scopes(SOLO)
    out.update(_hide(SOLO))
    return out


def stage_color_heat(ctx):
    out = _solo_suzanne()
    out.update(_only_viz(["VIZ_curv_surface"]))
    _viz("VIZ_curv_surface").attrviz_style = "Heat"
    return out


def stage_color_rgb(ctx):
    """grad is a vector, so RGB maps its channels straight to colour."""
    viz = _viz("VIZ_grad_arrows")
    viz.attrviz_style = "RGB"
    viz.attrviz_display = "Surface"
    return _only_viz(["VIZ_grad_arrows"])


def stage_color_random(ctx):
    """face_id is an int, so it gets a stable hash colour per id."""
    return _only_viz(["VIZ_faceid_surface"])


def stage_domain_point(ctx):
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    bpy.context.view_layer.objects.active = None
    out = _only_viz(["VIZ_curv_surface"])
    out.update(_drop_from_scopes(SOLO))
    out.update(_hide(SOLO))
    out.update(_unmute("Suzanne_Measured"))
    return out


def stage_domain_face(ctx):
    out = _only_viz(["VIZ_faceid_surface"])
    return out


def assert_batch_spread(ctx):
    """The outlier has to actually sit outside the others, or the picture
    claims something it cannot show."""
    import attrviz as av
    carriers, bare = [], []
    for name in BATCH:
        obj = bpy.data.objects[name]
        by, _ = av.attributes_by_domain(obj)
        names = [n for n, _t in by.get("Point", [])]
        (carriers if "wear" in names else bare).append(name)
    if len(carriers) < 4 or not bare:
        raise AssertionError(
            f"batch needs carriers and at least one non-carrier; "
            f"carriers={carriers} bare={bare}")
    return {"carriers": carriers, "non_carriers": bare}


def stage_result(ctx):
    """What the click in menu_breadcrumb produced.

    The viewport and the panel in ONE frame: every other figure shows one
    surface with the other cropped away, so none of them shows the tool
    actually in use.
    """
    import attrviz as av
    # Region overlap floats the sidebar OVER the viewport, which would leave
    # Suzanne half-hidden behind it. Off, the two share the area.
    bpy.context.preferences.system.use_region_overlap = False
    out = _solo_suzanne()
    # Delete the other visualizers rather than just disabling them. This shot
    # is the state right after ONE click, and a panel listing four greyed-out
    # visualizers in scopes the staging emptied ("0 obj / 1 viz") describes a
    # scene nobody has.
    keep = "VIZ_curv_surface"
    for obj in [o for o in bpy.data.objects
                if o.name.startswith("VIZ_") and o.name != keep]:
        bpy.data.objects.remove(obj, do_unlink=True)
    viz = _viz(keep)
    viz.attrviz_enabled = True
    viz.attrviz_style = "Heat"
    # Expand the one that was just created, so the reader's eye lands on the
    # row the menu promised.
    viz.attrviz_ui_expand = True
    out["kept"] = keep
    out.update(_unmute("Suzanne_Measured"))
    with bpy.context.temp_override(window=ctx["window"], area=ctx["area"],
                                   region=ctx["regions"].get("WINDOW")):
        av._reveal_viz_panel(bpy.context)
    ctx["area"].tag_redraw()
    return out


def assert_result(ctx):
    """The panel must be showing AND the surface must be drawn — a shot with
    one of the two missing is not the claim being made."""
    ui = ctx["regions"].get("UI")
    if ui is None or ui.width <= 1:
        raise AssertionError("sidebar is not open")
    if getattr(ui, "active_panel_category", None) != "Viz":
        raise AssertionError("sidebar is not on the Viz tab")
    vizzes = [o.name for o in bpy.data.objects if o.name.startswith("VIZ_")]
    if vizzes != ["VIZ_curv_surface"]:
        raise AssertionError(f"expected one visualizer, got {vizzes}")
    if not bpy.data.objects["VIZ_curv_surface"].attrviz_ui_expand:
        raise AssertionError("the visualizer is collapsed; its settings are "
                             "the point of the shot")
    return {"visualizers": vizzes, "ui_width": ui.width}


def stage_noop(ctx):
    """A filmstrip's stages do their own staging.

    The pre-switch guard requires the frame to CHANGE before a cell is
    accepted, so if `setup` has already put the scene in stage 0's state,
    stage 0 is a no-op and the cell never settles. Leave the scene alone here.
    """
    return {}


def stage_tableau(ctx):
    """One attribute, every Display type.

    `grad` is a vector, and that is not incidental: **Arrows needs a
    direction**, so a vector attribute is the only kind that every Display can
    render. A float would give an empty Arrows cell and the tableau would be
    making a claim it cannot support.
    """
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    bpy.context.view_layer.objects.active = None
    out = _only_viz(["VIZ_grad_arrows"])
    out["attribute"] = "grad"
    # A vector reads as RGB; Heat wants a scalar. Pin Colour so the Type
    # tableau varies ONE axis honestly rather than implying Colour follows
    # Type.
    _viz("VIZ_grad_arrows").attrviz_style = "RGB"
    out.update(_drop_from_scopes(TABLEAU_HIDE))
    out.update(_hide(TABLEAU_HIDE))
    # Tags defaults to a cap of 10000. On 507 points that is a white mass, not
    # a readable label — legible Tags need a cap the eye can follow.
    from attrviz import node_builder
    md = next(m for m in _viz("VIZ_grad_arrows").modifiers if m.type == 'NODES')
    node_builder.set_input(md, "Tag Cap", 8)
    out["tag_cap"] = 8
    return out


def assert_tableau(ctx):
    """The attribute must be a vector, or Arrows cannot draw — assert that
    rather than discovering it as an empty cell."""
    import attrviz as av
    from attrviz import node_builder
    viz = _viz("VIZ_grad_arrows")
    obj = bpy.data.objects["Suzanne_Measured"]
    by, _ = av.attributes_by_domain(obj)
    kinds = dict(by.get("Point", []))
    dtype = kinds.get("grad")
    if dtype != "FLOAT_VECTOR":
        raise AssertionError(
            f"grad is {dtype!r}, not FLOAT_VECTOR; Arrows needs a direction")
    return {"attribute": "grad", "dtype": dtype,
            "displays": list(node_builder.DISPLAYS),
            "final_display": viz.attrviz_display}


def stage_spreadsheet(ctx):
    """Blender's own Spreadsheet, for contrast.

    Not our panel. It is here because it shows what AttrViz adds: the
    spreadsheet lists stored attributes, so a GN-authored `curv` appears — but
    `Normal` never does, because it is computed, not stored. AttrViz offers it
    anyway, as an intrinsic.
    """
    _make_active("Suzanne_Measured")
    area = ctx["area"]
    area.type = 'SPREADSHEET'
    space = area.spaces.active
    space.geometry_component_type = 'MESH'
    space.attribute_domain = 'POINT'
    # EVALUATED or curv and grad are simply absent: they are written by the
    # modifier, and the original mesh has neither.
    space.object_eval_state = 'EVALUATED'
    # The area type changed, so the cached region map is stale.
    ctx["regions"] = {r.type: r for r in area.regions}
    area.tag_redraw()
    return {"editor": area.type, "domain": space.attribute_domain,
            "eval_state": space.object_eval_state}


def assert_spreadsheet_contrast(ctx):
    """Assert the claim the caption makes, rather than trusting the picture.

    Stored attributes are what the spreadsheet can show; AttrViz's intrinsics
    are computed and have no stored counterpart.
    """
    import attrviz as av
    obj = bpy.context.view_layer.objects.active
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = obj.evaluated_get(depsgraph).to_mesh()
    stored = set(mesh.attributes.keys())
    obj.evaluated_get(depsgraph).to_mesh_clear()

    for name in ("curv", "grad"):
        if name not in stored:
            raise AssertionError(f"{name!r} is not stored; spreadsheet would "
                                 f"not show it. stored={sorted(stored)}")
    if "Normal" in stored:
        raise AssertionError("'Normal' is stored after all — the whole "
                             "intrinsic-vs-stored contrast is wrong")

    by, _ = av.attributes_by_domain(obj)
    point = [n for n, _t in by.get("Point", [])]
    for name in ("Index", "Position", "Normal"):
        if name not in point:
            raise AssertionError(f"AttrViz does not offer {name!r} on Point")
    return {"stored": sorted(stored), "attrviz_point": point}


def select_instanced(ctx):
    """Instanced_Cloud has Instance elements and NO mesh elements, which is
    the only way to reach the 'add Realize Instances' guidance."""
    return _make_active("Instanced_Cloud")


def reveal_panel(ctx):
    """Use the addon's OWN helper, so the docs show the panel through the same
    code path the addon opens for a first visualizer."""
    import attrviz as av
    with bpy.context.temp_override(window=ctx["window"], area=ctx["area"],
                                   region=ctx["regions"].get("WINDOW")):
        av._reveal_viz_panel(bpy.context)
    ctx["area"].tag_redraw()
    return {"revealed": True}


# --------------------------------------------------------------------------
# assertions — these run BEFORE the shutter, and raise to abort the shot
# --------------------------------------------------------------------------
def assert_instanced(ctx):
    """The guidance only renders when Instance is populated and the mesh
    domains are not. Assert exactly that, or the shot is of nothing."""
    import attrviz as av
    from attrviz import node_builder
    obj = bpy.context.view_layer.objects.active
    by, _ = av.attributes_by_domain(obj)
    if not by.get(node_builder.INSTANCE_DOMAIN):
        raise AssertionError(f"{obj.name} has no Instance elements")
    mesh_domains = [d for d in node_builder.DOMAINS if by.get(d)]
    if mesh_domains:
        raise AssertionError(
            f"{obj.name} still has mesh domains {mesh_domains}; the "
            "instanced-geometry guidance will not render")
    return {"active": obj.name, "instance_only": True}


def assert_attrs_on_active(ctx):
    import attrviz as av
    obj = bpy.context.view_layer.objects.active
    if obj is None:
        raise AssertionError("no active object")
    if av.is_visualizer(obj):
        raise AssertionError(f"{obj.name} is a visualizer; the menu would poll off")
    by, _ = av.attributes_by_domain(obj)
    populated = sorted(d for d, v in by.items() if v)
    if not populated:
        raise AssertionError(f"{obj.name} has no attributes on any domain")
    return {"active": obj.name, "domains": populated}


def assert_two_scopes_atleast(ctx):
    import attrviz as av
    groups = av.visualizers_by_scope(bpy.context.scene)
    items = groups.items() if hasattr(groups, "items") else groups
    named = [[getattr(k, "name", str(k)), len(v)] for k, v in items]
    if len(named) < 2:
        raise AssertionError(f"expected several scope groups, got {named}")
    return {"groups": named}


def assert_two_scopes(ctx):
    import attrviz as av
    groups = av.visualizers_by_scope(bpy.context.scene)
    items = groups.items() if hasattr(groups, "items") else groups
    named = [[getattr(k, "name", str(k)), len(v)] for k, v in items]
    if len(named) != 5:
        raise AssertionError(f"expected 5 scope groups, got {named}")
    return {"groups": named}


def assert_panel_ready(ctx):
    out = assert_two_scopes(ctx)
    ui = ctx["regions"].get("UI")
    if ui is None or ui.width <= 1:
        raise AssertionError("sidebar is not open")
    category = getattr(ui, "active_panel_category", None)
    if category != "Viz":
        raise AssertionError(f"sidebar tab is {category!r}, not 'Viz'")
    out["ui_region"] = [ui.x, ui.y, ui.width, ui.height]
    return out


# --------------------------------------------------------------------------
# the registry
# --------------------------------------------------------------------------
def _menu(name, menu_id, gated=True, window=None, hover=None,
          retries=0):
    return {
        "name": name,
        "blend": SCOPE_BLEND,
        "window": window or WIN_STD,
        "prefs": MENU_PREFS,
        "setup": select_hero,
        "assertions": assert_attrs_on_active,
        # Frame on Suzanne and strip the studio furniture. Menu shots must not
        # drop objects from scopes — menu_scope prints live collection counts,
        # and menu_edit names the active scope — so the neighbours are removed
        # by FRAMING rather than by changing the scene.
        "shot": {"kind": "menu", "menu": menu_id, "cursor": "third",
                 "view": HERO_VIEW, "overlays": CLEAN_OVERLAYS,
                 "ticks": HOVER_TICKS if hover else MENU_TICKS,
                 "hud": _active_caption(), "hover": hover},
        "gated": gated,
        "retries": retries,
        "doc": "see DOC_MAP.md",
    }


SCENARIOS = [
    {
        "name": "panel_scope_tree",
        "blend": SCOPE_BLEND,
        "window": WIN_TALL,
        "prefs": PANEL_PREFS,
        "setup": reveal_panel,
        "assertions": assert_panel_ready,
        "shot": {"kind": "panel", "crop": "UI", "ticks": PANEL_TICKS},
        "gated": True,
        "doc": "README 'What it is' + 'Scopes'",
    },
    # ATTRVIZ_MT_root's first row expands a child, so it is a cascade and
    # racy by the same rule as menu_visualize_point: it differed from its own
    # second pass under --selfcheck. Captured for the docs, never gated.
    _menu("menu_root", "ATTRVIZ_MT_root", gated=False),
    # Blender's OWN object context menu — the actual thing RMB opens, with
    # the AttrViz entry appended at the bottom. Every other menu shot starts
    # below this level, because call_menu opens a menu as its own root.
    # Needs the TALL window: Blender's object context menu is ~20 entries and
    # clips at 900px, which hides the AttrViz row appended at its bottom.
    _menu("menu_object_context", "VIEW3D_MT_object_context_menu",
          gated=False, window=WIN_TALL, hover="last", retries=3),
    {
        # The whole path in one image: RMB -> AttrViz -> Visualize Attribute
        # -> Point -> the attributes. Every rung is located by diffing for the
        # menu that just appeared, so nothing here counts rows or hardcodes
        # pixels.
        "name": "menu_breadcrumb",
        "blend": SCOPE_BLEND,
        # As wide as the display allows: the full chain is roughly 1150px
        # of menus side by side.
        "window": (8, 8, 1900, 1250),
        "prefs": MENU_PREFS,
        "setup": select_hero,
        "assertions": assert_attrs_on_active,
        "shot": {"kind": "menu", "menu": "VIEW3D_MT_object_context_menu",
                 "cursor": "highleft", "view": HERO_VIEW,
                 "overlays": CLEAN_OVERLAYS, "ticks": WALK_TICKS,
                 # ...and one rung further, onto `curv` itself: -2 is the
                 # second entry from the bottom, past the section labels.
                 "hover_path": ["last", 0, 0, -2],
                 "hud": _active_caption()},
        "gated": False,
        "retries": 3,
        "doc": "README - the RMB path",
    },
    _menu("menu_edit", "ATTRVIZ_MT_edit"),
    _menu("menu_scope", "ATTRVIZ_MT_scope"),
    _menu("menu_domain_face", "ATTRVIZ_MT_domain_face"),
    {
        # The un-realized instances guidance: no test, no doc, and only
        # reachable on an object whose mesh domains are empty.
        "name": "menu_instanced",
        "blend": SCOPE_BLEND,
        "window": WIN_STD,
        "prefs": MENU_PREFS,
        "setup": select_instanced,
        "assertions": assert_instanced,
        "shot": {"kind": "menu", "menu": "ATTRVIZ_MT_visualize",
                 "cursor": "third", "ticks": MENU_TICKS},
        "gated": True,
        "doc": "README 'Visualization axes' — instanced geometry",
    },
    {
        # The hero. Surface + Arrows on ONE object, which is only possible
        # because Suzanne is in two scopes.
        "name": "viewport_hero",
        "blend": SCOPE_BLEND,
        "window": WIN_STD,
        "prefs": PANEL_PREFS,
        "setup": stage_hero,
        "assertions": assert_enabled_only(
            ["VIZ_curv_surface", "VIZ_grad_arrows"]),
        "shot": {"kind": "viewport", "crop": "WINDOW", "view": HERO_VIEW,
                 "overlays": CLEAN_OVERLAYS, "ticks": VIEW_TICKS,
                 "min_ink_px": 20000,
                 "hud": _viz_caption("VIZ_curv_surface")},
        "gated": True,
        "doc": "README hero image",
    },
    {
        # S9 — arrows on the carriers, and the non-carrier untouched.
        "name": "viewport_arrows",
        "blend": SCOPE_BLEND,
        "window": WIN_STD,
        "prefs": PANEL_PREFS,
        "setup": stage_arrows_only,
        "assertions": assert_visible_and_enabled(
            "Suzanne_Measured", ["VIZ_grad_arrows"]),
        "shot": {"kind": "viewport", "crop": "WINDOW", "view": HERO_VIEW,
                 "overlays": CLEAN_OVERLAYS, "ticks": VIEW_TICKS,
                 "min_ink_px": 2000,
                 "hud": _viz_caption("VIZ_grad_arrows")},
        "gated": True,
        "doc": "README 'Visualization axes' — Arrows",
    },
    {
        # One attribute, every Display type, in a single image. The cell list
        # is node_builder.DISPLAYS, so a future type joins on its own.
        "name": "tableau_displays",
        "blend": SCOPE_BLEND,
        "window": (60, 60, 1100, 760),
        "prefs": PANEL_PREFS,
        "setup": stage_tableau,
        "assertions": assert_tableau,
        "shot": {"kind": "tableau", "crop": "WINDOW", "view": TABLEAU_VIEW,
                 "overlays": CLEAN_OVERLAYS, "ticks": VIEW_TICKS,
                 "viz": "VIZ_grad_arrows", "min_cell_px": 500,
                 # Display varies per cell, so it must not appear in a caption
                 # that spans the whole tableau.
                 "hud": _viz_caption("VIZ_grad_arrows", omit_display=True)},
        "gated": True,
        "doc": "README 'Visualization axes' — same attribute, every Type",
    },
    {
        # The correlation shot: the same values as numbers and as ink, side by
        # side. Neither half means much alone — a table of floats is not a
        # shape, and a coloured monkey is not evidence.
        "name": "strip_numbers_to_ink",
        "blend": SCOPE_BLEND,
        "window": (60, 60, 1180, 800),
        "prefs": PANEL_PREFS,
        "setup": stage_noop,
        "assertions": assert_tableau,
        "shot": {"kind": "filmstrip", "view": HERO_VIEW,
                 "overlays": CLEAN_OVERLAYS, "ticks": VIEW_TICKS,
                 "min_cell_px": 500,
                 "stages": [("VIEWPORT", stage_hero),
                            ("SPREADSHEET", stage_spreadsheet)]},
        "gated": True,
        "doc": "README 'What it is' — numbers and ink are the same data",
    },
    {
        # One visualizer, six objects, one shared ramp — and one tile that is
        # plainly hotter than the rest.
        "name": "viewport_scope_compare",
        "blend": SCOPE_BLEND,
        "window": (60, 60, 1500, 760),
        "prefs": PANEL_PREFS,
        "setup": stage_batch,
        "assertions": assert_batch_spread,
        "shot": {"kind": "viewport", "crop": "WINDOW", "view": BATCH_VIEW,
                 "overlays": CLEAN_OVERLAYS, "ticks": VIEW_TICKS,
                 "min_ink_px": 6000,
                 "hud": _viz_caption("VIZ_wear_batch")},
        "gated": True,
        "doc": "README - one visualizer, many objects",
    },
    {
        # Same object, two domains. A Face attribute is flat per facet; a
        # Point attribute is smooth. Two different objects would not show it.
        "name": "strip_domains",
        "blend": SCOPE_BLEND,
        "window": (60, 60, 1500, 780),
        "prefs": PANEL_PREFS,
        "setup": stage_noop,
        "assertions": assert_two_scopes_atleast,
        "shot": {"kind": "filmstrip", "view": HERO_VIEW,
                 "overlays": CLEAN_OVERLAYS, "ticks": VIEW_TICKS,
                 "min_cell_px": 500,
                 "stages": [("POINT  CURV", stage_domain_point),
                            ("FACE  FACE ID", stage_domain_face)]},
        "gated": True,
        "doc": "README - domain",
    },
    {
        # Colour is chosen by the DATA, not by taste: Heat needs a scalar,
        # RGB needs a vector, Random needs an id. One object, three
        # attributes, three modes — the honest way to show it.
        "name": "strip_colors",
        "blend": SCOPE_BLEND,
        "window": (60, 60, 1560, 720),
        "prefs": PANEL_PREFS,
        "setup": stage_noop,
        "assertions": assert_two_scopes_atleast,
        "shot": {"kind": "filmstrip", "view": HERO_VIEW,
                 "overlays": CLEAN_OVERLAYS, "ticks": VIEW_TICKS,
                 "min_cell_px": 500,
                 "stages": [("HEAT  CURV  FLOAT", stage_color_heat),
                            ("RGB  GRAD  VECTOR", stage_color_rgb),
                            ("RANDOM  FACE ID  INT", stage_color_random)]},
        "gated": True,
        "doc": "README - Colour follows the data type",
    },
    {
        # The consequence of the click walked in menu_breadcrumb.
        "name": "viewport_result",
        "blend": SCOPE_BLEND,
        "window": (20, 20, 1600, 1150),
        "prefs": PANEL_PREFS,
        "setup": stage_result,
        "assertions": assert_result,
        "shot": {"kind": "panel", "ticks": PANEL_TICKS, "view": HERO_VIEW,
                 "overlays": CLEAN_OVERLAYS, "min_ink_px": 15000},
        # No burnt-in caption: the panel states curv - Point - Surface itself,
        # which is better evidence than a caption repeating it.
        "gated": True,
        "doc": "README - the result of the click",
    },
    {
        # Not our panel. The contrast is the point.
        "name": "spreadsheet_attributes",
        "blend": SCOPE_BLEND,
        "window": WIN_STD,
        "prefs": PANEL_PREFS,
        "setup": stage_spreadsheet,
        "assertions": assert_spreadsheet_contrast,
        "shot": {"kind": "editor", "ticks": VIEW_TICKS},
        "gated": True,
        "doc": "README 'What it is' — what AttrViz adds over the spreadsheet",
    },
    {
        # The cascade. Racy by construction (C7b): the sublevel delay cannot go
        # below 0.1s, so the shutter falls either side of the submenu opening.
        # Produced for the docs, never gated.
        "name": "menu_visualize_point",
        "blend": SCOPE_BLEND,
        "window": WIN_STD,
        "prefs": CASCADE_PREFS,
        "setup": select_hero,
        "assertions": assert_attrs_on_active,
        "shot": {"kind": "menu", "menu": "ATTRVIZ_MT_visualize",
                 "cursor": "center", "ticks": CASCADE_TICKS},
        "gated": False,
        "doc": "README 'Visualization axes'",
    },
]


def by_name(name):
    for scen in SCENARIOS:
        if scen["name"] == name:
            return scen
    raise KeyError(f"no scenario {name!r}; have "
                   f"{[s['name'] for s in SCENARIOS]}")
