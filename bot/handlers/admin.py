import json
import logging

from aiogram import Bot, F, Router
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


def _kb_user_card(user: dict, status_filter: str) -> InlineKeyboardMarkup:
    """Клавиатура карточки с кнопками действий в зависимости от статуса пользователя."""
    status = user.get("status", "")
    core_nodes = user.get("core_nodes") or []
    uid = str(user.get("id", ""))

    rows: list[list[InlineKeyboardButton]] = []

    if status == "inactive" and not core_nodes:
        rows.append([
            InlineKeyboardButton(text="✓ Одобрить", callback_data=f"user:approve:{uid}:{status_filter}"),
            InlineKeyboardButton(text="✗ Удалить",  callback_data=f"user:remove:{uid}:{status_filter}"),
        ])
        rows.append([
            InlineKeyboardButton(text="⚑ Заблокировать", callback_data=f"user:archive:{uid}:{status_filter}"),
        ])
    elif status == "inactive":
        rows.append([
            InlineKeyboardButton(text="▷ Восстановить", callback_data=f"user:activate:{uid}:{status_filter}"),
            InlineKeyboardButton(text="⚑ Архивировать", callback_data=f"user:archive:{uid}:{status_filter}"),
        ])
        rows.append([
            InlineKeyboardButton(text="✗ Удалить", callback_data=f"user:remove:{uid}:{status_filter}"),
        ])
    elif status == "active":
        rows.append([
            InlineKeyboardButton(text="⏸ Приостановить", callback_data=f"user:suspend:{uid}:{status_filter}"),
            InlineKeyboardButton(text="⚑ Архивировать",  callback_data=f"user:archive:{uid}:{status_filter}"),
        ])
        rows.append([
            InlineKeyboardButton(text="✗ Удалить", callback_data=f"user:remove:{uid}:{status_filter}"),
        ])
    elif status == "archived":
        rows.append([
            InlineKeyboardButton(text="✗ Удалить", callback_data=f"user:remove:{uid}:{status_filter}"),
        ])

    rows.append([
        InlineKeyboardButton(text="← Назад", callback_data=f"users:back:{status_filter}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
        reply_markup=_kb_user_card(user, status_filter),
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
# Каскадные операции с устройствами
# ---------------------------------------------------------------------------

async def _cascade_deactivate_devices(
    user_id: str, scripts_path: str, verbose: bool, send
) -> bool:
    """Деактивировать все активные устройства пользователя (снять с Entry-нод)."""
    rc, stdout, _ = await run_script(
        [f"{scripts_path}/devices/list.sh", "--user", user_id],
        send=send, verbose=verbose,
    )
    if rc != 0:
        return False
    try:
        devices = json.loads(stdout)
    except json.JSONDecodeError:
        return False

    for device in devices:
        if device.get("status") != "active":
            continue
        uuid = device["uuid"]
        rc, _, stderr = await run_script(
            [f"{scripts_path}/devices/deactivate.sh", "--uuid", uuid],
            send=send, verbose=verbose,
        )
        if rc != 0:
            logger.error("devices/deactivate.sh failed for %s: %s", uuid, stderr)
            return False
    return True


async def _cascade_archive_devices(
    user_id: str, scripts_path: str, verbose: bool, send
) -> bool:
    """Деактивировать и архивировать все устройства пользователя."""
    rc, stdout, _ = await run_script(
        [f"{scripts_path}/devices/list.sh", "--user", user_id],
        send=send, verbose=verbose,
    )
    if rc != 0:
        return False
    try:
        devices = json.loads(stdout)
    except json.JSONDecodeError:
        return False

    for device in devices:
        uuid = device["uuid"]
        status = device.get("status", "")

        if status == "active":
            rc, _, stderr = await run_script(
                [f"{scripts_path}/devices/deactivate.sh", "--uuid", uuid],
                send=send, verbose=verbose,
            )
            if rc != 0:
                logger.error("devices/deactivate.sh failed for %s: %s", uuid, stderr)
                return False

        if status != "archived":
            rc, _, stderr = await run_script(
                [f"{scripts_path}/devices/update.sh", "--uuid", uuid, "--status", "archived"],
                send=send, verbose=verbose,
            )
            if rc != 0:
                logger.error("devices/update.sh --status archived failed for %s: %s", uuid, stderr)
                return False
    return True


async def _refresh_user_card(
    callback: CallbackQuery,
    user_id: str,
    status_filter: str,
    scripts_path: str,
    verbose: bool,
) -> None:
    """Перезагрузить и отобразить карточку пользователя."""
    user = await _fetch_user_by_id(user_id, scripts_path, verbose, callback.message.answer)
    if not user:
        await callback.message.edit_text("Пользователь не найден.")
        return
    await callback.message.edit_text(
        _format_user_card(user),
        reply_markup=_kb_user_card(user, status_filter),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Helpers для карточки: клавиатура выбора Core-ноды
# ---------------------------------------------------------------------------

def _kb_core_selection_card(user_id: str, status_filter: str, nodes: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for node in nodes:
        ip = node["ip"]
        label = node.get("hostname") or ip
        location = node.get("location", "")
        btn_text = f"{label} ({location})" if location else label
        rows.append([InlineKeyboardButton(
            text=btn_text,
            callback_data=f"user:core:{user_id}:{status_filter}:{ip}",
        )])
    rows.append([InlineKeyboardButton(
        text="← Назад",
        callback_data=f"user:back:{user_id}:{status_filter}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Действия в карточке пользователя
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("user:approve:"))
async def cb_user_approve(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    parts = callback.data.split(":")  # user:approve:<id>:<filter>
    user_id, status_filter = parts[2], parts[3]

    rc, stdout, stderr = await run_script(
        [f"{scripts_path}/nodes/list-core.sh"],
        send=callback.message.answer, verbose=verbose,
    )
    if rc != 0:
        logger.error("nodes/list-core.sh failed: %s", stderr)
        await callback.answer("Не удалось получить список Core-нод.", show_alert=True)
        return

    try:
        nodes = json.loads(stdout)
    except json.JSONDecodeError:
        logger.error("nodes/list-core.sh returned invalid JSON: %s", stdout)
        await callback.answer("Ошибка при получении списка нод.", show_alert=True)
        return

    if not nodes:
        await callback.answer("Нет доступных Core-нод.", show_alert=True)
        return

    user = await _fetch_user_by_id(user_id, scripts_path, verbose, callback.message.answer)
    username = user["username"] if user else f"ID={user_id}"

    await callback.message.edit_text(
        f"Выберите Core-ноду для <b>{username}</b>:",
        reply_markup=_kb_core_selection_card(user_id, status_filter, nodes),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("user:core:"))
async def cb_user_core(
    callback: CallbackQuery,
    role: Role,
    bot: Bot,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    parts = callback.data.split(":", 4)  # user:core:<id>:<filter>:<ip>
    if len(parts) < 5:
        await callback.answer("Ошибка формата.", show_alert=True)
        return

    user_id, status_filter, core_ip = parts[2], parts[3], parts[4]

    user = await _fetch_user_by_id(user_id, scripts_path, verbose, callback.message.answer)
    if not user:
        await callback.answer("Пользователь не найден или уже обработан.", show_alert=True)
        return

    rc, _, stderr = await run_script(
        [
            f"{scripts_path}/users/update.sh",
            "--id", user_id,
            "--add-core-node", core_ip,
            "--status", "active",
        ],
        send=callback.message.answer, verbose=verbose,
    )
    if rc != 0:
        logger.error("users/update.sh failed: %s", stderr)
        await callback.answer("Ошибка при одобрении заявки.", show_alert=True)
        return

    tg_id = user.get("telegram_id")
    if tg_id:
        try:
            await bot.send_message(
                tg_id,
                "Ваша заявка одобрена. Добро пожаловать в Sigil Gate!\n"
                "Введите /start для начала работы.",
            )
        except Exception as e:
            logger.warning("Failed to notify approved user %s: %s", tg_id, e)

    await _refresh_user_card(callback, user_id, status_filter, scripts_path, verbose)
    await callback.answer()


@router.callback_query(F.data.startswith("user:back:"))
async def cb_user_back(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    parts = callback.data.split(":")  # user:back:<id>:<filter>
    user_id, status_filter = parts[2], parts[3]

    await _refresh_user_card(callback, user_id, status_filter, scripts_path, verbose)
    await callback.answer()


@router.callback_query(F.data.startswith("user:activate:"))
async def cb_user_activate(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    parts = callback.data.split(":")  # user:activate:<id>:<filter>
    user_id, status_filter = parts[2], parts[3]

    rc, _, stderr = await run_script(
        [f"{scripts_path}/users/update.sh", "--id", user_id, "--status", "active"],
        send=callback.message.answer, verbose=verbose,
    )
    if rc != 0:
        logger.error("users/update.sh failed: %s", stderr)
        await callback.answer("Ошибка при восстановлении пользователя.", show_alert=True)
        return

    await _refresh_user_card(callback, user_id, status_filter, scripts_path, verbose)
    await callback.answer()


@router.callback_query(F.data.startswith("user:suspend:"))
async def cb_user_suspend(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    parts = callback.data.split(":")  # user:suspend:<id>:<filter>
    user_id, status_filter = parts[2], parts[3]

    ok = await _cascade_deactivate_devices(
        user_id, scripts_path, verbose, callback.message.answer
    )
    if not ok:
        await callback.answer("Ошибка при деактивации устройств.", show_alert=True)
        return

    rc, _, stderr = await run_script(
        [f"{scripts_path}/users/update.sh", "--id", user_id, "--status", "inactive"],
        send=callback.message.answer, verbose=verbose,
    )
    if rc != 0:
        logger.error("users/update.sh failed: %s", stderr)
        await callback.answer("Ошибка при приостановке пользователя.", show_alert=True)
        return

    await _refresh_user_card(callback, user_id, status_filter, scripts_path, verbose)
    await callback.answer()


@router.callback_query(F.data.startswith("user:archive:"))
async def cb_user_archive(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    parts = callback.data.split(":")  # user:archive:<id>:<filter>
    user_id, status_filter = parts[2], parts[3]

    ok = await _cascade_archive_devices(
        user_id, scripts_path, verbose, callback.message.answer
    )
    if not ok:
        await callback.answer("Ошибка при архивировании устройств.", show_alert=True)
        return

    rc, _, stderr = await run_script(
        [f"{scripts_path}/users/update.sh", "--id", user_id, "--status", "archived"],
        send=callback.message.answer, verbose=verbose,
    )
    if rc != 0:
        logger.error("users/update.sh failed: %s", stderr)
        await callback.answer("Ошибка при архивировании пользователя.", show_alert=True)
        return

    await _refresh_user_card(callback, user_id, status_filter, scripts_path, verbose)
    await callback.answer()


@router.callback_query(F.data.startswith("user:remove:"))
async def cb_user_remove(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    parts = callback.data.split(":")  # user:remove:<id>:<filter>
    user_id, status_filter = parts[2], parts[3]

    rc, _, stderr = await run_script(
        [f"{scripts_path}/users/remove.sh", "--id", user_id],
        send=callback.message.answer, verbose=verbose,
    )
    if rc != 0:
        logger.error("users/remove.sh failed: %s", stderr)
        await callback.answer("Ошибка при удалении пользователя.", show_alert=True)
        return

    users = await _fetch_users(status_filter, scripts_path, verbose, callback.message.answer)
    if users is None:
        await callback.message.edit_text("Пользователь удалён.")
        await callback.answer()
        return

    await callback.message.edit_text(
        _list_text(status_filter, len(users)),
        reply_markup=_kb_users_list(users, status_filter),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Helpers для обработки заявок на регистрацию
# ---------------------------------------------------------------------------

def _kb_reg_notify(user_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✓ Одобрить",      callback_data=f"reg:approve:{user_id}"),
        InlineKeyboardButton(text="✗ Удалить",       callback_data=f"reg:decline:{user_id}"),
        InlineKeyboardButton(text="⚑ Заблокировать", callback_data=f"reg:ban:{user_id}"),
    ]])


def _kb_core_selection(user_id: str, nodes: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for node in nodes:
        ip = node["ip"]
        label = node.get("hostname") or ip
        location = node.get("location", "")
        btn_text = f"{label} ({location})" if location else label
        rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"reg:core:{user_id}:{ip}")])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=f"reg:back:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _fmt_reg_notify(user: dict) -> str:
    telegram = user.get("telegram") or "—"
    return (
        "<b>Новая заявка на регистрацию</b>\n\n"
        f"Пользователь: {user.get('username')}\n"
        f"Telegram: {telegram}\n"
        f"ID в реестре: {user.get('id')}"
    )


async def _fetch_user_by_id(
    user_id: str, scripts_path: str, verbose: bool, send
) -> dict | None:
    rc, stdout, stderr = await run_script(
        [f"{scripts_path}/users/get.sh", "--id", user_id],
        send=send, verbose=verbose,
    )
    if rc != 0:
        logger.error("users/get.sh failed: %s", stderr)
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        logger.error("users/get.sh returned invalid JSON: %s", stdout)
        return None


# ---------------------------------------------------------------------------
# Одобрение заявки — показать выбор Core-ноды
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("reg:approve:"))
async def cb_reg_approve(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    user_id = callback.data.split(":")[2]

    rc, stdout, stderr = await run_script(
        [f"{scripts_path}/nodes/list-core.sh"],
        send=callback.message.answer, verbose=verbose,
    )
    if rc != 0:
        logger.error("nodes/list-core.sh failed: %s", stderr)
        await callback.answer("Не удалось получить список Core-нод.", show_alert=True)
        return

    try:
        nodes = json.loads(stdout)
    except json.JSONDecodeError:
        logger.error("nodes/list-core.sh returned invalid JSON: %s", stdout)
        await callback.answer("Ошибка при получении списка нод.", show_alert=True)
        return

    if not nodes:
        await callback.answer("Нет доступных Core-нод.", show_alert=True)
        return

    user = await _fetch_user_by_id(user_id, scripts_path, verbose, callback.message.answer)
    username = user["username"] if user else f"ID={user_id}"

    await callback.message.edit_text(
        f"Выберите Core-ноду для <b>{username}</b>:",
        reply_markup=_kb_core_selection(user_id, nodes),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Выбор Core-ноды → одобрение
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("reg:core:"))
async def cb_reg_core(
    callback: CallbackQuery,
    role: Role,
    bot: Bot,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    parts = callback.data.split(":", 3)  # reg:core:<user_id>:<core_ip>
    if len(parts) < 4:
        await callback.answer("Ошибка формата.", show_alert=True)
        return

    user_id = parts[2]
    core_ip = parts[3]

    user = await _fetch_user_by_id(user_id, scripts_path, verbose, callback.message.answer)
    if not user:
        await callback.answer("Пользователь не найден или уже обработан.", show_alert=True)
        return

    rc, stdout, stderr = await run_script(
        [
            f"{scripts_path}/users/update.sh",
            "--id", user_id,
            "--add-core-node", core_ip,
            "--status", "active",
        ],
        send=callback.message.answer, verbose=verbose,
    )
    if rc != 0:
        logger.error("users/update.sh failed: %s", stderr)
        await callback.answer("Ошибка при одобрении заявки.", show_alert=True)
        return

    username = user["username"]
    await callback.message.edit_text(
        f"Пользователь <b>{username}</b> одобрен.\nCore-нода: {core_ip}",
        parse_mode="HTML",
    )

    tg_id = user.get("telegram_id")
    if tg_id:
        try:
            await bot.send_message(
                tg_id,
                "Ваша заявка одобрена. Добро пожаловать в Sigil Gate!\n"
                "Введите /start для начала работы.",
            )
        except Exception as e:
            logger.warning("Failed to notify approved user %s: %s", tg_id, e)

    await callback.answer()


# ---------------------------------------------------------------------------
# Отклонение заявки (удаление пользователя)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("reg:decline:"))
async def cb_reg_decline(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    user_id = callback.data.split(":")[2]

    user = await _fetch_user_by_id(user_id, scripts_path, verbose, callback.message.answer)
    username = user["username"] if user else f"ID={user_id}"

    rc, stdout, stderr = await run_script(
        [f"{scripts_path}/users/remove.sh", "--id", user_id],
        send=callback.message.answer, verbose=verbose,
    )
    if rc != 0:
        logger.error("users/remove.sh failed: %s", stderr)
        await callback.answer("Ошибка при удалении заявки.", show_alert=True)
        return

    await callback.message.edit_text(
        f"Заявка пользователя <b>{username}</b> отклонена и удалена.",
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Блокировка при регистрации (archived)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("reg:ban:"))
async def cb_reg_ban(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    user_id = callback.data.split(":")[2]

    user = await _fetch_user_by_id(user_id, scripts_path, verbose, callback.message.answer)
    username = user["username"] if user else f"ID={user_id}"

    rc, stdout, stderr = await run_script(
        [f"{scripts_path}/users/update.sh", "--id", user_id, "--status", "archived"],
        send=callback.message.answer, verbose=verbose,
    )
    if rc != 0:
        logger.error("users/update.sh failed: %s", stderr)
        await callback.answer("Ошибка при блокировке пользователя.", show_alert=True)
        return

    await callback.message.edit_text(
        f"Пользователь <b>{username}</b> заблокирован (archived).",
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Назад к уведомлению (из выбора Core-ноды)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("reg:back:"))
async def cb_reg_back(
    callback: CallbackQuery,
    role: Role,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role != Role.ADMIN:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    user_id = callback.data.split(":")[2]

    user = await _fetch_user_by_id(user_id, scripts_path, verbose, callback.message.answer)
    if not user:
        await callback.answer("Пользователь не найден или уже обработан.", show_alert=True)
        return

    await callback.message.edit_text(
        _fmt_reg_notify(user),
        reply_markup=_kb_reg_notify(str(user["id"])),
        parse_mode="HTML",
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
