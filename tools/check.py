#!/usr/bin/env python3
"""Проверка STL на печатопригодность через trimesh.

    uv run tools/check.py out/part.stl [--material petg] [--nozzle 0.4] [--bed 180x180x180]

Код возврата 1 — нашлись проблемы, из-за которых печатать не стоит.
Предупреждения на код возврата не влияют: они зависят от ориентации детали,
а её выбирают уже в слайсере.
"""
import argparse
import dataclasses
import sys
from pathlib import Path

import numpy as np
import trimesh

from forge import A1_MINI, Printer, get, in_stock, supported, wall

THICKNESS_SAMPLES = 1500
THIN_SHARE_LIMIT = 5.0   # % сэмплов тоньше порога, после которых это уже не край фаски
TIPPING_ASPECT = 4.0     # высота / меньшая сторона основания — риск опрокидывания
BED_CONTACT_TOL = 0.01   # грань считается лежащей на столе, мм


def parse_bed(text: str) -> tuple[float, float, float]:
    try:
        dims = tuple(float(v) for v in text.lower().split("x"))
    except ValueError:
        sys.exit(f"--bed ждёт формат ШxГxВ, получил {text!r}")
    if len(dims) != 3:
        sys.exit(f"--bed ждёт три размера ШxГxВ, получил {text!r}")
    if any(d <= 0 for d in dims):
        sys.exit(f"--bed: размеры должны быть положительными, получил {text!r}")
    return dims  # type: ignore[return-value]


def thickness_stats(mesh: trimesh.Trimesh, samples: int, floor: float) -> tuple[float, float] | None:
    """Минимальная толщина и доля сэмплов тоньше порога, %.

    Луч пускается внутрь тела от точки на поверхности против её нормали.
    Один только минимум не показателен: у любой фаски, уклона или конуса
    перпендикулярная толщина у самой кромки стремится к нулю. Поэтому
    решение принимается по доле поверхности, а минимум остаётся справкой.
    """
    points, face_ids = trimesh.sample.sample_surface(mesh, samples)
    normals = mesh.face_normals[face_ids]
    origins = points - normals * 1e-3          # чуть внутрь, чтобы не поймать старт
    locs, ray_ids, _ = mesh.ray.intersects_location(
        ray_origins=origins, ray_directions=-normals, multiple_hits=False
    )
    if len(ray_ids) == 0:
        return None
    d = np.linalg.norm(locs - origins[ray_ids], axis=1)
    return float(d.min()), float((d < floor).mean() * 100.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stl", type=Path)
    ap.add_argument("--material", default="PLA", help="PLA, PETG, PLA-CF, ASA, TPU")
    ap.add_argument("--bed", default=None, help="стол ШxГxВ, мм (по умолчанию из профиля принтера)")
    ap.add_argument("--nozzle", type=float, default=None, help="диаметр сопла, мм")
    ap.add_argument("--no-thickness", action="store_true", help="пропустить оценку толщины (долгая)")
    args = ap.parse_args()

    if not args.stl.exists():
        sys.exit(f"нет файла {args.stl}")

    try:
        mat = get(args.material)
    except KeyError as exc:
        sys.exit(exc.args[0])

    printer = A1_MINI
    if args.nozzle is not None:
        if args.nozzle <= 0:
            sys.exit("--nozzle должен быть положительным")
        printer = dataclasses.replace(
            printer, nozzle=args.nozzle, extrusion_width=round(args.nozzle * 1.05, 3)
        )
    if args.bed is not None:
        printer = dataclasses.replace(printer, bed=parse_bed(args.bed))

    try:
        mesh = trimesh.load_mesh(args.stl)
    except Exception as exc:
        sys.exit(f"не удалось прочитать {args.stl}: {exc}")
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.to_mesh()

    size = mesh.extents
    problems: list[str] = []
    warnings: list[str] = []

    print(f"файл          {args.stl}")
    print(f"материал      {mat.name}  (усадка {mat.shrink * 100:.1f}%, размягчается от {mat.hdt:.0f} °C)")
    print(f"принтер       {printer.name}, сопло {printer.nozzle} мм")
    print(f"габариты      {size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f} мм")
    print(f"треугольников {len(mesh.faces)}")
    print(f"тел в файле   {mesh.body_count}")

    problems += supported(mat, printer)
    if not in_stock(mat):
        warnings.append(f"{mat.name} не числится в наличии — проверь, есть ли катушка")

    if mesh.is_watertight:
        print(f"объём         {mesh.volume / 1000:.2f} см³   (герметичный меш)")
    else:
        problems.append("меш не герметичный — слайсер может напечатать мусор, нужен repair")
        print("объём         — (меш НЕ герметичный)")

    if not mesh.is_winding_consistent:
        problems.append("нормали развёрнуты непоследовательно")

    degenerate = int((~mesh.nondegenerate_faces(height=1e-4)).sum())
    if degenerate:
        problems.append(f"вырожденных треугольников: {degenerate}")

    # влезает ли на стол (с учётом поворота на 90° в плоскости)
    bed = printer.bed
    bed_str = f"{bed[0]:g}x{bed[1]:g}x{bed[2]:g}"
    fits_direct = size[0] <= bed[0] and size[1] <= bed[1] and size[2] <= bed[2]
    fits_rotated = size[1] <= bed[0] and size[0] <= bed[1] and size[2] <= bed[2]
    if fits_direct:
        print(f"стол {bed_str}  влезает")
    elif fits_rotated:
        print(f"стол {bed_str}  влезает после поворота на 90°")
    else:
        problems.append(f"не влезает на стол {bed_str}")

    # свесы: нормаль грани смотрит вниз круче порога, и грань не лежит на столе
    limit = np.cos(np.radians(mat.support_angle))
    z_min = mesh.bounds[0][2]
    on_bed = (mesh.triangles[:, :, 2] <= z_min + BED_CONTACT_TOL).all(axis=1)
    overhang = (mesh.face_normals[:, 2] < -limit) & ~on_bed
    if overhang.any():
        share = mesh.area_faces[overhang].sum() / mesh.area * 100
        print(f"свесы <{mat.support_angle:.0f}°   {share:.1f}% площади")
        warnings.append(
            f"{share:.1f}% площади — свесы положе {mat.support_angle:.0f}°, "
            f"для {mat.name} это поддержки или другая ориентация"
        )
    else:
        print(f"свесы <{mat.support_angle:.0f}°   нет (при печати как есть, без поворота)")

    # высокая узкая деталь на принтере с ездящим столом
    base = min(size[0], size[1])
    if printer.bed_slinger and base > 0 and size[2] / base > TIPPING_ASPECT:
        warnings.append(
            f"высота {size[2]:.0f} мм при основании {base:.0f} мм — на {printer.name} "
            "ездит стол, деталь может оторвать. Нужен brim или печать набок"
        )

    floor = wall(2, printer)
    if args.no_thickness:
        print("толщина       пропущена (--no-thickness)")
    elif not mesh.is_watertight:
        print("толщина       пропущена — меш не герметичный, лучи внутрь тела не считаются")
    else:
        stats = thickness_stats(mesh, THICKNESS_SAMPLES, floor)
        if stats is None:
            print("толщина       оценить не удалось")
        else:
            t_min, share = stats
            print(
                f"толщина       минимум ~{t_min:.2f} мм, "
                f"тоньше {floor:.2f} мм — {share:.1f}% поверхности"
            )
            if share > THIN_SHARE_LIMIT:
                problems.append(
                    f"{share:.1f}% поверхности тоньше {floor:.2f} мм "
                    f"(2 периметра при сопле {printer.nozzle} мм)"
                )

    if warnings:
        print("\nПредупреждения (на код возврата не влияют):")
        for w in warnings:
            print(f"  - {w}")

    if problems:
        print("\nПроблемы:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("\nПроблем не найдено.")


if __name__ == "__main__":
    main()
