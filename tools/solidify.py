#!/usr/bin/env python3
"""Заливка внутренней полости в чужом меше.

    uv run tools/solidify.py входной.stl                     # что внутри — только показать
    uv run tools/solidify.py входной.stl --fill 1     # залить пустоту №1

Полая модель (труба, вазовый режим, отсканированная скорлупа) печатается пустой:
слайсер честно видит полость и не кладёт внутрь инфилл. Здесь внутренняя оболочка
удаляется, оставшаяся дыра заклеивается — получается сплошное тело, заполнением
которого распоряжается слайсер.

Внешняя геометрия не трогается: берутся ровно исходные треугольники наружной
поверхности, поэтому профиль и острые рёбра сохраняются 1:1.

**Что заливать, выбирает человек.** По лучу стенка сквозного отверстия выглядит
такой же внутренней, как полость трубы, и надёжно различить их геометрией нельзя:
у трубы полость тоже открыта — торцом. Поэтому инструмент без --fill ничего не
пишет, а показывает найденные пустоты списком.
"""
import argparse
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import trimesh
from trimesh import grouping, repair

from forge.io import model_dir

# Сдвиг начала луча от поверхности, мм. Достаточно мал, чтобы не перескочить
# через стенку тоньше миллиметра.
RAY_EPS = 1e-3


def load_source(path: Path) -> trimesh.Trimesh:
    mesh = trimesh.load(path, force="mesh")
    if not mesh.is_watertight:
        raise SystemExit(
            f"{path.name}: меш не watertight — сначала почини его, "
            "иначе внутреннюю поверхность не отличить от наружной"
        )
    return mesh


def inner_faces(mesh: trimesh.Trimesh) -> np.ndarray:
    """Маска фейсов, смотрящих в пустоту внутри габарита тела.

    Признак: луч, пущенный из треугольника по его нормали (то есть в сторону
    пустоты перед ним), снова попадает в тело. Наружу такой луч уходит в
    бесконечность, внутрь полости или отверстия — упирается в стенку напротив.
    """
    origins = mesh.triangles_center + mesh.face_normals * RAY_EPS
    _, hit_rays, _ = mesh.ray.intersects_location(
        origins, mesh.face_normals, multiple_hits=False
    )
    mask = np.zeros(len(mesh.faces), dtype=bool)
    mask[hit_rays] = True
    return mask


def voids(mesh: trimesh.Trimesh, inner: np.ndarray) -> list[np.ndarray]:
    """Связные внутренние поверхности — каждая ограничивает свою пустоту."""
    adjacency = mesh.face_adjacency
    linked = adjacency[inner[adjacency[:, 0]] & inner[adjacency[:, 1]]]
    components = trimesh.graph.connected_components(linked, nodes=np.where(inner)[0])
    return sorted((np.asarray(c) for c in components), key=len, reverse=True)


def describe(mesh: trimesh.Trimesh, faces: np.ndarray) -> str:
    sub = mesh.submesh([faces], append=True)
    size = sub.extents
    open_edges = len(grouping.group_rows(sub.edges_sorted, require_count=1))
    return (f"{len(faces):5d} треугольников, площадь {mesh.area_faces[faces].sum():8.1f} мм², "
            f"габарит {size[0]:.1f}×{size[1]:.1f}×{size[2]:.1f} мм, открытых рёбер {open_edges}")


def boundary_loops(mesh: trimesh.Trimesh) -> list[list[int]]:
    """Все замкнутые контуры открытой кромки, а не по одному на компоненту."""
    edges = mesh.edges_sorted
    boundary = edges[grouping.group_rows(edges, require_count=1)]
    if len(boundary) == 0:
        return []
    graph = nx.from_edgelist(boundary)
    loops: list[list[int]] = []
    for component in nx.connected_components(graph):
        cycles = nx.cycle_basis(graph.subgraph(component))
        if not cycles:
            raise SystemExit(
                "кромка без замкнутого контура — заклеить её нечем; "
                "почини меш перед заливкой"
            )
        loops.extend(cycles)
    return loops


def cap_holes(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Заклеивает открытые контуры веером треугольников от центра контура.

    repair.fill_holes пасует на неплоских кромках с десятками рёбер, а после
    срезания внутренней оболочки они именно такие. Веер от центроида справляется.
    """
    loops = boundary_loops(mesh)
    if not loops:
        return mesh

    vertices = mesh.vertices.copy()
    faces = list(mesh.faces)
    for loop in loops:
        centre = len(vertices)
        vertices = np.vstack([vertices, mesh.vertices[loop].mean(axis=0)])
        for i in range(len(loop)):
            faces.append([centre, loop[i], loop[(i + 1) % len(loop)]])

    capped = trimesh.Trimesh(vertices=vertices, faces=np.array(faces), process=False)
    capped.merge_vertices()
    repair.fix_winding(capped)
    repair.fix_inversion(capped)
    return capped


def drop_flat_scraps(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Оставляет только само тело.

    Дно полости часто остаётся висеть внутри материала отдельной плёнкой нулевого
    объёма. Печати она не мешает, но слайсер видит два тела вместо одного.
    """
    bodies = mesh.split(only_watertight=False)
    if len(bodies) <= 1:
        return mesh
    # у плёнки нулевого объёма центр масс не считается — numpy ругается делением
    # на ноль, хотя объём это ровно то, что нам от неё и нужно
    with np.errstate(invalid="ignore", divide="ignore"):
        keep = max(bodies, key=lambda b: abs(b.volume))
        dropped = sum(abs(b.volume) for b in bodies if b is not keep)
    if dropped > 1e-6:
        raise SystemExit(f"отброшен кусок с ненулевым объёмом {dropped:.3f} мм³")
    print(f"выкинуто плёнок нулевого объёма: {len(bodies) - 1}")
    return keep


def parse_choice(text: str, count: int) -> list[int]:
    if text.strip().lower() == "all":
        return list(range(count))
    picked = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk.isdigit():
            sys.exit(f"--fill ждёт номера пустот через запятую или all, получил {chunk!r}")
        number = int(chunk)
        if not 1 <= number <= count:
            sys.exit(f"--fill: пустоты {number} нет, их всего {count}")
        picked.append(number - 1)
    return sorted(set(picked))


def solidify(src: trimesh.Trimesh, chosen: list[np.ndarray]) -> trimesh.Trimesh:
    mask = np.zeros(len(src.faces), dtype=bool)
    for faces in chosen:
        mask[faces] = True

    shell = src.submesh([np.where(~mask)[0]], append=True)
    boundary = grouping.group_rows(shell.edges_sorted, require_count=1)
    print(f"убрано внутренних треугольников: {mask.sum()} из {len(src.faces)}")
    print(f"открытых рёбер после удаления: {len(boundary)}")

    shell = cap_holes(shell)
    shell.update_faces(shell.nondegenerate_faces())
    shell = drop_flat_scraps(shell)

    if not shell.is_watertight:
        raise SystemExit("не удалось заклеить — тело осталось дырявым")
    if shell.volume <= src.volume:
        raise SystemExit("объём не вырос — пустота не залилась")

    print(f"объём: было {src.volume:.0f} мм³ → стало {shell.volume:.0f} мм³")
    print(f"габарит: {np.round(shell.extents, 2)} мм")
    return shell


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path, help="исходный меш (STL, OBJ, 3MF...)")
    ap.add_argument("-o", "--out", type=Path,
                    help="куда писать (по умолчанию prints/<имя>_solid/<имя>_solid.stl)")
    ap.add_argument("--fill", metavar="N[,M] | all",
                    help="номера пустот из списка выше; без этого флага файл не пишется")
    args = ap.parse_args()

    if not args.src.exists():
        sys.exit(f"нет файла {args.src}")

    src = load_source(args.src)
    inner = inner_faces(src)
    if not inner.any():
        raise SystemExit("внутренних поверхностей не найдено — тело уже сплошное")

    found = voids(src, inner)
    print(f"{args.src.name}: {src.volume:.0f} мм³, найдено внутренних пустот: {len(found)}\n")
    for i, faces in enumerate(found, 1):
        print(f"  [{i}] {describe(src, faces)}")

    if not args.fill:
        print("\nЧто из этого заливать — решай сам: стенка сквозного отверстия выглядит")
        print("такой же внутренней, как полость трубы. Залить первую: --fill 1, всё: --fill all")
        return

    stem = f"{args.src.stem}_solid"
    out = args.out or model_dir(stem) / f"{stem}.stl"
    if out.resolve() == args.src.resolve():
        sys.exit("результат затёр бы исходник — задай другой -o")

    chosen = [found[i] for i in parse_choice(args.fill, len(found))]
    print()
    solid = solidify(src, chosen)
    out.parent.mkdir(parents=True, exist_ok=True)
    solid.export(out)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
