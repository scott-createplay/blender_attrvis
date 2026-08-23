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
MENU_TICKS = {"warmup": 14, "open": 15, "nudges": (17, 19, 21, 23), "shot": 31}
# probe_menu's plan — earlier shutter, no nudges, and NO preference changes.
CASCADE_TICKS = {"warmup": 12, "open": 13, "nudges": (), "shot": 27}
PANEL_TICKS = {"warmup": 16, "reveal": 17, "shot": 27}
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
HERO_HIDE = ("Torus_Flow", "Grid_Plates", "Cube_Bare", "Instanced_Cloud")
ARROWS_HIDE = ("Grid_Plates", "Instanced_Cloud")

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
    so ATTRVIZ_MT_visualize.poll passes and the menu lists real attributes."""
    return _make_active("Suzanne_Measured")


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
    _viz("VIZ_curv_surface").attrviz_enabled = True
    _viz("VIZ_grad_arrows").attrviz_enabled = True
    _viz("VIZ_plate_random").attrviz_enabled = False
    out = {"enabled": ["VIZ_curv_surface", "VIZ_grad_arrows"]}
    out.update(_hide(HERO_HIDE))
    return out


def stage_arrows_only(ctx):
    """Arrows alone. The surface is their own background, so proving arrow ink
    exists means removing the surface — otherwise a Heat-only frame would
    satisfy any ink count."""
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    bpy.context.view_layer.objects.active = None
    _viz("VIZ_curv_surface").attrviz_enabled = False
    _viz("VIZ_grad_arrows").attrviz_enabled = True
    _viz("VIZ_plate_random").attrviz_enabled = False
    # Cube_Bare stays visible on purpose: it carries no grad, and the point of
    # this shot is that a non-carrier is left untouched rather than hidden.
    out = {"enabled": ["VIZ_grad_arrows"]}
    out.update(_hide(ARROWS_HIDE))
    return out


def assert_enabled_only(names):
    def check(ctx):
        on = [o.name for o in bpy.data.objects
              if getattr(o, "attrviz_enabled", False)
              and o.name.startswith("VIZ_")]
        if sorted(on) != sorted(names):
            raise AssertionError(f"enabled visualizers {on}, expected {names}")
        return {"enabled_asserted": on}
    return check


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


def assert_two_scopes(ctx):
    import attrviz as av
    groups = av.visualizers_by_scope(bpy.context.scene)
    items = groups.items() if hasattr(groups, "items") else groups
    named = [[getattr(k, "name", str(k)), len(v)] for k, v in items]
    if len(named) != 3:
        raise AssertionError(f"expected 3 scope groups, got {named}")
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
def _menu(name, menu_id, gated=True):
    return {
        "name": name,
        "blend": SCOPE_BLEND,
        "window": WIN_STD,
        "prefs": MENU_PREFS,
        "setup": select_hero,
        "assertions": assert_attrs_on_active,
        "shot": {"kind": "menu", "menu": menu_id, "cursor": "third",
                 "ticks": MENU_TICKS},
        "gated": gated,
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
                 "min_ink_px": 20000},
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
        "assertions": assert_enabled_only(["VIZ_grad_arrows"]),
        "shot": {"kind": "viewport", "crop": "WINDOW", "view": HERO_VIEW,
                 "overlays": CLEAN_OVERLAYS, "ticks": VIEW_TICKS,
                 "min_ink_px": 2000},
        "gated": True,
        "doc": "README 'Visualization axes' — Arrows",
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
