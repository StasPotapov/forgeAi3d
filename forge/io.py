"""Repository paths, export of a finished part, and the cache of looked-up dimensions."""

import json
import os
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from build123d import Mesher, Unit, export_step, export_stl


def root() -> Path:
    """The repository root.

    Taken from FORGEAI3D_HOME, otherwise derived from the package itself — so that
    everything works when the repository does not live in ~/dev/forgeAi3d.
    """
    env = os.environ.get("FORGEAI3D_HOME")
    if env:
        path = Path(env).expanduser()
        if not path.is_dir():
            raise RuntimeError(f"FORGEAI3D_HOME points nowhere: {path}")
        return path.resolve()
    return Path(__file__).resolve().parent.parent


def prints_dir() -> Path:
    """The directory of finished parts, created on first use."""
    path = root() / "prints"
    path.mkdir(parents=True, exist_ok=True)
    return path


EXTRAS = "extras"


def model_dir(stem: str) -> Path:
    """The folder of one part: prints/<part>/. Only the STL is in plain sight inside."""
    path = prints_dir() / stem
    path.mkdir(parents=True, exist_ok=True)
    return path


def extras_dir(stem: str) -> Path:
    """Everything that does not go into the slicer: STEP, 3MF, previews, sections."""
    path = model_dir(stem) / EXTRAS
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_step(path: Path) -> Path | None:
    """The STEP of the same part: the file itself, a sibling, or a sibling in extras/.

    The tools take a path to an STL while the exact analysis runs off the STEP — so
    there is no need to look for it by hand.
    """
    if path.suffix.lower() in (".step", ".stp"):
        return path if path.exists() else None
    for candidate in (path.parent, path.parent / EXTRAS, path.parent.parent / EXTRAS):
        for suffix in (".step", ".stp"):
            found = candidate / f"{path.stem}{suffix}"
            if found.exists():
                return found
    return None


def aux_path(source: Path, suffix: str, extension: str) -> Path:
    """Where to put a file derived from a part (a preview, a section).

    If the part is laid out the new way, into its extras/; otherwise next to the
    source, so the tools also work on a file brought in from outside.
    """
    extras = source.parent / EXTRAS
    directory = extras if extras.is_dir() else source.parent
    return directory / f"{source.stem}{suffix}{extension}"


def export_all(part: Any, stem: str, material: str | None = None,
               out: Path | None = None) -> dict[str, Path]:
    """Write the part in all three formats and return the paths.

    STL goes to the printer, STEP is for further edits and the exact analysis in
    check.py, and 3MF is Bambu Studio's native format: it carries the units and the
    metadata that an STL has no room for.

    export_stl and export_step return a bool and raise nothing: on failure they
    quietly leave the old file on disk, so the return value is checked.
    """
    # the directories are created right before the move: if the export fails, no empty
    # folders are left behind in prints/
    main = out or (prints_dir() / stem)
    extras = (main / EXTRAS) if out is None else main
    # the STL is what goes into the slicer — it stays in plain sight, the rest into extras/
    paths = {
        "stl": main / f"{stem}.stl",
        "step": extras / f"{stem}.step",
        "3mf": extras / f"{stem}.3mf",
    }

    # Tessellation is verified before anything reaches the disk: Mesher refuses to
    # assemble a 3MF out of a non-watertight mesh, while export_stl writes one silently
    # and returns True. Otherwise an unverified STL would be left sitting in plain sight.
    mesher = Mesher(unit=Unit.MM)
    try:
        mesher.add_shape(part, part_number=stem)
    except Exception as exc:
        raise RuntimeError(
            f"{stem}: the solid does not tessellate into a watertight mesh ({exc}). "
            "This cannot be printed — look for self-intersections and zero thicknesses "
            "in the model"
        ) from exc
    mesher.add_meta_data("forgeAi3d", "generated", date.today().isoformat(), "str", True)
    if material:
        mesher.add_meta_data("forgeAi3d", "material", material, "str", True)

    # write into a temporary directory and move everything at once: half an export on
    # disk is worse than none — the old file would go to the printer as if it were fresh
    with tempfile.TemporaryDirectory() as tmp:
        staged = {key: Path(tmp) / path.name for key, path in paths.items()}
        for key, writer in (("stl", export_stl), ("step", export_step)):
            if not writer(part, str(staged[key])):
                raise RuntimeError(f"failed to write {paths[key].name}")
        mesher.write(staged["3mf"])
        main.mkdir(parents=True, exist_ok=True)
        extras.mkdir(parents=True, exist_ok=True)
        for key, path in paths.items():
            shutil.move(str(staged[key]), path)

    return paths


# --- cache of other people's hardware dimensions --------------------------------
#
# Dimensions that cannot be measured here (the footprint of a board, the diameter of
# a lens, the pitch of mounting holes) are looked up in a datasheet and stored here —
# so they are not looked up twice and so the source of every number stays visible.

CACHE = "specs_cache.json"


def _cache_path() -> Path:
    return root() / "forge" / CACHE


def load_specs() -> dict[str, dict]:
    path = _cache_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def get_spec(name: str) -> dict | None:
    """Dimensions found earlier for this part. None means they have to be looked up."""
    return load_specs().get(name.strip().lower())


def save_spec(name: str, dimensions: dict[str, float], source: str) -> None:
    """Remember the dimensions that were found, together with where they came from."""
    if not source:
        raise ValueError("a source is mandatory — a number without one is no better than "
                         "an invented one")
    specs = load_specs()
    specs[name.strip().lower()] = {
        "dimensions": dimensions,
        "source": source,
        "found": date.today().isoformat(),
    }
    _cache_path().write_text(
        json.dumps(specs, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
