"""SQLAlchemy-модели модуля «Калории» (Kalorien-Coach).

Вынесены в ОТДЕЛЬНЫЙ файл, чтобы не трогать защищённый DataBase/models.py.
Импортируют общий Base -> регистрируются в Base.metadata -> создаются через
create_all (проект без Alembic; см. DataBase/database.py::init_db).

Изоляция по владельцу (users.id). FK ON DELETE CASCADE: при удалении
пользователя данные диеты стираются каскадом (в Postgres). Enum-поля храним
строками с проверкой на уровне приложения (как repeat_kind в напоминаниях),
чтобы не плодить БД-типы/миграции.
"""
from datetime import date as _date
from datetime import datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from DataBase.models import Base


class DietProfile(Base):
    """Профиль питания пользователя (1 на пользователя): цель, активность, цели по kcal/белку."""

    __tablename__ = "diet_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    age: Mapped[int] = mapped_column()
    height_cm: Mapped[int] = mapped_column()
    weight_kg: Mapped[float] = mapped_column(Float)
    goal: Mapped[str] = mapped_column(String(12))       # lose | maintain | gain
    activity: Mapped[str] = mapped_column(String(12))   # sedentary | light | very
    tdee: Mapped[int] = mapped_column()
    daily_target_kcal: Mapped[int] = mapped_column()
    protein_target_g: Mapped[int] = mapped_column()
    units: Mapped[str] = mapped_column(String(8), default="metric")  # metric | imperial
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DietFood(Base):
    """Продукт: значения на 100 г. owner_id NULL = общий (база); иначе — свой (manual)."""

    __tablename__ = "diet_foods"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(8), default="manual")  # db | manual | barcode
    name: Mapped[str] = mapped_column(String(80))
    brand: Mapped[str | None] = mapped_column(String(80), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    kcal_100: Mapped[float] = mapped_column(Float)
    protein_100: Mapped[float] = mapped_column(Float)
    fat_100: Mapped[float] = mapped_column(Float)
    carb_100: Mapped[float] = mapped_column(Float)
    sugar_100: Mapped[float] = mapped_column(Float, default=0.0)


class DietEntry(Base):
    """Запись в дневнике: продукт × количество для конкретного приёма и даты.

    kcal/макросы дублируются в запись (пересчитаны на сервере из продукта и
    количества), чтобы дневник не зависел от последующих правок продукта.
    """

    __tablename__ = "diet_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[_date] = mapped_column(Date, index=True)
    meal: Mapped[str] = mapped_column(String(10))  # breakfast | lunch | dinner | snack
    food_id: Mapped[int] = mapped_column(ForeignKey("diet_foods.id", ondelete="CASCADE"))
    amount: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(4), default="g")  # g | ml | pcs
    kcal: Mapped[float] = mapped_column(Float)
    protein: Mapped[float] = mapped_column(Float)
    fat: Mapped[float] = mapped_column(Float)
    carb: Mapped[float] = mapped_column(Float)
    sugar: Mapped[float] = mapped_column(Float, default=0.0)
    logged_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DietExpenditure(Base):
    """Расход энергии за день (1 запись на пользователя+дату)."""

    __tablename__ = "diet_expenditure"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    kcal: Mapped[int] = mapped_column()
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(8), default="estimate")  # estimate | manual
