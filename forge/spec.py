"""Printer profile and filament reference.

The numbers here are typical practical values, not datasheet constants. Shrinkage
and clearances depend on the particular spool, the humidity and the print profile,
so before a part that matters they are worth calibrating with a test print
(a set of holes in 0.05 mm steps is printed and the fit is picked off it).
"""

from dataclasses import dataclass, replace
import math
import os
from pathlib import Path
import tomllib

MM = float


@dataclass(frozen=True)
class Printer:
    name: str
    bed: tuple[MM, MM, MM]      # build volume W x D x H
    nozzle: MM
    extrusion_width: MM         # perimeter line width for this nozzle
    layer_height: MM            # typical layer height
    enclosed: bool              # is there an enclosure
    hardened_nozzle: bool       # can it run abrasive filaments
    ams: bool                   # is there an AMS lite
    bed_slinger: bool           # the bed travels in Y => tall parts get shaken

    @property
    def max_height(self) -> MM:
        return self.bed[2]


@dataclass(frozen=True)
class Material:
    name: str
    shrink: float               # linear shrinkage, as a fraction (0.006 = 0.6%)
    clearances: dict[str, MM]   # clearance PER SIDE for each type of fit
    support_angle: float        # a face tilted less than this to horizontal needs support
    max_bridge: MM              # bridge length spanned without sagging
    hdt: float                  # softening temperature, °C
    ductile: bool               # ductile (takes snap fits) or brittle
    abrasive: bool              # needs a hardened nozzle
    needs_enclosure: bool       # needs an enclosure
    ams_safe: bool              # can it be fed through an AMS lite
    heat_inserts: str           # how well it holds brass heat-set inserts: good / ok / poor
    note: str


A1_MINI = Printer(
    name="Bambu Lab A1 mini",
    bed=(180.0, 180.0, 180.0),
    nozzle=0.4,
    extrusion_width=0.42,
    layer_height=0.2,
    enclosed=False,
    hardened_nozzle=False,
    ams=False,
    bed_slinger=True,
)


MATERIALS: dict[str, Material] = {
    "PLA": Material(
        name="PLA",
        shrink=0.003,
        clearances={"press": 0.0, "snug": 0.10, "slip": 0.20, "free": 0.35},
        support_angle=40.0,
        max_bridge=25.0,
        hdt=55.0,
        ductile=False,
        abrasive=False,
        needs_enclosure=False,
        ams_safe=True,
        heat_inserts="ok",
        note="Stiff and brittle. Snap fits break; fillets in corners are mandatory. "
             "Softens in a car in summer.",
    ),
    "PETG": Material(
        name="PETG",
        shrink=0.006,
        clearances={"press": 0.05, "snug": 0.15, "slip": 0.30, "free": 0.45},
        support_angle=45.0,
        max_bridge=12.0,
        hdt=75.0,
        ductile=True,
        abrasive=False,
        needs_enclosure=False,
        ams_safe=True,
        heat_inserts="good",
        note="Ductile, takes impact and heat-set inserts. Bridges worse and supports fuse "
             "to it for good, so a part is better designed to do without them.",
    ),
    # Below is what is not on the shelf right now. Kept so that supported() can
    # explain why a part in this material will not run on an A1 mini.
    "PLA-CF": Material(
        name="PLA-CF",
        shrink=0.002,
        clearances={"press": 0.0, "snug": 0.10, "slip": 0.15, "free": 0.30},
        support_angle=40.0,
        max_bridge=15.0,
        hdt=60.0,
        ductile=False,
        abrasive=True,
        needs_enclosure=False,
        ams_safe=True,
        heat_inserts="ok",
        note="Stiffer and more dimensionally stable than plain PLA, but noticeably more "
             "brittle. Requires a hardened nozzle.",
    ),
    "ASA": Material(
        name="ASA",
        shrink=0.010,
        clearances={"press": 0.05, "snug": 0.15, "slip": 0.25, "free": 0.40},
        support_angle=45.0,
        max_bridge=15.0,
        hdt=95.0,
        ductile=True,
        abrasive=False,
        needs_enclosure=True,
        ams_safe=True,
        heat_inserts="good",
        note="Outdoor-grade and heat resistant, but it warps and delaminates on an open "
             "printer.",
    ),
    "TPU": Material(
        name="TPU",
        shrink=0.008,
        clearances={"press": 0.10, "snug": 0.25, "slip": 0.40, "free": 0.60},
        support_angle=50.0,
        max_bridge=5.0,
        hdt=60.0,
        ductile=True,
        abrasive=False,
        needs_enclosure=False,
        ams_safe=False,
        heat_inserts="poor",
        note="Flexible, 95A. The direct drive of the A1 mini handles it, but it has to be "
             "fed from an external spool — flexibles do not run through an AMS lite.",
    ),
}

AVAILABLE = ("PLA", "PETG")   # what is actually on the shelf



def _overrides(current, changes):
    """Validate TOML values against the existing typed profile; reject unknown fields."""
    if not isinstance(changes, dict):
        raise ValueError("profile section must be a table")
    values = {}
    for key, value in changes.items():
        if not hasattr(current, key) or key not in current.__dataclass_fields__:
            raise ValueError(f"unknown profile field: {key}")
        old = getattr(current, key)
        if isinstance(old, bool):
            valid = isinstance(value, bool)
        elif isinstance(old, float):
            valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
            if key in {"nozzle", "extrusion_width", "layer_height", "max_bridge"}:
                valid = valid and value > 0
            if key == "shrink":
                valid = valid and value < 1
        elif isinstance(old, tuple):
            valid = isinstance(value, list) and len(value) == 3 and all(
                type(v) in (int, float) and math.isfinite(v) and v > 0 for v in value)
            value = tuple(value) if valid else value
        elif isinstance(old, dict):
            valid = isinstance(value, dict) and not (value.keys() - old.keys()) and all(
                type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in value.values())
            value = {**old, **value} if valid else value
        else:
            valid = isinstance(value, str) and bool(value.strip())
        if not valid:
            raise ValueError(f"invalid profile value: {key}")
        values[key] = value
    return replace(current, **values)


def _load_profile():
    # A workspace profile remains shared when MODEL_DIR selects an output bundle.
    workspace = Path(os.environ.get("FORGEAI3D_HOME") or
                     os.environ.get("FORGEAI3D_MODEL_DIR") or Path.cwd()).expanduser()
    explicit = os.environ.get("FORGEAI3D_PROFILE")
    path = Path(explicit).expanduser() if explicit else workspace / "forge-profile.toml"
    if not path.exists() and not explicit:
        return A1_MINI, MATERIALS, AVAILABLE
    data = tomllib.loads(path.read_text())
    if data.keys() - {"printer", "materials", "available"}:
        raise ValueError("unknown forge profile section")
    printer = _overrides(A1_MINI, data.get("printer", {}))
    materials = dict(MATERIALS)
    overrides = data.get("materials", {})
    if not isinstance(overrides, dict) or overrides.keys() - materials.keys():
        raise ValueError("material overrides must name a shipped material")
    for name, changes in overrides.items():
        material = _overrides(materials[name], changes)
        if material.name != name:
            raise ValueError("material name is a stable identifier and cannot be changed")
        materials[name] = material
    available = data.get("available", list(AVAILABLE))
    if not isinstance(available, list) or not all(isinstance(v, str) and v in materials for v in available):
        raise ValueError("available must list known materials")
    return printer, materials, tuple(available)


A1_MINI, MATERIALS, AVAILABLE = _load_profile()


def in_stock(material: "str | Material") -> bool:
    """Whether this filament is on the shelf. Not a ban, just a reason to warn."""
    mat = material if isinstance(material, Material) else get(material)
    return mat.name in AVAILABLE


def get(material: str) -> Material:
    """A material by name; case and dashes do not matter: 'petg', 'pla_cf'."""
    key = material.strip().upper().replace("_", "-")
    if key in MATERIALS:
        return MATERIALS[key]
    raise KeyError(f"unknown material {material!r}; known ones: {', '.join(MATERIALS)}")


def wall(perimeters: int = 2, printer: Printer = A1_MINI) -> MM:
    """Wall thickness in whole perimeters — so the slicer leaves no void inside.

    2 perimeters is the minimum for a wall that carries nothing, 3-4 for one that does.
    """
    if perimeters < 1:
        raise ValueError("there must be at least 1 perimeter")
    return round(perimeters * printer.extrusion_width, 3)


def clearance(material: str | Material, fit: str = "slip") -> MM:
    """Clearance PER SIDE for a fit.

    press — press fit, driven in with a mallet; snug — goes in with hand force;
    slip — slides freely; free — deliberately loose.

    A hole for an 8 mm shaft with a sliding fit:
        d = 8 + 2 * clearance("PETG", "slip")
    """
    mat = material if isinstance(material, Material) else get(material)
    if fit not in mat.clearances:
        raise KeyError(f"unknown fit {fit!r}; known ones: {', '.join(mat.clearances)}")
    return mat.clearances[fit]


def compensate_shrink(nominal: MM, material: str | Material) -> MM:
    """Grow the size in the model so that after cooling it comes out at nominal."""
    mat = material if isinstance(material, Material) else get(material)
    return round(nominal / (1.0 - mat.shrink), 3)


def supported(material: str | Material, printer: Printer = A1_MINI) -> list[str]:
    """Reasons this material will not run on this printer. Empty means all good."""
    mat = material if isinstance(material, Material) else get(material)
    reasons: list[str] = []
    if mat.needs_enclosure and not printer.enclosed:
        reasons.append(f"{mat.name} needs an enclosure, and the {printer.name} is open")
    if mat.abrasive and not printer.hardened_nozzle:
        reasons.append(f"{mat.name} is abrasive, a hardened nozzle is required")
    if not mat.ams_safe and printer.ams:
        reasons.append(f"{mat.name} cannot be fed through an AMS lite, only from an external spool")
    return reasons
