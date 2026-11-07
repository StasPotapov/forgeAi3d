---
name: forgeAi3d
description: "Models parts for 3D printing: builds one from a description or edits a model that was sent in, hands back an STL with previews and a printability check, refines it after a test print."
when_to_use: "\"make a stand/holder/lid\", \"I'd like to print one\", an STL/STEP sent in to be edited, a request to change a size or clearance, a test print result (\"the hole is too small\", \"it does not fit\")."
argument-hint: <what to model, or a path to a model file>
allowed-tools: Bash, Read, Write, Edit, WebSearch, WebFetch, AskUserQuestion, Skill
---

# forgeAi3d — modelling for 3D printing

Resolve the complete runtime three levels above this skill; its `forge/`, `tools/` and dependencies are separate from personal models. Read `forge/spec.py` for printer defaults; use `skills/setup/SKILL.md` for setup.

## Private model folders

Personal models are local working data, not tool source. Before creating any model,
ensure `/models/` is Git-ignored in its containing workspace. Never git-add, commit,
push or package personal model code, references, slicer profiles or generated files.
General commit rules apply to development of this tool, not to these private models.
The tool's public templates live in `examples/`; never put user work there or in `docs/`.

Each model is one self-contained directory:

```
models/part/
    model.py                 # editable source; assets use paths relative to this file
    README.md                # dimensions, rebuild command, settings and known limits
    design.png               # one selected reference, when supplied
    part.stl                 # printing geometry
    part.3mf                 # configured slicer project, when prepared
    assets/                  # SVGs, source meshes, print profiles and other inputs
    extras/                  # STEP, geometric 3MF, previews, reports and old revisions
```

Start work from the selected model folder; read its README and source and inspect its
reference. Keep all model-specific data there. Use `export_all(..., out=Path(__file__).resolve().parent)`
so a relocated model rebuilds in its own folder. `out` is a model directory: STEP and
geometric 3MF go to its `extras/`; a configured root 3MF is not overwritten by CAD export.
`FORGEAI3D_HOME` can name the model folder or the parent workspace; `FORGEAI3D_MODEL_DIR`
explicitly selects a model folder. Without either, the working directory is used;
when it contains `model.py`, exports stay there. From a parent workspace they default
to `models/<stem>/`. Runtime and virtual environment remain separate from personal data.
Do not use runtime package directories as a workspace. Keep model-local hardware
measurements in `extras/specs_cache.json`; copy required profiles into the folder.

For migration, back up first, move all inputs and outputs together, resolve relative
paths, verify file hashes and a rebuild, then remove superseded loose locations.
Do not fabricate missing CAD source for a supplied STL: label it as mesh-only.
Do not overwrite a configured project with a geometry-only 3MF. Re-slice explicitly
when geometry changes, verify one instance unless requested otherwise, and keep the
user's printer, material, plate and process settings.

## The loop

```
understand the task → models/part/model.py → measure (numbers) → preview (eyes) → check → hand over
                            ↑                                                        ↓
                            └─────────── edit one constant ←── "the hole is small" ───┘
```

Use `measure`, `preview` and `check` for geometry. Follow user-required code review
as well; review does not authorize committing a private model.

```bash
cd "${FORGEAI3D_HOME:-$HOME/dev/forgeAi3d}"
uv run python model.py                          # -> part.stl + extras/
uv run tools/measure.py part.stl          # dimensions and holes as numbers
uv run tools/preview.py part.stl          # -> extras/part.png
uv run tools/check.py part.stl --material PETG   # exit 1 = do not print
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

**The names line up:** `models/stand/model.py` → `models/stand/stand.stl`. `check.py` and
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
to fill, do not decide it yourself. The list has hints — "open edges 0" means a closed
void, and a size like 3.9×3.9×5.2 mm gives away a screw hole.

```bash
uv run tools/solidify.py incoming.stl               # list the voids
uv run tools/solidify.py incoming.stl --fill 1     # -> models/incoming_solid/
```

**Never overwrite the file that was sent in.** The result is a new file in `models/`.

**Checking against the original — `tools/compare.py`.** After remodelling someone else's
STL, after `solidify.py`, and after an edit that was not supposed to touch the rest,
compare the new against the old by numbers rather than by eye:

```bash
uv run tools/compare.py incoming.stl part.stl --heatmap
```

Read both directions: `reference → candidate` is what got lost, `candidate → reference`
is what appeared. After `solidify.py` the first shows the removed inner shell, which is
expected, while the second should be almost entirely `within` — apart from the capped rim.
The models share coordinates: put a remodelled part where the original sits first.

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

To see **where** the overhangs are: `uv run tools/preview.py part.stl
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
fix exposes a systematic error in the clearances, offer to calibrate: `uv run python models/fit_test_pla/model.py`, print the comb, and write the real numbers into `clearances` for that
material in `forge/spec.py`. First copy `examples/fit_test.py` to that private `model.py` if it is absent;
never overwrite an existing model or edit the public template.

## What to hand back to the user

1. **the path to the STL — always, on the first line.** A full path like
   `models/stand/stand.stl`, not "the file is in prints" and not the folder: this is the
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
