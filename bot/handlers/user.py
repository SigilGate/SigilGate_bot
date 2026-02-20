import json
import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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

def _kb_devices_list(devices: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=d["device"], callback_data=f"mydev:c:{d['uuid']}")]
        for d in devices
    ]
    rows.append([InlineKeyboardButton(text="+ Добавить устройство", callback_data="mydev:add")])
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
    rows.append([InlineKeyboardButton(text="🗑 Удалить устройство", callback_data=f"mydev:del:{uuid}")])
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

    await message.answer(
        _list_text(devices),
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

    if device.get("user_id") != registry_user["id"]:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    links = await _fetch_config(uuid, scripts_path, verbose, callback.message.answer)

    await callback.message.edit_text(
        _format_device_card(device, links),
        reply_markup=_kb_device_card(uuid, links, device.get("status", "")),
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
        _list_text(devices),
        reply_markup=_kb_devices_list(devices),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Добавление устройства — запрос имени
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "mydev:add")
async def cb_add_device_start(
    callback: CallbackQuery,
    role: Role,
    registry_user: dict | None,
    state: FSMContext,
) -> None:
    if role not in (Role.USER, Role.ADMIN) or registry_user is None:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    await state.set_state(AddDeviceStates.waiting_name)
    await callback.message.edit_text(
        "Введите название нового устройства:",
        reply_markup=_kb_add_cancel(),
    )
    await callback.answer()


@router.message(Command("add_device"))
async def cmd_add_device(
    message: Message,
    role: Role,
    registry_user: dict | None,
    state: FSMContext,
) -> None:
    if role not in (Role.USER, Role.ADMIN):
        await message.answer("Доступ ограничен.")
        return

    if registry_user is None:
        await message.answer("Ваш аккаунт не найден в реестре.")
        return

    await state.set_state(AddDeviceStates.waiting_name)
    await message.answer(
        "Введите название нового устройства:",
        reply_markup=_kb_add_cancel(),
    )


# ---------------------------------------------------------------------------
# Добавление устройства — получение имени и запуск скрипта
# ---------------------------------------------------------------------------

@router.message(AddDeviceStates.waiting_name)
async def add_device_name(
    message: Message,
    role: Role,
    registry_user: dict | None,
    state: FSMContext,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role not in (Role.USER, Role.ADMIN) or registry_user is None:
        await state.clear()
        await message.answer("Доступ ограничен.")
        return

    device_name = (message.text or "").strip()

    if not device_name:
        await message.answer(
            "Название не может быть пустым. Попробуйте ещё раз:",
            reply_markup=_kb_add_cancel(),
        )
        return

    if len(device_name) > 64:
        await message.answer(
            "Название слишком длинное (максимум 64 символа). Попробуйте ещё раз:",
            reply_markup=_kb_add_cancel(),
        )
        return

    await state.clear()

    cmd = [
        f"{scripts_path}/devices/add.sh",
        "--user", str(registry_user["id"]),
        "--device", device_name,
    ]
    rc, stdout, stderr = await run_script(cmd, send=message.answer, verbose=verbose)

    if rc != 0:
        logger.error("devices/add.sh failed: %s", stderr)
        await message.answer("Не удалось добавить устройство. Попробуйте позже.")
        return

    await message.answer(f"Устройство <b>{device_name}</b> успешно добавлено.", parse_mode="HTML")

    devices = await _fetch_devices(registry_user["id"], scripts_path, verbose, message.answer)
    if devices is not None:
        await message.answer(
            _list_text(devices),
            reply_markup=_kb_devices_list(devices),
        )


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
        reply_markup=_kb_devices_list(devices),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Удаление устройства — запрос подтверждения
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("mydev:del:"))
async def cb_device_delete(
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
    if rc != 0 or not stdout:
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

    await callback.message.edit_text(
        f"Удалить устройство <b>{device['device']}</b>?\n\nЭто действие необратимо.",
        reply_markup=_kb_delete_confirm(uuid),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Удаление устройства — подтверждение
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("mydev:delok:"))
async def cb_device_delete_confirm(
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

    cmd = [f"{scripts_path}/devices/remove.sh", "--uuid", uuid]
    rc, stdout, stderr = await run_script(cmd, send=callback.message.answer, verbose=verbose)

    if rc != 0:
        logger.error("devices/remove.sh failed: %s", stderr)
        await callback.message.edit_text("Не удалось удалить устройство. Попробуйте позже.")
        await callback.answer()
        return

    devices = await _fetch_devices(registry_user["id"], scripts_path, verbose, callback.message.answer)
    if devices is not None:
        await callback.message.edit_text(
            _list_text(devices),
            reply_markup=_kb_devices_list(devices),
        )
    else:
        await callback.message.edit_text("Устройство удалено.")

    await callback.answer()


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

    await callback.message.edit_text(
        _format_device_card(device, links),
        reply_markup=_kb_device_card(uuid, links, device.get("status", "")),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Переименование устройства — запрос нового имени
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("mydev:rename:"))
async def cb_device_rename_start(
    callback: CallbackQuery,
    role: Role,
    registry_user: dict | None,
    state: FSMContext,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role not in (Role.USER, Role.ADMIN) or registry_user is None:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    uuid = callback.data.split(":", 2)[2]

    cmd_get = [f"{scripts_path}/devices/get.sh", "--uuid", uuid]
    rc, stdout, _ = await run_script(cmd_get, verbose=False)
    if rc != 0 or not stdout:
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

    await state.set_state(RenameDeviceStates.waiting_new_name)
    await state.update_data(uuid=uuid)

    await callback.message.edit_text(
        f"Введите новое название для устройства <b>{device['device']}</b>:",
        reply_markup=_kb_rename_cancel(),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Переименование устройства — получение нового имени
# ---------------------------------------------------------------------------

@router.message(RenameDeviceStates.waiting_new_name)
async def rename_device_name(
    message: Message,
    role: Role,
    registry_user: dict | None,
    state: FSMContext,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role not in (Role.USER, Role.ADMIN) or registry_user is None:
        await state.clear()
        await message.answer("Доступ ограничен.")
        return

    new_name = (message.text or "").strip()

    if not new_name:
        await message.answer(
            "Название не может быть пустым. Попробуйте ещё раз:",
            reply_markup=_kb_rename_cancel(),
        )
        return

    if len(new_name) > 64:
        await message.answer(
            "Название слишком длинное (максимум 64 символа). Попробуйте ещё раз:",
            reply_markup=_kb_rename_cancel(),
        )
        return

    data = await state.get_data()
    uuid = data["uuid"]
    await state.clear()

    cmd = [f"{scripts_path}/devices/update.sh", "--uuid", uuid, "--device", new_name]
    rc, _, stderr = await run_script(cmd, send=message.answer, verbose=verbose)

    if rc != 0:
        logger.error("devices/update.sh failed: %s", stderr)
        await message.answer("Не удалось переименовать устройство. Попробуйте позже.")
        return

    await message.answer(
        f"Устройство переименовано в <b>{new_name}</b>.",
        parse_mode="HTML",
    )

    cmd_get = [f"{scripts_path}/devices/get.sh", "--uuid", uuid]
    rc, stdout, _ = await run_script(cmd_get, verbose=False)
    if rc == 0:
        try:
            device = json.loads(stdout)
            links = await _fetch_config(uuid, scripts_path, verbose, message.answer)
            await message.answer(
                _format_device_card(device, links),
                reply_markup=_kb_device_card(uuid, links, device.get("status", "")),
                parse_mode="HTML",
            )
        except json.JSONDecodeError:
            pass


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
        await callback.message.edit_text("Отменено.")
        await callback.answer()
        return

    cmd_get = [f"{scripts_path}/devices/get.sh", "--uuid", uuid]
    rc, stdout, _ = await run_script(cmd_get, verbose=False)
    if rc != 0:
        await callback.message.edit_text("Отменено.")
        await callback.answer()
        return

    try:
        device = json.loads(stdout)
    except json.JSONDecodeError:
        await callback.message.edit_text("Отменено.")
        await callback.answer()
        return

    links = await _fetch_config(uuid, scripts_path, verbose, callback.message.answer)
    await callback.message.edit_text(
        _format_device_card(device, links),
        reply_markup=_kb_device_card(uuid, links, device.get("status", "")),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Активация устройства — показ списка Entry-нод
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("mydev:activate:"))
async def cb_device_activate_start(
    callback: CallbackQuery,
    role: Role,
    registry_user: dict | None,
    state: FSMContext,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role not in (Role.USER, Role.ADMIN) or registry_user is None:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    uuid = callback.data.split(":", 2)[2]

    cmd_get = [f"{scripts_path}/devices/get.sh", "--uuid", uuid]
    rc, stdout, _ = await run_script(cmd_get, verbose=False)
    if rc != 0 or not stdout:
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

    if device.get("status") != "inactive":
        await callback.answer("Устройство уже активно или архивировано.", show_alert=True)
        return

    rc, stdout, stderr = await run_script(
        [f"{scripts_path}/nodes/list-entry.sh", "--user", str(registry_user["id"])],
        send=callback.message.answer, verbose=verbose,
    )
    if rc != 0:
        logger.error("nodes/list-entry.sh failed: %s", stderr)
        await callback.answer("Не удалось получить список Entry-нод.", show_alert=True)
        return

    try:
        nodes = json.loads(stdout)
    except json.JSONDecodeError:
        logger.error("nodes/list-entry.sh returned invalid JSON: %s", stdout)
        await callback.answer("Ошибка при получении списка нод.", show_alert=True)
        return

    if not nodes:
        await callback.answer("Нет доступных Entry-нод. Обратитесь к администратору.", show_alert=True)
        return

    await state.set_state(ActivateDeviceStates.waiting_entry_node)
    await state.update_data(uuid=uuid, device_name=device["device"], nodes=nodes)

    await callback.message.edit_text(
        f"Выберите Entry-ноду для активации устройства <b>{device['device']}</b>:",
        reply_markup=_kb_entry_node_selection(nodes),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Активация устройства — выбор Entry-ноды
# ---------------------------------------------------------------------------

@router.callback_query(ActivateDeviceStates.waiting_entry_node, F.data.startswith("mydev:actnode:"))
async def cb_device_activate_node(
    callback: CallbackQuery,
    role: Role,
    registry_user: dict | None,
    state: FSMContext,
    scripts_path: str,
    verbose: bool,
) -> None:
    if role not in (Role.USER, Role.ADMIN) or registry_user is None:
        await state.clear()
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    index = int(callback.data.split(":")[2])
    data = await state.get_data()
    uuid = data["uuid"]
    device_name = data["device_name"]
    nodes = data["nodes"]

    if index >= len(nodes):
        await callback.answer("Ошибка: нода не найдена.", show_alert=True)
        return

    node = nodes[index]
    await state.clear()

    rc, _, stderr = await run_script(
        [
            f"{scripts_path}/entry/add-client.sh",
            "--host", node["ip"],
            "--uuid", uuid,
            "--service-name", node["service_name"],
            "--name", device_name,
        ],
        send=callback.message.answer, verbose=verbose,
    )
    if rc != 0:
        logger.error("entry/add-client.sh failed: %s", stderr)
        await callback.answer("Ошибка при активации устройства на ноде.", show_alert=True)
        return

    rc, _, stderr = await run_script(
        [f"{scripts_path}/devices/update.sh", "--uuid", uuid, "--status", "active"],
        send=callback.message.answer, verbose=verbose,
    )
    if rc != 0:
        logger.error("devices/update.sh --status active failed: %s", stderr)
        await callback.answer("Устройство добавлено на ноду, но статус не обновлён.", show_alert=True)
        return

    cmd_get = [f"{scripts_path}/devices/get.sh", "--uuid", uuid]
    rc, stdout, _ = await run_script(cmd_get, verbose=False)
    if rc == 0:
        try:
            device = json.loads(stdout)
            links = await _fetch_config(uuid, scripts_path, verbose, callback.message.answer)
            await callback.message.edit_text(
                _format_device_card(device, links),
                reply_markup=_kb_device_card(uuid, links, device.get("status", "")),
                parse_mode="HTML",
            )
        except json.JSONDecodeError:
            await callback.message.edit_text("Устройство активировано.")
    else:
        await callback.message.edit_text("Устройство активировано.")

    await callback.answer()


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
        await callback.message.edit_text("Отменено.")
        await callback.answer()
        return

    cmd_get = [f"{scripts_path}/devices/get.sh", "--uuid", uuid]
    rc, stdout, _ = await run_script(cmd_get, verbose=False)
    if rc != 0:
        await callback.message.edit_text("Отменено.")
        await callback.answer()
        return

    try:
        device = json.loads(stdout)
    except json.JSONDecodeError:
        await callback.message.edit_text("Отменено.")
        await callback.answer()
        return

    links = await _fetch_config(uuid, scripts_path, verbose, callback.message.answer)
    await callback.message.edit_text(
        _format_device_card(device, links),
        reply_markup=_kb_device_card(uuid, links, device.get("status", "")),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Деактивация устройства
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("mydev:deactivate:"))
async def cb_device_deactivate(
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
    if rc != 0 or not stdout:
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

    rc, _, stderr = await run_script(
        [f"{scripts_path}/devices/deactivate.sh", "--uuid", uuid],
        send=callback.message.answer, verbose=verbose,
    )
    if rc != 0:
        logger.error("devices/deactivate.sh failed: %s", stderr)
        await callback.answer("Ошибка при деактивации устройства.", show_alert=True)
        return

    cmd_get = [f"{scripts_path}/devices/get.sh", "--uuid", uuid]
    rc, stdout, _ = await run_script(cmd_get, verbose=False)
    if rc == 0:
        try:
            device = json.loads(stdout)
            links = await _fetch_config(uuid, scripts_path, verbose, callback.message.answer)
            await callback.message.edit_text(
                _format_device_card(device, links),
                reply_markup=_kb_device_card(uuid, links, device.get("status", "")),
                parse_mode="HTML",
            )
        except json.JSONDecodeError:
            await callback.message.edit_text("Устройство деактивировано.")
    else:
        await callback.message.edit_text("Устройство деактивировано.")

    await callback.answer()


# ---------------------------------------------------------------------------
# /remove_device — заглушка
# ---------------------------------------------------------------------------

@router.message(Command("remove_device"))
async def cmd_remove_device(message: Message, role: Role) -> None:
    if role in (Role.USER, Role.ADMIN):
        await message.answer("Здесь будет удаление устройства.")
    else:
        await message.answer("Доступ ограничен.")
