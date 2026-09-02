---
name: forgeAi3d
description: Designing parts for 3D printing. Builds a model from a description or edits one that was sent in, and hands back a ready STL with previews and a printability report. Works as a loop — the user prints, says what is wrong, and the model is fixed by one constant.
when_to_use: When asked to model a part for printing ("make a stand/holder/lid/adapter", "I'd like to print one"), when an STL/STEP is sent in to be edited, when asked to change a dimension or a clearance in a part that already exists, or when the result of a test print is reported ("the hole is too small", "it does not fit").
argument-hint: <what to model, or a path to a model file>
allowed-tools: Bash, Read, Write, Edit, WebSearch, WebFetch, AskUserQuestion, Skill
---

# forgeAi3d — modelling for 3D printing

Code CAD: a part is a Python file built with build123d, and out of it come an STL to
print, a STEP for further edits and exact analysis, and a 3MF for Bambu Studio. The model
is text, so it can be seen whole, edited surgically, and kept in history.

**Everything lives in the repository root** — `$FORGEAI3D_HOME`, `~/dev/forgeAi3d` by
default. Sources in `models/`, exports in `prints/`, the printer and filament reference
in `forge/`, the tools in `tools/`. Details are in `README.md` in the root.

**The tools report in Russian.** That is what their output looks like; read it as it is
and say the essentials back to the user in the language of the conversation.

**Every part gets its own folder in `prints/`.** Only the STL is in plain sight — that is
what goes into the slicer; STEP, 3MF, previews and sections are tucked into `extras/` so
they do not get in the way:

```
prints/stand/
    stand.stl                     ← this is what the user gets
    extras/stand.step             ← edits and exact analysis
    extras/stand.3mf              ← Bambu Studio
    extras/stand.png              ← preview
    extras/stand-overhangs.png    ← overhangs
    extras/stand-section-y.png    ← section
```

The layout is made by `export_all`; the tools take the path to the STL and find the rest
themselves. There is no need to assemble paths into `extras/` by hand.

**The printer and the filaments on the shelf are described in `forge/spec.py` — read them
from there, not from memory.** Right now it holds a Bambu Lab A1 mini (bed 180×180×180,
0.4 nozzle, no enclosure, no hardened nozzle) and PLA + PETG. When the hardware or the
spools change, they are edited in that one file and the models and checks pick it up.

## The loop

```
understand the task → models/part.py → measure (numbers) → preview (eyes) → check → hand over
                            ↑                                                        ↓
                            └─────────── edit one constant ←── "the hole is small" ───┘
```

```bash
cd "${FORGEAI3D_HOME:-$HOME/dev/forgeAi3d}"
uv run python models/part.py                          # -> prints/part/part.stl + extras/
uv run tools/measure.py prints/part/part.stl          # dimensions and holes as numbers
uv run tools/preview.py prints/part/part.stl          # -> extras/part.png
uv run tools/check.py prints/part/part.stl --material PETG   # exit 1 = do not print
```

## Rules that are not optional

**Numbers first, eyes second.** `measure.py` prints the bounding box, the volume and an
inventory of holes — diameter, depth, "through", centre coordinates. Compare that against
what was asked before rendering: a picture looks right even when the geometry is wrong.

**Then look at the preview yourself anyway.** After rendering, open the PNG with Read.
Nothing gets handed over without this: numbers do not catch "the rib sticks out the wrong
way", and `check.py` does not catch "the hole is in the wrong wall".

**Always run `check.py`.** Do not hand over a file until it returns 0, or until you have
explained to the user why a warning is acceptable here.

**No magic numbers.** Clearances and thicknesses come from `forge` and nowhere else:

```python
from forge import clearance, wall, compensate_shrink
hole = 8 + 2 * clearance(MAT, "slip")   # not 8.6
t    = wall(3)                          # not 1.26
```

**Parameters are constants at the top of the file**, each with a comment saying where it
came from. Then a fix after a print is one line rather than a rebuild:

```python
MAT       = "PETG"
PHONE_W   = 78.0    # measured with calipers, iPhone in its case
WALL      = wall(3)
```

**Export through `export_all`** — it writes all three formats and verifies the write:

```python
from forge import export_all
paths = export_all(part.part, "part", material=MAT)
```

**The names line up:** `models/stand.py` → `prints/stand/stand.stl`. `check.py` and
`measure.py` pick the STEP out of `extras/` themselves and analyse it exactly.

## Dimensions of someone else's hardware are never invented

The footprint of a board, the diameter of a lens, the pitch of mounting holes — these are
facts, not estimates. A mistake here shows up neither in the preview nor in the check: the
part comes out neat and does not fit.

In order:

1. **ask for a measurement** — if the user has the object in hand, that beats any
   datasheet: name the three numbers you need;
2. **look in the cache** — `forge.get_spec("raspberry pi 5")` returns what was found
   before;
3. **search** — WebSearch for the datasheet or the official documentation, then record it:

```python
from forge import get_spec, save_spec
save_spec("raspberry pi 5", {"length": 85.0, "width": 56.0, "hole_pitch_x": 58.0},
          source="https://datasheets.raspberrypi.com/rpi5/raspberry-pi-5-mechanical-drawing.pdf")
```

A number without a source is not stored — `save_spec` will not allow it. In the model
itself, leave a comment next to the constant saying where it came from.

If it cannot be found, say so plainly and offer to measure. Do not substitute something
plausible.

## What to ask about and what to decide yourself

Ask only about what would make the part wrong if guessed:

- **the dimensions of the physical object** the part attaches to (see above);
- **the material**, when it changes the construction (heat, load, flexibility). Otherwise
  take PLA and say so out loud;
- **how the part is loaded** — when wall thickness and ribs depend on it.

Decide yourself and name the decision in your answer: fillets, chamfers, wall thickness,
orientation, hole grid pitch, aesthetics. Do not run a five-question interview over a
phone stand.

## Off-the-shelf fasteners — from bd_warehouse

Screws, nuts, washers, bearings, gears and threads are not modelled by hand: their
dimensions come from `bd_warehouse`, to standard. The clearance around them still comes
from `forge` — the library's fits are machine-shop fits, not FDM ones. Examples are in
`references/build123d.md`.

## Editing models from other people

What arrived decides what can be done:

| Format | What to do |
|---|---|
| **STEP** | `import_step()` — a real solid, cut and edited in build123d like your own |
| **STL** | the geometry cannot be recovered. Small edits — trimesh (scale, rotate, cut, boolean, repair). Serious ones — remodel from scratch off measurements, and say so honestly |

`import_stl()` in build123d returns a `Face`, not a solid — booleans against it will not
work. For meshes it is trimesh only (`manifold3d` is installed, booleans work). Details
are in `references/build123d.md`.

**A hollow model that should be solid** — `tools/solidify.py`: it cuts away the inner
shell, caps the rim and returns a solid the slicer will fill with infill. The outer
geometry is left untouched.

It works in two steps: first it shows the voids it found, then it fills the chosen ones.
Without `--fill` no file is written. A void cannot be told from a through hole
automatically, so **the choice belongs to the human**: show the user the list and ask what
to fill, do not decide it yourself. The list has hints — "0 open edges" means a closed
void, and a bounding box like 3.9×3.9×5.2 mm gives away a screw hole.

```bash
uv run tools/solidify.py incoming.stl                    # list the voids
uv run tools/solidify.py incoming.stl --fill 1     # -> prints/incoming_solid/
```

**Never overwrite the file that was sent in.** The result is a new file in `prints/`.

## When the part cannot be printed

`check.py` computes the geometry with augura off the STEP — exactly, from faces rather
than from triangles. What it says and what to do about it:

| Finding | What to change |
|---|---|
| thin wall | `wall(3)` instead of `wall(2)`. It fails the part when a noticeable share of the surface is thin; about a single chamfer edge or a raised letter it only warns |
| overhang | turn the part over, replace the overhang with a 45° chamfer, make the hole a teardrop |
| will tip over | brim, print it on its side, or widen the base |
| brim needed | tell the user; this is not a defect of the model |
| lay it differently | the suggested rotation is augura's recommendation — decide it together with the user |
| step thinner than a layer | a small feature will disappear: make it bigger or print with a thinner layer |

To see **where** the overhangs are: `uv run tools/preview.py prints/part/part.stl
--overhangs --material PETG` — they come out red. To see inside: `--section y` (cut
through the middle, or `y:12.5`). The images land in `extras/` next to the part.

The slowest part of the check is the orientation search. On a large part whose
orientation is already settled it can be skipped: `--no-orientation`.

## Iterating on the result of a print

The user prints and says what is wrong. This is the most common work of all.

| What they said | What to change |
|---|---|
| "the screw does not go in" / "it wobbles" | the fit passed to `clearance()`, not the number itself |
| "too flimsy", "it broke" | `wall(3)` → `wall(4)`, fillets in the corners, stiffening ribs |
| "it did not fit on the bed" | split it into parts with a joint, or turn it |
| "the bottom spread, the size is off" | elephant foot — a 0.5 mm chamfer along the bottom contour |
| "the supports will not come off" | change the orientation or rework the overhang to 45° |

Change **the constant**, rebuild, show the preview, and say exactly what changed. If the
fix exposes a systematic error in the clearances, offer to calibrate: `uv run python
models/fit_test.py`, print the comb, and write the real numbers into `clearances` for that
material in `forge/spec.py`. Do not create a new file for this — `models/fit_test.py`
already exists.

## What to hand back to the user

1. **the path to the STL — always, on the first line.** A full path like
   `prints/stand/stand.stl`, not "the file is in prints" and not the folder: this is the
   file the human is about to drag into the slicer. Paths to the STEP, the 3MF and the
   previews only if asked, or if they are needed for the job;
2. the preview (show that you looked at it yourself);
3. the verdict of `check.py` in one line;
4. **which constants to turn** and what they change;
5. printing advice when it is not obvious: orientation, supports, brim.

## References

- `references/build123d.md` — an API cheat sheet verified against live code: primitives,
  selectors, holes, shells, revolves, import/export, bd_warehouse, mesh editing, pitfalls
- `references/design-rules.md` — design rules for FDM: walls, overhangs, holes, threads,
  heat-set inserts, snap fits, orientation, splitting large parts

## Limits

Say honestly when the task is not for this stack:

- organic shapes and sculpture belong in Blender, not build123d;
- a precise load-bearing fit needs calibration; until then the clearances are typical
  values;
- a material the printer cannot handle (ASA without an enclosure, PLA-CF without a
  hardened nozzle) — `check.py` says so itself, from the profile in `forge/spec.py`;
- a thread is better cut with a tap or replaced with a heat-set insert than printed;
- on a mesh with no STEP, wall thickness and small features are not checked at all — say
  so when handing back the result of editing someone else's STL.
