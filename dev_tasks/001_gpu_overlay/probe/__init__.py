"""Standalone GPU overlay probe (Stage A).

Load in Blender (GUI):
  Preferences → Add-ons → Install → select this folder's parent zip,
  or run from Text Editor / console:

    import sys
    sys.path.insert(0, "/path/to/dev_tasks/001_gpu_overlay")
    import probe
    probe.register()

See README.md for interactive validation steps.
"""
bl_info = {
    "name": "GPU Overlay Probe (AttrViz task 001)",
    "author": "AttrViz",
    "version": (0, 1, 0),
    "blender": (5, 0, 0),
    "location": "View3D → Sidebar → Probe",
    "description": (
        "Standalone probe: sample evaluated mesh attrs and draw unlit "
        "false-color points in Solid mode (no materials / AttrViz)."
    ),
    "category": "3D View",
    "doc_url": "",
    "tracker_url": "",
}

from . import overlay_probe


def register():
    overlay_probe.register()


def unregister():
    overlay_probe.unregister()


# Re-exports for tests / scripts
from .sample import buffer_stats, sample_evaluated  # noqa: E402,F401
from .build_fixture import author_attributes, build as build_fixture  # noqa: E402,F401
