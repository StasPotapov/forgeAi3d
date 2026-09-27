#!/usr/bin/env python3
"""How far one mesh is from another: two versions of a part, or a remodel against the original.

    uv run tools/compare.py reference.stl candidate.stl [--json] [--tol 0.05]
    uv run tools/compare.py reference.stl candidate.stl --heatmap

The distance is measured both ways, and the two directions answer different questions.
reference → candidate: is there surface in the reference that the candidate has lost?
candidate → reference: does the candidate have surface that the reference never had?
After solidify.py the first one shows the removed inner shell, while the second should be
almost entirely within tolerance — except at the capped rim, which is new surface.

Nothing is aligned: both meshes are taken in their own coordinates, as the models put
them. A remodel from someone else's STL has to be placed where the original sits,
otherwise the whole comparison measures the offset.

--heatmap paints the candidate by its distance to the reference: red where material was
added, blue where it was removed, grey within tolerance.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import trimesh

# the renderer is shared with preview.py, so the heatmap looks like every other preview;
# tools/ is on sys.path because this script is run from there
from preview import DEFAULT_VIEWS, OPENSCAD, VIEWS, render, scad_source, trim

from forge.io import aux_path

SAMPLES = 20000       # points per surface; the maximum additionally checks every vertex
SEED = 0              # the same pair of files gives the same numbers on every run
HEAT_EDGE = 60        # heatmap: triangles are split down to 1/60 of the part's size
HEAT_MAX_FACES = 400_000
TOL_COLOR = "[0.78, 0.78, 0.8]"
# |distance| bins, as multiples of --tol: tol..4·tol, 4·tol..16·tol, beyond
BIN_STEPS = (4, 16)
ADDED_COLORS = ("[0.95, 0.7, 0.55]", "[0.9, 0.45, 0.3]", "[0.75, 0.15, 0.12]")
REMOVED_COLORS = ("[0.6, 0.75, 0.95]", "[0.3, 0.5, 0.9]", "[0.12, 0.2, 0.7]")
UNSIGNED_COLORS = ("[0.95, 0.85, 0.5]", "[0.95, 0.65, 0.2]", "[0.8, 0.4, 0.05]")


def load(path: Path) -> trimesh.Trimesh:
    if not path.exists():
        sys.exit(f"no such file: {path}")
    try:
        mesh = trimesh.load(path, force="mesh")
    except Exception as exc:
        sys.exit(f"could not read {path}: {exc}")
    if len(mesh.faces) == 0:
        sys.exit(f"{path.name}: no triangles in the file")
    return mesh


def one_way(source: trimesh.Trimesh, target: trimesh.Trimesh, tol: float) -> dict:
    """Distances from the surface of source to the surface of target.

    The mean, the percentile and the share within tolerance are taken over points spread
    evenly by area — otherwise a finely tessellated fillet would outweigh a flat wall.
    The maximum also looks at every vertex: a sharp corner is where a change hides, and
    random points may miss it.
    """
    points, _ = trimesh.sample.sample_surface(source, SAMPLES, seed=SEED)
    query = trimesh.proximity.ProximityQuery(target)
    _, dist, _ = query.on_surface(points)
    _, dist_v, _ = query.on_surface(source.vertices)
    worst = int(np.argmax(dist_v))
    if dist_v[worst] >= dist.max():
        max_at = source.vertices[worst]
    else:
        max_at = points[int(np.argmax(dist))]
    return {
        "mean": float(dist.mean()),
        "p95": float(np.percentile(dist, 95)),
        "max": float(max(dist.max(), dist_v.max())),
        "max_at": [round(float(v), 2) for v in max_at],
        "within_tol": float((dist <= tol).mean() * 100),
    }


def summary(ref: trimesh.Trimesh, cand: trimesh.Trimesh, tol: float) -> dict:
    forward = one_way(ref, cand, tol)
    backward = one_way(cand, ref, tol)
    result = {
        "tol": tol,
        "reference": {"volume": float(ref.volume), "size": [float(v) for v in ref.extents],
                      "watertight": bool(ref.is_watertight)},
        "candidate": {"volume": float(cand.volume), "size": [float(v) for v in cand.extents],
                      "watertight": bool(cand.is_watertight)},
        "reference_to_candidate": forward,
        "candidate_to_reference": backward,
        "hausdorff": max(forward["max"], backward["max"]),
        # the symmetric mean: 0 only when both surfaces lie on each other
        "chamfer": (forward["mean"] + backward["mean"]) / 2,
    }
    # the parts barely overlap — almost certainly placed differently rather than reshaped
    ref_box, cand_box = ref.bounds, cand.bounds
    overlap = np.clip(np.minimum(ref_box[1], cand_box[1]) - np.maximum(ref_box[0], cand_box[0]),
                      0, None).prod()
    smaller = min(ref.extents.prod(), cand.extents.prod())
    result["misplaced"] = bool(smaller > 0 and overlap / smaller < 0.5)
    return result


def fmt_size(extents: list[float]) -> str:
    return "×".join(f"{v:.2f}" for v in extents)


def report(name_ref: str, name_cand: str, res: dict) -> None:
    ref, cand = res["reference"], res["candidate"]
    dv = (cand["volume"] - ref["volume"]) / ref["volume"] * 100 if ref["volume"] else 0.0
    print(f"reference: {name_ref}  {fmt_size(ref['size'])} mm, {ref['volume']:.0f} mm³")
    print(f"candidate: {name_cand}  {fmt_size(cand['size'])} mm, {cand['volume']:.0f} mm³ "
          f"({dv:+.1f}%)")
    for key, label in (("reference_to_candidate", "reference → candidate"),
                       ("candidate_to_reference", "candidate → reference")):
        d = res[key]
        # where the worst spot is only matters when it is off at all
        at = ""
        if d["max"] > res["tol"]:
            at = " at (" + ", ".join(f"{v:.2f}" for v in d["max_at"]) + ")"
        print(f"  {label}: mean {d['mean']:.3f}, p95 {d['p95']:.3f}, max {d['max']:.3f} mm"
              f"{at}; {d['within_tol']:.1f}% within {res['tol']} mm")
    print(f"hausdorff {res['hausdorff']:.3f} mm, chamfer {res['chamfer']:.3f} mm")
    if not (ref["watertight"] and cand["watertight"]):
        print("note: a mesh is not watertight — its volume is not meaningful")
    if res["misplaced"]:
        print("warning: the bounding boxes overlap by less than half — the parts are probably "
              "placed differently, and the distances measure that offset")


def heat_pieces(ref: trimesh.Trimesh, cand: trimesh.Trimesh, tol: float,
                workdir: Path) -> tuple[list[tuple[Path, str]], bool]:
    """The candidate split into coloured pieces by the distance of each triangle to the reference.

    The sign comes from the reference being a closed solid: a point of the candidate inside
    it means the surface went in (material removed), outside — it came out (added). An open
    reference has no inside, and then only the distance is painted.
    """
    max_edge = float(cand.extents.max()) / HEAT_EDGE
    vertices, faces = trimesh.remesh.subdivide_to_size(cand.vertices, cand.faces, max_edge,
                                                       max_iter=8)
    if len(faces) > HEAT_MAX_FACES:
        vertices, faces = cand.vertices, cand.faces
    fine = trimesh.Trimesh(vertices, faces, process=False)

    signed = ref.is_watertight
    centers = fine.triangles_center
    if signed:
        # trimesh: positive inside the mesh — the candidate's surface sank into the reference
        dist = -trimesh.proximity.signed_distance(ref, centers)
    else:
        _, dist, _ = trimesh.proximity.ProximityQuery(ref).on_surface(centers)

    magnitude = np.abs(dist)
    edges = [tol, *(tol * s for s in BIN_STEPS), np.inf]
    layers = [("tol", magnitude <= tol, TOL_COLOR)]
    for i in range(3):
        band = (magnitude > edges[i]) & (magnitude <= edges[i + 1])
        if signed:
            layers.append((f"added{i}", band & (dist > 0), ADDED_COLORS[i]))
            layers.append((f"removed{i}", band & (dist < 0), REMOVED_COLORS[i]))
        else:
            layers.append((f"off{i}", band, UNSIGNED_COLORS[i]))

    pieces = []
    for name, mask, color in layers:
        if not mask.any():
            continue
        path = workdir / f"{name}.stl"
        fine.submesh([np.where(mask)[0]], append=True).export(path)
        pieces.append((path, color))
    return pieces, signed


def heatmap(ref: trimesh.Trimesh, cand: trimesh.Trimesh, cand_path: Path, tol: float,
            views: list[str], size: int, out: Path | None) -> tuple[Path, str]:
    """Renders the heatmap and returns the path to it and a legend line."""
    from PIL import Image

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        pieces, signed = heat_pieces(ref, cand, tol, workdir)
        source = scad_source(pieces)
        tiles = trim([render(source, v, size, workdir) for v in views])

    tile_w, tile_h = tiles[0].size
    cols = 2 if len(tiles) > 1 else 1
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w, rows * tile_h), tiles[0].getpixel((0, 0)))
    for i, img in enumerate(tiles):
        sheet.paste(img, ((i % cols) * tile_w, (i // cols) * tile_h))

    out = out or aux_path(cand_path, "-compare", ".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    bands = ", ".join(f"{a:g}–{b:g}" for a, b in
                      zip([tol, *(tol * s for s in BIN_STEPS)], [tol * s for s in BIN_STEPS]))
    bands += f", >{tol * BIN_STEPS[-1]:g} mm"
    legend = ("red = material added, blue = removed" if signed
              else "yellow→brown = distance (the reference is open, so no sign)")
    return out, f"{', '.join(views)}; grey within {tol:g} mm, {legend}; shades {bands}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reference", type=Path, help="what is compared against: the original")
    ap.add_argument("candidate", type=Path, help="the new version")
    ap.add_argument("--tol", type=float, default=0.05,
                    help="distance counted as a match, mm (0.05 by default)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--heatmap", action="store_true",
                    help="paint the candidate by its distance to the reference")
    ap.add_argument("--views", default=DEFAULT_VIEWS)
    ap.add_argument("--size", type=int, default=520)
    ap.add_argument("-o", "--out", type=Path, help="where to put the heatmap PNG")
    args = ap.parse_args()

    if args.tol <= 0:
        sys.exit("--tol has to be positive")
    views = [v.strip() for v in args.views.split(",") if v.strip()]
    if args.heatmap:
        if OPENSCAD is None:
            sys.exit("OpenSCAD not found — brew install --cask openscad@snapshot")
        unknown = [v for v in views if v not in VIEWS]
        if not views or unknown:
            sys.exit(f"unknown views: {unknown}. Available: {list(VIEWS)}")
        if args.size < 1:
            sys.exit("--size has to be positive")

    ref, cand = load(args.reference), load(args.candidate)
    res = summary(ref, cand, args.tol)
    # the picture is rendered before anything is printed, so that --json stays one document
    if args.heatmap:
        out, legend = heatmap(ref, cand, args.candidate, args.tol, views, args.size, args.out)
        res["heatmap"] = str(out)

    if args.json:
        print(json.dumps(res, indent=2))
        return
    report(args.reference.name, args.candidate.name, res)
    if args.heatmap:
        print(f"{out}  ({legend})")


if __name__ == "__main__":
    main()
