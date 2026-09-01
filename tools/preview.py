#!/usr/bin/env python3
"""Рендер модели в PNG-контактный лист через headless OpenSCAD.

    uv run tools/preview.py prints/part/part.stl [-o файл.png] [--views iso,top,front,right]
    uv run tools/preview.py prints/part/part.stl --overhangs --material PETG
    uv run tools/preview.py prints/part/part.stl --section y

--overhangs красит красным грани, которым нужны поддержки: отчёт check.py говорит,
сколько их по площади, а превью показывает, где именно.
--section разрезает деталь пополам — единственный способ увидеть внутреннюю полость
и толщину стенки, не печатая.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from forge.io import aux_path
from forge.spec import get

# имя -> --camera=tx,ty,tz,rx,ry,rz (дистанция подбирается через --viewall)
VIEWS = {
    "iso":   "0,0,0,55,0,25",
    "iso2":  "0,0,0,55,0,205",
    "top":   "0,0,0,0,0,0",
    "front": "0,0,0,90,0,0",
    "right": "0,0,0,90,0,90",
    "back":  "0,0,0,90,0,180",
    # свесы смотрят вниз, сверху их не разглядеть — для них нужны нижние ракурсы
    "iso_low": "0,0,0,125,0,25",
    "bottom":  "0,0,0,180,0,0",
}

DEFAULT_VIEWS = "iso,top,front,right"
OVERHANG_VIEWS = "iso,iso_low,bottom,front"

BED_CONTACT_TOL = 0.01           # грань считается лежащей на столе, мм
OVERHANG_COLOR = "[0.85, 0.25, 0.2]"
BODY_COLOR = "[0.78, 0.78, 0.8]"


def find_openscad() -> str | None:
    """Бинарь из PATH, иначе бандл. Стабильный OpenSCAD-2021.01 — Intel-сборка,
    поэтому версионированные бандлы идут последними."""
    found = shutil.which("openscad")
    if found:
        return found
    apps = sorted(
        Path("/Applications").glob("OpenSCAD*.app/Contents/MacOS/OpenSCAD"),
        key=lambda p: (p.parts[2] != "OpenSCAD.app", p.parts[2]),
    )
    return str(apps[0]) if apps else None


OPENSCAD = find_openscad()


def split_overhangs(mesh: trimesh.Trimesh, support_angle: float, workdir: Path
                    ) -> list[tuple[Path, str]]:
    """Делит меш на свесы и остальное, возвращает пары (файл, цвет).

    Свес — грань, чья нормаль смотрит вниз круче порога и которая не лежит на столе.
    Считается по треугольникам, поэтому процент здесь и процент в отчёте check.py
    (augura меряет по точным граням и учитывает мосты) могут немного расходиться:
    задача картинки — показать место, а не число.
    """
    limit = np.cos(np.radians(support_angle))
    z_min = mesh.bounds[0][2]
    on_bed = (mesh.triangles[:, :, 2] <= z_min + BED_CONTACT_TOL).all(axis=1)
    overhang = (mesh.face_normals[:, 2] < -limit) & ~on_bed

    if not overhang.any():
        path = workdir / "body.stl"
        mesh.export(path)
        return [(path, BODY_COLOR)]

    share = mesh.area_faces[overhang].sum() / mesh.area * 100
    print(f"свесы положе {support_angle:.0f}°: {share:.1f}% площади — красным")

    pieces = []
    for name, mask, color in (
        ("body", ~overhang, BODY_COLOR),
        ("overhang", overhang, OVERHANG_COLOR),
    ):
        if not mask.any():
            continue
        path = workdir / f"{name}.stl"
        mesh.submesh([np.where(mask)[0]], append=True).export(path)
        pieces.append((path, color))
    return pieces


def parse_section(text: str, mesh: trimesh.Trimesh) -> tuple[int, float]:
    """`y` или `y:12.5` -> ось и координата реза (по умолчанию середина детали)."""
    axis_name, _, position = text.partition(":")
    axis_name = axis_name.strip().lower()
    if axis_name not in ("x", "y", "z"):
        sys.exit(f"--section ждёт x, y или z (можно 'y:12.5'), получил {text!r}")
    axis = "xyz".index(axis_name)
    if position:
        try:
            return axis, float(position)
        except ValueError:
            sys.exit(f"--section: координата должна быть числом, получил {position!r}")
    return axis, float(mesh.bounds[:, axis].mean())


def scad_source(pieces: list[tuple[Path, str]], cut: tuple[int, float] | None,
                mesh: trimesh.Trimesh) -> str:
    """Сборка .scad: цветные куски и, если просили, вычитание секущего блока."""
    body = "\n".join(
        f"  color({color}) import({json.dumps(str(path.resolve()))});"
        for path, color in pieces
    )
    if cut is None:
        return body.replace("\n  ", "\n").strip() + "\n"

    axis, position = cut
    size = float(mesh.extents.max()) * 4 + 10
    origin = [float(mesh.bounds[0][i]) - size / 2 for i in range(3)]
    origin[axis] = position
    place = ", ".join(f"{v:.3f}" for v in origin)
    return (
        "difference() {\n"
        "  union() {\n"
        + "\n".join(f"  {line}" for line in body.splitlines())
        + "\n  }\n"
        f"  translate([{place}]) cube([{size:.3f}, {size:.3f}, {size:.3f}]);\n"
        "}\n"
    )


def render(source: str, view: str, size: int, workdir: Path) -> Image.Image:
    scad = workdir / f"{view}.scad"
    scad.write_text(source)
    png = scad.with_suffix(".png")
    cmd = [
        OPENSCAD, "-o", str(png),
        f"--imgsize={size},{size}",
        f"--camera={VIEWS[view]},0",
        "--viewall", "--autocenter",
        "--colorscheme=Tomorrow",
        str(scad),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    # OpenSCAD на битом STL выходит с кодом 0 и всё равно пишет пустой PNG,
    # поэтому одного png.exists() мало — надо смотреть в stderr.
    if res.returncode != 0 or "ERROR:" in res.stderr or not png.exists():
        errors = [ln for ln in res.stderr.splitlines() if "ERROR:" in ln or "WARNING:" in ln]
        detail = "\n".join(errors) if errors else res.stderr.strip()[-800:]
        sys.exit(f"OpenSCAD не отрендерил вид {view}:\n{detail}")
    with Image.open(png) as img:
        img.load()          # файлы удалятся вместе с workdir
        return img.copy()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stl", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--views", default=None,
                    help=f"по умолчанию {DEFAULT_VIEWS}, с --overhangs {OVERHANG_VIEWS}")
    ap.add_argument("--size", type=int, default=520, help="сторона одного вида, px")
    ap.add_argument("--overhangs", action="store_true",
                    help="подсветить красным грани, которым нужны поддержки")
    ap.add_argument("--material", default="PLA",
                    help="от него зависит порог свесов при --overhangs")
    ap.add_argument("--section", default=None, metavar="ОСЬ[:КООРД]",
                    help="разрез: x, y, z или y:12.5 (по умолчанию посередине)")
    args = ap.parse_args()

    if OPENSCAD is None:
        sys.exit("OpenSCAD не найден — brew install --cask openscad@snapshot")
    if not args.stl.exists():
        sys.exit(f"нет файла {args.stl}")
    if args.size < 1:
        sys.exit("--size должен быть положительным")

    # со свесами по умолчанию смотрим снизу: сверху красное просто не видно
    requested = args.views or (OVERHANG_VIEWS if args.overhangs else DEFAULT_VIEWS)
    views = [v.strip() for v in requested.split(",") if v.strip()]
    if not views:
        sys.exit("--views пуст")
    unknown = [v for v in views if v not in VIEWS]
    if unknown:
        sys.exit(f"неизвестные виды: {unknown}. Доступно: {list(VIEWS)}")

    try:
        mesh = trimesh.load_mesh(args.stl)
    except Exception as exc:
        sys.exit(f"не удалось прочитать {args.stl}: {exc}")
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.to_mesh()

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)

        if args.overhangs:
            try:
                material = get(args.material)
            except KeyError as exc:
                sys.exit(exc.args[0])
            pieces = split_overhangs(mesh, material.support_angle, workdir)
        else:
            pieces = [(args.stl, BODY_COLOR)]

        cut = parse_section(args.section, mesh) if args.section else None
        source = scad_source(pieces, cut, mesh)
        tiles = [render(source, v, args.size, workdir) for v in views]

    cols = 2 if len(tiles) > 1 else 1
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * args.size, rows * args.size), "white")
    for i, img in enumerate(tiles):
        sheet.paste(img, ((i % cols) * args.size, (i // cols) * args.size))

    # превью — вспомогательный файл: рядом со STL его место только у чужих
    # моделей, у своих он ложится в extras/ этой детали
    tag = ""
    if args.overhangs:
        tag += "-overhangs"
    if cut:
        tag += f"-section-{'xyz'[cut[0]]}"
    out = args.out or aux_path(args.stl, tag, ".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    note = []
    if args.overhangs:
        note.append("свесы красным" if len(pieces) > 1 else "свесов нет")
    if cut:
        note.append(f"разрез по {'xyz'[cut[0]]} на {cut[1]:.2f}")
    print(f"{out}  ({', '.join(views)}{'; ' + ', '.join(note) if note else ''})")


if __name__ == "__main__":
    main()
