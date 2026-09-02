#!/usr/bin/env python3
"""Numeric measurement of a part off its STEP.

    uv run tools/measure.py prints/part/part.stl [--json]

A preview shows that the part looks like what was intended; measuring answers whether
the dimensions match. A render looks right even when the geometry is wrong, so the
check goes by numbers first and by eye afterwards.

Holes, bosses, fillets and rounds are told apart by their cylindrical faces: a concave
surface (material on the outside) is a hole, a convex one is a boss, and a partial wrap
means it is not a circle but a rounded corner.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from build123d import Vector, import_step

from forge import find_step

# OCP is the geometry kernel of build123d itself, so there is no point declaring it as
# a separate dependency: without it build123d does not import. build123d gives the
# radius too (Face.radius), but the axis of a cylinder only comes from here.
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_SurfaceType

FULL_WRAP = 5.5      # rad; above this wrap the surface counts as a full circle
PROBE = 0.05         # how far to step off the surface to see where the material is
PROBE_RADIUS = 0.75  # fraction of the radius: where to look past the end face so as
                     # not to land in the pilot hole


def cylinders(shape, solids) -> list[dict]:
    """Breakdown of the cylindrical faces: what each one is, how big, and where."""
    found = []
    for face in shape.faces():
        adaptor = BRepAdaptor_Surface(face.wrapped)
        if adaptor.GetType() != GeomAbs_SurfaceType.GeomAbs_Cylinder:
            continue
        cyl = adaptor.Cylinder()
        radius = cyl.Radius()
        axis = cyl.Axis()
        origin = Vector(axis.Location().X(), axis.Location().Y(), axis.Location().Z())
        direction = Vector(axis.Direction().X(), axis.Direction().Y(), axis.Direction().Z())

        centre = face.center()
        offset = centre - origin
        along = offset.dot(direction)
        radial = offset - direction * along
        if radial.length < 1e-9:
            continue
        unit = radial.normalized()

        outside = origin + unit * (radius + PROBE) + direction * along
        inside = origin + unit * (radius - PROBE) + direction * along
        # try every solid: in a compound a face belongs to any one of them
        if any(body.is_inside(outside) for body in solids):
            concave = True          # material further from the axis — this is a hole
        elif any(body.is_inside(inside) for body in solids):
            concave = False         # material closer to the axis — this is a boss
        else:
            continue                # a thin wall, both probes miss — do not guess

        face_bb = face.bounding_box()
        length = max(
            abs(face_bb.size.X * direction.X),
            abs(face_bb.size.Y * direction.Y),
            abs(face_bb.size.Z * direction.Z),
        )
        wrap = face.area / (radius * length) if radius * length else 0.0

        if wrap >= FULL_WRAP:
            kind = "hole" if concave else "boss"
        else:
            kind = "fillet" if concave else "round"

        dominant = max(("X", direction.X), ("Y", direction.Y), ("Z", direction.Z),
                       key=lambda pair: abs(pair[1]))[0]

        # through or blind: step past both ends of the cylinder and see whether there is
        # still material there. Comparing the length against the bounding box of the part
        # is no good — a chamfer or a raised label shifts the box and lies about "through".
        #
        # The probe is placed off the axis, closer to the wall: in a counterbore the pilot
        # hole starts on the axis past the far end — also empty space, and the hole would
        # look like a through one. At 0.75R there is material there already.
        side = unit * (radius * PROBE_RADIUS)
        ends = [
            origin + direction * (along + length / 2 + PROBE) + side,
            origin + direction * (along - length / 2 - PROBE) + side,
        ]
        through = kind == "hole" and not any(
            body.is_inside(end) for end in ends for body in solids
        )

        found.append({
            "kind": kind,
            "diameter": round(radius * 2, 3),
            "radius": round(radius, 3),
            "length": round(length, 3),
            "axis": dominant,
            "through": through,
            # round produces -0.0, and a "-0" in the report looks like a bug
            "centre": [round(v, 2) + 0.0 or 0.0 for v in (origin.X, origin.Y, origin.Z)],
        })
    return found


def group(items: list[dict]) -> list[dict]:
    """Identical features collapse into one entry with a count."""
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for item in items:
        buckets[(item["kind"], item["diameter"], item["length"], item["axis"],
                 item["through"])].append(item)
    out = []
    for items_ in buckets.values():
        head = dict(items_[0])
        head["count"] = len(items_)
        head["centres"] = [i["centre"] for i in items_]
        head.pop("centre")
        out.append(head)
    return sorted(out, key=lambda i: (i["kind"], -i["diameter"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model", type=Path, help="the part's STEP or STL (the STEP is found "
                                             "on its own)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if not args.model.exists():
        sys.exit(f"no such file: {args.model}")

    step = find_step(args.model)
    if step is None:
        sys.exit("measuring runs off the STEP — a mesh has neither faces nor hole axes, "
                 f"and no STEP was found next to {args.model.name}")

    try:
        shape = import_step(str(step))
    except Exception as exc:
        sys.exit(f"could not read {step}: {exc}")

    solids = shape.solids()
    if not solids:
        sys.exit("there is not a single solid in the file")

    bbox = shape.bounding_box()
    faces = shape.faces()
    types = defaultdict(int)
    for face in faces:
        types[str(face.geom_type).removeprefix("GeomType.")] += 1

    items = group(cylinders(shape, solids))

    if args.json:
        print(json.dumps({
            "file": str(step),
            "size": [round(bbox.size.X, 3), round(bbox.size.Y, 3), round(bbox.size.Z, 3)],
            "volume": round(shape.volume, 1),
            "solids": len(solids),
            "faces": len(faces),
            "face_types": dict(types),
            "features": items,
        }, ensure_ascii=False, indent=2))
        return

    print(f"file       {step}")
    print(f"size       {bbox.size.X:.2f} x {bbox.size.Y:.2f} x {bbox.size.Z:.2f} mm")
    print(f"volume     {shape.volume / 1000:.2f} cm³")
    print(f"solids     {len(solids)}")
    print(f"faces      {len(faces)}  ({', '.join(f'{k.lower()} {v}' for k, v in sorted(types.items()))})")

    if not items:
        print("\nno cylindrical features found")
        return

    print("\nFeatures:")
    for item in items:
        count = f"{item['count']} × " if item["count"] > 1 else ""
        if item["kind"] in ("hole", "boss"):
            size = f"Ø{item['diameter']:.2f}"
            depth = "through" if item["through"] else f"depth {item['length']:.2f}"
            # coordinates across the axis: along it a hole has no coordinate
            across = [i for i, name in enumerate("XYZ") if name != item["axis"]]
            where = "; ".join(
                f"({c[across[0]]:g}, {c[across[1]]:g})" for c in item["centres"][:6]
            )
            more = " …" if len(item["centres"]) > 6 else ""
            labels = "".join("XYZ"[i] for i in across)
            print(f"  {count}{item['kind']} {size}, {depth}, axis {item['axis']}")
            print(f"      centres ({labels}): {where}{more}")
        else:
            print(f"  {count}{item['kind']} R{item['radius']:.2f}, length {item['length']:.2f}, axis {item['axis']}")


if __name__ == "__main__":
    main()
