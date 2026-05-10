import asyncio
import json
import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter, or_f
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.crypto import hash_telegram_id
from bot.roles import Role
from bot.runner import run_script

logger = logging.getLogger(__name__)

_MAINTENANCE = (
    "⏳ Эта функция временно недоступна — идёт техническое обслуживание сети.\n"
    "Мы сообщим, когда всё будет готово."
)

router = Router()


class RegStates(StatesGroup):
    waiting_username = State()
    waiting_email = State()
    confirm = State()


def _kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="reg:cancel")],
    ])


def _kb_email() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Пропустить", callback_data="reg:skip_email"),
            InlineKeyboardButton(text="Отмена", callback_data="reg:cancel"),
        ],
    ])


def _kb_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отправить заявку", callback_data="reg:submit")],
        [InlineKeyboardButton(text="Отмена", callback_data="reg:cancel")],
    ])


def _is_username_unique(username: str, store_path: str) -> bool:
    users_dir = Path(store_path) / "users"
    if not users_dir.is_dir():
        return True
    for file in users_dir.glob("*.json"):
        try:
            data = json.loads(file.read_text())
            if data.get("username", "").lower() == username.lower():
                return False
        except (json.JSONDecodeError, OSError):
            pass
    return True


def _is_telegram_id_unique(telegram_id: int, store_path: str) -> bool:
    users_dir = Path(store_path) / "users"
    if not users_dir.is_dir():
        return True
    tg_hash = hash_telegram_id(telegram_id)
    for file in users_dir.glob("*.json"):
        try:
            data = json.loads(file.read_text())
            if data.get("hash_telegram_id") == tg_hash:
                return False
        except (json.JSONDecodeError, OSError):
            pass
    return True


def _confirm_text(username: str, email: str | None) -> str:
    email_line = f"Email: {email}" if email else "Email: не указан"
    return (
        "Проверьте данные перед отправкой:\n\n"
        f"Никнейм: {username}\n"
        f"{email_line}\n\n"
        "Всё верно?"
    )


# ---------------------------------------------------------------------------
# /reg — точка входа
# ---------------------------------------------------------------------------

@router.message(or_f(Command("reg"), F.text == "📝 Зарегистрироваться"), StateFilter(None))
async def cmd_reg(message: Message) -> None:
    await message.answer(_MAINTENANCE)


# ---------------------------------------------------------------------------
# Шаг 1: никнейм
# ---------------------------------------------------------------------------

@router.message(RegStates.waiting_username)
async def reg_username(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(_MAINTENANCE)


# ---------------------------------------------------------------------------
# Шаг 2: email — ввод текстом
# ---------------------------------------------------------------------------

@router.message(RegStates.waiting_email)
async def reg_email(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(_MAINTENANCE)


# ---------------------------------------------------------------------------
# Шаг 2: email — кнопка «Пропустить»
# ---------------------------------------------------------------------------

@router.callback_query(RegStates.waiting_email, F.data == "reg:skip_email")
async def reg_skip_email(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer(_MAINTENANCE, show_alert=True)


# ---------------------------------------------------------------------------
# Шаг 3: подтверждение и отправка
# ---------------------------------------------------------------------------

@router.callback_query(RegStates.confirm, F.data == "reg:submit")
async def reg_submit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer(_MAINTENANCE, show_alert=True)


# ---------------------------------------------------------------------------
# Отмена из любого состояния регистрации
# ---------------------------------------------------------------------------

@router.callback_query(StateFilter(RegStates), F.data == "reg:cancel")
async def reg_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Регистрация отменена.")
    await callback.answer()
