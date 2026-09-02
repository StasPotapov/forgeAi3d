"""Clearance calibration comb for an M3 screw.

Printed once per filament, to replace the typical clearances in forge/spec.py with real
ones. After printing, put an M3 screw into every hole and find two numbers: the one where
the screw goes in with hand force (that is snug) and the one where it slides freely with
no play (that is slip). Write the resulting clearances into the clearances of that
material.

Hole N has a clearance of STEP*N per side, that is a diameter of SCREW + 2*STEP*N. The
range covers all four fits of both filaments: from press (0.00) to free (0.45).
"""
from build123d import *

from forge import export_all

MAT = "PLA"          # printed separately for each filament; the file name reflects it
SCREW = 3.0          # nominal diameter of an M3 screw
COUNT = 10           # holes: clearances 0.00 ... 0.45
STEP = 0.05          # clearance step per side, mm
PITCH = 12.0         # distance between holes
PLATE_H = 3.0        # plate thickness
MARGIN = 8.0         # margin on the left and on the right
LABEL_H = 10.0       # digit size; the glyph comes out ~7.3 mm, stroke >= 0.8 mm = 2 perimeters
MAT_LABEL_H = 6.0    # size of the material label
EMBOSS = 0.6         # how far the labels stand out (3 layers of 0.2)
EDGE = 3.0           # margin at the top and at the bottom
ROW_GAP = 2.5        # gap between rows

# the glyph height of the default font is about 73% of the size — measured
GLYPH = 0.73
HOLE_R_MAX = (SCREW + 2 * STEP * (COUNT - 1)) / 2

# vertical layout from the bottom up: margin, material, row of digits, row of holes, margin
mat_h = MAT_LABEL_H * GLYPH
label_h = LABEL_H * GLYPH
L = PITCH * (COUNT - 1) + 2 * MARGIN
W = 2 * EDGE + mat_h + ROW_GAP + label_h + ROW_GAP + 2 * HOLE_R_MAX

y_bottom = -W / 2
y_mat = y_bottom + EDGE + mat_h / 2
y_label = y_bottom + EDGE + mat_h + ROW_GAP + label_h / 2
y_hole = W / 2 - EDGE - HOLE_R_MAX
x0 = -PITCH * (COUNT - 1) / 2

with BuildPart() as part:
    with BuildSketch() as plan:
        Rectangle(L, W)
        fillet(plan.vertices(), radius=3.0)
    extrude(amount=PLATE_H)

    # the row of holes with a growing clearance
    for i in range(COUNT):
        with Locations((x0 + i * PITCH, y_hole)):
            Hole(radius=(SCREW + 2 * STEP * i) / 2)

    # the hole number and the material label are raised, so they read on any colour
    with BuildSketch(Plane.XY.offset(PLATE_H)):
        for i in range(COUNT):
            with Locations((x0 + i * PITCH, y_label)):
                Text(str(i), font_size=LABEL_H)
        with Locations((0, y_mat)):
            Text(f"{MAT}  x0.05mm", font_size=MAT_LABEL_H)
    extrude(amount=EMBOSS)

    # a chamfer along the bottom contour against elephant foot
    chamfer(part.faces().sort_by(Axis.Z)[0].edges(), length=0.5)

stem = f"fit_test_{MAT.lower().replace('-', '_')}"
paths = export_all(part.part, stem, material=MAT)

bb = part.part.bounding_box()
print(f"material   {MAT}")
print(f"plate      {bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} mm")
print(f"files      {', '.join(str(v.name) for v in paths.values())}")
for i in range(COUNT):
    print(f"  {i}: clearance {STEP * i:.2f} per side -> hole {SCREW + 2 * STEP * i:.2f} mm")
