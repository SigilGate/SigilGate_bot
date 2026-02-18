import json
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.roles import Role
from bot.runner import run_script

logger = logging.getLogger(__name__)

router = Router()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kb_users_list(users: list[dict], status_filter: str) -> InlineKeyboardMarkup:
    """Клавиатура списка: строка фильтров + кнопка на каждого пользователя."""
    all_mark    = "✓ " if status_filter == "all"    else ""
    active_mark = "✓ " if status_filter == "active" else ""

    rows = [[
        InlineKeyboardButton(text=f"{all_mark}Все",      callback_data="users:f:all"),
        InlineKeyboardButton(text=f"{active_mark}Активные", callback_data="users:f:active"),
    ]]

    for u in users:
        rows.append([
            InlineKeyboardButton(
                text=u["username"],
                callback_data=f"users:c:{u['id']}:{status_filter}",
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_user_card(status_filter: str) -> InlineKeyboardMarkup:
    """Клавиатура карточки: кнопка «Назад»."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="← Назад", callback_data=f"users:back:{status_filter}"),
    ]])


def _format_user_card(user: dict) -> str:
    def fmt(val) -> str:
        if val is None or val == "" or val == []:
            return "—"
        if isinstance(val, list):
            return ", ".join(str(v) for v in val)
        return str(val)

    return (
        "<b>Карточка пользователя</b>\n\n"
        f"ID: {fmt(user.get('id'))}\n"
        f"Имя: {fmt(user.get('username'))}\n"
        f"Статус: {fmt(user.get('status'))}\n"
        f"Email: {fmt(user.get('email'))}\n"
        f"Telegram: {fmt(user.get('telegram'))}\n"
        f"Telegram ID: {fmt(user.get('telegram_id'))}\n"
        f"Ноды: {fmt(user.get('core_nodes'))}\n"
        f"Дата регистрации: {fmt(user.get('created'))}"
    )


def _list_text(status_filter: str, count: int) -> str:
    label = "активных" if status_filter == "active" else "всего"
    return f"Пользователи — {label}: {count}"


async def _fetch_users(
    status_filter: str,
    scripts_path: str,
    verbose: bool,
    send,
) -> list[dict] | None:
    cmd = [f"{scripts_path}/users/list.sh"]
    if status_filter == "active":
        cmd += ["--status", "active"]

    rc, stdout, stderr = await run_script(cmd, send=send, verbose=verbose)

    if rc != 0:
        logger.error("users/list.sh failed: %s", stderr)
        return None

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        logger.error("users/list.sh returned invalid JSON: %s", stdout)
        return None


# ---------------------------------------------------------------------------
# /users
# ---------------------------------------------------------------------------

@router.message(Command("users"))
async def cmd_users(
    message: Message,
    role: Role,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await message.answer("Доступ ограничен.")
        return

    users = await _fetch_users("all", scripts_path, verbose, message.answer)
    if users is None:
        await message.answer("Не удалось получить список пользователей.")
        return

    await message.answer(
        _list_text("all", len(users)),
        reply_markup=_kb_users_list(users, "all"),
    )


# ---------------------------------------------------------------------------
# Фильтр списка
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("users:f:"))
async def cb_users_filter(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    status_filter = callback.data.split(":")[2]

    users = await _fetch_users(status_filter, scripts_path, verbose, callback.message.answer)
    if users is None:
        await callback.answer("Ошибка при получении списка.", show_alert=True)
        return

    await callback.message.edit_text(
        _list_text(status_filter, len(users)),
        reply_markup=_kb_users_list(users, status_filter),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Карточка пользователя
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("users:c:"))
async def cb_user_card(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    parts = callback.data.split(":")  # users:c:<id>:<filter>
    user_id = parts[2]
    status_filter = parts[3] if len(parts) > 3 else "all"

    cmd = [f"{scripts_path}/users/get.sh", "--id", user_id]
    rc, stdout, stderr = await run_script(cmd, send=callback.message.answer, verbose=verbose)

    if rc != 0:
        logger.error("users/get.sh failed: %s", stderr)
        await callback.answer("Ошибка при получении данных.", show_alert=True)
        return

    try:
        user = json.loads(stdout)
    except json.JSONDecodeError:
        logger.error("users/get.sh returned invalid JSON: %s", stdout)
        await callback.answer("Ошибка при разборе данных.", show_alert=True)
        return

    await callback.message.edit_text(
        _format_user_card(user),
        reply_markup=_kb_user_card(status_filter),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Назад к списку
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("users:back:"))
async def cb_users_back(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    status_filter = callback.data.split(":")[2]

    users = await _fetch_users(status_filter, scripts_path, verbose, callback.message.answer)
    if users is None:
        await callback.answer("Ошибка при получении списка.", show_alert=True)
        return

    await callback.message.edit_text(
        _list_text(status_filter, len(users)),
        reply_markup=_kb_users_list(users, status_filter),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# /status — заглушка
# ---------------------------------------------------------------------------

@router.message(Command("status"))
async def cmd_status(message: Message, role: Role) -> None:
    if role == Role.ADMIN:
        await message.answer("Здесь будет статус сети.")
    else:
        await message.answer("Доступ ограничен.")
