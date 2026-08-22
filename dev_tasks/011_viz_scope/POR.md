# POR: per-visualizer scope — many collections, not one

**Parent / history:** deferred out of
[`../010_mute_scope/POR.md`](../010_mute_scope/POR.md), which fixed *automatic*
drawability but left no way to say "visualize `K` on these meshes but not that
one".
**Status:** **Phases 1-5b implemented and validated** (2026-08-21). One interactive spike outstanding, non-blocking -- see below.
**Northstar:** **a visualizer watches a collection.** `attrvis` is the default
bucket, not a global override and not a root that everything inherits from.

AttrViz **0.5.12**. Blender **5.2.0**.

---

## TL;DR

This is not a feature to build. Every visualizer already carries `Target ∪
Scope` sockets, `Scope` is already a Collection, and
`add_visualizer_from_selection` already sets `scope = attrvis`. The work is
**removing a global override that shadows data already on the modifier**, then
putting a UI on it.

`gpu_sample.watch_meshes_for_visualizer`:

```python
coll = scene_watch_collection()          # bpy.data.collections.get("attrvis")
if coll is not None:
    return iter_watch_meshes(None, coll) # <- ignores md entirely
```

Its own docstring: "it is the watch set for every visualizer."

---

## The payoff

What is impossible today: **the same attribute with two appearances.** `K` on
the torus with auto-range, `K` on the sphere with fixed −0.5..0.5, both visible
at once. Today they fight over one global watch set.

---

## Ratified design decisions

### D1 — The mapping is 1 visualizer → 1 scope

A visualizer is a *(what, how, where)* triple: attribute + domain; display +
style + range + ramp; scope. The "how" lives on the visualizer, so:

| Want | Cost |
|---|---|
| Same attribute, same look, two collections | **One** visualizer, scoped to a collection containing both |
| Same attribute, different look | **Two** visualizers — the range *is* the visualizer |

You never need two visualizers merely to span two collections.

**Rejected: object-side mapping.** Storing "which visualizers apply" on each
object is the same bipartite graph stored at the worse end — invisible custom
properties, no bulk edit, no drag-drop, no nesting. Collections are Blender's
grouping primitive and supply the management UI for free.

### D2 — The default topology is flat; `attrvis` is a peer, not a root

The question is not "should we nest" but **where the root of the recursion
sits**. Two topologies:

```
A. rooted                    B. flat  (ratified)

attrvis                      attrvis            <- the default bucket
    attrvis_custom_1         attrvis_custom_1
    attrvis_custom_2         attrvis_custom_2
```

In **A**, `attrvis` inherits everything for free and the children are
specialisations. Splitting objects out does not actually split them: a
visualizer scoped to `attrvis` still covers them. The user has to hold the
hierarchy in their head to predict coverage.

In **B**, the collections are peers. Nothing inherits. Moving an object out of
`attrvis` genuinely removes it from `attrvis`'s coverage. **The user never has
to think about nesting at all**, which is the property we are buying.

**Decision: AttrViz always creates siblings under
`scene.collection.children`.** Never a child of the active scope.

**What this does to recursion.** `iter_watch_meshes` keeps recursing — that is
today's tested behaviour (`nested collection meshes included`) and removing it
would change how existing files sample. But under a flat default topology the
recursion is **dormant**: nothing is nested, so it never fires. It exists for
the user who deliberately builds topology A in the outliner, at which point
inheritance is what they asked for.

So there is no "Include children" toggle and no behaviour change. Explicitness
comes from the structure we create, and topology A stays reachable by hand for
anyone who wants a root that covers everything.

Because recursion remains available, the panel must still make inheritance
**visible** when it exists: show `attrvis_custom_1 ⊂ attrvis`, and report
*effective* object counts including inherited ones. A panel number that
disagrees with what is drawn is the same class of bug as 010.

### D2a — `attrvis` stops meaning "everything AttrViz watches"

A consequence of D2 worth stating on its own, because it changes the mental
model and the UI copy.

Today `attrvis` **is** the universe: one collection, everything in it, and the
readout `attrvis  5 meshes · ...` correctly means "AttrViz watches 5 meshes".
After 011, `attrvis` is just the **default bucket** — the collection new
objects land in when the user has not said otherwise. Objects moved out are
genuinely gone from it.

That readout therefore becomes a lie the moment anyone splits a scope. It must
either describe the *active* collection (D3) or become a union across all
scopes. Those are different numbers and the panel has to be honest about which
one it is showing.

**`attrvis` is created lazily.** It does not need to exist at startup. The
first gesture that needs a default (`Add objects`, `Visualize Attribute`)
creates it and makes it active, which is what `_ensure_watch_collection`
already does. A file with no `attrvis` is a legal state, not an error.

### D3 — One active collection drives every new action

A scene-level pointer, `scene.attrviz_active_scope`, shown as a dropdown where
the coverage readout is now. It is the single answer to four questions:

1. Where `Edit → Add objects` / `Remove objects` put the selection
2. What `Scope` a newly created visualizer defaults to
3. What the per-collection coverage readout highlights
4. What `New collection from selection` makes active next

It governs **new actions only** — it never retroactively repoints an existing
visualizer, and per D9 it is **not** a view filter: every collection is always
listed, whether active or not. Active is indicated by selection in the panel
tree; clicking a collection row makes it active and changes nothing on screen.

### D4 — Collections are ADDITIVE, never exclusive

**Reversed after in-app use.** The original decision was "migrate means move":
`New collection from selection` unlinked objects from the active scope on the
grounds that splitting out should actually split. First real use showed that is
wrong.

Putting an object in a second scope must not take it out of the first. An
object legitimately belongs to several scopes when they visualize different
attributes -- `K` on one, `flow` on another, same mesh -- and that is the
common case, not the exception. Exclusivity also silently emptied the original
collection, leaving the visualizers scoped to it drawing nothing.

**Decision: adding is additive.** `New collection from selection` creates a
sibling and *links* the selection into it. Nothing is ever removed implicitly.

The subtractive half stays available and explicit: `Remove objects from
<scope>`. Two composable primitives -- Add and Remove -- rather than a third
that bundles both. `move_to_scope()` was deleted rather than left unused.

Consequence, accepted deliberately: a visualizer scoped to the original
collection keeps covering an object added elsewhere. If that is not wanted,
Remove says so explicitly.

**Labels must state which is which.** The reversal surfaced because "Add
objects" and "New collection from selection" gave no clue that one linked and
the other moved. The Edit menu now names its destination -- "Add objects to
attrvis_other", "Remove objects from attrvis_other" -- so the active scope is
never guessed.

### D5 — Progressive disclosure

Default: everything lands in `attrvis`, exactly as today. `attrvis` is simply
whatever the active collection resolves to when the user has not chosen one --
created on first use per D2a, not a special case in the code. Most users never
see a collection picker. Splitting out is an explicit act.

### D6 — An empty scope draws nothing

Never falls back to `attrvis`. An explicitly emptied group is a user statement.
Matches the existing instinct in `empty attrvis suppresses per-viz Scope`.

### D7 — ~~Linked (library) objects: warn, still draw~~ **WITHDRAWN**

**The premise was wrong, and discovery proved it.** This decision assumed
`display_type` is read-only on library data, so the mute would silently fail
and the original would draw solid under the overlay.

Spike **S8**: the write succeeds. `display_type` is a lib-exception property --
`before='TEXTURED' after='BOUNDS'`, no exception raised, on an object whose
`library` is not None.

Spike **S8b**: the `_MUTE_PROP` custom ID property that `_mute_target_solid`
stashes the previous value in is also writable *and* deletable on linked data.
So the whole mute/restore round trip works on linked objects.

Reload is self-healing too: if the property does not persist back to the
library, `_on_load_post` rebuilds `_muted_ptrs` from whatever carries
`_MUTE_PROP`, and `_sync_surface_target_mute` re-mutes from scratch. Nothing
stale, nothing stuck.

**Consequence: Phase 6 is deleted.** No warning UI, no detection code, no
special case -- one decision and one implementation phase removed by a
ninety-second probe.

### D8 — Scopes are discovered by use, not by name

A scope is just a collection. There is no `attrvis_` prefix rule, and scoping a
visualizer to an existing collection like `Buildings` is legal.

The active-collection dropdown is therefore populated by **usage**: `attrvis`,
plus every collection currently referenced by some visualizer's `Scope`, plus
`New collection from selection`. Discovery by usage rather than by naming
convention keeps the list short and truthful, and avoids inventing a rule the
data model does not have.

`New collection from selection` may still *suggest* an `attrvis_` name. A
suggestion, never a constraint.

### D9 — The panel is a collection tree, and collections toggle

**Superseded an earlier draft** that filtered the panel to a single active
collection. That was wrong: a filter that hides visualizers which are still
drawing produces ink on screen with no control for it -- the 009/010 confusion
running backwards.

The fix is not to make the filter presentational. It is to **stop filtering**
and show every collection as its own group in the panel, each with its own
enable toggle:

```
GPU Overlay   [Solid OK]

v  [x] attrvis                    3 meshes
       [x] Normal  ·  Point  ·  Arrows
       [x] K       ·  Point  ·  Surface
v  [x] attrvis_curvature          2 meshes
       [x] grad_z  ·  Point  ·  Surface
       [ ] lap_z   ·  Point  ·  Surface
>  [ ] Buildings                 12 meshes
```

Nothing is hidden, so nothing can draw without a visible row. Groups collapse,
so the panel still scales. And the user gets a capability the flat list never
had: **disable a whole collection of visualizers at once, or enable three at
the same time.**

**Selecting is presentational; checking is functional.** The distinction the
superseded draft got wrong:

- Making a collection **active** (clicking its row) only sets the target for
  new actions -- D3. It changes nothing on screen.
- **Checking** its box enables or disables every visualizer scoped to it. That
  is deliberate, explicit, and visible -- not a side effect of navigation.

**Collection enable ANDs with per-viz enable.** A visualizer draws iff
`viz.attrviz_enabled and scope_enabled(viz.Scope)`. Collection state must be
stored separately -- a `BoolProperty` registered on `bpy.types.Collection` --
and must **not** write `hide_viewport` on each visualizer, or toggling a
collection off and on would flatten the individual checkboxes the user set.

Do not reuse Blender's own `Collection.hide_viewport` or the view-layer
`exclude` flag: those hide the *watched objects*, which is a different thing
from disabling the *visualizers scoped to them*.

**Collection enable must feed the mute path.** `_active_watch_targets` skips
`viz.hide_viewport` today and must equally skip collection-disabled
visualizers. Miss this and a disabled collection leaves its objects muted with
nothing drawn -- **exactly the 010 bug, reintroduced.** This is the single
highest-risk detail in D9.

**What is left of nesting.** With the panel supplying grouping, bulk enable and
collapse, nesting loses its organisational job entirely. It retains exactly one
purpose: letting **one** visualizer cover **several** collections (D1). That is
a genuine capability -- a Scope socket holds one pointer, and GN sockets do not
do lists -- but it is now an advanced escape hatch rather than a structure
anyone needs to reason about. D2's flat default stands, and the user was right
that under this model there is otherwise no reason to nest.

**Every visualizer must stay reachable.** D8 populates the group list from
usage, so every collection referenced by some `Scope` gets a group and every
visualizer appears under exactly one. That invariant breaks in one case: a
visualizer whose `Scope` is unset belongs to no group and becomes
unmanageable -- present, drawing, with no row anywhere. **A visualizer with no
`Scope` is listed under `attrvis`** and flagged, so it can always be repointed.

Spike **S1** removed the other half of this worry: a GN Collection socket
**auto-nulls** when its collection is deleted, so there is no dangling pointer
to detect. "Dangling" and "unset" are the same state.

### D10 — Blender UI mechanics available for the tree (verified on 5.2)

Probed against Blender 5.2.0, not recalled:

| Mechanism | Status |
|---|---|
| `UILayout.panel_prop(data, prop)` | **Yes.** RNA doc: *"should be used when multiple instances of the same panel can exist. For example one for every item in a collection property or list."* Exactly the per-collection group case. |
| `UILayout.operator(..., depress=True)` | **Yes.** `depress` is a real parameter -- this is how a row is drawn as selected. |
| `BoolProperty` registered on `bpy.types.Collection` | **Yes.** Verified default/set/get round trip. D9's collection-enable flag is viable. |
| `PointerProperty(type=Collection)` on Scene | **Yes**, and it **auto-nulls when the collection is deleted** -- verified. |
| `template_list` | Yes, but **flat only**. No hierarchy. |

**There is no ambient panel selection in Blender.** No "focused panel", no
"current row". Every notion of active is a property you own and draw yourself.
So "the collection you have selected in the panel" is implementable, but it
means: a `PointerProperty` on the Scene, a click-to-activate operator per
collection header, and `depress=(coll is active)` for the highlight. It looks
native; it is not free.

**The auto-null finding simplifies a corner case.** Because Blender nulls an ID
pointer when its target is deleted, "active collection deleted" is just
`is None`. **Confirmed for GN modifier Collection sockets too** by spike S1,
so D9's "dangling `Scope`" case collapses into "unset `Scope`" and the Phase 1
backfill covers both. There is no dangling-pointer state to detect.

**The layout-panel width constraint is real and already respected.** RNA doc:
*"can only be used when the panel has the full width of the panel region
available to it. So it can't be used in e.g. in a box or columns."* This is the
constraint the existing code notes at `panel_prop must not sit inside
column/box/split`.

**Open question -- needs a spike, cannot be tested headless.** Can a
`panel_prop` (per visualizer) nest inside the body of another `panel_prop` (per
collection)? A layout-panel body is full width, so it is not obviously
forbidden, but the docs neither promise nor deny it and panel drawing needs a
real UI region. **Ten-minute spike in an interactive session before committing
to the tree layout.**

Fallback if nesting is refused: collection headers become plain full-width rows
carrying the checkbox, count and activate button, with the existing per-viz
`panel_prop` rows staying at root level beneath them. Visually a shade less
crisp, functionally identical.

**Rejected: `template_list`.** It is the only widget with true selection chrome,
but it is flat, requires a `CollectionProperty` mirror kept in sync with the
real collections and visualizers -- a classic source of drift bugs -- and would
push per-visualizer settings out of expand-in-place into a details pane below
the list. Too much UX churn for highlight styling.

---

## Corner cases

**Already correct, no work.** Same object in two scopes (mute is a union,
deduped by pointer). Nested collections (`iter_watch_meshes` recurses).
Removing an object from a scope (restore-the-complement, tested). Deleting a
visualizer whose scope is shared with another.

**Must be handled.**

| Case | Handling |
|---|---|
| Visualizer with unset `Scope` | Silently draws nothing after un-shadowing. **Version-bumped migration backfills `attrvis`.** The single biggest risk in this POR. |
| Viz carrier dragged into a scope | Self-visualization. `is_watchable` checks only `obj.type`; carriers are filtered at *selection* time by `_watch_candidates`, which a hand-managed collection bypasses. Move the filter into `is_watchable`. |
| Objects in a collection not linked to this scene | Collections are scene-independent data; such objects have no evaluated state in this view layer. Filter to the view layer. |
| Active collection deleted | Fall back to `attrvis`, creating it if absent (D2a). Never leave the pointer dangling. |
| No `attrvis` in the file | Legal (D2a). The first gesture needing a default creates it and makes it active. |
| Everything moved out of `attrvis` | `attrvis` is empty; visualizers still scoped to it draw nothing (D6). Coherent under flat topology — under rooted topology an empty root would still inherit its children, which is not. |
| Move orphans an object from the scene | New scope collections must be linked under `scene.collection.children`, same as `_ensure_watch_collection`. |
| Add objects while an unrelated viz is expanded | Cue in the viz body when its collection is not the active one. Every collection stays listed (D9), so the target is never off-screen. |
| Visualizer with no `Scope` | Listed under `attrvis` and flagged, never orphaned from the UI (D9). Deleting a collection auto-nulls the socket (S1), so this is the only such state. |
| Collection disabled while its objects stay muted | **The 010 bug reintroduced.** Collection enable must feed `_active_watch_targets`, not just the draw loop (D9). |
| Collection toggled off then on | Per-viz enable states must survive intact -- collection state is stored separately, never written onto each visualizer (D9). |
| Object in two collections, one enabled one disabled | Muted by the enabled one. Union semantics already handle it. |

---

## Phase D - discovery (COMPLETE)

Every mechanic the plan depends on, verified in isolation before committing to
it. [`discovery.py`](discovery.py), Blender 5.2.0 headless:

```
blender --background --factory-startup --python-exit-code 0 \
  --python dev_tasks/011_viz_scope/discovery.py
```

**11/11 spikes passed.**

| Spike | Question | Result |
|---|---|---|
| **S1** | Does a GN Collection socket auto-null when its collection is deleted? | **Yes.** `S1Doomed` then `None`. No dangling state exists. |
| **S2** | Is `Scope` a real Collection socket, readable and writable? | **Yes.** `socket_type='NodeSocketCollection'`; `get_input` round trips. |
| **S3** | Does per-viz `Scope` resolve once the `attrvis` override is bypassed? | **Yes.** Shadowed returns all 3 objects; `Target u Scope` returns exactly `S3InB`. **Phase 1's core mechanic, proven.** |
| **S4** | Do GUI-created visualizers already carry `Scope = attrvis`? | **Yes.** `Scope -> attrvis`, `Target -> None`. Migration is near-free. |
| **S5** | Does a `BoolProperty` on `bpy.types.Collection` survive save + reload? | **Yes.** Set `False`, saved, reopened, still `False`. D9's toggle is viable. |
| **S6** | Does a Scene `PointerProperty(Collection)` survive save + reload, and auto-null? | **Yes** to both. `'S6Active'` after reload; `None` after delete. |
| **S7** | Does moving an object between collections change coverage without orphaning it? | **Yes.** src empties, dst gains it, still in scene. D4 is sound. |
| **S8** | Is `display_type` writable on library data? | **WRITABLE.** `'TEXTURED'` then `'BOUNDS'`, no exception. **Refutes D7.** |
| **S8b** | Can `_MUTE_PROP` be written and deleted on library data? | **Yes** to both. The full mute/restore round trip works on linked objects. |
| **S9** | Can `is_visualizer` move to `gpu_sample` without a circular import? | **Yes.** Its body touches only `obj.type` and `obj.modifiers`. Phase 2 is trivial. |
| **S10** | What happens to an object in a collection not linked to the scene? | Seen by `iter_watch_meshes`, **not** in `view_layer.objects`, yet `evaluated_get` still works. Confirms the need for a view-layer filter. |

### What discovery changed

- **D7 withdrawn, Phase 6 deleted.** S8/S8b refuted the read-only premise
  outright. One decision and one whole implementation phase removed.
- **D9's dangling-`Scope` case collapsed** into "unset `Scope`" (S1), so the
  Phase 1 backfill is the only mechanism needed.
- **S10 promoted the view-layer filter** from a suspicion to a confirmed
  requirement, with a precise symptom: sampled, but not in the view layer.

Two spikes were rewritten mid-run. S1 first reported `ReferenceError: StructRNA
of type Collection has been removed` -- a bug in the probe, which held a Python
reference across the delete, not a finding. S8 was written to assert the write
would be *refused*; it succeeded, so the assertion was inverted and S8b added
to check the `_MUTE_PROP` stash as well. Recorded because a spike that passes
for the wrong reason is worse than one that fails.

### Still unverified - requires an interactive session

**Can `panel_prop` nest inside another `panel_prop` body?** (D10). Panel drawing
needs a real UI region, so `--background` cannot answer it. Ten-minute spike at
the top of Phase 5b, with a documented fallback if refused. **Nothing before
Phase 5b depends on the answer**, so implementation can start without it.

---


## Progressive implementation and validation plan

Phase 1 is the only behaviour-changing step; 2–6 are additive and reorderable.
Everything here is headless-testable — collections, sockets and mute all work
in `--background`. Only the drawing is not, per 009.

### Phase 0 — characterisation baseline

Capture today's behaviour before changing it, including the parts that are
*supposed* to flip.

- `scope_baseline.py`: a viz scoped to collection B, with `attrvis` also
  present, currently samples `attrvis` — assert that, so the flip is visible.
- Inventory the three tests that encode the shadowing: `empty attrvis
  suppresses per-viz Scope`, `no attrvis → Scope fallback samples`, `GUI
  add-viz Scope is attrvis`.

**Gate:** harness runs and documents current behaviour; full suite green.

### Phase 1 — un-shadow `Scope` (no UI)

The risky step, and the reason it is safe: GUI-created visualizers already
store `Scope = attrvis`, so for existing files this is close to a no-op.

- `watch_meshes_for_visualizer`: drop the `attrvis` override, always resolve
  `Target ∪ Scope`.
- Migration backfill on load + register: any visualizer with an unset `Scope`
  gets `attrvis`. Version-bumped so it runs once.
- Rewrite the three shadowing tests to assert the new contract.

**Gate:** a viz scoped to B covers only B. Existing GUI-created visualizers
behave identically. A viz with no `Scope` is backfilled, not blanked. Full
suite green. `010` mute tests still pass — the mute path resolves through the
same function.

### Phase 2 — `is_watchable` excludes visualizer carriers

Small, independent, closes the self-visualization hole Phase 1 makes reachable.

**Gate:** a carrier linked into a scope collection is not sampled and not
muted.

### Phase 3 — active collection

- `scene.attrviz_active_scope` pointer, with dangling/deleted → `attrvis`.
- Panel dropdown in place of the current readout line.
- `Add objects` / `Remove objects` retarget to active.
- New visualizers default `Scope` to active.

**Gate:** switching active changes where Add lands and what a new viz scopes
to; deleting the active collection falls back without error; a file with no
`attrvis` creates one lazily on first use (D2a); the dropdown lists exactly
`attrvis` + collections in use as a `Scope` (D8).

### Phase 4 — `New collection from selection`

The migrate gesture. Name prompt → create **sibling** under
`scene.collection.children` → **move** selection out of the active scope →
make it active.

**Gate:** objects leave the old collection; visualizers scoped to the old
collection stop covering them; the new collection is a **sibling** under
`scene.collection.children`, never a child of the active scope (D2); the
resulting topology is flat, so recursion never fires; no object is orphaned
from the scene.

### Phase 5 — per-viz scope UI and drawability readout

- `Scope` dropdown in the viz body (the socket is a Collection — `_draw_socket`
  may render it natively).
- `Scope: attrvis_curvature — 4 objects, 3 carry K`, using 010's
  `_viz_draws_on`. This line is the diagnostic that would have made the
  original vanishing-boxes report self-explanatory.
- Nesting shown explicitly (`⊂ attrvis`) with **effective** counts including
  inherited objects (D2).
- Collapsed header no longer needs the scope appended: under D9 each visualizer
  sits under its collection's group heading.

**Gate:** the readout count equals what is actually drawn, including the
inherited case; a scope containing no carrier of the attribute reads `0 carry`
and the objects stay unmuted (010 consistency).

### Phase 5a - collection enable semantics (no UI)

Data and plumbing first, so the rule is headless-testable before any panel work.

- `BoolProperty` registered on `bpy.types.Collection`, defaulting to enabled.
- `_gpu_visualizers` skips visualizers whose scope is disabled.
- **`_active_watch_targets` skips them too** -- the highest-risk detail in D9.

**Gate:** disabling a collection stops its visualizers drawing **and** restores
its objects' `display_type` (no 010 regression); re-enabling restores both;
per-viz enable states survive a collection off/on cycle unchanged; a visualizer
in an enabled collection is unaffected by another collection's state.

### Phase 5b - panel as a collection tree (D9)

- **Spike first:** confirm `panel_prop` nests inside a `panel_prop` body (D10).
  Interactive session, not headless. Fall back to plain collection header rows
  if refused.
- Group visualizer rows under their scope collection, collapsible.
- Per-collection enable checkbox and object count.
- Active collection indicated by selection; dangling/unset listed under
  `attrvis` and flagged.
- Expand-healing operates within the visible tree.

**Gate:** every visualizer in the file appears under exactly one collection
group; clicking a collection row changes only the active target and leaves the
viewport byte-identical; checking a collection box is the only panel action
that changes what is drawn.

### ~~Phase 6 - linked-data warning~~ **DELETED**

Removed by discovery. Spikes S8 and S8b show `display_type` and the
`_MUTE_PROP` stash are both writable on library data, so the mute and restore
round trip already works on linked objects. There is nothing to warn about.

## Implementation results

Every phase gated before the next began, Blender 5.2.0 headless.

| Phase | Gate | Result |
|---|---|---|
| **0** | Characterise what flips | Predicted exactly one test would invert; exactly one did |
| **1** | Un-shadow `Scope`, backfill unset | 62 passed. Two visualizers on two collections each see only their own |
| **2** | Carriers never watchable | 69 passed |
| **3** | Active scope | 79 passed. Lazy `attrvis`, auto-null fallback, discovery by use |
| **4** | Add to a new scope | 117 passed (rewritten). **Additive: objects stay in the original scope** |
| **5** | Coverage readout | 95 passed. Panel count agrees with the mute set |
| **5a** | Collection enable | 106 passed. **Disabling a collection RESTORES display_type** |
| **5b** | Panel groups by collection | 115 passed. **Switching active changes nothing drawn or muted** |

`test_watch_collection` went 45 -> 115. Everything else unchanged: `test_gpu_sample`
228, `test_surface_direct` 11, plus `test_overlay_kinds`, `test_gpu_color`,
`test_draw_guard`, the 009 baseline (4/4) and the 010 repro (4/4).

A registration smoke test covers what headless cannot: register/unregister/
re-register, all three new properties, all four operators, all three menus, and
the panel helpers against an empty scene.

### Deviations from the plan

**Phase 5b uses plain rows for collection headers, not nested layout panels.**
The nesting question (D10) is still unverified, and per-visualizer `panel_prop`
must stay on the root layout regardless. So collection headings are full-width
rows carrying the collapse triangle, the enable checkbox, a click-to-activate
name and an object/visualizer count, with the visualizer panels beneath them at
root level. This is the documented fallback, and it delivers the whole sketch --
grouping, per-collection toggles, collapse -- with no dependency on the spike.
If nesting is confirmed later it is a cosmetic upgrade, not a rework.

**Two discovery spikes were re-pointed.** S3 and S9 asserted PRE-011 behaviour,
so they inverted the moment Phases 1 and 2 landed -- correctly. Rather than
leave a harness that fails by design, both now assert the post-implementation
contract; their original readings are recorded in Phase D above.

### Still outstanding

- **The `panel_prop` nesting spike** (D10). Cosmetic only: Phase 5b shipped the
  documented fallback (plain full-width collection header rows, per-visualizer
  panels at root), which delivers grouping, toggles and collapse without it.
  Interactive session required; not blocking anything.

### Closed since

- **S10's view-layer filter** — **implemented.** `iter_watch_meshes` now drops
  objects not linked into the scene.

  The first attempt filtered on `view_layer.objects` and broke three passing
  tests, because that collection is **resynced lazily**: an object linked
  moments earlier is still missing from it, so freshly-added objects fell out
  of their watch set. Replaced with reachability from `scene.collection` --
  plain data, always current, no resync. Undeterminable keeps the object, so a
  missing context never silently empties a watch set.

  **Rule for this path:** do not filter watch sets on `view_layer.objects`.

- **In-app verification** — done. Surfaced the D4 reversal (collections are
  additive, not exclusive) and confirmed the tree, scope row and coverage
  readout render.

---

## Files

| Path | Why |
|---|---|
| `attrviz/gpu_sample.py:600` | `watch_meshes_for_visualizer` — the shadowing to remove |
| `attrviz/gpu_sample.py:42` | `is_watchable` — must exclude viz carriers |
| `attrviz/gpu_sample.py:570` | `iter_watch_meshes` — the recursion D2 governs |
| `attrviz/__init__.py:162` | `add_visualizer_from_selection` — already sets `scope` |
| `attrviz/__init__.py:1043` | `_draw_watch_readout` — becomes the active-collection dropdown |
| `attrviz/__init__.py:1018` | `ATTRVIZ_MT_edit` — Add / Remove / New collection |
| `attrviz/__init__.py:133` | `_link_to_watch` / `_unlink_from_watch` — retarget to active |
| `attrviz/gpu_overlay.py` | `_viz_draws_on` — feeds the Phase 5 readout |
