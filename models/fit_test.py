"""Калибровочная гребёнка зазоров под винт M3.

Печатается по разу на каждый пластик, чтобы заменить типовые зазоры в forge/spec.py
на реальные. После печати вставить винт M3 в каждое отверстие и найти два номера:
где винт входит с усилием руки (это snug) и где ходит свободно без люфта (это slip).
Полученные зазоры вписать в clearances нужного материала.

Отверстие N имеет зазор STEP*N на сторону, то есть диаметр SCREW + 2*STEP*N.
Диапазон покрывает все четыре посадки обоих пластиков: от press (0.00) до free (0.45).
"""
from pathlib import Path

from build123d import *

OUT = Path(__file__).resolve().parent.parent / "out"

MAT = "PLA"          # печатается отдельно под каждый пластик, имя файла это учитывает
SCREW = 3.0          # номинальный диаметр винта M3
COUNT = 10           # отверстий: зазоры 0.00 ... 0.45
STEP = 0.05          # шаг зазора на сторону, мм
PITCH = 12.0         # расстояние между отверстиями
PLATE_H = 3.0        # толщина пластины
MARGIN = 8.0         # поле слева и справа
LABEL_H = 10.0       # кегль цифры; глиф выходит ~7.3 мм, штрих >= 0.8 мм = 2 периметра
MAT_LABEL_H = 6.0    # кегль подписи материала
EMBOSS = 0.6         # на сколько выступают надписи (3 слоя по 0.2)
EDGE = 3.0           # поле сверху и снизу
ROW_GAP = 2.5        # просвет между рядами

# высота глифа у дефолтного шрифта — примерно 73% кегля, замерено
GLYPH = 0.73
HOLE_R_MAX = (SCREW + 2 * STEP * (COUNT - 1)) / 2

# компоновка по вертикали снизу вверх: поле, материал, ряд цифр, ряд отверстий, поле
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

    # ряд отверстий с нарастающим зазором
    for i in range(COUNT):
        with Locations((x0 + i * PITCH, y_hole)):
            Hole(radius=(SCREW + 2 * STEP * i) / 2)

    # номер отверстия и подпись материала — выступающими, чтобы читались на любом цвете
    with BuildSketch(Plane.XY.offset(PLATE_H)):
        for i in range(COUNT):
            with Locations((x0 + i * PITCH, y_label)):
                Text(str(i), font_size=LABEL_H)
        with Locations((0, y_mat)):
            Text(f"{MAT}  x0.05mm", font_size=MAT_LABEL_H)
    extrude(amount=EMBOSS)

    # фаска по нижнему контуру против elephant foot
    chamfer(part.faces().sort_by(Axis.Z)[0].edges(), length=0.5)

OUT.mkdir(parents=True, exist_ok=True)
stem = f"fit_test_{MAT.lower().replace('-', '_')}"
for path, writer in ((OUT / f"{stem}.stl", export_stl), (OUT / f"{stem}.step", export_step)):
    if not writer(part.part, str(path)):
        raise RuntimeError(f"не удалось записать {path}")

bb = part.part.bounding_box()
print(f"материал   {MAT}")
print(f"пластина   {bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} мм")
print(f"файл       out/{stem}.stl")
for i in range(COUNT):
    print(f"  {i}: зазор {STEP * i:.2f} на сторону -> отверстие {SCREW + 2 * STEP * i:.2f} мм")
