# DRAFT — proposed README `## The UI` section

Slots in after *What it is*, before *Scopes*. Image paths are real; the
`attrviz:begin/end` blocks are Phase 4 targets and are hand-written here as
placeholders showing the intended output.

**The images are from the OLD fixture.** The demo scene is moving to Suzanne,
so every shot here is provisional — see *Notes for review*. The structure and
prose are what to review now; the pixels get re-captured.

---

## The UI

Three surfaces, and the split between them is the whole mental model:

| Surface | Verb | Why it lives there |
| --- | --- | --- |
| **RMB menu** | *create* | the attribute list can only be read off the object you clicked |
| **Viz tab** (sidebar) | *tune and manage* | persistent state needs a persistent home |
| **Outliner** | *inventory* | visualizers are ordinary objects, so the outliner is already the registry |

A visualizer is **made** in one place and **lived with** in another. The
right-click menu answers *"what does this object carry?"* — a question only the
object can answer, and only on its evaluated geometry. The Viz panel answers
*"what am I drawing, and on what?"* — a question about the scene. Nothing here
is modal; the menu never blocks the panel.

What binds the two is the **scope**: a visualizer watches a *collection*, not
an object. That is why the panel is a tree rather than a flat list, and why
Add / Remove sit on the menu right next to Visualize.

### Right-click — where visualizers come from

![AttrViz context menu](docs/img/menu_root.png)

Two verbs, and they are deliberately not the same thing: **Visualize
Attribute** creates, **Edit** changes who is being watched.

![Visualize Attribute, Point domain](docs/img/menu_visualize_point.png)

The menu is domain-first. Each submenu lists only attributes that exist on
*that* domain of the evaluated geometry, with the dtype and the auto-picked
Color / Type it would create:

<!-- attrviz:begin menu-point-example -->
```
Intrinsic
  Index     int · intrinsic     → Random / Surface
  Position  vector · intrinsic  → RGB / Surface
  Normal    vector · intrinsic  → RGB / Arrows
Attributes
  curv  float   → Heat / Surface
  grad  vector  → RGB / Surface
```
<!-- attrviz:end menu-point-example -->

Empty domains are skipped rather than shown greyed, so the menu is also a
readout of what the object actually has.

![Face domain](docs/img/menu_domain_face.png)

Face carries `sharp_face` and Point does not. Localising the read is the point
— a face attribute draws on faces, never smeared to points.

### The Viz tab — where they live

![The Viz panel](docs/img/panel_scope_tree.png)

Visualizers are grouped under the collection each one watches:

<!-- attrviz:begin panel-tree -->
```
▼ ☑ attrvis                3 obj / 1 viz
     ▶ ☑ grad · Point · Arrows
▼ ☑ attrvis_curvature      1 obj / 1 viz
     ▶ ☑ curv · Point · Surface
```
<!-- attrviz:end panel-tree -->

- the **group checkbox** ANDs with each visualizer's own toggle, so individual
  states survive a group being switched off and on
- **clicking a group name** makes that collection active — the target for
  Add / Remove. It changes nothing on screen
- expanding a visualizer reveals Scope / Domain / Attribute / Type / Color and
  the per-type controls

Coverage is reported honestly rather than hidden:

<!-- attrviz:begin coverage-line -->
```
3 objects  -  2 carry grad
```
<!-- attrviz:end coverage-line -->

Objects in a scope that lack the attribute are skipped and stay **visible** —
they are not hidden with nothing in their place.

> One visualizer expands at a time. Opening one closes the others, so compare
> by switching, not by expanding both.

### Choosing what is watched

![Active Scope](docs/img/menu_scope.png)

Every collection is listed with its live count, and the filled radio is the
active one — the destination for Add / Remove and the default Scope for the
next visualizer.

![Edit menu](docs/img/menu_edit.png)

The labels name the destination, because with several scopes "Add objects"
alone does not say where.

---

## Notes for review

- **Every image is generated** by `run_captures.py`, currently from
  `examples/attrviz_scope.blend`. Four are gated at ≤200px drift;
  `menu_root` and `menu_visualize_point` are cascades and regenerate without
  gating.
- **Switching the demo to Suzanne re-cuts all of this.** It is not only the
  hero image: the demo scene is what every UI shot is taken against, so the
  object names in the panel, the attribute lists in the menus, and the numbers
  in `coverage-line` all change with it. Concretely — re-build the fixture,
  re-run `--selfcheck`, re-`--bless` the four gated baselines, and re-check
  every count quoted in this prose. Suzanne also has enough curvature variation
  to make `curv` legible, which the sphere did not.
- Open: whether `attrviz_scope.blend` is rebuilt around Suzanne or a separate
  docs fixture supersedes it. The tests reference the existing scene, so
  rebuilding it in place is not free.
- The three `attrviz:begin` blocks are **hand-written placeholders**. Phase 4
  generates them; until then they can still drift.
- The blockquote about the accordion is new prose — it documents behaviour
  (`_update_ui_expand`) that no image can show and nothing currently states.
- Not yet covered here, for want of shots: the outliner as registry, arrows in
  the viewport (needs C2), and the instanced-geometry guidance.
- Some overlap with the existing *Scopes* section is deliberate — that section
  should probably shrink to the semantics (additive, flat by default) once this
  one carries the visuals.
