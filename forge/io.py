"""Пути репозитория, экспорт готовой детали и кэш найденных размеров."""

import json
import os
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from build123d import Mesher, Unit, export_step, export_stl


def root() -> Path:
    """Корень репозитория.

    Берётся из FORGEAI3D_HOME, иначе считается от самого пакета — чтобы всё
    работало и когда репозиторий лежит не в ~/dev/forgeAi3d.
    """
    env = os.environ.get("FORGEAI3D_HOME")
    if env:
        path = Path(env).expanduser()
        if not path.is_dir():
            raise RuntimeError(f"FORGEAI3D_HOME указывает в никуда: {path}")
        return path.resolve()
    return Path(__file__).resolve().parent.parent


def prints_dir() -> Path:
    """Каталог готовых деталей, создаётся при первом обращении."""
    path = root() / "prints"
    path.mkdir(parents=True, exist_ok=True)
    return path


EXTRAS = "extras"


def model_dir(stem: str) -> Path:
    """Папка одной детали: prints/<деталь>/. Внутри на виду лежит только STL."""
    path = prints_dir() / stem
    path.mkdir(parents=True, exist_ok=True)
    return path


def extras_dir(stem: str) -> Path:
    """Всё, что не идёт в слайсер: STEP, 3MF, превью, разрезы."""
    path = model_dir(stem) / EXTRAS
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_step(path: Path) -> Path | None:
    """STEP той же детали: сам файл, сосед или сосед в extras/.

    Инструменты принимают путь к STL, а точный анализ идёт по STEP — искать его
    руками не нужно.
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
    """Куда класть производный файл (превью, разрез) от детали.

    Если деталь разложена по-новому — в её extras/, иначе рядом с исходником,
    чтобы инструменты работали и на файле, принесённом со стороны.
    """
    extras = source.parent / EXTRAS
    directory = extras if extras.is_dir() else source.parent
    return directory / f"{source.stem}{suffix}{extension}"


def export_all(part: Any, stem: str, material: str | None = None,
               out: Path | None = None) -> dict[str, Path]:
    """Записать деталь во все три формата и вернуть пути.

    STL — в печать, STEP — для дальнейших правок и точного анализа в check.py,
    3MF — родной формат Bambu Studio: несёт единицы измерения и метаданные,
    которых в STL нет.

    export_stl и export_step возвращают bool и не бросают исключений: при ошибке
    они молча оставят на диске старый файл, поэтому возврат проверяется.
    """
    # каталоги создаются перед самым переносом: если экспорт сорвётся, пустых папок
    # в prints/ не останется
    main = out or (prints_dir() / stem)
    extras = (main / EXTRAS) if out is None else main
    # в слайсер несут STL — он лежит на виду, остальное убрано в extras/
    paths = {
        "stl": main / f"{stem}.stl",
        "step": extras / f"{stem}.step",
        "3mf": extras / f"{stem}.3mf",
    }

    # Тесселяция проверяется до того, как что-то ляжет на диск: Mesher отказывается
    # собирать 3MF из негерметичной сетки, а export_stl такую пишет молча и возвращает
    # True. Иначе на виду остался бы STL, который никто не проверил.
    mesher = Mesher(unit=Unit.MM)
    try:
        mesher.add_shape(part, part_number=stem)
    except Exception as exc:
        raise RuntimeError(
            f"{stem}: тело не тесселируется в герметичную сетку ({exc}). "
            "Печатать такое нельзя — ищи самопересечения и нулевые толщины в модели"
        ) from exc
    mesher.add_meta_data("forgeAi3d", "generated", date.today().isoformat(), "str", True)
    if material:
        mesher.add_meta_data("forgeAi3d", "material", material, "str", True)

    # пишем во временный каталог и переносим разом: половина экспорта на диске
    # хуже, чем его отсутствие — старый файл ушёл бы в печать как свежий
    with tempfile.TemporaryDirectory() as tmp:
        staged = {key: Path(tmp) / path.name for key, path in paths.items()}
        for key, writer in (("stl", export_stl), ("step", export_step)):
            if not writer(part, str(staged[key])):
                raise RuntimeError(f"не удалось записать {paths[key].name}")
        mesher.write(staged["3mf"])
        main.mkdir(parents=True, exist_ok=True)
        extras.mkdir(parents=True, exist_ok=True)
        for key, path in paths.items():
            shutil.move(str(staged[key]), path)

    return paths


# --- кэш размеров чужого железа ------------------------------------------------
#
# Размеры, которые нельзя обмерить самому (габариты платы, диаметр объектива,
# шаг крепёжных отверстий), ищутся в datasheet и складываются сюда — чтобы
# второй раз не искать и чтобы источник числа всегда был виден.

CACHE = "specs_cache.json"


def _cache_path() -> Path:
    return root() / "forge" / CACHE


def load_specs() -> dict[str, dict]:
    path = _cache_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def get_spec(name: str) -> dict | None:
    """Ранее найденные размеры детали. None — надо искать."""
    return load_specs().get(name.strip().lower())


def save_spec(name: str, dimensions: dict[str, float], source: str) -> None:
    """Запомнить найденные размеры вместе со ссылкой, откуда они взяты."""
    if not source:
        raise ValueError("источник обязателен — число без источника ничем не лучше выдуманного")
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
