# Explorations

Design work that is **settled enough to remember, not scheduled enough to be a POR**.

A `dev_tasks/NNN_*/POR.md` is a plan of record: someone is going to build it. This file
is for ideas that have been reasoned through — often with measurements — but have no
owner or phase yet. Each entry should be complete enough that picking it up later needs
no memory of the conversation that produced it.

When an entry graduates, move it into a POR and leave a one-line pointer here.

---

## Constant / varying readout

**Status:** design settled, not built. One open question (colour lever, below).
**Related:** [`../dev_tasks/007_instance_domain/POR.md`](../dev_tasks/007_instance_domain/POR.md)
— "What survives" — this is that item, expanded.

### What it is

When every sampled value of an attribute is identical, say so, in one line.

It is **not** an optimisation. It is a *negative result delivered cheaply*. A visualizer's
job is to reveal variation; when there is none, a picture is the wrong output. You get a
field of identically-coloured dots, which is indistinguishable from "wrong attribute",
"broken visualizer", or "haven't orbited to the interesting side yet" — and the user
spends real time proving a negative by hand.

The whole payload is: **"don't bother looking deeper, all the values are the same."**

### Why the viewport cannot tell you

Measured on a constant FLOAT field with Heat + Auto Range:

```
values: n=49  ptp=0.0  all-equal=True
colors: min=[0.05 0.12 0.90 1.0]  max=[0.05 0.12 0.90 1.0]   NaN: False
```

A constant field maps to the **low end of the ramp** — a uniformly blue field, visually
identical to "all values happen to sit at the minimum of a varying range". Nothing
crashes and nothing is NaN; it is simply uninformative, and the two cases are
indistinguishable by eye. Only a readout separates them.

### The primitive: exact, no tolerance

`np.ptp(vals) == 0`, or `(v == v[0]).all()`. **No epsilon, no rounding, anywhere in the
pipeline.**

The visualizer is a way of *looking at* the data, but the data is what drives the scene.
A 1e-7 difference invisible under any colour ramp can still be driving geometry, a
driver, or a render. The errors are not symmetric:

| Failure | Cost |
|---|---|
| Says "varies" when variation is tiny | You look, find something small, mildly annoyed |
| Says "constant" when it isn't | **You stop looking** and miss data that is driving your scene |

Exact equality fails in the safe direction by construction. NaN falls out correctly too:
`ptp` with NaN is NaN, which is not zero, so it reports "varies" rather than claiming
uniformity over data it cannot compare.

### Cost — and do not reach for `set()`

Benchmarked on float32 arrays with 33 distinct values (the promoted-instance shape):

| n | `set()` | `np.unique` | `np.ptp` | `(v == v[0]).all()` |
|---:|---:|---:|---:|---:|
| 44,616 | 1.9 ms | 0.06 ms | 0.01 ms | 0.00 ms |
| 190,344 | 8.5 ms | 0.20 ms | 0.02 ms | 0.01 ms |
| 785,928 | **36.8 ms** | 1.13 ms | 0.09 ms | 0.06 ms |

Python's `set()` boxes every element — 36.8 ms at 786k, **more than twice the entire
sample read**. The binary "are they all the same" question does not need dedupe at all;
it needs one O(N) pass. `np.unique` (a sort) is only required if a *distinct count* is
being displayed, so compute it on demand rather than every draw.

### Where it is computed

In `sample_visualizer_targets`, **before `concat_density_cap`**. The array is already in
cache, so it rides along on data that is hot.

Pre-cull is not a detail — it is the whole point. Computed after the density cull and
cap, the check would be certifying *the drawn subset*, which is exactly the untrustworthy
thing it exists to replace. Markers goes through the density cull, the 50k cap and
`view_cull_geometric`'s frame-centre budget; Tags has Tag Cap. Uniformity in a sample
proves nothing about the remainder.

**The panel must never sample.** Panel draws fire constantly. The result is stashed on
the existing `_sample_caches` entry (which already carries `positions`, `values`,
`dtype`, `n`) and the panel *reads* it, showing nothing when absent. Consequence: the
badge only appears once the overlay has drawn at least once, and is absent on the GN
(GPU-overlay-off) path. That is acceptable; a UI redraw must never trigger a 15 ms read.

### UI: the badge

**Both states get a badge**, not just the constant one. With two explicit states, an
empty slot unambiguously means "not yet sampled" — with an exception-only badge, empty
would mean either "varying" or "not sampled", which reintroduces the guessing this
feature removes.

**Icon only in the header; numbers in the body.**

```
▸ ☑ ⌐‾  height  ·  Instance  ·  Markers        ✕     ← constant
▸ ☑  ╱   wear  ·  Point  ·  Surface            ✕     ← varying

--- expanded body, first line ---
  constant:  All 1,848 values are 0.500 — no variation to find.
  varying:   0.27 → 0.75 across 1,848 samples
```

- The header title (`attr · domain · type`) is the thing you scan by, and the N-panel is
  narrow. A range in the header truncates the title; an icon costs no width.
- **A second header row is not available.** `layout.panel_prop` headers are a single
  fixed-height row; nesting a column of labels will clip rather than stack. Not
  GUI-verified, but not worth designing around — POR 001 already carries scar tissue from
  Blender's layout nesting rules.
- **Use `IPO_CONSTANT` and `IPO_LINEAR`.** Blender's UI font does not reliably render
  colour emoji (they can appear as boxes). Those two native icons are literally a flat
  step and a ramp — the same read as an emoji, guaranteed at any UI scale.
- The body line sits in the same slot in both states, so the eye lands in the same place.

### Per-visualizer behaviour

| Visualizer | Panel header | Viewport |
|---|---|---|
| **Markers** | badge | **unchanged** — colour is degenerate, but position still says where the elements are |
| **Surface** | badge | **unchanged** — it draws every triangle, so a flat-coloured object already *is* the complete answer |
| **Arrows** | badge | **unchanged** — constant means identical direction *and* length; parallel arrows are self-evident and their positions still matter |
| **Tags** | badge | **collapses** — see below |

The badge applies to all four even though only Tags changes its drawing. *Where the
display changes* and *where the signal is useful* are different questions, and a badge
appearing on three of four types is a rule people have to remember.

### Tags is genuinely different

The rule everywhere else is "the badge reports, the viewport never changes", because a
mark's position is still data even when its colour is degenerate. **That does not hold
for text.** N identical strings convey nothing the position channel was not already
conveying better, and at density they are unreadable regardless. So Tags collapses.

**But a lone tag is ambiguous**, and this is the part that must not be skipped. On screen
it could mean any of:

1. the value is constant and we collapsed it
2. there is genuinely only one element
3. Tag Cap culled everything else

So a collapsed tag must be visually unmistakable as a **summary, not a sample**. Three
levers, and more than one should be used:

- **Position** — draw at the watch-set bounds centre, not at an element. A constant is
  not attached to any particular vertex, so putting it on one is a small lie, and an
  off-element position is the strongest available signal that this is not per-element ink.
- **Form** — self-describing text, e.g. `≡ 60.76  (1,848 samples)`. The `≡` and the count
  together say "everywhere, this many" with no legend.
- **Colour** — ⚠️ `Tag Color` is a user socket. Overriding it makes their setting silently
  not apply. Prefer desaturating or outlining *their* colour over substituting one.

### Collapse granularity — global vs per-object

"Constant across 50 objects" and "constant *within each* of 50 objects" are different
facts, and a single global tag is wrong for the second. The sampler concatenates per
watched object, so the chunk boundaries are already known:

| Data | Collapse to |
|---|---|
| constant across the whole sampled set | **one** tag |
| constant within each object, differing between objects | **one tag per object** |
| otherwise | normal per-element tags |

This is the case a dense scene is really about: 50 buildings each with a flat `height`
should read as 50 legible labels — not 50,000 illegible ones, and not one misleading
summary.

### Open question

**May a collapsed tag modify the user's `Tag Color`, or must it express itself purely
through position and form?** Everything else here is settled.

### Deliberately out of scope

Recovering *scope* (was this a per-instance attribute before Realize flattened it?) by
value inference, static graph analysis, or a sidecar metadata cache. All three were
explored, measured, and rejected — see POR 007, "Rejected: recovering scope after
Realize". This readout describes **what is in front of you**, and claims nothing about
provenance. That is why it survives every lifecycle question the cache failed: it is
derived fresh and thrown away.

---

## Parked elsewhere

Recorded in POR 007 rather than duplicated here:

- **Graph instrumentation / tap helper** — mid-graph values are unaddressed, not missing;
  wiring any field into a `Store Named Attribute` exposes it to AttrViz with zero code
  changes. Includes the Viewer-node passthrough lead.
- **Datablock "detail" attributes** — ID properties work on Object / Mesh / Collection /
  Scene, but are not attributes; reading them changes AttrViz from an attribute
  visualizer into a data visualizer. Deferred on product identity, not capability.
- **P4 unpack mode** — reconstructing realized geometry in numpy so mesh domains work on
  un-realized instances, without adding a Realize node to the user's graph.
