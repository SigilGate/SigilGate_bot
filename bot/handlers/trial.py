import asyncio
import io
import json
import logging
import re
import time
from pathlib import Path

import qrcode
from aiogram import Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.roles import Role
from bot.runner import run_script

logger = logging.getLogger(__name__)

router = Router()

# ID сервисного пользователя trial в реестре
TRIAL_USER_ID = "3"

# Начальное значение лимита для первого использования (9 означает: ещё 9 попыток после этой)
TRIAL_LIMIT_START = 9

# Время жизни одного триал-подключения в секундах
TRIAL_TTL = 3600

# Паттерн для извлечения UUID из вывода devices/add.sh
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _get_device_mtime(store_path: str, uuid: str) -> float | None:
    """Возвращает mtime файла устройства (unix timestamp) или None."""
    path = Path(store_path) / "devices" / f"{uuid}.json"
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _make_qr_photo(link: str) -> BufferedInputFile | None:
    """Генерирует QR-код для VLESS-ссылки. Возвращает BufferedInputFile или None при ошибке."""
    try:
        img = qrcode.make(link)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return BufferedInputFile(buf.read(), filename="qr.png")
    except Exception:
        logger.exception("Failed to generate QR code")
        return None


def _make_result_keyboard(link: str) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой копирования VLESS-ссылки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Скопировать ссылку", copy_text=CopyTextButton(text=link))]
        ]
    )


def _result_text(link: str, remaining: int) -> str:
    """Формирует текст результата с приветствием, ссылкой и счётчиком лимита."""
    return (
        "🌐 Сеть <b>Sigil Gate</b> — доступ открыт\n"
        "Добро пожаловать!\n"
        "\n"
        f"Ссылка действует <b>1 час</b>.\n"
        f"Лимит подключений: <b>{remaining}</b>\n"
        "\n"
        f"<code>{link}</code>"
    )


@router.message(Command("trial"))
async def cmd_trial(
    message: Message,
    role: Role,
    scripts_path: str,
    store_path: str,
    verbose: bool,
) -> None:
    # Доступно: GUEST (незарегистрированные) и ADMIN (для тестирования)
    # USER (активные пользователи) не нуждаются в триале
    if role == Role.USER:
        await message.answer(
            "Вы уже зарегистрированы в системе.\n"
            "Используйте /devices для управления подключениями."
        )
        return

    processing_msg = await message.answer("⏳ Ваш запрос на подключение обрабатывается...")
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    telegram_id = message.from_user.id

    # --- Шаг 1: получаем все триал-устройства пользователя ---

    rc, stdout, stderr = await run_script(
        [f"{scripts_path}/trial/find.sh", "--telegram-id", str(telegram_id)],
    )
    if rc != 0:
        logger.error("trial/find.sh failed: %s", stderr)
        await processing_msg.edit_text(
            "Не удалось проверить статус пробного доступа. Попробуйте позже."
        )
        return

    try:
        devices = json.loads(stdout)
    except json.JSONDecodeError:
        logger.error("trial/find.sh returned invalid JSON: %s", stdout)
        devices = []

    # --- Шаг 2: ленивая очистка истёкших активных устройств ---

    now = time.time()
    for dev in devices:
        if dev.get("status") == "active":
            mtime = _get_device_mtime(store_path, dev["uuid"])
            if mtime is not None and (now - mtime) >= TRIAL_TTL:
                logger.info("Lazy expire: trial device %s (age=%.0fs)", dev["uuid"], now - mtime)
                # Запускаем в фоне, не блокируем пользователя
                asyncio.create_task(
                    run_script([f"{scripts_path}/trial/expire.sh", "--uuid", dev["uuid"]])
                )

    # --- Шаг 3: определяем оставшийся лимит ---

    digits = []
    for dev in devices:
        name = dev.get("device", "")
        if name and name[-1].isdigit():
            digits.append(int(name[-1]))

    if digits:
        min_digit = min(digits)
        if min_digit == 0:
            await processing_msg.edit_text(
                "<b>Лимит пробных подключений исчерпан.</b>\n\n"
                "Вы использовали все доступные пробные подключения.\n"
                "Для получения постоянного доступа пройдите регистрацию: /reg",
                parse_mode="HTML",
            )
            return
        new_digit = min_digit - 1
    else:
        # Первое использование
        new_digit = TRIAL_LIMIT_START

    # --- Шаг 4: создаём новое триал-устройство ---

    device_name = f"{telegram_id}{new_digit}"

    rc, stdout, stderr = await run_script(
        [
            f"{scripts_path}/devices/add.sh",
            "--user", TRIAL_USER_ID,
            "--device", device_name,
        ],
        send=message.answer if verbose else None,
        verbose=verbose,
    )
    if rc != 0:
        logger.error("devices/add.sh failed for trial device %s: %s", device_name, stderr)
        await processing_msg.edit_text(
            "Не удалось создать пробное подключение. Попробуйте позже."
        )
        return

    # --- Шаг 5: извлекаем UUID из вывода ---

    uuid_match = _UUID_RE.search(stdout)
    if not uuid_match:
        logger.error("Could not extract UUID from devices/add.sh output: %s", stdout)
        await processing_msg.edit_text(
            "Не удалось получить параметры подключения. Обратитесь к администратору."
        )
        return

    uuid = uuid_match.group(0)

    # --- Шаг 6: получаем VLESS-ссылки ---

    rc, links_json, stderr = await run_script(
        [f"{scripts_path}/devices/config.sh", "--uuid", uuid],
    )
    if rc != 0:
        logger.error("devices/config.sh failed for uuid %s: %s", uuid, stderr)
        await processing_msg.edit_text(
            "Подключение создано, но не удалось сформировать ссылку. Обратитесь к администратору."
        )
        return

    try:
        links = json.loads(links_json)
    except json.JSONDecodeError:
        logger.error("devices/config.sh returned invalid JSON: %s", links_json)
        links = []

    if not links:
        await processing_msg.edit_text(
            "Подключение создано, но маршрут не найден. Обратитесь к администратору."
        )
        return

    # --- Шаг 7: отправляем результат ---

    link = links[0]
    remaining_after = new_digit  # сколько попыток останется после этой

    await processing_msg.delete()

    qr_photo = _make_qr_photo(link)
    if qr_photo:
        await message.answer_photo(qr_photo)

    await message.answer(
        _result_text(link, remaining_after),
        parse_mode="HTML",
        reply_markup=_make_result_keyboard(link),
    )
