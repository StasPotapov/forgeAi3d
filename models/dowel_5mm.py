"""Мебельный дюбель (анкер) под шуруп 3.5x15 в отверстие 5 мм.

Втулка-ёлочка: забивается в отверстие ДСП, кольцевые зубцы впиваются в стенку
и не дают вылезти обратно; шуруп нарезает резьбу в вязком PETG и распирает
втулку изнутри. Классических распорных лепестков нет намеренно — при стенке
около 1 мм печатные лепестки ломаются по слоям. Прорезь включается флагом SLOT.

Печатать стоя (ось дюбеля вертикально), как деталь и построена.
"""
from build123d import *

from forge import clearance, export_all, wall

MAT = "PETG"          # вязкий: держит резьбу шурупа и не лопается от распора

# --- размеры чужого железа: сказаны пользователем, не выдуманы ---
HOLE_D     = 5.0      # отверстие в мебели
HOLE_DEPTH = 11.0     # рабочая глубина посадки; укорочено с 15 — по примерке было длинно
SCREW_D    = 3.5      # диаметр резьбовой части шурупа
SCREW_L    = 15.0     # длина шурупа
HEAD_D     = 7.0      # шляпка — фланец делаем заведомо меньше, чтобы она его накрыла

# --- что крутится по итогам печати ---
PILOT_TOP  = 2.8      # внутреннее отверстие сверху: 0.8 * SCREW_D
PILOT_BOT  = 2.2      # снизу уже — шуруп идёт всё туже и распирает втулку
BARB_OVER  = 0.20     # выступ зубца за тело, на сторону
BARB_RISE  = 1.7      # высота конуса зубца
BARB_PITCH = 3.0      # шаг зубцов
BARB_FIRST = 2.0      # где начинается первый зубец
FLANGE_D   = 6.0      # бортик: не даёт провалиться, прячется под шляпкой 7 мм
FLANGE_H   = 0.7
LEAD_IN    = 0.5      # заходная фаска снизу, по радиусу
CHAMFER_TOP = 0.3     # заходная фаска под шуруп сверху
SLOT       = False    # True — сквозная прорезь по диаметру (классический распорный)
SLOT_W     = 0.9
SLOT_FRAC  = 0.65     # какую долю длины режет прорезь

BODY_R = (HOLE_D - 2 * clearance(MAT, "press")) / 2   # запрессовка в 5 мм
BARB_R = BODY_R + BARB_OVER
FLANGE_RISE = FLANGE_D / 2 - BODY_R                   # конус под фланцем ровно 45°
TOP_Z = HOLE_DEPTH + FLANGE_RISE + FLANGE_H

_min_wall = BODY_R - PILOT_TOP / 2
assert _min_wall >= wall(2), f"стенка {_min_wall:.2f} тоньше двух периметров {wall(2)}"
assert FLANGE_D < HEAD_D, "бортик должен прятаться под шляпкой шурупа"

# профиль в осевом сечении: (радиус, высота), обход по внешнему контуру снизу вверх
pts: list[tuple[float, float]] = [
    (PILOT_BOT / 2, 0.0),          # дно, внутренняя кромка
    (BODY_R - LEAD_IN, 0.0),       # дно, наружная кромка
    (BODY_R, LEAD_IN),             # конец заходной фаски
]

z = BARB_FIRST
while z + BARB_RISE <= HOLE_DEPTH - 1.0:
    pts += [
        (BODY_R, z),               # подошва зубца
        (BARB_R, z + BARB_RISE),   # вершина: пологий конус, дюбель входит легко
        (BODY_R, z + BARB_RISE),   # обратная ступенька — цепляется при выдёргивании
    ]
    z += BARB_PITCH

pts += [
    (BODY_R, HOLE_DEPTH),
    (FLANGE_D / 2, HOLE_DEPTH + FLANGE_RISE),   # конус 45°, печатается без поддержки
    (FLANGE_D / 2, TOP_Z),
    (PILOT_TOP / 2 + CHAMFER_TOP, TOP_Z),
    (PILOT_TOP / 2, TOP_Z - CHAMFER_TOP),       # дальше замыкание вниз = конус отверстия
]

with BuildPart() as dowel:
    with BuildSketch(Plane.XZ):
        with BuildLine():
            Polyline(*pts, close=True)
        make_face()
    revolve(axis=Axis.Z)

    if SLOT:
        Box(SLOT_W, 2 * BARB_R + 2, HOLE_DEPTH * SLOT_FRAC,
            align=(Align.CENTER, Align.CENTER, Align.MIN), mode=Mode.SUBTRACT)

paths = export_all(dowel.part, "dowel_5mm", material=MAT)
print(f"дюбель {HOLE_D} мм под шуруп {SCREW_D}x{SCREW_L}: "
      f"высота {TOP_Z:.2f}, посадка {HOLE_DEPTH}, стенка {_min_wall:.2f}")
for k, v in paths.items():
    print(f"  {k}: {v}")
