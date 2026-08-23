# Doc map — which shot and which generated block feeds which section

Written before Phase 1-3 deliberately. The POR sequences docs **last** (Phase
5), but the doc sections are what *define* the scenario list; deriving them
first turns Phase 3/3b from guesswork into a checklist.

Status: **outline**. Nothing wired yet. Six shots already exist from the M1/C3
probes and are marked ✅.

---

## Shot inventory

| # | Shot | Source | Proves | Exists |
|---|---|---|---|---|
| S1 | `panel_scope_tree` | `attrviz_scope.blend` | collection groups, per-group toggles, `N obj / N viz` counts | ✅ `out/panelTall` |
| S2 | `menu_root` | same | `AttrViz →` Visualize / Edit | ✅ `out/dirA` |
| S3 | `menu_visualize_point` | same | the cascade: domain submenus + attribute list with dtype and auto-pick | ✅ `out/run1` |
| S4 | `menu_edit` | same | `Add objects to <scope>` — the label carries live scope name | ✅ `out/dirA` |
| S5 | `menu_scope` | same | radio list, live object counts, singular/plural | ✅ `out/dirA` |
| S6 | `menu_domain_face` | same | domain-localised attrs (`sharp_face`), Face-specific auto-pick | ✅ `out/dirA` |
| S7 | `hero_cube_position` | **new fixture** — default cube | the one-click promise in the hero image | ✗ |
| S8 | `panel_grad_expanded` | `attrviz_scope.blend` | the coverage readout `3 objects - 2 carry grad` | ✗ |
| S9 | `viewport_arrows` | same | arrows on two carriers, non-carrier visibly untouched | ✗ |
| S10 | `outliner_registry` | same | `attrvis` / `attrvis_curvature` / `Visualizers` as ordinary collections | ✗ |
| S11 | `menu_instanced` | **new fixture** — instanced geo | the "Geometry is instanced — add Realize Instances" guidance | ✗ |

**Panel expansion is scriptable**, so S1/S8 are exactly settable and
assertable: `obj.attrviz_ui_expand` (`layout.panel_prop`, `__init__.py:1488`)
and `coll.attrviz_scope_expand` (`:1445`).

**But `_update_ui_expand` (`:1775`) is an accordion** — expanding one
visualizer closes the others. **A shot can never show two visualizers expanded
at once.** Any doc section implying otherwise is describing a UI that does not
exist. This is why S1 and S8 are separate shots rather than one.

---

## Generated text blocks

Marker convention per the POR: `<!-- attrviz:begin <name> -->` … `:end`.

| Block | Feeds | Source of truth |
|---|---|---|
| `axes-table` | README *Visualization axes* | the `attrviz_domain` / `attrviz_style` / `attrviz_display` enum items — the table is currently hand-transcribed from them |
| `panel-tree` | README *Scopes*, the ASCII block | `visualizers_by_scope()` + the panel's own row format |
| `coverage-line` | README *Scopes*, `3 objects - 2 carry grad` | the panel's coverage format string |
| `scope-list` | README *Scopes* | `scope_collections()` with live counts |

`axes-table` is the highest-value one and is not in the POR's list. It is a
hand-transcription of three enums; adding a Display type means editing code and
remembering to edit a markdown table.

---

## README, section by section

| Section | Line | Action |
|---|---|---|
| hero image | 6 | **replace** `docs/cube_position.png` (hand-made) with S7 |
| *What it is* | 11 | S1 beside the "Viz tab in the sidebar" bullet; S10 beside "visualizers are ordinary scene objects" |
| *Why it's fast* | 36 | none — prose about architecture, no UI claim |
| *Visualization axes* | 54 | generate `axes-table`; add S3 under the "RMB → Visualize Attribute opens domain submenus" paragraph, and S6 to show the domain claim is real |
| *Scopes* | 70 | S2 + S4 for the Edit list; S5 for active-scope; generate `panel-tree` and keep S1 next to it; generate `coverage-line` and add S8 |
| *Install* / *Tests* / *Design notes* / *Roadmap* / *License* | 122+ | none |

### One claim no existing shot verifies

README line ~113 states the panel reports `3 objects  -  2 carry grad`. The
captured panel shows **two different coverage formats**:

```
3 objects - Cube_No...ed, Torus_Measured     ← scope header: NAMES
1 object  -  1 carry curv                    ← per-viz body: COUNTS
```

The README quotes the per-viz form, but in every shot so far the `grad`
visualizer is **collapsed** — the expanded one is `curv`. So the exact string
the README claims has never been photographed. **S8 exists to verify it**, and
`coverage-line` exists so it cannot drift again.

The two formats being different is itself undocumented.

---

## docs/explorations.md

`### UI: the badge` carries a hand-drawn ASCII mock of a UI that **is not
built** (constant/varying badges). Leave it alone — it is a design document,
not a description of shipped behaviour. Do not point the harness at it, and do
not let a generated block imply the badge exists.

Worth a note in that section saying so, since a reader arriving from the README
cannot currently tell design-intent from shipped.

---

## Gallery page — `docs/gallery.md`

New. One section per Display × Color combination, each a generated shot with
its generating parameters printed beneath. This is where the "crowded scene"
problem from the POR's open design decision actually bites, and the answer is
the POR's own middle ground: one fixture, each scenario **hiding the
collections it does not need**.

---

## Sequencing consequence

The shot list changes the fixture question. Three fixtures are needed, not one:

1. `attrviz_scope.blend` — **exists**, feeds S1-S6, S8-S10.
2. a default-cube scene for S7 — trivial, scriptable.
3. an **instanced-geometry** scene for S11 — the un-realized instances case at
   `__init__.py:1216`, which has no test and no doc.

That third one is new information: the POR's Phase 1 assumed a single
`docs_demo.blend`. S11 cannot share a fixture with S1-S6, because the whole
point is that the mesh domains are *empty*.

## Open

- Sidebar **width** has no clean API, so `Cube_No...ed` truncation is
  unavoidable in S1/S8 (see `FINDINGS_M1.md`).
- S9 (viewport arrows) needs C2 — the overlay redraw tick count — which is
  still unmeasured.
- S3 is a cascade shot, therefore **generator-only, never regression-gated**
  (C7b). S1, S2, S4, S5, S6, S8 can all be gated.
