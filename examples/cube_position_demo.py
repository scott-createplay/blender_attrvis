"""The default-cube gesture, headless: visualize `position` as
surface RGB (what RMB -> Visualize Attribute -> position does).

Run:
  blender --background --factory-startup --python-exit-code 1 \
      --python examples/cube_position_demo.py
Outputs: renders/cube_position.png beside this repo.
"""
import os
import sys
from math import radians

import bpy

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import attrviz as av  # noqa: E402

for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

bpy.ops.mesh.primitive_cube_add(size=2.0)
cube = bpy.context.active_object

# exactly what the RMB menu does: domain submenu + auto-pick
by, has_faces = av.attributes_by_domain(cube)
dtype = next(t for n, t in by["Point"] if n == "position")
style, display = av.auto_pick("Point", dtype, has_faces)
viz = av.add_visualizer(bpy.context, target=cube,
                        attribute="position", domain="Point",
                        style=style, display=display)
viz.hide_render = False
print(f"[attrviz] auto-picked style={style} display={display}")

sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", 'SUN'))
sun.data.energy = 3.0
sun.rotation_euler = (radians(55), radians(-10), radians(35))
bpy.context.collection.objects.link(sun)
cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
cam.location = (4.2, -4.6, 3.2)
cam.rotation_euler = (radians(60), 0.0, radians(42))
bpy.context.collection.objects.link(cam)
bpy.context.scene.camera = cam

scene = bpy.context.scene
for eng in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
    try:
        scene.render.engine = eng
        break
    except Exception:
        continue
scene.render.resolution_x = 1100
scene.render.resolution_y = 900

os.makedirs(os.path.join(REPO, "renders"), exist_ok=True)
scene.render.filepath = os.path.join(REPO, "renders",
                                     "cube_position.png")
bpy.ops.render.render(write_still=True)
print("[attrviz] rendered renders/cube_position.png")
