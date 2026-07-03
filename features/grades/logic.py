"""Чистая логика калькулятора оценок (две немецкие шкалы, у каждой своя формула).

points — баллы 0–15 (FOS/Oberstufe, больше = лучше), формула как в
example/Noten.xlsx:
- маленькие оценки: KA весит вдвое против устной -> (2·ΣKA + ΣMündl) / (2·nKA + nMündl)
- SA весит как вся группа маленьких: итог = (SA-средняя + маленькие-средняя) / 2
- есть только SA или только маленькие -> берётся то, что есть.

marks — оценки 1–6 (обычная школа, меньше = лучше), типов только два (SA и
Mündlich/Ex), простое взвешенное среднее: каждая SA с весом 2, остальное с
весом 1. Пример пользователя: SA 4, M 5 -> (2·4 + 5) / 3 = 4.33.

Без зависимостей от БД/телеграма — легко тестируется.
"""

SA = "sa"
KA = "ka"
ORAL = "muendlich"
KINDS = (SA, KA, ORAL)

SCALE_POINTS = "points"  # баллы 0–15
SCALE_MARKS = "marks"    # оценки 1–6
SCALES = (SCALE_POINTS, SCALE_MARKS)
SCALE_BOUNDS = {SCALE_POINTS: (0, 15), SCALE_MARKS: (1, 6)}


class ValueError_(ValueError):
    """Понятная пользователю ошибка ввода (i18n-ключ)."""

    def __init__(self, key: str, **fmt):
        super().__init__(key)
        self.key = key
        self.fmt = fmt


def parse_value(raw: str, scale: str = SCALE_POINTS) -> int:
    lo, hi = SCALE_BOUNDS.get(scale, SCALE_BOUNDS[SCALE_POINTS])
    raw = raw.strip()
    if not raw.lstrip("+").isdigit():
        raise ValueError_("grades.err.value", min=lo, max=hi)
    value = int(raw)
    if not lo <= value <= hi:
        raise ValueError_("grades.err.value", min=lo, max=hi)
    return value


def kinds_for_scale(scale: str) -> tuple[str, ...]:
    """Доступные типы оценок: в школе 1–6 есть только SA и Mündlich/Ex."""
    return (SA, ORAL) if scale == SCALE_MARKS else KINDS


def subject_average(grades, scale: str = SCALE_POINTS) -> float | None:
    """Средний балл предмета по списку (kind, value). None — оценок нет."""
    if scale == SCALE_MARKS:
        return _weighted_average(grades)
    return _fos_average(grades)


def _weighted_average(grades) -> float | None:
    """Оценки 1–6: каждая SA с весом 2, всё остальное с весом 1."""
    total = weight = 0
    for kind, value in grades:
        w = 2 if kind == SA else 1
        total += w * value
        weight += w
    return total / weight if weight else None


def _fos_average(grades) -> float | None:
    """Баллы 0–15: (SA-средняя + маленькие-средняя)/2, внутри маленьких KA ×2."""
    sa_values = [v for k, v in grades if k == SA]
    small_sum = small_weight = 0
    for kind, value in grades:
        if kind == KA:
            small_sum += 2 * value
            small_weight += 2
        elif kind == ORAL:
            small_sum += value
            small_weight += 1
    sa_avg = sum(sa_values) / len(sa_values) if sa_values else None
    small_avg = small_sum / small_weight if small_weight else None
    if sa_avg is not None and small_avg is not None:
        return (sa_avg + small_avg) / 2
    return sa_avg if sa_avg is not None else small_avg


def overall_average(averages: list[float]) -> float | None:
    """Общий средний = среднее по средним предметов (пустые предметы не участвуют)."""
    return sum(averages) / len(averages) if averages else None


def fmt_avg(value: float | None) -> str:
    """11.0 -> «11», 10.666… -> «10.67» (для показа в UI)."""
    if value is None:
        return "—"
    rounded = round(value, 2)
    return f"{rounded:g}"
