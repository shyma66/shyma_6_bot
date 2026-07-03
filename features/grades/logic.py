"""Чистая логика калькулятора оценок (немецкая система, баллы 0–15).

Правила как в примере пользователя (example/Noten.xlsx, баварская FOS):
- маленькие оценки: KA весит вдвое против устной -> (2·ΣKA + ΣMündl) / (2·nKA + nMündl)
- SA весит как вся группа маленьких: итог = (SA-средняя + маленькие-средняя) / 2
- есть только SA или только маленькие -> берётся то, что есть.
Без зависимостей от БД/телеграма — легко тестируется.
"""

SA = "sa"
KA = "ka"
ORAL = "muendlich"
KINDS = (SA, KA, ORAL)

MIN_VALUE = 0
MAX_VALUE = 15


class ValueError_(ValueError):
    """Понятная пользователю ошибка ввода (i18n-ключ)."""

    def __init__(self, key: str, **fmt):
        super().__init__(key)
        self.key = key
        self.fmt = fmt


def parse_value(raw: str) -> int:
    raw = raw.strip()
    if not raw.lstrip("+").isdigit():
        raise ValueError_("grades.err.value")
    value = int(raw)
    if not MIN_VALUE <= value <= MAX_VALUE:
        raise ValueError_("grades.err.value")
    return value


def subject_average(grades) -> float | None:
    """Средний балл предмета по списку (kind, value). None — оценок нет."""
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
