# build123d — шпаргалка

Всё ниже проверено на живом коде (build123d 0.11.1, Python 3.14, macOS arm64).
Работать из `~/dev/forgeAi3d`, запускать через `uv run python models/деталь.py`.

## Скелет файла модели

```python
"""Что за деталь и для чего."""
from pathlib import Path
from build123d import *
from forge import clearance, wall, compensate_shrink

MAT = "PETG"
OUT = Path(__file__).resolve().parent.parent / "out"

# --- параметры, которые крутятся по итогам печати ---
L, W, H = 40.0, 24.0, 6.0
SCREW   = 3.0            # M3
WALL    = wall(3)

with BuildPart() as part:
    Box(L, W, H)
    Hole(radius=(SCREW + 2 * clearance(MAT, "free")) / 2)

OUT.mkdir(parents=True, exist_ok=True)
for path, writer in ((OUT / "деталь.stl", export_stl), (OUT / "деталь.step", export_step)):
    if not writer(part.part, str(path)):    # оба возвращают bool, исключений НЕ бросают
        raise RuntimeError(f"не удалось записать {path}")
```

## Примитивы

```python
Box(l, w, h)                    Cylinder(radius=r, height=h)
Cone(bottom_radius=a, top_radius=b, height=h)   # top_radius=0 даёт негерметичный STL, бери 0.5
Sphere(radius=r)                Torus(major_radius=R, minor_radius=r)
Wedge(...)
```

Выравнивание — третий аргумент `align`, по умолчанию центр по всем осям:

```python
Box(30, 30, 0.6, align=(Align.CENTER, Align.CENTER, Align.MIN))   # низом на плоскость
```

## Эскиз и выдавливание

```python
with BuildPart() as p:
    with BuildSketch() as plan:          # BuildSketch(Plane.XZ) — эскиз в другой плоскости
        Rectangle(L, W)
        fillet(plan.vertices(), radius=5)
    extrude(amount=H)
```

Плоские примитивы: `Rectangle`, `RectangleRounded`, `Circle`, `RegularPolygon`,
`SlotOverall`, `Text(txt, font_size=)`, `Polyline`, `Line`, `ThreePointArc`.

## Отверстия и размещение

```python
Hole(radius=r, depth=None)                          # depth=None — насквозь
CounterBoreHole(radius=, counter_bore_radius=, counter_bore_depth=)
CounterSinkHole(radius=, counter_sink_radius=)      # под потайной винт

with Locations((-13, 0), (13, 0)):     # произвольные точки
    Hole(radius=2)
with GridLocations(30, 30, 2, 2):      # сетка: шаг X, шаг Y, кол-во X, кол-во Y
    CounterSinkHole(radius=1.7, counter_sink_radius=3.2)
with PolarLocations(radius=20, count=6):
    Hole(radius=1.5)
```

## Селекторы — как достать нужные рёбра и грани

```python
part.faces().sort_by(Axis.Z)[-1]           # верхняя грань
part.faces().sort_by(Axis.Z)[0]            # нижняя
part.edges().filter_by(Axis.Z)             # все вертикальные рёбра
part.edges().filter_by(Axis.X).sort_by(Axis.Z)[-1]   # верхнее ребро вдоль X
part.faces().sort_by(Axis.Z)[-1].edges()   # рёбра верхней грани
```

Дальше их скругляют или снимают фаску:

```python
fillet(part.edges().filter_by(Axis.Z), radius=3)
chamfer(part.faces().sort_by(Axis.Z)[-1].edges(), length=0.8)
```

## Оболочка, вращение, вычитание

```python
# корпус со стенкой 1.26 мм, открытый сверху
with BuildPart() as case:
    Box(40, 30, 20)
    offset(amount=-1.26, openings=case.faces().sort_by(Axis.Z)[-1])

# тело вращения из профиля
with BuildPart() as rev:
    with BuildSketch(Plane.XZ):
        Rectangle(10, 20, align=(Align.MIN, Align.MIN))
    revolve(axis=Axis.Z)

# вычесть произвольное тело
Cylinder(radius=5, height=50, mode=Mode.SUBTRACT)
```

Ещё есть `loft`, `sweep`, `mirror`, `split`, `scale`, `add`.

## Импорт и экспорт

| Функция | Отдаёт | Годится для |
|---|---|---|
| `import_step(path)` | `Solid` для одного тела, `Compound` для нескольких | полноценная правка, булевы операции |
| `import_stl(path)` | **`Face`** | только показать; булевы операции НЕ пройдут |
| `export_step(part, path)` | **`bool`** | обмен, дальнейшие правки |
| `export_stl(part, path)` | **`bool`** | печать |

Тела из импортированного STEP достаются через `.solids()` — так работает и для `Solid`,
и для `Compound`, не надо гадать что вернулось.

**Оба экспорта возвращают `bool` и не бросают исключений.** При ошибке они молча вернут
`False` и ничего не запишут — старый файл останется на диске и уйдёт в печать как свежий.
Проверять возврат обязательно.

## Правка чужих мешей — trimesh

build123d для STL не годится. Меши правятся через trimesh (`manifold3d` стоит,
булевы операции работают):

```python
import numpy as np
import trimesh

m = trimesh.load_mesh("out/чужая.stl")
if isinstance(m, trimesh.Scene):
    m = m.to_mesh()

m.apply_scale(1.05)                                  # увеличить на 5%
m.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [1,0,0]))
m.apply_translation([0, 0, -m.bounds[0][2]])         # посадить на стол

cutter = trimesh.creation.cylinder(radius=4, height=100)
m = trimesh.boolean.difference([m, cutter])          # просверлить
m = trimesh.boolean.union([m, plate])                # приварить

trimesh.repair.fill_holes(m)                         # починить дыры
trimesh.repair.fix_normals(m)
m.export("out/правленая.stl")
```

Разрез плоскостью — `m.slice_plane(origin, normal)`. Отдельные тела — `m.split()`.

## Грабли

- `Cone(top_radius=0)` даёт вырожденный треугольник в вершине и негерметичный STL —
  бери `top_radius=0.5` или строй вращением.
- Тела, соприкасающиеся ровно гранью, сливаются в одно — проверено, перекрытие для этого
  не нужно. А вот тела с зазором остаются раздельными и молча уезжают в STL двумя кусками:
  на это смотри строку «тел в файле» в выводе `check.py`.
- `from build123d import *` тянет много имён, но `pathlib.Path` не затеняет — проверено.
- Относительные пути в экспорте считаются от CWD. Всегда строй путь от `__file__`.
- `part` внутри `with BuildPart() as part` — это билдер; тело достаётся как `part.part`.
