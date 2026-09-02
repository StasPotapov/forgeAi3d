"""A smoke-test part: a 40x24x6 plate with two M3 holes, rounded corners and a chamfer
along the top contour."""
from build123d import *

from forge import clearance, export_all

MAT = "PETG"

L, W, H = 40.0, 24.0, 6.0
M3 = 3.0
HOLE_DX = 13.0        # offset of the holes from the centre along X

hole_d = M3 + 2 * clearance(MAT, "free")   # a clearance hole, the screw has to pass freely

with BuildPart() as part:
    with BuildSketch() as plan:
        Rectangle(L, W)
        fillet(plan.vertices(), radius=5.0)
    extrude(amount=H)

    with Locations((-HOLE_DX, 0), (HOLE_DX, 0)):
        Hole(radius=hole_d / 2)

    chamfer(part.faces().sort_by(Axis.Z)[-1].edges(), length=0.8)

paths = export_all(part.part, "smoke_test", material=MAT)

print(f"material   {MAT}")
print(f"hole       {hole_d:.2f} mm for an M{M3:.0f} screw")
print(f"volume     {part.part.volume:.1f} mm³")
bb = part.part.bounding_box()
print(f"size       {bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} mm")
print(f"files      {', '.join(str(v.name) for v in paths.values())}")
