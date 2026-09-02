#!/usr/bin/env python3
"""Rendering a model into a PNG contact sheet through headless OpenSCAD.

    uv run tools/preview.py prints/part/part.stl [-o file.png] [--views iso,top,front,right]
    uv run tools/preview.py prints/part/part.stl --overhangs --material PETG
    uv run tools/preview.py prints/part/part.stl --section y

--overhangs paints the faces that need supports red: the report from check.py says how
much of them there is by area, and the preview shows where exactly.
--section cuts the part in half — the only way to see an internal cavity and the wall
thickness without printing it.
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

# name -> --camera=tx,ty,tz,rx,ry,rz (the distance is picked by --viewall)
VIEWS = {
    "iso":   "0,0,0,55,0,25",
    "iso2":  "0,0,0,55,0,205",
    "iso3":  "0,0,0,55,0,115",
    "iso4":  "0,0,0,55,0,295",
    "top":   "0,0,0,0,0,0",
    "front": "0,0,0,90,0,0",
    "right": "0,0,0,90,0,90",
    "back":  "0,0,0,90,0,180",
    # overhangs face downwards and cannot be made out from above — they need low angles
    "iso_low": "0,0,0,125,0,25",
    "bottom":  "0,0,0,180,0,0",
}

DEFAULT_VIEWS = "iso,top,front,right"
OVERHANG_VIEWS = "iso,iso_low,bottom,front"
# a section removes everything past the cutting plane, so it has to be viewed from the
# side of the discarded half — otherwise the frame holds the whole part and no cut is visible
SECTION_VIEWS = {0: "iso3,right", 1: "iso2,back", 2: "iso,top"}

BED_CONTACT_TOL = 0.01           # a face counts as lying on the bed within this, mm
CUT_FACE_TOL = 1e-4              # a face counts as lying in the cutting plane within this, mm
OVERHANG_COLOR = "[0.85, 0.25, 0.2]"
CUT_COLOR = "[0.93, 0.62, 0.28]"
BODY_COLOR = "[0.78, 0.78, 0.8]"


def find_openscad() -> str | None:
    """The binary from PATH, otherwise a bundle. The stable OpenSCAD-2021.01 is an Intel
    build, so versioned bundles come last."""
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
    """Paints the mesh by the meaning of its faces and returns (file, colour) pairs.

    The cutting plane is orange, so it is clear where the cut went and what the wall is
    measured against. An overhang is red: a face whose normal points down steeper than the
    threshold and that does not lie on the bed. Overhangs here are counted from triangles,
    so this percentage and the one in the check.py report (augura measures exact faces and
    accounts for bridges) may differ slightly: the job of the picture is to show the place,
    not the number. With a section the mesh arrives already trimmed, so both the overhangs
    and the percentage are for the remaining half — ask check.py about the printability of
    the whole part.
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
        # on a sectioned part the area of the cut is left out of the denominator — it is
        # not printed
        area = mesh.area_faces[rest].sum()
        share = mesh.area_faces[overhang].sum() / area * 100 if area else 0.0
        half = " of the remaining half" if cut is not None else ""
        print(f"overhangs shallower than {support_angle:.0f}°: {share:.1f}% of the area{half} — in red")
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
    """`y` or `y:12.5` -> the axis and the coordinate of the cut (the middle by default)."""
    axis_name, _, position = text.partition(":")
    axis_name = axis_name.strip().lower()
    if axis_name not in ("x", "y", "z"):
        sys.exit(f"--section expects x, y or z (or 'y:12.5'), got {text!r}")
    axis = "xyz".index(axis_name)
    low, high = (float(v) for v in mesh.bounds[:, axis])
    if not position:
        return axis, (low + high) / 2
    try:
        value = float(position)
    except ValueError:
        sys.exit(f"--section: the coordinate has to be a number, got {position!r}")
    # there is nothing to cut outside the bounding box: the result is either the whole
    # part or an empty frame
    if not low < value < high:
        sys.exit(f"--section: {value:.2f} is outside the part, along {axis_name} it spans "
                 f"{low:.2f}..{high:.2f} mm")
    return axis, value


def scad_source(pieces: list[tuple[Path, str]]) -> str:
    """Assembling the .scad: just coloured pieces, all the geometry is already computed."""
    return "\n".join(
        f"color({color}) import({json.dumps(str(path.resolve()))});"
        for path, color in pieces
    ) + "\n"


def run_openscad(args: list[str], what: str) -> None:
    """Runs it and parses the output. On broken geometry OpenSCAD exits with code 0 and
    still writes an empty file, so checking the return code is not enough — stderr has to
    be read."""
    res = subprocess.run([OPENSCAD, *args], capture_output=True, text=True, check=False)
    if res.returncode != 0 or "ERROR:" in res.stderr:
        errors = [ln for ln in res.stderr.splitlines() if "ERROR:" in ln or "WARNING:" in ln]
        detail = "\n".join(errors) if errors else res.stderr.strip()[-800:]
        sys.exit(f"OpenSCAD could not do it ({what}):\n{detail}")


def cut_solid(stl: Path, cut: tuple[int, float], mesh: trimesh.Trimesh,
              workdir: Path) -> Path:
    """Cuts off half the part and returns an STL whose cut face is capped.

    The cut has to be made beforehand and in the geometry rather than by subtracting a cube
    at render time: the fast OpenCSG preview does not fill the section — the part comes out
    a hollow shell — and the full render does not take the pieces that --overhangs splits
    the mesh into.
    """
    axis, position = cut
    size = float(mesh.extents.max()) * 4 + 10
    origin = [float(mesh.bounds[0][i]) - size / 2 for i in range(3)]
    origin[axis] = position
    # the coordinates are written out with room to spare on the signs: OpenSCAD cuts
    # exactly where it is told, and the cut faces are later found by that same position
    # within CUT_FACE_TOL
    place = ", ".join(f"{v:.6f}" for v in origin)
    scad = workdir / "cut.scad"
    scad.write_text(
        "difference() {\n"
        f"  import({json.dumps(str(stl.resolve()))});\n"
        f"  translate([{place}]) cube([{size:.6f}, {size:.6f}, {size:.6f}]);\n"
        "}\n"
    )
    out = workdir / "solid.stl"
    run_openscad(["-o", str(out), str(scad)], f"section along {'xyz'[axis]}")
    if not out.exists() or out.stat().st_size == 0:
        sys.exit(f"the section along {'xyz'[axis]} at {position:.2f} left no geometry — "
                 "is the coordinate outside the part?")
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
    ], f"view {view}")
    if not png.exists() or png.stat().st_size == 0:
        sys.exit(f"OpenSCAD did not render the {view} view")
    with Image.open(png) as img:
        img.load()          # the files go away together with workdir
        return img.copy()


def trim(tiles: list[Image.Image], pad: int = 12) -> list[Image.Image]:
    """Crops the empty margin that all the views share.

    --viewall fits the part into the frame by its larger dimension, so on a flat plate half
    the picture is background. The crop box is computed once for all the views, otherwise
    the scale would drift from tile to tile and they could no longer be compared.
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
                    help=f"{DEFAULT_VIEWS} by default, {OVERHANG_VIEWS} with --overhangs, "
                         "and with --section a pair of angles from the side of the cut")
    ap.add_argument("--size", type=int, default=520,
                    help="render size of a single view before the margins are cropped, px")
    ap.add_argument("--overhangs", action="store_true",
                    help="paint the faces that need supports red")
    ap.add_argument("--material", default="PLA",
                    help="it sets the overhang threshold used by --overhangs")
    ap.add_argument("--section", default=None, metavar="AXIS[:COORD]",
                    help="section: x, y, z or y:12.5 (through the middle by default)")
    args = ap.parse_args()

    if OPENSCAD is None:
        sys.exit("OpenSCAD not found — brew install --cask openscad@snapshot")
    if not args.stl.exists():
        sys.exit(f"no such file: {args.stl}")
    if args.size < 1:
        sys.exit("--size has to be positive")

    try:
        mesh = trimesh.load_mesh(args.stl)
    except Exception as exc:
        sys.exit(f"could not read {args.stl}: {exc}")
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.to_mesh()

    cut = parse_section(args.section, mesh) if args.section else None

    # the default angles depend on the mode: with overhangs we look from below (from above
    # the red simply does not show), with a section from the side of the cut
    if args.views:
        requested = args.views
    elif cut:
        requested = SECTION_VIEWS[cut[0]]
        if args.overhangs:
            requested += ",iso_low"     # the cut dictates the angle, but overhangs show only from below
    elif args.overhangs:
        requested = OVERHANG_VIEWS
    else:
        requested = DEFAULT_VIEWS
    views = [v.strip() for v in requested.split(",") if v.strip()]
    if not views:
        sys.exit("--views is empty")
    unknown = [v for v in views if v not in VIEWS]
    if unknown:
        sys.exit(f"unknown views: {unknown}. Available: {list(VIEWS)}")

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
            pieces = [(args.stl, BODY_COLOR)]      # nothing to paint, an import is enough
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

    # a preview is an auxiliary file: its place next to the STL is only for models from
    # outside, while for our own parts it goes into that part's extras/
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
        note.append("overhangs in red" if OVERHANG_COLOR in painted else "no overhangs")
    if cut:
        note.append(f"section along {'xyz'[cut[0]]} at {cut[1]:.2f}")
    print(f"{out}  ({', '.join(views)}{'; ' + ', '.join(note) if note else ''})")


if __name__ == "__main__":
    main()
