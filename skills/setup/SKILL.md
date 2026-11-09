---
name: setup
description: "Set up forgeAi3d runtime dependencies, an external model project and printer profile. Check or update a portable package without modifying its versioned runtime."
argument-hint: "[check | printer | update]"
---

# forgeAi3d setup

Use the current host's shell, questions and image APIs; tool names are capabilities.
Resolve the runtime root two levels above this skill directory. It contains
`pyproject.toml`, `uv.lock`, `forge/`, `tools/`, and model templates. `FORGEAI3D_HOME`
is the person's separate model project, not the installed runtime. Reuse an existing
project; ask for its location only if unknown. Preserve its models and prints.

## Private model folders

Personal models are local working data, not tool source. Before creating any model,
ensure `/models/` is Git-ignored in its containing workspace. Never git-add, commit,
push or package personal model code, references, slicer profiles or generated files.
General commit rules apply to development of this tool, not to these private models.
The tool's public templates live in `examples/`; never put user work there or in `docs/`.

Each model is one self-contained directory:

```
models/part/
    model.py                 # editable source; assets use paths relative to this file
    README.md                # dimensions, rebuild command, settings and known limits
    design.png               # one selected reference, when supplied
    part.stl                 # printing geometry
    part.3mf                 # configured slicer project, when prepared
    assets/                  # SVGs, source meshes, print profiles and other inputs
    extras/                  # STEP, geometric 3MF, previews, reports and old revisions
```

Start work from the selected model folder; read its README and source and inspect its
reference. Keep all model-specific data there. Use `export_all(..., out=Path(__file__).resolve().parent)`
so a relocated model rebuilds in its own folder. `out` is a model directory: STEP and
geometric 3MF go to its `extras/`; a configured root 3MF is not overwritten by CAD export.
`FORGEAI3D_HOME` can name the model folder or the parent workspace; `FORGEAI3D_MODEL_DIR`
explicitly selects a model folder. Without either, the working directory is used;
when it contains `model.py`, exports stay there. From a parent workspace they default
to `models/<stem>/`. Runtime and virtual environment remain separate from personal data.
Do not use runtime package directories as a workspace. Keep model-local hardware
measurements in `extras/specs_cache.json`; copy required profiles into the folder.

For migration, back up first, move all inputs and outputs together, resolve relative
paths, verify file hashes and a rebuild, then remove superseded loose locations.
Do not fabricate missing CAD source for a supplied STL: label it as mesh-only.
Do not overwrite a configured project with a geometry-only 3MF. Re-slice explicitly
when geometry changes, verify one instance unless requested otherwise, and keep the
user's printer, material, plate and process settings.


## Check and install

Check Python (3.13+), uv and OpenSCAD using the actual OS. Read the runtime's locked
requirements. Dependency installation requires the requested setup scope; do not
install merely because the modeling skill was discovered. Keep the environment
outside an immutable package:

```sh
export FORGEAI3D_HOME="<absolute-model-project>"
export FORGEAI3D_RUNTIME="<real-runtime-root>"
export UV_PROJECT_ENVIRONMENT="${XDG_DATA_HOME:-$HOME/.local/share}/forgeAi3d/venv"
export PYTHONDONTWRITEBYTECODE=1
uv sync --frozen --project "$FORGEAI3D_RUNTIME"
```

Do not write Claude settings from another client. Persist nonsecret project paths
through that client's supported configuration or a project instruction; credentials
are unnecessary. `models/` contains private per-model folders in the writable workspace. Copy only the
requested template there and preserve existing files. Run scripts using absolute
runtime paths and `uv run --frozen --project "$FORGEAI3D_RUNTIME" ...` from the model
project. No repository clone is needed when the complete runtime package is present.

## Printer and filaments

Read `forge/spec.py` for shipped defaults. Ask only for unknown hardware or material
facts. Write overrides to `$FORGEAI3D_HOME/forge-profile.toml` (or an explicit
`FORGEAI3D_PROFILE` path); never edit installed `forge/spec.py`:

```toml
available = ["PLA", "PETG"]
[printer]
name = "Example printer"
bed = [180.0, 180.0, 180.0]
nozzle = 0.4
extrusion_width = 0.42
layer_height = 0.2
enclosed = false
hardened_nozzle = false
ams = false
bed_slinger = true
[materials.PETG.clearances]
slip = 0.30
```

Only changed fields are needed. The loader merges printer/material fields with
shipped defaults and validates types, positive dimensions and known material names.
A material not in the shipped table requires a runtime change with its full verified
properties, not a guessed partial override. Invalid or explicitly missing profiles
fail instead of silently falling back. Profile lookup precedence is:
`FORGEAI3D_PROFILE`, otherwise `forge-profile.toml` under `FORGEAI3D_HOME`,
otherwise under `FORGEAI3D_MODEL_DIR`, otherwise the current directory.
Keep workspace `FORGEAI3D_HOME` unchanged when selecting a model with `FORGEAI3D_MODEL_DIR`.
A missing implicit profile uses shipped defaults; an explicitly named missing file fails.
Keep `forge-profile.toml` Git-ignored; never publish personal calibration. `wall`, material checks and tool imports see
the profile on process startup. Restart a long-running Python process after editing.

## Verify and update

For a requested end-to-end setup, copy `examples/fit_test.py` to `models/fit_test_pla/model.py`,
run it, then packaged `tools/measure.py`, `tools/preview.py` and `tools/check.py` on
its output. Open the preview with the host's image tool. Report missing system
dependencies separately; help/import checks alone do not prove printable geometry.

For an installed pinned package, rebuild/update it through AI Workspace and retain
the previous workspace for rollback. Never git-pull, edit or create a venv in the
installed snapshot. Developers may update an explicit owner checkout using that
repository's Git rules; this does not update an installed package until rebuilt.
The external model project, printer profile and output files survive replacement.

Report runtime and model-project paths, actual printer profile, checks performed
and any missing dependencies. Do not claim setup or a visual verdict without evidence.
