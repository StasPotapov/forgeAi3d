#!/usr/bin/env python3
"""Printability check of a part.

    uv run tools/check.py prints/part/part.stl [--material petg] [--nozzle 0.4] [--bed 180x180x180]
    uv run tools/check.py prints/part/part.step --material petg

The geometry is computed by augura: off a STEP it is exact, from B-Rep faces; off an STL
it is approximate — there is neither wall thickness nor small vertical features there. So
a STEP of the same name is looked for next to the STL and used instead. The quality of the
mesh itself (watertightness, normals, number of bodies) is checked off the STL — augura
does not deal with that.

Exit code 1 means problems were found that make printing a bad idea.
Warnings do not affect the exit code: they depend on the orientation of the part, and
that is chosen in the slicer.
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

# A thin wall is a warning in augura. Here it is a failure: a wall thinner than two
# perimeters prints as a void between the contours and the part comes out papery.
# But augura reports the minimum, and the minimum alone means little: on a chamfer, a
# draft angle or the edge of a raised letter the thickness tends to zero by construction.
# So the verdict goes by the share of the surface below the threshold, and the minimum
# stays in the report for reference.
THIN_SAMPLES = 1500
THIN_SHARE_LIMIT = 5.0   # % of the surface beyond which this is no longer a chamfer edge

# A short label for each finding; the details come from augura in its own words, with the
# numbers, and rewriting them would mean paraphrasing the library.
KIND_LABEL = {
    "overhang": "overhang",
    "bridge": "bridge",
    "tip_over": "will tip over",
    "brim": "brim needed",
    "thin_wall": "thin wall",
    "thin_feature": "thin feature",
    "min_feature": "small feature",
    "bed_fit": "does not fit the bed",
    "not_manifold": "mesh is not closed",
}

# How much better the best orientation has to be before it is worth mentioning.
ORIENT_GAIN = 0.25   # the overhang area has to drop by this fraction
ORIENT_FLOOR = 50.0  # mm²; below this there are hardly any overhangs, so stay quiet

# height / shorter side of the base: above this, a tall part on a moving bed gets torn
# off by inertia. augura computes tipping from the centre of mass and knows nothing about
# the acceleration of the bed, so this check is our own
TIPPING_ASPECT = 4.0


def parse_bed(text: str) -> tuple[float, float, float]:
    try:
        dims = tuple(float(v) for v in text.lower().split("x"))
    except ValueError:
        sys.exit(f"--bed expects the format WxDxH, got {text!r}")
    if len(dims) != 3:
        sys.exit(f"--bed expects three dimensions WxDxH, got {text!r}")
    if any(d <= 0 for d in dims):
        sys.exit(f"--bed: the dimensions have to be positive, got {text!r}")
    return dims  # type: ignore[return-value]


def fits_rotated(extents: tuple[float, float, float] | None,
                 bed: tuple[float, float, float]) -> bool:
    """Whether the part fits the bed when turned 90° in the plane of the bed."""
    if extents is None:
        return False
    x, y, z = extents
    return y <= bed[0] and x <= bed[1] and z <= bed[2]


def thin_share(mesh: trimesh.Trimesh, floor: float) -> float | None:
    """Share of the surface thinner than the threshold, %. None means it could not be computed.

    A ray is cast into the solid from a point on the surface, against its normal.
    """
    if not mesh.is_watertight:
        return None
    points, face_ids = trimesh.sample.sample_surface(mesh, THIN_SAMPLES)
    normals = mesh.face_normals[face_ids]
    origins = points - normals * 1e-3          # a little inside, so the start is not hit
    locs, ray_ids, _ = mesh.ray.intersects_location(
        ray_origins=origins, ray_directions=-normals, multiple_hits=False
    )
    if len(ray_ids) == 0:
        return None
    d = np.linalg.norm(locs - origins[ray_ids], axis=1)
    return float((d < floor).mean() * 100.0)


def as_mesh(shape) -> trimesh.Trimesh | None:
    """Tessellation of the STEP — to compute the share even when no mesh came in."""
    try:
        vertices, faces = shape.tessellate(tolerance=0.05)
        return trimesh.Trimesh(
            vertices=[(v.X, v.Y, v.Z) for v in vertices], faces=faces
        )
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model", type=Path, help="STL or STEP")
    ap.add_argument("--material", default="PLA", help="PLA, PETG, PLA-CF, ASA, TPU")
    ap.add_argument("--bed", default=None, help="bed WxDxH, mm (from the printer profile "
                                                "by default)")
    ap.add_argument("--nozzle", type=float, default=None, help="nozzle diameter, mm")
    ap.add_argument("--no-orientation", action="store_true",
                    help="do not search for an orientation (the slowest part of the check)")
    args = ap.parse_args()

    if not args.model.exists():
        sys.exit(f"no such file: {args.model}")

    try:
        mat = get(args.material)
    except KeyError as exc:
        sys.exit(exc.args[0])

    printer = A1_MINI
    if args.nozzle is not None:
        if args.nozzle <= 0:
            sys.exit("--nozzle has to be positive")
        # the typical layer changes along with the nozzle: a 0.8 nozzle does not print a
        # 0.2 layer, otherwise the "step thinner than a layer" check would compare against
        # a number from another printer
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

    print(f"file          {args.model}")
    print(f"material      {mat.name}  (shrinkage {mat.shrink * 100:.1f}%, softens from {mat.hdt:.0f} °C)")
    print(f"printer       {printer.name}, {printer.nozzle} mm nozzle")

    # --- mesh quality: off the STL only, augura cannot do this ---
    mesh = None
    if is_mesh_input:
        try:
            mesh = trimesh.load_mesh(args.model)
        except Exception as exc:
            sys.exit(f"could not read {args.model}: {exc}")
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.to_mesh()

        size = mesh.extents
        extents = (float(size[0]), float(size[1]), float(size[2]))
        print(f"size          {size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f} mm")
        print(f"triangles     {len(mesh.faces)}")
        print(f"bodies        {mesh.body_count}")

        if mesh.is_watertight:
            print(f"volume        {mesh.volume / 1000:.2f} cm³   (watertight mesh)")
        else:
            problems.append("the mesh is not watertight — the slicer may print rubbish, "
                            "it needs repair")
            print("volume        — (the mesh is NOT watertight)")

        if not mesh.is_winding_consistent:
            problems.append("the normals are wound inconsistently")

        degenerate = int((~mesh.nondegenerate_faces(height=1e-4)).sum())
        if degenerate:
            problems.append(f"degenerate triangles: {degenerate}")

    # --- printer profile and material availability ---
    problems += supported(mat, printer)
    if not in_stock(mat):
        warnings.append(f"{mat.name} is not listed as being on the shelf — check whether "
                        "you have a spool")

    # --- geometry: augura ---
    shape = None
    if step is not None:
        try:
            shape = import_step(str(step))
        except Exception as exc:
            if mesh is None:
                sys.exit(f"could not read {step}: {exc}")
            warnings.append(f"could not read {step.name}, the analysis will run off the "
                            f"mesh: {exc}")

    if shape is not None:
        source = f"{step.name} (exact B-Rep)"
        if not is_mesh_input:
            bb = shape.bounding_box()
            extents = (bb.size.X, bb.size.Y, bb.size.Z)
            print(f"size          {bb.size.X:.2f} x {bb.size.Y:.2f} x {bb.size.Z:.2f} mm")
            print(f"bodies        {len(shape.solids())}")
            print(f"volume        {shape.volume / 1000:.2f} cm³")
        report = augura.analyze(
            shape,
            support_angle=mat.support_angle,
            build_volume=printer.bed,
            # augura computes the thin-wall threshold as nozzle * min_perimeters, while
            # two perimeters here means 2 * the line width — otherwise its 0.80 would
            # disagree with wall()'s 0.84
            nozzle=printer.extrusion_width,
            min_perimeters=2,
            min_feature=printer.nozzle,
            max_bridge=mat.max_bridge,
        )
    elif mesh is not None:
        source = f"{args.model.name} (mesh, approximate)"
        warnings.append(
            "small vertical features were not checked — that needs a STEP next to the "
            "mesh; the wall thickness below was computed from triangles, approximately"
        )
        report = augura.analyze_mesh(
            mesh, support_angle=mat.support_angle, build_volume=printer.bed
        )
    else:
        sys.exit(f"could not parse {args.model}")

    floor = wall(2, printer)
    print(f"analysed from {source}")
    print(f"wall          minimum {floor:.2f} mm = 2 perimeters with a {printer.nozzle} mm nozzle")

    # the share of the surface below the threshold is computed once: tessellating the STEP
    # and casting 1500 rays is not free, and there can be more than one thin_wall finding.
    # On a mesh augura does not look at thickness at all, so there it is computed
    # unconditionally: editing someone else's STL is routine, and leaving it unchecked
    # is not an option.
    thin = None
    by_mesh_only = shape is None
    if by_mesh_only or any(f.kind == "thin_wall" for f in report.findings):
        sample = mesh if mesh is not None else as_mesh(shape)
        thin = thin_share(sample, floor) if sample is not None else None

    if by_mesh_only:
        if thin is None:
            warnings.append("the wall thickness could not be estimated — the mesh is not "
                            "watertight")
        elif thin > THIN_SHARE_LIMIT:
            problems.append(
                f"thinner than {floor:.2f} mm — {thin:.1f}% of the surface "
                "(from the mesh, approximately: an exact figure needs a STEP)"
            )
        else:
            print(f"thickness     thinner than {floor:.2f} mm — {thin:.1f}% of the surface (from the mesh)")

    for finding in report.findings:
        # augura's prefix about approximation repeats the "analysed from" line
        message = finding.message.removeprefix("[mesh, approximate] ")
        kind = KIND_LABEL.get(finding.kind, finding.kind)
        text = f"{kind}: {message}"
        if finding.area is not None:
            text = f"{text} ({finding.area:.0f} mm²)"
        if finding.kind == "thin_wall":
            # the share decides, not the minimum: a single chamfer or letter edge is not a defect
            if thin is None:
                warnings.append(f"{text} — the share of the surface this takes up could "
                                "not be estimated")
            elif thin > THIN_SHARE_LIMIT:
                problems.append(f"{text}; thinner than {floor:.2f} mm — {thin:.1f}% of the surface")
            else:
                warnings.append(
                    f"{text}, but that is {thin:.1f}% of the surface — this looks like the "
                    "edge of a chamfer or of a label rather than a wall"
                )
        elif finding.kind == "bed_fit" and fits_rotated(extents, printer.bed):
            # augura measures the bounding box along the axes as they are, while a part is
            # placed on the bed whichever way is convenient
            warnings.append(
                f"{text} — but it fits after a 90° turn in the plane of the bed"
            )
        elif finding.kind == "not_manifold" and mesh is not None and not mesh.is_watertight:
            pass    # the watertightness was already reported above, in our own words
        elif finding.severity == "error":
            problems.append(text)
        elif finding.severity == "warning":
            warnings.append(text)
        else:
            print(f"info          {text}")

    # --- maximum layer height from the smallest vertical step ---
    if shape is not None:
        step_h = augura.min_vertical_feature(shape)
        if step_h is not None:
            # print it only when the step really limits the layer; on a flat plate it
            # equals the height of the plate and says nothing
            if step_h < 5 * printer.layer_height:
                print(f"layer         no thicker than {step_h:.2f} mm "
                      f"(the profile currently says {printer.layer_height} mm)")
            if step_h < printer.layer_height:
                problems.append(
                    f"the smallest step of {step_h:.2f} mm is thinner than the "
                    f"{printer.layer_height} mm layer — the feature will disappear, "
                    "a thinner layer is needed"
                )

    # --- orientation ---
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
                    f"lay it differently — a ({rx:g}, {ry:g}, {rz:g})° rotation leaves "
                    f"{best.overhang_area:.0f} mm² of overhangs instead of {current.overhang_area:.0f}"
                )

    # a tall narrow part on a printer with a moving bed
    if printer.bed_slinger and extents is not None:
        seen = {f.kind for f in report.findings}
        base = min(extents[0], extents[1])
        if base > 0 and extents[2] / base > TIPPING_ASPECT and not (
            seen & {"tip_over", "brim"}      # augura has already said the same thing
        ):
            warnings.append(
                f"a height of {extents[2]:.0f} mm on a base of {base:.0f} mm — the bed of "
                f"the {printer.name} moves, so inertia may tear the part off. "
                "It needs a brim, or printing on its side"
            )

    if warnings:
        print("\nWarnings (they do not affect the exit code):")
        for w in warnings:
            print(f"  - {w}")

    if problems:
        print("\nProblems:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("\nNo problems found.")


if __name__ == "__main__":
    main()
