"""Проверочная деталь: пластина 40x24x6 с двумя отверстиями под M3,
скруглёнными углами и фаской по верхнему контуру."""
from pathlib import Path

from build123d import *

from forge import clearance

MAT = "PETG"
OUT = Path(__file__).resolve().parent.parent / "out"

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

OUT.mkdir(parents=True, exist_ok=True)
stl = OUT / "smoke_test.stl"
if not export_stl(part.part, str(stl)):
    raise RuntimeError(f"не удалось записать {stl}")
export_step(part.part, str(OUT / "smoke_test.step"))

print(f"материал   {MAT}")
print(f"отверстие  {hole_d:.2f} мм под винт M{M3:.0f}")
print(f"объём      {part.part.volume:.1f} мм³")
bb = part.part.bounding_box()
print(f"габариты   {bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} мм")
