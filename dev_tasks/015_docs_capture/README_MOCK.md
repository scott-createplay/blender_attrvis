# MOCK — the rewritten `README.md`

Structure and argument for sign-off. Prose is draft; image lines are stubs
describing what each figure shows and why it is there. Governed by
[`DOC_GUIDANCE.md`](DOC_GUIDANCE.md).

Every option is enumerated in prose. **The document reads complete with images
turned off** — figures confirm what the reader has already been told.

---
---

# AttrViz

> **See any attribute, on the geometry it belongs to.** Right-click an object,
> pick an attribute, and it draws in the viewport — in Solid shading, without
> touching your mesh, your materials, or your render.

> 🖼 **`strip_numbers_to_ink`** — the Spreadsheet's columns of floats beside the
> same values drawn on Suzanne. The thesis in one picture: these are the same
> data, and normally you join them in your head.

---

## The gap

Blender will show you **shape** — the viewport. And it will show you
**values** — the Spreadsheet editor, hundreds of rows of floats. It will not
show you the two together, so you cross-reference: read a row, find the
element, hold the mapping in your head, repeat.

If you work in Geometry Nodes, the **Viewer node** doesn't close this either.
It shows what the geometry *is* at that point in the tree — at best one
anonymous field on the active object, while you're inside the node editor. It
won't tell you what `plate_id` is on *that* face, in the viewport, beside the
object it belongs to.

AttrViz is that translation. It draws the values onto the geometry.

---

## Sixty seconds

### Install
Blender 5.x. Install the add-on and enable it. *(exact steps TBD)*

### Your first visualizer
1. Open the sidebar in the 3D viewport (`N`) and pick the **Viz** tab.
2. Right-click any object → **AttrViz → Visualize Attribute**.
3. Choose a domain, then an attribute.

That's the whole loop.

The menu reads the object *after* its modifiers have run, so an attribute your
node tree just created is in the list, by name, beside the ones you authored by
hand. If you named it `grad`, you'll see `grad`. **If it isn't there, you just
found your bug.**

> 🖼 **`menu_breadcrumb`** — the full path in one image, left to right: object
> context menu with AttrViz highlighted → Visualize Attribute → Point → the
> attribute list with types and defaults. Confirms the three steps above.


---

## What you're looking at

### Where attributes come from

AttrViz doesn't care who made them:

- **You authored them** — painted, edited, or added as custom layers.
- **A node tree produced them** — visible because the menu reads evaluated
  geometry.
- **They arrived with the file** — USD, Alembic, point caches and sim results
  routinely carry per-element data you never wrote and currently cannot see at
  all.

`Index`, `Position` and `Normal` are always offered on top of whatever the
object carries.

### Domain — where the value lives

- **Point** — vertices. Most attributes live here.
- **Edge** — edges.
- **Face** — polygons. A face attribute draws *on the face*, not smeared out to
  its points.
- **Corner** — face corners (loops): per-face-per-vertex data, like UVs and
  split normals.
- **Instance** — instance references, not the geometry they point at.

Empty domains are skipped rather than greyed out, so the menu doubles as a
readout of what the object actually has.

> 🖼 **`strip_domains`** — the *same* Suzanne twice: `curv` on Point reads as a
> smooth gradient; `face_id` on Face reads as flat per-facet blocks. Two
> different objects could not prove this.

### Colour — how a value becomes a colour

Colour follows the **data type**; it isn't a free choice:

- **Heat** — a scalar through a ramp. By default **Auto Range normalises across
  everything the visualizer watches**, not per object, so several objects share
  one scale and can be compared. Turn Auto Range off to pin Min/Max yourself.
- **RGB** — a vector's channels mapped straight to colour.
- **Random** — a stable colour per id, for ints and categorical data.

> 🖼 **`strip_colors`** — one object, three attributes, three modes: `curv`
> float as Heat, `grad` vector as RGB, `face_id` int as Random. Shows that the
> mode is chosen by the data, not by taste.

### Type — how it's drawn

Type changes *how* a value is drawn, not *which* value is read. Type and Colour
are independent axes.

- **Markers** — a point per element. Where things are, and how many.
- **Surface** — false colour across the mesh. The gradient over a whole form.
- **Arrows** — cones along a vector. Direction and relative magnitude.
  **Needs a vector.**
- **Tags** — the value printed as text at the element, for reading an actual
  number off one. Capped, so it stays legible.

> 🖼 **`tableau_displays`** — one attribute (`grad`, as RGB throughout) drawn
> four ways, one cell per Type. Colour is held constant *and stated*, so the
> image teaches one axis.

### It won't touch your render or your file

Visualizers are ordinary objects in a `Visualizers` collection. They save with
your `.blend`, and they don't appear in an F12 render.

---

## One visualizer, many objects

Point a visualizer at a **collection** rather than an object and every member
draws the same attribute, the same way, on the same scale. That's what Scope is
for: scan a scattered set for the one that's wrong instead of clicking through
them one at a time.

`attrvis` is just the default collection name — rename it, or make your own
from a selection.

Objects in the scope that don't carry the attribute simply don't get ink. They
stay visible, plainly undecorated, and the panel says `5 obj / 1 viz`. That
mismatch is usually the interesting part — those are the objects where your
tree didn't run.

> 🖼 **`viewport_scope_compare`** — six tiles, one visualizer, one shared ramp.
> Five are cool; the fourth is plainly hot. The sixth is grey because it never
> got the attribute. Both claims — shared scale, honest coverage — in one shot.

---

## Three things you can now do

### Fix a node tree you can't see into
Your scatter density is driven by an attribute that's wrong somewhere.
Visualize it on Face and the dead patch is obvious in the viewport — no probing
single rows in the Spreadsheet.

### Check a field before you drive something with it
Look at `grad` as Arrows, confirm the directions are what you meant, *then*
wire it into instance rotation. That confirmation step doesn't exist in Blender
today; you wire it up and infer backwards from the result.

> 🖼 **`viewport_arrows`** — `grad · Point · Arrows` on visible geometry. The
> arrows sit *on* the mesh; only Surface replaces it.

### Read data you didn't author
A USD or Alembic import lands with attributes you didn't write. There's no tree
to inspect and nothing to have anticipated. Point a visualizer at it and look.

---

## The UI in detail

### The right-click menu
Domain-first; each submenu shows only what exists on that domain, with its type
and the Colour / Type pair it will create.

> 🖼 **`menu_domain_face`** — the Face submenu, listing `sharp_face` and
> `face_id`, which Point does not carry.

### The Viz panel
Visualizers group under the collection each one watches. A group checkbox ANDs
with each visualizer's own toggle, so individual states survive a group being
switched off and back on. Clicking a group name makes that collection active.
One visualizer expands at a time.

> 🖼 **`panel_scope_tree`** *(rendered at `width="420"`)* — the tree with
> several scopes, live `obj / viz` counts, and one visualizer expanded showing
> Domain, Attribute, Type and Colour.

### Adding and removing objects
Additive — an object stays in every collection it already belongs to. Scopes
are flat unless you nest them yourself in the outliner.

> 🖼 **`menu_scope`** — the Active Scope list with live object counts and a
> filled radio on the active one.
>
> 🖼 **`menu_edit`** — Add / Remove, with the destination scope named in the
> label.

---

## When you turn it on and see nothing

In the order worth checking:

1. **Wrong domain** — the value is on Face and you're looking at Point.
2. **The object doesn't carry it** — check the coverage count in the panel.
3. **GPU Overlay is off** and you're in Solid shading. It's on by default and
   draws unlit ink in Solid; turn it off only for the materials path, where
   Material Preview is preferred.
4. **The geometry is instanced** — the menu says so in place, and tells you to
   add Realize Instances or read it on the Instance domain.

> 🖼 **`menu_instanced`** — the guidance rendered in the menu itself:
> "Point / Edge / Face / Corner: no elements — geometry is instanced".

---

## Limits and roadmap

- **Tags is capped** and needs a low cap to stay readable on dense meshes.
- **Cost on heavy meshes** — *(numbers TBD)*.
- **Auto Range shows no numbers.** With it on, the computed min and max aren't
  displayed anywhere: you can see the shape of a field but not read its bounds.

---

## Design notes · Tests · License

Existing content, kept. The Houdini comparison lives here rather than in the
opening line.

---
---

## Figure ledger

| Figure | Section | Status |
|---|---|---|
| `strip_numbers_to_ink` | banner / The gap | exists |
| `menu_breadcrumb` | Sixty seconds | exists |
| `strip_domains` | Domain | **new** |
| `strip_colors` | Colour | **new** |
| `tableau_displays` | Type | **re-shot** — Colour pinned to RGB and stated |
| `viewport_scope_compare` | One visualizer, many objects | **new** |
| `viewport_arrows` | Check a field | exists |
| `menu_domain_face` | The right-click menu | exists |
| `panel_scope_tree` | The Viz panel | exists |
| `menu_scope`, `menu_edit` | Adding and removing | exists |
| `menu_instanced` | Nothing appears | exists |

Retired from the document (kept as assets): `viewport_hero`,
`spreadsheet_attributes`, `menu_root`, `menu_object_context`,
`menu_visualize_point` — each superseded by a figure that makes a point the
prose has already raised.
