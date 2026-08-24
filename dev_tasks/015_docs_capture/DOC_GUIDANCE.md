# Guidance — how the AttrViz docs are written, and what the images are for

Distilled from the review in `REVIEW_README_ui_draft.md` and the rounds that
followed it. This governs the README rewrite and every figure the harness
produces for it.

---

## Who is reading

A Blender user. They have built a Geometry Nodes tree or two. They have never
used Houdini and have never heard of this addon. **They do not arrive believing
that attributes are the substance of a scene** — that belief is a Houdini
inheritance, and prose that assumes it reads as an abstraction rather than an
appetite.

Three questions, in order:

1. What is AttrViz?
2. Why would I want it?
3. How do I use it?

An earlier draft answered 3 well, 1 partially, and 2 not at all.

---

## The thesis: AttrViz is an introspection tool

Blender shows you **shape** (the viewport) and it shows you **values** (the
Spreadsheet editor). It does not show the two together. So the user
cross-references: read a row, find the element, hold the mapping in their head,
repeat.

**AttrViz is that translation.** It draws the values onto the geometry.

Two things this framing must not get wrong:

- **The Geometry Nodes Viewer node is not a weaker version of AttrViz.** It
  shows what the geometry *is* at a point in a tree — at best one anonymous
  field on the active object, while the node editor is open. It does not tell
  you what a named attribute is on a given element, in the viewport, beside the
  object it belongs to. Always name it as a *Geometry Nodes* node; a reader who
  does not use GN will not know the term, and the argument must survive them
  skipping that paragraph.
- **AttrViz is not a Geometry Nodes tool.** Attributes arrive from three
  directions and it does not care which: authored by hand, produced by a node
  tree, or **arrived with the file** — USD, Alembic, point caches, sim results.
  That third case is the strongest, because there is no tree to inspect and
  nothing to have anticipated. GN debugging is the first worked example, never
  the frame.

---

## The sentence test

> Does this describe something that happens on a screen while a person is
> trying to get something done?

If not, it is a property of the system. Properties belong lower down, or
nowhere. Sentences that failed this test and were cut:

- *"A visualizer is made in one place and lived with in another."* Balanced,
  and carries zero information.
- *"What binds the two is the scope: a visualizer watches a collection, not an
  object. That is why the panel is a tree..."* Explains a UI consequence before
  establishing why anyone would want it. Scope must read as **leverage**, not
  bookkeeping.

Sentences that pass, and are the model:

- *"If you named it `grad`, you'll see `grad`. If it isn't there, you just
  found your bug."*
- *"Empty domains are skipped rather than greyed out, so the menu is a readout
  of what the object actually has."*

---

## The images validate; they never carry the argument

**The document must be complete with images turned off.**

Enumerate options in prose — domains, types, colour modes — as explicit bullet
lists. *Then* show a figure so the reader can confirm what they just read
against the real UI. A figure that is the only place something is explained has
been given the wrong job.

Consequences for the harness:

- Every figure answers a question the prose has already raised.
- A figure that teaches an axis must not silently hold another axis constant.
  The old Display tableau varied Type while pinning Colour to Heat, which
  taught that Surface *means* a heat ramp. It does not — **Type and Colour are
  independent**.
- Burnt-in HUD captions stay. They survive GitHub, which has no caption
  element, and they say what is being visualized without prose.
- Each figure is used once. A repeated image without a new point is filler.

---

## Format constraints — the deliverable is `README.md`

- **Relative paths to `docs/img/*.png`.** Base64 `data:` URIs are stripped by
  GitHub's sanitiser. The HTML artifact is a *preview only*, never the source.
- No CSS, no fonts, no `figcaption`. Words and structure carry what design was
  carrying. Paragraphs shorter than they would be in a styled page, because
  line length is the reader's window width.
- `<img width="420">` on tall sidebar captures, or they dominate the page.
- A plain italic line under each image is the caption.
- Headings become anchors and the sidebar TOC, so they name **tasks**, not
  moods. "Things the spreadsheet won't show you", not "Numbers and ink".

---

## Vocabulary that must be defined, once, in prose

Each of these was assumed by an earlier draft and is not safe to assume:

| Term | Must say |
|---|---|
| Domain | Point / Edge / Face / Corner / Instance mapped to vertices, edges, faces, loops, instance references — and why localising matters |
| Colour | Heat / RGB / Random, and that **Auto Range normalises across the whole scope**, not per object |
| Type | Markers / Surface / Arrows / Tags, and which question each answers |
| Scope | a collection; `attrvis` is only the default name of an ordinary collection the user can rename or replace |
| GPU Overlay | on by default, draws unlit ink in Solid shading; off falls back to the materials path |
| Viz tab | it is in the 3D viewport sidebar (`N`) — say so |

Two trust questions must be answered explicitly, because they convert a curious
reader into someone who installs:

- **Will these show up in my render?** No — `hide_render` on viz carriers.
- **Do they survive a save?** Yes — they are ordinary objects in the `.blend`.

---

## Known gaps to state honestly

- With Auto Range on, the computed min and max are not displayed anywhere. The
  reader can see the shape of a field but cannot read its bounds.
- Tags is capped, and needs a low cap to stay legible.

Stating a limit is cheaper than a reader discovering it and distrusting the
rest.
