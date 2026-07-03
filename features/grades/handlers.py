"""Модуль «Оценки» (Notenrechner): предметы CRUD + оценки SA/KA/Mündlich (0–15).

Средние считает features/grades/logic.py (формула как в example/Noten.xlsx).
Навигация — инлайн-кнопки; ввод (название, баллы) — через ConversationHandler.
callback_data:
  subj:list | subj:new | subj:open:<id> | subj:ren:<id> | subj:del:<id> | subj:delyes:<id>
  grade:add:<sid>:<kind> | grade:pickdel:<sid> | grade:del:<gid> | grade:cancel
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

from core.dashboard import CALLBACK_PREFIX, HOME_KEY, edit_safely
from core.i18n import t, user_lang
from core.registry import Module, register
from features.grades import logic, repo

# Состояния диалога
G_NAME, G_RENAME, G_VALUE = range(3)

MAX_TITLE = 100
MAX_SUBJECTS = 30   # лимиты в духе improvements #07
MAX_GRADES = 60

_HOME_CB = f"{CALLBACK_PREFIX}{HOME_KEY}"


def _arg(data: str) -> int:
    return int(data.rsplit(":", 1)[1])


def _kind_label(lang: str, kind: str) -> str:
    return t(lang, f"grades.kind.{kind}")


def _pairs(subject) -> list[tuple[str, int]]:
    return [(g.kind, g.value) for g in subject.grades]


# ----- экраны -> (text, markup) -----

async def _render_list(tg_id: int, lang: str):
    subjects = await repo.list_subjects(tg_id)
    averages = []
    rows = []
    for subj in subjects:
        avg = logic.subject_average(_pairs(subj))
        if avg is not None:
            averages.append(avg)
        rows.append(
            [
                InlineKeyboardButton(
                    f"{subj.title} — {logic.fmt_avg(avg)}",
                    callback_data=f"subj:open:{subj.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(t(lang, "grades.new_subj_btn"), callback_data="subj:new")])
    rows.append([InlineKeyboardButton(t(lang, "common.menu_btn"), callback_data=_HOME_CB)])

    lines = [t(lang, "grades.title")]
    overall = logic.overall_average(averages)
    if overall is not None:
        lines.append(t(lang, "grades.overall", avg=logic.fmt_avg(overall)))
    lines.append("")
    lines.append(t(lang, "grades.choose" if subjects else "grades.empty"))
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _not_found(lang: str):
    return t(lang, "grades.subj_not_found"), InlineKeyboardMarkup(
        [[InlineKeyboardButton(t(lang, "grades.back_to_subjects"), callback_data="subj:list")]]
    )


async def _render_subject(tg_id: int, sid: int, lang: str):
    subj = await repo.get_subject(tg_id, sid)
    if subj is None:
        return _not_found(lang)
    avg = logic.subject_average(_pairs(subj))
    lines = [f"📗 {subj.title}", t(lang, "grades.schnitt", avg=logic.fmt_avg(avg)), ""]
    if subj.grades:
        for kind in logic.KINDS:
            values = [str(g.value) for g in subj.grades if g.kind == kind]
            if values:
                lines.append(f"{_kind_label(lang, kind)}: {', '.join(values)}")
        lines.append("")
        lines.append(t(lang, "grades.formula_note"))
    else:
        lines.append(t(lang, "grades.no_grades"))

    rows = [
        [
            InlineKeyboardButton(
                f"➕ {_kind_label(lang, kind)}", callback_data=f"grade:add:{sid}:{kind}"
            )
            for kind in logic.KINDS
        ]
    ]
    if subj.grades:
        rows.append(
            [InlineKeyboardButton(t(lang, "grades.del_grade_btn"), callback_data=f"grade:pickdel:{sid}")]
        )
    rows.append(
        [
            InlineKeyboardButton(t(lang, "grades.rename_btn"), callback_data=f"subj:ren:{sid}"),
            InlineKeyboardButton(t(lang, "grades.del_subj_btn"), callback_data=f"subj:del:{sid}"),
        ]
    )
    rows.append(
        [InlineKeyboardButton(t(lang, "grades.back_to_subjects"), callback_data="subj:list")]
    )
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _edit(update: Update, text: str, markup: InlineKeyboardMarkup | None) -> None:
    await edit_safely(update.callback_query, text, reply_markup=markup)


def _cancel_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data="grade:cancel")]]
    )


# ----- навигация -----

async def open_grades(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    text, markup = await _render_list(update.effective_user.id, lang)
    await _edit(update, text, markup)


async def open_subject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    text, markup = await _render_subject(
        update.effective_user.id, _arg(update.callback_query.data), lang
    )
    await _edit(update, text, markup)


async def pick_del_grade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Список оценок кнопками — тап удаляет."""
    lang = await user_lang(update, context)
    sid = _arg(update.callback_query.data)
    subj = await repo.get_subject(update.effective_user.id, sid)
    if subj is None:
        text, markup = _not_found(lang)
        await _edit(update, text, markup)
        return
    rows = [
        [
            InlineKeyboardButton(
                f"🗑 {_kind_label(lang, g.kind)} {g.value}", callback_data=f"grade:del:{g.id}"
            )
        ]
        for g in subj.grades
    ]
    rows.append(
        [InlineKeyboardButton(t(lang, "grades.back_to_subject"), callback_data=f"subj:open:{sid}")]
    )
    await _edit(update, t(lang, "grades.pick_del"), InlineKeyboardMarkup(rows))


async def del_grade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    sid = await repo.delete_grade(update.effective_user.id, _arg(update.callback_query.data))
    if sid is None:
        text, markup = await _render_list(update.effective_user.id, lang)
    else:
        text, markup = await _render_subject(update.effective_user.id, sid, lang)
    await _edit(update, text, markup)


async def confirm_del_subject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    sid = _arg(update.callback_query.data)
    subj = await repo.get_subject(update.effective_user.id, sid)
    if subj is None:
        text, markup = _not_found(lang)
        await _edit(update, text, markup)
        return
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "common.yes_delete"), callback_data=f"subj:delyes:{sid}")],
            [InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data=f"subj:open:{sid}")],
        ]
    )
    await _edit(update, t(lang, "grades.confirm_del_subj", title=subj.title), markup)


async def do_del_subject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    await repo.delete_subject(update.effective_user.id, _arg(update.callback_query.data))
    text, markup = await _render_list(update.effective_user.id, lang)
    await _edit(update, text, markup)


# ----- диалоги ввода -----

async def new_subject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    subjects = await repo.list_subjects(update.effective_user.id)
    if len(subjects) >= MAX_SUBJECTS:
        await edit_safely(update.callback_query, t(lang, "grades.limit_subjects", max=MAX_SUBJECTS))
        return ConversationHandler.END
    await edit_safely(update.callback_query, t(lang, "grades.enter_name"), reply_markup=_cancel_kb(lang))
    return G_NAME


async def recv_subject_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    title = update.message.text.strip()
    if not title or len(title) > MAX_TITLE:
        await update.message.reply_text(
            t(lang, "common.too_long", max=MAX_TITLE), reply_markup=_cancel_kb(lang)
        )
        return G_NAME
    await repo.create_subject(update.effective_user.id, title)
    text, markup = await _render_list(update.effective_user.id, lang)
    await update.message.reply_text(text, reply_markup=markup)
    return ConversationHandler.END


async def rename_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    context.user_data["grade_sid"] = _arg(update.callback_query.data)
    await edit_safely(
        update.callback_query, t(lang, "grades.enter_new_name"), reply_markup=_cancel_kb(lang)
    )
    return G_RENAME


async def recv_rename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    title = update.message.text.strip()
    if not title or len(title) > MAX_TITLE:
        await update.message.reply_text(
            t(lang, "common.too_long", max=MAX_TITLE), reply_markup=_cancel_kb(lang)
        )
        return G_RENAME
    sid = context.user_data.pop("grade_sid", None)
    await repo.rename_subject(update.effective_user.id, sid, title)
    text, markup = await _render_subject(update.effective_user.id, sid, lang)
    await update.message.reply_text(text, reply_markup=markup)
    return ConversationHandler.END


async def add_grade_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    _, _, sid, kind = update.callback_query.data.split(":")
    subj = await repo.get_subject(update.effective_user.id, int(sid))
    if subj is None:
        text, markup = _not_found(lang)
        await _edit(update, text, markup)
        return ConversationHandler.END
    if len(subj.grades) >= MAX_GRADES:
        await edit_safely(update.callback_query, t(lang, "grades.limit_grades", max=MAX_GRADES))
        return ConversationHandler.END
    context.user_data["grade_sid"] = int(sid)
    context.user_data["grade_kind"] = kind
    await edit_safely(
        update.callback_query,
        t(lang, "grades.enter_value", kind=_kind_label(lang, kind)),
        reply_markup=_cancel_kb(lang),
    )
    return G_VALUE


async def recv_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    try:
        value = logic.parse_value(update.message.text)
    except logic.ValueError_ as e:
        await update.message.reply_text(
            t(lang, "common.try_again", err=t(lang, e.key, **e.fmt)),
            reply_markup=_cancel_kb(lang),
        )
        return G_VALUE
    sid = context.user_data.pop("grade_sid", None)
    kind = context.user_data.pop("grade_kind", logic.ORAL)
    await repo.add_grade(update.effective_user.id, sid, kind, value)
    text, markup = await _render_subject(update.effective_user.id, sid, lang)
    await update.message.reply_text(text, reply_markup=markup)
    return ConversationHandler.END


def _clear_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("grade_sid", "grade_kind"):
        context.user_data.pop(k, None)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена по команде /cancel (текстовое сообщение)."""
    lang = await user_lang(update, context)
    _clear_draft(context)
    text, markup = await _render_list(update.effective_user.id, lang)
    await update.message.reply_text(text, reply_markup=markup)
    return ConversationHandler.END


async def cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена по кнопке «⬅️ Отмена» на шаге ввода."""
    lang = await user_lang(update, context)
    _clear_draft(context)
    text, markup = await _render_list(update.effective_user.id, lang)
    await _edit(update, text, markup)
    return ConversationHandler.END


_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(new_subject, pattern=r"^subj:new$"),
        CallbackQueryHandler(rename_entry, pattern=r"^subj:ren:\d+$"),
        CallbackQueryHandler(add_grade_entry, pattern=r"^grade:add:\d+:(sa|ka|muendlich)$"),
    ],
    states={
        G_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_subject_name)],
        G_RENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_rename)],
        G_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_value)],
    },
    fallbacks=[
        CommandHandler("cancel", cancel),
        CallbackQueryHandler(cancel_cb, pattern=r"^grade:cancel$"),
    ],
    per_message=False,
)


def setup(app: Application) -> None:
    register(Module(key="grades", title_key="module.grades", on_open=open_grades))
    app.add_handler(_conversation)
    app.add_handler(CallbackQueryHandler(open_grades, pattern=r"^subj:list$"))
    app.add_handler(CallbackQueryHandler(open_subject, pattern=r"^subj:open:\d+$"))
    app.add_handler(CallbackQueryHandler(confirm_del_subject, pattern=r"^subj:del:\d+$"))
    app.add_handler(CallbackQueryHandler(do_del_subject, pattern=r"^subj:delyes:\d+$"))
    app.add_handler(CallbackQueryHandler(pick_del_grade, pattern=r"^grade:pickdel:\d+$"))
    app.add_handler(CallbackQueryHandler(del_grade, pattern=r"^grade:del:\d+$"))
    # запасной обработчик отмены, если диалог уже завершён (устаревший промпт)
    app.add_handler(CallbackQueryHandler(open_grades, pattern=r"^grade:cancel$"))
