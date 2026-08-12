"""Spike: Blender 5.0 GPU custom shader + draw_instanced availability."""
from __future__ import annotations

import inspect
import sys

import bpy
import gpu
from gpu_extras.batch import batch_for_shader


def main():
    print("=== gpu.types ===")
    print([a for a in dir(gpu.types) if not a.startswith("_")])
    print("=== gpu.shader ===")
    print([a for a in dir(gpu.shader) if not a.startswith("_")])

    for name in (
        "GPUShaderCreateInfo",
        "GPUStageInterfaceInfo",
        "GPUVertFormat",
        "GPUBatch",
        "GPUShader",
        "GPUVertBuf",
        "GPUIndexBuf",
    ):
        print(f"has {name}:", hasattr(gpu.types, name))

    b = gpu.types.GPUBatch
    print("GPUBatch draw-ish:", [m for m in dir(b) if "draw" in m.lower() or "inst" in m.lower()])

    try:
        info = gpu.types.GPUShaderCreateInfo()
        print("CreateInfo OK methods:", [m for m in dir(info) if not m.startswith("_")])
    except Exception as e:
        print("CreateInfo fail:", type(e).__name__, e)

    print("from_builtin sig:", inspect.signature(gpu.shader.from_builtin))
    try:
        print("GPUShader init:", inspect.signature(gpu.types.GPUShader.__init__))
    except Exception as e:
        print("GPUShader sig fail:", e)

    for attr in ("create_from_info", "from_builtin", "unbind"):
        fn = getattr(gpu.shader, attr, None)
        if fn:
            print(f"{attr} doc:", (fn.__doc__ or "").strip()[:400])

    # Try minimal CreateInfo shader
    try:
        info = gpu.types.GPUShaderCreateInfo()
        info.vertex_in(0, "VEC3", "pos")
        info.push_constant("MAT4", "ModelViewProjectionMatrix")
        info.push_constant("VEC4", "color")
        info.fragment_out(0, "VEC4", "fragColor")
        info.vertex_source(
            "void main() {\n"
            "  gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);\n"
            "}\n"
        )
        info.fragment_source(
            "void main() {\n"
            "  fragColor = color;\n"
            "}\n"
        )
        sh = gpu.shader.create_from_info(info)
        print("create_from_info OK:", sh)
        del info
    except Exception as e:
        print("create_from_info fail:", type(e).__name__, e)

    # Try string GPUShader (legacy)
    try:
        vert = """
in vec3 pos;
uniform mat4 ModelViewProjectionMatrix;
void main() {
  gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);
}
"""
        frag = """
uniform vec4 color;
out vec4 FragColor;
void main() {
  FragColor = color;
}
"""
        sh2 = gpu.types.GPUShader(vert, frag)
        print("GPUShader(string) OK:", sh2)
    except Exception as e:
        print("GPUShader(string) fail:", type(e).__name__, e)

    # draw_instanced existence
    try:
        sh = gpu.shader.from_builtin("UNIFORM_COLOR")
        coords = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        batch = batch_for_shader(sh, "TRIS", {"pos": coords})
        print("batch type", type(batch))
        print("has draw_instanced", hasattr(batch, "draw_instanced"))
        if hasattr(batch, "draw_instanced"):
            print("draw_instanced sig", inspect.signature(batch.draw_instanced))
            print("draw_instanced doc", (batch.draw_instanced.__doc__ or "")[:500])
        print("has draw", hasattr(batch, "draw"))
        print("draw sig", inspect.signature(batch.draw))
    except Exception as e:
        print("batch probe fail:", type(e).__name__, e)

    # Instance attribute APIs
    for name in ("attr_add", "inst_attr_add", "program_use"):
        print("GPUBatch", name, hasattr(gpu.types.GPUBatch, name))

    print("SPIKE_DONE")


if __name__ == "__main__":
    main()
