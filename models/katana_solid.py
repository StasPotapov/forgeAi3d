"""Twisted Katana — заливка внутренней полости.

Исходный STL (Twisted_Katana_blades.stl) — полая витая труба: стенка 1.1–1.5 мм,
внутри сквозная полость, открытая маленьким отверстием на кончике. Слайсер честно
печатает эту полость как пустоту, поэтому infill внутрь не попадает.

Здесь внутренняя оболочка удаляется, оставшаяся дыра заклеивается — получается
сплошное тело. Теперь заполнением внутри распоряжается слайсер (infill 15%).

Внешняя геометрия не трогается вообще: берутся ровно исходные треугольники
наружной поверхности, поэтому витой профиль и острые рёбра сохраняются 1:1.
"""

from pathlib import Path

import networkx as nx
import numpy as np
import trimesh
from trimesh import grouping, repair

SRC = Path.home() / "Desktop" / "Twisted_Katana_blades.stl"
OUT = Path(__file__).resolve().parent.parent / "out" / "katana_solid.stl"

# Сдвиг начала луча от поверхности, мм. Достаточно мал, чтобы не перескочить
# через стенку (минимальная стенка в модели ~1.1 мм).
RAY_EPS = 1e-3


def load_source() -> trimesh.Trimesh:
    mesh = trimesh.load(SRC, force="mesh")
    if not mesh.is_watertight:
        raise SystemExit("исходный меш не watertight — сначала почини его")
    return mesh


def inner_faces(mesh: trimesh.Trimesh) -> np.ndarray:
    """Маска фейсов, смотрящих в полость.

    Признак: луч, пущенный из треугольника по его нормали (то есть в сторону
    пустоты перед ним), снова попадает в тело. Наружу такой луч уходит в
    бесконечность, внутрь полости — упирается в противоположную стенку.
    """
    origins = mesh.triangles_center + mesh.face_normals * RAY_EPS
    _, hit_rays, _ = mesh.ray.intersects_location(
        origins, mesh.face_normals, multiple_hits=False
    )
    mask = np.zeros(len(mesh.faces), dtype=bool)
    mask[hit_rays] = True
    return mask


def cap_holes(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Заклеивает открытые контуры веером треугольников от центра контура.

    repair.fill_holes здесь пасует: кромка на кончике клинка неплоская и в ней
    36 рёбер. Веер от центроида справляется и с такой.
    """
    edges = mesh.edges_sorted
    boundary = edges[grouping.group_rows(edges, require_count=1)]
    if len(boundary) == 0:
        return mesh

    vertices = mesh.vertices.copy()
    faces = list(mesh.faces)

    for cycle in nx.connected_components(nx.from_edgelist(boundary)):
        loop = nx.cycle_basis(nx.from_edgelist(boundary).subgraph(cycle))[0]
        center = len(vertices)
        vertices = np.vstack([vertices, mesh.vertices[loop].mean(axis=0)])
        for i in range(len(loop)):
            faces.append([center, loop[i], loop[(i + 1) % len(loop)]])

    capped = trimesh.Trimesh(vertices=vertices, faces=np.array(faces), process=False)
    capped.merge_vertices()
    repair.fix_winding(capped)
    repair.fix_inversion(capped)
    return capped


def drop_flat_scraps(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Оставляет только само тело.

    Дно полости в исходнике — плоский шестиугольник, который после удаления
    внутренней оболочки остаётся висеть внутри материала отдельной плёнкой
    нулевого объёма. Печати она не мешает, но слайсер видит два тела вместо
    одного, поэтому выкидываем.
    """
    bodies = mesh.split(only_watertight=False)
    if len(bodies) <= 1:
        return mesh
    keep = max(bodies, key=lambda b: abs(b.volume))
    dropped = sum(abs(b.volume) for b in bodies if b is not keep)
    if dropped > 1e-6:
        raise SystemExit(f"отброшен кусок с ненулевым объёмом {dropped:.3f} мм³")
    print(f"выкинуто плёнок нулевого объёма: {len(bodies) - 1}")
    return keep


def build() -> trimesh.Trimesh:
    src = load_source()
    mask = inner_faces(src)

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
        raise SystemExit("объём не вырос — полость не залилась")

    print(f"объём: было {src.volume:.0f} мм³ → стало {shell.volume:.0f} мм³")
    print(f"габарит: {np.round(shell.extents, 2)} мм")
    return shell


if __name__ == "__main__":
    solid = build()
    OUT.parent.mkdir(exist_ok=True)
    solid.export(OUT)
    print(f"-> {OUT}")
