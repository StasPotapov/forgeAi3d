"""Параметры принтера и справочник филаментов.

Числа здесь — типовые практические значения, а не паспортные константы.
Усадка и зазоры зависят от конкретной катушки, влажности и профиля печати,
поэтому перед ответственной деталью их стоит откалибровать тестовой печатью
(печатается набор отверстий с шагом 0.05 мм и подбирается посадка).
"""

from dataclasses import dataclass

MM = float


@dataclass(frozen=True)
class Printer:
    name: str
    bed: tuple[MM, MM, MM]      # рабочая область Ш x Г x В
    nozzle: MM
    extrusion_width: MM         # ширина линии периметра при этом сопле
    layer_height: MM            # типовая высота слоя
    enclosed: bool              # есть ли закрытая камера
    hardened_nozzle: bool       # можно ли абразивные филаменты
    ams: bool                   # есть ли AMS lite
    bed_slinger: bool           # стол ездит по Y => высокие детали качает

    @property
    def max_height(self) -> MM:
        return self.bed[2]


@dataclass(frozen=True)
class Material:
    name: str
    shrink: float               # линейная усадка, доля (0.006 = 0.6%)
    clearances: dict[str, MM]   # зазор НА СТОРОНУ для типа посадки
    support_angle: float        # грань наклонена к горизонтали меньше => нужна поддержка
    max_bridge: MM              # длина моста, который тянет без провисания
    hdt: float                  # температура размягчения, °C
    ductile: bool               # вязкий (терпит защёлки) или хрупкий
    abrasive: bool              # нужно закалённое сопло
    needs_enclosure: bool       # нужна закрытая камера
    ams_safe: bool              # можно ли подавать через AMS lite
    heat_inserts: str           # как держит латунные термовставки: good / ok / poor
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
        note="Жёсткий и хрупкий. Защёлки ломаются, в углах обязательны галтели. "
             "В закрытой машине летом плывёт.",
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
        note="Вязкий, держит удар и термовставки. Хуже мостит, поддержки прикипают "
             "намертво — деталь лучше проектировать так, чтобы обойтись без них.",
    ),
    # Ниже — то, чего сейчас нет в наличии. Оставлено, чтобы supported() мог
    # объяснить, почему деталь под этот материал на A1 mini не поедет.
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
        note="Жёстче и стабильнее по размерам обычного PLA, но заметно хрупче. "
             "Требует закалённого сопла.",
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
        note="Уличный и термостойкий, но на открытом принтере коробит и расслаивается.",
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
        note="Гибкий, 95A. Прямой привод A1 mini его тянет, но подавать нужно с внешней "
             "катушки — через AMS lite гибкие филаменты не идут.",
    ),
}

AVAILABLE = ("PLA", "PETG")   # что реально есть на руках


def in_stock(material: "str | Material") -> bool:
    """Есть ли этот пластик в наличии. Не запрет, а повод предупредить."""
    mat = material if isinstance(material, Material) else get(material)
    return mat.name in AVAILABLE


def get(material: str) -> Material:
    """Материал по имени, регистр и дефисы не важны: 'petg', 'pla_cf'."""
    key = material.strip().upper().replace("_", "-")
    if key in MATERIALS:
        return MATERIALS[key]
    raise KeyError(f"неизвестный материал {material!r}; известны: {', '.join(MATERIALS)}")


def wall(perimeters: int = 2, printer: Printer = A1_MINI) -> MM:
    """Толщина стенки в целых периметрах — чтобы слайсер не оставил пустоту внутри.

    2 периметра — минимум для неответственной стенки, 3-4 — для несущей.
    """
    if perimeters < 1:
        raise ValueError("периметров должно быть хотя бы 1")
    return round(perimeters * printer.extrusion_width, 3)


def clearance(material: str | Material, fit: str = "slip") -> MM:
    """Зазор НА СТОРОНУ для посадки.

    press — запрессовка, снимается молотком; snug — с усилием руки;
    slip — свободно ходит; free — заведомо с люфтом.

    Отверстие под вал 8 мм со скользящей посадкой:
        d = 8 + 2 * clearance("PETG", "slip")
    """
    mat = material if isinstance(material, Material) else get(material)
    if fit not in mat.clearances:
        raise KeyError(f"неизвестная посадка {fit!r}; известны: {', '.join(mat.clearances)}")
    return mat.clearances[fit]


def compensate_shrink(nominal: MM, material: str | Material) -> MM:
    """Увеличить размер в модели так, чтобы после остывания получился nominal."""
    mat = material if isinstance(material, Material) else get(material)
    return round(nominal / (1.0 - mat.shrink), 3)


def supported(material: str | Material, printer: Printer = A1_MINI) -> list[str]:
    """Причины, по которым материал не поедет на этом принтере. Пусто — всё в порядке."""
    mat = material if isinstance(material, Material) else get(material)
    reasons: list[str] = []
    if mat.needs_enclosure and not printer.enclosed:
        reasons.append(f"{mat.name} требует закрытой камеры, а {printer.name} открытый")
    if mat.abrasive and not printer.hardened_nozzle:
        reasons.append(f"{mat.name} абразивный, нужно закалённое сопло")
    if not mat.ams_safe and printer.ams:
        reasons.append(f"{mat.name} нельзя подавать через AMS lite, только с внешней катушки")
    return reasons
