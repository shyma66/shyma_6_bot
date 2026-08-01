"""Доступ к данным модуля «Калории». Всё изолировано по владельцу (users.id).

Если БД не настроена (async_session is None) — безопасные пустые результаты/None.
Итоги дня считаются здесь, на сервере, из записей — клиентским суммам не доверяем.
"""
from datetime import date as _date

from sqlalchemy import delete, select

from DataBase.database import async_session, get_or_create_user
from features.diet import logic
from features.diet.models import (
    DietEntry,
    DietExpenditure,
    DietFavorite,
    DietFood,
    DietProfile,
)

FREE_FAV_LIMIT = 10  # бесплатный лимит избранного; безлимит — prime (⭐)


# ----- профиль -----

async def get_profile(tg_id: int) -> DietProfile | None:
    if not async_session:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        return await s.get(DietProfile, uid)


async def save_profile(tg_id: int, age: int, height_cm: int, weight_kg: float,
                       goal: str, activity: str, units: str = "metric") -> DietProfile | None:
    """Создаёт/обновляет профиль, пересчитывает TDEE и цели. Валидация — у вызывающего."""
    if not async_session:
        return None
    uid = await get_or_create_user(tg_id)
    t = logic.targets(age, height_cm, weight_kg, goal, activity)
    async with async_session() as s:
        prof = await s.get(DietProfile, uid)
        if prof is None:
            prof = DietProfile(user_id=uid)
            s.add(prof)
        prof.age = age
        prof.height_cm = height_cm
        prof.weight_kg = weight_kg
        prof.goal = goal
        prof.activity = activity
        prof.units = units if units in logic.UNITS else "metric"
        prof.tdee = t["tdee"]
        prof.daily_target_kcal = t["daily_target_kcal"]
        prof.protein_target_g = t["protein_target_g"]
        await s.commit()
        await s.refresh(prof)
        return prof


# ----- продукты -----

async def create_manual_food(tg_id: int, name: str, kcal_100: float, protein_100: float,
                             fat_100: float, carb_100: float, sugar_100: float = 0.0) -> DietFood | None:
    if not async_session:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        food = DietFood(owner_id=uid, source="manual", name=name[:80],
                        kcal_100=kcal_100, protein_100=protein_100, fat_100=fat_100,
                        carb_100=carb_100, sugar_100=sugar_100)
        s.add(food)
        await s.commit()
        await s.refresh(food)
        return food


async def get_food(tg_id: int, food_id: int) -> DietFood | None:
    """Продукт, если он свой (owner) или общий (owner_id NULL)."""
    if not async_session:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        food = await s.get(DietFood, food_id)
        if food is None or (food.owner_id is not None and food.owner_id != uid):
            return None
        return food


# ----- избранное -----

async def list_favorites(tg_id: int) -> list[tuple[DietFavorite, DietFood]]:
    if not async_session:
        return []
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            select(DietFavorite, DietFood)
            .join(DietFood, DietFavorite.food_id == DietFood.id)
            .where(DietFavorite.user_id == uid)
            .order_by(DietFavorite.created_at.desc())
        )
        return list(res.all())


async def favorite_count(tg_id: int) -> int:
    if not async_session:
        return 0
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            select(DietFavorite.id).where(DietFavorite.user_id == uid)
        )
        return len(res.scalars().all())


async def get_favorite(tg_id: int, food_id: int) -> DietFavorite | None:
    if not async_session:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            select(DietFavorite).where(
                DietFavorite.user_id == uid, DietFavorite.food_id == food_id
            )
        )
        return res.scalar_one_or_none()


async def add_favorite(tg_id: int, food_id: int, default_amount: float) -> DietFavorite | None:
    """Добавляет/обновляет избранное (по паре user+food). Владелец продукта проверен у вызывающего."""
    if not async_session:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            select(DietFavorite).where(
                DietFavorite.user_id == uid, DietFavorite.food_id == food_id
            )
        )
        fav = res.scalar_one_or_none()
        if fav is None:
            fav = DietFavorite(user_id=uid, food_id=food_id, default_amount=default_amount)
            s.add(fav)
        else:
            fav.default_amount = default_amount
        await s.commit()
        await s.refresh(fav)
        return fav


async def remove_favorites(tg_id: int, ids: list[int]) -> int:
    if not async_session or not ids:
        return 0
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            delete(DietFavorite).where(DietFavorite.user_id == uid, DietFavorite.id.in_(ids))
        )
        await s.commit()
        return res.rowcount or 0


# ----- дневник -----

async def add_entry(tg_id: int, day: _date, meal: str, food_id: int,
                    amount: float, unit: str) -> DietEntry | None:
    food = await get_food(tg_id, food_id)
    if food is None:
        return None
    uid = await get_or_create_user(tg_id)
    m = logic.scale_food(food, amount, unit)
    async with async_session() as s:
        entry = DietEntry(user_id=uid, date=day, meal=meal, food_id=food_id,
                          amount=amount, unit=unit, **m)
        s.add(entry)
        await s.commit()
        await s.refresh(entry)
        return entry


async def list_entries(tg_id: int, day: _date) -> list[tuple[DietEntry, DietFood]]:
    """Записи за день с их продуктами (для названий), по времени добавления."""
    if not async_session:
        return []
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            select(DietEntry, DietFood)
            .join(DietFood, DietEntry.food_id == DietFood.id)
            .where(DietEntry.user_id == uid, DietEntry.date == day)
            .order_by(DietEntry.logged_at_utc)
        )
        return list(res.all())


async def delete_entry(tg_id: int, entry_id: int) -> bool:
    if not async_session:
        return False
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        entry = await s.get(DietEntry, entry_id)
        if entry is None or entry.user_id != uid:
            return False
        await s.delete(entry)
        await s.commit()
        return True


async def delete_entries(tg_id: int, ids: list[int]) -> int:
    if not async_session or not ids:
        return 0
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            delete(DietEntry).where(DietEntry.user_id == uid, DietEntry.id.in_(ids))
        )
        await s.commit()
        return res.rowcount or 0


def day_totals(rows: list[tuple[DietEntry, DietFood]]) -> dict:
    """Сумма съеденного за день из записей (округлённо)."""
    tot = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carb": 0.0, "sugar": 0.0}
    for entry, _food in rows:
        tot["kcal"] += entry.kcal
        tot["protein"] += entry.protein
        tot["fat"] += entry.fat
        tot["carb"] += entry.carb
        tot["sugar"] += entry.sugar
    return {
        "kcal": round(tot["kcal"]),
        "protein": round(tot["protein"]),
        "fat": round(tot["fat"]),
        "carb": round(tot["carb"]),
        "sugar": round(tot["sugar"]),
    }


# ----- расход -----

async def get_expenditure(tg_id: int, day: _date) -> DietExpenditure | None:
    if not async_session:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        return await s.get(DietExpenditure, (uid, day))


async def set_expenditure(tg_id: int, day: _date, kcal: int, weight_kg: float | None,
                          source: str) -> DietExpenditure | None:
    if not async_session:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        exp = await s.get(DietExpenditure, (uid, day))
        if exp is None:
            exp = DietExpenditure(user_id=uid, date=day)
            s.add(exp)
        exp.kcal = kcal
        exp.weight_kg = weight_kg
        exp.source = source if source in ("estimate", "manual") else "estimate"
        await s.commit()
        await s.refresh(exp)
        return exp
