"""
bot/handlers/appeals.py
Система обращений пользователей (тикеты).

Пользователь:
  - Создать обращение («Написать администратору» / «Сообщить о проблеме» в карточке устройства)
  - «Мои обращения» — список (active + inactive; archived скрыты)
  - Войти в активное обращение → «Написать ответ»

Администратор:
  - Уведомление о новом/переданном обращении → Принять / Просмотреть
  - /appeals — список обращений с фильтрами
  - Карточка: Ответить / Закрыть / Передать

Маршрутизация сообщений:
  - Пользователь пишет → назначенному администратору
  - Администратор пишет → пользователю
  - Контакты администратора скрыты: всё через бот
"""

import json
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter, or_f
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.appeals import get_appeal, list_appeals
from bot.roles import Role
from bot.runner import run_script

logger = logging.getLogger(__name__)

router = Router()

_STATUS_LABEL = {
    "inactive": "ожидает",
    "active":   "активно",
    "archived": "закрыто",
}

_STATUS_ICON = {
    "inactive": "⏳",
    "active":   "💬",
    "archived": "✓",
}


# ---------------------------------------------------------------------------
# FSM
# ---------------------------------------------------------------------------

class AppealCreateState(StatesGroup):
    entering_text = State()


class AppealReplyState(StatesGroup):
    entering_text = State()


# ---------------------------------------------------------------------------
# Форматирование
# ---------------------------------------------------------------------------

def _fmt_appeal_card(appeal: dict, show_messages: bool = True) -> str:
    aid       = appeal.get("id", "")[:8]
    username  = appeal.get("username", "—")
    status    = appeal.get("status", "")
    subject   = appeal.get("subject", "—")
    created   = appeal.get("created", "")[:10]
    device    = appeal.get("device_uuid")
    admin_tg  = appeal.get("admin_telegram_id")

    header = (
        f"<b>Обращение #{aid}</b>\n"
        f"Пользователь: {username}\n"
        f"Статус: {_STATUS_ICON.get(status, '')} {_STATUS_LABEL.get(status, status)}\n"
        f"Дата: {created}\n"
    )
    if device:
        header += f"Устройство: <code>{device[:8]}…</code>\n"
    if admin_tg:
        header += f"Администратор: назначен\n"

    header += f"\n<b>Тема:</b> {subject}"

    if show_messages:
        messages = appeal.get("messages", [])
        if messages:
            header += "\n\n<b>Диалог:</b>\n"
            for msg in messages[-10:]:  # последние 10 сообщений
                sender = "Вы" if msg["from"] == "user" else "Поддержка"
                ts = msg.get("ts", "")[:16].replace("T", " ")
                header += f"\n[{ts}] <b>{sender}:</b> {msg['text']}"

    return header


def _fmt_appeal_row(appeal: dict) -> str:
    aid    = appeal.get("id", "")[:8]
    status = appeal.get("status", "")
    icon   = _STATUS_ICON.get(status, "")
    subj   = appeal.get("subject", "")[:35]
    return f"{icon} #{aid} — {subj}"


# ---------------------------------------------------------------------------
# Keyboards — пользователь
# ---------------------------------------------------------------------------

def _kb_my_appeals(appeals: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for a in appeals:
        aid    = a["id"]
        status = a.get("status", "")
        label  = _fmt_appeal_row(a)
        if status == "active":
            rows.append([InlineKeyboardButton(text=label, callback_data=f"appeal:view:{aid}")])
        else:
            # inactive — показываем, но без действия (просто информация)
            rows.append([InlineKeyboardButton(text=label, callback_data=f"appeal:info:{aid}")])
    rows.append([InlineKeyboardButton(text="+ Новое обращение", callback_data="appeal:new")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_appeal_dialog(appeal_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏ Написать ответ", callback_data=f"appeal:reply:{appeal_id}")],
        [InlineKeyboardButton(text="← Назад",          callback_data="appeal:my_list")],
    ])


def _kb_appeal_info_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="← Назад", callback_data="appeal:my_list"),
    ]])


# ---------------------------------------------------------------------------
# Keyboards — администратор
# ---------------------------------------------------------------------------

def _kb_admin_notify(appeal_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✓ Принять",      callback_data=f"adm_appeal:accept:{appeal_id}"),
        InlineKeyboardButton(text="↗ Просмотреть", callback_data=f"adm_appeal:view:{appeal_id}"),
    ]])


def _kb_admin_appeals_filter(status_filter: str) -> InlineKeyboardMarkup:
    marks = {k: ("✓ " if k == status_filter else "") for k in ("inactive", "active", "archived")}
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{marks['inactive']}Ожидают",  callback_data="adm_appeal:f:inactive"),
        InlineKeyboardButton(text=f"{marks['active']}Активные",   callback_data="adm_appeal:f:active"),
        InlineKeyboardButton(text=f"{marks['archived']}Закрытые", callback_data="adm_appeal:f:archived"),
    ]])


def _kb_admin_appeal_card(appeal: dict) -> InlineKeyboardMarkup:
    aid    = appeal["id"]
    status = appeal.get("status", "")
    rows: list[list[InlineKeyboardButton]] = []

    if status == "inactive":
        rows.append([InlineKeyboardButton(text="✓ Принять", callback_data=f"adm_appeal:accept:{aid}")])
    elif status == "active":
        rows.append([
            InlineKeyboardButton(text="✏ Ответить",  callback_data=f"adm_appeal:reply:{aid}"),
            InlineKeyboardButton(text="⇄ Передать",  callback_data=f"adm_appeal:transfer:{aid}"),
        ])
        rows.append([
            InlineKeyboardButton(text="✓ Закрыть",   callback_data=f"adm_appeal:close:{aid}"),
        ])

    rows.append([InlineKeyboardButton(text="← Назад", callback_data="adm_appeal:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Уведомление администраторов о новом/переданном обращении
# ---------------------------------------------------------------------------

async def _notify_admins(
    bot: Bot,
    appeal: dict,
    admin_ids: set[int],
    transferred: bool = False,
) -> None:
    aid      = appeal["id"]
    username = appeal.get("username", "?")
    subject  = appeal.get("subject", "")[:60]

    if transferred:
        title = "Обращение передано на рассмотрение"
        note  = "\n<i>Предыдущий диалог сохранен в обращении.</i>"
    else:
        title = "Новое обращение"
        note  = ""

    text = (
        f"<b>{title}</b>\n\n"
        f"Пользователь: {username}\n"
        f"Тема: {subject}{note}"
    )

    for admin_id in admin_ids:
        try:
            await bot.send_message(
                admin_id,
                text,
                parse_mode="HTML",
                reply_markup=_kb_admin_notify(aid),
            )
        except Exception as e:
            logger.warning("Failed to notify admin %s: %s", admin_id, e)


# ---------------------------------------------------------------------------
# Создание обращения: entry point из user.py (callback appeal:new / appeal:new:device:<uuid>)
# и кнопка «Написать администратору» из главного меню (текстовое сообщение)
# ---------------------------------------------------------------------------

@router.message(F.text == "✍ Написать администратору")
async def msg_appeal_new(
    message: Message,
    role: Role,
    state: FSMContext,
) -> None:
    if role != Role.USER:
        return
    await state.set_state(AppealCreateState.entering_text)
    await state.update_data(device_uuid=None)
    await message.answer("Опишите вашу проблему или вопрос:")


@router.callback_query(F.data.startswith("appeal:new"))
async def cb_appeal_new(
    callback: CallbackQuery,
    role: Role,
    state: FSMContext,
) -> None:
    if role != Role.USER:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    # appeal:new или appeal:new:device:<uuid>
    parts = callback.data.split(":", 3)
    device_uuid = parts[3] if len(parts) > 3 else None

    await state.set_state(AppealCreateState.entering_text)
    await state.update_data(device_uuid=device_uuid)

    if device_uuid:
        prompt = f"Опишите проблему с устройством <code>{device_uuid[:8]}…</code>:"
    else:
        prompt = "Опишите вашу проблему или вопрос:"

    await callback.message.answer(prompt, parse_mode="HTML")
    await callback.answer()


@router.message(StateFilter(AppealCreateState.entering_text))
async def on_appeal_text(
    message: Message,
    role: Role,
    state: FSMContext,
    scripts_path: str,
    verbose: bool,
    store_path: str,
    bot: Bot,
    admin_ids: set[int],
) -> None:
    if role != Role.USER:
        await state.clear()
        return

    text = (message.text or "").strip()
    if not text:
        await message.answer("Сообщение не может быть пустым. Введите текст:")
        return

    data = await state.get_data()
    device_uuid = data.get("device_uuid")

    # Получить данные пользователя из реестра (roles уже прочитали, но нам нужен user_id)
    from bot.roles import find_user_by_telegram_id
    registry_user = find_user_by_telegram_id(message.from_user.id, store_path)
    if not registry_user:
        await state.clear()
        await message.answer("Ошибка: не удалось найти ваш аккаунт.")
        return

    await state.clear()

    # Формируем аргументы скрипта
    cmd = [
        f"{scripts_path}/appeals/add.sh",
        "--user-id",     str(registry_user["id"]),
        "--username",    registry_user["username"],
        "--telegram-id", str(message.from_user.id),
        "--text",        text,
    ]
    if device_uuid:
        cmd += ["--device-uuid", device_uuid]

    rc, stdout, stderr = await run_script(cmd, send=message.answer, verbose=verbose)

    if rc != 0:
        logger.error("appeals/add.sh failed: %s", stderr)
        await message.answer("Не удалось создать обращение. Попробуйте позже.")
        return

    appeal_id = stdout.strip().splitlines()[-1]

    await message.answer(
        "Ваше обращение принято. Администратор ответит вам в ближайшее время."
    )

    # Уведомить администраторов
    appeal = get_appeal(store_path, appeal_id)
    if appeal:
        await _notify_admins(bot, appeal, admin_ids)


# ---------------------------------------------------------------------------
# «Мои обращения» — список (entry point из user.py)
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "appeal:my_list")
async def cb_my_appeals(
    callback: CallbackQuery,
    role: Role,
    store_path: str,
) -> None:
    if role != Role.USER:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    from bot.roles import find_user_by_telegram_id
    registry_user = find_user_by_telegram_id(callback.from_user.id, store_path)
    if not registry_user:
        await callback.answer("Аккаунт не найден.", show_alert=True)
        return

    user_id = str(registry_user["id"])
    appeals = [
        a for a in list_appeals(store_path, user_id=user_id)
        if a.get("status") != "archived"
    ]

    if not appeals:
        await callback.message.edit_text(
            "У вас нет обращений.\n\n"
            "Чтобы создать новое — используйте кнопку «Написать администратору»."
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        f"Ваши обращения ({len(appeals)}):",
        reply_markup=_kb_my_appeals(appeals),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Просмотр активного обращения (пользователь)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("appeal:view:"))
async def cb_appeal_view(
    callback: CallbackQuery,
    role: Role,
    store_path: str,
) -> None:
    if role != Role.USER:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    appeal_id = callback.data.split(":", 2)[2]
    appeal = get_appeal(store_path, appeal_id)

    if not appeal or appeal.get("status") != "active":
        await callback.answer("Обращение недоступно.", show_alert=True)
        return

    await callback.message.edit_text(
        _fmt_appeal_card(appeal, show_messages=True),
        parse_mode="HTML",
        reply_markup=_kb_appeal_dialog(appeal_id),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Информация об inactive-обращении (пользователь)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("appeal:info:"))
async def cb_appeal_info(
    callback: CallbackQuery,
    role: Role,
    store_path: str,
) -> None:
    if role != Role.USER:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    appeal_id = callback.data.split(":", 2)[2]
    appeal = get_appeal(store_path, appeal_id)

    if not appeal:
        await callback.answer("Обращение не найдено.", show_alert=True)
        return

    await callback.message.edit_text(
        _fmt_appeal_card(appeal, show_messages=False) +
        "\n\n<i>Ожидает рассмотрения администратором.</i>",
        parse_mode="HTML",
        reply_markup=_kb_appeal_info_back(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Ответ пользователя в активное обращение
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("appeal:reply:"))
async def cb_appeal_reply_start(
    callback: CallbackQuery,
    role: Role,
    state: FSMContext,
) -> None:
    if role != Role.USER:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    appeal_id = callback.data.split(":", 2)[2]
    await state.set_state(AppealReplyState.entering_text)
    await state.update_data(appeal_id=appeal_id, reply_as="user")
    await callback.message.answer("Введите ваше сообщение:")
    await callback.answer()


@router.message(StateFilter(AppealReplyState.entering_text))
async def on_reply_text(
    message: Message,
    role: Role,
    state: FSMContext,
    scripts_path: str,
    verbose: bool,
    store_path: str,
    bot: Bot,
    admin_ids: set[int],
) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Сообщение не может быть пустым. Введите текст:")
        return

    data = await state.get_data()
    appeal_id = data.get("appeal_id", "")
    reply_as  = data.get("reply_as", "user")   # "user" или "admin"

    await state.clear()

    appeal = get_appeal(store_path, appeal_id)
    if not appeal or appeal.get("status") != "active":
        await message.answer("Обращение недоступно или уже закрыто.")
        return

    # Записать сообщение
    cmd = [
        f"{scripts_path}/appeals/reply.sh",
        "--id",   appeal_id,
        "--from", reply_as,
        "--text", text,
    ]
    rc, _, stderr = await run_script(cmd, send=message.answer, verbose=verbose)

    if rc != 0:
        logger.error("appeals/reply.sh failed: %s", stderr)
        await message.answer("Не удалось отправить сообщение. Попробуйте позже.")
        return

    # Маршрутизация: user → admin, admin → user
    if reply_as == "user":
        admin_tg_id = appeal.get("admin_telegram_id")
        if admin_tg_id:
            try:
                aid_short = appeal_id[:8]
                username  = appeal.get("username", "?")
                await bot.send_message(
                    admin_tg_id,
                    f"<b>Обращение #{aid_short}</b> — {username}\n\n{text}",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning("Failed to forward reply to admin: %s", e)
        await message.answer("Сообщение отправлено.")

    else:  # admin
        user_tg_id = appeal.get("telegram_id")
        if user_tg_id:
            try:
                await bot.send_message(
                    user_tg_id,
                    f"<b>Ответ по вашему обращению</b>\n\n{text}",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning("Failed to forward reply to user: %s", e)
        await message.answer("Ответ отправлен пользователю.")


# ---------------------------------------------------------------------------
# /appeals — список обращений для администратора
# ---------------------------------------------------------------------------

@router.message(or_f(Command("appeals"), F.text == "📋 Обращения"))
async def cmd_appeals(
    message: Message,
    role: Role,
    store_path: str,
) -> None:
    if role == Role.ADMIN:
        await _show_admin_appeals(message.answer, store_path, "inactive")
    elif role == Role.USER:
        from bot.roles import find_user_by_telegram_id
        registry_user = find_user_by_telegram_id(message.from_user.id, store_path)
        if not registry_user:
            await message.answer("Аккаунт не найден.")
            return
        user_id = str(registry_user["id"])
        user_appeals = [
            a for a in list_appeals(store_path, user_id=user_id)
            if a.get("status") != "archived"
        ]
        if not user_appeals:
            await message.answer(
                "У вас нет обращений.\n\n"
                "Используйте кнопку «Написать администратору» в разделе /devices."
            )
            return
        await message.answer(
            f"Ваши обращения ({len(user_appeals)}):",
            reply_markup=_kb_my_appeals(user_appeals),
        )
    else:
        await message.answer("Доступ ограничен.")


async def _show_admin_appeals(send, store_path: str, status_filter: str) -> None:
    appeals = list_appeals(store_path, status=status_filter)
    count   = len(appeals)
    label   = _STATUS_LABEL.get(status_filter, status_filter)

    rows: list[list[InlineKeyboardButton]] = []
    for a in appeals:
        aid   = a["id"]
        label_row = _fmt_appeal_row(a)
        rows.append([InlineKeyboardButton(
            text=label_row,
            callback_data=f"adm_appeal:view:{aid}",
        )])

    kb = InlineKeyboardMarkup(
        inline_keyboard=[_kb_admin_appeals_filter(status_filter).inline_keyboard[0]] + rows
    )

    await send(
        f"Обращения — {_STATUS_LABEL.get(status_filter, status_filter)}: {count}",
        reply_markup=kb,
    )


# ---------------------------------------------------------------------------
# Фильтр списка администратора
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("adm_appeal:f:"))
async def cb_admin_filter(
    callback: CallbackQuery,
    role: Role,
    store_path: str,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    status_filter = callback.data.split(":")[2]
    appeals = list_appeals(store_path, status=status_filter)

    rows: list[list[InlineKeyboardButton]] = []
    for a in appeals:
        aid = a["id"]
        rows.append([InlineKeyboardButton(
            text=_fmt_appeal_row(a),
            callback_data=f"adm_appeal:view:{aid}",
        )])

    kb = InlineKeyboardMarkup(
        inline_keyboard=[_kb_admin_appeals_filter(status_filter).inline_keyboard[0]] + rows
    )

    await callback.message.edit_text(
        f"Обращения — {_STATUS_LABEL.get(status_filter, status_filter)}: {len(appeals)}",
        reply_markup=kb,
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Карточка обращения (администратор)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("adm_appeal:view:"))
async def cb_admin_appeal_view(
    callback: CallbackQuery,
    role: Role,
    store_path: str,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    appeal_id = callback.data.split(":", 2)[2]
    appeal = get_appeal(store_path, appeal_id)

    if not appeal:
        await callback.answer("Обращение не найдено.", show_alert=True)
        return

    await callback.message.edit_text(
        _fmt_appeal_card(appeal, show_messages=True),
        parse_mode="HTML",
        reply_markup=_kb_admin_appeal_card(appeal),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Принять обращение
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("adm_appeal:accept:"))
async def cb_admin_accept(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
    store_path: str,
    bot: Bot,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    appeal_id  = callback.data.split(":", 2)[2]
    admin_tg_id = callback.from_user.id

    appeal = get_appeal(store_path, appeal_id)
    if not appeal:
        await callback.answer("Обращение не найдено.", show_alert=True)
        return
    if appeal.get("status") != "inactive":
        await callback.answer("Обращение уже принято или закрыто.", show_alert=True)
        return

    rc, _, stderr = await run_script(
        [
            f"{scripts_path}/appeals/update.sh",
            "--id",                appeal_id,
            "--status",            "active",
            "--admin-telegram-id", str(admin_tg_id),
        ],
        send=callback.message.answer, verbose=verbose,
    )

    if rc != 0:
        logger.error("appeals/update.sh failed: %s", stderr)
        await callback.answer("Ошибка при принятии обращения.", show_alert=True)
        return

    # Уведомить пользователя
    user_tg_id = appeal.get("telegram_id")
    if user_tg_id:
        try:
            await bot.send_message(
                user_tg_id,
                "Ваше обращение принято. Администратор свяжется с вами в ближайшее время.",
            )
        except Exception as e:
            logger.warning("Failed to notify user on appeal accept: %s", e)

    # Обновить карточку
    updated = get_appeal(store_path, appeal_id)
    if updated:
        await callback.message.edit_text(
            _fmt_appeal_card(updated, show_messages=True),
            parse_mode="HTML",
            reply_markup=_kb_admin_appeal_card(updated),
        )
    await callback.answer("Обращение принято.")


# ---------------------------------------------------------------------------
# Ответить (администратор)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("adm_appeal:reply:"))
async def cb_admin_reply_start(
    callback: CallbackQuery,
    role: Role,
    state: FSMContext,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    appeal_id = callback.data.split(":", 2)[2]
    await state.set_state(AppealReplyState.entering_text)
    await state.update_data(appeal_id=appeal_id, reply_as="admin")
    await callback.message.answer("Введите ответ пользователю:")
    await callback.answer()


# ---------------------------------------------------------------------------
# Передать обращение
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("adm_appeal:transfer:"))
async def cb_admin_transfer(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
    store_path: str,
    bot: Bot,
    admin_ids: set[int],
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    appeal_id = callback.data.split(":", 2)[2]
    appeal = get_appeal(store_path, appeal_id)

    if not appeal or appeal.get("status") != "active":
        await callback.answer("Обращение недоступно.", show_alert=True)
        return

    # Снять назначение, вернуть в inactive
    rc, _, stderr = await run_script(
        [
            f"{scripts_path}/appeals/update.sh",
            "--id",                appeal_id,
            "--status",            "inactive",
            "--admin-telegram-id", "",          # сброс в null
        ],
        send=callback.message.answer, verbose=verbose,
    )

    if rc != 0:
        logger.error("appeals/update.sh (transfer) failed: %s", stderr)
        await callback.answer("Ошибка при передаче обращения.", show_alert=True)
        return

    updated = get_appeal(store_path, appeal_id)
    await callback.message.edit_text(
        f"Обращение #{appeal_id[:8]} передано на повторное рассмотрение."
    )

    # Уведомить всех администраторов
    if updated:
        await _notify_admins(bot, updated, admin_ids, transferred=True)

    await callback.answer()


# ---------------------------------------------------------------------------
# Закрыть обращение
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("adm_appeal:close:"))
async def cb_admin_close(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
    store_path: str,
    bot: Bot,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    appeal_id = callback.data.split(":", 2)[2]
    appeal = get_appeal(store_path, appeal_id)

    if not appeal or appeal.get("status") != "active":
        await callback.answer("Обращение недоступно.", show_alert=True)
        return

    rc, _, stderr = await run_script(
        [
            f"{scripts_path}/appeals/update.sh",
            "--id",     appeal_id,
            "--status", "archived",
        ],
        send=callback.message.answer, verbose=verbose,
    )

    if rc != 0:
        logger.error("appeals/update.sh (close) failed: %s", stderr)
        await callback.answer("Ошибка при закрытии обращения.", show_alert=True)
        return

    # Уведомить пользователя
    user_tg_id = appeal.get("telegram_id")
    if user_tg_id:
        try:
            await bot.send_message(
                user_tg_id,
                "Ваше обращение закрыто. Если у вас остались вопросы — создайте новое обращение.",
            )
        except Exception as e:
            logger.warning("Failed to notify user on appeal close: %s", e)

    await callback.message.edit_text(
        f"Обращение #{appeal_id[:8]} закрыто."
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Назад к списку (из карточки)
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "adm_appeal:back")
async def cb_admin_back(
    callback: CallbackQuery,
    role: Role,
    store_path: str,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    appeals = list_appeals(store_path, status="inactive")
    rows: list[list[InlineKeyboardButton]] = []
    for a in appeals:
        rows.append([InlineKeyboardButton(
            text=_fmt_appeal_row(a),
            callback_data=f"adm_appeal:view:{a['id']}",
        )])

    kb = InlineKeyboardMarkup(
        inline_keyboard=[_kb_admin_appeals_filter("inactive").inline_keyboard[0]] + rows
    )

    await callback.message.edit_text(
        f"Обращения — ожидают: {len(appeals)}",
        reply_markup=kb,
    )
    await callback.answer()
