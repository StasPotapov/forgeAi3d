#!/usr/bin/env python3
"""Численный обмер детали по STEP.

    uv run tools/measure.py prints/part/part.stl [--json]

Превью показывает, что деталь похожа на задуманное; обмер отвечает, совпадают ли
размеры. Рендер выглядит правильным и при неверной геометрии, поэтому сверяться
надо числами, а глазами — уже потом.

Отверстия, штыри, скругления и галтели узнаются по цилиндрическим граням:
вогнутая поверхность (материал снаружи) — отверстие, выпуклая — штырь, а неполный
обхват означает, что это не круг, а скругление угла.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from build123d import Vector, import_step

from forge import find_step

# OCP — геометрическое ядро самого build123d, отдельной зависимостью его объявлять
# нечего: без него build123d не импортируется. Радиус даёт и build123d (Face.radius),
# а вот ось цилиндра только отсюда.
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_SurfaceType

FULL_WRAP = 5.5      # рад; больше этого обхвата поверхность считается полным кругом
PROBE = 0.05         # на сколько отойти от поверхности, чтобы понять, где материал
PROBE_RADIUS = 0.75  # доля радиуса: где смотреть за торцом, чтобы не попасть в пилот


def cylinders(shape, solids) -> list[dict]:
    """Разбор цилиндрических граней: что это, какого размера и где."""
    found = []
    for face in shape.faces():
        adaptor = BRepAdaptor_Surface(face.wrapped)
        if adaptor.GetType() != GeomAbs_SurfaceType.GeomAbs_Cylinder:
            continue
        cyl = adaptor.Cylinder()
        radius = cyl.Radius()
        axis = cyl.Axis()
        origin = Vector(axis.Location().X(), axis.Location().Y(), axis.Location().Z())
        direction = Vector(axis.Direction().X(), axis.Direction().Y(), axis.Direction().Z())

        centre = face.center()
        offset = centre - origin
        along = offset.dot(direction)
        radial = offset - direction * along
        if radial.length < 1e-9:
            continue
        unit = radial.normalized()

        outside = origin + unit * (radius + PROBE) + direction * along
        inside = origin + unit * (radius - PROBE) + direction * along
        # пробуем по всем телам: у компаунда грань принадлежит любому из них
        if any(body.is_inside(outside) for body in solids):
            concave = True          # материал дальше от оси — это дырка
        elif any(body.is_inside(inside) for body in solids):
            concave = False         # материал ближе к оси — это столбик
        else:
            continue                # тонкая стенка, обе пробы мимо — не гадаем

        face_bb = face.bounding_box()
        length = max(
            abs(face_bb.size.X * direction.X),
            abs(face_bb.size.Y * direction.Y),
            abs(face_bb.size.Z * direction.Z),
        )
        wrap = face.area / (radius * length) if radius * length else 0.0

        if wrap >= FULL_WRAP:
            kind = "отверстие" if concave else "штырь"
        else:
            kind = "галтель" if concave else "скругление"

        dominant = max(("X", direction.X), ("Y", direction.Y), ("Z", direction.Z),
                       key=lambda pair: abs(pair[1]))[0]

        # сквозное или глухое: выходим за оба торца цилиндра и смотрим, осталось
        # ли там тело. Сравнивать длину с габаритом детали нельзя — фаска или
        # выступающая надпись сдвигают габарит и врут про сквозное.
        #
        # Проба ставится не на оси, а ближе к стенке: у цековки на оси за дальним
        # торцом начинается пилотное отверстие — тоже пустота, и отверстие
        # выглядело бы сквозным. На радиусе 0.75R там уже материал.
        side = unit * (radius * PROBE_RADIUS)
        ends = [
            origin + direction * (along + length / 2 + PROBE) + side,
            origin + direction * (along - length / 2 - PROBE) + side,
        ]
        through = kind == "отверстие" and not any(
            body.is_inside(end) for end in ends for body in solids
        )

        found.append({
            "kind": kind,
            "diameter": round(radius * 2, 3),
            "radius": round(radius, 3),
            "length": round(length, 3),
            "axis": dominant,
            "through": through,
            # round даёт -0.0, а «-0» в отчёте выглядит как ошибка
            "centre": [round(v, 2) + 0.0 or 0.0 for v in (origin.X, origin.Y, origin.Z)],
        })
    return found


def group(items: list[dict]) -> list[dict]:
    """Одинаковые элементы схлопываются в один с количеством."""
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for item in items:
        buckets[(item["kind"], item["diameter"], item["length"], item["axis"],
                 item["through"])].append(item)
    out = []
    for items_ in buckets.values():
        head = dict(items_[0])
        head["count"] = len(items_)
        head["centres"] = [i["centre"] for i in items_]
        head.pop("centre")
        out.append(head)
    return sorted(out, key=lambda i: (i["kind"], -i["diameter"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model", type=Path, help="STEP или STL детали (STEP найдётся сам)")
    ap.add_argument("--json", action="store_true", help="машиночитаемый вывод")
    args = ap.parse_args()

    if not args.model.exists():
        sys.exit(f"нет файла {args.model}")

    step = find_step(args.model)
    if step is None:
        sys.exit("обмер идёт по STEP — у меша нет ни граней, ни осей отверстий, "
                 f"а STEP рядом с {args.model.name} не нашёлся")

    try:
        shape = import_step(str(step))
    except Exception as exc:
        sys.exit(f"не удалось прочитать {step}: {exc}")

    solids = shape.solids()
    if not solids:
        sys.exit("в файле нет ни одного тела")

    bbox = shape.bounding_box()
    faces = shape.faces()
    types = defaultdict(int)
    for face in faces:
        types[str(face.geom_type).removeprefix("GeomType.")] += 1

    items = group(cylinders(shape, solids))

    if args.json:
        print(json.dumps({
            "file": str(step),
            "size": [round(bbox.size.X, 3), round(bbox.size.Y, 3), round(bbox.size.Z, 3)],
            "volume": round(shape.volume, 1),
            "solids": len(solids),
            "faces": len(faces),
            "face_types": dict(types),
            "features": items,
        }, ensure_ascii=False, indent=2))
        return

    print(f"файл       {step}")
    print(f"габариты   {bbox.size.X:.2f} x {bbox.size.Y:.2f} x {bbox.size.Z:.2f} мм")
    print(f"объём      {shape.volume / 1000:.2f} см³")
    print(f"тел        {len(solids)}")
    print(f"граней     {len(faces)}  ({', '.join(f'{k.lower()} {v}' for k, v in sorted(types.items()))})")

    if not items:
        print("\nкруглых элементов не найдено")
        return

    print("\nЭлементы:")
    for item in items:
        count = f"{item['count']} × " if item["count"] > 1 else ""
        if item["kind"] in ("отверстие", "штырь"):
            size = f"Ø{item['diameter']:.2f}"
            depth = "насквозь" if item["through"] else f"глубина {item['length']:.2f}"
            # координаты поперёк оси: вдоль неё у отверстия координаты нет
            across = [i for i, name in enumerate("XYZ") if name != item["axis"]]
            where = "; ".join(
                f"({c[across[0]]:g}, {c[across[1]]:g})" for c in item["centres"][:6]
            )
            more = " …" if len(item["centres"]) > 6 else ""
            labels = "".join("XYZ"[i] for i in across)
            print(f"  {count}{item['kind']} {size}, {depth}, ось {item['axis']}")
            print(f"      центры ({labels}): {where}{more}")
        else:
            print(f"  {count}{item['kind']} R{item['radius']:.2f}, длина {item['length']:.2f}, ось {item['axis']}")


if __name__ == "__main__":
    main()
