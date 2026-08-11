"""Register the GPU overlay probe and enable it on the active mesh.

Use with a GUI Blender session (GPU draw is unavailable in --background):

  blender dev_tasks/001_gpu_overlay/probe/probe_fixture.blend \\
    --python dev_tasks/001_gpu_overlay/probe/enable_in_gui.py

Then: Solid viewport → Sidebar (N) → Probe. Alt+Shift+P toggles.
Save a screenshot to ../references/probe_phase2_points.png for Gate A.
"""
from __future__ import annotations

import os
import sys

TASK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK not in sys.path:
    sys.path.insert(0, TASK)

import bpy
import importlib
import probe

importlib.reload(probe)
# reload submodules so iterative edits stick
for name in ("probe.sample", "probe.color_map", "probe.overlay_probe"):
    if name in sys.modules:
        importlib.reload(sys.modules[name])

try:
    probe.unregister()
except Exception:
    pass
probe.register()

prefs = bpy.context.scene.probe_gpu_overlay
prefs.attribute = "heat"
prefs.domain = 'POINT'
obj = bpy.context.active_object
if obj is None:
    obj = bpy.data.objects.get("Probe Grid")
if obj is not None:
    prefs.target = obj
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
prefs.enabled = True

print("[probe] registered + enabled on", getattr(prefs.target, "name", None))
print("[probe] Sidebar → Probe tab; Alt+Shift+P to toggle")
print("[probe] Save screenshot → references/probe_phase2_points.png")
