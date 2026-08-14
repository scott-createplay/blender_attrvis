"""AttrViz GPU overlay bottleneck harness.

Opens a real .blend, creates visualizers, and times cold/warm/scrub paths
with ``attrviz.perf`` spans.

Examples::

  # Default: sample_scene_3 AOV test (if sibling checkout exists)
  blender --background --python-exit-code 1 \\
    --python dev_tasks/001_gpu_overlay/tests/profile_overlay_harness.py

  # Explicit blend + attrs + displays
  blender --background --python-exit-code 1 \\
    --python dev_tasks/001_gpu_overlay/tests/profile_overlay_harness.py -- \\
    --blend /path/to/scene.blend \\
    --attr emission_strength \\
    --displays Markers,Surface,Tags \\
    --max-targets 3 \\
    --warm 5 \\
    --scrub \\
    --json /tmp/attrviz_perf.json

Env: ATTRVIZ_PERF=1 is set by this script.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import bpy

TASK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(TASK))
sys.path.insert(0, REPO)

os.environ["ATTRVIZ_PERF"] = "1"

import attrviz as av  # noqa: E402
from attrviz import gpu_overlay, node_builder, perf  # noqa: E402
from attrviz import tags_draw  # noqa: E402

DEFAULT_BLEND = (
    "/Users/scott.peters/dev/hdr_synthetic_scene_pipeline/"
    "prototypes/pro_city_look_variation/scenes/sample_scene_3/"
    "user_scenes/sample_scene_3_look_seed__aov_test.blend"
)


def _argv_after_dd():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return []


def _parse():
    p = argparse.ArgumentParser(description="AttrViz overlay perf harness")
    p.add_argument("--blend", default=DEFAULT_BLEND)
    p.add_argument("--attr", default="emission_strength",
                   help="Attribute name to visualize")
    p.add_argument("--domain", default="Point")
    p.add_argument(
        "--displays",
        default="Markers,Surface,Tags",
        help="Comma list: Markers,Surface,Arrows,Tags",
    )
    p.add_argument("--style", default="Heat")
    p.add_argument("--max-targets", type=int, default=3,
                   help="Max mesh objects with the attr to viz")
    p.add_argument("--target", default="",
                   help="Exact object name (skips auto-pick)")
    p.add_argument("--warm", type=int, default=5,
                   help="Warm cache refresh iterations after cold")
    p.add_argument("--scrub", action="store_true",
                   help="Scrub Length / Range / Density and time rebuilds")
    p.add_argument("--json", default="",
                   help="Write full perf dict as JSON")
    return p.parse_args(_argv_after_dd())


def _objects_with_attr(attr_name: str):
    rows = []
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.data is None:
            continue
        if attr_name in obj.data.attributes:
            rows.append(obj)
    rows.sort(key=lambda o: len(o.data.vertices), reverse=True)
    return rows


def _viz_mod(obj):
    return av.viz_modifier(obj)


def _force_refresh(obj, display: str):
    md = _viz_mod(obj)
    if md is None:
        return None
    gpu_overlay.invalidate_all()
    return gpu_overlay._refresh_viz(obj, md, display)


def _warm_refresh(obj, display: str):
    md = _viz_mod(obj)
    if md is None:
        return None
    return gpu_overlay._refresh_viz(obj, md, display)


def _run_tags(obj, rounds: int):
    md = _viz_mod(obj)
    if md is None:
        return
    cam = (0.0, -10.0, 2.0)
    for _ in range(rounds):
        # Bypass label cache by invalidating
        tags_draw.invalidate_cache()
        with perf.span("harness.tags_round"):
            tags_draw._collect_tags(
                md, cam,
                cap=tags_draw._int_socket(
                    node_builder.get_input(md, "Tag Cap"), 10000),
                facing_cull=False,
            )


def main():
    args = _parse()
    blend = args.blend
    if not os.path.isfile(blend):
        print(f"FAIL: blend not found: {blend}")
        sys.exit(1)

    perf.enable(True)
    perf.reset()
    perf.set_meta(
        blend=blend,
        attr=args.attr,
        domain=args.domain,
        displays=args.displays,
        max_targets=args.max_targets,
    )

    t_load = time.perf_counter()
    bpy.ops.wm.open_mainfile(filepath=blend)
    load_ms = (time.perf_counter() - t_load) * 1000.0
    perf.add_ms("harness.load_blend", load_ms)

    av.register()
    bpy.context.scene.attrviz_gpu_markers = True

    displays = [d.strip() for d in args.displays.split(",") if d.strip()]
    if args.target:
        targets = [bpy.data.objects.get(args.target)]
        targets = [t for t in targets if t is not None]
    else:
        targets = _objects_with_attr(args.attr)[: max(1, args.max_targets)]

    if not targets:
        print(f"FAIL: no mesh with attribute {args.attr!r}")
        sys.exit(1)

    perf.note("targets", [t.name for t in targets])
    print(f"\nHarness targets ({len(targets)}): "
          f"{', '.join(t.name for t in targets)}")
    print(f"Displays: {displays}\n")

    created = []
    for tgt in targets:
        for display in displays:
            style = args.style
            if display == "Arrows":
                # Prefer Normal if emission isn't vector
                attr = args.attr
                domain = args.domain
                # Arrows need vectors — use Normal intrinsic for harness
                # when attr isn't vector-like.
                a = tgt.data.attributes.get(args.attr)
                if a is None or a.data_type not in (
                        "FLOAT_VECTOR", "FLOAT2"):
                    attr = node_builder.NORMAL_ATTR
                    domain = "Point"
                    style = "RGB"
            else:
                attr = args.attr
                domain = args.domain
            with perf.span(f"harness.add.{display}"):
                viz = av.add_visualizer(
                    bpy.context,
                    target=tgt,
                    attribute=attr,
                    domain=domain,
                    style=style,
                    display=display,
                )
            created.append((viz, display, tgt.name))

    # --- Cold refresh (invalidate + rebuild) ---
    for viz, display, tgt_name in created:
        if display == "Tags":
            with perf.span("harness.cold.Tags"):
                _run_tags(viz, rounds=1)
            continue
        with perf.span(f"harness.cold.{display}"):
            entry = _force_refresh(viz, display)
        n = 0 if entry is None else entry.get("n", 0)
        perf.note(f"cold_n.{tgt_name}.{display}", n)
        print(f"  cold {display:8} @ {tgt_name}: n={n}")

    # --- Warm refresh (should be cache hits for GPU displays) ---
    for viz, display, tgt_name in created:
        if display == "Tags":
            # Tags intentionally re-collect today — measure that cost
            with perf.span("harness.warm.Tags"):
                _run_tags(viz, rounds=args.warm)
            continue
        for i in range(args.warm):
            with perf.span(f"harness.warm.{display}"):
                _warm_refresh(viz, display)

    # --- Scrub scenarios (bust flat cache key) ---
    if args.scrub:
        for viz, display, tgt_name in created:
            md = _viz_mod(viz)
            if md is None:
                continue
            if display == "Arrows":
                with perf.span("harness.scrub.Length"):
                    for length in (0.04, 0.08, 0.12, 0.16, 0.20):
                        node_builder.set_input(md, "Length", length)
                        # key includes length → miss → resample today
                        _warm_refresh(viz, display)
            if display in ("Markers", "Surface"):
                with perf.span("harness.scrub.Range"):
                    node_builder.set_input(md, "Auto Range", False)
                    for lo, hi in ((0.0, 0.5), (0.0, 1.0), (0.0, 2.0),
                                   (0.01, 0.1), (0.0, 0.05)):
                        node_builder.set_input(md, "Range Min", lo)
                        node_builder.set_input(md, "Range Max", hi)
                        _warm_refresh(viz, display)
            if display in ("Markers", "Arrows"):
                with perf.span("harness.scrub.Density"):
                    for dens in (1.0, 0.5, 0.25, 0.1):
                        node_builder.set_input(md, "Density", dens)
                        _warm_refresh(viz, display)

    # Cleanup viz objects so we don't dirty user's file on disk (we don't save)
    report = perf.report()
    data = perf.as_dict()
    if args.json:
        out = os.path.abspath(args.json)
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"Wrote JSON: {out}")

    # Ranked headline for quick paste into POR / chat
    print("\nTop spans by total_ms:")
    for row in data["ranked_by_total_ms"][:15]:
        print(f"  {row['total_ms']:8.1f} ms  n={row['n']:<4}  {row['name']}")

    try:
        av.unregister()
    except Exception as exc:
        print(f"(unregister note: {exc})")

    # Always exit 0 — this is a measurement tool, not a pass/fail suite
    print("\nHarness done.")


if __name__ == "__main__":
    main()
