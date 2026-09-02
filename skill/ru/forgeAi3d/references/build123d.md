# build123d — шпаргалка

Всё ниже проверено на живом коде (build123d 0.11.1, bd_warehouse 0.3.0, Python 3.14,
macOS arm64). Работать из корня репозитория (`$FORGEAI3D_HOME`, по умолчанию
`~/dev/forgeAi3d`), запускать через `uv run python models/деталь.py`.

## Скелет файла модели

```python
"""Что за деталь и для чего."""
from build123d import *
from forge import clearance, export_all, wall, compensate_shrink

MAT = "PETG"

# --- параметры, которые крутятся по итогам печати ---
L, W, H = 40.0, 24.0, 6.0
SCREW   = 3.0            # M3
WALL    = wall(3)

with BuildPart() as part:
    Box(L, W, H)
    Hole(radius=(SCREW + 2 * clearance(MAT, "free")) / 2)

# prints/деталь/деталь.stl, остальное в prints/деталь/extras/; запись проверена
paths = export_all(part.part, "деталь", material=MAT)
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
| `export_step(part, path)` | **`bool`** | обмен, дальнейшие правки, точный анализ в check.py |
| `export_stl(part, path)` | **`bool`** | печать |
| `export_all(part, stem, material=)` | `dict` путей | обычный способ: сразу stl + step + 3mf |

Тела из импортированного STEP достаются через `.solids()` — так работает и для `Solid`,
и для `Compound`, не надо гадать что вернулось.

**Оба экспорта возвращают `bool` и не бросают исключений.** При ошибке они молча вернут
`False` и ничего не запишут — старый файл останется на диске и уйдёт в печать как свежий.
Проверять возврат обязательно; `export_all` из `forge` это уже делает.

3MF пишется классом `Mesher` из build123d — он единственный несёт единицы измерения
и метаданные, поэтому Bambu Studio открывает такую деталь сразу в миллиметрах:

```python
from build123d import Mesher, Unit
mesher = Mesher(unit=Unit.MM)
mesher.add_shape(part.part, part_number="деталь")
mesher.add_meta_data("forgeAi3d", "material", "PETG", "str", True)
mesher.write("prints/деталь.3mf")
```

## Готовый крепёж — bd_warehouse

Размеры винтов, гаек, подшипников и резьб берутся из стандарта, а не из головы.
Зазор к ним добавляется свой: у библиотеки посадки машиностроительные, под FDM они тесны.

```python
from bd_warehouse.fastener import HexNut, SocketHeadCapScrew
from bd_warehouse.bearing import SingleRowDeepGrooveBallBearing as Bearing
from bd_warehouse.thread import IsoThread

SocketHeadCapScrew.sizes("iso4762")      # ['M1.6-0.35', 'M2-0.4', 'M2.5-0.45', 'M3-0.5', ...]

screw = SocketHeadCapScrew(size="M3-0.5", length=12, fastener_type="iso4762")
screw.head_diameter                       # 5.68 — под потай или карман головки
screw.head_height                         # 3.0

nut = HexNut(size="M3-0.5", fastener_type="iso4032")
nut.nut_diameter                          # 6.35 — диаметр ПО УГЛАМ (e), не под ключ
nut.bounding_box().size.Y                 # 5.50 — вот это под ключ (s)
nut.nut_thickness                         # 2.4

bearing = Bearing(size="M8-22-7", bearing_type="SKT")   # 608
bearing.outer_diameter, bearing.bore_diameter           # 22, 8
```

Карман под гайку — шестигранник по размеру гайки плюс посадка из `forge`. Тут легко
ошибиться дважды: `nut_diameter` это диаметр **по углам**, и `RegularPolygon` по
умолчанию тоже считает `radius` апофемой, а не радиусом по углам. Ошибиться в обоих
местах сразу — карман на миллиметр шире нужного, и гайка в нём проворачивается.

```python
pocket = nut.nut_diameter + 2 * clearance(MAT, "snug")     # 6.65 по углам, для PETG
with BuildPart() as p:
    Box(24, 24, 10)
    with BuildSketch(Plane.XY.offset(5)):
        RegularPolygon(radius=pocket / 2, side_count=6, major_radius=True)   # ПО УГЛАМ
    extrude(amount=-(nut.nut_thickness + 0.2), mode=Mode.SUBTRACT)   # +0.2 на посадку по высоте
    Hole(radius=(3 + 2 * clearance(MAT, "free")) / 2)
```

Проверено замером выемки: 6.65 × 5.76 мм против гайки 6.35 × 5.50 — по 0.15 мм на
сторону, как и просили у `clearance`. С `major_radius=False` получилось бы 7.33 мм.

Гнездо под подшипник — запрессовка: `bearing.outer_diameter + 2 * clearance(MAT, "press")`.

Резьба — это только винтовая нарезка, её надо посадить на стержень:

```python
thread = IsoThread(major_diameter=8, pitch=1.25, length=10,
                   external=True, end_finishes=("fade", "fade"))
with BuildPart() as bolt:
    Cylinder(radius=thread.min_radius, height=10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    add(thread)
```

`thread.is_valid` — свойство, а не метод. Печатная резьба разбалтывается: под нагрузку
бери термовставку или гайку в кармане, см. `design-rules.md`.

## Правка чужих мешей — trimesh

build123d для STL не годится. Меши правятся через trimesh (`manifold3d` стоит,
булевы операции работают):

```python
import numpy as np
import trimesh

m = trimesh.load_mesh("prints/чужая.stl")
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
m.export("prints/правленая.stl")
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
