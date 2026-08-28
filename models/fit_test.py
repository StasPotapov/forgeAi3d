"""Калибровочная гребёнка зазоров под винт M3.

Печатается один раз на каждый пластик, чтобы заменить типовые зазоры в forge/spec.py
на реальные. После печати вставить винт M3 в каждое отверстие и найти два:
первое, куда винт входит с усилием руки (это snug), и первое, где он ходит
свободно без люфта (это slip). Номер отверстия подписан рядом.

Отверстие N имеет зазор STEP*N на сторону, то есть диаметр 3.0 + 2*STEP*N.
"""
from pathlib import Path

from build123d import *

OUT = Path(__file__).resolve().parent.parent / "out"

SCREW = 3.0          # номинальный диаметр винта M3
COUNT = 6            # количество отверстий
STEP = 0.05          # шаг зазора на сторону, мм
PITCH = 12.0         # расстояние между отверстиями
PLATE_H = 3.0        # толщина пластины
MARGIN = 8.0         # поле по краям
LABEL_H = 7.5        # высота цифры (мельче 7 мм штрих не пропечатывается соплом 0.4)
LABEL_DEPTH = 0.6    # на сколько цифра выступает

L = PITCH * (COUNT - 1) + 2 * MARGIN
W = 22.0

with BuildPart() as part:
    with BuildSketch() as plan:
        Rectangle(L, W)
        fillet(plan.vertices(), radius=3.0)
    extrude(amount=PLATE_H)

    # ряд отверстий с нарастающим зазором
    x0 = -PITCH * (COUNT - 1) / 2
    for i in range(COUNT):
        gap = STEP * (i + 1)
        with Locations((x0 + i * PITCH, 4.0)):
            Hole(radius=(SCREW + 2 * gap) / 2)

    # подписи: номер отверстия, по нему считается зазор
    with BuildSketch(Plane.XY.offset(PLATE_H)) as labels:
        for i in range(COUNT):
            with Locations((x0 + i * PITCH, -6.0)):
                Text(str(i + 1), font_size=LABEL_H)
    extrude(amount=LABEL_DEPTH)

    # фаска по нижнему контуру против elephant foot
    chamfer(part.faces().sort_by(Axis.Z)[0].edges(), length=0.5)

OUT.mkdir(parents=True, exist_ok=True)
stl = OUT / "fit_test.stl"
if not export_stl(part.part, str(stl)):
    raise RuntimeError(f"не удалось записать {stl}")
export_step(part.part, str(OUT / "fit_test.step"))

print(f"пластина   {L:.0f} x {W:.0f} x {PLATE_H:.0f} мм")
for i in range(COUNT):
    gap = STEP * (i + 1)
    print(f"  {i + 1}: зазор {gap:.2f} на сторону -> отверстие {SCREW + 2 * gap:.2f} мм")
