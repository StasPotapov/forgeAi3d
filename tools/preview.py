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
from PIL import Image, ImageChops

from forge.io import aux_path
from forge.spec import get

# имя -> --camera=tx,ty,tz,rx,ry,rz (дистанция подбирается через --viewall)
VIEWS = {
    "iso":   "0,0,0,55,0,25",
    "iso2":  "0,0,0,55,0,205",
    "iso3":  "0,0,0,55,0,115",
    "iso4":  "0,0,0,55,0,295",
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
# разрез снимает всё за плоскостью реза, значит смотреть надо со стороны
# отброшенной половины — иначе в кадре целая деталь и разреза не видно
SECTION_VIEWS = {0: "iso3,right", 1: "iso2,back", 2: "iso,top"}

BED_CONTACT_TOL = 0.01           # грань считается лежащей на столе, мм
CUT_FACE_TOL = 1e-4              # грань считается лежащей в плоскости реза, мм
OVERHANG_COLOR = "[0.85, 0.25, 0.2]"
CUT_COLOR = "[0.93, 0.62, 0.28]"
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


def split_pieces(mesh: trimesh.Trimesh, workdir: Path,
                 support_angle: float | None = None,
                 cut: tuple[int, float] | None = None) -> list[tuple[Path, str]]:
    """Красит меш по смыслу граней и возвращает пары (файл, цвет).

    Плоскость среза — оранжевым, чтобы было видно, где резали, и по чему меряется
    стенка. Свес — красным: это грань, чья нормаль смотрит вниз круче порога и
    которая не лежит на столе. Свесы считаются по треугольникам, поэтому процент
    здесь и процент в отчёте check.py (augura меряет по точным граням и учитывает
    мосты) могут немного расходиться: задача картинки — показать место, а не число.
    С разрезом меш приходит уже урезанным, поэтому и свесы, и процент считаются
    по оставшейся половине — про печатопригодность целой детали спрашивать check.py.
    """
    rest = np.ones(len(mesh.faces), dtype=bool)
    layers: list[tuple[str, np.ndarray, str]] = []

    if cut is not None:
        axis, position = cut
        on_cut = (np.abs(mesh.triangles[:, :, axis] - position) <= CUT_FACE_TOL).all(axis=1)
        layers.append(("cut_face", on_cut, CUT_COLOR))
        rest &= ~on_cut

    if support_angle is not None:
        limit = np.cos(np.radians(support_angle))
        z_min = mesh.bounds[0][2]
        on_bed = (mesh.triangles[:, :, 2] <= z_min + BED_CONTACT_TOL).all(axis=1)
        overhang = (mesh.face_normals[:, 2] < -limit) & ~on_bed & rest
        # у разрезанной детали площадь среза в знаменатель не идёт — она не печатается
        area = mesh.area_faces[rest].sum()
        share = mesh.area_faces[overhang].sum() / area * 100 if area else 0.0
        half = " оставшейся половины" if cut is not None else ""
        print(f"свесы положе {support_angle:.0f}°: {share:.1f}% площади{half} — красным")
        layers.append(("overhang", overhang, OVERHANG_COLOR))
        rest &= ~overhang

    layers.append(("body", rest, BODY_COLOR))

    pieces = []
    for name, mask, color in layers:
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
    low, high = (float(v) for v in mesh.bounds[:, axis])
    if not position:
        return axis, (low + high) / 2
    try:
        value = float(position)
    except ValueError:
        sys.exit(f"--section: координата должна быть числом, получил {position!r}")
    # за габаритами резать нечего: получится либо целая деталь, либо пустой кадр
    if not low < value < high:
        sys.exit(f"--section: {value:.2f} вне детали, по {axis_name} она занимает "
                 f"{low:.2f}..{high:.2f} мм")
    return axis, value


def scad_source(pieces: list[tuple[Path, str]]) -> str:
    """Сборка .scad: просто цветные куски, вся геометрия уже посчитана."""
    return "\n".join(
        f"color({color}) import({json.dumps(str(path.resolve()))});"
        for path, color in pieces
    ) + "\n"


def run_openscad(args: list[str], what: str) -> None:
    """Запуск с разбором вывода. OpenSCAD на битой геометрии выходит с кодом 0
    и всё равно пишет пустой файл, поэтому мало проверить код возврата — надо
    смотреть в stderr."""
    res = subprocess.run([OPENSCAD, *args], capture_output=True, text=True, check=False)
    if res.returncode != 0 or "ERROR:" in res.stderr:
        errors = [ln for ln in res.stderr.splitlines() if "ERROR:" in ln or "WARNING:" in ln]
        detail = "\n".join(errors) if errors else res.stderr.strip()[-800:]
        sys.exit(f"OpenSCAD не справился ({what}):\n{detail}")


def cut_solid(stl: Path, cut: tuple[int, float], mesh: trimesh.Trimesh,
              workdir: Path) -> Path:
    """Отрезает половину детали и возвращает STL, у которого срез заглушен.

    Резать приходится заранее и в геометрии, а не вычитать куб прямо на рендере:
    быстрое OpenCSG-превью среза не заливает — деталь выходит пустой скорлупой,
    а полный рендер не берёт куски, на которые --overhangs делит меш.
    """
    axis, position = cut
    size = float(mesh.extents.max()) * 4 + 10
    origin = [float(mesh.bounds[0][i]) - size / 2 for i in range(3)]
    origin[axis] = position
    # координаты идут с запасом по знакам: OpenSCAD режет ровно по написанному,
    # а грани среза потом ищутся по той же position с допуском CUT_FACE_TOL
    place = ", ".join(f"{v:.6f}" for v in origin)
    scad = workdir / "cut.scad"
    scad.write_text(
        "difference() {\n"
        f"  import({json.dumps(str(stl.resolve()))});\n"
        f"  translate([{place}]) cube([{size:.6f}, {size:.6f}, {size:.6f}]);\n"
        "}\n"
    )
    out = workdir / "solid.stl"
    run_openscad(["-o", str(out), str(scad)], f"разрез по {'xyz'[axis]}")
    if not out.exists() or out.stat().st_size == 0:
        sys.exit(f"разрез по {'xyz'[axis]} на {position:.2f} не оставил геометрии — "
                 "координата вне детали?")
    return out


def render(source: str, view: str, size: int, workdir: Path) -> Image.Image:
    scad = workdir / f"{view}.scad"
    scad.write_text(source)
    png = scad.with_suffix(".png")
    run_openscad([
        "-o", str(png),
        f"--imgsize={size},{size}",
        f"--camera={VIEWS[view]},0",
        "--viewall", "--autocenter",
        "--colorscheme=Tomorrow",
        str(scad),
    ], f"вид {view}")
    if not png.exists() or png.stat().st_size == 0:
        sys.exit(f"OpenSCAD не отрендерил вид {view}")
    with Image.open(png) as img:
        img.load()          # файлы удалятся вместе с workdir
        return img.copy()


def trim(tiles: list[Image.Image], pad: int = 12) -> list[Image.Image]:
    """Срезает у всех видов общее пустое поле.

    --viewall вписывает деталь в кадр по большему габариту, поэтому у плоской
    пластины половина картинки — фон. Рамка считается общей на все виды, иначе
    масштаб поехал бы от тайла к тайлу и сравнивать их стало бы нельзя.
    """
    boxes = []
    for img in tiles:
        bg = Image.new(img.mode, img.size, img.getpixel((0, 0)))
        box = ImageChops.difference(img, bg).getbbox()
        if box:
            boxes.append(box)
    if not boxes:
        return tiles
    w, h = tiles[0].size
    left = max(min(b[0] for b in boxes) - pad, 0)
    top = max(min(b[1] for b in boxes) - pad, 0)
    right = min(max(b[2] for b in boxes) + pad, w)
    bottom = min(max(b[3] for b in boxes) + pad, h)
    return [img.crop((left, top, right, bottom)) for img in tiles]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stl", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--views", default=None,
                    help=f"по умолчанию {DEFAULT_VIEWS}, с --overhangs {OVERHANG_VIEWS}, "
                         "с --section — пара ракурсов со стороны среза")
    ap.add_argument("--size", type=int, default=520,
                    help="размер рендера одного вида до обрезки полей, px")
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

    try:
        mesh = trimesh.load_mesh(args.stl)
    except Exception as exc:
        sys.exit(f"не удалось прочитать {args.stl}: {exc}")
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.to_mesh()

    cut = parse_section(args.section, mesh) if args.section else None

    # ракурсы по умолчанию зависят от режима: со свесами смотрим снизу (сверху
    # красное просто не видно), с разрезом — со стороны среза
    if args.views:
        requested = args.views
    elif cut:
        requested = SECTION_VIEWS[cut[0]]
        if args.overhangs:
            requested += ",iso_low"     # срез диктует ракурс, но свесы видно только снизу
    elif args.overhangs:
        requested = OVERHANG_VIEWS
    else:
        requested = DEFAULT_VIEWS
    views = [v.strip() for v in requested.split(",") if v.strip()]
    if not views:
        sys.exit("--views пуст")
    unknown = [v for v in views if v not in VIEWS]
    if unknown:
        sys.exit(f"неизвестные виды: {unknown}. Доступно: {list(VIEWS)}")

    support_angle = None
    if args.overhangs:
        try:
            support_angle = get(args.material).support_angle
        except KeyError as exc:
            sys.exit(exc.args[0])

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)

        if cut is not None:
            mesh = trimesh.load_mesh(cut_solid(args.stl, cut, mesh, workdir))

        if cut is None and support_angle is None:
            pieces = [(args.stl, BODY_COLOR)]      # красить нечего, хватит импорта
        else:
            pieces = split_pieces(mesh, workdir, support_angle, cut)

        source = scad_source(pieces)
        tiles = [render(source, v, args.size, workdir) for v in views]

    tiles = trim(tiles)
    tile_w, tile_h = tiles[0].size
    cols = 2 if len(tiles) > 1 else 1
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w, rows * tile_h), tiles[0].getpixel((0, 0)))
    for i, img in enumerate(tiles):
        sheet.paste(img, ((i % cols) * tile_w, (i // cols) * tile_h))

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
        painted = {color for _, color in pieces}
        note.append("свесы красным" if OVERHANG_COLOR in painted else "свесов нет")
    if cut:
        note.append(f"разрез по {'xyz'[cut[0]]} на {cut[1]:.2f}")
    print(f"{out}  ({', '.join(views)}{'; ' + ', '.join(note) if note else ''})")


if __name__ == "__main__":
    main()
