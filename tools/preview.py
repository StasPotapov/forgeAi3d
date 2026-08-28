#!/usr/bin/env python3
"""Рендер STL в PNG-контактный лист через headless OpenSCAD.

    uv run tools/preview.py out/part.stl [-o out/part.png] [--views iso,top,front,right]
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

# имя -> --camera=tx,ty,tz,rx,ry,rz (дистанция подбирается через --viewall)
VIEWS = {
    "iso":   "0,0,0,55,0,25",
    "iso2":  "0,0,0,55,0,205",
    "top":   "0,0,0,0,0,0",
    "front": "0,0,0,90,0,0",
    "right": "0,0,0,90,0,90",
    "back":  "0,0,0,90,0,180",
}


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


def render(stl: Path, view: str, size: int, workdir: Path) -> Image.Image:
    scad = workdir / f"{view}.scad"
    scad.write_text(f"import({json.dumps(str(stl.resolve()))});\n")
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
    ap.add_argument("--views", default="iso,top,front,right")
    ap.add_argument("--size", type=int, default=520, help="сторона одного вида, px")
    args = ap.parse_args()

    if OPENSCAD is None:
        sys.exit("OpenSCAD не найден — brew install --cask openscad@snapshot")
    if not args.stl.exists():
        sys.exit(f"нет файла {args.stl}")
    if args.size < 1:
        sys.exit("--size должен быть положительным")

    views = [v.strip() for v in args.views.split(",") if v.strip()]
    if not views:
        sys.exit("--views пуст")
    unknown = [v for v in views if v not in VIEWS]
    if unknown:
        sys.exit(f"неизвестные виды: {unknown}. Доступно: {list(VIEWS)}")

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        tiles = [render(args.stl, v, args.size, workdir) for v in views]

    cols = 2 if len(tiles) > 1 else 1
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * args.size, rows * args.size), "white")
    for i, img in enumerate(tiles):
        sheet.paste(img, ((i % cols) * args.size, (i // cols) * args.size))

    out = args.out or args.stl.with_suffix(".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"{out}  ({', '.join(views)})")


if __name__ == "__main__":
    main()
