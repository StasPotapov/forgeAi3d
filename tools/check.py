#!/usr/bin/env python3
"""Проверка детали на печатопригодность.

    uv run tools/check.py prints/part/part.stl [--material petg] [--nozzle 0.4] [--bed 180x180x180]
    uv run tools/check.py prints/part/part.step --material petg

Геометрию считает augura: по STEP — точно, по граням B-Rep; по STL — приблизительно,
там нет ни толщины стенок, ни мелких вертикальных деталей. Поэтому рядом с STL ищется
одноимённый STEP и берётся он. Качество самого меша (герметичность, нормали, число тел)
проверяется по STL — augura этим не занимается.

Код возврата 1 — нашлись проблемы, из-за которых печатать не стоит.
Предупреждения на код возврата не влияют: они зависят от ориентации детали,
а её выбирают уже в слайсере.
"""
import argparse
import dataclasses
import sys
from pathlib import Path

import augura
import numpy as np
import trimesh
from build123d import import_step

from forge import A1_MINI, find_step, get, in_stock, supported, wall

# Тонкая стенка у augura — предупреждение. Здесь это отказ: стенка тоньше двух
# периметров печатается как пустота между контурами, деталь выходит бумажной.
# Но augura отдаёт минимум, а минимум сам по себе не показателен: у фаски, уклона
# и у кромки выдавленной буквы толщина по построению стремится к нулю. Поэтому
# решает доля поверхности тоньше порога, а минимум остаётся справкой.
THIN_SAMPLES = 1500
THIN_SHARE_LIMIT = 5.0   # % поверхности, после которых это уже не край фаски

# Суть находки по-русски; подробности augura отдаёт своим текстом, с числами,
# и переписывать их значило бы пересказывать библиотеку своими словами.
KIND_RU = {
    "overhang": "свес",
    "bridge": "мост",
    "tip_over": "опрокинется",
    "brim": "нужен brim",
    "thin_wall": "тонкая стенка",
    "thin_feature": "тонкая деталь",
    "min_feature": "мелкая деталь",
    "bed_fit": "не влезает на стол",
    "not_manifold": "меш не замкнут",
}

# Насколько лучшая поза должна быть лучше текущей, чтобы про неё стоило говорить.
ORIENT_GAIN = 0.25   # на столько должна упасть площадь свесов, доля
ORIENT_FLOOR = 50.0  # мм²; меньше этого свесов и так нет, молчим

# высота / меньшая сторона основания: выше этого высокую деталь на ездящем столе
# отрывает инерцией. augura считает опрокидывание по центру масс и про разгон
# стола не знает, поэтому проверка своя
TIPPING_ASPECT = 4.0


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


def fits_rotated(extents: tuple[float, float, float] | None,
                 bed: tuple[float, float, float]) -> bool:
    """Влезает ли деталь на стол, если развернуть её на 90° в плоскости стола."""
    if extents is None:
        return False
    x, y, z = extents
    return y <= bed[0] and x <= bed[1] and z <= bed[2]


def thin_share(mesh: trimesh.Trimesh, floor: float) -> float | None:
    """Доля поверхности тоньше порога, %. None — посчитать не удалось.

    Луч пускается внутрь тела от точки на поверхности против её нормали.
    """
    if not mesh.is_watertight:
        return None
    points, face_ids = trimesh.sample.sample_surface(mesh, THIN_SAMPLES)
    normals = mesh.face_normals[face_ids]
    origins = points - normals * 1e-3          # чуть внутрь, чтобы не поймать старт
    locs, ray_ids, _ = mesh.ray.intersects_location(
        ray_origins=origins, ray_directions=-normals, multiple_hits=False
    )
    if len(ray_ids) == 0:
        return None
    d = np.linalg.norm(locs - origins[ray_ids], axis=1)
    return float((d < floor).mean() * 100.0)


def as_mesh(shape) -> trimesh.Trimesh | None:
    """Тесселяция STEP — чтобы считать долю и когда меша на входе не было."""
    try:
        vertices, faces = shape.tessellate(tolerance=0.05)
        return trimesh.Trimesh(
            vertices=[(v.X, v.Y, v.Z) for v in vertices], faces=faces
        )
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model", type=Path, help="STL или STEP")
    ap.add_argument("--material", default="PLA", help="PLA, PETG, PLA-CF, ASA, TPU")
    ap.add_argument("--bed", default=None, help="стол ШxГxВ, мм (по умолчанию из профиля принтера)")
    ap.add_argument("--nozzle", type=float, default=None, help="диаметр сопла, мм")
    ap.add_argument("--no-orientation", action="store_true",
                    help="не подбирать ориентацию (перебор поз — самая долгая часть)")
    args = ap.parse_args()

    if not args.model.exists():
        sys.exit(f"нет файла {args.model}")

    try:
        mat = get(args.material)
    except KeyError as exc:
        sys.exit(exc.args[0])

    printer = A1_MINI
    if args.nozzle is not None:
        if args.nozzle <= 0:
            sys.exit("--nozzle должен быть положительным")
        # вместе с соплом меняется и типовой слой: сопло 0.8 не печатает слоем 0.2,
        # иначе проверка «ступенька тоньше слоя» сравнивала бы с чужим числом
        printer = dataclasses.replace(
            printer,
            nozzle=args.nozzle,
            extrusion_width=round(args.nozzle * 1.05, 3),
            layer_height=round(args.nozzle * 0.5, 2),
        )
    if args.bed is not None:
        printer = dataclasses.replace(printer, bed=parse_bed(args.bed))

    is_mesh_input = args.model.suffix.lower() not in (".step", ".stp")
    step = find_step(args.model)

    problems: list[str] = []
    warnings: list[str] = []
    extents: tuple[float, float, float] | None = None

    print(f"файл          {args.model}")
    print(f"материал      {mat.name}  (усадка {mat.shrink * 100:.1f}%, размягчается от {mat.hdt:.0f} °C)")
    print(f"принтер       {printer.name}, сопло {printer.nozzle} мм")

    # --- качество меша: только по STL, augura этого не умеет ---
    mesh = None
    if is_mesh_input:
        try:
            mesh = trimesh.load_mesh(args.model)
        except Exception as exc:
            sys.exit(f"не удалось прочитать {args.model}: {exc}")
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.to_mesh()

        size = mesh.extents
        extents = (float(size[0]), float(size[1]), float(size[2]))
        print(f"габариты      {size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f} мм")
        print(f"треугольников {len(mesh.faces)}")
        print(f"тел в файле   {mesh.body_count}")

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

    # --- профиль принтера и наличие материала ---
    problems += supported(mat, printer)
    if not in_stock(mat):
        warnings.append(f"{mat.name} не числится в наличии — проверь, есть ли катушка")

    # --- геометрия: augura ---
    shape = None
    if step is not None:
        try:
            shape = import_step(str(step))
        except Exception as exc:
            if mesh is None:
                sys.exit(f"не удалось прочитать {step}: {exc}")
            warnings.append(f"не удалось прочитать {step.name}, анализ пойдёт по мешу: {exc}")

    if shape is not None:
        source = f"{step.name} (точный B-Rep)"
        if not is_mesh_input:
            bb = shape.bounding_box()
            extents = (bb.size.X, bb.size.Y, bb.size.Z)
            print(f"габариты      {bb.size.X:.2f} x {bb.size.Y:.2f} x {bb.size.Z:.2f} мм")
            print(f"тел в файле   {len(shape.solids())}")
            print(f"объём         {shape.volume / 1000:.2f} см³")
        report = augura.analyze(
            shape,
            support_angle=mat.support_angle,
            build_volume=printer.bed,
            # порог тонкой стенки augura считает как nozzle * min_perimeters, а у нас
            # два периметра это 2 * ширину линии — иначе её 0.80 разойдётся с wall() 0.84
            nozzle=printer.extrusion_width,
            min_perimeters=2,
            min_feature=printer.nozzle,
            max_bridge=mat.max_bridge,
        )
    elif mesh is not None:
        source = f"{args.model.name} (меш, приблизительно)"
        warnings.append(
            "мелкие вертикальные детали не проверены — для этого нужен STEP рядом "
            "с мешем; толщина стенки ниже посчитана по треугольникам, приблизительно"
        )
        report = augura.analyze_mesh(
            mesh, support_angle=mat.support_angle, build_volume=printer.bed
        )
    else:
        sys.exit(f"не удалось разобрать {args.model}")

    floor = wall(2, printer)
    print(f"анализ по     {source}")
    print(f"стенка        минимум {floor:.2f} мм = 2 периметра при сопле {printer.nozzle} мм")

    # доля поверхности тоньше порога — считается один раз: тесселяция STEP и 1500
    # лучей не бесплатны, а находка thin_wall может прийти не одна.
    # По мешу augura толщину не смотрит вовсе, поэтому там считаем сами и без повода:
    # правка чужих STL — обычное дело, и оставлять их вовсе без проверки нельзя.
    thin = None
    by_mesh_only = shape is None
    if by_mesh_only or any(f.kind == "thin_wall" for f in report.findings):
        sample = mesh if mesh is not None else as_mesh(shape)
        thin = thin_share(sample, floor) if sample is not None else None

    if by_mesh_only:
        if thin is None:
            warnings.append("толщину стенки оценить не удалось — меш негерметичный")
        elif thin > THIN_SHARE_LIMIT:
            problems.append(
                f"тоньше {floor:.2f} мм — {thin:.1f}% поверхности "
                "(по мешу, приблизительно: точное значение даст STEP)"
            )
        else:
            print(f"толщина       тоньше {floor:.2f} мм — {thin:.1f}% поверхности (по мешу)")

    for finding in report.findings:
        # префикс augura про приблизительность дублирует строку «анализ по»
        message = finding.message.removeprefix("[mesh, approximate] ")
        kind = KIND_RU.get(finding.kind, finding.kind)
        text = f"{kind}: {message}"
        if finding.area is not None:
            text = f"{text} ({finding.area:.0f} мм²)"
        if finding.kind == "thin_wall":
            # решает доля, а не минимум: одна кромка фаски или буквы — не брак
            if thin is None:
                warnings.append(f"{text} — какую долю поверхности это занимает, оценить не удалось")
            elif thin > THIN_SHARE_LIMIT:
                problems.append(f"{text}; тоньше {floor:.2f} мм — {thin:.1f}% поверхности")
            else:
                warnings.append(
                    f"{text}, но это {thin:.1f}% поверхности — похоже на кромку фаски "
                    "или надписи, а не на стенку"
                )
        elif finding.kind == "bed_fit" and fits_rotated(extents, printer.bed):
            # augura меряет габарит по осям как есть, а деталь на стол кладут как удобно
            warnings.append(
                f"{text} — но влезает после поворота на 90° в плоскости стола"
            )
        elif finding.kind == "not_manifold" and mesh is not None and not mesh.is_watertight:
            pass    # про негерметичность уже сказано выше, своими словами
        elif finding.severity == "error":
            problems.append(text)
        elif finding.severity == "warning":
            warnings.append(text)
        else:
            print(f"инфо          {text}")

    # --- максимальная высота слоя из самой мелкой вертикальной ступеньки ---
    if shape is not None:
        step_h = augura.min_vertical_feature(shape)
        if step_h is not None:
            # печатаем, только когда ступенька реально ограничивает слой;
            # у плоской пластины она равна её высоте и ни о чём не говорит
            if step_h < 5 * printer.layer_height:
                print(f"слой          не толще {step_h:.2f} мм "
                      f"(сейчас в профиле {printer.layer_height} мм)")
            if step_h < printer.layer_height:
                problems.append(
                    f"самая мелкая ступенька {step_h:.2f} мм тоньше слоя "
                    f"{printer.layer_height} мм — деталь на ней пропадёт, нужен слой мельче"
                )

    # --- ориентация ---
    if shape is not None and not args.no_orientation:
        scores = augura.orientation_scores(
            shape, support_angle=mat.support_angle, build_volume=printer.bed,
            max_bridge=mat.max_bridge,
        )
        best = scores[0] if scores else None
        current = next((s for s in scores if tuple(s.rotation) == (0, 0, 0)), None)
        if best is not None and current is not None and tuple(best.rotation) != (0, 0, 0):
            gain = current.overhang_area - best.overhang_area
            if current.overhang_area > ORIENT_FLOOR and gain > current.overhang_area * ORIENT_GAIN:
                rx, ry, rz = best.rotation
                warnings.append(
                    f"положить иначе — поворот ({rx:g}, {ry:g}, {rz:g})° оставит "
                    f"{best.overhang_area:.0f} мм² свесов вместо {current.overhang_area:.0f}"
                )

    # высокая узкая деталь на принтере с ездящим столом
    if printer.bed_slinger and extents is not None:
        seen = {f.kind for f in report.findings}
        base = min(extents[0], extents[1])
        if base > 0 and extents[2] / base > TIPPING_ASPECT and not (
            seen & {"tip_over", "brim"}      # augura уже сказала про то же самое
        ):
            warnings.append(
                f"высота {extents[2]:.0f} мм при основании {base:.0f} мм — "
                f"на {printer.name} ездит стол, деталь может оторвать инерцией. "
                "Нужен brim или печать набок"
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
