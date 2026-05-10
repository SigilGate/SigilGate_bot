import asyncio
import json
import logging
import re
import time
from pathlib import Path

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, or_f
from aiogram.types import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.crypto import hash_telegram_id
from bot.qr import make_qr_photo
from bot.roles import Role
from bot.runner import run_script

logger = logging.getLogger(__name__)

_MAINTENANCE = (
    "⏳ Эта функция временно недоступна — идёт техническое обслуживание сети.\n"
    "Мы сообщим, когда всё будет готово."
)

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
        f"Ссылка действует: <b>1 час</b>\n"
        f"Лимит подключений: <b>{remaining}</b>\n"
        "\n"
        f"<code>{link}</code>"
    )


@router.message(or_f(Command("trial"), F.text == "🚀 Пробный доступ (без регистрации)"))
async def cmd_trial(message: Message) -> None:
    await message.answer(_MAINTENANCE)
