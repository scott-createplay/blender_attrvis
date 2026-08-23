"""Render a visual diff of two captures: unchanged dimmed, changed in red."""
import os, sys, bpy, numpy as np
a_path, b_path, out_path = sys.argv[-3:]
def load(p):
    i = bpy.data.images.load(p, check_existing=False)
    w,h = i.size; b = np.empty(w*h*4, dtype=np.float32); i.pixels.foreach_get(b)
    bpy.data.images.remove(i); return b.reshape(h,w,4), (w,h)
a,sa = load(a_path); b,sb = load(b_path)
assert sa==sb, (sa,sb)
m = (np.abs(a[:,:,:3]-b[:,:,:3])>0.02).any(axis=2)
out = a.copy(); out[:,:,:3] *= 0.25
out[m] = [1.0,0.0,0.0,1.0]
img = bpy.data.images.new("d", width=sa[0], height=sa[1], alpha=True)
img.pixels.foreach_set(out.reshape(-1))
img.filepath_raw = out_path; img.file_format='PNG'; img.save()
print(f"changed={int(m.sum())} of {sa[0]*sa[1]} -> {out_path}")
