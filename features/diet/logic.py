"""Чистые формулы калькулятора калорий (без БД/Telegram — легко тестируется).

BMR — Mifflin-St Jeor. Пол в онбординге НЕ спрашиваем (как в дизайне), поэтому
берём усреднённую по полу константу s = (+5 муж. − 161 жен.)/2 = −78.
TDEE = BMR × коэффициент активности. Дневная цель зависит от цели, но не ниже BMR.
Белок = 1.8 г/кг массы (настраиваемо).
"""

ACTIVITY_FACTORS = {"sedentary": 1.2, "light": 1.375, "very": 1.55}
GOALS = ("lose", "maintain", "gain")
ACTIVITIES = tuple(ACTIVITY_FACTORS)
UNITS = ("metric", "imperial")
MEALS = ("breakfast", "lunch", "dinner", "snack")
FOOD_UNITS = ("g", "ml", "pcs")

# Диапазоны валидации (build-prompt §5). Проверяются и на клиенте, и на сервере.
AGE_MIN, AGE_MAX = 10, 120
HEIGHT_MIN, HEIGHT_MAX = 100, 250
WEIGHT_MIN, WEIGHT_MAX = 30.0, 300.0

PROTEIN_PER_KG = 1.8
_SEX_NEUTRAL_S = -78  # среднее м/ж, т.к. пол не спрашиваем


class DietError(ValueError):
    """Понятная ошибка ввода (i18n-ключ во fmt при желании)."""

    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


def bmr(age: int, height_cm: float, weight_kg: float) -> float:
    return 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age + _SEX_NEUTRAL_S


def tdee(age: int, height_cm: float, weight_kg: float, activity: str) -> float:
    return bmr(age, height_cm, weight_kg) * ACTIVITY_FACTORS.get(activity, 1.2)


def targets(age: int, height_cm: float, weight_kg: float, goal: str, activity: str) -> dict:
    """-> {tdee, daily_target_kcal, protein_target_g} (округлённые целые)."""
    base = bmr(age, height_cm, weight_kg)
    t = tdee(age, height_cm, weight_kg, activity)
    if goal == "lose":
        daily = t - 500
    elif goal == "gain":
        daily = t + 300
    else:
        daily = t
    daily = max(daily, base)  # не опускаем ниже BMR
    return {
        "tdee": round(t),
        "daily_target_kcal": round(daily),
        "protein_target_g": round(PROTEIN_PER_KG * weight_kg),
    }


def macro_targets(daily_kcal: int, protein_g: int) -> dict:
    """Целевые макросы из дневного kcal и цели по белку: жир ~30% ккал, углеводы —
    остаток, сахар — ориентир ВОЗ (не жёсткий). Всё в граммах."""
    fat_g = round(daily_kcal * 0.30 / 9)
    carb_kcal = max(0, daily_kcal - protein_g * 4 - fat_g * 9)
    return {
        "protein": protein_g,
        "carb": round(carb_kcal / 4),
        "fat": fat_g,
        "sugar": 50,
    }


def validate_profile(age: int, height_cm: int, weight_kg: float, goal: str, activity: str) -> None:
    if not (AGE_MIN <= age <= AGE_MAX):
        raise DietError("diet.err.age")
    if not (HEIGHT_MIN <= height_cm <= HEIGHT_MAX):
        raise DietError("diet.err.height")
    if not (WEIGHT_MIN <= weight_kg <= WEIGHT_MAX):
        raise DietError("diet.err.weight")
    if goal not in GOALS:
        raise DietError("diet.err.goal")
    if activity not in ACTIVITIES:
        raise DietError("diet.err.activity")


def portion_factor(amount: float, unit: str) -> float:
    """Множитель к значениям «на 100 г». g/ml — amount/100; pcs — считаем 1 шт ≈ 100 г."""
    return amount if unit == "pcs" else amount / 100.0


def scale_food(food, amount: float, unit: str) -> dict:
    """Пересчёт продукта (на 100 г) под количество -> абсолютные kcal/макросы (округл.)."""
    f = portion_factor(amount, unit)
    return {
        "kcal": round(food.kcal_100 * f),
        "protein": round(food.protein_100 * f, 1),
        "fat": round(food.fat_100 * f, 1),
        "carb": round(food.carb_100 * f, 1),
        "sugar": round((food.sugar_100 or 0.0) * f, 1),
    }
