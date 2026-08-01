"""Поиск продукта по штрихкоду в OpenFoodFacts (публичный API, без ключа).

Наружу уходит только сам штрихкод. Ошибки/таймауты -> None (без падений).
OFF просит присылать User-Agent приложения.
"""
import httpx

_TIMEOUT = 6.0
_UA = {"User-Agent": "shyma6-bot/1.0 (Telegram calorie tracker)"}
_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
_FIELDS = "product_name,brands,nutriments"


def _num(nutriments: dict, key: str):
    v = nutriments.get(key)
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_product(data: dict) -> dict | None:
    """OFF-ответ -> {name, brand, kcal_100, protein_100, fat_100, carb_100, sugar_100} или None."""
    if not data or data.get("status") != 1:
        return None
    p = data.get("product") or {}
    n = p.get("nutriments") or {}
    kcal = _num(n, "energy-kcal_100g")
    if kcal is None:
        kj = _num(n, "energy_100g")  # запасной вариант — кДж
        if kj is not None:
            kcal = round(kj / 4.184, 1)
    name = (p.get("product_name") or "").strip()
    if not name or kcal is None:
        return None
    brand = (p.get("brands") or "").split(",")[0].strip()[:80] or None
    return {
        "name": name[:80],
        "brand": brand,
        "kcal_100": kcal,
        "protein_100": _num(n, "proteins_100g") or 0.0,
        "fat_100": _num(n, "fat_100g") or 0.0,
        "carb_100": _num(n, "carbohydrates_100g") or 0.0,
        "sugar_100": _num(n, "sugars_100g") or 0.0,
    }


async def lookup(code: str) -> dict | None:
    """Скачивает и парсит продукт по штрихкоду. None — не найден/ошибка/нет данных."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA, follow_redirects=True) as c:
            r = await c.get(_URL.format(code=code), params={"fields": _FIELDS})
            if r.status_code != 200:
                return None
            data = r.json()
    except Exception:  # noqa: BLE001 — сеть/парсинг не должны ронять эндпоинт
        return None
    return parse_product(data)
