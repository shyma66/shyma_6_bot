"""Админ-панель + prime-доступ.

Панель видна только владельцу (ADMIN_ID). Каждый обработчик проверяет права сам:
callback_data подделывается — отсутствие кнопки в меню не защита.

Уровни: common < prime < admin. Prime-членство и уровень модулей («всем» /
«только prime») правятся отсюда; обычные юзеры просят prime кнопкой в меню, заявки
падают в очередь панели.

callback_data:
  adm:home | adm:mods | adm:toggle:<key> | adm:tier:<key>
  adm:prime | adm:allow:<id> | adm:deny:<id> | adm:unprime:<id> | adm:addid
  adm:errors | adm:clear | adm:dbs
  prime:request  (пользовательская заявка на prime)
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from core.admin import (
    ADMIN_ID,
    admin_configured,
    clear_errors,
    grant_prime,
    is_admin,
    is_disabled,
    is_prime,
    module_is_prime_only,
    prime_ids,
    recent_errors,
    revoke_prime,
    set_disabled,
    set_module_prime_only,
)
from core.dashboard import CALLBACK_PREFIX, HOME_KEY, answer_safely, edit_safely
from core.i18n import t, user_lang
from core.registry import MODULES, Module, register
from DataBase.database import (
    add_prime_request,
    db_status,
    delete_prime_request,
    list_prime_requests,
    list_prime_users,
)

_HOME_CB = f"{CALLBACK_PREFIX}{HOME_KEY}"
P_ADDID = 0  # состояние диалога «введи id для prime»


async def _deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Чужой в админке: тот же ответ, что и на несуществующий модуль."""
    lang = await user_lang(update, context)
    await answer_safely(update.callback_query, t(lang, "menu.unknown_module"), show_alert=True)


def _configurable() -> list[Module]:
    """Модули, доступные для настройки: без админских и без самой панели."""
    return [m for m in MODULES if not m.admin_only and not m.essential]


# ----- главный экран панели -----

async def _panel(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    pending = len(await list_prime_requests())
    rows = [
        [InlineKeyboardButton(t(lang, "adm.mods_btn"), callback_data="adm:mods")],
        [InlineKeyboardButton(t(lang, "adm.prime_btn", n=pending), callback_data="adm:prime")],
        [InlineKeyboardButton(t(lang, "adm.dbs_btn"), callback_data="adm:dbs")],
        [
            InlineKeyboardButton(
                t(lang, "adm.errors_btn", n=len(recent_errors())), callback_data="adm:errors"
            )
        ],
        [InlineKeyboardButton(t(lang, "common.menu_btn"), callback_data=_HOME_CB)],
    ]
    return t(lang, "adm.title"), InlineKeyboardMarkup(rows)


async def open_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return
    lang = await user_lang(update, context)
    text, markup = await _panel(lang)
    await edit_safely(update.callback_query, text, reply_markup=markup)


# ----- экран модулей (вкл/выкл + уровень доступа) -----

def _mods_screen(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    rows = []
    for m in _configurable():
        on = "🔧" if is_disabled(m.key) else "✅"
        tier_mark = "⭐" if module_is_prime_only(m.key) else "👥"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{on} {t(lang, m.title_key)}", callback_data=f"adm:toggle:{m.key}"
                ),
                InlineKeyboardButton(tier_mark, callback_data=f"adm:tier:{m.key}"),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(t(lang, "adm.back_btn"), callback_data="adm:home"),
            InlineKeyboardButton(t(lang, "common.home_btn"), callback_data=_HOME_CB),
        ]
    )
    return t(lang, "adm.mods_title"), InlineKeyboardMarkup(rows)


async def show_mods(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return
    lang = await user_lang(update, context)
    text, markup = _mods_screen(lang)
    await edit_safely(update.callback_query, text, reply_markup=markup)


async def toggle_module(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return
    key = update.callback_query.data.rsplit(":", 1)[1]
    if key not in {m.key for m in _configurable()}:
        await _deny(update, context)
        return
    await set_disabled(key, not is_disabled(key))
    lang = await user_lang(update, context)
    text, markup = _mods_screen(lang)
    await edit_safely(update.callback_query, text, reply_markup=markup)


async def toggle_tier(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return
    key = update.callback_query.data.rsplit(":", 1)[1]
    if key not in {m.key for m in _configurable()}:
        await _deny(update, context)
        return
    await set_module_prime_only(key, not module_is_prime_only(key))
    lang = await user_lang(update, context)
    text, markup = _mods_screen(lang)
    await edit_safely(update.callback_query, text, reply_markup=markup)


# ----- экран prime (список, очередь заявок, добавить по id) -----

def _fmt_user(uid: int, username: str | None) -> str:
    return f"@{username} ({uid})" if username else str(uid)


async def _prime_screen(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    users = await list_prime_users()
    requests = await list_prime_requests()
    lines = [t(lang, "adm.prime_title")]
    rows = []

    lines.append("")
    lines.append(t(lang, "adm.prime_members", n=len(users)))
    for uid, uname, _added in users:
        rows.append(
            [
                InlineKeyboardButton(
                    f"⭐ {_fmt_user(uid, uname)}", callback_data="adm:noop"
                ),
                InlineKeyboardButton("🗑", callback_data=f"adm:unprime:{uid}"),
            ]
        )

    if requests:
        lines.append("")
        lines.append(t(lang, "adm.prime_waitlist", n=len(requests)))
        for uid, uname, at in requests:
            when = at.strftime("%d.%m %H:%M") if at else "—"
            lines.append(f"• {when} — {_fmt_user(uid, uname)}")
            rows.append(
                [
                    InlineKeyboardButton(
                        t(lang, "adm.allow_btn"), callback_data=f"adm:allow:{uid}"
                    ),
                    InlineKeyboardButton(
                        t(lang, "adm.deny_btn"), callback_data=f"adm:deny:{uid}"
                    ),
                ]
            )

    rows.append([InlineKeyboardButton(t(lang, "adm.add_id_btn"), callback_data="adm:addid")])
    rows.append(
        [
            InlineKeyboardButton(t(lang, "adm.back_btn"), callback_data="adm:home"),
            InlineKeyboardButton(t(lang, "common.home_btn"), callback_data=_HOME_CB),
        ]
    )
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def show_prime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return
    lang = await user_lang(update, context)
    text, markup = await _prime_screen(lang)
    await edit_safely(update.callback_query, text[:4000], reply_markup=markup)


async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_safely(update.callback_query)


async def allow_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return
    uid = int(update.callback_query.data.rsplit(":", 1)[1])
    uname = next((u for i, u, _ in await list_prime_requests() if i == uid), None)
    await grant_prime(uid, uname)
    await delete_prime_request(uid)
    lang = await user_lang(update, context)
    try:  # уведомим пользователя, что его одобрили
        await context.bot.send_message(chat_id=uid, text=t(lang, "prime.approved_dm"))
    except Exception:  # noqa: BLE001
        pass
    text, markup = await _prime_screen(lang)
    await edit_safely(update.callback_query, text[:4000], reply_markup=markup)


async def deny_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return
    uid = int(update.callback_query.data.rsplit(":", 1)[1])
    await delete_prime_request(uid)
    lang = await user_lang(update, context)
    text, markup = await _prime_screen(lang)
    await edit_safely(update.callback_query, text[:4000], reply_markup=markup)


async def unprime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return
    uid = int(update.callback_query.data.rsplit(":", 1)[1])
    await revoke_prime(uid)
    lang = await user_lang(update, context)
    text, markup = await _prime_screen(lang)
    await edit_safely(update.callback_query, text[:4000], reply_markup=markup)


# ----- добавить prime по id (диалог) -----

async def add_id_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return ConversationHandler.END
    lang = await user_lang(update, context)
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data="adm:prime")]]
    )
    await edit_safely(update.callback_query, t(lang, "adm.add_id_hint"), reply_markup=kb)
    return P_ADDID


async def add_id_recv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    raw = update.message.text.strip()
    if not raw.isdigit():
        await update.message.reply_text(t(lang, "adm.add_id_bad"))
        return P_ADDID
    await grant_prime(int(raw))
    try:
        await context.bot.send_message(chat_id=int(raw), text=t(lang, "prime.approved_dm"))
    except Exception:  # noqa: BLE001
        pass
    text, markup = await _prime_screen(lang)
    await update.message.reply_text(
        t(lang, "adm.add_id_ok", id=raw) + "\n\n" + text[:3800], reply_markup=markup
    )
    return ConversationHandler.END


async def add_id_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await show_prime(update, context)
    return ConversationHandler.END


# ----- журнал ошибок -----

async def show_errors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return
    lang = await user_lang(update, context)
    errors = recent_errors()
    if not errors:
        body = t(lang, "adm.no_errors")
    else:
        lines = [
            f"• {r.at.strftime('%d.%m %H:%M')} UTC — {r.where}\n  {r.text}" for r in errors
        ]
        body = t(lang, "adm.errors_title", n=len(errors)) + "\n\n" + "\n".join(lines)
    rows = [
        [InlineKeyboardButton(t(lang, "adm.clear_btn"), callback_data="adm:clear")],
        [
            InlineKeyboardButton(t(lang, "adm.back_btn"), callback_data="adm:home"),
            InlineKeyboardButton(t(lang, "common.home_btn"), callback_data=_HOME_CB),
        ],
    ]
    await edit_safely(update.callback_query, body[:4000], reply_markup=InlineKeyboardMarkup(rows))


async def clear_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return
    clear_errors()
    await show_errors(update, context)


# ----- статус баз -----

async def show_dbs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Только статус баз: жива/активна/резерв + сколько занято. Переключения нет —
    активную БД бот выбирает сам (живая с самыми свежими данными)."""
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return
    lang = await user_lang(update, context)
    statuses = await db_status()
    if not statuses:
        body = t(lang, "adm.db_none")
    else:
        lines = []
        for s in statuses:
            name = t(lang, f"adm.db.{s['key']}")
            if not s["alive"]:
                state = t(lang, "adm.db_down")
            elif s["active"]:
                state = t(lang, "adm.db_active")
            else:
                state = t(lang, "adm.db_standby")
            line = f"{state} {name}"
            if s["alive"]:
                usage = s["size"] or "—"
                line += "\n   " + t(lang, "adm.db_usage", size=usage, users=s["users"] or 0)
            lines.append(line)
        body = t(lang, "adm.db_title") + "\n\n" + "\n\n".join(lines)
    rows = [[
        InlineKeyboardButton(t(lang, "adm.back_btn"), callback_data="adm:home"),
        InlineKeyboardButton(t(lang, "common.home_btn"), callback_data=_HOME_CB),
    ]]
    await edit_safely(update.callback_query, body[:4000], reply_markup=InlineKeyboardMarkup(rows))


# ----- пользовательская заявка на prime -----

async def request_prime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «⭐ Запросить доступ» / команда /prime — ставит заявку в очередь."""
    lang = await user_lang(update, context)
    user = update.effective_user
    is_cb = update.callback_query is not None

    async def reply(txt: str) -> None:
        if is_cb:
            await answer_safely(update.callback_query, txt, show_alert=True)
        else:
            await update.message.reply_text(txt)

    if is_prime(user.id):
        await reply(t(lang, "prime.already"))
        return
    status = await add_prime_request(user.id, user.username)
    if status == "pending":
        await reply(t(lang, "prime.pending"))
        return
    if status == "no_db":
        await reply(t(lang, "err.maintenance"))
        return
    await reply(t(lang, "prime.sent"))
    if ADMIN_ID is not None:  # уведомим админа о новой заявке
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=t(lang, "prime.admin_new", who=_fmt_user(user.id, user.username)),
            )
        except Exception:  # noqa: BLE001
            pass


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает свой Telegram ID и уровень доступа."""
    lang = await user_lang(update, context)
    uid = update.effective_user.id
    body = t(lang, "adm.whoami", id=uid)
    if is_admin(uid):
        body += "\n" + t(lang, "adm.whoami_admin")
    elif is_prime(uid):
        body += "\n" + t(lang, "adm.whoami_prime")
    else:
        body += "\n" + t(lang, "adm.whoami_common")
        if not admin_configured():
            body += "\n" + t(lang, "adm.whoami_unset")
    await update.message.reply_text(body)


def setup(app: Application) -> None:
    register(
        Module(
            key="admin",
            title_key="module.admin",
            on_open=open_panel,
            admin_only=True,
            essential=True,
        )
    )
    # диалог «добавить prime по id» (регистрируем раньше одиночных adm:*-хендлеров)
    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(add_id_entry, pattern=r"^adm:addid$")],
            states={P_ADDID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_id_recv)]},
            fallbacks=[
                CommandHandler("cancel", add_id_cancel),
                CallbackQueryHandler(add_id_cancel, pattern=r"^adm:prime$"),
            ],
            per_message=False,
        )
    )
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("prime", request_prime))
    app.add_handler(CallbackQueryHandler(request_prime, pattern=r"^prime:request$"))
    app.add_handler(CallbackQueryHandler(open_panel, pattern=r"^adm:home$"))
    app.add_handler(CallbackQueryHandler(show_mods, pattern=r"^adm:mods$"))
    app.add_handler(CallbackQueryHandler(toggle_module, pattern=r"^adm:toggle:[a-z_]+$"))
    app.add_handler(CallbackQueryHandler(toggle_tier, pattern=r"^adm:tier:[a-z_]+$"))
    app.add_handler(CallbackQueryHandler(show_prime, pattern=r"^adm:prime$"))
    app.add_handler(CallbackQueryHandler(allow_request, pattern=r"^adm:allow:\d+$"))
    app.add_handler(CallbackQueryHandler(deny_request, pattern=r"^adm:deny:\d+$"))
    app.add_handler(CallbackQueryHandler(unprime, pattern=r"^adm:unprime:\d+$"))
    app.add_handler(CallbackQueryHandler(noop, pattern=r"^adm:noop$"))
    app.add_handler(CallbackQueryHandler(show_errors, pattern=r"^adm:errors$"))
    app.add_handler(CallbackQueryHandler(clear_log, pattern=r"^adm:clear$"))
    app.add_handler(CallbackQueryHandler(show_dbs, pattern=r"^adm:dbs$"))
