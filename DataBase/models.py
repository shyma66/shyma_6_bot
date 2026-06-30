"""SQLAlchemy-модели (async): User, Shelf, Note."""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    """Пользователь бота. Опознаётся по telegram_user_id; данные изолируются по нему."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    shelves: Mapped[list["Shelf"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    reminders: Mapped[list["Reminder"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Shelf(Base):
    """Полка «шкафа памяти» — принадлежит одному пользователю, содержит заметки."""

    __tablename__ = "shelves"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="shelves")
    notes: Mapped[list["Note"]] = relationship(
        back_populates="shelf", cascade="all, delete-orphan"
    )


class Note(Base):
    """Заметка внутри полки."""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    shelf_id: Mapped[int] = mapped_column(
        ForeignKey("shelves.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    shelf: Mapped["Shelf"] = relationship(back_populates="notes")


class Reminder(Base):
    """Напоминание: бот шлёт `text` владельцу в `next_fire_at` (хранится в UTC).

    repeat_kind: once | daily | weekly | interval. Для interval период задаётся
    в interval_seconds. После срабатывания разовое гасится (active=False),
    повторяющееся — пересчитывает next_fire_at.
    """

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    next_fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    repeat_kind: Mapped[str] = mapped_column(String(16), default="once")
    interval_seconds: Mapped[int | None] = mapped_column(nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="reminders")
