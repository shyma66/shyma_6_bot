"""SQLAlchemy-модели (async): AppSetting, User, Shelf, Note, Reminder, CalendarFeed, CalendarEvent."""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AppSetting(Base):
    """Глобальная настройка бота (не привязана к пользователю).

    Пока хранит только флаги «модуль выключен» из админ-панели:
    key = "module_off:<module_key>", value = "1". Читается один раз при старте
    в кэш (core/admin.py), чтобы отрисовка меню не ходила в БД на каждое нажатие.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PrimeUser(Base):
    """Привилегированный (prime) пользователь: доступ к модулям, помеченным «только prime».

    Уровни доступа: common (обычный) < prime < admin (по ADMIN_ID в окружении).
    Членство хранится тут (переживает рестарт, попадает в зеркало-резерв).
    """

    __tablename__ = "prime_users"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PrimeRequest(Base):
    """Заявка на prime (очередь в админ-панели): id, username, время запроса."""

    __tablename__ = "prime_requests"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Base):
    """Пользователь бота. Опознаётся по telegram_user_id; данные изолируются по нему."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language: Mapped[str | None] = mapped_column(String(5), nullable=True)  # ru/en/de
    # согласие на обработку данных (Datenschutz): время нажатия «Согласен», None = нет
    consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    shelves: Mapped[list["Shelf"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    reminders: Mapped[list["Reminder"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    calendar_feeds: Mapped[list["CalendarFeed"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    grade_subjects: Mapped[list["GradeSubject"]] = relationship(
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


class CalendarFeed(Base):
    """Подписка на опубликованный ICS-календарь (один фид на пользователя, v1).

    URL полуприватный (по ссылке видно события) — в логи не выводится,
    в UI показывается только домен. last_synced_at — время последней
    попытки синка (удачной или нет); текст последней ошибки — в last_error.
    """

    __tablename__ = "calendar_feeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    lead_minutes: Mapped[int] = mapped_column(default=30)  # за сколько минут напоминать
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="calendar_feeds")
    events: Mapped[list["CalendarEvent"]] = relationship(
        back_populates="feed", cascade="all, delete-orphan"
    )


class CalendarEvent(Base):
    """Событие из фида в окне ближайших дней. starts_at хранится в UTC.

    notified=True — напоминание перед началом уже отправлено; при сдвиге
    события в фиде сбрасывается, чтобы напомнить заново.
    """

    __tablename__ = "calendar_events"
    __table_args__ = (UniqueConstraint("feed_id", "uid", name="uq_calendar_events_feed_uid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    feed_id: Mapped[int] = mapped_column(
        ForeignKey("calendar_feeds.id", ondelete="CASCADE"), index=True
    )
    uid: Mapped[str] = mapped_column(String(512))
    summary: Mapped[str] = mapped_column(String(512))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    all_day: Mapped[bool] = mapped_column(default=False)
    notified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    feed: Mapped["CalendarFeed"] = relationship(back_populates="events")


class GradeSubject(Base):
    """Предмет калькулятора оценок.

    scale: points (баллы 0–15, FOS/Oberstufe) | marks (оценки 1–6, обычная школа).
    """

    __tablename__ = "grade_subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(100))
    scale: Mapped[str] = mapped_column(String(8), default="points")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="grade_subjects")
    grades: Mapped[list["GradeEntry"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )


class GradeEntry(Base):
    """Оценка предмета: kind = sa | ka | muendlich, value = баллы 0–15.

    Веса (как в баварской FOS): маленькие = (2·KA + Mündlich)/3,
    итог = (SA-средняя + маленькие)/2 — формула в features/grades/logic.py.
    """

    __tablename__ = "grade_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("grade_subjects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(12))
    value: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    subject: Mapped["GradeSubject"] = relationship(back_populates="grades")
