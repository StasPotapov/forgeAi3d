"""Проверочная деталь: пластина 40x24x6 с двумя отверстиями под M3,
скруглёнными углами и фаской по верхнему контуру."""
from build123d import *

from forge import clearance, export_all

MAT = "PETG"

L, W, H = 40.0, 24.0, 6.0
M3 = 3.0
HOLE_DX = 13.0        # смещение отверстий от центра по X

hole_d = M3 + 2 * clearance(MAT, "free")   # проходное, винт должен входить свободно

with BuildPart() as part:
    with BuildSketch() as plan:
        Rectangle(L, W)
        fillet(plan.vertices(), radius=5.0)
    extrude(amount=H)

    with Locations((-HOLE_DX, 0), (HOLE_DX, 0)):
        Hole(radius=hole_d / 2)

    chamfer(part.faces().sort_by(Axis.Z)[-1].edges(), length=0.8)

paths = export_all(part.part, "smoke_test", material=MAT)

print(f"материал   {MAT}")
print(f"отверстие  {hole_d:.2f} мм под винт M{M3:.0f}")
print(f"объём      {part.part.volume:.1f} мм³")
bb = part.part.bounding_box()
print(f"габариты   {bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} мм")
print(f"файлы      {', '.join(str(v.name) for v in paths.values())}")
