# Design rules for FDM

**The source of truth for the hardware and the filaments is `forge/spec.py`.** What is
explained here is why the numbers are what they are and what else to account for in the
geometry; the actual values come from the spec, not from this file.

The examples below are computed for the current profile: Bambu Lab A1 mini, 0.4 nozzle,
line width ~0.42, layer 0.2, bed 180×180×180, no enclosure, PLA and PETG.

## Walls

Thickness must be a multiple of the line width, otherwise the slicer leaves a gap between
perimeters or fills it with crooked infill.

| Perimeters | Thickness | Where |
|---|---|---|
| 2 | 0.84 mm | unloaded walls, decoration |
| 3 | 1.26 mm | an ordinary enclosure, a lid |
| 4 | 1.68 mm | loaded areas, fasteners, hinges |

`wall(3)` from `forge` works this out itself. The absolute minimum is 2 perimeters.
`check.py` measures thickness exactly off the STEP, from the faces of the solid, and names
the thinnest spot — but it fails a part by the share of the surface: on a chamfer or on
the edge of a raised letter the thickness tends to zero by construction, so the minimum on
its own proves nothing. With no STEP next to the STL, thickness is not checked at all.

## Overhangs and bridges

A surface tilted **steeper than 45°** to the horizontal prints without supports. Shallower
than that needs supports or a different orientation. PETG tolerates less than PLA — its
threshold is 45° against 40° (`support_angle` in the spec).

A bridge between two supports: PLA spans up to ~25 mm, PETG up to ~12 mm. Longer than that
and it sags.

Where the overhangs actually are on a given part is shown by the preview:
`uv run tools/preview.py prints/part/part.stl --overhangs --material PETG` — in red.

Design moves instead of supports:

- make a hole in a vertical wall a teardrop or a hexagon rather than a circle — the top
  then bridges itself;
- replace a horizontal overhang with a 45° chamfer;
- turn the part so the overhangs face upwards.

Supports fuse to PETG for good — with that material it is better to design without them
from the start.

## Holes

**Holes print smaller than nominal.** The layer is laid along the chord, plus the shrink
pulls inwards. So a hole for a screw or a shaft always takes its clearance from
`clearance()`, never the nominal value.

| Fit | What it means |
|---|---|
| `press` | press fit, driven in with a mallet |
| `snug` | goes in with hand force |
| `slip` | slides freely, for shafts and axles |
| `free` | deliberately loose, for clearance holes |

The clearance is given **per side**, and the hole gets twice that:
`d = shaft + 2 * clearance(MAT, "slip")`.

Vertical holes are more accurate than horizontal ones. A hole under 2 mm is better drilled
than printed.

## Corners and stress concentration

Every internal corner gets a fillet. A sharp corner is a crack waiting to happen,
especially in PLA, which is brittle. A radius of at least 1–2 mm, more where it is loaded.

External corners get a 0.5–1 mm chamfer: nicer in the hand, and it does not catch when the
part is pulled off the bed.

## Elephant foot

The first layer is squashed and the bottom of the part comes out 0.1–0.3 mm wider than
nominal. If the bottom of the part has to fit into something, take a 0.5 mm chamfer along
the bottom contour.

## Threads and fasteners

Printed threads work poorly and wear loose.

Take the dimensions of screws, nuts and bearings from `bd_warehouse`, and the clearance
around them from `forge` (examples in `build123d.md`). In descending order of reliability:

1. **a brass heat-set insert** pushed in with a soldering iron — the best option; PETG
   holds one very well, PLA less so (it softens). The hole for the insert follows its
   specification, usually 0.1 mm smaller;
2. **a nut in a pocket** — a hex pocket for the nut, the screw passing through;
3. **a self-tapping screw into a blind hole** — diameter about 0.8 of the screw's outer
   diameter;
4. **a tap run into a printed hole** — holds, but for a couple of assemblies;
5. a printed thread — only for a coarse pitch and a light load.

## Snap fits and springs

PLA is brittle and snap fits break on it: make them long and thin so the deformation is
spread out. PETG is ductile and takes far more — use it for snap fits.

The print direction is critical: a snap fit must bend **across the layers, not along
them**, or it will snap off along the bond line.

## Orientation

Layers carry load worse than the plane of a layer does. Orient the part so tensile load
runs **along the layers**, not across them.

A tall narrow part on the A1 mini is a risk: the bed travels in Y and the inertia tears
the part off. `check.py` computes the centre of mass and warns when a part will tip over
or when it needs a brim.

It also searches through orientations and suggests the one with the fewest unsupported
overhangs — as a recommendation: turning the part changes both the strength (layers) and
which face ends up on the bed, so the last word belongs to the human.

## Large parts

Does not fit in 180×180×180 — split it and join the pieces:

- **a tenon and mortise** with `clearance(MAT, "snug")`;
- **a dovetail** — holds without glue;
- **screws through a flange** — demountable;
- glue: cyanoacrylate works well on PLA and PETG, and PLA also takes dichloromethane.

The diagonal of the bed fits more than its side — sometimes turning the part is enough.

## Materials: which to choose

| | PLA | PETG |
|---|---|---|
| Stiffness | higher | lower |
| Brittleness | brittle | ductile |
| Heat resistance | to ~55 °C | to ~75 °C |
| Printing | easy | harder, it strings |
| Overhangs and bridges | better | worse |
| Heat-set inserts | so-so | good |
| Outdoors, sunlight | degrades | holds up better |

The rule: **PLA by default**, PETG when the part gets hot, takes impact, lives outdoors or
carries snap fits.

Neither ABS, nor ASA, nor PLA-CF will run on this printer — there is no enclosure and no
hardened nozzle.
