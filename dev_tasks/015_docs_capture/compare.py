"""Pixel comparison, run inside Blender --background.

Byte equality is the wrong gate. Two runs of the same scenario differ by tens
of pixels of antialiasing noise — 36 of 995,934 for menu_domain_face, 8 of
422,180 for panel_scope_tree. Playwright's own toHaveScreenshot compares with
maxDiffPixels/threshold rather than hashing bytes, for exactly this reason.

Blender is the image library here (bpy.data.images + numpy), so this runs
headless in one launch and keeps the driver dependency-free.

  blender --background --factory-startup --python compare.py -- pairs.json out.json

pairs.json: [{"name":..., "a": path, "b": path}, ...]
out.json:   {name: {"changed": int, "total": int, "frac": float, ...}}
"""
from __future__ import annotations

import json
import sys

import bpy
import numpy as np

THRESHOLD = 0.02  # per-channel delta below this is not a real difference


def load(path):
    img = bpy.data.images.load(path, check_existing=False)
    width, height = img.size
    buf = np.empty(width * height * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return buf.reshape(height, width, 4)[:, :, :3], (width, height)


def compare(a_path, b_path):
    try:
        a, size_a = load(a_path)
        b, size_b = load(b_path)
    except RuntimeError as exc:
        return {"error": str(exc)}
    if size_a != size_b:
        return {"error": f"size mismatch {size_a} vs {size_b}",
                "changed": -1, "total": 0}
    mask = (np.abs(a - b) > THRESHOLD).any(axis=2)
    changed = int(mask.sum())
    total = size_a[0] * size_a[1]
    out = {"changed": changed, "total": total,
           "frac": round(changed / float(total), 6), "size": list(size_a)}
    if changed:
        ys, xs = np.nonzero(mask)
        out["bbox"] = [int(xs.min()), int(ys.min()),
                       int(xs.max()), int(ys.max())]
    return out


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    pairs = json.load(open(argv[0], encoding="utf-8"))
    results = {p["name"]: compare(p["a"], p["b"]) for p in pairs}
    with open(argv[1], "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print(f"[compare] {len(results)} pairs")


main()
