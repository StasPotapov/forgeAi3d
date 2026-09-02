#!/usr/bin/env python3
"""Filling an internal cavity in someone else's mesh.

    uv run tools/solidify.py incoming.stl              # only show what is inside
    uv run tools/solidify.py incoming.stl --fill 1     # fill void number 1

A hollow model (a tube, vase mode, a scanned shell) prints hollow: the slicer honestly
sees the cavity and lays no infill inside. Here the inner shell is removed and the hole
left behind is capped — the result is a solid whose filling is up to the slicer.

The outer geometry is left alone: exactly the original triangles of the outer surface are
kept, so the profile and the sharp edges survive 1:1.

**What to fill is the human's choice.** To a ray, the wall of a through hole looks just as
internal as the cavity of a tube, and geometry cannot reliably tell them apart: a tube's
cavity is open too — at its end. So without --fill the tool writes nothing and only lists
the voids it found.
"""
import argparse
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import trimesh
from trimesh import grouping, repair

from forge.io import model_dir

# How far the start of a ray is offset from the surface, mm. Small enough not to jump
# across a wall thinner than a millimetre.
RAY_EPS = 1e-3


def load_source(path: Path) -> trimesh.Trimesh:
    mesh = trimesh.load(path, force="mesh")
    if not mesh.is_watertight:
        raise SystemExit(
            f"{path.name}: the mesh is not watertight — repair it first, "
            "otherwise the inner surface cannot be told from the outer one"
        )
    return mesh


def inner_faces(mesh: trimesh.Trimesh) -> np.ndarray:
    """Mask of the faces looking into empty space inside the bounding box of the solid.

    The test: a ray cast from a triangle along its normal (that is, towards the empty
    space in front of it) hits the solid again. Outwards such a ray goes off to infinity;
    into a cavity or a hole it runs into the wall opposite.
    """
    origins = mesh.triangles_center + mesh.face_normals * RAY_EPS
    _, hit_rays, _ = mesh.ray.intersects_location(
        origins, mesh.face_normals, multiple_hits=False
    )
    mask = np.zeros(len(mesh.faces), dtype=bool)
    mask[hit_rays] = True
    return mask


def voids(mesh: trimesh.Trimesh, inner: np.ndarray) -> list[np.ndarray]:
    """Connected internal surfaces — each one bounds a void of its own."""
    adjacency = mesh.face_adjacency
    linked = adjacency[inner[adjacency[:, 0]] & inner[adjacency[:, 1]]]
    components = trimesh.graph.connected_components(linked, nodes=np.where(inner)[0])
    return sorted((np.asarray(c) for c in components), key=len, reverse=True)


def describe(mesh: trimesh.Trimesh, faces: np.ndarray) -> str:
    sub = mesh.submesh([faces], append=True)
    size = sub.extents
    open_edges = len(grouping.group_rows(sub.edges_sorted, require_count=1))
    return (f"{len(faces):5d} triangles, area {mesh.area_faces[faces].sum():8.1f} mm², "
            f"size {size[0]:.1f}×{size[1]:.1f}×{size[2]:.1f} mm, open edges {open_edges}")


def boundary_loops(mesh: trimesh.Trimesh) -> list[list[int]]:
    """Every closed loop of the open rim, not just one per component."""
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
                "a rim with no closed loop — there is nothing to cap it with; "
                "repair the mesh before filling"
            )
        loops.extend(cycles)
    return loops


def cap_holes(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Caps the open loops with a fan of triangles from the centre of each loop.

    repair.fill_holes gives up on non-planar rims with dozens of edges, and after the
    inner shell is cut away that is exactly what they are. A fan from the centroid copes.
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
    """Keeps the solid itself and nothing else.

    The floor of a cavity often stays behind inside the material as a separate film of
    zero volume. It does not get in the way of printing, but the slicer sees two bodies
    instead of one.
    """
    bodies = mesh.split(only_watertight=False)
    if len(bodies) <= 1:
        return mesh
    # the centre of mass of a zero-volume film cannot be computed — numpy complains about
    # division by zero, even though the volume is exactly what we want from it
    with np.errstate(invalid="ignore", divide="ignore"):
        keep = max(bodies, key=lambda b: abs(b.volume))
        dropped = sum(abs(b.volume) for b in bodies if b is not keep)
    if dropped > 1e-6:
        raise SystemExit(f"a piece with a non-zero volume of {dropped:.3f} mm³ was dropped")
    print(f"zero-volume films discarded: {len(bodies) - 1}")
    return keep


def parse_choice(text: str, count: int) -> list[int]:
    if text.strip().lower() == "all":
        return list(range(count))
    picked = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk.isdigit():
            sys.exit(f"--fill expects void numbers separated by commas, or all, got {chunk!r}")
        number = int(chunk)
        if not 1 <= number <= count:
            sys.exit(f"--fill: there is no void {number}, there are {count} in total")
        picked.append(number - 1)
    return sorted(set(picked))


def solidify(src: trimesh.Trimesh, chosen: list[np.ndarray]) -> trimesh.Trimesh:
    mask = np.zeros(len(src.faces), dtype=bool)
    for faces in chosen:
        mask[faces] = True

    shell = src.submesh([np.where(~mask)[0]], append=True)
    boundary = grouping.group_rows(shell.edges_sorted, require_count=1)
    print(f"internal triangles removed: {mask.sum()} of {len(src.faces)}")
    print(f"open edges after removal: {len(boundary)}")

    shell = cap_holes(shell)
    shell.update_faces(shell.nondegenerate_faces())
    shell = drop_flat_scraps(shell)

    if not shell.is_watertight:
        raise SystemExit("capping failed — the solid is still leaky")
    if shell.volume <= src.volume:
        raise SystemExit("the volume did not grow — the void was not filled")

    print(f"volume: was {src.volume:.0f} mm³ → now {shell.volume:.0f} mm³")
    print(f"size: {np.round(shell.extents, 2)} mm")
    return shell


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path, help="the source mesh (STL, OBJ, 3MF...)")
    ap.add_argument("-o", "--out", type=Path,
                    help="where to write it (prints/<name>_solid/<name>_solid.stl by default)")
    ap.add_argument("--fill", metavar="N[,M] | all",
                    help="numbers of the voids from the list above; without this flag no "
                         "file is written")
    args = ap.parse_args()

    if not args.src.exists():
        sys.exit(f"no such file: {args.src}")

    src = load_source(args.src)
    inner = inner_faces(src)
    if not inner.any():
        raise SystemExit("no internal surfaces found — the solid is already solid")

    found = voids(src, inner)
    print(f"{args.src.name}: {src.volume:.0f} mm³, internal voids found: {len(found)}\n")
    for i, faces in enumerate(found, 1):
        print(f"  [{i}] {describe(src, faces)}")

    if not args.fill:
        print("\nWhich of these to fill is up to you: the wall of a through hole looks just")
        print("as internal as the cavity of a tube. Fill the first: --fill 1, all: --fill all")
        return

    stem = f"{args.src.stem}_solid"
    out = args.out or model_dir(stem) / f"{stem}.stl"
    if out.resolve() == args.src.resolve():
        sys.exit("the result would overwrite the source — pass a different -o")

    chosen = [found[i] for i in parse_choice(args.fill, len(found))]
    print()
    solid = solidify(src, chosen)
    out.parent.mkdir(parents=True, exist_ok=True)
    solid.export(out)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
