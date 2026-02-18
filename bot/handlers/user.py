import json
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    CopyTextButton,
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

def _kb_devices_list(devices: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=d["device"], callback_data=f"mydev:c:{d['uuid']}")]
        for d in devices
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_device_card(links: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for i, link in enumerate(links):
        label = "📋 Скопировать конфигурацию" if len(links) == 1 else f"📋 Конфигурация {i + 1}"
        rows.append([
            InlineKeyboardButton(text=label, copy_text=CopyTextButton(text=link))
        ])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="mydev:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_device_card(device: dict, links: list[str]) -> str:
    def fmt(val) -> str:
        return "—" if (val is None or val == "") else str(val)

    lines = [
        f"<b>Устройство: {fmt(device.get('device'))}</b>\n",
        f"UUID: <code>{fmt(device.get('uuid'))}</code>",
        f"Статус: {fmt(device.get('status'))}",
        f"Дата добавления: {fmt(device.get('created'))}",
    ]

    if links:
        lines.append("\n<b>Конфигурация для подключения:</b>")
        for link in links:
            lines.append(f"<code>{link}</code>")
    else:
        lines.append("\nКонфигурация недоступна.")

    return "\n".join(lines)


async def _fetch_devices(
    user_id: int,
    scripts_path: str,
    verbose: bool,
    send,
) -> list[dict] | None:
    cmd = [f"{scripts_path}/devices/list.sh", "--user", str(user_id)]
    rc, stdout, stderr = await run_script(cmd, send=send, verbose=verbose)
    if rc != 0:
        logger.error("devices/list.sh failed: %s", stderr)
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        logger.error("devices/list.sh returned invalid JSON: %s", stdout)
        return None


async def _fetch_config(
    uuid: str,
    scripts_path: str,
    verbose: bool,
    send,
) -> list[str]:
    cmd = [f"{scripts_path}/devices/config.sh", "--uuid", uuid]
    rc, stdout, stderr = await run_script(cmd, send=send, verbose=verbose)
    if rc != 0:
        logger.error("devices/config.sh failed: %s", stderr)
        return []
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        logger.error("devices/config.sh returned invalid JSON: %s", stdout)
        return []


# ---------------------------------------------------------------------------
# /devices
# ---------------------------------------------------------------------------

@router.message(Command("devices"))
async def cmd_devices(
    message: Message,
    role: Role,
    registry_user: dict | None,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role not in (Role.USER, Role.ADMIN):
        await message.answer("Доступ ограничен.")
        return

    if registry_user is None:
        await message.answer("Ваш аккаунт не найден в реестре.")
        return

    devices = await _fetch_devices(registry_user["id"], scripts_path, verbose, message.answer)
    if devices is None:
        await message.answer("Не удалось получить список устройств.")
        return

    if not devices:
        await message.answer("У вас нет зарегистрированных устройств.")
        return

    await message.answer(
        f"Ваши устройства: {len(devices)}",
        reply_markup=_kb_devices_list(devices),
    )


# ---------------------------------------------------------------------------
# Карточка устройства
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("mydev:c:"))
async def cb_device_card(
    callback: CallbackQuery,
    role: Role,
    registry_user: dict | None,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role not in (Role.USER, Role.ADMIN) or registry_user is None:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    uuid = callback.data.split(":", 2)[2]

    cmd_get = [f"{scripts_path}/devices/get.sh", "--uuid", uuid]
    rc, stdout, stderr = await run_script(cmd_get, send=callback.message.answer, verbose=verbose)
    if rc != 0:
        await callback.answer("Устройство не найдено.", show_alert=True)
        return

    try:
        device = json.loads(stdout)
    except json.JSONDecodeError:
        await callback.answer("Ошибка при разборе данных.", show_alert=True)
        return

    # Проверяем что устройство принадлежит текущему пользователю
    if device.get("user_id") != registry_user["id"]:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    links = await _fetch_config(uuid, scripts_path, verbose, callback.message.answer)

    await callback.message.edit_text(
        _format_device_card(device, links),
        reply_markup=_kb_device_card(links),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Назад к списку
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "mydev:back")
async def cb_devices_back(
    callback: CallbackQuery,
    role: Role,
    registry_user: dict | None,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role not in (Role.USER, Role.ADMIN) or registry_user is None:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    devices = await _fetch_devices(registry_user["id"], scripts_path, verbose, callback.message.answer)
    if devices is None:
        await callback.answer("Ошибка при получении списка.", show_alert=True)
        return

    await callback.message.edit_text(
        f"Ваши устройства: {len(devices)}",
        reply_markup=_kb_devices_list(devices),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Заглушки
# ---------------------------------------------------------------------------

@router.message(Command("add_device"))
async def cmd_add_device(message: Message, role: Role) -> None:
    if role in (Role.USER, Role.ADMIN):
        await message.answer("Здесь будет добавление устройства.")
    else:
        await message.answer("Доступ ограничен.")


@router.message(Command("remove_device"))
async def cmd_remove_device(message: Message, role: Role) -> None:
    if role in (Role.USER, Role.ADMIN):
        await message.answer("Здесь будет удаление устройства.")
    else:
        await message.answer("Доступ ограничен.")
