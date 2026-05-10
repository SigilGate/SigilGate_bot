import io
import json
import logging

from PIL import Image
from aiogram import F, Router
from aiogram.filters import Command, StateFilter, or_f
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from bot.qr import make_qr_photo
from bot.roles import Role
from bot.runner import run_script

logger = logging.getLogger(__name__)

_MAINTENANCE = (
    "⏳ Эта функция временно недоступна — идёт техническое обслуживание сети.\n"
    "Мы сообщим, когда всё будет готово."
)

router = Router()


# ---------------------------------------------------------------------------
# FSM
# ---------------------------------------------------------------------------

class AddDeviceStates(StatesGroup):
    waiting_name = State()


class RenameDeviceStates(StatesGroup):
    waiting_new_name = State()


class ActivateDeviceStates(StatesGroup):
    waiting_entry_node = State()


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def _kb_devices_list(devices: list[dict], show_appeals: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=d["device"], callback_data=f"mydev:c:{d['uuid']}")]
        for d in devices
    ]
    rows.append([InlineKeyboardButton(text="+ Добавить устройство", callback_data="mydev:add")])
    if show_appeals:
        rows.append([
            InlineKeyboardButton(text="✍ Написать администратору", callback_data="appeal:new"),
            InlineKeyboardButton(text="📋 Мои обращения",          callback_data="appeal:my_list"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_add_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Отмена", callback_data="mydev:add_cancel"),
    ]])


def _kb_device_card(uuid: str, links: list[str], status: str = "") -> InlineKeyboardMarkup:
    rows = []
    if status == "inactive":
        rows.append([InlineKeyboardButton(text="▷ Активировать", callback_data=f"mydev:activate:{uuid}")])
    elif status == "active":
        rows.append([InlineKeyboardButton(text="⏸ Деактивировать", callback_data=f"mydev:deactivate:{uuid}")])
    if status != "archived":
        rows.append([InlineKeyboardButton(text="✏ Переименовать", callback_data=f"mydev:rename:{uuid}")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить устройство",    callback_data=f"mydev:del:{uuid}")])
    rows.append([InlineKeyboardButton(text="⚠ Сообщить о проблеме", callback_data=f"appeal:new:device:{uuid}")])
    for i, link in enumerate(links):
        label = "📋 Скопировать конфигурацию" if len(links) == 1 else f"📋 Конфигурация {i + 1}"
        rows.append([
            InlineKeyboardButton(text=label, copy_text=CopyTextButton(text=link))
        ])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="mydev:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_entry_node_selection(nodes: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for i, node in enumerate(nodes):
        label = node.get("hostname") or node["ip"]
        location = node.get("location", "")
        btn_text = f"{label} ({location})" if location else label
        rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"mydev:actnode:{i}")])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="mydev:actcancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_rename_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Отмена", callback_data="mydev:rename_cancel"),
    ]])


def _kb_delete_confirm(uuid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, удалить", callback_data=f"mydev:delok:{uuid}")],
        [InlineKeyboardButton(text="Отмена",      callback_data=f"mydev:delno:{uuid}")],
    ])


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _list_text(devices: list[dict]) -> str:
    if not devices:
        return "У вас нет зарегистрированных устройств."
    return f"Ваши устройства: {len(devices)}"


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


# ---------------------------------------------------------------------------
# Photo helpers
# ---------------------------------------------------------------------------


def _make_placeholder_photo() -> BufferedInputFile:
    """Заглушка для карточек без активного подключения."""
    img = Image.new("RGB", (200, 200), color=(20, 20, 35))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return BufferedInputFile(buf.read(), filename="card.png")


def _make_card_photo(links: list[str]) -> BufferedInputFile:
    """QR-код для активного устройства, заглушка — для неактивного."""
    if links:
        qr = make_qr_photo(links[0])
        if qr:
            return qr
    return _make_placeholder_photo()


async def _send_device_card(target: Message, device: dict, links: list[str]) -> None:
    """Отправляет новое фото-сообщение с карточкой устройства."""
    text = _format_device_card(device, links)
    kb = _kb_device_card(device["uuid"], links, device.get("status", ""))
    photo = _make_card_photo(links)
    await target.answer_photo(photo, caption=text, reply_markup=kb, parse_mode="HTML")


async def _edit_device_card(callback: CallbackQuery, device: dict, links: list[str]) -> None:
    """Обновляет текущее фото-сообщение карточкой устройства (edit_media)."""
    text = _format_device_card(device, links)
    kb = _kb_device_card(device["uuid"], links, device.get("status", ""))
    photo = _make_card_photo(links)
    await callback.message.edit_media(
        InputMediaPhoto(media=photo, caption=text, parse_mode="HTML"),
        reply_markup=kb,
    )


# ---------------------------------------------------------------------------
# Script helpers
# ---------------------------------------------------------------------------

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

@router.message(or_f(Command("devices"), F.text == "📱 Устройства"))
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

    await message.answer(
        _list_text(devices),
        reply_markup=_kb_devices_list(devices, show_appeals=(role == Role.USER)),
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

    if device.get("user_id") != registry_user["id"]:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    links = await _fetch_config(uuid, scripts_path, verbose, callback.message.answer)

    await callback.message.delete()
    await _send_device_card(callback.message, device, links)
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

    await callback.message.delete()
    await callback.message.answer(
        _list_text(devices),
        reply_markup=_kb_devices_list(devices, show_appeals=(role == Role.USER)),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Добавление устройства — запрос имени
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "mydev:add")
async def cb_add_device_start(callback: CallbackQuery) -> None:
    await callback.answer(_MAINTENANCE, show_alert=True)


# ---------------------------------------------------------------------------
# Добавление устройства — получение имени и запуск скрипта
# ---------------------------------------------------------------------------

@router.message(AddDeviceStates.waiting_name)
async def add_device_name(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(_MAINTENANCE)


# ---------------------------------------------------------------------------
# Отмена добавления
# ---------------------------------------------------------------------------

@router.callback_query(StateFilter(AddDeviceStates), F.data == "mydev:add_cancel")
async def cb_add_cancel(
    callback: CallbackQuery,
    role: Role,
    registry_user: dict | None,
    state: FSMContext,
    scripts_path: str,
    verbose: bool,
) -> None:
    await state.clear()

    if role not in (Role.USER, Role.ADMIN) or registry_user is None:
        await callback.message.edit_text("Отменено.")
        await callback.answer()
        return

    devices = await _fetch_devices(registry_user["id"], scripts_path, verbose, callback.message.answer)
    if devices is None:
        await callback.message.edit_text("Отменено.")
        await callback.answer()
        return

    await callback.message.edit_text(
        _list_text(devices),
        reply_markup=_kb_devices_list(devices, show_appeals=(role == Role.USER)),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Удаление устройства — запрос подтверждения
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("mydev:del:"))
async def cb_device_delete(callback: CallbackQuery) -> None:
    await callback.answer(_MAINTENANCE, show_alert=True)


# ---------------------------------------------------------------------------
# Удаление устройства — подтверждение
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("mydev:delok:"))
async def cb_device_delete_confirm(callback: CallbackQuery) -> None:
    await callback.answer(_MAINTENANCE, show_alert=True)


# ---------------------------------------------------------------------------
# Удаление устройства — отмена (возврат к карточке)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("mydev:delno:"))
async def cb_device_delete_cancel(
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
    rc, stdout, _ = await run_script(cmd_get, verbose=False)
    if rc != 0:
        await callback.answer("Ошибка.", show_alert=True)
        return

    try:
        device = json.loads(stdout)
    except json.JSONDecodeError:
        await callback.answer("Ошибка при разборе данных.", show_alert=True)
        return

    links = await _fetch_config(uuid, scripts_path, verbose, callback.message.answer)

    await _edit_device_card(callback, device, links)
    await callback.answer()


# ---------------------------------------------------------------------------
# Переименование устройства — запрос нового имени
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("mydev:rename:"))
async def cb_device_rename_start(callback: CallbackQuery) -> None:
    await callback.answer(_MAINTENANCE, show_alert=True)


# ---------------------------------------------------------------------------
# Переименование устройства — получение нового имени
# ---------------------------------------------------------------------------

@router.message(RenameDeviceStates.waiting_new_name)
async def rename_device_name(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(_MAINTENANCE)


# ---------------------------------------------------------------------------
# Переименование устройства — отмена
# ---------------------------------------------------------------------------

@router.callback_query(StateFilter(RenameDeviceStates), F.data == "mydev:rename_cancel")
async def cb_rename_cancel(
    callback: CallbackQuery,
    role: Role,
    registry_user: dict | None,
    state: FSMContext,
    scripts_path: str,
    verbose: bool,
) -> None:
    data = await state.get_data()
    uuid = data.get("uuid", "")
    await state.clear()

    if not uuid:
        await callback.message.edit_caption("Отменено.")
        await callback.answer()
        return

    cmd_get = [f"{scripts_path}/devices/get.sh", "--uuid", uuid]
    rc, stdout, _ = await run_script(cmd_get, verbose=False)
    if rc != 0:
        await callback.message.edit_caption("Отменено.")
        await callback.answer()
        return

    try:
        device = json.loads(stdout)
    except json.JSONDecodeError:
        await callback.message.edit_caption("Отменено.")
        await callback.answer()
        return

    links = await _fetch_config(uuid, scripts_path, verbose, callback.message.answer)
    await _edit_device_card(callback, device, links)
    await callback.answer()


# ---------------------------------------------------------------------------
# Активация устройства — показ списка Entry-нод
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("mydev:activate:"))
async def cb_device_activate_start(callback: CallbackQuery) -> None:
    await callback.answer(_MAINTENANCE, show_alert=True)


# ---------------------------------------------------------------------------
# Активация устройства — выбор Entry-ноды
# ---------------------------------------------------------------------------

@router.callback_query(ActivateDeviceStates.waiting_entry_node, F.data.startswith("mydev:actnode:"))
async def cb_device_activate_node(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer(_MAINTENANCE, show_alert=True)


# ---------------------------------------------------------------------------
# Активация устройства — отмена
# ---------------------------------------------------------------------------

@router.callback_query(ActivateDeviceStates.waiting_entry_node, F.data == "mydev:actcancel")
async def cb_device_activate_cancel(
    callback: CallbackQuery,
    role: Role,
    registry_user: dict | None,
    state: FSMContext,
    scripts_path: str,
    verbose: bool,
) -> None:
    data = await state.get_data()
    uuid = data.get("uuid", "")
    await state.clear()

    if not uuid:
        await callback.message.edit_caption("Отменено.")
        await callback.answer()
        return

    cmd_get = [f"{scripts_path}/devices/get.sh", "--uuid", uuid]
    rc, stdout, _ = await run_script(cmd_get, verbose=False)
    if rc != 0:
        await callback.message.edit_caption("Отменено.")
        await callback.answer()
        return

    try:
        device = json.loads(stdout)
    except json.JSONDecodeError:
        await callback.message.edit_caption("Отменено.")
        await callback.answer()
        return

    links = await _fetch_config(uuid, scripts_path, verbose, callback.message.answer)
    await _edit_device_card(callback, device, links)
    await callback.answer()


# ---------------------------------------------------------------------------
# Деактивация устройства
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("mydev:deactivate:"))
async def cb_device_deactivate(callback: CallbackQuery) -> None:
    await callback.answer(_MAINTENANCE, show_alert=True)
