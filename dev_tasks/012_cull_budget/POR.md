# POR: the cull budget bounds the wrong quantity

**Parent / history:** all three items deferred out of
[`../009_empty_sample_crash/POR.md`](../009_empty_sample_crash/POR.md), which
measured the culler in the course of proving it was *not* the cause of that
crash. It is correct. It is also solving a different problem than the one it
claims to.
**Status:** designed, not started. **Nothing here is a bug** — the overlay is
correct today. This is about a control variable that does not match its stated
purpose.
**Northstar:** **bound what actually costs, by what actually crowds.**

AttrViz **0.5.12**. Blender **5.2.0**.

---

## TL;DR

`view_cull_geometric` promises "smooth density falloff" and a draw budget. It
delivers neither, for three independent reasons:

1. The budget is **per visualizer**, so it bounds nothing at scene level.
2. The weighting is by **distance from frame centre**, not by density.
3. The frustum test uses the **sample point**, not the drawn extent.

And because of (1), the weighting in (2) is effectively dead code in ordinary
scenes — it never executes.

---

## Measured, not read

`overlay_kind` imports only `math` and `numpy`, so the culler runs standalone.
Against a synthetic perspective matrix:

| case | in frustum | cap | kept |
|---|---|---|---|
| 1k pts, centered | 940 | 50000 | **940** |
| 200k pts, centered | 185,563 | 50000 | **50,000** |
| 200k pts | 185,563 | 1000 | **1,000** |
| 200k pts | 185,563 | 10 | **10** |
| cloud off to +X | 0 | 50000 | **0** |
| cloud behind camera | 0 | 50000 | **0** |

Over budget it returns exactly the cap, centre-biased, and it can never return
zero — `weight` has a hard floor of `_CULL_FLOOR = 0.05` and `scale =
cap / weight.sum()` normalises the expectation to `cap`:

```
fd [0.00,0.25)  all=  8098  kept=  8098  survival=100.0%
fd [0.25,0.50)  all= 19462  kept= 18079  survival= 92.9%
fd [0.50,0.75)  all= 23253  kept=  9406  survival= 40.5%
fd [0.75,1.00)  all= 21482  kept=  3008  survival= 14.0%
```

The policy works exactly as written. The question is whether what is written is
what is wanted.

---

## Problem 1 — the budget is per visualizer

`cap` is hardcoded to 50000 at `_refresh_viz` and never overridden, and applies
to each visualizer independently. Fifteen watched objects can upload 750,000
instances and nothing anywhere notices.

If the cap exists to bound GPU cost — and 50,000 is clearly a GPU number — then
it is bounding the wrong quantity. Cost is per frame, across the whole pass;
the cap is per visualizer.

**Consequence: the centre-bias is dead code.** `if n_in_view <= cap: return
everything` short-circuits below 50,000 in-frame samples *on a single
visualizer*. In ordinary scenes the weighted-budget block never runs at all,
so problem 2 is currently invisible — and would become visible the moment
problem 1 is fixed.

---

## Problem 2 — centeredness is not density

`frame_dist` is Chebyshev distance from frame centre. The docstring promises
"smooth density falloff". Those are different quantities.

A fully visible object off to one side has **all** of its samples
down-weighted together, because they all share a high `fd`. It goes sparse for
being off-centre, not for being crowded. Orbit, and its marker density
breathes.

Meanwhile a small, dense object dead-centre keeps every sample even when its
markers are overlapping into mush — high screen density, low `fd`, no thinning.

If the goal is a **draw budget**, the honest variable is projected screen
density: samples per pixel, or projected screen area per object. If the goal is
**attention** — keep detail where the user is looking — centeredness is
defensible, but then the docstring should say so and the promise of density
falloff should go.

**This is the decision the POR exists to force.** They are different features:

| Goal | Variable | Behaviour |
|---|---|---|
| Bound GPU cost | screen density / projected area | Dense regions thin; sparse regions never do, wherever they are |
| Direct attention | frame distance (today) | Everything off-centre thins, however sparse |

Picking "cost" is the more defensible default, and it is the one the current
docstring already claims.

---

## Problem 3 — the frustum test uses the sample point

An arrow whose base sits just outside the frame but whose head points inward is
culled entirely, so arrows pop at the frame edge. Markers have a pixel radius
and the same thing applies.

`pad = 0.05` is a constant fudge for a quantity that actually depends on arrow
`Scale`, marker `point_size`, and distance. Five percent of a 4K viewport is a
very different margin from five percent of a small one.

Correct shape: derive the pad from the drawn extent — project the arrow length
(or marker radius) to pixels and pad by that.

---

## A fourth, smaller one found while measuring

`keep_prob = min(1.0, weight * scale)` truncates probability mass above 1
without redistributing it, so when weights are uneven the expected kept count
falls **below** `cap`. The budget is not quite the budget. Minor, but it should
either be corrected by renormalising after the clamp or documented as
approximate.

---

## Open decisions

**D1 — What is the budget for?** Cost or attention. See the table above.
Recommendation: **cost**, matching the existing docstring.

**D2 — What is the global number?** 50,000 was chosen per visualizer. A scene
budget is a different figure and needs measuring on real hardware, not picked.

**D3 — How is a global budget divided?** Equal shares are simple but wrong: an
object filling the screen deserves more than one occupying forty pixels.
Dividing by projected screen area is the obvious candidate, and it composes
with D1 if the variable is density.

**D4 — Does the budget apply before or after per-visualizer Density?** The
`Density` socket already subsamples at L0, view-agnostically. A view-dependent
budget on top means two thinning stages; their interaction should be stated
rather than discovered.

**D5 — Stability.** The per-sample hash is stable across frames, but
`keep_prob` is view-dependent, so samples near the threshold flicker as the
view moves. Today that is invisible (the block never runs). Under a real global
budget it would not be. Hysteresis, or quantising `keep_prob`, may be needed.

---

## Why this is not urgent

Nothing here is a defect. The overlay draws correctly, the crash class from 009
is fixed, and in ordinary scenes the questionable code path does not even
execute. This is worth doing when scene sizes make the per-visualizer budget
bite — and it is worth doing deliberately, because changing the cull changes
what every existing scene looks like.

**Do not bolt this onto another task.** Problems 1 and 2 are coupled: fixing
the budget makes the weighting visible for the first time, so shipping 1
without deciding 2 would change the look of every large scene as a side effect.

---

## Testing

The whole culler is pure numpy and headless-testable — `tests/test_overlay_kinds.py`
already covers cap guarantee, centre bias, edge representation, determinism and
the off-screen case. Extend rather than replace:

- a global budget shared across N visualizers respects the total
- an off-centre but sparse object is **not** thinned (the D1 behaviour change)
- a centred but dense object **is**
- an arrow whose head enters the frame is kept (problem 3)
- expected kept count equals the budget within tolerance (problem 4)

---

## Files

| Path | Why |
|---|---|
| `attrviz/overlay_kind.py:98` | `view_cull_geometric` — the policy |
| `attrviz/overlay_kind.py:53` | `frame_dist` — the control variable in question |
| `attrviz/overlay_kind.py:85` | `_CULL_POWER` / `_CULL_FLOOR` — the weighting constants |
| `attrviz/gpu_overlay.py` | `_refresh_viz(cap=50000)` — the per-visualizer cap |
| `attrviz/gpu_overlay.py` | `_draw_callback_view_impl` — where a global budget would be divided |
| `tests/test_overlay_kinds.py` | existing cull coverage to extend |
