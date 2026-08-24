# Review — the AttrViz UI doc

Reviewed as a **new user**: someone who uses Blender, has built a Geometry
Nodes tree or two, has never used Houdini, and has never heard of this addon.
Three questions were asked of the document:

1. What is AttrViz?
2. How do I use it?
3. What can I now author that Blender doesn't let me author today?

It answers **2** well, **1** partially, and **3** not at all.

Two artefacts were reviewed and they share a problem:

- the published HTML artifact *The AttrViz UI*
- `dev_tasks/015_docs_capture/README_ui_draft.md`

The prose is nearly identical in both. **The HTML rendering is not the
problem — it faithfully presented a draft whose prose was already the
problem.** Fixing the format without fixing the prose fixes nothing.

---

## 0. Blocking: the deliverable is `README.md`, not an HTML page

This ships as the repo README on GitHub. That is a hard constraint the HTML
artifact does not satisfy, and it changes what can be authored.

**What breaks if the HTML is ported naively:**

- **`data:` URI images do not render on GitHub.** The artifact inlines all 11
  screenshots as base64 (~3.2 MB). GitHub's markdown sanitiser strips them.
  They must be file references.
- **No CSS, no custom fonts, no `figcaption`.** The IBM Plex type system, the
  accent colour, the shadowed figure frames, the right-aligned captions — none
  of it survives. Anything the design was carrying has to be carried by words
  and structure instead.
- **No `text-wrap: balance`, no `max-width: 66ch`, no columns.** Line length is
  the reader's window width. Long paragraphs read worse on GitHub than in the
  artifact, so paragraphs should be shorter than they currently are.

**The good news — most assets are already correct.** `docs/img/` already holds
the shots as real PNGs, and `README_ui_draft.md` already references them with
working relative paths (`docs/img/menu_root.png`). Keep doing that. The HTML
artifact should be treated as a *preview* of the README, never as the source
of truth.

**What GitHub markdown *does* give you, and should be used:**

- tables (already used well in the draft — keep)
- fenced code blocks (the `attrviz:begin/end` generated blocks work fine)
- `<details><summary>` for collapsible reference material
- relative links between repo files
- `<img width="480" ...>` inline HTML when a panel shot shouldn't render
  full-bleed — worth using, several of these screenshots are ~1300px wide and
  will dominate the page

**One thing that already works in your favour:** the HUD captions burned into
the viewport shots (`CURV POINT SURFACE`, `GRAD POINT ARROWS`) survive the
loss of styled captions, because they're pixels. That convention was a good
call and should continue. Still put a plain italic line under each image —
GitHub has no caption element, so it's just a line of text.

---

## 1. The core problem: the prose never grounds a Blender user

Every sentence in the document describes **a property of the system**. Not one
describes **a moment in someone's work**.

That is why it reads as Houdini-native. A Houdini user arrives already
believing that attributes are the substance of a scene and that seeing them is
a daily need — so mechanism-first prose lands fine. **A Blender user does not
arrive with that belief.** They think in modifiers, node trees, vertex groups,
and the spreadsheet. To them, "visualize an attribute" is an abstraction, not
an appetite. The document never converts the one into the other, so a reader
who doesn't already want AttrViz is never given a reason to.

The hook exists and is unwritten. Every Blender user who has touched Geometry
Nodes has done this dance:

> Your tree isn't producing what you expected. So you open the spreadsheet and
> stare at 507 rows of floats that tell you nothing about *where*. Or you drag
> out a Viewer node — which shows one thing, only while the node editor is
> open, only on the active object, and vanishes the moment you click away. Or
> you give up and wire a temporary Attribute → Emission material just to see
> the field, which means leaving Solid shading, polluting your materials, and
> remembering to tear it all down afterwards.

Name that dance in the opening paragraphs and the reader recognises themself.
Everything after it is then self-evidently useful.

The existing `README.md` already contains the sentence that does this job, and
the UI doc drops it:

> Blender has no equivalent of Houdini's visualizers — the geometry
> spreadsheet shows numbers, the Viewer node is transient, and nothing gives
> you persistent, per-object "show me this attribute in the viewport" workflow.

That is the pitch. It should open the document, expanded into the concrete
version above.

**A working test for every sentence in the rewrite:** *does this describe
something that happens on a screen while a person is trying to get something
done?* If not, it's a property, and it belongs lower down or nowhere.

---

## 2. Sentence-level rewrites

### "A visualizer is made in one place and lived with in another."

The clearest case. A well-balanced sentence containing zero information. A new
user learns nothing from it; a returning user learns nothing from it. Say what
actually differs:

> You create a visualizer by right-clicking the object — because only the
> object knows what attributes it carries. You manage it in the Viz panel,
> because once it exists it may be watching several objects at once.

### "...only the object can answer that, and only on its evaluated geometry, so attributes written by Geometry Nodes show up."

The single most valuable fact in the document — *your GN attributes are
visible* — is a trailing clause after two em-dashes. Promote it and make it a
promise:

> The menu reads the object *after* its modifiers have run. So an attribute
> your Geometry Nodes tree just created is in the list, by name, alongside the
> ones you authored by hand. If you named it `grad`, you'll see `grad`.

That last line quietly solves the most common Geometry Nodes bug there is — a
typo in a Named Attribute string silently yielding zeros. **If the name isn't
in the menu, you just found your bug.** That is a use case, stated as prose, in
one sentence. The document currently contains nothing of this kind.

### "What binds the two is the scope: a visualizer watches a collection, not an object. That is why the panel is a tree rather than a flat list..."

Explains the UI's *consequences* before establishing why anyone would want the
design. Invert it — lead with the payoff:

> One visualizer can cover a dozen objects at once. Point it at a collection
> instead of an object and every member draws the same attribute the same way
> — so you can scan a whole scattered set for the one that's wrong, instead of
> clicking through them one at a time. That's why the panel is a tree: each
> branch is a collection being watched.

Right now Scope reads like bookkeeping. It should read like leverage.

### "Objects in a scope that lack the attribute are skipped and stay visible — they are not hidden with nothing in their place."

Real content wrapped in a rhetorical flourish. Replace the flourish with the
payoff:

> Objects in the scope that don't have the attribute simply don't get ink —
> they stay in the viewport, plainly undecorated, and the panel tells you
> `3 obj / 1 viz`. That mismatch is usually the interesting part: it's the
> objects where your tree didn't run.

### "Type changes how a value is drawn, not which value is read."

This one survives — a real distinction, crisply made. But it stops one beat
before the decision the reader has to make. Follow it with:

> Use **Arrows** when direction is the question, **Surface** when you care
> about the gradient across a whole form, **Markers** when you're checking
> where elements *are* (and how many), **Tags** when you need to read the
> actual number off a specific one.

### "Numbers and ink" (section heading)

A poem where a signpost belongs. The section underneath carries a genuinely
better-than-Blender claim — the spreadsheet lists only *stored* attributes, so
`Normal` never appears there, and AttrViz offers it anyway. Retitle for what it
gives the reader: **"Things the spreadsheet won't show you."**

Headings throughout are stylistic rather than task-shaped. On GitHub they also
become the anchor links and the sidebar TOC, so they carry navigational weight
that they don't carry in the artifact. Make them name tasks.

---

## 3. Missing content a new user needs

- **Install / requirements.** Nothing. No download, no Blender version floor
  beyond a version stamp in the footer, no "the Viz tab is in the 3D viewport
  N-panel sidebar." The doc says "Viz tab" without ever saying where it is.

- **The two trust questions**, both answered in `README.md` and both absent
  here: *will these show up in my render?* (no — `hide_render` on viz
  carriers) and *do they survive a save?* (yes — they're ordinary objects in
  the .blend). These are two sentences that convert a curious reader into
  someone who installs.

- **Colour is never explained.** Heat / RGB / Random don't appear in the prose
  at all, yet `panel_scope_tree.png` shows "default Random / Surface", "Hash
  colour per id", and a Seed field, and the hero image is a blue-to-orange
  gradient. Looking at that Suzanne, a new user's first question is not "how do
  I make one" — it's **"what does green mean, and what's the range?"** Is Heat
  normalised per object, per scope, per frame? Is there a legend? For a
  diagnostic tool, unlabelled false colour is a trust problem: the reader can
  see a shape but can't read a value.

- **Domain is treated as already understood.** "The menu is domain-first"
  arrives before Point / Edge / Face / Corner / Instance has been defined. Pick
  the audience explicitly. If it's Houdini refugees, say so in the lede and the
  vocabulary comes free. If it's Blender users — which is what the README
  should assume — give one sentence mapping the terms to
  vertices / edges / faces / loops, plus why localising the read matters. The
  existing README line does it: *"Face attrs draw on faces, not smeared to
  points."*

- **GPU Overlay is visible but unexplained.** `panel_scope_tree.png` has a
  prominent blue `GPU Overlay` button and a "Solid OK" pill. A new user will
  click it and not know what changed — or will have it off, see nothing in
  Solid shading, and conclude the addon is broken. Needs a line: on by
  default, draws as unlit ink in Solid mode, turn it off for the materials
  path (prefer Material Preview there).

- **`attrviz` vs `attrvis`.** The product is AttrViz; the default collection is
  `attrvis`. One letter apart, never explained. In the panel the Scope dropdown
  reads `attrvis`; the Edit menu reads "Add objects to attrvis" — and a new
  user cannot tell whether that's the addon's namespace, a magic collection, or
  something they created. The main README explains it ("created the first time
  something needs one — an ordinary collection, not a special case"); this doc
  must too, in one line, at first mention. **Strongly consider renaming the
  collection to `attrviz` and deleting the problem outright.**

- **Nothing on failure.** No "I turned it on and saw nothing" section. The
  common causes are known: wrong domain, object doesn't carry the attribute,
  GPU Overlay off in Solid shading, geometry is instanced.

- **Nothing on limits.** Performance on a heavy mesh, the Tag Cap, what's
  roadmap.

---

## 4. The biggest gap: nothing shows what the reader can now *do*

The document is a tour of surfaces. Every noun is UI. There is not one **task**
in it — no moment where somebody was trying to author something, couldn't see
what was wrong, turned on a visualizer, and saw it.

Those moments clearly exist already. The panel screenshot contains the tooltip
**"IDs before Subdiv interpolate — use …"**. Somebody hit that bug. *That* is
the story: my per-plate IDs went to mush after subdivision, the spreadsheet's
507 rows didn't tell me, and three seconds of `plate_id · Face · Surface` did.

Three short worked examples would change the document's character entirely:

1. **Debugging a Geometry Nodes graph.** An attribute you wrote in GN, wrong,
   seen wrong, fixed. This is the killer use case and it is currently one
   subordinate clause.
2. **Reading a field before you drive something with it.** `curv` or `grad`
   inspected on the surface, confirmed, *then* wired into scatter density or
   instance rotation. That is the procedural authoring loop Blender genuinely
   lacks and the one that answers question 3.
3. **Comparing across a set.** This is what Scope is *for*: one visualizer,
   same attribute, twelve objects, spot the outlier.

Each of these can be three sentences and one existing screenshot. They do not
require new capture work.

---

## 5. Figures

- **`docs/img/` already holds the assets and the draft already references them
  correctly.** Keep that; do not inline base64.
- **The four-ways tableau is the strongest single asset** — but the Tags
  quadrant is a pile of overlapping numbers, which makes Tags look broken
  rather than useful. Re-shoot with a sparser mesh, a much lower Tag Cap, or a
  categorical/string attribute where the labels are short.
- **The hero image is reused verbatim** under "Numbers and ink" without making
  a new point. Either make a new point about it or cut the second instance.
- **Panel shots will render very large** on a GitHub README at full width.
  Consider `<img width="420">` for the vertical sidebar captures.
- **The HUD caption convention is good.** Keep it, and add a plain italic line
  under each image as the GitHub-native caption.

---

## 6. Suggested structure

The current draft is section 5 of this list. Sections 1, 2, 4, 6 and 7 do not
exist yet.

1. **The gap** — the "Blender has no equivalent" paragraph, expanded into the
   concrete spreadsheet / Viewer-node / temporary-emission-material dance.
   Plus the hero image. Two paragraphs.
2. **60 seconds** — install, default cube, RMB → `position`, done. One image.
3. **The model** — a visualizer is an object; a scope is a collection; domain /
   type / colour. Define the whole vocabulary once, here.
4. **What it lets you author** — the three workflows from section 4 above. This
   is the part that answers "what is Blender missing," and it's the part that
   doesn't exist.
5. **UI reference** — essentially the current draft, which is good at this job.
6. **When nothing appears** — the four failure modes.
7. **Limits and roadmap.**

---

## 7. What's working — keep it

- **The three-surface orientation table** (RMB / Viz tab / Outliner → what each
  is for). Unusually effective: three rows and the reader knows the shape of
  the tool. Keep it, but move it *after* the why.
- **The screenshots are excellent** — specific, situated, captioned with real
  attribute names from a real scene. They already pass the "moment in someone's
  work" test that the prose fails. **The prose is the only layer of this
  document operating at the abstract altitude.**
- **`menu_root.png`** captures all three cascade levels *plus* the type/colour
  hints (`curv float → Heat / Surface`) in one image. That one picture teaches
  more than the paragraph around it.
- **The instanced-geometry material** is the best-argued part, because the
  addon explains the problem in-menu ("Point / Edge / Face / Corner: no
  elements — geometry is instanced"). Software that teaches in place is a
  strong quality signal; show it off.
- **The honest coverage reporting** (`3 objects - 2 carry grad`) is a real
  design virtue. State it as a benefit, not as a disclaimer.
- **"Empty domains are skipped rather than shown greyed, so the menu is also a
  readout of what the object actually has."** One of the few sentences in the
  draft that already passes the test. More like this.

---

## Summary

- **Format:** must be `README.md` with relative image paths. HTML is a preview
  only; base64 images will not render on GitHub.
- **Prose:** rewrite top to bottom, not patch. Same screenshots, same rough
  section order, but every sentence re-aimed at a Blender user who has not yet
  been given a reason to care.
- **Structure:** add the opening "gap", a quickstart, three worked workflows,
  and a troubleshooting section.
- **Correctness gaps:** colour modes, domain vocabulary, GPU Overlay, install,
  render/save behaviour, and the `attrviz` / `attrvis` naming collision.
