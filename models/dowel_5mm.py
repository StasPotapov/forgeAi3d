"""A furniture wall plug for a 3.5x15 screw in a 5 mm hole.

An expanding sleeve. Three things work at once:

* a slit running through the body — the halves spread apart as the screw goes in and
  wedge the plug into the hole; the same slit lets the body squeeze while it is being
  driven in, which is why the barbs can stand noticeably proud of the nominal diameter;
* ring barbs — they hold against pull-out;
* longitudinal ribs — they hold against rotation. Ring barbs do nothing against torque
  at all (the body is axisymmetric, there is nothing to bite with) — which is why the
  first version spun in the hole together with the screw and would not let it drive in.

Print it standing up (the axis of the plug vertical), the way the part is built.
"""
from math import radians, tan

from build123d import *

from forge import clearance, export_all, wall

MAT = "PETG"          # ductile: it holds the screw thread and does not split when wedged

# --- dimensions of someone else's hardware: given by the user, not invented ---
HOLE_D     = 5.0      # the hole in the furniture
HOLE_DEPTH = 11.0     # working seating depth; shortened from 15 — it was too long when tried
SCREW_D    = 3.5      # diameter of the threaded part of the screw
SCREW_L    = 15.0     # length of the screw
HEAD_D     = 7.0      # the head — the flange is made smaller on purpose so the head covers it

# --- what gets turned after a print ---
PILOT_TOP  = 2.9      # the inner hole at the top; larger => the screw goes in easier,
PILOT_BOT  = 2.5      # narrower at the bottom — the screw bites harder and wedges the
                      # sleeve. Both raised by 0.3 against the first version: there the
                      # screw did not cut a thread but tore the plug loose.
BARB_OVER  = 0.35     # how far a barb stands out of the body, per side (was 0.20 — it did not hold)
BARB_RISE  = 1.0      # height of the barb cone; smaller at the same overhang = a steeper lead-in
BARB_FLAT  = 0.9      # a cylindrical land at the tip: a pure wedge barb tapers to zero
                      # thickness, prints as a thread and crushes against the wood
BARB_PITCH = 2.6      # pitch of the barbs
BARB_FIRST = 2.0      # where the first barb starts
RIB_COUNT  = 4        # longitudinal ribs against rotation
RIB_OVER   = 0.45     # how far a rib stands out, per side: it bites into the wall of the hole
RIB_W      = 1.3      # width of a rib at its base
RIB_TIP    = 0.45     # width at the tip: one perimeter line, nothing sharper prints
RIB_ROOT   = 0.3      # how far the base of a rib sinks into the body (a reliable fusion)
RIB_START  = 45       # the first rib at 45°: the ribs clear the slit, two per half
FLANGE_D   = 6.0      # the flange: it keeps the plug from sinking in and hides under the 7 mm head
FLANGE_H   = 0.7
LEAD_IN    = 0.5      # lead-in chamfer at the bottom, on the radius (cut by a knife, see lead_pts)
CHAMFER_TOP = 0.3     # lead-in chamfer for the screw at the top
SLOT_W     = 0.7      # width of the slit right at the pilot hole
SLOT_ANG   = 20.0     # opening angle of the slit wedge: outwards the gap spreads
                      # radially. A straight slit of constant width would cut the
                      # cylinder almost tangentially and leave zero-thickness blades
                      # along its edges
SLOT_TOP   = HOLE_DEPTH - 1.0   # how far it cuts; above that a bridge holds the halves together

RIB_ANGLES = tuple(RIB_START + i * 360 / RIB_COUNT for i in range(RIB_COUNT))

BODY_R = (HOLE_D - 2 * clearance(MAT, "press")) / 2   # a press fit into 5 mm
BARB_R = BODY_R + BARB_OVER
RIB_R  = BODY_R + RIB_OVER
FLANGE_RISE = FLANGE_D / 2 - BODY_R                   # the cone under the flange is exactly 45°
TOP_Z = HOLE_DEPTH + FLANGE_RISE + FLANGE_H

_min_wall = BODY_R - PILOT_TOP / 2
assert _min_wall >= wall(2), f"wall {_min_wall:.2f} is thinner than two perimeters {wall(2)}"
assert FLANGE_D < HEAD_D, "the collar has to hide under the head of the screw"
assert SLOT_TOP < HOLE_DEPTH, "a full-length slit would split the plug into two halves"
assert SLOT_W >= wall(1), f"the slit {SLOT_W} is narrower than a perimeter line — the slicer will fuse it shut"
assert RIB_TIP >= wall(1), f"the rib tip {RIB_TIP} is thinner than a perimeter line {wall(1)}"
SLOT_OUT = 2 * BODY_R * tan(radians(SLOT_ANG / 2))   # width of the gap at the wall of the hole
assert SLOT_OUT >= SLOT_W, "the wedge is narrower than the strip — the gap would come out as sharp blades"

# The profile in axial section: (radius, height), walking the outer contour bottom-up.
# There is deliberately no lead-in chamfer at the bottom here: it is cut by the common
# lead-in knife, and drawing it in the profile as well is not allowed — coincident faces
# break the tessellation when subtracted.
pts: list[tuple[float, float]] = [
    (PILOT_BOT / 2, 0.0),          # the bottom, inner edge
    (BODY_R, 0.0),                 # the bottom, outer edge
]

z = BARB_FIRST
while z + BARB_RISE + BARB_FLAT <= HOLE_DEPTH - 1.0:
    pts += [
        (BODY_R, z),                           # the foot of the barb
        (BARB_R, z + BARB_RISE),               # the end of the shallow lead-in
        (BARB_R, z + BARB_RISE + BARB_FLAT),   # the land: this is what stands in the wood
        (BODY_R, z + BARB_RISE + BARB_FLAT),   # the step down — this holds against pull-out
    ]
    z += BARB_PITCH

pts += [
    (BODY_R, HOLE_DEPTH),
    (FLANGE_D / 2, HOLE_DEPTH + FLANGE_RISE),   # a 45° cone, prints without support
    (FLANGE_D / 2, TOP_Z),
    (PILOT_TOP / 2 + CHAMFER_TOP, TOP_Z),
    (PILOT_TOP / 2, TOP_Z - CHAMFER_TOP),       # closing downwards from here = the cone of the hole
]

# cross-section of a rib in plan: a trapezoid from the sunken base to the flat tip
rib_pts = [
    (BODY_R - RIB_ROOT, -RIB_W / 2),
    (BODY_R - RIB_ROOT,  RIB_W / 2),
    (RIB_R,              RIB_TIP / 2),
    (RIB_R,             -RIB_TIP / 2),
]

# the slit knife in plan: a central strip plus two radial wedges. The strip sets the
# width of the gap at the pilot hole, the wedges carry it outwards with faces normal to
# the surface
KNIFE_R = RIB_R + 1.0
wedge_pts = [
    (0.0, 0.0),
    (KNIFE_R,  KNIFE_R * tan(radians(SLOT_ANG / 2))),
    (KNIFE_R, -KNIFE_R * tan(radians(SLOT_ANG / 2))),
]

# the lead-in knife: a 45° cone shaves off everything that sticks out right at the
# bottom — otherwise the ribs would start with a vertical step and the plug could not be
# started into the hole
LEAD_R = RIB_R + 0.5
lead_pts = [
    (BODY_R - LEAD_IN, 0.0),
    (LEAD_R, 0.0),
    (LEAD_R, LEAD_R - (BODY_R - LEAD_IN)),
]

with BuildPart() as dowel:
    with BuildSketch(Plane.XZ):
        with BuildLine():
            Polyline(*pts, close=True)
        make_face()
    revolve(axis=Axis.Z)

    with BuildSketch(Plane.XY):
        with Locations(*[Rot(0, 0, a) for a in RIB_ANGLES]):
            Polygon(*rib_pts, align=None)
    extrude(amount=HOLE_DEPTH)

    with BuildSketch(Plane.XZ):
        with BuildLine():
            Polyline(*lead_pts, close=True)
        make_face()
    revolve(axis=Axis.Z, mode=Mode.SUBTRACT)

    # the slit knife is dropped below the bottom: a face in the plane of the part's
    # bottom produces the same non-watertight mesh as a coincident chamfer does
    with BuildSketch(Plane.XY.offset(-1.0)):
        Rectangle(SLOT_W, 2 * KNIFE_R)
        with Locations(*[Rot(0, 0, a) for a in (90, 270)]):
            Polygon(*wedge_pts, align=None)
    extrude(amount=SLOT_TOP + 1.0, mode=Mode.SUBTRACT)

paths = export_all(dowel.part, "dowel_5mm", material=MAT)
print(f"a {HOLE_D} mm plug for a {SCREW_D}x{SCREW_L} screw: "
      f"height {TOP_Z:.2f}, seating {HOLE_DEPTH}, wall {_min_wall:.2f}, "
      f"Ø over the barbs {2 * BARB_R:.2f}, Ø over the ribs {2 * RIB_R:.2f}, "
      f"slit {SLOT_W}..{SLOT_OUT:.2f} x {SLOT_TOP}")
for k, v in paths.items():
    print(f"  {k}: {v}")
