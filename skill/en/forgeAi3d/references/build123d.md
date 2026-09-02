# build123d — cheat sheet

Everything below was verified against live code (build123d 0.11.1, bd_warehouse 0.3.0,
Python 3.14, macOS arm64). Work from the repository root (`$FORGEAI3D_HOME`,
`~/dev/forgeAi3d` by default) and run things with `uv run python models/part.py`.

## Skeleton of a model file

```python
"""What the part is and what it is for."""
from build123d import *
from forge import clearance, export_all, wall, compensate_shrink

MAT = "PETG"

# --- parameters that get turned after a print ---
L, W, H = 40.0, 24.0, 6.0
SCREW   = 3.0            # M3
WALL    = wall(3)

with BuildPart() as part:
    Box(L, W, H)
    Hole(radius=(SCREW + 2 * clearance(MAT, "free")) / 2)

# prints/part/part.stl, the rest in prints/part/extras/; the write is verified
paths = export_all(part.part, "part", material=MAT)
```

## Primitives

```python
Box(l, w, h)                    Cylinder(radius=r, height=h)
Cone(bottom_radius=a, top_radius=b, height=h)   # top_radius=0 gives a non-watertight STL, use 0.5
Sphere(radius=r)                Torus(major_radius=R, minor_radius=r)
Wedge(...)
```

Alignment is the third argument, `align`; the default is centred on every axis:

```python
Box(30, 30, 0.6, align=(Align.CENTER, Align.CENTER, Align.MIN))   # bottom on the plane
```

## Sketching and extruding

```python
with BuildPart() as p:
    with BuildSketch() as plan:          # BuildSketch(Plane.XZ) — a sketch on another plane
        Rectangle(L, W)
        fillet(plan.vertices(), radius=5)
    extrude(amount=H)
```

Flat primitives: `Rectangle`, `RectangleRounded`, `Circle`, `RegularPolygon`,
`SlotOverall`, `Text(txt, font_size=)`, `Polyline`, `Line`, `ThreePointArc`.

## Holes and placement

```python
Hole(radius=r, depth=None)                          # depth=None — all the way through
CounterBoreHole(radius=, counter_bore_radius=, counter_bore_depth=)
CounterSinkHole(radius=, counter_sink_radius=)      # for a countersunk screw

with Locations((-13, 0), (13, 0)):     # arbitrary points
    Hole(radius=2)
with GridLocations(30, 30, 2, 2):      # a grid: X pitch, Y pitch, X count, Y count
    CounterSinkHole(radius=1.7, counter_sink_radius=3.2)
with PolarLocations(radius=20, count=6):
    Hole(radius=1.5)
```

## Selectors — how to get at the edges and faces you need

```python
part.faces().sort_by(Axis.Z)[-1]           # the top face
part.faces().sort_by(Axis.Z)[0]            # the bottom one
part.edges().filter_by(Axis.Z)             # every vertical edge
part.edges().filter_by(Axis.X).sort_by(Axis.Z)[-1]   # the top edge running along X
part.faces().sort_by(Axis.Z)[-1].edges()   # the edges of the top face
```

Then they get filleted or chamfered:

```python
fillet(part.edges().filter_by(Axis.Z), radius=3)
chamfer(part.faces().sort_by(Axis.Z)[-1].edges(), length=0.8)
```

## Shelling, revolving, subtracting

```python
# an enclosure with a 1.26 mm wall, open at the top
with BuildPart() as case:
    Box(40, 30, 20)
    offset(amount=-1.26, openings=case.faces().sort_by(Axis.Z)[-1])

# a solid of revolution from a profile
with BuildPart() as rev:
    with BuildSketch(Plane.XZ):
        Rectangle(10, 20, align=(Align.MIN, Align.MIN))
    revolve(axis=Axis.Z)

# subtract an arbitrary solid
Cylinder(radius=5, height=50, mode=Mode.SUBTRACT)
```

There are also `loft`, `sweep`, `mirror`, `split`, `scale` and `add`.

## Import and export

| Function | Returns | Good for |
|---|---|---|
| `import_step(path)` | `Solid` for one body, `Compound` for several | real editing, boolean operations |
| `import_stl(path)` | **`Face`** | display only; booleans will NOT work |
| `export_step(part, path)` | **`bool`** | exchange, further edits, exact analysis in check.py |
| `export_stl(part, path)` | **`bool`** | printing |
| `export_all(part, stem, material=)` | a `dict` of paths | the normal way: stl + step + 3mf at once |

Solids from an imported STEP come out through `.solids()` — that works for both a `Solid`
and a `Compound`, so there is no guessing about what came back.

**Both exports return a `bool` and raise nothing.** On failure they quietly return `False`
and write nothing — the old file stays on disk and goes to the printer as if it were
fresh. Checking the return value is mandatory; `export_all` from `forge` already does it.

The 3MF is written by build123d's `Mesher` class — it is the only one that carries units
and metadata, which is why Bambu Studio opens such a part in millimetres straight away:

```python
from build123d import Mesher, Unit
mesher = Mesher(unit=Unit.MM)
mesher.add_shape(part.part, part_number="part")
mesher.add_meta_data("forgeAi3d", "material", "PETG", "str", True)
mesher.write("prints/part.3mf")
```

## Off-the-shelf fasteners — bd_warehouse

The dimensions of screws, nuts, bearings and threads come from the standard, not out of
thin air. The clearance around them is added separately: the library's fits are
machine-shop fits and are too tight for FDM.

```python
from bd_warehouse.fastener import HexNut, SocketHeadCapScrew
from bd_warehouse.bearing import SingleRowDeepGrooveBallBearing as Bearing
from bd_warehouse.thread import IsoThread

SocketHeadCapScrew.sizes("iso4762")      # ['M1.6-0.35', 'M2-0.4', 'M2.5-0.45', 'M3-0.5', ...]

screw = SocketHeadCapScrew(size="M3-0.5", length=12, fastener_type="iso4762")
screw.head_diameter                       # 5.68 — for a countersink or a head pocket
screw.head_height                         # 3.0

nut = HexNut(size="M3-0.5", fastener_type="iso4032")
nut.nut_diameter                          # 6.35 — ACROSS CORNERS (e), not across flats
nut.bounding_box().size.Y                 # 5.50 — this one is across flats (s)
nut.nut_thickness                         # 2.4

bearing = Bearing(size="M8-22-7", bearing_type="SKT")   # a 608
bearing.outer_diameter, bearing.bore_diameter           # 22, 8
```

A pocket for a nut is a hexagon sized off the nut plus a fit from `forge`. There are two
easy mistakes here: `nut_diameter` is the diameter **across corners**, and `RegularPolygon`
by default also treats `radius` as the apothem rather than the corner radius. Get both
wrong at once and the pocket is a millimetre too wide, and the nut spins in it.

```python
pocket = nut.nut_diameter + 2 * clearance(MAT, "snug")     # 6.65 across corners, for PETG
with BuildPart() as p:
    Box(24, 24, 10)
    with BuildSketch(Plane.XY.offset(5)):
        RegularPolygon(radius=pocket / 2, side_count=6, major_radius=True)   # ACROSS CORNERS
    extrude(amount=-(nut.nut_thickness + 0.2), mode=Mode.SUBTRACT)   # +0.2 for the fit in height
    Hole(radius=(3 + 2 * clearance(MAT, "free")) / 2)
```

Verified by measuring the pocket: 6.65 × 5.76 mm against a nut of 6.35 × 5.50 — 0.15 mm
per side, exactly what was asked of `clearance`. With `major_radius=False` it would have
come out 7.33 mm.

A seat for a bearing is a press fit:
`bearing.outer_diameter + 2 * clearance(MAT, "press")`.

A thread is only the helical cut; it has to be put onto a shank:

```python
thread = IsoThread(major_diameter=8, pitch=1.25, length=10,
                   external=True, end_finishes=("fade", "fade"))
with BuildPart() as bolt:
    Cylinder(radius=thread.min_radius, height=10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    add(thread)
```

`thread.is_valid` is a property, not a method. A printed thread wears loose: under load,
take a heat-set insert or a nut in a pocket, see `design-rules.md`.

## Editing other people's meshes — trimesh

build123d is no good for STL. Meshes are edited through trimesh (`manifold3d` is
installed, so booleans work):

```python
import numpy as np
import trimesh

m = trimesh.load_mesh("prints/incoming.stl")
if isinstance(m, trimesh.Scene):
    m = m.to_mesh()

m.apply_scale(1.05)                                  # 5% bigger
m.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [1,0,0]))
m.apply_translation([0, 0, -m.bounds[0][2]])         # sit it on the bed

cutter = trimesh.creation.cylinder(radius=4, height=100)
m = trimesh.boolean.difference([m, cutter])          # drill it
m = trimesh.boolean.union([m, plate])                # weld it on

trimesh.repair.fill_holes(m)                         # patch the holes
trimesh.repair.fix_normals(m)
m.export("prints/edited.stl")
```

Cutting with a plane — `m.slice_plane(origin, normal)`. Separate bodies — `m.split()`.

## Pitfalls

- `Cone(top_radius=0)` produces a degenerate triangle at the apex and a non-watertight
  STL — use `top_radius=0.5` or build it as a revolve.
- Solids that touch exactly face to face merge into one — verified, no overlap is needed
  for that. Solids with a gap between them, on the other hand, stay separate and quietly
  end up in the STL as two pieces: watch the "bodies" line in the output of `check.py`.
- `from build123d import *` pulls in a lot of names, but it does not shadow `pathlib.Path`
  — verified.
- Relative paths in the exports are resolved from the CWD. Always build the path from
  `__file__`.
- `part` inside `with BuildPart() as part` is the builder; the solid comes out as
  `part.part`.
