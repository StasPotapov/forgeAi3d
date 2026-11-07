---
name: setup
description: "Sets up the forgeAi3d workspace and checks it: git, uv, OpenSCAD, the workspace clone in $FORGEAI3D_HOME (~/dev/forgeAi3d by default) with its Python environment, the printer and the filaments in forge/spec.py, and a test part built, measured, previewed and checked end to end. Updates the workspace after a plugin update. Use it for \"set up forgeAi3d\", \"install the 3D printing tools\", \"uv run fails in forgeAi3d\", \"OpenSCAD not found\", \"I have another printer\", \"update forgeAi3d\", and when the forgeAi3d skill finds no workspace."
argument-hint: "[check | printer | update]"
allowed-tools:
  - Bash
  - Read
  - Edit
  - Write
  - AskUserQuestion
---

# forgeAi3d setup

The forgeAi3d skill models parts in a **workspace**: a clone of the forgeAi3d repository with the
tools (`tools/`), the printer and filament reference (`forge/spec.py`), part sources (`models/`) and
exports (`models/`). The plugin carries only the skills, and its cache is replaced on every update, so
the workspace is a clone of its own outside the cache. The person's parts, prints and calibrated
clearances live there and survive plugin updates.

```
W="${FORGEAI3D_HOME:-$HOME/dev/forgeAi3d}"     # the workspace; set it in every Bash call
```

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


## Check

Run these and tell the person in two or three lines what is there and what is missing:

```bash
W="${FORGEAI3D_HOME:-$HOME/dev/forgeAi3d}"
git --version; uv --version
command -v openscad || find /Applications -maxdepth 1 -name 'OpenSCAD*.app' 2>/dev/null
test -f "$W/pyproject.toml" && git -C "$W" status -sb | head -1 && git -C "$W" describe --tags --always
test -d "$W/.venv" && echo "venv ok"
```

The plugin's own version is `version` in `${CLAUDE_SKILL_DIR}/../../.claude-plugin/plugin.json`
(if `${CLAUDE_SKILL_DIR}` is not substituted, take the folder from the "Base directory for this skill"
line).

## Install

Ask once with `AskUserQuestion` what is missing and how to install it; install only after a yes.

1. **uv** — macOS `brew install uv`, otherwise `curl -LsSf https://astral.sh/uv/install.sh | sh`
   (docs.astral.sh/uv). uv brings the Python the workspace needs (3.13) by itself.
2. **OpenSCAD** — headless renders and section cuts. macOS: `brew install --cask openscad@snapshot`
   (the stable cask is a 2021 Intel build that macOS complains about). Linux: `sudo apt install openscad`
   — the person runs commands with `sudo`. The tools find `openscad` on `PATH` and in `/Applications`.
3. **The workspace.** Ask where to keep it; the default is `~/dev/forgeAi3d`.
   `git clone https://github.com/StasPotapov/forgeAi3d.git <folder>`. A folder other than the default
   needs `FORGEAI3D_HOME`: offer to add `"FORGEAI3D_HOME": "<folder>"` to `env` in
   `~/.claude/settings.json` (create the file with `{"env": {...}}` if it does not exist), so every
   session finds it. If the folder already has a forgeAi3d clone,
   use it — do not clone a second one.
4. **The environment** — `cd "$W" && uv sync`. It downloads build123d, trimesh and the rest (several
   hundred MB the first time).

## The printer and the filaments

`forge/spec.py` in the workspace describes one printer and the spools on the shelf; the checks and the
clearances come from there. Out of the box it is a Bambu Lab A1 mini (bed 180×180×180, 0.4 nozzle)
with PLA and PETG. Ask which printer and which filaments the person has. A different printer: read the
file, then change the values of the `A1_MINI = Printer(...)` entry — `name`, `bed`, `nozzle`,
`extrusion_width`, `layer_height`, `enclosed`, `hardened_nozzle`, `ams`, `bed_slinger` (all of them
are required). Keep the variable name `A1_MINI`: `tools/check.py` and the defaults in `spec.py`
import it. Other spools: `AVAILABLE`, and for a material that is not there yet copy an existing
`MATERIALS` entry and change its values. Then commit these local changes in the workspace
(`git -C "$W" commit -am "my printer and filaments"`): an update merges them, while uncommitted
changes would stop `git pull`. Calibrating clearances is optional and comes
later: copy `examples/fit_test.py` into a private model folder, print that copy and write the real numbers into `clearances` — the forgeAi3d skill
knows how.

## Check that it works

```bash
cd "$W"
mkdir -p models/fit_test_pla
test -e models/fit_test_pla/model.py || cp examples/fit_test.py models/fit_test_pla/model.py
uv run python models/fit_test_pla/model.py                                     # -> models/fit_test_pla/
uv run tools/measure.py models/fit_test_pla/fit_test_pla.stl
uv run tools/preview.py models/fit_test_pla/fit_test_pla.stl
uv run tools/check.py models/fit_test_pla/fit_test_pla.stl --material PLA
```

All four must finish without an error; open the preview PNG the tool prints with Read and look at it.
`preview.py` failing on OpenSCAD — the binary is not found or not runnable: back to step 2.

## After a plugin update

The skills update with the plugin; the workspace does not. Every plugin release has a tag
`v<version>` in the repository. Check that the workspace has it:

```bash
git -C "$W" fetch --tags -q && git -C "$W" merge-base --is-ancestor "v<plugin version>" HEAD && echo "up to date"
```

Not an ancestor — the workspace is older than the plugin: update it. Uncommitted changes first:
show `git -C "$W" status -s` to the person and commit only tool configuration changes (`spec.py`); never commit personal models or put them aside
with `git stash` — `git pull` refuses to run over them. Then `git -C "$W" pull` (it merges the
person's commits); on a conflict show it and do not resolve it alone. Then `uv sync` and the check
above. A workspace ahead of the plugin (newer commits on `main`) is not updated; if a tool then behaves
differently from what the skill says, tell the person and suggest a plugin update.

## Answer

Where the workspace is, the printer and filaments in `spec.py`, what was installed, and that the test
part went through all four tools. Short.
